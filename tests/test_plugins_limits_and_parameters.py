# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_plugins_limits_and_parameters.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The limits of the plugin registry that no other test reached: a `provides` list that is not valid, an isolation mode that does not exist, enabling a
plugin that is already enabled, the parameters a generator may be handed (not an object, not JSON, too long), the ceiling of parallel process calls and the
ceiling of threads that overran in thread mode. Nothing waits and no process is started (evidence: simulator)."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_dev_server import plugins


def manifest(**changes):
    raw = {"name": "demo", "version": "0.1.0", "api_version": 1, "entry": "plugin.py", "provides": ["checks"]}
    raw.update(changes)
    return raw


class ManifestProvidesTests(unittest.TestCase):
    def test_a_provides_list_that_is_empty_repeated_unknown_or_not_a_list_is_refused(self):
        for provides in ([], ["checks", "checks"], ["unknown"], "checks", [3], None):
            with self.assertRaises(plugins.PluginError, msg=repr(provides)):
                plugins.PluginManifest.from_dict(manifest(provides=provides))

    def test_all_the_kinds_together_are_accepted_and_kept_in_order(self):
        parsed = plugins.PluginManifest.from_dict(manifest(provides=list(plugins.KINDS)))
        self.assertEqual(parsed.provides, tuple(plugins.KINDS))


class IsolationTests(unittest.TestCase):
    def test_an_isolation_mode_that_does_not_exist_is_refused(self):
        with self.assertRaises(plugins.PluginError):
            plugins.PluginRegistry(isolation="container")

    def test_the_environment_chooses_the_mode_and_an_empty_value_means_process(self):
        with mock.patch.dict("os.environ", {"HYDRA_DEV_SERVER_PLUGIN_ISOLATION": " THREAD "}):
            self.assertEqual(plugins.PluginRegistry().isolation, "thread")
        with mock.patch.dict("os.environ", {"HYDRA_DEV_SERVER_PLUGIN_ISOLATION": "  "}):
            self.assertEqual(plugins.PluginRegistry().isolation, "process")


class RunLimitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        directory = root / "demo"
        directory.mkdir()
        (directory / "plugin.json").write_text(json.dumps(manifest(provides=["checks", "generators"])), encoding="utf-8")
        (directory / "plugin.py").write_text(
            "def register(registry):\n    registry.add_check('ok', lambda: {'fine': True})\n    registry.add_generator('echo', lambda params: {'filename': 'a.txt', 'content': json_text(params)})\n"
            "def json_text(params):\n    import json\n    return json.dumps(params, sort_keys=True)\n",
            encoding="utf-8",
        )
        self.directory = directory
        self.root = root

    def enabled(self, isolation):
        registry = plugins.PluginRegistry(isolation=isolation)
        registry.discover(self.root)
        parsed = plugins.PluginManifest.from_dict(json.loads((self.directory / "plugin.json").read_text(encoding="utf-8")))
        registry.enable("demo", plugins.plugin_digest(self.directory, parsed))
        return registry

    def test_enabling_a_plugin_that_is_enabled_describes_it_again_and_changes_nothing(self):
        registry = self.enabled("thread")
        first = registry.list()
        parsed = plugins.PluginManifest.from_dict(json.loads((self.directory / "plugin.json").read_text(encoding="utf-8")))
        again = registry.enable("demo", plugins.plugin_digest(self.directory, parsed))
        self.assertEqual(again["state"], plugins.ENABLED)
        self.assertEqual(registry.list(), first)

    def test_the_parameters_of_a_generator_must_be_a_small_json_object(self):
        registry = self.enabled("thread")
        for bad in ([1, 2], "text", 3):
            with self.assertRaises(plugins.PluginError):
                registry.run_generator("demo", "echo", bad)
        with self.assertRaises(plugins.PluginError):
            registry.run_generator("demo", "echo", {"value": object()})
        with self.assertRaises(plugins.PluginError):
            registry.run_generator("demo", "echo", {"value": "x" * (plugins.MAX_PARAMS_BYTES + 1)})
        answer = registry.run_generator("demo", "echo", {"b": 2, "a": 1})
        self.assertEqual(answer["status"], "ok")
        self.assertEqual(answer["result"]["content"], '{"a": 1, "b": 2}')

    def test_no_parameters_means_an_empty_object(self):
        registry = self.enabled("thread")
        self.assertEqual(registry.run_generator("demo", "echo")["result"]["content"], "{}")

    def test_when_every_slot_is_taken_a_process_call_is_refused_without_starting_anything(self):
        registry = self.enabled("process")
        taken = [registry._slots.acquire(blocking=False) for _ in range(plugins.MAX_PARALLEL_RUNS)]
        self.addCleanup(lambda: [registry._slots.release() for ok in taken if ok])
        with mock.patch.object(plugins, "_run_isolated", side_effect=AssertionError("must not start")):
            answer = registry.run_check("demo", "ok")
        self.assertEqual(answer["status"], "error")
        self.assertIn("already running", answer["error"])

    def test_the_slot_is_given_back_when_a_process_call_ends(self):
        registry = self.enabled("process")
        with mock.patch.object(plugins, "_run_isolated", return_value={"status": "ok", "result": {}}):
            for _ in range(plugins.MAX_PARALLEL_RUNS + 2):
                self.assertEqual(registry.run_check("demo", "ok")["status"], "ok")

    def test_too_many_threads_that_overran_stop_new_calls_and_finished_ones_are_forgotten(self):
        registry = self.enabled("thread")
        release = threading.Event()
        self.addCleanup(release.set)
        workers = [threading.Thread(target=release.wait, daemon=True) for _ in range(plugins.MAX_STUCK_THREADS)]
        for worker in workers:
            worker.start()
            registry._remember_stuck(worker)
        answer = registry.run_check("demo", "ok")
        self.assertEqual(answer["status"], "error")
        self.assertIn("still running", answer["error"])
        release.set()
        for worker in workers:
            worker.join(timeout=5)
        self.assertEqual(registry.run_check("demo", "ok")["status"], "ok")


if __name__ == "__main__":
    unittest.main()
