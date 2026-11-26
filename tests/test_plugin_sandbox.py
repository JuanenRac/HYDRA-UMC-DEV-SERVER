"""The sandbox of the plugin processes: which one is used, what it is asked to do and what happens without it."""
from __future__ import annotations

import sys

import pytest

from hydra_umc_dev_server import plugins
from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.plugins import PluginError, PluginManifest, PluginRegistry
from hydra_umc_dev_server.sandbox import PluginSandbox, SandboxUnavailableError

MANIFEST = PluginManifest(name="p", version="1.0.0", api_version=1, entry="plugin.py", provides=("checks",))
COMMAND = (sys.executable, "-I", "-c", "pass")


def _sandbox(mode: str, *, installed: bool = True, works: bool = True, os_name: str = "posix", seen: list | None = None, **kwargs) -> PluginSandbox:
    def probe(argv):
        if seen is not None:
            seen.append(argv)
        return works

    return PluginSandbox(mode, which=lambda name: "/usr/bin/" + name if installed else None, os_name=os_name, probe=probe, **kwargs)


def test_auto_wraps_when_bubblewrap_works_and_tries_it_once(tmp_path):
    seen: list = []
    sandbox = _sandbox("auto", seen=seen)
    for _ in range(2):
        argv, env = sandbox.wrap(COMMAND, cwd=str(tmp_path), env={"HOME": str(tmp_path)})
        assert argv[0] == "bwrap"
        assert argv[-len(COMMAND):] == COMMAND
        assert "--unshare-all" in argv and "--share-net" not in argv
        assert list(env) == ["PATH"]
    assert sandbox.used == "bubblewrap"
    assert len(seen) == 1


@pytest.mark.parametrize("kwargs", [{"installed": False}, {"works": False}, {"os_name": "nt"}])
def test_auto_runs_without_a_sandbox_where_there_is_none_and_required_refuses(tmp_path, kwargs):
    env = {"HOME": str(tmp_path)}
    sandbox = _sandbox("auto", **kwargs)
    assert sandbox.wrap(COMMAND, cwd=str(tmp_path), env=env) == (COMMAND, env)
    assert sandbox.used == "none"
    with pytest.raises(SandboxUnavailableError):
        _sandbox("required", **kwargs).wrap(COMMAND, cwd=str(tmp_path), env=env)


def test_off_never_wraps(tmp_path):
    seen: list = []
    assert _sandbox("off", seen=seen).wrap(COMMAND, cwd=str(tmp_path), env={})[0] == COMMAND
    assert seen == []


def test_the_environment_chooses_the_mode_the_network_and_the_paths(tmp_path):
    chosen = PluginSandbox.from_environment({})
    assert chosen.mode == "auto"
    chosen = PluginSandbox.from_environment({
        "HYDRA_DEV_SERVER_PLUGIN_SANDBOX": " Required ",
        "HYDRA_DEV_SERVER_PLUGIN_SANDBOX_NETWORK": "1",
        "HYDRA_DEV_SERVER_PLUGIN_SANDBOX_READ_ONLY": "/srv/data",
    })
    assert chosen.mode == "required"
    sandbox = _sandbox("auto", network=True, read_only_paths=("/srv/data",))
    argv = sandbox.wrap(COMMAND, cwd=str(tmp_path), env={})[0]
    assert "--share-net" in argv
    assert "/srv/data" in argv
    with pytest.raises(ConfigValidationError):
        PluginSandbox.from_environment({"HYDRA_DEV_SERVER_PLUGIN_SANDBOX": "maybe"})


def test_a_wrong_mode_in_the_environment_is_a_plugin_error(monkeypatch):
    monkeypatch.setenv("HYDRA_DEV_SERVER_PLUGIN_SANDBOX", "maybe")
    with pytest.raises(PluginError):
        PluginRegistry()


def test_a_required_sandbox_that_is_missing_starts_nothing(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no process may be started")

    monkeypatch.setattr(plugins.subprocess, "Popen", forbidden)
    sandbox = _sandbox("required", installed=False)
    answer = plugins._call_child(b"def register(r):\n    pass\n", MANIFEST, "register", "", "", (), 1.0, sandbox)
    assert "sandbox is required" in answer["error"]
