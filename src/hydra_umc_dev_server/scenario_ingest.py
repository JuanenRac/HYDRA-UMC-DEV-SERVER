# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/scenario_ingest.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Hands a ScenarioOutcome to HYDRA-UMC-SERVER (`POST /api/ingest/scenario-outcome`).

The before/after runs of a repair cycle are the same `ScenarioOutcome` 1.0 documents the SERVER keeps in a
signed, hash-chained record. This module is the sending end: off until the scenario-ingest configuration document (`configs/scenario-ingest.example.json`)
turns it on, and it only ever reports; a server that is off (404), that refuses the credential or that cannot be reached is
told to the caller as a result and never stops the verification.

The credential is the identity the SERVER issues: the token in `token_file`, or an account (`username` and the password in
`password_file`) that logs in first. Nothing secret is kept in the configuration, in a log or in a result. The token goes only
over HTTPS, or to this machine itself; a bench that needs plain HTTP says so with `allow_plain_http`. A redirect is never
followed (the token would travel to wherever the answer points).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SCENARIO_ROUTE = "/api/ingest/scenario-outcome"
LOGIN_ROUTE = "/api/login"
_REQUIRED = ("schema_version", "scenario_id", "run_id", "base_fingerprint", "phase", "repro_case", "observed", "timestamp_utc")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_MAX_ANSWER_BYTES = 64 * 1024


@dataclass(frozen=True)
class IngestSettings:
    server_url: str
    token_file: str | None = None
    username: str | None = None
    password_file: str | None = None
    timeout_seconds: float = 5.0
    allow_plain_http: bool = False


@dataclass(frozen=True)
class IngestResult:
    ok: bool
    status: int | None
    detail: str
    seq: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "status": self.status, "detail": self.detail, "seq": self.seq}


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - stdlib hook
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


def outcome_problem(outcome: object) -> str | None:
    """Why this is not a ScenarioOutcome 1.0 the server would take, or None."""
    if not isinstance(outcome, dict):
        return "the outcome is not an object"
    missing = [key for key in _REQUIRED if key not in outcome]
    if missing:
        return "the outcome lacks " + ", ".join(missing)
    if outcome["schema_version"] != "1.0":
        return "schema_version must be 1.0"
    if outcome["phase"] not in ("before", "after"):
        return "phase must be before or after"
    for key in ("scenario_id", "run_id", "base_fingerprint", "repro_case", "timestamp_utc"):
        if not isinstance(outcome[key], str) or not outcome[key]:
            return f"{key} must be a non-empty string"
    observed = outcome["observed"]
    if not isinstance(observed, dict) or observed.get("outcome") not in ("reproduced", "not-reproduced", "error"):
        return "observed.outcome must be reproduced, not-reproduced or error"
    return None


def _read_secret(path: str | None) -> str | None:
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _url_for(settings: IngestSettings, route: str) -> tuple[str | None, str]:
    """The URL of a route, or (None, why) when the base address may not carry a credential."""
    parts = urllib.parse.urlsplit(settings.server_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None, "server_url must be an http(s) address"
    if parts.username is not None or parts.password is not None:
        return None, "server_url must not carry a user or password"
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK and not settings.allow_plain_http:
        return None, "the credential only goes over HTTPS (set allow_plain_http for a bench)"
    base = settings.server_url.rstrip("/")
    return base + route, ""


def _send(request: urllib.request.Request, timeout: float, opener: Callable[..., Any] | None) -> tuple[int | None, Any, str]:
    """(status, JSON body or None, why-not) for one request; a network failure is a status of None."""
    try:
        response = (opener or _OPENER.open)(request, timeout=timeout)
        status, raw = response.status, response.read(_MAX_ANSWER_BYTES)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(_MAX_ANSWER_BYTES)
        exc.close()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return None, None, f"the server cannot be reached ({exc.__class__.__name__})"
    try:
        return status, json.loads(raw or b"{}"), ""
    except ValueError:
        return status, None, ""


def _login(settings: IngestSettings, opener: Callable[..., Any] | None) -> tuple[str | None, str]:
    password = _read_secret(settings.password_file)
    if not settings.username or password is None:
        return None, "no credential: set token_file, or username and password_file"
    url, why = _url_for(settings, LOGIN_ROUTE)
    if url is None:
        return None, why
    body = json.dumps({"username": settings.username, "password": password}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    status, answer, why = _send(request, settings.timeout_seconds, opener)
    if status is None:
        return None, why
    token = answer.get("token") if isinstance(answer, dict) else None
    if status != 200 or not isinstance(token, str) or not token:
        return None, f"the server refused the login (HTTP {status})"
    return token, ""


def post_scenario_outcome(outcome: dict[str, Any], settings: IngestSettings, *, opener: Callable[..., Any] | None = None) -> IngestResult:
    """Sends one ScenarioOutcome. Never raises for the network or the answer: the result says what happened."""
    problem = outcome_problem(outcome)
    if problem:
        return IngestResult(False, None, problem)
    url, why = _url_for(settings, SCENARIO_ROUTE)
    if url is None:
        return IngestResult(False, None, why)
    token = _read_secret(settings.token_file)
    if token is None:
        token, why = _login(settings, opener)
        if token is None:
            return IngestResult(False, None, why)
    body = json.dumps(outcome).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    status, answer, why = _send(request, settings.timeout_seconds, opener)
    if status is None:
        return IngestResult(False, None, why)
    if status == 201:
        seq = answer.get("seq") if isinstance(answer, dict) else None
        return IngestResult(True, 201, "kept by the server", seq if isinstance(seq, int) else None)
    meaning = {
        400: "the server does not take this outcome",
        401: "the server refused the credential",
        403: "the account may not hand in outcomes (operator or administrator)",
        404: "the server has this feed off (HYDRA_UMC_INGEST_SCENARIO)",
        503: "the server cannot sign its record",
    }.get(status, "the server did not keep it")
    return IngestResult(False, status, f"{meaning} (HTTP {status})")


def load_ingest_settings(path: Path) -> IngestSettings | None:
    """The settings of a scenario-ingest document, or None while its `enabled` is false (the default). A malformed document raises
    ConfigValidationError: half a configuration must not switch half a feature on."""
    from .config import ConfigValidationError, load_json_document

    data = load_json_document(path)
    known = {"enabled", "server_url", "token_file", "username", "password_file", "timeout_seconds", "allow_plain_http"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigValidationError(f"{path}: unknown key(s): {', '.join(unknown)}")
    for name in ("enabled", "allow_plain_http"):
        if name in data and not isinstance(data[name], bool):
            raise ConfigValidationError(f"{path}: {name!r} must be true or false")
    for name in ("server_url", "token_file", "username", "password_file"):
        if data.get(name) is not None and (not isinstance(data[name], str) or not data[name].strip()):
            raise ConfigValidationError(f"{path}: {name!r} must be a non-empty string or null")
    timeout = data.get("timeout_seconds", 5.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.1 <= timeout <= 600:
        raise ConfigValidationError(f"{path}: 'timeout_seconds' must be a number between 0.1 and 600")
    if data.get("enabled") is not True:
        return None
    if not data.get("server_url"):
        raise ConfigValidationError(f"{path}: 'server_url' is needed when 'enabled' is true")
    if not data.get("token_file") and not (data.get("username") and data.get("password_file")):
        raise ConfigValidationError(f"{path}: give 'token_file', or 'username' and 'password_file'")
    return IngestSettings(
        server_url=data["server_url"], token_file=data.get("token_file"), username=data.get("username"),
        password_file=data.get("password_file"), timeout_seconds=float(timeout), allow_plain_http=bool(data.get("allow_plain_http", False)),
    )


def outcome_sink(settings: IngestSettings | None) -> tuple[Callable[[dict[str, Any]], None] | None, list[IngestResult]]:
    """(the function a RepairCycle calls with each ScenarioOutcome, the list of what came of each one); (None, []) while off."""
    results: list[IngestResult] = []
    if settings is None:
        return None, results

    def sink(outcome: dict[str, Any]) -> None:
        results.append(post_scenario_outcome(outcome, settings))

    return sink, results
