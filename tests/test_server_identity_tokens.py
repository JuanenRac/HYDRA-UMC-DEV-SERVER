# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_server_identity_tokens.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Every way a signed token of the SERVER can be wrong must be refused, and the probe must say yes only to a 200."""
import base64
import hmac
import json
import random
import threading
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from hydra_umc_dev_server import server_identity as si

KEY = b"k" * 40
NOW = 1_800_000_000.0


def _part(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token(claims: dict | None = None, header: dict | None = None, key: bytes = KEY, raw_signature: bytes | None = None) -> str:
    head = _part(json.dumps(header if header is not None else {"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    body = _part(json.dumps(claims if claims is not None else {"username": "ana", "role": "operator", "exp": NOW + 60}).encode("utf-8"))
    signature = raw_signature if raw_signature is not None else hmac.new(key, f"{head}.{body}".encode("ascii"), sha256).digest()
    return f"{head}.{body}.{_part(signature)}"


def _claims(**changes) -> dict:
    claims = {"username": "ana", "role": "operator", "exp": NOW + 60}
    claims.update(changes)
    return {k: v for k, v in claims.items() if v is not None}


def test_a_good_token_gives_its_user_and_role() -> None:
    assert si.verify_token(_token(), KEY, now=NOW) == si.Identity("ana", "operator")
    for role in si.ROLES:
        assert si.verify_token(_token(_claims(role=role)), KEY, now=NOW).role == role


@pytest.mark.parametrize("token", [None, "", "a.b", "a.b.c.d", "..", "a..c", ".b.c", "a.b.", "x" * (si.MAX_TOKEN_CHARS + 1)])
def test_a_missing_or_misshapen_token_is_refused(token) -> None:
    with pytest.raises(si.IdentityError):
        si.verify_token(token, KEY, now=NOW)


def test_the_longest_accepted_token_is_not_refused_for_its_length_alone() -> None:
    padded = _token(_claims(note="n" * 2700))
    assert len(padded) <= si.MAX_TOKEN_CHARS
    assert si.verify_token(padded, KEY, now=NOW).username == "ana"


def test_only_hs256_is_accepted_and_a_none_algorithm_never_is() -> None:
    for header in ({"alg": "none"}, {"alg": "HS512"}, {"alg": "RS256"}, {}, {"alg": None}, {"typ": "JWT"}):
        with pytest.raises(si.IdentityError, match="algorithm"):
            si.verify_token(_token(header=header), KEY, now=NOW)
    unsigned = _token(header={"alg": "none"}, raw_signature=b"")
    with pytest.raises(si.IdentityError):
        si.verify_token(unsigned, KEY, now=NOW)


def test_a_wrong_key_or_a_changed_payload_fails_the_signature() -> None:
    with pytest.raises(si.IdentityError, match="signature"):
        si.verify_token(_token(key=b"z" * 40), KEY, now=NOW)
    head, body, signature = _token().split(".")
    forged_body = _part(json.dumps(_claims(role="admin")).encode("utf-8"))
    with pytest.raises(si.IdentityError, match="signature"):
        si.verify_token(f"{head}.{forged_body}.{signature}", KEY, now=NOW)
    with pytest.raises(si.IdentityError, match="signature"):
        si.verify_token(_token(raw_signature=b"short"), KEY, now=NOW)


@pytest.mark.parametrize("part", ["header", "body"])
def test_a_part_that_is_not_base64_json_object_is_malformed(part) -> None:
    head, body, signature = _token().split(".")
    garbage = ["!!!", _part(b"not json"), _part(b"[1,2]"), _part(b"\xff\xfe"), _part(b'"text"')]
    for bad in garbage:
        token = f"{bad}.{body}.{signature}" if part == "header" else f"{head}.{bad}.{signature}"
        with pytest.raises(si.IdentityError):
            si.verify_token(token, KEY, now=NOW)


def test_the_expiry_is_required_finite_and_in_the_future() -> None:
    with pytest.raises(si.IdentityError, match="no expiry"):
        si.verify_token(_token(_claims(exp=None)), KEY, now=NOW)
    for exp in ("soon", True, False, [1], {"a": 1}):
        with pytest.raises(si.IdentityError, match="no expiry"):
            si.verify_token(_token(_claims(exp=exp)), KEY, now=NOW)
    for text in ("NaN", "Infinity", "-Infinity"):
        # Python's json accepts these words; a NaN expiry would otherwise never expire
        raw = _token(_claims()).split(".")
        body = _part(('{"username":"ana","role":"operator","exp":' + text + "}").encode("ascii"))
        signature = hmac.new(KEY, f"{raw[0]}.{body}".encode("ascii"), sha256).digest()
        with pytest.raises(si.IdentityError, match="no expiry"):
            si.verify_token(f"{raw[0]}.{body}.{_part(signature)}", KEY, now=NOW)
    with pytest.raises(si.IdentityError, match="expired"):
        si.verify_token(_token(_claims(exp=NOW)), KEY, now=NOW)  # exactly now is already expired
    assert si.verify_token(_token(_claims(exp=NOW + 0.001)), KEY, now=NOW).username == "ana"


def test_not_before_and_issued_at_have_exact_edges() -> None:
    assert si.verify_token(_token(_claims(nbf=NOW)), KEY, now=NOW).username == "ana"
    with pytest.raises(si.IdentityError, match="not valid yet"):
        si.verify_token(_token(_claims(nbf=NOW + 1)), KEY, now=NOW)
    for nbf in ("x", True, [1]):
        with pytest.raises(si.IdentityError, match="not valid yet"):
            si.verify_token(_token(_claims(nbf=nbf)), KEY, now=NOW)
    assert si.verify_token(_token(_claims(iat=NOW + si.IAT_SKEW_SECONDS)), KEY, now=NOW).username == "ana"
    with pytest.raises(si.IdentityError, match="future"):
        si.verify_token(_token(_claims(iat=NOW + si.IAT_SKEW_SECONDS + 1)), KEY, now=NOW)
    for iat in ("x", False, {"a": 1}):
        with pytest.raises(si.IdentityError, match="future"):
            si.verify_token(_token(_claims(iat=iat)), KEY, now=NOW)


def test_a_token_without_a_user_or_with_an_unknown_role_is_refused() -> None:
    for username in (None, "", 5, ["ana"]):
        with pytest.raises(si.IdentityError, match="no user"):
            si.verify_token(_token(_claims(username=username)), KEY, now=NOW)
    for role in (None, "root", "ADMIN", "", 1, ["admin"]):
        with pytest.raises(si.IdentityError, match="role"):
            si.verify_token(_token(_claims(role=role)), KEY, now=NOW)


def test_random_mutations_of_a_good_token_are_never_accepted() -> None:
    rng = random.Random(1234)
    good = _token()
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    for _ in range(400):
        chars = list(good)
        index = rng.randrange(len(chars))
        replacement = rng.choice(alphabet)
        if replacement == chars[index]:
            continue
        chars[index] = replacement
        mutated = "".join(chars)
        try:
            identity = si.verify_token(mutated, KEY, now=NOW)
        except si.IdentityError:
            continue
        # base64 padding bits can make a changed last character decode to the same bytes; anything accepted must be the same identity
        assert identity == si.Identity("ana", "operator"), mutated


class _Handler:
    def __init__(self, method: str, authorization: str | None) -> None:
        self.command = method
        self.headers = {} if authorization is None else {"Authorization": authorization}
        self.identity = "unset"


def test_accepts_without_a_key_follows_the_earlier_rule() -> None:
    assert si.accepts(_Handler("POST", None), "", None) is True  # no token, no key: open
    assert si.accepts(_Handler("POST", None), "secret", None) is False
    assert si.accepts(_Handler("POST", "Bearer secret"), "secret", None) is True
    assert si.accepts(_Handler("POST", "Bearer other"), "secret", None) is False
    assert si.accepts(_Handler("POST", "Basic secret"), "secret", None) is False
    assert si.accepts(_Handler("POST", "Bearer "), "secret", None) is False


def test_accepts_with_a_key_is_never_open_and_a_viewer_cannot_write() -> None:
    assert si.accepts(_Handler("GET", None), "", KEY) is False
    viewer = si.sign_token(KEY, "eve", "viewer")
    operator = si.sign_token(KEY, "ana", "operator")
    for method in ("GET", "HEAD", "OPTIONS"):
        handler = _Handler(method, f"Bearer {viewer}")
        assert si.accepts(handler, "", KEY) is True
        assert handler.identity == si.Identity("eve", "viewer")
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert si.accepts(_Handler(method, f"Bearer {viewer}"), "", KEY) is False
        handler = _Handler(method, f"Bearer {operator}")
        assert si.accepts(handler, "", KEY) is True
        assert handler.identity == si.Identity("ana", "operator")


def test_accepts_with_a_key_still_takes_the_own_token_and_refuses_a_token_that_is_not_a_token() -> None:
    handler = _Handler("POST", "Bearer secret")
    assert si.accepts(handler, "secret", KEY) is True
    assert handler.identity is None
    assert si.accepts(_Handler("POST", "Bearer not.a"), "secret", KEY) is False
    assert si.accepts(_Handler("GET", f"Bearer {_token(key=b'z' * 40)}"), "", KEY) is False
    assert si.accepts(_Handler("GET", f"Token {si.sign_token(KEY)}"), "", KEY) is False


def test_sign_token_round_trips_and_expires() -> None:
    token = si.sign_token(KEY, "probe", "viewer", 30, now=NOW)
    assert si.verify_token(token, KEY, now=NOW + 29) == si.Identity("probe", "viewer")
    with pytest.raises(si.IdentityError, match="expired"):
        si.verify_token(token, KEY, now=NOW + 30)


def test_the_key_file_rules(tmp_path: Path) -> None:
    short = tmp_path / "short"
    short.write_text("x" * (si.MIN_KEY_LENGTH - 1), encoding="utf-8")
    with pytest.raises(ValueError, match="at least") as raised:
        si.load_identity_key(str(short))
    assert "x" * 5 not in str(raised.value)
    with pytest.raises(ValueError, match="cannot read"):
        si.load_identity_key(str(tmp_path / "absent"))
    exact = tmp_path / "exact"
    exact.write_text(" " + "y" * si.MIN_KEY_LENGTH + " \n", encoding="utf-8")
    assert si.load_identity_key(str(exact)) == b"y" * si.MIN_KEY_LENGTH
    assert si.identity_key_from(None, {}) is None
    assert si.identity_key_from("  ", {si.ENV_IDENTITY_KEY_FILE: ""}) is None
    assert si.identity_key_from(None, {si.ENV_IDENTITY_KEY_FILE: str(exact)}) == b"y" * si.MIN_KEY_LENGTH
    assert si.identity_key_from(str(exact), {si.ENV_IDENTITY_KEY_FILE: str(short)}) == b"y" * si.MIN_KEY_LENGTH  # the flag wins


class _Probed(BaseHTTPRequestHandler):
    seen: list[str] = []
    status = 200

    def do_GET(self):
        type(self).seen.append(self.headers.get("Authorization", ""))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args):
        pass


def _serve(status: int) -> tuple[HTTPServer, int]:
    _Probed.seen, _Probed.status = [], status
    server = HTTPServer(("127.0.0.1", 0), _Probed)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_the_probe_says_yes_only_to_a_200_and_presents_a_viewer_token(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_bytes(KEY)
    server, port = _serve(200)
    try:
        assert si.probe(port, key_file=str(key_file)) is True
        assert si.verify_token(_Probed.seen[0].removeprefix("Bearer "), KEY).role == "viewer"
        assert si.probe(port) is True and _Probed.seen[-1] == ""  # no key: nothing is presented
        assert si.main(["probe", "--port", str(port), "--key-file", str(key_file)]) == 0
    finally:
        server.shutdown()
        server.server_close()
    server, port = _serve(503)
    try:
        assert si.probe(port) is False
        assert si.main(["probe", "--port", str(port)]) == 1
    finally:
        server.shutdown()
        server.server_close()
    assert si.probe(port, timeout=0.5) is False  # nobody is listening any more


def test_the_probe_command_reports_a_bad_key_file_with_exit_2(tmp_path: Path, capsys) -> None:
    short = tmp_path / "short"
    short.write_text("tiny", encoding="utf-8")
    assert si.main(["probe", "--port", "1", "--key-file", str(short)]) == 2
    assert "error:" in capsys.readouterr().out
