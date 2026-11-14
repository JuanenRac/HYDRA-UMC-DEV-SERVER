# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_check_coverage_floor.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The floor of the coverage job: the file that holds it, the comparison and the exit codes of tools/check_coverage_floor.py."""
import importlib.util
import json
import random
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("check_coverage_floor", ROOT / "tools" / "check_coverage_floor.py")
assert _SPEC is not None and _SPEC.loader is not None
floor_tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(floor_tool)

FLOORS = ROOT / "tools" / "coverage_floor.json"


def _report(percent):
    return {"totals": {"percent_covered": percent}}


def test_the_shipped_floors_file_is_a_list_with_a_sane_python_floor():
    text = FLOORS.read_text(encoding="utf-8")
    assert not re.search(r"[:\s\[,]0\d+\s*[,}\]\n]", text), "a floor written with a leading zero ('00') is a sed accident, not a floor"
    entries = json.loads(text)
    assert 1 <= floor_tool.floor_of(entries) <= 100
    python = [entry for entry in entries if entry["stack"] == "python"]
    assert len(python) == 1
    assert python[0]["source"] == "src/hydra_umc_dev_server" and (ROOT / python[0]["source"]).is_dir()
    assert (ROOT / python[0]["tests"]).is_dir() and (ROOT / python[0]["pythonpath"]).is_dir()


def test_a_figure_at_or_above_the_floor_passes_and_one_below_fails():
    entries = [{"stack": "python", "floor": 90}]
    assert floor_tool.check(_report(90.0), entries)[0] is True
    assert floor_tool.check(_report(97.3), entries)[0] is True
    ok, message = floor_tool.check(_report(89.99), entries)
    assert ok is False and "below the floor of 90%" in message


@pytest.mark.parametrize("entries", [None, {}, "90", [], [{"stack": "go", "floor": 90}], [{"stack": "python"}], [{"stack": "python", "floor": 0}],
                                      [{"stack": "python", "floor": 101}], [{"stack": "python", "floor": True}], [{"stack": "python", "floor": "90"}],
                                      ["python"]])
def test_a_floors_file_that_is_not_a_floor_is_refused(entries):
    ok, message = floor_tool.check(_report(95.0), entries)
    assert ok is False and message.startswith("COVERAGE_FLOOR=FAIL")


@pytest.mark.parametrize("report", [None, {}, {"totals": {}}, {"totals": {"percent_covered": "high"}}, {"totals": {"percent_covered": None}}, [], "x"])
def test_a_report_without_a_figure_is_refused(report):
    ok, message = floor_tool.check(report, [{"stack": "python", "floor": 50}])
    assert ok is False and "no totals.percent_covered" in message


def test_the_exit_codes_of_the_command_line(tmp_path, capsys):
    report = tmp_path / "coverage.json"
    floors = tmp_path / "floors.json"
    floors.write_text(json.dumps([{"stack": "python", "floor": 80}]), encoding="utf-8")
    report.write_text(json.dumps(_report(91.2)), encoding="utf-8")
    assert floor_tool.main([str(report), "--floors", str(floors)]) == 0
    assert "COVERAGE_FLOOR=PASS 91.20%" in capsys.readouterr().out
    report.write_text(json.dumps(_report(70.0)), encoding="utf-8")
    assert floor_tool.main([str(report), "--floors", str(floors)]) == 1
    assert "below the floor" in capsys.readouterr().err
    assert floor_tool.main([str(tmp_path / "missing.json"), "--floors", str(floors)]) == 1
    report.write_bytes(b"\xff\xfe")
    assert floor_tool.main([str(report), "--floors", str(floors)]) == 1
    floors.write_text('[{"stack": "python", "floor": 00}]', encoding="utf-8")
    report.write_text(json.dumps(_report(95)), encoding="utf-8")
    assert floor_tool.main([str(report), "--floors", str(floors)]) == 1, "'00' is not JSON, so it is not a floor"


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as stop:
        floor_tool.main(["--help"])
    assert stop.value.code == 0
    capsys.readouterr()


def test_random_figures_and_floors_agree_with_a_plain_comparison():
    rng = random.Random(20261114)
    for _ in range(300):
        floor = rng.randint(1, 100)
        value = round(rng.uniform(0, 100), 2)
        ok, _message = floor_tool.check(_report(value), [{"stack": "python", "floor": floor}])
        assert ok is (value + 1e-9 >= floor)
