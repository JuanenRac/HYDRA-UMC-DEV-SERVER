# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_coverage_gaps.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Branches and edge cases that the other suites leave open, found with the line and branch report of the coverage job: the accounts and
permissions of the host inspector (a fake `pwd`/`grp`, no real account), the liveness test of a process on both systems, the tail of the output
of a child, the raw CAN socket of the URTC bench, the operator side of the bridge bench and seeded random input for the manifest scan, the
tokens file and the tail reader. Nothing here touches the network or a real device; every random run uses a fixed seed."""
import json
import os
import random
import socket
import stat
import struct
import sys
import time
import types
from pathlib import Path

import pytest

from hydra_umc_dev_server import bridge_bench, runner, taskflow, urtc_bench
from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.inventory import scan_project_manifests
from hydra_umc_dev_server.node_channel import NodeChannelError, load_tokens
from hydra_umc_dev_server.preflight import SystemHostInspector

SEED = 20261114


@pytest.fixture(autouse=True)
def _no_real_group_kill(monkeypatch):
    """The fake children have made-up process ids: no test here may signal a real process group."""
    monkeypatch.setattr(os, "killpg", lambda *args: None, raising=False)


# ------------------------------------------------------------------ host inspector: accounts and permissions
def _entry(uid=1000, gid=1000, shell="/bin/bash", home="/home/dev"):
    return types.SimpleNamespace(pw_uid=uid, pw_gid=gid, pw_shell=shell, pw_dir=home)


def _fake_pwd(monkeypatch, accounts):
    def getpwnam(name):
        if name not in accounts:
            raise KeyError(name)
        return accounts[name]

    monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwnam=getpwnam))


def test_the_account_checks_need_a_posix_host(monkeypatch):
    monkeypatch.setitem(sys.modules, "pwd", None)  # `import pwd` raises ImportError, as on Windows
    with pytest.raises(ConfigValidationError, match="POSIX"):
        SystemHostInspector().user_exists("dev")


def test_an_unknown_account_has_nothing(monkeypatch):
    _fake_pwd(monkeypatch, {})
    inspector = SystemHostInspector()
    assert inspector.user_exists("ghost") is False
    assert inspector.user_uid("ghost") is None
    assert inspector.user_shell("ghost") is None
    assert inspector.user_has_authorized_keys("ghost") is False
    assert inspector.user_is_system_account("ghost") is False
    assert inspector.path_is_writable_by(str(Path.cwd()), "ghost") is False


def test_the_uid_and_the_shell_of_an_account(monkeypatch):
    _fake_pwd(monkeypatch, {"dev": _entry(uid=1234, shell="/bin/zsh"), "odd": _entry(uid="x", shell="")})
    inspector = SystemHostInspector()
    assert inspector.user_exists("dev") is True
    assert inspector.user_uid("dev") == 1234
    assert inspector.user_shell("dev") == "/bin/zsh"
    assert inspector.user_uid("odd") is None, "a uid that is not a number is not an answer"
    assert inspector.user_shell("odd") is None, "an empty shell is no shell"


def test_authorized_keys_are_looked_for_in_the_home_of_the_account(monkeypatch, tmp_path):
    (tmp_path / ".ssh").mkdir()
    _fake_pwd(monkeypatch, {"with": _entry(home=str(tmp_path)), "without": _entry(home=str(tmp_path / "nowhere")), "nohome": _entry(home="")})
    inspector = SystemHostInspector()
    assert inspector.user_has_authorized_keys("with") is False
    (tmp_path / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAA\n", encoding="utf-8")
    assert inspector.user_has_authorized_keys("with") is True
    assert inspector.user_has_authorized_keys("without") is False
    assert inspector.user_has_authorized_keys("nohome") is False


@pytest.mark.parametrize(
    ("uid", "shell", "expected"),
    [
        (0, "/bin/false", False),  # root is never a service account
        (100, "/usr/sbin/nologin", True),
        (100, "/bin/false", True),
        (100, "/bin/bash", False),  # a login shell below 1000 is a person
        (999, "/usr/sbin/nologin", True),
        (1000, "/usr/sbin/nologin", False),  # from 1000 on, an account is a user
        ("x", "/usr/sbin/nologin", False),
    ],
)
def test_what_makes_an_account_a_system_account(monkeypatch, uid, shell, expected):
    _fake_pwd(monkeypatch, {"svc": _entry(uid=uid, shell=shell)})
    assert SystemHostInspector().user_is_system_account("svc") is expected


def _with_stat(monkeypatch, target, *, uid, gid, mode):
    """`os.stat` answers the given owner, group and mode for one path and the real answer for the rest."""
    real = os.stat

    def fake(path, *args, **kwargs):
        if str(path) == str(target):
            return types.SimpleNamespace(st_uid=uid, st_gid=gid, st_mode=stat.S_IFDIR | mode)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", fake)


def test_write_permission_of_the_owner_the_group_and_the_others(monkeypatch, tmp_path):
    _fake_pwd(monkeypatch, {"dev": _entry(uid=1000, gid=1000), "root": _entry(uid=0, gid=0)})
    inspector = SystemHostInspector()
    target = str(tmp_path)
    _with_stat(monkeypatch, target, uid=1000, gid=50, mode=0o500)
    assert inspector.path_is_writable_by(target, "dev") is False, "the owner without the write bit"
    _with_stat(monkeypatch, target, uid=1000, gid=50, mode=0o700)
    assert inspector.path_is_writable_by(target, "dev") is True
    _with_stat(monkeypatch, target, uid=1, gid=1000, mode=0o070)
    assert inspector.path_is_writable_by(target, "dev") is True, "the primary group with the group write bit"
    _with_stat(monkeypatch, target, uid=1, gid=1000, mode=0o750)
    assert inspector.path_is_writable_by(target, "dev") is False
    _with_stat(monkeypatch, target, uid=1, gid=2, mode=0o002)
    assert inspector.path_is_writable_by(target, "dev") is True, "the others with the world write bit"
    _with_stat(monkeypatch, target, uid=1, gid=2, mode=0o775)
    assert inspector.path_is_writable_by(target, "dev") is False
    _with_stat(monkeypatch, target, uid=1, gid=2, mode=0o000)
    assert inspector.path_is_writable_by(target, "root") is True, "root writes anywhere"


def test_a_secondary_group_gives_the_write_bit_of_the_group(monkeypatch, tmp_path):
    _fake_pwd(monkeypatch, {"dev": _entry(uid=1000, gid=1000)})
    monkeypatch.setitem(sys.modules, "grp", types.SimpleNamespace(getgrall=lambda: [
        types.SimpleNamespace(gr_gid=77, gr_mem=["dev", "other"]),
        types.SimpleNamespace(gr_gid=78, gr_mem=["other"]),
    ]))
    _with_stat(monkeypatch, str(tmp_path), uid=1, gid=77, mode=0o020)
    assert SystemHostInspector().path_is_writable_by(str(tmp_path), "dev") is True
    _with_stat(monkeypatch, str(tmp_path), uid=1, gid=78, mode=0o020)
    assert SystemHostInspector().path_is_writable_by(str(tmp_path), "dev") is False


def test_a_host_without_the_group_database_still_answers(monkeypatch, tmp_path):
    _fake_pwd(monkeypatch, {"dev": _entry(uid=1000, gid=1000)})
    monkeypatch.setitem(sys.modules, "grp", None)
    _with_stat(monkeypatch, str(tmp_path), uid=1, gid=77, mode=0o020)
    assert SystemHostInspector().path_is_writable_by(str(tmp_path), "dev") is False


def test_the_nearest_existing_parent_is_judged_for_a_path_that_is_not_there(monkeypatch, tmp_path):
    _fake_pwd(monkeypatch, {"dev": _entry(uid=1000, gid=1000)})
    _with_stat(monkeypatch, str(tmp_path), uid=1000, gid=1, mode=0o700)
    assert SystemHostInspector().path_is_writable_by(str(tmp_path / "a" / "b"), "dev") is True


# ------------------------------------------------------------------ host inspector: disk, port, writable path
def test_the_free_disk_of_a_path_that_is_not_there_is_the_one_of_its_parent(tmp_path):
    inspector = SystemHostInspector()
    here = inspector.free_disk_gb(str(tmp_path))
    assert here is not None and here > 0
    assert inspector.free_disk_gb(str(tmp_path / "x" / "y")) == pytest.approx(here, rel=0.05)
    assert inspector.free_disk_gb("") is None


def test_a_path_that_is_not_there_is_writable_when_its_parent_is(tmp_path):
    inspector = SystemHostInspector()
    assert inspector.path_is_writable(str(tmp_path / "new" / "deeper")) is True
    assert inspector.path_is_writable("") is False


def test_a_port_in_use_is_not_free_and_a_free_one_is():
    inspector = SystemHostInspector()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = held.getsockname()[1]
        assert inspector.tcp_port_is_free("127.0.0.1", port) is False
    assert inspector.tcp_port_is_free("127.0.0.1", port) is True


def test_the_python_version_is_the_running_one():
    assert SystemHostInspector().python_version() == tuple(sys.version_info[:3])


# ------------------------------------------------------------------ is a process alive
def test_a_process_id_that_cannot_exist_is_not_alive():
    assert taskflow._pid_alive(0) is False
    assert taskflow._pid_alive(-5) is False


def test_the_own_process_is_alive():
    assert taskflow._pid_alive(os.getpid()) is True


def _posix_os(kill):
    return types.SimpleNamespace(name="posix", kill=kill)


def test_a_missing_process_is_dead_and_one_that_is_not_ours_is_alive(monkeypatch):
    def gone(pid, sig):
        raise ProcessLookupError

    def foreign(pid, sig):
        raise PermissionError

    monkeypatch.setattr(taskflow, "os", _posix_os(gone))
    assert taskflow._pid_alive(4242) is False
    monkeypatch.setattr(taskflow, "os", _posix_os(foreign))
    assert taskflow._pid_alive(4242) is True
    monkeypatch.setattr(taskflow, "os", _posix_os(lambda pid, sig: None))
    assert taskflow._pid_alive(4242) is True


def test_the_windows_way_of_asking_for_a_process(monkeypatch):
    import ctypes

    calls = []

    class Kernel:
        def __init__(self, handle):
            self.handle = handle

        def OpenProcess(self, access, inherit, pid):  # noqa: N802 - the name of the Windows call
            calls.append(("open", access, pid))
            return self.handle

        def CloseHandle(self, handle):  # noqa: N802
            calls.append(("close", handle))

    monkeypatch.setattr(taskflow, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=Kernel(0)), raising=False)
    assert taskflow._pid_alive(4242) is False
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=Kernel(99)), raising=False)
    assert taskflow._pid_alive(4242) is True
    assert calls == [("open", 0x1000, 4242), ("open", 0x1000, 4242), ("close", 99)]


# ------------------------------------------------------------------ the tail of the output of a child
class ChunkStream:
    def __init__(self, chunks=(), error=None):
        self.chunks = list(chunks)
        self.error = error

    def close(self):
        pass

    def read(self, size):
        if self.chunks:
            return self.chunks.pop(0)
        if self.error:
            raise self.error
        return ""


def _tail(chunks, limit, error=None):
    reader = runner._TailReader(ChunkStream(chunks, error), limit)
    reader.run()  # on this thread: the loop is what is under test, not the thread
    return reader.text()


def test_the_tail_keeps_the_last_characters_only():
    assert _tail(["abc", "def", "ghi"], 5) == "efghi"
    assert _tail(["abc"], 10) == "abc"
    assert _tail([], 10) == ""


def test_a_pipe_closed_under_the_reader_ends_it_quietly():
    assert _tail(["abc"], 10, error=ValueError("I/O operation on closed file")) == "abc"
    assert _tail(["abc"], 10, error=OSError("bad descriptor")) == "abc"


def test_the_tail_of_random_chunks_is_always_the_end_of_the_whole_output():
    rng = random.Random(SEED)
    for _ in range(200):
        chunks = ["".join(rng.choice("abcxyz\n") for _ in range(rng.randint(1, 40))) for _ in range(rng.randint(0, 12))]
        limit = rng.randint(1, 60)
        whole = "".join(chunks)
        got = _tail(list(chunks), limit)
        assert got == whole[-limit:] if whole else got == ""
        assert len(got) <= limit


class FakeProc:
    """Just enough of a `Popen` for the handle: the pipes are empty, the child answers from a script."""

    def __init__(self, polls=(0,), pid=424242, pipes_fail=False, wait_fails=False):
        self.pid = pid
        self._polls = list(polls)
        self.stdout = FailingPipe() if pipes_fail else ChunkStream([])
        self.stderr = FailingPipe() if pipes_fail else ChunkStream([])
        self._wait_fails = wait_fails
        self.waited = False

    def poll(self):
        return self._polls.pop(0) if len(self._polls) > 1 else self._polls[0]

    def wait(self, timeout=None):
        self.waited = True
        if self._wait_fails:
            raise RuntimeError("will not exit")


class FailingPipe(ChunkStream):
    def close(self):
        raise OSError("already closed")


def test_a_handle_whose_pipes_and_child_misbehave_still_ends_reaped():
    handle = runner._SubprocessHandle(FakeProc(pipes_fail=True, wait_fails=True))
    handle._drain()
    assert handle._reaped is True
    assert handle.stdout_tail() == "" and handle.stderr_tail() == ""


def test_polling_a_finished_child_drains_it_once():
    proc = FakeProc(polls=(0,))
    handle = runner._SubprocessHandle(proc)
    assert handle.poll() == 0
    assert handle._reaped is True and proc.waited is True
    proc.waited = False
    assert handle.poll() == 0
    assert proc.waited is False, "a reaped child is not waited for again"


def test_polling_a_running_child_drains_nothing():
    handle = runner._SubprocessHandle(FakeProc(polls=(None,)))
    assert handle.poll() is None
    assert handle._reaped is False
    handle._drain()  # leave no thread behind


def test_the_brief_wait_ends_when_the_child_does(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))
    handle = runner._SubprocessHandle(FakeProc(polls=(None, None, 0)))
    handle._wait_briefly()
    assert len(sleeps) == 2
    handle._drain()


def test_the_brief_wait_gives_up_after_twenty_tries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))
    handle = runner._SubprocessHandle(FakeProc(polls=(None,)))
    handle._wait_briefly()
    assert len(sleeps) == 20
    handle._drain()


def test_a_group_that_is_gone_or_not_ours_is_not_an_error(monkeypatch):
    handle = runner._SubprocessHandle(FakeProc(polls=(0,)))
    for error in (ProcessLookupError, PermissionError):
        def kill(pid, sig, error=error):
            raise error

        monkeypatch.setattr(os, "killpg", kill, raising=False)
        handle._kill_group(15)
    handle._drain()


# ------------------------------------------------------------------ the raw CAN socket of the URTC bench
class FakeCanSocket:
    def __init__(self, frames=(), error=None):
        self.frames = list(frames)
        self.error = error
        self.timeout = None
        self.sent = []
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def recv(self, size):
        if self.error:
            raise self.error
        return self.frames.pop(0)

    def send(self, raw):
        self.sent.append(raw)

    def close(self):
        self.closed = True


def _can(sock):
    bus = object.__new__(urtc_bench.SocketCan)
    bus._socket = sock
    return bus


def _frame(can_id, data, length=None):
    return urtc_bench._CAN_FRAME.pack(can_id, len(data) if length is None else length, data.ljust(8, b"\0"))


def test_without_socketcan_the_bus_is_unavailable(monkeypatch):
    monkeypatch.delattr(socket, "AF_CAN", raising=False)
    with pytest.raises(urtc_bench.BusUnavailable, match="Linux"):
        urtc_bench.SocketCan("vcan0")


@pytest.mark.skipif(not hasattr(socket, "AF_CAN"), reason="SocketCAN is Linux only")
def test_an_interface_that_does_not_exist_is_unavailable():
    with pytest.raises(urtc_bench.BusUnavailable, match="cannot be opened"):
        urtc_bench.SocketCan("hydra-nocan0")


def test_a_frame_is_read_with_its_own_length():
    sock = FakeCanSocket([_frame(0x110, b"\x01\x02\x03")])
    assert _can(sock).recv(0.5) == (0x110, b"\x01\x02\x03")
    assert sock.timeout == 0.5


def test_a_frame_that_is_not_standard_or_too_long_is_ignored():
    not_standard = urtc_bench._NOT_STANDARD
    sock = FakeCanSocket([_frame(0x110 | not_standard, b"\x01"), _frame(0x110, b"\x01", length=9), b"\x00\x01"])
    bus = _can(sock)
    assert bus.recv(0.1) is None, "an extended or flagged identifier"
    assert bus.recv(0.1) is None, "a length over 8"
    assert bus.recv(0.1) is None, "a frame cut short"


@pytest.mark.parametrize("error", [TimeoutError(), BlockingIOError(), socket.timeout()])
def test_nothing_on_the_bus_is_none(error):
    assert _can(FakeCanSocket(error=error)).recv(0.01) is None


def test_a_frame_goes_out_padded_to_eight_bytes_and_the_socket_closes():
    sock = FakeCanSocket()
    bus = _can(sock)
    bus.send(0x110, b"\x07")
    assert sock.sent == [struct.pack(urtc_bench._CAN_FRAME.format, 0x110, 1, b"\x07".ljust(8, b"\0"))]
    bus.close()
    assert sock.closed is True


# ------------------------------------------------------------------ the operator side of the bridge bench
class FakeOperator:
    def __init__(self, messages):
        self.messages = list(messages)

    def next_message(self, wait):
        return self.messages.pop(0) if self.messages else None


def test_the_answer_skips_other_topics_and_names_them():
    ops = FakeOperator([("a/status", b"1"), ("a/other", b"2"), ("a/result", b"{}")])
    assert bridge_bench._answer(ops, "a/result", wait=5.0) == (b"{}", ["a/status", "a/other"])


def test_no_answer_in_time_is_none_with_the_topics_that_came():
    ops = FakeOperator([("a/status", b"1")])
    assert bridge_bench._answer(ops, "a/result", wait=5.0) == (None, ["a/status"])
    assert bridge_bench._answer(FakeOperator([("a/result", b"{}")]), "a/result", wait=0.0) == (None, [])


# ------------------------------------------------------------------ seeded random input
def test_a_manifest_scan_survives_random_files_and_says_what_is_wrong(tmp_path):
    rng = random.Random(SEED)
    good = 0
    for index in range(120):
        folder = tmp_path / f"project-{index:03d}"
        folder.mkdir()
        kind = rng.randint(0, 5)
        path = folder / "hydra-umc.project.json"
        if kind == 0:
            path.write_bytes(bytes(rng.randrange(256) for _ in range(rng.randint(0, 60))))
        elif kind == 1:
            path.write_text(json.dumps([rng.randint(0, 9) for _ in range(3)]), encoding="utf-8")
        elif kind == 2:
            path.write_text(json.dumps({"name": "x", "version": rng.choice(["", 1, None])}), encoding="utf-8")
        elif kind == 3:
            path.write_text('{"name": "x", ', encoding="utf-8")
        elif kind == 4:
            path.write_text(json.dumps({"name": f"p{index}", "version": "1.0.0", "maturity": "alpha"}), encoding="utf-8")
            good += 1
        # kind 5: a folder without a manifest is not an issue
    (tmp_path / "loose-file.txt").write_text("not a folder", encoding="utf-8")
    result = scan_project_manifests(tmp_path)
    assert len(result.projects) == good
    assert all(issue.reason for issue in result.issues)
    assert len(result.projects) + len(result.issues) <= 120


def test_a_manifest_that_cannot_be_read_is_an_issue_not_a_crash(tmp_path, monkeypatch):
    folder = tmp_path / "locked"
    folder.mkdir()
    (folder / "hydra-umc.project.json").write_text("{}", encoding="utf-8")
    real = Path.read_text

    def refuse(self, *args, **kwargs):
        if self.name == "hydra-umc.project.json":
            raise PermissionError("denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refuse)
    result = scan_project_manifests(tmp_path)
    assert result.projects == ()
    assert len(result.issues) == 1 and "could not read" in result.issues[0].reason


def test_a_tokens_file_is_read_or_refused_with_one_kind_of_error(tmp_path):
    rng = random.Random(SEED)
    path = tmp_path / "tokens.json"
    assert load_tokens(path) == {}, "an absent file is an empty one"
    for _ in range(150):
        shape = rng.randint(0, 4)
        if shape == 0:
            path.write_bytes(bytes(rng.randrange(256) for _ in range(rng.randint(1, 50))))
        elif shape == 1:
            path.write_text(json.dumps(rng.choice([[], 3, "x", None, {"nodes": []}, {"schema": "nope", "nodes": {}}])), encoding="utf-8")
        elif shape == 2:
            path.write_text('{"schema": ', encoding="utf-8")
        else:
            path.write_text(json.dumps({"schema": "x", "nodes": rng.choice([[], "n", 1, None])}), encoding="utf-8")
        try:
            load_tokens(path)
        except NodeChannelError:
            pass
