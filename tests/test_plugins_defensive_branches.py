# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_plugins_defensive_branches.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The defensive branches of the plugin lifecycle that no other test reaches: a manifest that is not an object, the registration rules for the three
kinds (undeclared kind, invalid name, not callable, registered twice), a root that is not a directory, a plugin whose files cannot be read, a thread-mode
module without `register`, an item that is not offered, a generator that returns text of the wrong type, a plugin function that raises or returns
something that is not JSON, and the kill of a process group. Nothing is started that waits (evidence: simulator)."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_dev_server import plugins


def write_plugin(root: Path, name: str, source: str, provides=("checks",)) -> Path:
    directory = root / name
    directory.mkdir()
    manifest = {"name": name, "version": "0.1.0", "api_version": 1, "entry": "plugin.py", "provides": list(provides)}
    (directory / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "plugin.py").write_text(source, encoding="utf-8")
    return directory


def digest(directory: Path) -> str:
    manifest = plugins.PluginManifest.from_dict(json.loads((directory / "plugin.json").read_text(encoding="utf-8")))
    return plugins.plugin_digest(directory, manifest)


class ManifestTests(unittest.TestCase):
    def test_a_manifest_that_is_not_an_object_is_refused(self):
        for raw in ([], "text", 3, None):
            with self.assertRaises(plugins.PluginError):
                plugins.PluginManifest.from_dict(raw)


class RegistrationTests(unittest.TestCase):
    def test_a_kind_the_manifest_does_not_declare_is_refused_for_each_kind(self):
        registration = plugins._Registration(("checks",))
        with self.assertRaises(plugins.PluginError):
            registration.add_report("one", lambda: {})
        with self.assertRaises(plugins.PluginError):
            registration.add_generator("one", lambda params: {})

    def test_a_name_that_is_not_valid_is_refused(self):
        registration = plugins._Registration(("checks", "reports", "generators"))
        for name in ("Upper", "", "-dash", 5, "a" * 41):
            with self.assertRaises(plugins.PluginError):
                registration.add_check(name, lambda: {})

    def test_something_that_is_not_callable_is_refused(self):
        registration = plugins._Registration(("reports",))
        with self.assertRaises(plugins.PluginError):
            registration.add_report("one", "not a function")

    def test_a_name_registered_twice_is_refused_and_the_first_stays(self):
        registration = plugins._Registration(("checks", "reports", "generators"))
        first = lambda: {}  # noqa: E731
        registration.add_report("one", first)
        registration.add_generator("one", lambda params: {})
        with self.assertRaises(plugins.PluginError):
            registration.add_report("one", lambda: {})
        self.assertIs(registration.reports["one"], first)
        self.assertEqual(sorted(registration.generators), ["one"])


class DiscoveryTests(unittest.TestCase):
    def test_a_root_that_is_not_a_directory_discovers_nothing_and_forgets_the_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_plugin(root, "kept", "def register(registry):\n    pass\n")
            registry = plugins.PluginRegistry(isolation="thread")
            registry.discover(root)
            self.assertEqual([item["name"] for item in registry.list()], ["kept"])
            registry.discover(root / "missing")
            self.assertEqual(registry.list(), [])

    def test_a_directory_without_manifest_and_a_manifest_without_its_module_are_handled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "no-manifest").mkdir()
            (root / "a-file.txt").write_text("x", encoding="utf-8")
            broken = write_plugin(root, "no-module", "")
            (broken / "plugin.py").unlink()
            registry = plugins.PluginRegistry(isolation="thread")
            registry.discover(root)
            self.assertEqual(registry.list(), [])
            self.assertEqual([p["directory"] for p in registry.problems], ["no-module"])
            self.assertIn("is missing", registry.problems[0]["reason"])


class EnableAndRunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def registry_with(self, name, source, provides=("checks",), isolation="thread"):
        directory = write_plugin(self.root, name, source, provides)
        registry = plugins.PluginRegistry(isolation=isolation)
        registry.discover(self.root)
        return registry, directory

    def test_a_plugin_whose_files_cannot_be_read_ends_failed(self):
        registry, directory = self.registry_with("unreadable", "def register(registry):\n    pass\n")
        approved = digest(directory)
        with mock.patch.object(plugins, "read_plugin_bytes", side_effect=OSError("gone")):
            described = registry.enable("unreadable", approved)
        self.assertEqual(described["state"], plugins.FAILED)
        self.assertIn("cannot read the plugin: gone", described["detail"])

    def test_a_thread_mode_module_without_register_ends_failed_with_nothing_registered(self):
        registry, directory = self.registry_with("no-register", "VALUE = 1\n")
        described = registry.enable("no-register", digest(directory))
        self.assertEqual(described["state"], plugins.FAILED)
        self.assertIn("defines no register", described["detail"])
        self.assertEqual(described["checks"], [])

    def test_an_item_that_is_not_offered_is_refused_for_checks_reports_and_generators(self):
        source = "def register(registry):\n    pass\n"
        registry, directory = self.registry_with("empty", source, provides=("checks", "reports", "generators"))
        registry.enable("empty", digest(directory))
        for call in (lambda: registry.run_check("empty", "x"), lambda: registry.run_report("empty", "x"), lambda: registry.run_generator("empty", "x")):
            with self.assertRaises(plugins.PluginError):
                call()

    def test_a_generator_that_returns_text_of_the_wrong_type_is_an_error(self):
        source = (
            "def register(registry):\n"
            "    registry.add_generator('bad-content', lambda params: {'filename': 'a.txt', 'content': 5})\n"
            "    registry.add_generator('bad-name', lambda params: {'filename': '../a.txt', 'content': 'x'})\n"
            "    registry.add_generator('extra', lambda params: {'filename': 'a.txt', 'content': 'x', 'more': 1})\n"
        )
        registry, directory = self.registry_with("generators", source, provides=("generators",))
        registry.enable("generators", digest(directory))
        content = registry.run_generator("generators", "bad-content")
        self.assertEqual(content["status"], "error")
        self.assertIn("content must be text", content["error"])
        name = registry.run_generator("generators", "bad-name")
        self.assertIn("plain file name", name["error"])
        extra = registry.run_generator("generators", "extra")
        self.assertIn("it must return", extra["error"])

    def test_a_function_that_raises_even_system_exit_is_an_error_and_the_plugin_stays_enabled(self):
        source = (
            "def boom():\n    raise SystemExit(3)\n"
            "def fails():\n    raise RuntimeError('broken')\n"
            "def register(registry):\n    registry.add_check('boom', boom)\n    registry.add_check('fails', fails)\n"
        )
        registry, directory = self.registry_with("raises", source)
        registry.enable("raises", digest(directory))
        self.assertEqual(registry.run_check("raises", "fails"), {"status": "error", "error": "RuntimeError: broken"})
        self.assertEqual(registry.run_check("raises", "boom")["status"], "error")
        self.assertEqual(registry.list()[0]["state"], plugins.ENABLED)

    def test_a_result_that_is_not_json_is_an_error(self):
        source = "def register(registry):\n    registry.add_report('odd', lambda: {'value': {1, 2}})\n"
        registry, directory = self.registry_with("not-json", source, provides=("reports",))
        registry.enable("not-json", digest(directory))
        answer = registry.run_report("not-json", "odd")
        self.assertEqual(answer, {"status": "error", "error": "the report returned something that is not JSON"})

    def test_a_result_over_the_limit_is_an_error(self):
        source = "def register(registry):\n    registry.add_check('big', lambda: {'text': 'x' * 300000})\n"
        registry, directory = self.registry_with("big", source)
        registry.enable("big", digest(directory))
        answer = registry.run_check("big", "big")
        self.assertEqual(answer["status"], "error")
        self.assertIn("more than", answer["error"])

    def test_run_bounded_works_without_an_overrun_callback(self):
        import threading
        release = threading.Event()
        self.addCleanup(release.set)
        answer = plugins._run_bounded(lambda: release.wait(5), (), 0.05, "check", plugins._as_dict_result)
        self.assertEqual(answer["status"], "error")
        self.assertIn("did not finish within", answer["error"])


class ChildSupportTests(unittest.TestCase):
    def test_the_environment_of_the_child_is_scrubbed_and_points_at_the_scratch_folder(self):
        with mock.patch.dict(os.environ, {"SECRET_VALUE": "no", "SYSTEMROOT": "C:\\Windows"}, clear=False):
            env = plugins._child_environment("/scratch")
        self.assertNotIn("SECRET_VALUE", env)
        self.assertEqual(env["HOME"], "/scratch")
        self.assertEqual(env["TMPDIR"], "/scratch")

    def test_the_environment_of_the_child_on_windows_keeps_what_the_interpreter_needs(self):
        with mock.patch.object(plugins.os, "name", "nt"), mock.patch.dict(os.environ, {"SYSTEMROOT": "C:\\Windows", "PATH": "C:\\bin"}, clear=True):
            env = plugins._child_environment("S")
        self.assertEqual(env["SYSTEMROOT"], "C:\\Windows")
        self.assertNotIn("WINDIR", env)
        self.assertEqual((env["TEMP"], env["TMP"], env["PATH"]), ("S", "S", "C:\\bin"))

    def test_the_whole_group_is_killed_on_posix_and_a_failure_to_kill_is_ignored(self):
        process = mock.Mock(pid=77)
        with mock.patch.object(plugins.os, "name", "posix"), mock.patch.object(plugins.signal, "SIGKILL", 9, create=True), mock.patch.object(plugins.os, "killpg", create=True) as killpg:
            plugins._kill_group(process)
            killpg.assert_called_once_with(77, 9)
        with mock.patch.object(plugins.os, "name", "posix"), mock.patch.object(plugins.signal, "SIGKILL", 9, create=True), mock.patch.object(plugins.os, "killpg", create=True, side_effect=ProcessLookupError):
            plugins._kill_group(process)  # already gone: no error

    def test_the_process_is_killed_directly_off_posix_and_a_failure_is_ignored(self):
        process = mock.Mock(pid=77)
        with mock.patch.object(plugins.os, "name", "nt"):
            plugins._kill_group(process)
            process.kill.assert_called_once_with()
            process.kill.side_effect = PermissionError
            plugins._kill_group(process)

    def test_a_module_that_is_not_text_cannot_be_handed_to_the_child(self):
        manifest = plugins.PluginManifest("odd", "0.1.0", 1, "plugin.py")
        answer = plugins._call_child(b"\xff\xfe", manifest, "register", "", "", (), 1.0)
        self.assertIn("cannot be handed to the isolated process", answer["error"])

    def test_the_registration_answer_must_name_what_the_plugin_registers(self):
        manifest = plugins.PluginManifest("odd", "0.1.0", 1, "plugin.py")
        for answer in ({"names": "x"}, {}, {"names": {"unknown": []}}, {"names": {"checks": "x"}}, {"names": {"checks": ["Bad Name"]}}):
            with mock.patch.object(plugins, "_call_child", return_value=answer):
                with self.assertRaises(plugins.PluginError):
                    plugins._register_in_child(b"", manifest)
        with mock.patch.object(plugins, "_call_child", return_value={"error": "boom"}):
            with self.assertRaisesRegex(plugins.PluginError, "boom"):
                plugins._register_in_child(b"", manifest)


class DigestTests(unittest.TestCase):
    def test_the_digest_covers_the_names_and_the_bytes_in_order(self):
        manifest = plugins.PluginManifest("odd", "0.1.0", 1, "plugin.py")
        expected = hashlib.sha256(b"plugin.json\0" + b"M" + b"plugin.py\0" + b"E").hexdigest()
        self.assertEqual(plugins.digest_of(manifest, b"M", b"E"), expected)
        self.assertNotEqual(plugins.digest_of(manifest, b"E", b"M"), expected)


if __name__ == "__main__":
    unittest.main()
