# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_plugin_kinds.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Plugins that provide reports and generators: the manifest field, the
lifecycle, the sandbox limits, failure isolation, the HTTP routes, the CLI
and the shipped example plugins."""
import contextlib
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from hydra_umc_dev_server.api import DevServer, MAX_BODY_BYTES
from hydra_umc_dev_server.cli import main
from hydra_umc_dev_server.plugins import (
    ENABLED,
    FAILED,
    MAX_PARAMS_BYTES,
    MAX_RESULT_BYTES,
    PluginError,
    PluginManifest,
    PluginRegistry,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"
TOKEN = "t" * 32

ALL_KINDS = """
def register(r):
    r.add_check("ping", lambda: {"pong": True})
    r.add_report("state", lambda: {"n": 3})
    r.add_report("boom", lambda: 1 / 0)
    r.add_report("big", lambda: {"x": "y" * (300 * 1024)})
    r.add_report("not-json", lambda: {"x": object()})
    r.add_report("not-a-dict", lambda: [1])
    r.add_generator("hello", lambda p: {"filename": "hello.txt", "content": "hi " + str(p.get("who", "you"))})
    r.add_generator("bad-name", lambda p: {"filename": "../x.txt", "content": "x"})
    r.add_generator("absolute", lambda p: {"filename": "/etc/passwd", "content": "x"})
    r.add_generator("extra-field", lambda p: {"filename": "a.txt", "content": "x", "mode": 0o777})
    r.add_generator("binary", lambda p: {"filename": "a.bin", "content": b"x"})
    r.add_generator("raises", lambda p: (_ for _ in ()).throw(SystemExit(3)))
    r.add_generator("huge", lambda p: {"filename": "a.txt", "content": "z" * (300 * 1024)})
    r.add_generator("mutates", lambda p: (p.update({"hacked": True}), {"filename": "m.txt", "content": "ok"})[1])
"""


def _write(root: Path, directory: str, source: str, **manifest) -> Path:
    plugin_dir = root / directory
    plugin_dir.mkdir(parents=True, exist_ok=True)
    body = {"name": directory, "version": "0.1.0", "api_version": 1, "entry": "plugin.py"}
    body.update(manifest)
    (plugin_dir / "plugin.json").write_text(json.dumps(body), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    return plugin_dir


class ManifestTests(unittest.TestCase):
    BASE = {"name": "p", "version": "1.0.0", "api_version": 1, "entry": "plugin.py"}

    def test_provides_defaults_to_checks_so_older_plugins_keep_working(self):
        self.assertEqual(PluginManifest.from_dict(self.BASE).provides, ("checks",))

    def test_provides_accepts_each_kind_once(self):
        manifest = PluginManifest.from_dict({**self.BASE, "provides": ["reports", "generators"]})
        self.assertEqual(manifest.provides, ("reports", "generators"))

    def test_bad_provides_values_are_refused(self):
        for bad in ([], "reports", ["reports", "reports"], ["widgets"], [1], None):
            with self.assertRaises(PluginError, msg=repr(bad)):
                PluginManifest.from_dict({**self.BASE, "provides": bad})


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _enabled(self, source=ALL_KINDS, provides=("checks", "reports", "generators")) -> PluginRegistry:
        _write(self.root, "demo", source, provides=list(provides))
        registry = PluginRegistry()
        registry.discover(self.root)
        described = registry.enable("demo", registry.list()[0]["sha256"])
        self.assertEqual(described["state"], ENABLED, described)
        return registry

    def test_enabling_lists_every_kind_and_disabling_removes_them(self):
        registry = self._enabled()
        described = registry.list()[0]
        self.assertEqual(described["provides"], ["checks", "reports", "generators"])
        self.assertIn("state", described["reports"])
        self.assertIn("hello", described["generators"])
        registry.disable("demo")
        described = registry.list()[0]
        self.assertEqual((described["checks"], described["reports"], described["generators"]), ([], [], []))
        with self.assertRaises(PluginError):
            registry.run_report("demo", "state")
        with self.assertRaises(PluginError):
            registry.run_generator("demo", "hello")

    def test_a_report_runs_and_an_unknown_one_is_refused(self):
        registry = self._enabled()
        self.assertEqual(registry.run_report("demo", "state"), {"status": "ok", "result": {"n": 3}})
        with self.assertRaises(PluginError):
            registry.run_report("demo", "ghost")
        with self.assertRaises(PluginError):
            registry.run_report("demo", "ping")  # a check is not a report

    def test_a_generator_returns_its_file_with_the_parameters(self):
        registry = self._enabled()
        self.assertEqual(
            registry.run_generator("demo", "hello", {"who": "Ana"}),
            {"status": "ok", "result": {"filename": "hello.txt", "content": "hi Ana"}},
        )
        self.assertEqual(registry.run_generator("demo", "hello")["result"]["content"], "hi you")

    def test_a_kind_the_manifest_does_not_declare_fails_the_whole_plugin(self):
        _write(self.root, "demo", ALL_KINDS, provides=["reports"])
        registry = PluginRegistry()
        registry.discover(self.root)
        described = registry.enable("demo", registry.list()[0]["sha256"])
        self.assertEqual(described["state"], FAILED)
        self.assertIn("does not declare", described["detail"])
        self.assertEqual((described["checks"], described["reports"], described["generators"]), ([], [], []))

    def test_a_register_that_raises_halfway_leaves_nothing_registered(self):
        source = "def register(r):\n    r.add_report('a', lambda: {})\n    r.add_generator('g', lambda p: {})\n    raise RuntimeError('late')\n"
        _write(self.root, "demo", source, provides=["reports", "generators"])
        registry = PluginRegistry()
        registry.discover(self.root)
        described = registry.enable("demo", registry.list()[0]["sha256"])
        self.assertEqual(described["state"], FAILED)
        self.assertEqual((described["reports"], described["generators"]), ([], []))

    def test_duplicate_and_badly_named_items_fail_the_plugin(self):
        for body in (
            "r.add_report('a', lambda: {})\n    r.add_report('a', lambda: {})",
            "r.add_generator('Bad Name', lambda p: {})",
            "r.add_report('ok', 5)",
        ):
            with self.subTest(body=body):
                shutil.rmtree(self.root / "demo", ignore_errors=True)
                _write(self.root, "demo", f"def register(r):\n    {body}\n", provides=["reports", "generators"])
                registry = PluginRegistry()
                registry.discover(self.root)
                self.assertEqual(registry.enable("demo", registry.list()[0]["sha256"])["state"], FAILED)

    def test_a_report_may_share_a_name_with_a_check_or_a_generator(self):
        source = (
            "def register(r):\n    r.add_check('x', lambda: {})\n    r.add_report('x', lambda: {})\n"
            "    r.add_generator('x', lambda p: {'filename': 'f', 'content': ''})\n"
        )
        registry = self._enabled(source)
        self.assertEqual(registry.run_check("demo", "x")["status"], "ok")
        self.assertEqual(registry.run_report("demo", "x")["status"], "ok")
        self.assertEqual(registry.run_generator("demo", "x")["status"], "ok")

    def test_failure_of_a_report_is_an_error_entry_and_the_plugin_stays_enabled(self):
        registry = self._enabled()
        for name in ("boom", "big", "not-json", "not-a-dict"):
            self.assertEqual(registry.run_report("demo", name)["status"], "error", name)
        self.assertIn("ZeroDivisionError", registry.run_report("demo", "boom")["error"])
        self.assertIn(str(MAX_RESULT_BYTES), registry.run_report("demo", "big")["error"])
        self.assertEqual(registry.list()[0]["state"], ENABLED)
        self.assertEqual(registry.run_report("demo", "state")["status"], "ok")

    def test_every_malformed_generator_answer_is_an_error_entry(self):
        registry = self._enabled()
        for name in ("bad-name", "absolute", "extra-field", "binary", "raises", "huge"):
            outcome = registry.run_generator("demo", name)
            self.assertEqual(outcome["status"], "error", name)
        self.assertEqual(registry.list()[0]["state"], ENABLED)

    def test_a_plugin_exiting_the_interpreter_does_not_take_the_server_down(self):
        registry = self._enabled()
        outcome = registry.run_generator("demo", "raises")
        self.assertIn("SystemExit", outcome["error"])

    def test_an_overrunning_report_or_generator_is_cut_off(self):
        source = (
            "import time\ndef register(r):\n"
            "    r.add_report('slow', lambda: (time.sleep(2), {})[1])\n"
            "    r.add_generator('slow', lambda p: (time.sleep(2), {})[1])\n"
        )
        registry = self._enabled(source, provides=("reports", "generators"))
        started = time.monotonic()
        self.assertEqual(registry.run_report("demo", "slow", timeout=0.2)["status"], "error")
        self.assertEqual(registry.run_generator("demo", "slow", timeout=0.2)["status"], "error")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_generator_parameters_are_bounded_and_must_be_an_object_of_json(self):
        registry = self._enabled()
        with self.assertRaises(PluginError):
            registry.run_generator("demo", "hello", {"who": "x" * (MAX_PARAMS_BYTES + 1)})
        with self.assertRaises(PluginError):
            registry.run_generator("demo", "hello", ["not", "an", "object"])  # type: ignore[arg-type]
        with self.assertRaises(PluginError):
            registry.run_generator("demo", "hello", {"who": object()})

    def test_a_generator_gets_a_copy_of_its_parameters(self):
        registry = self._enabled()
        params = {"who": "x"}
        self.assertEqual(registry.run_generator("demo", "mutates", params)["status"], "ok")
        self.assertEqual(params, {"who": "x"})

    def test_one_failing_plugin_does_not_affect_another(self):
        _write(self.root, "good", ALL_KINDS, provides=["checks", "reports", "generators"])
        _write(self.root, "bad", "def register(r):\n    raise RuntimeError('x')\n", provides=["reports"])
        registry = PluginRegistry()
        registry.discover(self.root)
        digests = {item["name"]: item["sha256"] for item in registry.list()}
        self.assertEqual(registry.enable("bad", digests["bad"])["state"], FAILED)
        self.assertEqual(registry.enable("good", digests["good"])["state"], ENABLED)
        self.assertEqual(registry.run_report("good", "state")["status"], "ok")
        with self.assertRaises(PluginError):
            registry.run_report("bad", "state")

    def test_a_changed_plugin_is_still_refused_whatever_it_provides(self):
        registry = self._enabled()
        registry.disable("demo")
        digest = registry.list()[0]["sha256"]
        (self.root / "demo" / "plugin.py").write_text(ALL_KINDS + "\n# edited\n", encoding="utf-8")
        self.assertEqual(registry.enable("demo", digest)["state"], FAILED)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "ws").mkdir()
        self.plugins = root / "plugins"
        _write(self.plugins, "demo", ALL_KINDS, provides=["checks", "reports", "generators"])
        self.server = DevServer(("127.0.0.1", 0), token=TOKEN, workspace_root=root / "ws", plugins_root=self.plugins)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)
        digest = self._call("GET", "/v1/plugins")[1]["plugins"][0]["sha256"]
        self._call("POST", "/v1/plugins/demo/enable", {"sha256": digest})

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()

    def _call(self, method, path, body=None, token=TOKEN, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_the_listing_shows_reports_and_generators(self):
        plugin = self._call("GET", "/v1/plugins")[1]["plugins"][0]
        self.assertIn("state", plugin["reports"])
        self.assertIn("hello", plugin["generators"])
        self.assertEqual(plugin["provides"], ["checks", "reports", "generators"])

    def test_a_report_over_http(self):
        self.assertEqual(self._call("POST", "/v1/plugins/demo/reports/state"), (200, {"status": "ok", "result": {"n": 3}}))
        status, body = self._call("POST", "/v1/plugins/demo/reports/boom")
        self.assertEqual((status, body["status"]), (200, "error"))
        self.assertEqual(self._call("POST", "/v1/plugins/demo/reports/ghost")[0], 409)
        self.assertEqual(self._call("POST", "/v1/plugins/ghost/reports/state")[0], 404)

    def test_a_generator_over_http_with_and_without_parameters(self):
        status, body = self._call("POST", "/v1/plugins/demo/generators/hello", {"params": {"who": "Ana"}})
        self.assertEqual((status, body["result"]["content"]), (200, "hi Ana"))
        self.assertEqual(self._call("POST", "/v1/plugins/demo/generators/hello")[1]["result"]["content"], "hi you")
        self.assertEqual(self._call("POST", "/v1/plugins/demo/generators/bad-name")[1]["status"], "error")

    def test_bad_generator_parameters_are_refused_not_run(self):
        self.assertEqual(self._call("POST", "/v1/plugins/demo/generators/hello", {"params": [1]})[0], 409)
        self.assertEqual(self._call("POST", "/v1/plugins/demo/generators/hello", raw=b"x" * (MAX_BODY_BYTES + 1))[0], 413)

    def test_the_new_routes_need_the_token_like_every_other(self):
        for path in ("/v1/plugins/demo/reports/state", "/v1/plugins/demo/generators/hello"):
            self.assertEqual(self._call("POST", path, token=None)[0], 401, path)
            self.assertEqual(self._call("POST", path, token="x" * 32)[0], 401, path)

    def test_a_disabled_plugin_answers_409(self):
        self._call("POST", "/v1/plugins/demo/disable")
        self.assertEqual(self._call("POST", "/v1/plugins/demo/reports/state")[0], 409)
        self.assertEqual(self._call("POST", "/v1/plugins/demo/generators/hello")[0], 409)

    def test_a_get_on_the_new_routes_is_not_found(self):
        self.assertEqual(self._call("GET", "/v1/plugins/demo/reports/state")[0], 404)
        self.assertEqual(self._call("GET", "/v1/plugins/demo/generators/hello")[0], 404)


class CliAndExamplesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for name in ("host-report", "readme-generator"):
            shutil.copytree(EXAMPLES / name, self.root / name)
        registry = PluginRegistry()
        registry.discover(self.root)
        self.digests = {item["name"]: item["sha256"] for item in registry.list()}

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_both_example_plugins_are_valid_and_listed_with_their_kind(self):
        code, out, _ = self._run("plugin", "list", "--plugins-root", str(self.root))
        self.assertEqual(code, 0)
        plugins = {p["name"]: p for p in json.loads(out)["plugins"]}
        self.assertEqual(plugins["host-report"]["provides"], ["reports"])
        self.assertEqual(plugins["readme-generator"]["provides"], ["generators"])

    def test_the_example_report_runs_through_the_cli(self):
        code, out, _ = self._run(
            "plugin", "run", "--plugins-root", str(self.root), "--plugin", "host-report",
            "--sha256", self.digests["host-report"], "--kind", "report", "--item", "host-summary",
        )
        self.assertEqual(code, 0, out)
        result = json.loads(out)["result"]
        self.assertIn("python", result)
        self.assertGreater(result["cpu_count"], 0)

    def test_the_example_generator_runs_through_the_cli(self):
        code, out, _ = self._run(
            "plugin", "run", "--plugins-root", str(self.root), "--plugin", "readme-generator",
            "--sha256", self.digests["readme-generator"], "--kind", "generator", "--item", "readme-skeleton",
            "--params", json.dumps({"name": "demo", "summary": "A demo."}),
        )
        self.assertEqual(code, 0, out)
        result = json.loads(out)["result"]
        self.assertEqual(result["filename"], "README.md")
        self.assertTrue(result["content"].startswith("# demo\n\nA demo."))

    def test_the_cli_refuses_a_wrong_digest_a_wrong_kind_and_bad_params(self):
        base = ("plugin", "run", "--plugins-root", str(self.root), "--plugin", "host-report")
        self.assertEqual(self._run(*base, "--sha256", "0" * 64, "--kind", "report", "--item", "host-summary")[0], 1)
        code, _, err = self._run(*base, "--sha256", self.digests["host-report"], "--kind", "generator", "--item", "host-summary")
        self.assertEqual(code, 1)
        self.assertIn("refused", err)
        code, _, err = self._run(
            *base, "--sha256", self.digests["host-report"], "--kind", "report", "--item", "host-summary", "--params", "{nope"
        )
        self.assertEqual(code, 1)

    def test_an_item_that_errors_exits_1(self):
        _write(self.root, "broken", "def register(r):\n    r.add_report('boom', lambda: 1 / 0)\n", provides=["reports"])
        registry = PluginRegistry()
        registry.discover(self.root)
        digest = next(p["sha256"] for p in registry.list() if p["name"] == "broken")
        code, out, _ = self._run(
            "plugin", "run", "--plugins-root", str(self.root), "--plugin", "broken",
            "--sha256", digest, "--kind", "report", "--item", "boom",
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["status"], "error")


if __name__ == "__main__":
    unittest.main()
