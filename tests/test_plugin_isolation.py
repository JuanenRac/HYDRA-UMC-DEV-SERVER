# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_plugin_isolation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Plugins run in their own process by default: they see nothing of the API process, run the
approved bytes only, are killed when they overrun and cannot pile up."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from hydra_umc_dev_server import plugins
from hydra_umc_dev_server.plugins import ENABLED, FAILED, PluginError, PluginRegistry

SOURCE = """
import os, sys
COUNTER = 0

def register(registry):
    def env():
        return {"keys": sorted(os.environ), "cwd_name": os.path.basename(os.getcwd()), "home_is_cwd": os.environ.get("HOME") == os.getcwd()}
    def count():
        global COUNTER
        COUNTER += 1
        return {"n": COUNTER}
    def sibling():
        import secret_neighbour
        return {"got": secret_neighbour.VALUE}
    def hang():
        import time
        time.sleep(60)
        return {}
    def chatty():
        print("noise before the answer")
        return {"ok": True}
    registry.add_check("env", env)
    registry.add_check("count", count)
    registry.add_check("sibling", sibling)
    registry.add_check("hang", hang)
    registry.add_check("chatty", chatty)
"""


def _make(root: Path, source: str = SOURCE) -> Path:
    directory = root / "demo-dir"
    directory.mkdir()
    (directory / "plugin.json").write_text(json.dumps({"name": "demo", "version": "0.1.0", "api_version": 1, "entry": "plugin.py"}), encoding="utf-8")
    (directory / "plugin.py").write_text(source, encoding="utf-8")
    return directory


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.directory = _make(self.root)
        self.registry = PluginRegistry()
        self.registry.discover(self.root)
        self.sha = self.registry.list()[0]["sha256"]

    def _enable(self) -> None:
        self.assertEqual(self.registry.enable("demo", self.sha)["state"], ENABLED)

    def test_process_isolation_is_the_default(self):
        self.assertEqual(self.registry.isolation, "process")
        with self.assertRaises(PluginError):
            PluginRegistry(isolation="docker")

    def test_the_plugin_sees_no_secret_of_the_api_process_and_runs_in_an_empty_directory(self):
        os.environ["HYDRA_TEST_API_TOKEN"] = "do-not-leak"
        self.addCleanup(os.environ.pop, "HYDRA_TEST_API_TOKEN", None)
        self._enable()
        result = self.registry.run_check("demo", "env")
        self.assertEqual(result["status"], "ok", result)
        keys = result["result"]["keys"]
        self.assertNotIn("HYDRA_TEST_API_TOKEN", keys)
        self.assertTrue(result["result"]["cwd_name"].startswith("hydra-plugin-"))
        if os.name == "posix":
            self.assertTrue(result["result"]["home_is_cwd"])

    def test_a_plugin_keeps_no_state_between_calls(self):
        self._enable()
        first = self.registry.run_check("demo", "count")
        second = self.registry.run_check("demo", "count")
        self.assertEqual((first["result"]["n"], second["result"]["n"]), (1, 1))

    def test_a_module_next_to_the_plugin_cannot_be_imported(self):
        (self.directory / "secret_neighbour.py").write_text("VALUE = 'x'\n", encoding="utf-8")
        self._enable()
        result = self.registry.run_check("demo", "sibling")
        self.assertEqual(result["status"], "error")
        self.assertIn("secret_neighbour", result["error"])

    def test_only_the_approved_bytes_run_even_if_the_file_changes_after_approval(self):
        self._enable()
        (self.directory / "plugin.py").write_text(SOURCE.replace('"n": COUNTER', '"n": 999'), encoding="utf-8")
        self.assertEqual(self.registry.run_check("demo", "count")["result"]["n"], 1)

    def test_a_file_changed_between_discovery_and_enable_is_refused(self):
        (self.directory / "plugin.py").write_text(SOURCE + "\n# changed\n", encoding="utf-8")
        record = self.registry.enable("demo", self.sha)
        self.assertEqual(record["state"], FAILED)
        self.assertIn("SHA-256", record["detail"])

    def test_an_overrunning_call_is_killed_and_reported(self):
        self._enable()
        started = time.monotonic()
        result = self.registry.run_check("demo", "hang", timeout=1.0)
        self.assertEqual(result["status"], "error")
        self.assertIn("did not finish", result["error"])
        self.assertLess(time.monotonic() - started, 10)

    def test_what_the_plugin_prints_cannot_be_taken_for_the_answer(self):
        self._enable()
        result = self.registry.run_check("demo", "chatty")
        self.assertEqual(result, {"status": "ok", "result": {"ok": True}})

    def test_no_more_than_the_allowed_number_of_calls_run_at_once(self):
        self._enable()
        old = plugins.MAX_PARALLEL_RUNS
        registry = PluginRegistry()
        registry.discover(self.root)
        registry.enable("demo", self.sha)
        for _ in range(old):
            self.assertTrue(registry._slots.acquire(blocking=False))
        try:
            refused = registry.run_check("demo", "count")
        finally:
            for _ in range(old):
                registry._slots.release()
        self.assertEqual(refused["status"], "error")
        self.assertIn("already running", refused["error"])

    def test_parallel_enable_disable_and_rescan_do_not_break_the_registry(self):
        errors: list[BaseException] = []

        def worker():
            try:
                for _ in range(5):
                    self.registry.discover(self.root)
                    self.registry.list()
                    try:
                        self.registry.enable("demo", self.sha)
                    except PluginError:
                        pass
                    self.registry.disable("demo")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        self.assertEqual(errors, [])


class ThreadModeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _make(self.root, "import time\ndef register(r):\n    r.add_check('hang', lambda: time.sleep(5) or {})\n    r.add_check('ok', lambda: {'x': 1})\n")
        self.registry = PluginRegistry(isolation="thread")
        self.registry.discover(self.root)
        self.registry.enable("demo", self.registry.list()[0]["sha256"])

    def test_the_approved_bytes_are_what_gets_executed(self):
        self.assertEqual(self.registry.run_check("demo", "ok"), {"status": "ok", "result": {"x": 1}})

    def test_overrunning_threads_are_counted_and_new_calls_are_refused_past_the_limit(self):
        old = plugins.MAX_STUCK_THREADS
        plugins.MAX_STUCK_THREADS = 2
        self.addCleanup(setattr, plugins, "MAX_STUCK_THREADS", old)
        for _ in range(2):
            self.assertIn("did not finish", self.registry.run_check("demo", "hang", timeout=0.05)["error"])
        refused = self.registry.run_check("demo", "ok")
        self.assertEqual(refused["status"], "error")
        self.assertIn("still running", refused["error"])


if __name__ == "__main__":
    unittest.main()
