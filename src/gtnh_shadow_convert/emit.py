"""Write a solved plan as gtnh-factory-flow plan JSON, the shape gtnh-process-line-solver's adapter
reads (its ``adapter/plan.py``)::

    {"schemaVersion": 1, "name": ...,
     "converter": {name, version, shadowCommit, dataVersion, dataSha256, packVersion},
     "recipes": [...],   one per recipe row: base figures, I/O, the controller block, ONE runtime
                         variant (the figures this row runs at), ONE machine handler
     "nodes":   [...],   one per recipe row: whole machine count, parallels, tier, coil, casings
     "storages": [...],  a feed per good the plan takes in, a drain per good it puts out
     "edges":   [...]}   maker x user for every good linked in a group, and the storages' pipes

**How the adapter reads the figures**, and so how they are split here. Per machine, it draws
``variant.eut x variant.parallel x node.parallel`` EU/t and moves ``amount x node.parallel /
duration`` per tick of each good. So the variant carries one parallel's EU/t and the batch duration
after overclocks, the speed bonus and rounding, with ``parallel: 1``; the node carries the parallels.
A parallel count is always whole; a fractional speed is folded into the duration.

**Every row is a node of its own**, with a recipe of its own, since two rows of one recipe can run
at different tiers. A row the solved plan runs zero times is left out, with a warning.

**What the converter cannot place it refuses** (:class:`~.errors.UnsupportedRecipeError`): a recipe
with no machine time (a crafting-table recipe), or a recipe type with no machine at all.
"""

from __future__ import annotations

import hashlib
import math
import warnings
from dataclasses import dataclass
from fractions import Fraction
from importlib import metadata
from pathlib import Path
from typing import Any

from ._pins import SHADOW_COMMIT
from .databin import Fluid, Item, OreDict, Repository
from .errors import ConversionError, ConversionWarning, UnsupportedRecipeError
from .fetch import KNOWN_DATA
from .goods import Resource, check_unique, goods_resource, item_resource, oredict_pick
from .machines import ChoiceKind, chemical_plant
from .page import load_page
from .solve import TIER_NAMES, Flow, SolvedPage, SolvedRecipe, solve

NAME = "gtnh-shadow-convert"
#: The adapter refuses more machines than this in one node (``plan.MAX_MACHINE_COUNT``).
MAX_MACHINE_COUNT = 1000

#: Option keys as the arodoid fork of gtnh-factory-flow spells them, so a plan from either reads
#: the same. Indexed by the calculator's choice value.
HEATING_COILS = (
    "cupronickel",
    "kanthal",
    "nichrome",
    "tpv",
    "hss_g",
    "hss_s",
    "naquadah",
    "naquadah_alloy",
    "trinium",
    "electrum_flux",
    "awakened_draconium",
    "infinity",
    "hypogen",
    "eternal",
)
FLUID_PIPE_CASINGS = ("bronze", "steel", "titanium", "tungstensteel")
ITEM_PIPE_CASINGS = (
    "tin",
    "brass",
    "electrum",
    "platinum",
    "osmium",
    "quantium",
    "fluxed-electrum",
    "black-plutonium",
)
COKE_OVEN_CASINGS = ("heat_resistant", "heat_proof")

#: ``machineConfigTiers`` keys, by the calculator choice they come from.
_CONFIG_KEYS = {
    ChoiceKind.FLUID_PIPE_CASING: ("pipeCasing", FLUID_PIPE_CASINGS),
    ChoiceKind.ITEM_PIPE_CASING: ("itemPipeCasing", ITEM_PIPE_CASINGS),
    ChoiceKind.COKE_OVEN_CASING: ("cokeOvenCasing", COKE_OVEN_CASINGS),
}


@dataclass(frozen=True)
class DataInfo:
    """Which ``data.bin`` a plan was solved against, for the plan's ``converter`` block."""

    sha256: str
    data_version: int
    pack_version: str


def version() -> str:
    try:
        return metadata.version(NAME)
    except metadata.PackageNotFoundError:  # pragma: no cover - only when run from a bare checkout
        return "0+unknown"


def convert(
    plan_path: str | Path, data_path: str | Path, *, pack_version: str | None = None
) -> dict[str, Any]:
    """Read a ``.gtnh`` plan, solve it against ``data.bin`` and return gtnh-factory-flow plan JSON.

    ``pack_version`` names the GTNH pack the ``data.bin`` came from; it is needed only for a file
    :data:`~.fetch.KNOWN_DATA` does not know.
    """
    raw = Path(data_path).read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if pack_version is None:
        known = KNOWN_DATA.get(sha256)
        if known is None:
            raise ConversionError(
                f"{data_path} is not a data.bin this converter knows (sha256 {sha256}), so the pack "
                f"it came from is unknown; name it with --pack-version"
            )
        pack_version = known.pack_version
    repo = Repository.from_bytes(raw)
    solved = solve(load_page(plan_path), repo)
    return emit(solved, repo, DataInfo(sha256, repo.data_version, pack_version))


def emit(solved: SolvedPage, repo: Repository, data: DataInfo) -> dict[str, Any]:
    """The plan JSON for an already solved page. See the module docstring."""
    return _Emitter(solved, repo, data).plan()


def _number(value: Fraction) -> int | float:
    return value.numerator if value.denominator == 1 else float(value)


def _row_label(row: SolvedRecipe) -> str:
    return f"recipe row {list(row.element.path)} ({row.recipe.id})"


class _Emitter:
    def __init__(self, solved: SolvedPage, repo: Repository, data: DataInfo) -> None:
        self.solved = solved
        self.repo = repo
        self.data = data
        self.rows = [row for row in solved.recipes if row.runs_per_minute > 0]
        for row in solved.recipes:
            if row.runs_per_minute <= 0:
                warnings.warn(
                    f"{_row_label(row)} runs no times a minute in the solved plan, so it is left out",
                    ConversionWarning,
                    stacklevel=4,
                )
        self.kept = {id(row) for row in self.rows}
        #: The item each ore-dict input of a row was LINKED to, which a later group's pick (an
        #: app quirk) must not override: the edge names this one.
        self.linked_oredicts: dict[tuple[int, str], str] = {
            (id(row), key): link.goods_id
            for link in solved.links
            for row, key in link.consumers
            if key.startswith("o:")
        }
        self.pairs: list[tuple[str, Resource]] = []
        self.storages: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.edge_keys: set[tuple[str, str, str, str]] = set()

    # -- goods ------------------------------------------------------------------------------------

    def resource(self, goods_id: str) -> Resource:
        """A linked or external good, by calculator id (never an ore dict)."""
        goods = self.repo.goods(goods_id)
        if goods is None or isinstance(goods, OreDict):
            raise ConversionError(f"{goods_id!r} is not an item or fluid in this data.bin")
        resource = goods_resource(self.repo, goods)
        self.pairs.append((goods_id, resource))
        return resource

    def input_resource(self, row: SolvedRecipe, goods: Item | Fluid | OreDict | None) -> Resource:
        """What a row's input is named: an ore dict resolves to the item it was linked to, else the
        item the calculator picked for it, else :func:`~.goods.oredict_pick`."""
        if goods is None:
            raise ConversionError("a recipe uses a good this data.bin does not have")
        if not isinstance(goods, OreDict):
            resource = goods_resource(self.repo, goods)
            self.pairs.append((goods.id, resource))
            return resource
        linked = self.linked_oredicts.get((id(row), goods.id))
        if linked is not None:
            return self.resource(linked)
        picked = row.selected_oredicts.get(goods.id)
        resource = item_resource(picked) if picked is not None else oredict_pick(self.repo, goods)
        self.pairs.append((goods.id, resource))
        return resource

    def slot(self, row: SolvedRecipe, flow: Flow) -> dict[str, Any]:
        resource = self.input_resource(row, flow.goods)
        entry: dict[str, Any] = {
            "kind": resource.kind,
            "id": resource.id,
            "amount": _number(flow.amount),
            "displayName": resource.display_name,
        }
        if flow.output:
            if flow.probability != 1:
                entry["chance"] = _number(flow.probability)
        elif flow.expected == 0:
            # Not used up (a programmed circuit, a mold): one in the machine, as arodoid emits it.
            entry["amount"] = 1
            entry["consumed"] = False
        return entry

    # -- machines ---------------------------------------------------------------------------------

    def block(self, row: SolvedRecipe) -> tuple[Item, str]:
        """The block that runs a row, and whether it is a ``single`` block or a ``multiblock``."""
        crafter = row.crafter
        if crafter is None:
            block = row.single_block
            if block is None:
                raise UnsupportedRecipeError(
                    f"{_row_label(row)} is a {row.recipe.recipe_type.name!r} recipe, and the data "
                    f"has no machine for that type at {TIER_NAMES[row.voltage_tier]}"
                )
            return block, "single"
        if crafter.single_block_tier is not None:
            return self.tiered_block(row, crafter), "single"
        if row.machine is not None and row.machine.single_block:
            return crafter, "single"
        return crafter, "multiblock"

    def tiered_block(self, row: SolvedRecipe, crafter: Item) -> Item:
        """The single block of the row's tier. The calculator names the type's first listed block
        (the LV one) whatever the tier; the build needs the one of the row's tier, read off the
        listed blocks' tooltips. With none at that tier, the nearest below, else above, warned."""
        recipe_type = row.recipe.recipe_type
        listed = [b for b in (*recipe_type.singleblocks, *recipe_type.multiblocks) if b is not None]
        tiered = [(b.single_block_tier, b) for b in listed if b.single_block_tier is not None]
        tier = row.voltage_tier
        exact = [b for t, b in tiered if t == tier]
        if exact:
            return exact[0]
        below = [(t, b) for t, b in tiered if t is not None and t < tier]
        above = [(t, b) for t, b in tiered if t is not None and t > tier]
        _, chosen = (
            max(below, key=lambda pair: pair[0]) if below else min(above, key=lambda p: p[0])
        )
        warnings.warn(
            f"{_row_label(row)} runs at {TIER_NAMES[tier]}, but no {recipe_type.name!r} single "
            f"block exists at that tier; using {chosen.display_name!r}",
            ConversionWarning,
            stacklevel=5,
        )
        return chosen

    def options(self, row: SolvedRecipe) -> tuple[str | None, dict[str, str]]:
        """The row's heating coil key, and its other build options as ``machineConfigTiers``."""
        coil: str | None = None
        config: dict[str, str] = {}
        machine = row.machine
        for key, choice in (machine.choices if machine is not None else {}).items():
            value = row.choices[key]
            if choice.kind is ChoiceKind.HEATING_COIL:
                coil = HEATING_COILS[value]
            elif choice.kind is ChoiceKind.COKE_OVEN_SLICES:
                config["cokeOvenSlices"] = f"slice-{value}"
            elif choice.kind in _CONFIG_KEYS:
                name, keys = _CONFIG_KEYS[choice.kind]
                config[name] = keys[value]
        gt = row.recipe.gt
        if row.crafter is not None and row.crafter.name == chemical_plant.NAME and gt is not None:
            config["solidCasing"] = chemical_plant.solid_casing_key(gt.special_value)
        return coil, config

    def recipe_and_node(self, row: SolvedRecipe) -> tuple[dict[str, Any], dict[str, Any]]:
        gt = row.recipe.gt
        if not row.timed or gt is None:
            raise UnsupportedRecipeError(
                f"{_row_label(row)} is a {row.recipe.recipe_type.name!r} recipe with no machine "
                f"time, which the converter cannot size or lay out"
            )
        block, kind = self.block(row)
        tier = TIER_NAMES[row.voltage_tier]
        coil, config = self.options(row)
        flows = row.flows()
        recipe_id = self.recipe_id(row)
        block_resource = item_resource(block)
        outputs = [self.slot(row, f) for f in flows if f.output]
        recipe: dict[str, Any] = {
            "id": recipe_id,
            "name": ": ".join(
                [row.recipe.recipe_type.name, *(o["displayName"] for o in outputs[:1])]
            ),
            "kind": "gregtech_machine",
            "machineType": block.display_name,
            "eut": gt.voltage * gt.amperage,
            "durationTicks": gt.duration_ticks,
            "inputs": [self.slot(row, f) for f in flows if not f.output],
            "outputs": outputs,
            "source": {
                "machineBlock": {"id": block_resource.id, "displayName": block.display_name},
                "datasetVersionId": f"shadow-{self.data.pack_version}",
                "rawRecipeId": "",
                "shadowRecipeId": row.recipe.id,
            },
            "runtimeCalculation": {
                "sourceKind": NAME,
                "variants": [
                    {
                        "id": "shadow",
                        "overclockTier": tier,
                        "coilTier": coil,
                        "eut": _number(row.eut_per_parallel),
                        "durationTicks": _number(row.batch_ticks),
                        "parallel": 1,
                    }
                ],
            },
            "machineHandlers": [{"id": "shadow", "kind": kind, "label": block.display_name}],
        }
        count = max(1, math.ceil(row.crafter_count))
        if count > MAX_MACHINE_COUNT:
            raise ConversionError(
                f"{_row_label(row)} needs {count} machines, more than the {MAX_MACHINE_COUNT} one "
                f"node may stand for"
            )
        node: dict[str, Any] = {
            "id": self.node_id(row),
            "recipeId": recipe_id,
            "machineCount": count,
            "parallel": row.parallels,
            "overclockTier": tier,
        }
        if coil is not None:
            node["coilTier"] = coil
        if config:
            node["machineConfigTiers"] = config
        return recipe, node

    @staticmethod
    def node_id(row: SolvedRecipe) -> str:
        return "node-" + "-".join(map(str, row.element.path))

    @staticmethod
    def recipe_id(row: SolvedRecipe) -> str:
        return f"shadow:{'/'.join(map(str, row.element.path))}:{row.recipe.id}"

    # -- the graph --------------------------------------------------------------------------------

    def storage(self, role: str, resource: Resource) -> str:
        key = (role, resource.kind, resource.id)
        existing = self.storages.get(key)
        if existing is None:
            existing = self.storages[key] = {
                "id": f"{role}-{len(self.storages) + 1}",
                "kind": resource.kind,
                "resourceId": resource.id,
                "displayName": resource.display_name,
            }
        storage_id: str = existing["id"]
        return storage_id

    def edge(self, source: str, target: str, resource: Resource) -> None:
        key = (source, target, resource.kind, resource.id)
        if source == target or key in self.edge_keys:
            return
        self.edge_keys.add(key)
        self.edges.append(
            {
                "id": f"edge-{len(self.edges) + 1}",
                "source": source,
                "target": target,
                "resourceKind": resource.kind,
                "resourceId": resource.id,
                "label": resource.display_name,
            }
        )

    def wire(self) -> None:
        for link in self.solved.links:
            resource = self.resource(link.goods_id)
            makers = [self.node_id(r) for r in link.producers if id(r) in self.kept]
            users = [self.node_id(r) for r, _ in link.consumers if id(r) in self.kept]
            for maker in makers:
                for user in users:
                    self.edge(maker, user, resource)
            if link.demand is not None and makers:
                drain = self.storage("drain", resource)
                for maker in makers:
                    self.edge(maker, drain, resource)
            if link.supply is not None and users:
                feed = self.storage("feed", resource)
                for user in users:
                    self.edge(feed, user, resource)
        for external in self.solved.inputs:
            for row in external.recipes:
                if id(row) not in self.kept:
                    continue
                goods = self.repo.goods(external.goods_id)
                resource = self.input_resource(row, goods)
                self.edge(self.storage("feed", resource), self.node_id(row), resource)
        for external in self.solved.outputs:
            producing = [r for r in external.recipes if id(r) in self.kept]
            if not producing:
                continue
            resource = self.resource(external.goods_id)
            drain = self.storage("drain", resource)
            for row in producing:
                self.edge(self.node_id(row), drain, resource)

    def plan(self) -> dict[str, Any]:
        recipes: list[dict[str, Any]] = []
        nodes: list[dict[str, Any]] = []
        for row in self.rows:
            recipe, node = self.recipe_and_node(row)
            recipes.append(recipe)
            nodes.append(node)
        self.wire()
        check_unique(self.pairs)
        return {
            "schemaVersion": 1,
            "name": self.solved.page.name,
            "converter": {
                "name": NAME,
                "version": version(),
                "shadowCommit": SHADOW_COMMIT,
                "dataVersion": self.data.data_version,
                "dataSha256": self.data.sha256,
                "packVersion": self.data.pack_version,
            },
            "recipes": recipes,
            "nodes": nodes,
            "storages": list(self.storages.values()),
            "edges": self.edges,
        }
