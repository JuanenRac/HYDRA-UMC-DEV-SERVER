# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_plugins.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import json
import tempfile
import time
import unittest
from pathlib import Path

from hydra_umc_dev_server.plugins import (
    DISABLED,
    DISCOVERED,
    ENABLED,
    FAILED,
    PluginError,
    PluginManifest,
    PluginRegistry,
)

GOOD_SOURCE = """
def register(registry):
    registry.add_check("ping", lambda: {"pong": True})
    registry.add_check("boom", lambda: 1 / 0)
    registry.add_check("not-json", lambda: {"x": object()})
    registry.add_check("not-a-dict", lambda: [1, 2])
"""


def _write_plugin(root: Path, directory: str, *, name: str = "demo", source: str = GOOD_SOURCE, **manifest_overrides) -> Path:
    plugin_dir = root / directory
    plugin_dir.mkdir()
    manifest = {"name": name, "version": "0.1.0", "api_version": 1, "entry": "plugin.py"}
    manifest.update(manifest_overrides)
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    return plugin_dir


class PluginTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _registry(self, **kwargs) -> tuple[PluginRegistry, str]:
        _write_plugin(self.root, "demo-dir", **kwargs)
        registry = PluginRegistry()
        registry.discover(self.root)
        return registry, registry.list()[0]["sha256"]

    def test_discovery_imports_nothing_and_leaves_the_plugin_inert(self):
        marker = self.root / "imported.txt"
        registry, _ = self._registry(source=f"open({str(marker)!r}, 'w').write('x')\ndef register(r): pass\n")
        self.assertFalse(marker.exists())
        self.assertEqual(registry.list()[0]["state"], DISCOVERED)
        self.assertEqual(registry.list()[0]["checks"], [])

    def test_enabling_needs_the_approved_digest(self):
        registry, digest = self._registry()
        refused = registry.enable("demo", "0" * 64)
        self.assertEqual(refused["state"], FAILED)
        self.assertIn("SHA-256", refused["detail"])
        self.assertEqual(registry.enable("demo", digest.upper())["state"], ENABLED)

    def test_a_plugin_changed_after_approval_is_refused(self):
        registry, digest = self._registry()
        (self.root / "demo-dir" / "plugin.py").write_text(GOOD_SOURCE + "\n# edited\n", encoding="utf-8")
        self.assertEqual(registry.enable("demo", digest)["state"], FAILED)

    def test_enabled_checks_run_and_disabled_ones_do_not(self):
        registry, digest = self._registry()
        registry.enable("demo", digest)
        self.assertEqual(registry.run_check("demo", "ping"), {"status": "ok", "result": {"pong": True}})
        registry.disable("demo")
        self.assertEqual(registry.list()[0]["state"], DISABLED)
        with self.assertRaises(PluginError):
            registry.run_check("demo", "ping")

    def test_a_check_that_raises_or_returns_junk_is_an_error_not_a_result(self):
        registry, digest = self._registry()
        registry.enable("demo", digest)
        self.assertEqual(registry.run_check("demo", "boom")["status"], "error")
        self.assertIn("ZeroDivisionError", registry.run_check("demo", "boom")["error"])
        self.assertEqual(registry.run_check("demo", "not-json")["status"], "error")
        self.assertEqual(registry.run_check("demo", "not-a-dict")["status"], "error")

    def test_a_check_that_overruns_is_cut_off(self):
        source = "import time\ndef register(r):\n    r.add_check('slow', lambda: (time.sleep(2), {})[1])\n"
        registry, digest = self._registry(source=source)
        registry.enable("demo", digest)
        started = time.monotonic()
        outcome = registry.run_check("demo", "slow", timeout=0.2)
        self.assertEqual(outcome["status"], "error")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_a_register_that_raises_fails_the_plugin_without_raising(self):
        registry, digest = self._registry(source="def register(r):\n    raise RuntimeError('nope')\n")
        described = registry.enable("demo", digest)
        self.assertEqual(described["state"], FAILED)
        self.assertIn("RuntimeError", described["detail"])

    def test_a_module_without_register_or_with_a_bad_check_name_fails(self):
        registry, digest = self._registry(source="x = 1\n")
        self.assertEqual(registry.enable("demo", digest)["state"], FAILED)
        registry2 = PluginRegistry()
        other = Path(self._tmp.name) / "second"
        other.mkdir()
        _write_plugin(other, "p", source="def register(r):\n    r.add_check('Bad Name', lambda: {})\n")
        registry2.discover(other)
        self.assertEqual(registry2.enable("demo", registry2.list()[0]["sha256"])["state"], FAILED)

    def test_broken_plugins_are_reported_and_do_not_hide_good_ones(self):
        _write_plugin(self.root, "good")
        (self.root / "bad").mkdir()
        (self.root / "bad" / "plugin.json").write_text("{not json", encoding="utf-8")
        _write_plugin(self.root, "escape", name="escape", entry="../evil.py")
        _write_plugin(self.root, "old-api", name="old", api_version=2)
        registry = PluginRegistry()
        registry.discover(self.root)
        self.assertEqual([p["name"] for p in registry.list()], ["demo"])
        self.assertEqual({p["directory"] for p in registry.problems}, {"bad", "escape", "old-api"})

    def test_two_directories_may_not_claim_the_same_name(self):
        _write_plugin(self.root, "a")
        _write_plugin(self.root, "b")
        registry = PluginRegistry()
        registry.discover(self.root)
        self.assertEqual(len(registry.list()), 1)
        self.assertEqual(len(registry.problems), 1)

    def test_rediscovering_an_unchanged_plugin_keeps_its_state_and_a_changed_one_resets(self):
        registry, digest = self._registry()
        registry.enable("demo", digest)
        registry.discover(self.root)
        self.assertEqual(registry.list()[0]["state"], ENABLED)
        (self.root / "demo-dir" / "plugin.py").write_text(GOOD_SOURCE + "\n# edited\n", encoding="utf-8")
        registry.discover(self.root)
        self.assertEqual(registry.list()[0]["state"], DISCOVERED)

    def test_unknown_plugin_and_bad_manifest_values_are_refused(self):
        registry = PluginRegistry()
        with self.assertRaises(PluginError):
            registry.enable("nothing", "0" * 64)
        for change in ({"name": "Bad Name"}, {"version": "1.2"}, {"api_version": True}, {"entry": "a/b.py"}, {"extra": 1}):
            raw = {"name": "x", "version": "1.0.0", "api_version": 1, "entry": "p.py", **change}
            with self.assertRaises(PluginError, msg=change):
                PluginManifest.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
