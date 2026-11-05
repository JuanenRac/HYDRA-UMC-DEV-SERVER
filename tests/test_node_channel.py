# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_node_channel.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""One token per node, issued and revocable; the route is closed unless the channel is configured."""
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from hydra_umc_dev_server.api import DevServer
from hydra_umc_dev_server.incident_transport import IncidentMessage, CONTRACT_VERSION
from hydra_umc_dev_server.node_channel import (
    ChannelSettings, NodeChannel, NodeChannelError, authenticate, issue_token, load_tokens, revoke_token,
)

API_TOKEN = "a" * 32
# Ephemeral per-run test keys: random bytes, never a fixed value.
NODE_ONE_KEY = os.urandom(16).hex()
NODE_TWO_KEY = os.urandom(16).hex()
NODE_FORGED_KEY = os.urandom(16).hex()


def message(node="tech-1", message_id="tech-1-esc-1", nonce="n1", at=None, secret=NODE_ONE_KEY, to_node="dev-server"):
    unsigned = IncidentMessage(
        message_id=message_id, from_node=node, to_node=to_node, kind="incident", contract_version=CONTRACT_VERSION,
        nonce=nonce, sent_at=time.time() if at is None else at, payload={"escalationId": "esc-1"},
    )
    return json.dumps(unsigned.signed(secret).to_dict()).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.tokens = self.root / "tokens.json"
        self.token_out = self.root / "tech-1.token"
        (self.root / "registry.json").write_text(json.dumps({"tech-1": NODE_ONE_KEY, "tech-2": NODE_TWO_KEY}), encoding="utf-8")
        (self.root / "channel.json").write_text(json.dumps({
            "tokens_file": str(self.tokens), "registry_file": str(self.root / "registry.json"),
            "state_file": str(self.root / "state.db"), "inbox_dir": str(self.root / "inbox"), "to_node": "dev-server",
        }), encoding="utf-8")
        self.settings = ChannelSettings.load(self.root / "channel.json")
        self.channel = NodeChannel(self.settings)

    def issue(self, node="tech-1", name=None):
        out = self.root / (name or f"{node}.token")
        issue_token(self.tokens, node, out)
        return out.read_text(encoding="utf-8").strip()


class TokenTests(Base):
    def test_the_token_is_written_to_a_private_new_file_and_only_its_hash_is_kept(self):
        token = self.issue()
        out = self.root / "tech-1.token"
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        stored = self.tokens.read_text(encoding="utf-8")
        self.assertNotIn(token, stored)
        self.assertEqual(authenticate(self.tokens, token), "tech-1")
        with self.assertRaises(NodeChannelError):
            issue_token(self.tokens, "tech-1", out)  # never overwrites a file

    def test_a_rotation_replaces_the_token_and_a_revocation_stops_it(self):
        first = self.issue(name="a.token")
        second = self.issue(name="b.token")
        self.assertNotEqual(first, second)
        self.assertIsNone(authenticate(self.tokens, first))
        self.assertEqual(authenticate(self.tokens, second), "tech-1")
        revoke_token(self.tokens, "tech-1")
        self.assertIsNone(authenticate(self.tokens, second))
        self.assertIsNotNone(load_tokens(self.tokens)["tech-1"]["revoked_at"])
        with self.assertRaises(NodeChannelError):
            revoke_token(self.tokens, "nobody")

    def test_garbage_is_not_a_token(self):
        self.issue()
        for presented in ("", "x" * 60, "hnt1_short", None):
            self.assertIsNone(authenticate(self.tokens, presented))

    def test_node_names_are_checked(self):
        with self.assertRaises(NodeChannelError):
            issue_token(self.tokens, "bad node", self.root / "x.token")


class ChannelTests(Base):
    def post(self, token, body, **kw):
        return self.channel.handle(f"Bearer {token}" if token is not None else "", body, **kw)

    def test_a_valid_token_and_message_are_stored_once(self):
        token = self.issue()
        status, answer = self.post(token, message())
        self.assertEqual((status, answer["ok"], answer["duplicate"]), (200, True, False))
        status, answer = self.post(token, message(nonce="n2"))  # the retry of the same escalation, fresh nonce
        self.assertEqual((status, answer["ok"], answer["duplicate"]), (200, True, True))
        self.assertEqual(len(list((self.root / "inbox").glob("*.json"))), 1)

    def test_no_token_a_wrong_token_and_a_revoked_token_are_refused(self):
        token = self.issue()
        self.assertEqual(self.post(None, message())[0], 401)
        self.assertEqual(self.post("hnt1_" + "z" * 50, message())[0], 401)
        self.assertEqual(self.channel.handle("Basic abc", message())[0], 401)
        revoke_token(self.tokens, "tech-1")
        self.assertEqual(self.post(token, message())[0], 401)
        self.assertFalse((self.root / "inbox").exists())

    def test_a_token_cannot_speak_for_another_node(self):
        token = self.issue("tech-1")
        status, answer = self.post(token, message(node="tech-2", secret=NODE_TWO_KEY))
        self.assertEqual((status, answer["code"]), (403, "impersonation"))

    def test_a_stolen_token_without_the_node_secret_cannot_forge_a_message(self):
        token = self.issue()
        status, answer = self.post(token, message(secret=NODE_FORGED_KEY))
        self.assertEqual((status, answer["code"]), (403, "bad-signature"))

    def test_a_replayed_message_and_a_stale_one_are_refused(self):
        token = self.issue()
        body = message()
        self.assertEqual(self.post(token, body)[0], 200)
        self.assertEqual(self.post(token, body)[1]["code"], "replay")
        self.assertEqual(self.post(token, message(nonce="n9", message_id="other", at=time.time() - 10_000))[1]["code"], "stale")

    def test_a_message_for_another_recipient_is_refused(self):
        token = self.issue()
        self.assertEqual(self.post(token, message(to_node="someone-else"))[1]["code"], "wrong-recipient")

    def test_bad_bodies(self):
        token = self.issue()
        self.assertEqual(self.post(token, b"nope")[0], 400)
        self.assertEqual(self.post(token, b"[]")[0], 400)
        self.assertEqual(self.post(token, b"x" * (self.settings.max_body_bytes + 1))[0], 413)
        self.assertEqual(self.post(token, message(message_id="../../evil"))[0], 400)

    def test_settings_are_checked(self):
        path = self.root / "bad.json"
        path.write_text(json.dumps({"tokens_file": "t", "registry_file": "r", "state_file": "s", "inbox_dir": "i", "to_node": "n", "extra": 1}), encoding="utf-8")
        with self.assertRaises(NodeChannelError):
            ChannelSettings.load(path)
        path.write_text(json.dumps({"tokens_file": "t"}), encoding="utf-8")
        with self.assertRaises(NodeChannelError):
            ChannelSettings.load(path)


class RouteTests(Base):
    def start(self, channel):
        server = DevServer(("127.0.0.1", 0), token=API_TOKEN, workspace_root=self.root, plugins_root=self.root, node_channel=channel)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def stop():
            server.shutdown()
            server.server_close()
        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_address[1]}/v1/incident-transport"

    def call(self, url, token, body):
        request = urllib.request.Request(url, data=body, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_the_route_is_closed_without_the_channel_even_for_the_api_token(self):
        url = self.start(None)
        self.assertEqual(self.call(url, API_TOKEN, message())[0], 404)

    def test_the_route_takes_the_token_of_the_node_and_not_the_token_of_the_api(self):
        url = self.start(self.channel)
        token = self.issue()
        self.assertEqual(self.call(url, API_TOKEN, message())[0], 401)
        status, answer = self.call(url, token, message())
        self.assertEqual((status, answer["ok"]), (200, True))
        revoke_token(self.tokens, "tech-1")
        self.assertEqual(self.call(url, token, message(nonce="n5"))[0], 401)


if __name__ == "__main__":
    unittest.main()
