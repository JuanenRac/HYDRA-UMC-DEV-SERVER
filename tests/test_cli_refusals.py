# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_cli_refusals.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Every command of the command line, given a file that is not there, a file that is not the document it names, or a folder that holds nothing,
answers with a non-zero exit code and a line on the error output - never with a traceback. A fixed-seed run feeds random bytes to the commands
that read a document."""
import random

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
