# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bench_real_start.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""How the bench starts the real services it is asked for with `--real`, and what it does when one of them cannot be started or stopped (evidence: simulator).

No real service is run: the processes are stand-ins that record how they were started, so every way a start can fail is reached without a build or a network.
"""
from __future__ import annotations

import subprocess

import pytest

from hydra_umc_dev_server import bench
from hydra_umc_dev_server.bench import Bench


class FakeProcess:
    """A process as `subprocess.Popen` hands it back."""

    def __init__(self, *, exited: int | None = None, hangs: bool = False) -> None:
        self.exited, self.hangs = exited, hangs
        self.terminated = self.killed = False
        self.waits = 0

    def poll(self):
        return self.exited

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None) -> int:
        self.waits += 1
        if self.hangs and not self.killed:
            raise subprocess.TimeoutExpired("fake", timeout)
        return 0


@pytest.fixture
def quiet(monkeypatch):
    """No waiting for real: the clock of the retries does not run."""
    monkeypatch.setattr(bench.time, "sleep", lambda seconds: None)


@pytest.fixture
def run(tmp_path):
    instance = Bench(real=True, workspace=str(tmp_path))
    yield instance
    instance.__exit__()


# -- the small helpers ------------------------------------------------------------------------------------------------------------
def test_the_workspace_is_the_given_folder_or_the_one_above_the_repository(tmp_path) -> None:
    assert bench.workspace_of(str(tmp_path)) == tmp_path.resolve()
    assert bench.workspace_of(None).is_dir()


def test_a_service_that_has_died_is_never_waited_for(monkeypatch) -> None:
    monkeypatch.setattr(bench, "call", lambda *a, **k: pytest.fail("a dead process must not be asked"))
    assert bench._wait_up("http://x", "/stats", FakeProcess(exited=1)) is False


def test_a_service_is_up_when_it_answers_or_asks_for_a_login(monkeypatch) -> None:
    for status in (200, 401):
        monkeypatch.setattr(bench, "call", lambda *a, status=status, **k: (status, {}))
        assert bench._wait_up("http://x", "/stats", FakeProcess()) is True


def test_a_service_that_never_answers_is_given_up_after_the_time_allowed(monkeypatch, quiet) -> None:
    asked = []
    monkeypatch.setattr(bench, "call", lambda *a, **k: asked.append(a) or (0, "refused"))
    assert bench._wait_up("http://x", "/stats", None, seconds=0.05) is False
    assert asked  # it did ask before giving up


def test_a_python_service_starts_only_where_its_sources_are(monkeypatch, tmp_path) -> None:
    started = []
    monkeypatch.setattr(bench.subprocess, "Popen", lambda argv, **kwargs: started.append((argv, kwargs)) or FakeProcess())
    assert bench._python_service(tmp_path, "REPO", "pkg.main", 4000) is None
    assert not started
    (tmp_path / "REPO" / "src").mkdir(parents=True)
    process = bench._python_service(tmp_path, "REPO", "pkg.main", 4000)
    assert isinstance(process, FakeProcess)
    argv, kwargs = started[0]
    assert argv[1:] == ["-m", "pkg.main", "serve", "--addr", "127.0.0.1", "--port", "4000"]
    assert kwargs["env"]["PYTHONPATH"] == str(tmp_path / "REPO" / "src")


def test_a_binary_is_found_from_its_variable_then_the_target_folder_then_the_repository(monkeypatch, tmp_path) -> None:
    suffix = ".exe" if bench.os.name == "nt" else ""
    monkeypatch.delenv("BIN_VAR", raising=False)
    monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)
    assert bench._binary(tmp_path, "REPO", "tool", "BIN_VAR") is None
    built = tmp_path / "REPO" / "target" / "debug"
    built.mkdir(parents=True)
    (built / ("tool" + suffix)).write_text("x", encoding="utf8")
    assert bench._binary(tmp_path, "REPO", "tool", "BIN_VAR") == built / ("tool" + suffix)
    release = tmp_path / "REPO" / "target" / "release"
    release.mkdir()
    (release / ("tool" + suffix)).write_text("x", encoding="utf8")
    assert bench._binary(tmp_path, "REPO", "tool", "BIN_VAR") == release / ("tool" + suffix)
    shared = tmp_path / "shared" / "debug"
    shared.mkdir(parents=True)
    (shared / ("tool" + suffix)).write_text("x", encoding="utf8")
    monkeypatch.setenv("CARGO_TARGET_DIR", str(tmp_path / "shared"))
    assert bench._binary(tmp_path, "REPO", "tool", "BIN_VAR") == shared / ("tool" + suffix)
    named = tmp_path / "named-tool"
    named.write_text("x", encoding="utf8")
    monkeypatch.setenv("BIN_VAR", str(named))
    assert bench._binary(tmp_path, "REPO", "tool", "BIN_VAR") == named


# -- the real services ------------------------------------------------------------------------------------------------------------
def test_a_python_service_that_comes_up_is_a_real_one(monkeypatch, run) -> None:
    process = FakeProcess()
    monkeypatch.setattr(bench, "_python_service", lambda workspace, repo, module, port: process)
    monkeypatch.setattr(bench, "_wait_up", lambda *a, **k: True)
    for name, repo in (("planner", "SEMANTIC-PLANNER"), ("safety", "SAFETY-ZONES")):
        started = run._start_real(name)
        assert started is not None and started.source == "real" and started.process is process, repo
        assert started.url.startswith("http://127.0.0.1:")


def test_a_python_service_that_does_not_come_up_is_stopped_and_not_used(monkeypatch, run) -> None:
    process = FakeProcess()
    monkeypatch.setattr(bench, "_python_service", lambda *a: process)
    monkeypatch.setattr(bench, "_wait_up", lambda *a, **k: False)
    assert run._start_real("planner") is None
    assert process.terminated


def test_a_service_with_no_sources_falls_back_to_its_simulation(monkeypatch, run) -> None:
    monkeypatch.setattr(bench, "_python_service", lambda *a: None)
    assert run._start_real("safety") is None
    run.services["safety"] = run._bring_up("safety")  # kept, so that leaving the bench stops it
    assert run.services["safety"].source == "simulated"


def test_the_dispatcher_is_never_started_by_the_bench(run) -> None:
    assert run._start_real("dispatcher") is None


def test_a_given_address_wins_over_everything(tmp_path) -> None:
    with Bench(real=True, given={"planner": "http://elsewhere:1"}, workspace=str(tmp_path)) as given:
        assert (given.services["planner"].source, given.services["planner"].url) == ("given", "http://elsewhere:1")


def test_the_twin_is_started_and_hears_the_simulated_robot_once(monkeypatch, run) -> None:
    process = FakeProcess()
    calls = []
    monkeypatch.setattr(run, "_start_twin", lambda port: process)
    monkeypatch.setattr(bench, "_wait_up", lambda *a, **k: True)
    monkeypatch.setattr(bench, "call", lambda *a, **k: calls.append((a, k)) or (200, {}))
    started = run._start_real("twin")
    assert started is not None and started.process is process
    (method_args, kwargs), = calls
    assert method_args[1:3] == ("POST", "/sim/step") and kwargs["token"] == run.twin_token


def test_a_twin_without_a_binary_is_not_started(monkeypatch, run) -> None:
    monkeypatch.setattr(bench, "_binary", lambda *a: None)
    assert run._start_twin(4001) is None


def test_a_twin_that_cannot_make_its_key_is_not_started(monkeypatch, run, tmp_path) -> None:
    monkeypatch.setattr(bench, "_binary", lambda *a: tmp_path / "twin")
    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1))
    monkeypatch.setattr(bench.subprocess, "Popen", lambda *a, **k: pytest.fail("the twin must not start without its key"))
    assert run._start_twin(4001) is None


def _twin_popen(monkeypatch, announcement: bytes):
    started = []

    def popen(argv, **kwargs):
        kwargs["stderr"].write(announcement)
        kwargs["stderr"].flush()
        started.append(argv)
        return FakeProcess()

    monkeypatch.setattr(bench.subprocess, "Popen", popen)
    return started


def test_the_twin_is_started_with_its_files_and_its_public_key_is_read_from_its_log(monkeypatch, run, tmp_path, quiet) -> None:
    key = "ab" * 32
    monkeypatch.setattr(bench, "_binary", lambda *a: tmp_path / "twin")
    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    started = _twin_popen(monkeypatch, f"twin: public key {key}\n".encode())
    assert isinstance(run._start_twin(4002), FakeProcess)
    assert run.twin_public_key == key
    argv = started[0]
    assert argv[1:3] == ["serve", "--addr"] and "4002" in argv and "--sim-config" in argv
    assert (run.scratch / "twin.token").read_text(encoding="utf8").strip() == run.twin_token


def test_a_twin_that_never_announces_a_key_is_still_returned_without_one(monkeypatch, run, tmp_path, quiet) -> None:
    monkeypatch.setattr(bench, "_binary", lambda *a: tmp_path / "twin")
    monkeypatch.setattr(bench.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    _twin_popen(monkeypatch, b"nothing to see\n")
    assert isinstance(run._start_twin(4003), FakeProcess)
    assert run.twin_public_key == ""


# -- the bridge -------------------------------------------------------------------------------------------------------------------
def _twin_service(source: str) -> bench.Running:
    return bench.Running("twin", "http://127.0.0.1:1", source)


def test_the_bridge_is_unavailable_unless_everything_it_needs_is_real(monkeypatch, run, tmp_path) -> None:
    monkeypatch.setattr(bench, "_binary", lambda *a: tmp_path / "bridge")
    run.services["twin"] = _twin_service("simulated")
    run.twin_public_key = "cd" * 32
    assert run._bring_up_bridge().source == "unavailable"  # the twin is simulated
    run.services["twin"] = _twin_service("real")
    run.twin_public_key = ""
    assert run._bring_up_bridge().source == "unavailable"  # the twin never told its key
    run.twin_public_key = "cd" * 32
    monkeypatch.setattr(bench, "_binary", lambda *a: None)
    assert run._bring_up_bridge().source == "unavailable"  # there is no bridge built
    run.real = False
    monkeypatch.setattr(bench, "_binary", lambda *a: tmp_path / "bridge")
    assert run._bring_up_bridge().source == "unavailable"  # the run is not --real


def test_a_given_bridge_is_used_as_it_is(tmp_path) -> None:
    given = Bench(real=True, given={"bridge": "http://bridge:9"}, workspace=str(tmp_path))
    try:
        assert given._bring_up_bridge().source == "given"
    finally:
        given.__exit__()


def test_the_bridge_is_started_in_front_of_the_real_twin(monkeypatch, run, tmp_path) -> None:
    process = FakeProcess()
    seen = []
    monkeypatch.setattr(bench, "_binary", lambda *a: tmp_path / "bridge")
    monkeypatch.setattr(bench.subprocess, "Popen", lambda argv, **kwargs: seen.append(argv) or process)
    monkeypatch.setattr(bench, "_wait_up", lambda *a, **k: True)
    run.services["twin"] = _twin_service("real")
    run.twin_public_key = "cd" * 32
    bridge = run._bring_up_bridge()
    assert (bridge.source, bridge.process) == ("real", process)
    assert "--sim-robot" in seen[0] and "http://127.0.0.1:1" in seen[0]
    assert (run.scratch / "twin.pub").read_text(encoding="utf8").strip() == "cd" * 32


def test_a_bridge_that_does_not_come_up_is_stopped(monkeypatch, run, tmp_path) -> None:
    process = FakeProcess()
    monkeypatch.setattr(bench, "_binary", lambda *a: tmp_path / "bridge")
    monkeypatch.setattr(bench.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(bench, "_wait_up", lambda *a, **k: False)
    run.services["twin"] = _twin_service("real")
    run.twin_public_key = "cd" * 32
    assert run._bring_up_bridge().source == "unavailable"
    assert process.terminated


# -- stopping ---------------------------------------------------------------------------------------------------------------------
def test_leaving_the_bench_stops_what_it_started_and_kills_what_will_not_stop(tmp_path) -> None:
    quiet_process, stubborn = FakeProcess(), FakeProcess(hangs=True)
    stopped = []

    class Simulated:
        def stop(self) -> None:
            stopped.append("simulated")

    run = Bench(real=True, workspace=str(tmp_path))
    run.services = {
        "a": bench.Running("a", "u", "real", process=quiet_process),
        "b": bench.Running("b", "u", "real", process=stubborn),
        "c": bench.Running("c", "u", "simulated", simulated=Simulated()),
        "d": bench.Running("d", "", "unavailable"),
    }
    scratch = run.scratch
    run.__exit__()
    assert quiet_process.terminated and not quiet_process.killed
    assert stubborn.terminated and stubborn.killed
    assert stopped == ["simulated"]
    assert not scratch.exists()
