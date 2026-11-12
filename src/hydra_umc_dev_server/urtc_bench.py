# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/urtc_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Scenarios for the URTC bench: a simulated tool head answering on a virtual CAN bus (`vcan0`), asked with the frames of the real protocol.

The head is the one of HYDRA-UMC-DOCS (`tools/fake_urtc.py`): it answers the two read-only queries and nothing else. The scenarios below speak raw
SocketCAN to it and compare the answers byte for byte with what the firmware sends (the active tool frame `0x111` and the version frames `0x7F9` and
`0x7E9`), and check that a frame of the flashing range is ignored. The bus is a small interface so that the same scenarios are tested here on an
in-memory pair and run in CI on a real `vcan0` interface (the manual workflow of this repository creates it).

Each scenario is one named check with a PASS / FAIL line; the run fails at the end (never at the first failure). Nothing here writes to a real head.
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import time
from typing import Callable, Protocol

from .bench import Result

ID_QUERY_ACTIVE_TOOL = 0x110
ID_ACTIVE_TOOL_RESP = 0x111
ID_QUERY_VERSION = 0x7F8
ID_VERSION_RESPONSE = 0x7F9
ID_VERSION_PATCH = 0x7E9
#: an identifier of the flashing range: the head must not answer it
ID_FLASH_RANGE = 0x7F0
#: the layout of `struct can_frame` of Linux: identifier, length, three bytes of padding, eight bytes of data
_CAN_FRAME = struct.Struct("=IB3x8s")
#: flags in the top bits of the identifier: extended frame, remote request, error frame
_NOT_STANDARD = 0xE0000000

#: How long a scenario waits for an answer.
ANSWER_WAIT_S = 2.0
#: How long a scenario listens to be sure that an answer that must NOT come did not come.
SILENCE_S = 0.6


class BusUnavailable(RuntimeError):
    """The bus cannot be opened here (SocketCAN needs Linux and an interface that exists)."""


class Bus(Protocol):
    def send(self, can_id: int, data: bytes) -> None: ...

    def recv(self, timeout: float) -> tuple[int, bytes] | None: ...

    def close(self) -> None: ...


class SocketCan:
    """A raw SocketCAN socket bound to `interface` (for example `vcan0`). Linux only."""

    def __init__(self, interface: str) -> None:
        if not hasattr(socket, "AF_CAN"):
            raise BusUnavailable("SocketCAN is only available on Linux")
        try:
            self._socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            self._socket.bind((interface,))
        except OSError as error:
            raise BusUnavailable(f"the CAN interface {interface!r} cannot be opened ({error})") from error

    def send(self, can_id: int, data: bytes) -> None:
        self._socket.send(_CAN_FRAME.pack(can_id, len(data), data.ljust(8, b"\0")))

    def recv(self, timeout: float) -> tuple[int, bytes] | None:
        self._socket.settimeout(timeout)
        try:
            raw = self._socket.recv(_CAN_FRAME.size)
        except (TimeoutError, BlockingIOError, socket.timeout):
            return None
        if len(raw) < _CAN_FRAME.size:
            return None
        can_id, length, data = _CAN_FRAME.unpack(raw[: _CAN_FRAME.size])
        if can_id & _NOT_STANDARD or length > 8:
            return None
        return can_id, data[:length]

    def close(self) -> None:
        self._socket.close()


class Head:
    """The head of the bench: the bus it is asked on and the tool it was started as."""

    def __init__(self, bus: Bus, tool_id: int) -> None:
        self.bus = bus
        self.tool_id = tool_id

    def drain(self) -> None:
        while self.bus.recv(0.05) is not None:
            pass

    def ask(self, can_id: int, wanted: list[int], wait: float = ANSWER_WAIT_S) -> dict[int, bytes]:
        """Sends the query and collects the answers whose identifier is in [wanted] until all came or [wait] passes."""
        self.drain()
        self.bus.send(can_id, b"")
        got: dict[int, bytes] = {}
        deadline = time.monotonic() + wait
        while len(got) < len(wanted) and time.monotonic() < deadline:
            frame = self.bus.recv(max(0.05, deadline - time.monotonic()))
            if frame is not None and frame[0] in wanted:
                got.setdefault(frame[0], frame[1])
        return got


def scenario_active_tool(head: Head, run_id: str) -> str:
    got = head.ask(ID_QUERY_ACTIVE_TOOL, [ID_ACTIVE_TOOL_RESP])
    assert ID_ACTIVE_TOOL_RESP in got, "the head did not answer the query of the active tool (0x110) with 0x111"
    data = got[ID_ACTIVE_TOOL_RESP]
    assert 4 <= len(data) <= 6, f"0x111 carries {len(data)} bytes, not 4 to 6"
    assert data[0] == head.tool_id, f"0x111 reports tool {data[0]}, the head was started as tool {head.tool_id}"
    assert data[1:4] == b"\0\0\0", f"0x111 reports an error or a boot in progress: {data.hex()}"
    return f"0x110 is answered with 0x111: tool {data[0]}, no error, no boot ({data.hex()})"


def scenario_version(head: Head, run_id: str) -> str:
    got = head.ask(ID_QUERY_VERSION, [ID_VERSION_RESPONSE])
    assert ID_VERSION_RESPONSE in got, "the head did not answer the query of the version (0x7F8) with 0x7F9"
    data = got[ID_VERSION_RESPONSE]
    assert len(data) == 8, f"0x7F9 carries {len(data)} bytes, not 8"
    assert data[0] == 0, f"0x7F9 says the head runs the bootloader (side {data[0]}), not the application"
    hardware = int.from_bytes(data[1:5], "big")
    major, minor = int.from_bytes(data[5:7], "big"), data[7]
    return f"0x7F8 is answered with 0x7F9: application, hardware {hardware:#010x}, version {major}.{minor}"


def scenario_patch(head: Head, run_id: str) -> str:
    got = head.ask(ID_QUERY_VERSION, [ID_VERSION_RESPONSE, ID_VERSION_PATCH])
    assert ID_VERSION_PATCH in got, "the head did not send the patch frame (0x7E9) after the query of the version"
    data = got[ID_VERSION_PATCH]
    assert len(data) == 3, f"0x7E9 carries {len(data)} bytes, not 3"
    assert data[0] == 0, f"0x7E9 names side {data[0]}, not the application"
    return f"0x7E9 follows 0x7F9: patch {data[1]}, flags {data[2]:#04x}"


def scenario_ignores_the_flashing_range(head: Head, run_id: str) -> str:
    head.drain()
    head.bus.send(ID_FLASH_RANGE, b"\x01\x02\x03\x04")
    heard = head.bus.recv(SILENCE_S)
    while heard is not None and heard[0] == ID_FLASH_RANGE:  # our own frame comes back on a virtual bus
        heard = head.bus.recv(SILENCE_S)
    assert heard is None, f"the head answered a frame of the flashing range: {heard[0]:#x} {heard[1].hex()}"
    return "a frame of the flashing range (0x7F0) is ignored"


def scenario_answers_are_stable(head: Head, run_id: str) -> str:
    first = head.ask(ID_QUERY_ACTIVE_TOOL, [ID_ACTIVE_TOOL_RESP])
    assert first, "the head did not answer"
    for turn in range(20):
        again = head.ask(ID_QUERY_ACTIVE_TOOL, [ID_ACTIVE_TOOL_RESP])
        assert again == first, f"the answer changed on query {turn + 2}: {again} instead of {first}"
    return "twenty more queries get the same answer as the first"


def scenario_answers_to_both_queries_in_a_row(head: Head, run_id: str) -> str:
    head.drain()
    head.bus.send(ID_QUERY_ACTIVE_TOOL, b"")
    head.bus.send(ID_QUERY_VERSION, b"")
    wanted = {ID_ACTIVE_TOOL_RESP, ID_VERSION_RESPONSE}
    seen: set[int] = set()
    deadline = time.monotonic() + ANSWER_WAIT_S
    while seen != wanted and time.monotonic() < deadline:
        frame = head.bus.recv(0.1)
        if frame is not None and frame[0] in wanted:
            seen.add(frame[0])
    assert seen == wanted, f"after two queries sent back to back the head answered only {sorted(hex(i) for i in seen)}"
    return "two queries sent back to back are both answered"


#: The scenarios of the URTC bench, in order.
SCENARIOS: list[tuple[str, Callable[[Head, str], str]]] = [
    ("urtc_active_tool", scenario_active_tool),
    ("urtc_version", scenario_version),
    ("urtc_patch", scenario_patch),
    ("urtc_ignores_the_flashing_range", scenario_ignores_the_flashing_range),
    ("urtc_answers_are_stable", scenario_answers_are_stable),
    ("urtc_answers_to_both_queries_in_a_row", scenario_answers_to_both_queries_in_a_row),
]


def wait_until_ready(head: Head, seconds: float) -> bool:
    """True once the head answers the active tool query; the process may need a moment after it starts."""
    deadline = time.monotonic() + seconds
    while True:
        if ID_ACTIVE_TOOL_RESP in head.ask(ID_QUERY_ACTIVE_TOOL, [ID_ACTIVE_TOOL_RESP], wait=1.0):
            return True
        if time.monotonic() >= deadline:
            return False


def run(head: Head, run_id: str | None = None, only: list[str] | None = None) -> list[Result]:
    """Every scenario, in order. A scenario that raises is a failure with the reason; the run goes on."""
    run_id = run_id or str(int(time.time()))
    results: list[Result] = []
    for name, scenario in SCENARIOS:
        if only and name not in only:
            continue
        started = time.monotonic()
        try:
            detail, status = scenario(head, run_id), "pass"
        except AssertionError as error:
            detail, status = str(error), "fail"
        except Exception as error:  # a broken scenario must not stop the others
            detail, status = f"{type(error).__name__}: {error}", "fail"
        results.append(Result(name, status, detail, round(time.monotonic() - started, 3)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-dev-server-urtc-bench", description="Scenarios against the simulated tool head of the URTC bench.")
    parser.add_argument("--interface", default="vcan0", help="the SocketCAN interface the head answers on")
    parser.add_argument("--tool", type=int, default=5, help="the tool the head was started as")
    parser.add_argument("--wait", type=float, default=30.0, help="seconds to wait for the head before the scenarios start (0: do not wait)")
    parser.add_argument("--only", action="append", help="run only this scenario (repeatable)")
    arguments = parser.parse_args(argv)
    try:
        bus: Bus = SocketCan(arguments.interface)
    except BusUnavailable as error:
        print(f"URTC_BENCH=FAIL {error}", file=sys.stderr)
        return 2
    head = Head(bus, arguments.tool)
    try:
        if arguments.wait > 0 and not wait_until_ready(head, arguments.wait):
            print(f"URTC_BENCH=FAIL the head did not answer within {arguments.wait:g} s")
            return 1
        results = run(head, only=arguments.only)
    finally:
        bus.close()
    for result in results:
        print(f"{result.status.upper():4} {result.name}: {result.detail}")
    failed = [r.name for r in results if r.status != "pass"]
    print(f"URTC_BENCH={'FAIL' if failed else 'PASS'} scenarios={len(results)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
