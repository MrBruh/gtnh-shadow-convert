"""The calculator's multiblock rules, ported from ``src/machines.ts`` in the app's order.

Each entry is the app's, transcribed: decimals become exact fractions (``D("2.2")``), ``recipe.
voltageTier`` is ``c.voltage_tier``, and ``choices.x`` is ``c.choice("x")``. Where the app shares one
rule between several controllers it is shared here too. The Industrial Coke Oven and the
ExxonMobil Chemical Plant, whose rules the converter also reads to describe the built machine, are
in their own modules.

Controllers the app lists but whose rules are not ported are in :data:`NOT_PORTED`, with why; a plan
that uses one raises :class:`~..errors.UnsupportedMachineError`.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from ..databin import Fluid, IoType, Recipe, RecipeIo
from ..errors import ConversionError, ConversionWarning
from .machine import Choice, ChoiceKind, Machine, RecipeContext
from .overclock import NULL_OVERCLOCKER, Overclocker, StandardOverclocker

D = Fraction

TIER_LV, TIER_MV, TIER_LUV, TIER_ZPM, TIER_UV = 0, 1, 5, 6, 7
TIER_UHV, TIER_UEV, TIER_UIV, TIER_UXV = 8, 9, 10, 12

#: ``CoilTierNames`` in ``utils.ts``.
COIL_NAMES = (
    "Cupronickel",
    "Kanthal",
    "Nichrome",
    "TPV",
    "HSS-G",
    "HSS-S",
    "Naquadah",
    "Naquadah Alloy",
    "Trinium",
    "Electrum Flux",
    "Awakened Draconium",
    "Infinity",
    "Hypogen",
    "Eternal",
)
COIL_TIER = Choice(
    "Coils",
    tuple(f"T{i + 1}: {name}" for i, name in enumerate(COIL_NAMES)),
    kind=ChoiceKind.HEATING_COIL,
)
ITEM_PIPE_CASING = Choice(
    "Item Pipe Casing Tier",
    (
        "T1: Tin",
        "T2: Brass",
        "T3: Electrum",
        "T4: Platinum",
        "T5: Osmium",
        "T6: Quantium",
        "T7: Fluxed Electrum",
        "T8: Black Plutonium",
    ),
    kind=ChoiceKind.ITEM_PIPE_CASING,
)
FLUID_PIPE_CASING = Choice(
    "Fluid Pipe Casing Tier",
    ("T1: Bronze", "T2: Steel", "T3: Titanium", "T4: Tungstensteel"),
    kind=ChoiceKind.FLUID_PIPE_CASING,
)
SOLENOID_TIER = Choice(
    "Solenoid Tier",
    ("MV", "HV", "EV", "IV", "LuV", "ZPM", "UV", "UHV", "UEV", "UIV", "UMV"),
)

_NORMAL = StandardOverclocker.only_normal()
_PERFECT = StandardOverclocker.only_perfect()


def _metadata(c: RecipeContext, key: str, default: float) -> float:
    gt = c.recipe.gt
    return gt.metadata_value(key, default) if gt is not None else default


def _whole(value: float) -> int:
    if not float(value).is_integer():
        raise ConversionError(f"recipe metadata {value} is not a whole number")
    return int(value)


def _is_type(c: RecipeContext, name: str) -> bool:
    return c.recipe.recipe_type.name == name


def _per_tier(factor: int) -> Callable[[RecipeContext], int]:
    """``(recipe.voltageTier + 1) * factor``, the commonest parallel rule."""
    return lambda c: (c.voltage_tier + 1) * factor


def _compressor_excluder(tier: int) -> Callable[[Recipe], bool]:
    """``makeCompressorRecipeExcluder``: refuse a recipe needing a higher compression tier."""

    def excludes(recipe: Recipe) -> bool:
        gt = recipe.gt
        return tier < (gt.metadata_value("compression_tier") if gt is not None else 0)

    return excludes


MACHINES: dict[str, Machine] = {}
NOT_PORTED: dict[str, str] = {
    "Advanced Assembly Line": "its laser overclock and per-input parallels are not ported yet",
    "Nano Forge": "its nanite parallels and magmatter cost are not ported yet",
    "PCB Factory": "its trace size, nanites and cooling are not ported yet",
    "Dimensionally Transcendent Plasma Forge": "its catalyst and convergence are not ported yet",
    "Quantum Force Transformer": "its focused output chances are not ported yet",
    "Tree Growth Simulator": "its per-tool outputs are not ported yet",
    "Eye of Harmony": "its success chance, dilation and astral arrays are not ported yet",
    "Forge of the Gods": "the calculator has no rule for it",
    "Absolute Baryonic Perfection Purification Unit": "the calculator has no rule for it",
    "High Energy Laser Purification Unit": "the calculator has no rule for it",
}


def _add(names: tuple[str, ...] | str, machine: Machine) -> None:
    for name in (names,) if isinstance(names, str) else names:
        MACHINES[name] = machine


# -- steam ----------------------------------------------------------------------------------------

_add(
    (
        "Steam Compressor",
        "Steam Alloy Smelter",
        "Steam Extractor",
        "Steam Furnace",
        "Steam Forge Hammer",
        "Steam Macerator",
    ),
    Machine(
        NULL_OVERCLOCKER,
        speed=D("0.5"),
        power=D(0),
        excludes_recipe=_compressor_excluder(0),
        single_block=True,
        info="Steam machine: Steam consumption not calculated",
    ),
)
_add(
    (
        "High Pressure Steam Compressor",
        "High Pressure Alloy Smelter",
        "High Pressure Steam Extractor",
        "High Pressure Steam Furnace",
        "High Pressure Steam Forge Hammer",
        "High Pressure Steam Macerator",
    ),
    Machine(
        NULL_OVERCLOCKER,
        power=D(0),
        excludes_recipe=_compressor_excluder(0),
        single_block=True,
        info="High pressure steam machine: Steam consumption not calculated",
    ),
)
_add(
    (
        "Steam Squasher",
        "Steam Separator",
        "Steam Presser",
        "Steam Grinder",
        "Steam Purifier",
        "Steam Blender",
    ),
    Machine(
        NULL_OVERCLOCKER,
        speed=lambda c: D("1.25") if c.choice("pressure") == 1 else D("0.625"),
        power=D(0),
        parallels=8,
        excludes_recipe=_compressor_excluder(0),
        choices={"pressure": Choice("Pressure", ("Normal", "High"))},
        info="Steam multiblock machine: Steam consumption not calculated",
    ),
)

# -- compressors ----------------------------------------------------------------------------------

_add(
    "Large Electric Compressor",
    Machine(
        _NORMAL,
        speed=D(2),
        power=D("0.9"),
        excludes_recipe=_compressor_excluder(0),
        parallels=_per_tier(2),
    ),
)
_add(
    "Hot Isostatic Pressurization Unit",
    Machine(
        _NORMAL,
        speed=D("2.5"),
        power=D("0.75"),
        parallels=_per_tier(4),
        excludes_recipe=_compressor_excluder(1),
        info="Assumes it is not overheated",
    ),
)
_add(
    "Pseudostable Black Hole Containment Field",
    Machine(
        _NORMAL,
        speed=D(5),
        power=D("0.7"),
        parallels=_per_tier(8),
        excludes_recipe=_compressor_excluder(2),
        info="Parallels depend on stability, which is not represented.",
    ),
)


def _bacterial_vat(c: RecipeContext, items: list[RecipeIo]) -> list[RecipeIo]:
    """Assumes a perfect fill rate: every fluid in and out x1001."""
    for slot in items:
        if slot.type in (IoType.FLUID_INPUT, IoType.FLUID_OUTPUT) and isinstance(slot.goods, Fluid):
            slot.amount *= 1001
    return items


_add("Bacterial Vat", Machine(_NORMAL, recipe=_bacterial_vat, info="Assumes perfect fill rate"))
_add("Circuit Assembly Line", Machine(_PERFECT))


def _coal_tier(c: RecipeContext) -> int:
    return _whole(_metadata(c, "coal_casing_tier", 1))


def _component_assembly_line_minimum(c: RecipeContext, choices: dict[str, int]) -> None:
    choices["componentTier"] = max(choices["componentTier"], _coal_tier(c) - 1)


_add(
    "Component Assembly Line",
    Machine(
        _NORMAL,
        speed=lambda c: D(2) ** (c.choice("componentTier") + 1 - _coal_tier(c)),
        enforce_choice_constraints=_component_assembly_line_minimum,
        choices={
            "componentTier": Choice(
                "Components Tier",
                (
                    "LV",
                    "MV",
                    "HV",
                    "EV",
                    "IV",
                    "LuV",
                    "ZPM",
                    "UV",
                    "UHV",
                    "UEV",
                    "UIV",
                    "UMV",
                    "UXV",
                ),
            )
        },
    ),
)
_add("Extreme Heat Exchanger", Machine(_NORMAL))


def _nfr_tier(c: RecipeContext) -> int:
    return _whole(_metadata(c, "nfr_coil_tier", 1))


def _nfr_minimum(c: RecipeContext, choices: dict[str, int]) -> None:
    choices["coils"] = max(choices["coils"], _nfr_tier(c) - 1)


_add(
    "Naquadah Fuel Refinery",
    Machine(
        lambda c: StandardOverclocker.only_perfect(max(0, c.choice("coils") + 1 - _nfr_tier(c))),
        parallels=lambda c: (c.choice("coils") + 1) * 4,
        choices={
            "coils": Choice(
                "Coils",
                (
                    "T1 Field Restriction Coil",
                    "T2 Advanced Field Restriction Coil",
                    "T3 Ultimate Field Restriction Coil",
                    "T4 Temporal Field Restriction Coil",
                ),
            )
        },
        enforce_choice_constraints=_nfr_minimum,
    ),
)
_add(
    "Neutron Activator",
    Machine(
        NULL_OVERCLOCKER,
        speed=lambda c: (1 / D("0.9")) ** (c.choice("speedingPipeCasing") - 4),
        power=D(0),
        choices={"speedingPipeCasing": Choice("Speeding Pipe Casing", minimum=4)},
        info="Power usage not calculated",
    ),
)
_add(
    "Precise Auto-Assembler MT-3662",
    Machine(
        _NORMAL,
        speed=lambda c: D(1) if _is_type(c, "Precise Assembler") else D(2),
        parallels=lambda c: 2 ** c.choice("precisionTier") * 16,
        choices={
            "precisionTier": Choice(
                "Precision Tier", ("Imprecise (MK-0)", "MK-I", "MK-II", "MK-III", "MK-IV")
            )
        },
    ),
)
_add(
    "Fluid Shaper",
    Machine(
        _NORMAL,
        speed=D(3),
        power=D("0.8"),
        parallels=lambda c: (c.voltage_tier + 1) * (2 + 3 * c.choice("widthExpansion")),
        choices={"widthExpansion": Choice("Width Expansion", maximum=6)},
        info="Assuming running at max speed.",
    ),
)
_add(
    "Zyngen",
    Machine(
        _NORMAL,
        speed=lambda c: 1 + c.choice("coilTier") * D("0.05"),
        parallels=lambda c: (c.voltage_tier + 1) * c.choice("coilTier"),
        choices={"coilTier": COIL_TIER},
    ),
)


@dataclass(frozen=True)
class _Electrode:
    name: str
    speed: Fraction
    parallels: int
    oc: Fraction
    power: Fraction


_ELECTRODES = (
    _Electrode("Graphite", D("2.0"), 4, D(2), D("1.0")),
    _Electrode("Tantalum", D("4.0"), 2, D(4), D("1.2")),
    _Electrode("Molybdenum", D("3.0"), 16, D(3), D("0.8")),
    _Electrode("Tungsten", D("1.0"), 128, D(1), D("1.1")),
    _Electrode("Tungstensteel", D("1.0"), 256, D(1), D("1.2")),
    _Electrode("Graphene", D("2.0"), 16, D(2), D("1.0")),
    _Electrode("YBCO", D("6.0"), 8, D(6), D("0.8")),
    _Electrode("Netherite", D("1.5"), 64, D("1.5"), D("1.3")),
    _Electrode("Tritanium", D("2.0"), 48, D(2), D("1.7")),
    _Electrode("Infinity", D("1.0"), 1, D(1), D("1.0")),
    _Electrode("Hypogen", D("1.0"), 256, D(1), D("1.5")),
    _Electrode("Neutronium Nanite", D("2.0"), 64, D(2), D("2.0")),
    _Electrode("Transcendent Nanite", D("4.0"), 512, D(4), D("2.0")),
    _Electrode("Universium Nanite", D("8.0"), 1024, D(8), D("2.0")),
)


def _electrode(c: RecipeContext) -> _Electrode:
    return _ELECTRODES[c.choice("electrode")]


_add(
    "Industrial Arc Furnace",
    Machine(
        lambda c: StandardOverclocker.only_perfect(None, _electrode(c).oc),
        speed=lambda c: _electrode(c).speed,
        power=lambda c: _electrode(c).power,
        parallels=lambda c: _electrode(c).parallels,
        choices={"electrode": Choice("Electrode", tuple(e.name for e in _ELECTRODES))},
        info="Electrode special properties not implemented. Startup not implemented.",
    ),
)
_add(
    "Large Scale Auto-Assembler v1.01",
    Machine(_NORMAL, speed=D(3), parallels=_per_tier(2)),
)


def _space_assembler_excluder(tier: int) -> Callable[[Recipe], bool]:
    def excludes(recipe: Recipe) -> bool:
        gt = recipe.gt
        return (gt.metadata_value("space_elevator_module_tier") if gt is not None else 0) > tier

    return excludes


for _name, _parallels, _fixed, _tier in (
    ("Space Assembler Module MK-I", 4, TIER_UHV + 1, 1),
    ("Space Assembler Module MK-II", 16, TIER_UIV + 2, 2),
    ("Space Assembler Module MK-III", 64, TIER_UXV + 3, 3),
):
    _add(
        _name,
        Machine(
            _NORMAL,
            parallels=_parallels,
            fixed_voltage_tier=_fixed,
            excludes_recipe=_space_assembler_excluder(_tier),
            info="NOTE: overrides voltage tier",
        ),
    )

_add(
    "Industrial Autoclave",
    Machine(
        _NORMAL,
        speed=lambda c: D("1.25") + c.choice("coilTier") * D("0.25"),
        power=lambda c: D(11 - c.choice("pipeFluidCasingTier"), 12),
        parallels=lambda c: c.choice("pipeCasingTier") * 12 + 12,
        choices={
            "coilTier": COIL_TIER,
            "pipeCasingTier": ITEM_PIPE_CASING,
            "pipeFluidCasingTier": FLUID_PIPE_CASING,
        },
    ),
)

# -- blast furnaces -------------------------------------------------------------------------------


def _ebf_excess_heat(c: RecipeContext) -> int:
    """``getEbfExcessHeat``: coil heat plus 100 K per tier above MV, less the recipe's heat."""
    gt = c.recipe.gt
    recipe_heat = gt.special_value if gt is not None else 0
    coil_heat = 1801 + c.choice("coilTier") * 900
    voltage_heat = max(0, c.voltage_tier - TIER_MV) * 100
    return coil_heat + voltage_heat - recipe_heat


def _ebf_overclocker(c: RecipeContext) -> Overclocker:
    """One perfect overclock per 1800 K of excess heat, then normal ones (``makeEbfOverclocker``).
    Coils too cold for the recipe give a negative count, which the app, and so this, carries
    through; GT would not run the recipe at all."""
    excess = _ebf_excess_heat(c)
    if excess < 0:
        warnings.warn(
            f"recipe {c.recipe.id!r} needs {-excess} K more heat than its coils give; GT will not "
            f"run it, but the calculator, and so this converter, computes it anyway",
            ConversionWarning,
            stacklevel=2,
        )
    return StandardOverclocker.perfect_then_normal(math.floor(Fraction(excess, 1800)))


def _ebf_power(c: RecipeContext) -> Fraction:
    """5% less energy per 900 K of excess heat (``ebfPower``)."""
    return D("0.95") ** math.floor(Fraction(_ebf_excess_heat(c), 900))


_POLLUTION_GASES = ("CO2 Gas", "Sulfur Dioxide", "Carbon Monoxide")


def _ebf_muffler(c: RecipeContext, items: list[RecipeIo]) -> list[RecipeIo]:
    """The first pollution gas comes out scaled by the muffler hatch's tier (12.5% per tier)."""
    for slot in items:
        if (
            slot.type is IoType.FLUID_OUTPUT
            and isinstance(slot.goods, Fluid)
            and slot.goods.name in _POLLUTION_GASES
        ):
            slot.amount = c.choice("muffler") * slot.amount * D("0.125")
            break
    return items


_add(
    "Electric Blast Furnace",
    Machine(
        _ebf_overclocker,
        power=_ebf_power,
        recipe=_ebf_muffler,
        choices={
            "coilTier": COIL_TIER,
            "muffler": Choice(
                "Muffler hatch",
                (
                    "LV (0%)",
                    "MV (12.5%)",
                    "HV (25%)",
                    "EV (37.5%)",
                    "IV (50%)",
                    "LuV (62.5%)",
                    "ZPM (75%)",
                    "UV (87.5%)",
                    "UHV (100%)",
                ),
            ),
        },
    ),
)
_add(
    "Volcanus",
    Machine(
        _ebf_overclocker,
        speed=D("2.2"),
        power=lambda c: _ebf_power(c) * D("0.9"),
        parallels=8,
        choices={"coilTier": COIL_TIER},
        info="Blazing pyrotheum required (Not calculated)",
    ),
)
_add(
    "Exothermic Hearth",
    Machine(_ebf_overclocker, power=_ebf_power, parallels=256, choices={"coilTier": COIL_TIER}),
)

# -- the rest, in the app's order -----------------------------------------------------------------

_add("Big Barrel Brewery", Machine(_NORMAL, speed=D("1.5"), parallels=_per_tier(4)))
_add("TurboCan Pro", Machine(_NORMAL, speed=D(2), parallels=_per_tier(8)))
_add("Ore Washing Plant", Machine(_NORMAL, speed=D(5), parallels=_per_tier(4)))
_add("Industrial Chemical Bath", Machine(_NORMAL, speed=D(5), parallels=_per_tier(4)))


def _cracker_power(c: RecipeContext) -> Fraction:
    return 1 - min(D("0.5"), (c.choice("coilTier") + 1) * D("0.1"))


_add("Oil Cracking Unit", Machine(_NORMAL, power=_cracker_power, choices={"coilTier": COIL_TIER}))
_add(
    "Mega Oil Cracker",
    Machine(_NORMAL, power=_cracker_power, parallels=256, choices={"coilTier": COIL_TIER}),
)

_SAWBLADES = (
    ("Tungsten Titanium Carbide", D("2.5"), D("0.9"), 2),
    ("Mysterious Crystal", D(3), D("0.8"), 3),
    ("Neutronium ", D("3.5"), D("0.7"), 4),
    ("Transcendent Metal ", D("4.5"), D("0.6"), 6),
)
_add(
    "Industrial Cutting Factory",
    Machine(
        _NORMAL,
        speed=lambda c: _SAWBLADES[c.choice("sawblade")][1],
        power=lambda c: _SAWBLADES[c.choice("sawblade")][2],
        parallels=lambda c: _SAWBLADES[c.choice("sawblade")][3] * (c.voltage_tier + 1),
        choices={"sawblade": Choice("Sawblade", tuple(s[0] for s in _SAWBLADES))},
    ),
)
_add("Distillation Tower", Machine(_NORMAL))


def _tower_mode(c: RecipeContext) -> bool:
    return _is_type(c, "Distillation Tower")


_add(
    "Dangote Distillus",
    Machine(
        _NORMAL,
        speed=lambda c: D("3.5") if _tower_mode(c) else D(2),
        power=lambda c: D(1) if _tower_mode(c) else D("0.85"),
        parallels=lambda c: 12 if _tower_mode(c) else (c.voltage_tier + 1) * 8,
    ),
)
_add("Mega Distillation Tower", Machine(_NORMAL, parallels=256))
_add(
    "Electric Implosion Compressor",
    Machine(
        _NORMAL,
        parallels=lambda c: 4 ** c.choice("containmentBlockTier"),
        choices={
            "containmentBlockTier": Choice(
                "Containment Block Tier",
                ("Neutronium", "Infinity", "Transcendent Metal", "SpaceTime", "Universum"),
            )
        },
    ),
)

_ELECTROMAGNETS = (
    ("Iron Electromagnet", D("1.1"), D("0.8"), 8),
    ("Steel Electromagnet", D("1.25"), D("0.75"), 24),
    ("Neodymium Electromagnet", D("1.5"), D("0.7"), 48),
    ("Samarium Electromagnet", D(2), D("0.6"), 96),
    ("Tengam Electromagnet", D("2.5"), D("0.5"), 256),
)
_add(
    "Magnetic Flux Exhibitor",
    Machine(
        _NORMAL,
        speed=lambda c: _ELECTROMAGNETS[c.choice("electromagnet")][1],
        power=lambda c: _ELECTROMAGNETS[c.choice("electromagnet")][2],
        parallels=lambda c: _ELECTROMAGNETS[c.choice("electromagnet")][3],
        choices={"electromagnet": Choice("Electromagnet", tuple(m[0] for m in _ELECTROMAGNETS))},
    ),
)
_add(
    "Dissection Apparatus",
    Machine(
        _NORMAL,
        speed=D(3),
        power=D("0.85"),
        parallels=lambda c: (c.choice("pipeCasingTier") + 1) * 8,
        choices={"pipeCasingTier": ITEM_PIPE_CASING},
    ),
)
_add("Industrial Extrusion Machine", Machine(_NORMAL, speed=D("3.5"), parallels=_per_tier(6)))
_add("Assembly Line", Machine(_NORMAL))
_add(
    "Large Fluid Extractor",
    Machine(
        _NORMAL,
        speed=lambda c: D("1.5") + c.choice("coilTier") * D("0.1"),
        power=lambda c: D("0.80") * D("0.90") ** c.choice("coilTier"),
        parallels=lambda c: (c.choice("solenoidTier") + 2) * 8,
        choices={"coilTier": COIL_TIER, "solenoidTier": SOLENOID_TIER},
    ),
)
_add(
    "Thermic Heating Device",
    Machine(_NORMAL, speed=D("2.2"), power=D("0.9"), parallels=_per_tier(8)),
)
_add("Furnace", Machine(_NORMAL))
_add(
    "Multi Smelter",
    Machine(
        _NORMAL,
        parallels=lambda c: 8 * 2 ** c.choice("coilTier"),
        choices={"coilTier": COIL_TIER},
        info="Parallel amount needs testing!",
    ),
)
_add(
    "Industrial Sledgehammer",
    Machine(
        _NORMAL,
        speed=D(2),
        parallels=lambda c: (c.voltage_tier + 1) * (c.choice("anvilTier") + 1) * 8,
        choices={
            "anvilTier": Choice(
                "Anvil Tier",
                (
                    "T1 - Vanilla",
                    "T2 - Steel",
                    "T3 - Dark Steel / Thaumium",
                    "T4 - Void Metal",
                ),
            )
        },
    ),
)
_add("Nuclear Reactor", Machine(_NORMAL))
_add("Implosion Compressor", Machine(_NORMAL))
_add(
    "Density^2",
    Machine(_NORMAL, speed=D(2), parallels=lambda c: (c.voltage_tier + 1) // 2 + 1),
)
_add("Large Chemical Reactor", Machine(_PERFECT))
_add("Mega Chemical Reactor", Machine(_PERFECT, parallels=256))


def _integer_cbrt(n: int) -> int:
    """``Math.floor(Math.cbrt(n))``, exactly, by bisection (``n >= 0``)."""
    low, high = 0, 1
    while high**3 <= n:
        high *= 2
    while high - low > 1:
        middle = (low + high) // 2
        if middle**3 <= n:
            low = middle
        else:
            high = middle
    return low


_add(
    "Hyper-Intensity Laser Engraver",
    Machine(
        _NORMAL,
        speed=D("3.5"),
        power=D("0.8"),
        parallels=lambda c: _integer_cbrt(c.choice("laserAmperage")),
        choices={"laserAmperage": Choice("Laser Amperage", minimum=1)},
    ),
)

_LATHE_PARALLELS = (1, 1, 2, 4, 8, 12, 16, 32)
_LATHE_SPEED = (D("0.75"), D("0.8"), D("0.9"), D(1), D("1.5"), D(2), D(3), D(4))
_add(
    "Industrial Precision Lathe",
    Machine(
        _NORMAL,
        speed=lambda c: (_LATHE_SPEED[c.choice("itemPipeCasings")] + c.voltage_tier + 1) / 4,
        power=D("0.8"),
        parallels=lambda c: (
            _LATHE_PARALLELS[c.choice("itemPipeCasings")] + (c.voltage_tier + 1) * 2
        ),
        choices={"itemPipeCasings": ITEM_PIPE_CASING},
    ),
)
_add(
    "Industrial Maceration Stack",
    Machine(
        _NORMAL,
        speed=lambda c: D("6.4") if c.choice("upgradeChip") == 1 else D("1.6"),
        parallels=lambda c: (8 if c.choice("upgradeChip") == 1 else 2) * (c.voltage_tier + 1),
        choices={"upgradeChip": Choice("Upgrade Chip", ("No Upgrade", "Maceration Upgrade Chip"))},
    ),
)
_add("Industrial Bending Machine", Machine(_NORMAL, speed=D(6), parallels=_per_tier(6)))
_add("Industrial Forming Press", Machine(_NORMAL, speed=D(6), parallels=_per_tier(6)))
_add(
    "Neutronium Compressor",
    Machine(_NORMAL, parallels=8, excludes_recipe=_compressor_excluder(0)),
)
_add(
    "Amazon Warehousing Depot",
    Machine(
        _NORMAL,
        speed=lambda c: D(c.choice("tier") + 1),
        power=D("0.75"),
        parallels=_per_tier(16),
        choices={"tier": ITEM_PIPE_CASING},
    ),
)
_add("Bricked Blast Furnace", Machine(_NORMAL))
_add(
    (
        "Clarifier Purification Unit",
        "Residual Decontaminant Degasser Purification Unit",
        "Flocculation Purification Unit",
        "Ozonation Purification Unit",
        "pH Neutralization Purification Unit",
        "Extreme Temperature Fluctuation Purification Unit",
    ),
    Machine(_NORMAL),
)
_add(
    "Pyrolyse Oven",
    Machine(
        _NORMAL,
        speed=lambda c: (c.choice("coils") + 1) * D("0.5"),
        choices={"coils": COIL_TIER},
    ),
)
_add("Elemental Duplicator", Machine(_PERFECT, speed=D(2), parallels=_per_tier(8)))
_add("Research station", Machine(_NORMAL))
_add("Boldarnator", Machine(_NORMAL, speed=D(3), power=D("0.75"), parallels=_per_tier(8)))
_add(
    "Large Thermal Refinery",
    Machine(
        _NORMAL,
        speed=lambda c: D("2.5") * (1 + (c.choice("coilTier") + 1) * D("0.05")),
        power=lambda c: D("0.8") * D("0.95") ** (c.choice("coilTier") + 1),
        parallels=lambda c: (c.voltage_tier + 1) * 8 + (c.choice("solenoidTier") + 1) * 2,
        choices={"solenoidTier": SOLENOID_TIER, "coilTier": COIL_TIER},
    ),
)
_add(
    "Transcendent Plasma Mixer",
    Machine(
        NULL_OVERCLOCKER,
        power=D(10),
        parallels=lambda c: c.choice("parallels"),
        choices={"parallels": Choice("Parallels", minimum=1)},
    ),
)
_add("Vacuum Freezer", Machine(_NORMAL))
_add(
    "Endothermic Fridge",
    Machine(
        lambda c: StandardOverclocker.perfect_then_normal(c.choice("coolant")),
        parallels=256,
        choices={
            "coolant": Choice(
                "Coolant",
                ("No Coolant", "Molten SpaceTime", "Spatially Enlarged Fluid", "Molten Eternity"),
            )
        },
        info="Coolant calculation not implemented.",
    ),
)
_add(
    "Industrial Wire Factory",
    Machine(
        _NORMAL,
        speed=lambda c: 1 + D("0.5") * (c.choice("tier") + 1),
        power=D("0.75"),
        parallels=_per_tier(4),
        choices={"tier": ITEM_PIPE_CASING},
    ),
)
_add("Digester", Machine(_PERFECT))
_add("Dissolution Tank", Machine(_NORMAL))
_add("Source Chamber", Machine(_NORMAL))
_add("Target Chamber", Machine(_NORMAL))
_add("Alloy Blast Smelter", Machine(_NORMAL))
_add(
    "Mega Alloy Blast Smelter",
    Machine(
        _NORMAL,
        speed=lambda c: max(D(1), 1 - D("0.05") * (c.choice("coilTier") - 3)),
        power=lambda c: D("0.95") ** (c.choice("coilTier") - c.voltage_tier),
        parallels=256,
        choices={"coilTier": COIL_TIER},
        info="Assumes matching glass tier.",
    ),
)
_add("Cryogenic Freezer", Machine(_NORMAL, speed=D("2.2"), power=D("0.9"), parallels=8))
_add("COMET - Compact Cyclotron", Machine(_NORMAL))
_add(
    "Zhuhai - Fishing Port",
    Machine(_NORMAL, parallels=lambda c: ((c.voltage_tier + 1) + 1) * 2),
)
_add("Reactor Fuel Processing Plant", Machine(_NORMAL))
_add("Flotation Cell Regulator", Machine(_PERFECT))
_add("Thorium Reactor [LFTR]", Machine(_NORMAL))


def _matter_fabrication_parallels(c: RecipeContext) -> int:
    gt = c.recipe.gt
    scrap = gt is not None and gt.voltage_tier == TIER_LV
    return 64 if scrap else 8 * (c.voltage_tier + 1)


_add(
    "Matter Fabrication CPU",
    Machine(_PERFECT, power=D("0.8"), parallels=_matter_fabrication_parallels),
)
_add("Molecular Transformer", Machine(_NORMAL))
_add(
    "Industrial Centrifuge",
    Machine(_NORMAL, speed=D(3), power=D("0.9"), parallels=_per_tier(8), info="Assumes max speed"),
)


def _spinmatron_parallels(c: RecipeContext) -> int:
    fuel = D("1.25") if c.choice("fuel") == 1 else D(1)
    heavy = 32 if c.choice("mode") == 2 else 1
    return math.ceil(c.choice("sumTurbineTier") * 4 * fuel / heavy)


_add(
    "Spinmatron-2737",
    Machine(
        _NORMAL,
        speed=lambda c: D(3 * (2 if c.choice("mode") == 1 else 1)),
        power=lambda c: D("0.7") * (16 if c.choice("mode") == 2 else 1),
        parallels=_spinmatron_parallels,
        choices={
            "mode": Choice("Mode", ("Standard", "Light", "Heavy")),
            "sumTurbineTier": Choice("Sum Turbine Tier", minimum=1),
            "fuel": Choice("Fuel", ("Kerosene", "Biocatalysed Propulsion Fluid")),
        },
    ),
)
_add(
    "Utupu-Tanuri",
    Machine(
        lambda c: StandardOverclocker.perfect_then_normal(c.choice("heatIncrements") // 2),
        speed=lambda c: D("2.2") * D("1.05") ** c.choice("heatIncrements"),
        power=D("0.5"),
        parallels=4,
        choices={"heatIncrements": Choice("Heat Difference Tiers", minimum=0)},
        info="Extracting heat difference from the recipe is not implemented.",
    ),
)
_add(
    "Industrial Electrolyzer",
    Machine(_NORMAL, speed=D("2.8"), power=D("0.9"), parallels=_per_tier(4)),
)
_add(
    "Industrial Mixing Machine",
    Machine(
        _NORMAL,
        speed=lambda c: D(2 + c.choice("tier")),
        parallels=_per_tier(8),
        choices={"tier": ITEM_PIPE_CASING},
    ),
)
_add("Nuclear Salt Processing Plant", Machine(_NORMAL, speed=D("2.5"), parallels=_per_tier(2)))
_add("IsaMill Grinding Machine", Machine(_PERFECT))
_add("Sparge Tower Controller", Machine(_NORMAL))


def _defc_tier(c: RecipeContext) -> int:
    return _whole(_metadata(c, "defc_casing_tier", 1))


def _defc_minimum(c: RecipeContext, choices: dict[str, int]) -> None:
    choices["casings"] = max(choices["casings"], _defc_tier(c) - 1)


_add(
    "Draconic Evolution Fusion Crafter",
    Machine(
        lambda c: StandardOverclocker.perfect_then_normal(
            max(0, c.choice("casings") + 1 - _defc_tier(c))
        ),
        choices={
            "casings": Choice(
                "Fusion casings",
                ("Bloody Ichorium", "Draconium", "Wyvern", "Awakened Draconium", "Chaotic"),
            )
        },
        enforce_choice_constraints=_defc_minimum,
    ),
)
_add(
    "Large Sifter Control Block",
    Machine(_NORMAL, speed=D(5), power=D("0.75"), parallels=_per_tier(4)),
)

# -- fusion ---------------------------------------------------------------------------------------


def fusion_tier_by_startup_cost(eu_to_start: float) -> int:
    """``getFusionTierByStartupCost`` in ``utils.ts``."""
    for limit, tier in (
        (10_000_000 * 16, 1),
        (20_000_000 * 16, 2),
        (40_000_000 * 16, 3),
        (320_000_000 * 16, 4),
        (1_280_000_000 * 16, 5),
    ):
        if eu_to_start < limit:
            return tier
    raise ConversionError(f"a fusion startup cost of {eu_to_start:g} EU is beyond every reactor")


def fusion_tier(recipe: Recipe) -> int:
    """``getFusionTier``: the reactor a recipe needs, by startup cost, plasma tier and voltage."""
    gt = recipe.gt
    cost = gt.metadata_value("fusion_threshold") if gt is not None else 0
    plasma = _whole(gt.metadata_value("fog_plasma_tier")) if gt is not None else 0
    voltage = (gt.voltage_tier if gt is not None else 0) - TIER_LUV + 1
    return max(plasma, fusion_tier_by_startup_cost(cost), voltage)


def _fusion(
    tier: int, multiplier: int, fixed: int, parallels: int | Callable[[RecipeContext], int]
) -> Machine:
    def overclocker(c: RecipeContext) -> Overclocker:
        return StandardOverclocker.only_perfect(tier - fusion_tier(c.recipe), multiplier)

    return Machine(
        overclocker,
        parallels=parallels,
        fixed_voltage_tier=fixed,
        excludes_recipe=lambda recipe: tier < fusion_tier(recipe),
        info="NOTE: overrides voltage tier",
    )


def _compact_fusion_parallels(tier: int) -> Callable[[RecipeContext], int]:
    return lambda c: (1 + tier - fusion_tier(c.recipe)) * 64


_add("Fusion Control Computer Mark I", _fusion(1, 2, TIER_LUV, 1))
_add("Fusion Control Computer Mark II", _fusion(2, 2, TIER_ZPM, 1))
_add("Fusion Control Computer Mark III", _fusion(3, 2, TIER_UV, 1))
_add("FusionTech MK IV", _fusion(4, 4, TIER_UHV, 1))
_add("FusionTech MK V", _fusion(5, 4, TIER_UEV, 1))
_add("Compact Fusion Computer MK-I Prototype", _fusion(1, 2, TIER_LUV + 3, 64))
_add("Compact Fusion Computer MK-II", _fusion(2, 2, TIER_ZPM + 4, _compact_fusion_parallels(2)))
_add("Compact Fusion Computer MK-III", _fusion(3, 2, TIER_UV + 4, _compact_fusion_parallels(3)))
_add(
    "Compact Fusion Computer MK-IV Prototype",
    _fusion(4, 4, TIER_UHV + 4, _compact_fusion_parallels(4)),
)
_add("Compact Fusion Computer MK-V", _fusion(5, 4, TIER_UEV + 5, _compact_fusion_parallels(5)))
