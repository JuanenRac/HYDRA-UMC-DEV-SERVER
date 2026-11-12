# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_urtc_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The scenarios of the URTC bench, run against a small stand-in head on an in-memory bus.

The stand-in answers the two read-only queries with the frames the firmware sends; the real simulated head on a real virtual CAN interface is exercised
by the manual workflow of this repository."""
from __future__ import annotations

import queue
import socket
import threading

import pytest

from hydra_umc_dev_server import urtc_bench
from hydra_umc_dev_server.urtc_bench import (
    ID_ACTIVE_TOOL_RESP,
    ID_QUERY_ACTIVE_TOOL,
    ID_QUERY_VERSION,
    ID_VERSION_PATCH,
    ID_VERSION_RESPONSE,
    SCENARIOS,
    BusUnavailable,
    Head,
    SocketCan,
    main,
    run,
)

TOOL = 5


class _Pair:
    """One end of an in-memory bus: what one end sends the other receives."""

    def __init__(self, inbox: queue.Queue, outbox: queue.Queue) -> None:
        self.inbox, self.outbox = inbox, outbox

    def send(self, can_id: int, data: bytes) -> None:
        self.outbox.put((can_id, data))

    def recv(self, timeout: float):
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        pass


class _Stand:
    def __init__(self, mode: str = "good") -> None:
        a, b = queue.Queue(), queue.Queue()
        self.client, self.device = _Pair(a, b), _Pair(b, a)
        self.mode = mode
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        self.counter = 0

    def _serve(self) -> None:
        while not self.stop.is_set():
            frame = self.device.recv(0.02)
            if frame is None:
                continue
            can_id, _ = frame
            if self.mode == "deaf":
                continue
            if can_id == ID_QUERY_ACTIVE_TOOL:
                self.counter += 1
                tool = TOOL if self.mode != "wrong-tool" else TOOL + 1
                flag = 1 if self.mode == "error" else 0
                last = self.counter if self.mode == "drifting" else 0
                self.device.send(ID_ACTIVE_TOOL_RESP, bytes([tool, flag, 0, 0, last, 8]))
            elif can_id == ID_QUERY_VERSION:
                side = 1 if self.mode == "bootloader" else 0
                self.device.send(ID_VERSION_RESPONSE, bytes([side]) + (0x0303CC01).to_bytes(4, "big") + (0).to_bytes(2, "big") + bytes([3]))
                if self.mode != "no-patch":
                    self.device.send(ID_VERSION_PATCH, bytes([0, 0, 0]))
            elif self.mode == "chatty":
                self.device.send(0x7FA, bytes([0, 3, 9]))

    def head(self) -> Head:
        return Head(self.client, TOOL)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(1)


@pytest.fixture
def stand():
    made: list[_Stand] = []

    def make(mode: str = "good") -> _Stand:
        item = _Stand(mode)
        made.append(item)
        return item

    yield make
    for item in made:
        item.close()


@pytest.fixture(autouse=True)
def _short_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urtc_bench, "ANSWER_WAIT_S", 0.4)
    monkeypatch.setattr(urtc_bench, "SILENCE_S", 0.15)


def _by_name(results):
    return {r.name: r for r in results}


def test_every_scenario_passes_against_a_head_that_answers_like_the_firmware(stand) -> None:
    results = run(stand().head())
    assert len(results) == len(SCENARIOS) == 6
    assert [r.name for r in results if r.status != "pass"] == []


def test_a_deaf_head_fails_every_scenario_that_needs_an_answer(stand) -> None:
    failed = {r.name for r in run(stand("deaf").head()) if r.status == "fail"}
    assert failed == {name for name, _ in SCENARIOS} - {"urtc_ignores_the_flashing_range"}


def test_a_head_started_as_another_tool_fails_the_active_tool_scenario(stand) -> None:
    results = _by_name(run(stand("wrong-tool").head()))
    assert results["urtc_active_tool"].status == "fail"
    assert "tool 6" in results["urtc_active_tool"].detail


def test_a_head_that_reports_an_error_fails_the_active_tool_scenario(stand) -> None:
    assert _by_name(run(stand("error").head()))["urtc_active_tool"].status == "fail"


def test_a_head_that_runs_the_bootloader_fails_the_version_scenario(stand) -> None:
    results = _by_name(run(stand("bootloader").head()))
    assert results["urtc_version"].status == "fail"
    assert "bootloader" in results["urtc_version"].detail


def test_a_head_without_the_patch_frame_fails_only_the_patch_scenario(stand) -> None:
    failed = {r.name for r in run(stand("no-patch").head()) if r.status == "fail"}
    assert failed == {"urtc_patch"}


def test_a_head_that_answers_the_flashing_range_fails_that_scenario(stand) -> None:
    results = _by_name(run(stand("chatty").head()))
    assert results["urtc_ignores_the_flashing_range"].status == "fail"


def test_an_answer_that_drifts_between_queries_is_a_failure(stand) -> None:
    assert _by_name(run(stand("drifting").head()))["urtc_answers_are_stable"].status == "fail"


def test_only_runs_the_scenarios_it_names(stand) -> None:
    assert [r.name for r in run(stand().head(), only=["urtc_version"])] == ["urtc_version"]


def test_a_scenario_that_raises_is_a_failure_and_the_run_goes_on(stand, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(head: Head, run_id: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(urtc_bench, "SCENARIOS", [("broken", broken)] + list(SCENARIOS))
    results = run(stand().head())
    assert results[0].status == "fail" and "RuntimeError: boom" in results[0].detail
    assert all(r.status == "pass" for r in results[1:])


def test_the_head_is_ready_once_it_answers_and_never_when_it_is_deaf(stand) -> None:
    assert urtc_bench.wait_until_ready(stand().head(), 1.0)
    assert not urtc_bench.wait_until_ready(stand("deaf").head(), 0.2)


def test_socketcan_is_unavailable_without_the_family_or_the_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(socket, "AF_CAN", raising=False)
    with pytest.raises(BusUnavailable):
        SocketCan("vcan0")


def test_the_command_line_says_when_the_bus_cannot_be_opened(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(interface: str):
        raise BusUnavailable("nothing here")

    monkeypatch.setattr(urtc_bench, "SocketCan", refuse)
    assert main(["--wait", "0"]) == 2
    assert "URTC_BENCH=FAIL nothing here" in capsys.readouterr().err


def test_the_command_line_passes_and_fails_with_the_head(stand, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    good = stand()
    monkeypatch.setattr(urtc_bench, "SocketCan", lambda interface: good.client)
    assert main(["--wait", "0", "--tool", str(TOOL)]) == 0
    assert "URTC_BENCH=PASS" in capsys.readouterr().out
    assert main(["--wait", "0", "--tool", "9"]) == 1
    assert "URTC_BENCH=FAIL" in capsys.readouterr().out
    deaf = stand("deaf")
    monkeypatch.setattr(urtc_bench, "SocketCan", lambda interface: deaf.client)
    assert main(["--wait", "0.2"]) == 1
    assert "did not answer" in capsys.readouterr().out
