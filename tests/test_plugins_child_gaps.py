# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_plugins_child_gaps.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The ways the isolated process of a plugin can fail that the coverage job lists as not run: it cannot be started, it does not finish in time, it ends
without an answer or answers something that is not JSON or not an object, and the answer of the registration is not what the server expects. The
process is a stand-in (`subprocess.Popen` is replaced), so nothing is started and nothing waits (evidence: simulator)."""
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from hydra_umc_dev_server import plugins

MANIFEST = SimpleNamespace(entry="plugin.py", provides=("checks",))


class FakeProcess:
    def __init__(self, out=b"", timeout_first=False, returncode=3):
        self.out = out
        self.timeout_first = timeout_first
        self.returncode = returncode
        self.pid = 4242
        self.calls = 0

    def communicate(self, request=None, timeout=None):
        self.calls += 1
        if self.timeout_first and self.calls == 1:
            raise subprocess.TimeoutExpired("child", timeout)
        return self.out, b""


def call(process=None, popen_error=None):
    patched = mock.patch.object(plugins.subprocess, "Popen", side_effect=popen_error) if popen_error else mock.patch.object(plugins.subprocess, "Popen", return_value=process)
    with patched, mock.patch.object(plugins, "_kill_group") as kill:
        return plugins._call_child(b"print('x')", MANIFEST, "call", "checks", "a", (1,), 2.0), kill


def marked(payload):
    return b"noise before\n" + plugins._RESULT_MARK.encode() + payload


class CallChildFailureTests(unittest.TestCase):
    def test_a_process_that_cannot_be_started_is_an_error_with_its_reason(self):
        answer, _ = call(popen_error=OSError("no more processes"))
        self.assertEqual(answer, {"error": "the isolated process could not be started: no more processes"})

    def test_a_timeout_kills_the_group_and_says_how_long_it_waited(self):
        process = FakeProcess(timeout_first=True)
        answer, kill = call(process)
        self.assertEqual(answer, {"error": "timeout: it did not finish within 2 s"})
        self.assertEqual(process.calls, 2)  # the second communicate collects what is left
        self.assertGreaterEqual(kill.call_count, 2)

    def test_no_marker_in_the_output_is_an_error_with_the_exit_code(self):
        answer, _ = call(FakeProcess(out=b"traceback only", returncode=137))
        self.assertEqual(answer, {"error": "the isolated process ended without an answer (exit code 137)"})

    def test_an_answer_that_is_not_json_is_refused(self):
        answer, _ = call(FakeProcess(out=marked(b"{not json")))
        self.assertEqual(answer, {"error": "the isolated process answered something that is not JSON"})

    def test_an_answer_that_is_not_an_object_is_refused(self):
        answer, _ = call(FakeProcess(out=marked(b"[1, 2]")))
        self.assertEqual(answer, {"error": "the isolated process answered the wrong shape"})

    def test_an_object_is_returned_as_it_is_and_the_group_is_always_killed(self):
        answer, kill = call(FakeProcess(out=marked(json.dumps({"result": 5}).encode())))
        self.assertEqual(answer, {"result": 5})
        self.assertEqual(kill.call_count, 1)

    def test_a_module_that_is_not_text_cannot_be_handed_over(self):
        answer = plugins._call_child(b"\xff\xfe", MANIFEST, "call", "checks", "a", (), 2.0)
        self.assertIn("cannot be handed to the isolated process", answer["error"])


class RegisterAnswerTests(unittest.TestCase):
    def register(self, answer):
        with mock.patch.object(plugins, "_call_child", return_value=answer):
            return plugins._register_in_child(b"x", MANIFEST)

    def test_the_error_of_the_child_becomes_a_plugin_error(self):
        with self.assertRaises(plugins.PluginError) as caught:
            self.register({"error": "boom"})
        self.assertEqual(str(caught.exception), "boom")

    def test_names_that_are_not_a_mapping_are_refused(self):
        for names in (None, ["tools"], "tools"):
            with self.assertRaises(plugins.PluginError, msg=repr(names)) as caught:
                self.register({"names": names})
            self.assertIn("did not report what the plugin registers", str(caught.exception))

    def test_a_kind_or_a_name_that_is_not_valid_is_refused(self):
        for names in ({"unknown_kind": ["a"]}, {"checks": "a"}, {"checks": [5]}, {"checks": ["has space"]}, {"checks": ["a", "../b"]}, {"checks": ["Upper"]}):
            with self.assertRaises(plugins.PluginError, msg=repr(names)) as caught:
                self.register({"names": names})
            self.assertIn("not valid", str(caught.exception))

    def test_valid_names_are_returned(self):
        self.assertEqual(self.register({"names": {"checks": ["read-file", "write-file"]}}), {"checks": ["read-file", "write-file"]})


if __name__ == "__main__":
    unittest.main()
