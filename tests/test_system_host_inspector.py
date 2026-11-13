# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_system_host_inspector.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The real read-only inspector, driven on this machine's own temporary folder, a socket made by the test and an account database the test supplies.

Nothing is created outside the temporary folder and no account or port of the host is changed.
"""
import os
import socket
import sys
import types
from pathlib import Path

import pytest

from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.preflight import HostInspector, SystemHostInspector
from hydra_umc_dev_server.workspace import SystemWorkspaceFs


def _passwd(uid: int = 1500, shell: str = "/bin/bash", home: str = "/home/x", gid: int = 1500):
    return types.SimpleNamespace(pw_uid=uid, pw_shell=shell, pw_dir=home, pw_gid=gid)


@pytest.fixture()
def inspector() -> SystemHostInspector:
    return SystemHostInspector()


@pytest.fixture()
def accounts(monkeypatch: pytest.MonkeyPatch):
    """A stand-in for the `pwd` module with the accounts the test names."""
    table: dict[str, object] = {}

    def getpwnam(name: str):
        if name not in table:
            raise KeyError(name)
        return table[name]

    fake = types.ModuleType("pwd")
    fake.getpwnam = getpwnam  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pwd", fake)
    return table


def test_it_is_a_host_inspector(inspector: SystemHostInspector) -> None:
    assert isinstance(inspector, HostInspector)


def test_the_python_version_is_this_interpreter(inspector: SystemHostInspector) -> None:
    assert inspector.python_version() == tuple(sys.version_info[:3])


def test_free_disk_is_reported_for_a_folder_and_for_the_nearest_existing_parent(inspector: SystemHostInspector, tmp_path: Path) -> None:
    here = inspector.free_disk_gb(str(tmp_path))
    assert here is not None and here > 0
    assert inspector.free_disk_gb(str(tmp_path / "not" / "yet" / "there")) == pytest.approx(here, rel=0.2)
    assert inspector.free_disk_gb("") is None


def test_an_executable_is_found_or_not(inspector: SystemHostInspector, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    program = tmp_path / ("hyt-probe-tool.cmd" if os.name == "nt" else "hyt-probe-tool")
    program.write_text("echo hi\n", encoding="utf-8")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert inspector.has_executable("hyt-probe-tool") is True
    assert inspector.has_executable("hyt-no-such-tool") is False


def test_writability_follows_the_nearest_existing_parent(inspector: SystemHostInspector, tmp_path: Path) -> None:
    assert inspector.path_is_writable(str(tmp_path)) is True
    assert inspector.path_is_writable(str(tmp_path / "a" / "b")) is True
    assert inspector.path_is_writable("") is False
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            assert inspector.path_is_writable(str(locked / "child")) is False
        finally:
            locked.chmod(0o700)


def test_a_port_is_free_until_someone_listens_on_it(inspector: SystemHostInspector) -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        assert inspector.tcp_port_is_free("127.0.0.1", port) is False
    finally:
        holder.close()
    assert inspector.tcp_port_is_free("127.0.0.1", port) is True
    assert inspector.tcp_port_is_free("192.0.2.1", 80) is False  # an address that is not this machine's cannot be bound


def test_accounts_are_read_from_the_database_and_a_missing_one_is_not_an_error(inspector: SystemHostInspector, accounts: dict) -> None:
    accounts["svc"] = _passwd(uid=998, shell="/usr/sbin/nologin", home="/srv/svc")
    assert inspector.user_exists("svc") is True
    assert inspector.user_exists("ghost") is False
    assert inspector.user_uid("svc") == 998
    assert inspector.user_uid("ghost") is None
    assert inspector.user_shell("svc") == "/usr/sbin/nologin"
    assert inspector.user_shell("ghost") is None


def test_a_dedicated_service_account_is_told_from_a_login_user_and_from_root(inspector: SystemHostInspector, accounts: dict) -> None:
    accounts["svc"] = _passwd(uid=998, shell="/usr/sbin/nologin")
    accounts["svc2"] = _passwd(uid=120, shell="/bin/false")
    accounts["login"] = _passwd(uid=998, shell="/bin/bash")
    accounts["human"] = _passwd(uid=1000, shell="/usr/sbin/nologin")
    accounts["root"] = _passwd(uid=0, shell="/usr/sbin/nologin")
    assert inspector.user_is_system_account("svc") is True
    assert inspector.user_is_system_account("svc2") is True
    assert inspector.user_is_system_account("login") is False
    assert inspector.user_is_system_account("human") is False
    assert inspector.user_is_system_account("root") is False
    assert inspector.user_is_system_account("ghost") is False


def test_authorized_keys_are_looked_for_in_the_home_of_the_account(inspector: SystemHostInspector, accounts: dict, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    accounts["keyed"] = _passwd(home=str(home))
    accounts["bare"] = _passwd(home=str(tmp_path / "other"))
    accounts["nohome"] = _passwd(home="")
    assert inspector.user_has_authorized_keys("keyed") is False
    (home / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAA test\n", encoding="utf-8")
    assert inspector.user_has_authorized_keys("keyed") is True
    assert inspector.user_has_authorized_keys("bare") is False
    assert inspector.user_has_authorized_keys("nohome") is False
    assert inspector.user_has_authorized_keys("ghost") is False


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="owner, group and mode need a POSIX host")
def test_writability_by_another_account_reads_owner_group_and_mode(inspector: SystemHostInspector, accounts: dict, tmp_path: Path) -> None:
    me, my_group = os.getuid(), os.getgid()
    folder = tmp_path / "f"
    folder.mkdir()
    accounts["owner"] = _passwd(uid=me, gid=my_group)
    accounts["groupmate"] = _passwd(uid=me + 1, gid=my_group)
    accounts["stranger"] = _passwd(uid=me + 1, gid=my_group + 1)
    accounts["admin"] = _passwd(uid=0, gid=0)
    folder.chmod(0o700)
    assert inspector.path_is_writable_by(str(folder), "owner") is True
    assert inspector.path_is_writable_by(str(folder), "groupmate") is False
    assert inspector.path_is_writable_by(str(folder), "admin") is True
    folder.chmod(0o770)
    assert inspector.path_is_writable_by(str(folder), "groupmate") is True
    assert inspector.path_is_writable_by(str(folder), "stranger") is False
    folder.chmod(0o777)
    assert inspector.path_is_writable_by(str(folder), "stranger") is True
    folder.chmod(0o500)
    try:
        assert inspector.path_is_writable_by(str(folder / "new"), "owner") is False
    finally:
        folder.chmod(0o700)
    assert inspector.path_is_writable_by(str(folder), "ghost") is False


def test_without_a_posix_account_database_the_identity_questions_say_so(inspector: SystemHostInspector, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pwd", None)  # an import of a module set to None raises ImportError
    with pytest.raises(ConfigValidationError, match="POSIX"):
        inspector.user_exists("anyone")


def test_the_real_workspace_folder_is_made_once_and_resolved(tmp_path: Path) -> None:
    fs = SystemWorkspaceFs()
    target = tmp_path / "w1"
    assert fs.exists(str(target)) is False
    fs.make_dir(str(target))
    assert fs.exists(str(target)) is True
    with pytest.raises(FileExistsError):
        fs.make_dir(str(target))
    resolved = fs.realpath(str(target))
    assert "\\" not in resolved
    assert resolved.endswith("/w1")
