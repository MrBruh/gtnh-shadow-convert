from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from gtnh_shadow_convert.cli import main
from gtnh_shadow_convert.fetch import file_sha256
from gtnh_shadow_convert.testing import Gt, SyntheticData, voltage_tooltip

WATER = "f:minecraft:water"
STEAM = "f:IC2:ic2steam"


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    data = SyntheticData()
    data.fluid("minecraft", "water", "Water")
    data.fluid("IC2", "ic2steam", "Steam")
    heater = data.item(
        "gregtech", "gt.blockmachines", 621, "Basic Fluid Heater", tooltip=[voltage_tooltip("LV")]
    )
    data.recipe_type("Fluid Heater", multiblocks=[heater])
    data.recipe(
        "r~heat",
        "Fluid Heater",
        inputs=[(WATER, 100)],
        outputs=[(STEAM, 100)],
        gt=Gt(voltage=30, duration_ticks=20),
    )
    plan = tmp_path / "plan.gtnh"
    plan.write_text(
        json.dumps(
            {
                "name": "Steam",
                "products": [{"goodsId": STEAM, "amount": 9000}],
                "rootGroup": {"elements": [{"type": "recipe", "recipeId": "r~heat"}]},
            }
        ),
        encoding="utf-8",
    )
    return plan, data.write(tmp_path / "data.bin")


def test_convert_to_stdout(files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    plan, data = files
    assert main([str(plan), "--data", str(data), "--pack-version", "2.9.0-beta-2"]) == 0
    converted = json.loads(capsys.readouterr().out)
    assert converted["name"] == "Steam"
    assert converted["nodes"][0]["machineCount"] == 2


def test_convert_to_a_file(files: tuple[Path, Path], tmp_path: Path) -> None:
    plan, data = files
    out = tmp_path / "out.json"
    argv = [str(plan), "--data", str(data), "--pack-version", "x", "-o", str(out)]
    assert main(argv) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["converter"]["packVersion"] == "x"


def test_a_failure_exits_2(files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    plan, data = files
    assert main([str(plan), "--data", str(data)]) == 2
    assert "--pack-version" in capsys.readouterr().err
    assert main([str(plan), "--data", str(plan.parent / "missing.bin")]) == 2
    assert "missing.bin" in capsys.readouterr().err


def test_fetch_data(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, data = files
    url = data.as_uri()
    cache = tmp_path / "cache"
    assert main(["fetch-data", "--url", url, "--cache", str(cache)]) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.parent.name == file_sha256(data)
    assert main(["fetch-data", "--url", url, "--sha256", "NONE", "--cache", str(cache)]) == 0
    capsys.readouterr()
    assert main(["fetch-data", "--url", url, "--sha256", "0" * 64, "--cache", str(cache)]) == 2
    assert "not the expected" in capsys.readouterr().err


def test_fetch_data_defaults_to_the_pinned_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def fake(**kwargs: object) -> Path:
        seen.update(kwargs)
        return Path("cached")

    monkeypatch.setattr("gtnh_shadow_convert.cli.fetch_data", fake)
    assert main(["fetch-data"]) == 0
    assert seen["url"] is None
    assert seen["sha256"] == "624c9a20c8476dc630c274145dc04c72d7c582e130a3599dc49ce9aee0a2fe73"
    assert capsys.readouterr().out.strip() == "cached"


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.startswith("gtnh-shadow-convert ")


def test_main_reads_sys_argv(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan, data = files
    monkeypatch.setattr("sys.argv", ["gtnh-shadow-convert", str(plan), "--data", str(data)])
    assert main() == 2
    capsys.readouterr()


def test_python_dash_m(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan, data = files
    argv = ["gtnh_shadow_convert", str(plan), "--data", str(data), "--pack-version", "x"]
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("gtnh_shadow_convert", run_name="__main__")
    assert caught.value.code == 0
    assert json.loads(capsys.readouterr().out)["name"] == "Steam"
