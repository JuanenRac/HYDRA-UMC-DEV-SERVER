# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_cli_run_paths.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The commands of the command line that run something for real: a task in its workspace, the token of a node and the start of the API (evidence: simulator).

The task is the real recipe machinery against the real workspace on disk; `true` and `false` stand in for a build. Nothing talks to a network or to the HYDRA-UMC-SERVER.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_dev_server import cli
from hydra_umc_dev_server.cli import main

POSIX = os.name == "posix"


def run_main(argv):
    """(exit code, standard output, standard error) of one call of `main`."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def write_json(path, document):
    Path(path).write_text(json.dumps(document), encoding="utf-8")
    return str(path)


@unittest.skipUnless(POSIX, "the workspace base of a task must be a POSIX absolute path")
class TaskRunCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.base = str(self.root / "ws")
        self.policy = write_json(self.root / "policy.json", {"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": ["true", "false"]})

    def recipe(self, command, task_id="cov-task-0001"):
        return write_json(self.root / f"{task_id}.json", {"task_id": task_id, "repo": "R", "revision": "v0.0.4", "command": command, "timeout_seconds": 30, "input_paths": []})

    def run_task(self, command, *extra, task_id="cov-task-0001"):
        return run_main(["task", "run", self.recipe(command, task_id), "--policy", self.policy, "--workspace-base", self.base, *extra])

    def test_a_task_that_succeeds_is_reported_and_its_workspace_removed(self):
        code, out, err = self.run_task(["true"])
        self.assertEqual(code, 0, err)
        document = json.loads(out)
        self.assertEqual((document["outcome"], document["exit_code"]), ("completed", 0))
        self.assertTrue(document["workspace_removed"])
        self.assertIsNone(document["staged_commit"])
        self.assertIn("no source is configured", err)  # nothing was staged: the workspace stayed empty

    def test_a_task_that_fails_exits_nonzero_and_keeps_its_workspace(self):
        code, out, _ = self.run_task(["false"])
        self.assertEqual(code, 1)
        document = json.loads(out)
        self.assertEqual((document["outcome"], document["exit_code"]), ("completed", 1))
        self.assertFalse(document["workspace_removed"])

    def test_the_workspace_of_a_failed_task_is_replaced_only_when_asked(self):
        self.assertEqual(self.run_task(["false"])[0], 1)
        code, out, err = self.run_task(["false"])
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", err)  # the old workspace is in the way
        self.assertEqual(out, "")
        code, out, err = self.run_task(["false"], "--replace-workspace")
        self.assertEqual(code, 1)
        self.assertNotIn("REFUSED", err)
        self.assertEqual(json.loads(out)["outcome"], "completed")

    def test_a_command_the_policy_does_not_allow_is_rejected_and_nothing_runs(self):
        code, out, _ = self.run_task(["echo", "hello"])
        self.assertEqual(code, 1)
        document = json.loads(out)
        self.assertEqual(document["outcome"], "rejected")
        self.assertIsNone(document["exit_code"])

    def test_a_workspace_base_that_is_not_absolute_is_refused(self):
        code, out, err = run_main(["task", "run", self.recipe(["true"]), "--policy", self.policy, "--workspace-base", "relative/ws"])
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", err)
        self.assertEqual(out, "")


class TaskValidateCommandTests(unittest.TestCase):
    def test_a_recipe_the_policy_does_not_allow_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = write_json(Path(tmp) / "policy.json", {"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": ["pytest"]})
            recipe = write_json(Path(tmp) / "recipe.json", {"task_id": "cov-task-0002", "repo": "R", "revision": "v0.0.4", "command": ["make", "all"], "timeout_seconds": 30, "input_paths": []})
            code, out, err = run_main(["task", "validate", recipe, "--policy", policy])
            self.assertEqual(code, 1)
            self.assertIn("INVALID", err)
            self.assertEqual(out, "")


class NodeTokenCommandTests(unittest.TestCase):
    def test_a_token_is_issued_to_a_new_file_and_a_second_one_to_the_same_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens, out_file = str(Path(tmp) / "tokens.json"), str(Path(tmp) / "node-a.token")
            code, out, err = run_main(["node-token", "issue", "node-a", "--tokens-file", tokens, "--out", out_file])
            self.assertEqual(code, 0, err)
            self.assertIn("node-a", out)
            written = Path(out_file).read_text(encoding="utf-8").strip()
            self.assertNotIn(written, out)  # the token itself is never printed
            self.assertNotIn(written, Path(tokens).read_text(encoding="utf-8"))  # only its hash is kept
            code, out, err = run_main(["node-token", "issue", "node-a", "--tokens-file", tokens, "--out", out_file])
            self.assertEqual(code, 1)
            self.assertIn("ERROR", err)

    def test_a_node_name_with_odd_characters_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_main(["node-token", "issue", "../etc", "--tokens-file", str(Path(tmp) / "t.json"), "--out", str(Path(tmp) / "o.token")])
            self.assertEqual(code, 1)
            self.assertIn("ERROR", err)

    def test_a_node_is_revoked_and_the_second_revocation_is_refused_or_harmless(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens = str(Path(tmp) / "tokens.json")
            self.assertEqual(run_main(["node-token", "issue", "node-b", "--tokens-file", tokens, "--out", str(Path(tmp) / "b.token")])[0], 0)
            code, out, _ = run_main(["node-token", "revoke", "node-b", "--tokens-file", tokens])
            self.assertEqual(code, 0)
            self.assertIn("node-b is revoked", out)
            code, _, err = run_main(["node-token", "revoke", "node-b", "--tokens-file", tokens])
            self.assertIn(code, (0, 1))
            if code == 1:
                self.assertIn("ERROR", err)


class ServeCommandTests(unittest.TestCase):
    def arguments(self, tmp, *extra):
        return ["serve", "--workspace-root", tmp, "--plugins-root", tmp, "--port", "0", *extra]

    def test_a_channel_file_that_cannot_be_read_stops_the_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_main(self.arguments(tmp, "--node-channel", str(Path(tmp) / "missing.json")))
            self.assertEqual(code, 1)
            self.assertIn("cannot start the API", err)

    def test_without_a_token_the_api_does_not_start(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HYDRA_UMC_DEV_SERVER_TOKEN": ""}):
            code, _, err = run_main(self.arguments(tmp))
            self.assertEqual(code, 1)
            self.assertIn("cannot start the API", err)

    def test_the_token_is_read_from_a_file_and_an_interrupt_ends_the_service_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "api.token"
            token_file.write_text("a-token-of-more-than-24-characters\n", encoding="utf-8")
            seen = {}

            class StubServer:
                server_address = ("127.0.0.1", 4321)
                identity_key = None
                health_open = False

                def __init__(self, address, **options):
                    seen["address"], seen["options"] = address, options

                def serve_forever(self):
                    raise KeyboardInterrupt

                def server_close(self):
                    seen["closed"] = True

            with mock.patch.object(cli, "DevServer", StubServer):
                code, out, _ = run_main(self.arguments(tmp, "--token-file", str(token_file), "--public-health-detail"))
            self.assertEqual(code, 0)
            self.assertIn("on http://127.0.0.1:4321", out)
            self.assertEqual(seen["options"]["token"], "a-token-of-more-than-24-characters")
            self.assertTrue(seen["options"]["public_health_detail"])
            self.assertTrue(seen["closed"])


if __name__ == "__main__":
    unittest.main()
