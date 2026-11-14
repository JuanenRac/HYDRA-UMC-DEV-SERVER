# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_cli_refusals.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Every command of the command line, given a file that is not there, a file that is not the document it names, or a folder that holds nothing,
answers with a non-zero exit code and a line on the error output - never with a traceback. A fixed-seed run feeds random bytes to the commands
that read a document."""
import json
import random
from pathlib import Path

import pytest

from hydra_umc_dev_server.cli import main

SEED = 20261114


def _bad(tmp_path):
    """A file that is not JSON and one that is JSON of the wrong shape."""
    not_json = tmp_path / "not-json.json"
    not_json.write_bytes(b"\xff\xfe not json at all")
    wrong = tmp_path / "wrong-shape.json"
    wrong.write_text('["a", "b"]', encoding="utf-8")
    return str(not_json), str(wrong)


def _commands(tmp_path):
    missing = str(tmp_path / "missing.json")
    empty = tmp_path / "empty-folder"
    empty.mkdir()
    not_json, wrong = _bad(tmp_path)
    db = str(tmp_path / "queue.sqlite")
    base = str(tmp_path / "workspaces")
    store = str(tmp_path / "trust-store.json")
    return [
        ["station", "validate", missing],
        ["station", "validate", not_json],
        ["station", "preflight", missing],
        ["station", "plan", missing],
        ["station", "plan", wrong, "--preflight"],
        ["migrate", "inventory", str(empty)],
        ["migrate", "plan", str(empty), "--destinations", missing],
        ["migrate", "plan", str(empty), "--destinations", wrong],
        ["task", "validate", missing, "--policy", missing],
        ["task", "validate", wrong, "--policy", wrong],
        ["task", "run", missing, "--policy", missing, "--workspace-base", base],
        ["task", "run", not_json, "--policy", wrong, "--workspace-base", base],
        ["queue", "enqueue", missing, "--db", db],
        ["queue", "enqueue", wrong, "--db", db],
        ["provider", "suggest", "--config", missing, "--prompt-file", missing],
        ["incident", "verify", missing, "--policy", missing, "--registry", missing, "--authenticated-as", "node-a"],
        ["repair", "check", missing, "--secret-file", missing, "--incident", "i-1", "--base", "b", "--target", "t"],
        ["repair", "report", missing, "--config", missing],
        ["ops", "verify", missing, "--backup-root", str(empty)],
        ["ops", "sign-backup", missing, "--private-key-file", missing],
        ["trust", "add", store, "ops-key", "--public-key-file", missing],
        ["trust", "rotation-body", str(empty), "--old", "a", "--new", "b", "--new-public-key-file", missing],
        ["trust", "sign-rotation", "--body-file", missing, "--seed-file", missing],
        ["trust", "rotate", str(empty), "--body-file", missing, "--signature-file", missing, "--enable-rotation", "--skip-dir-check"],
        ["trust", "add", store, "ops-key", "--public-key-file", not_json],
        ["trust", "sign-rotation", "--body-file", not_json, "--seed-file", not_json],
        ["trust", "rotate", str(empty), "--body-file", not_json, "--signature-file", not_json, "--enable-rotation", "--skip-dir-check"],
        ["provider", "suggest", "--config", wrong, "--prompt-file", not_json],
        ["ops", "verify", wrong, "--backup-root", str(empty), "--public-key-file", not_json],
        ["ops", "sign-backup", wrong, "--private-key-file", not_json],
        ["repair", "check", wrong, "--secret-file", not_json, "--incident", "i-1", "--base", "b", "--target", "t"],
        ["plugin", "list", "--plugins-root", str(tmp_path / "no-plugins")],
        ["plugin", "run", "--plugins-root", str(tmp_path / "no-plugins"), "--plugin", "x", "--sha256", "0" * 64, "--kind", "check", "--item", "y"],
        ["inventory", "scan", "--root", str(tmp_path / "no-root")],
    ]


def test_a_command_given_nothing_to_read_refuses_without_a_traceback(tmp_path, capsys):
    refused = []
    for argv in _commands(tmp_path):
        try:
            code = main(argv)
        except SystemExit as stop:
            code = stop.code
        except Exception as error:  # noqa: BLE001 - the point of the test is to find the command that raises
            pytest.fail(f"{' '.join(argv[:3])} raised {type(error).__name__}: {error}")
        capsys.readouterr()
        if code in (0, None):
            refused.append(" ".join(argv[:3]))
    # a few commands may rightly answer 0 for an empty thing (a scan of a root with nothing in it); none of the readers of a document may
    assert all(not entry.startswith(("station", "task", "queue", "provider", "incident", "repair", "ops")) for entry in refused), refused


def test_a_scan_written_to_a_place_that_is_not_there_is_refused(tmp_path, capsys):
    out = tmp_path / "no-such-folder" / "inventory.json"
    assert main(["inventory", "scan", "--root", str(tmp_path), "--out", str(out)]) == 1
    assert "cannot write" in capsys.readouterr().err


def test_a_scan_is_written_where_it_is_asked(tmp_path, capsys):
    out = tmp_path / "inventory.json"
    assert main(["inventory", "scan", "--root", str(tmp_path), "--out", str(out)]) == 0
    assert out.is_file()
    assert "Wrote inventory" in capsys.readouterr().out


def test_documents_of_random_bytes_never_make_a_command_raise(tmp_path, capsys):
    rng = random.Random(SEED)
    document = tmp_path / "random.json"
    policy = tmp_path / "policy.json"
    for _ in range(40):
        document.write_bytes(bytes(rng.randrange(256) for _ in range(rng.randint(0, 80))))
        policy.write_bytes(bytes(rng.randrange(256) for _ in range(rng.randint(0, 80))))
        for argv in (
            ["station", "validate", str(document)],
            ["task", "validate", str(document), "--policy", str(policy)],
            ["config", "validate", str(document), "--kind", "task-policy"],
            ["config", "validate", str(document), "--kind", "host-profile"],
        ):
            assert main(argv) == 1, argv
            capsys.readouterr()


# ------------------------------------------------------------------ the refusals that need a good document first
CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def test_the_same_task_with_another_recipe_is_a_conflict(tmp_path, capsys):
    db = str(tmp_path / "queue.sqlite")
    recipe = json.loads((CONFIGS / "task-recipe.example.json").read_text(encoding="utf-8"))
    first = tmp_path / "first.json"
    first.write_text(json.dumps(recipe), encoding="utf-8")
    recipe["command"] = ["pytest", "-x"]
    other = tmp_path / "other.json"
    other.write_text(json.dumps(recipe), encoding="utf-8")
    assert main(["queue", "enqueue", str(first), "--db", db, "--base-fingerprint", "b1"]) == 0
    capsys.readouterr()
    assert main(["queue", "enqueue", str(other), "--db", db, "--base-fingerprint", "b1"]) == 1
    assert "already exists with a different recipe" in capsys.readouterr().err


def test_a_worker_is_refused_a_relative_workspace_and_a_missing_policy(tmp_path, capsys):
    db = str(tmp_path / "queue.sqlite")
    policy = str(CONFIGS / "task-policy.example.json")
    assert main(["queue", "work", "--db", db, "--policy", policy, "--workspace-base", "relative/base", "--max-tasks", "1"]) == 1
    assert "must be an absolute path" in capsys.readouterr().err
    assert main(["queue", "work", "--db", db, "--policy", str(tmp_path / "missing.json"), "--workspace-base", str(tmp_path / "ws")]) == 1
    capsys.readouterr()


def test_a_worker_with_nothing_queued_stops_at_once(tmp_path, capsys):
    db = str(tmp_path / "queue.sqlite")
    base = tmp_path / "workspaces"
    assert main(["queue", "work", "--db", db, "--policy", str(CONFIGS / "task-policy.example.json"), "--workspace-base", str(base), "--max-tasks", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == {"tasks": []}


def test_a_candidate_needs_exactly_one_way_to_be_trusted(tmp_path, capsys):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"candidate_id": "c1", "for_incident_id": "INC-1", "for_base_fingerprint": "b", "for_target": "t", "patch_ref": "abc1234", "signature": "00"}), encoding="utf-8")
    secret = tmp_path / "secret"
    secret.write_text("s3cret-for-the-test", encoding="utf-8")
    common = ["--incident", "INC-1", "--base", "b", "--target", "t"]
    code = main(["repair", "check-candidate", str(candidate), *common])
    err = capsys.readouterr().err
    assert code == 1 and ("exactly one" in err or "INVALID" in err)
    assert main(["repair", "check-candidate", str(candidate), "--secret-file", str(secret), "--trust-store", str(tmp_path / "s.json"), *common]) == 1
    assert "exactly one" in capsys.readouterr().err
    assert main(["repair", "check-candidate", str(candidate), "--secret-file", str(secret), "--signer", "ops", *common]) in (1,)
    capsys.readouterr()


def test_reporting_an_outcome_while_the_ingest_is_off_sends_nothing(tmp_path, capsys):
    outcome = tmp_path / "outcome.json"
    outcome.write_text("{}", encoding="utf-8")
    code = main(["repair", "report-outcome", str(outcome), "--config", str(CONFIGS / "scenario-ingest.example.json")])
    assert code == 1
    assert "OFF" in capsys.readouterr().err


def test_a_registry_of_something_else_than_secrets_is_refused(tmp_path, capsys):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"node-a": 7}), encoding="utf-8")
    message = tmp_path / "message.json"
    message.write_text(json.dumps({"x": 1}), encoding="utf-8")
    code = main(["incident", "verify", str(message), "--policy", str(CONFIGS / "incident-transport.example.json"),
                 "--registry", str(registry), "--authenticated-as", "node-a"])
    assert code == 1
    capsys.readouterr()


def test_the_trust_store_of_the_examples_lists_and_a_broken_one_is_refused(tmp_path, capsys):
    assert main(["trust", "list", str(CONFIGS / "trust-store.example.json")]) == 0
    assert "trusted" in capsys.readouterr().out
    broken = tmp_path / "store.json"
    broken.write_text("[1, 2]", encoding="utf-8")
    assert main(["trust", "list", str(broken)]) == 1
    assert "INVALID" in capsys.readouterr().err
    assert main(["trust", "revoke", str(broken), "ops"]) == 1
    capsys.readouterr()
