# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_corpus_build.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The reproducible, unsigned documentation corpus build (corpus_build.py): configuration, pins, clones, the twice-and-compare rule and the sources file.

evidence=simulator: the repositories are local git repositories and the indexer is a stand-in written in the test, except the last test, which uses the
real HYDRA-UMC-DOCS-QA when a checkout sits next to this one.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hydra_umc_dev_server import corpus_build as cb

STAND_IN = textwrap.dedent(
    '''\
    import hashlib, json, os, sys
    from pathlib import Path
    argv = sys.argv[1:]
    out = Path(argv[argv.index("--out") + 1])
    manifest = json.loads(Path(argv[argv.index("--corpus") + 1]).read_text(encoding="utf-8"))
    names = []
    for root in manifest["roots"]:
        for path in sorted(Path(root).rglob("*.md")):
            names.append(Path(root).name + "/" + path.relative_to(root).as_posix() + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
    leak = os.environ.get("STAND_IN_LEAK", "")
    extra = {"seed": os.environ["PYTHONHASHSEED"]} if leak == "seed" else {"where": manifest["roots"][0]} if leak == "path" else {}
    out.write_text(json.dumps({"release": argv[argv.index("--release") + 1], "documents": names, **extra}, sort_keys=True), encoding="utf-8")
    '''
)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _make_repo(base: Path, name: str, files: dict[str, str]) -> Path:
    repo = base / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "ci")
    (repo / "hydra-umc.project.json").write_text("{}", encoding="utf-8")
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture()
def remotes(tmp_path: Path) -> dict[str, Path]:
    base = tmp_path / "remotes"
    return {
        "HYDRA-UMC-ALPHA": _make_repo(base, "HYDRA-UMC-ALPHA", {"README.md": "# Alpha\n\nThe alpha service.\n", "docs/guide.md": "# Guide\n\nSteps.\n"}),
        "HYDRA-UMC-BETA": _make_repo(base, "HYDRA-UMC-BETA", {"README.md": "# Beta\n\nThe beta service.\n"}),
    }


@pytest.fixture()
def stand_in(tmp_path: Path) -> Path:
    root = tmp_path / "docs-qa"
    package = root / "src" / "hydra_umc_docs_qa"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "main.py").write_text(STAND_IN, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "ci@example.invalid")
    _git(root, "config", "user.name", "ci")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "stand-in")
    return root


def _config(names: list[str]) -> dict[str, object]:
    return {"owner": "Example", "repos": sorted(names), "exclude": ["README_*.md"]}


def _plan(remotes: dict[str, Path], pins: dict[str, str] | None = None) -> list[dict[str, str]]:
    pins = pins or {}
    return [{"name": n, "url": str(p), "commit": pins.get(n, "")} for n, p in sorted(remotes.items())]


def test_the_shipped_configuration_is_valid_and_lists_only_plain_public_names() -> None:
    config = cb.load_config(Path(__file__).resolve().parents[1] / "configs" / "corpus-repos.json")
    assert config["owner"] == "JuanenRac" and len(config["repos"]) > 10
    assert all(name.startswith("HYDRA-UMC") for name in config["repos"])
    plan = cb.clone_plan(config)
    assert all(item["url"].startswith("https://github.com/JuanenRac/") and item["commit"] == "" for item in plan)


@pytest.mark.parametrize(
    "bad",
    [
        {"schema": "other", "owner": "o", "repos": ["a"]},
        {"schema": cb.CONFIG_SCHEMA, "owner": "o", "repos": []},
        {"schema": cb.CONFIG_SCHEMA, "owner": "o", "repos": ["a", "a"]},
        {"schema": cb.CONFIG_SCHEMA, "owner": "o", "repos": ["../x"]},
        {"schema": cb.CONFIG_SCHEMA, "owner": "bad owner", "repos": ["a"]},
        {"schema": cb.CONFIG_SCHEMA, "owner": "o", "repos": ["a"], "exclude": ["../etc"]},
    ],
)
def test_a_bad_configuration_is_refused(tmp_path: Path, bad: dict[str, object]) -> None:
    path = tmp_path / "c.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(cb.CorpusBuildError):
        cb.load_config(path)
    with pytest.raises(cb.CorpusBuildError):
        cb.load_config(tmp_path / "missing.json")


def test_pins_must_be_full_commits_of_listed_repositories(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"schema": cb.SOURCES_SCHEMA, "repositories": [{"name": "A", "commit": "abc"}]}), encoding="utf-8")
    with pytest.raises(cb.CorpusBuildError):
        cb.load_pins(path)
    path.write_text(json.dumps({"schema": cb.SOURCES_SCHEMA, "repositories": [{"name": "A", "commit": "a" * 40}]}), encoding="utf-8")
    assert cb.load_pins(path) == {"A": "a" * 40}
    with pytest.raises(cb.CorpusBuildError, match="do not list|does not list"):
        cb.clone_plan({"owner": "o", "repos": ["B"], "exclude": []}, {"A": "a" * 40})


def test_clone_takes_the_tip_or_the_pinned_commit_and_records_it(tmp_path: Path, remotes: dict[str, Path]) -> None:
    first = {n: _git(p, "rev-parse", "HEAD") for n, p in remotes.items()}
    done = cb.clone_all(_plan(remotes), tmp_path / "ws1")
    assert {d["name"]: d["commit"] for d in done} == first
    (remotes["HYDRA-UMC-BETA"] / "README.md").write_text("# Beta\n\nChanged.\n", encoding="utf-8")
    _git(remotes["HYDRA-UMC-BETA"], "commit", "-q", "-am", "change")
    pinned = cb.clone_all(_plan(remotes, first), tmp_path / "ws2")
    assert {d["name"]: d["commit"] for d in pinned} == first
    assert "The beta service" in (tmp_path / "ws2" / "HYDRA-UMC-BETA" / "README.md").read_text(encoding="utf-8")
    with pytest.raises(cb.CorpusBuildError, match="already exists"):
        cb.clone_all(_plan(remotes), tmp_path / "ws2")


def test_a_repository_that_is_not_a_project_of_the_ecosystem_is_refused(tmp_path: Path) -> None:
    remote = _make_repo(tmp_path / "remotes", "HYDRA-UMC-GAMMA", {"README.md": "# G\n"})
    _git(remote, "rm", "-q", "hydra-umc.project.json")
    _git(remote, "commit", "-q", "-m", "drop")
    with pytest.raises(cb.CorpusBuildError, match="hydra-umc.project.json"):
        cb.clone_all([{"name": "HYDRA-UMC-GAMMA", "url": str(remote), "commit": ""}], tmp_path / "ws")


def test_two_identical_builds_give_the_bundle_and_a_sources_file_that_says_unsigned(tmp_path: Path, remotes: dict[str, Path], stand_in: Path) -> None:
    config = _config(list(remotes))
    repositories = cb.clone_all(_plan(remotes), tmp_path / "ws")
    bundle = cb.build_twice(tmp_path / "ws", config, stand_in, "0.3.0", tmp_path / "out")
    assert bundle.name == "corpus-0.3.0.json"
    documents = json.loads(bundle.read_text(encoding="utf-8"))["documents"]
    assert sorted(d.split(":")[0] for d in documents) == ["HYDRA-UMC-ALPHA/README.md", "HYDRA-UMC-ALPHA/docs/guide.md", "HYDRA-UMC-BETA/README.md"]
    sources = json.loads(cb.write_sources(bundle, "0.3.0", repositories, "f" * 40).read_text(encoding="utf-8"))
    assert sources["signed"] is False and sources["reproducible"] is True
    assert sources["bundle"]["sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert not list((tmp_path / "out").glob("*.sig")) and not list((tmp_path / "out").glob("*.pem"))


@pytest.mark.parametrize("leak", ["seed", "path"])
def test_a_build_that_depends_on_the_hash_seed_or_the_place_is_refused(
    tmp_path: Path, remotes: dict[str, Path], stand_in: Path, monkeypatch: pytest.MonkeyPatch, leak: str
) -> None:
    cb.clone_all(_plan(remotes), tmp_path / "ws")
    monkeypatch.setenv("STAND_IN_LEAK", leak)
    with pytest.raises(cb.CorpusBuildError, match="not reproducible"):
        cb.build_twice(tmp_path / "ws", _config(list(remotes)), stand_in, "0.3.0", tmp_path / "out")
    assert not (tmp_path / "out" / "corpus-0.3.0.json").exists()


def test_a_release_that_is_not_a_version_and_a_failing_indexer_stop_the_build(tmp_path: Path, remotes: dict[str, Path], stand_in: Path) -> None:
    cb.clone_all(_plan(remotes), tmp_path / "ws")
    with pytest.raises(cb.CorpusBuildError, match="not a version"):
        cb.build_twice(tmp_path / "ws", _config(list(remotes)), stand_in, "latest", tmp_path / "out")
    (stand_in / "src" / "hydra_umc_docs_qa" / "main.py").write_text("import sys\nprint('boom')\nsys.exit(3)\n", encoding="utf-8")
    with pytest.raises(cb.CorpusBuildError, match="could not be built"):
        cb.build_twice(tmp_path / "ws", _config(list(remotes)), stand_in, "0.3.0", tmp_path / "out")


def test_same_pins_same_bytes_even_after_the_remote_moved(tmp_path: Path, remotes: dict[str, Path], stand_in: Path) -> None:
    config = _config(list(remotes))
    first_repos = cb.clone_all(_plan(remotes), tmp_path / "ws1")
    first = cb.build_twice(tmp_path / "ws1", config, stand_in, "0.3.0", tmp_path / "out1")
    (remotes["HYDRA-UMC-ALPHA"] / "README.md").write_text("# Alpha\n\nMoved on.\n", encoding="utf-8")
    _git(remotes["HYDRA-UMC-ALPHA"], "commit", "-q", "-am", "move")
    pins = {r["name"]: r["commit"] for r in first_repos}
    cb.clone_all(_plan(remotes, pins), tmp_path / "ws2")
    second = cb.build_twice(tmp_path / "ws2", config, stand_in, "0.3.0", tmp_path / "out2")
    assert first.read_bytes() == second.read_bytes()


def test_the_command_line_dry_run_changes_nothing_and_a_real_run_prints_pass(
    tmp_path: Path, remotes: dict[str, Path], stand_in: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "cfg.json"
    config.write_text(json.dumps({"schema": cb.CONFIG_SCHEMA, "owner": "Example", "repos": sorted(remotes), "exclude": []}), encoding="utf-8")
    argv = ["--release", "0.3.0", "--config", str(config), "--workspace", str(tmp_path / "ws"), "--out", str(tmp_path / "out"), "--docs-qa", str(stand_in)]
    assert cb.main([*argv, "--dry-run"]) == 0
    assert "CORPUS_BUILD=DRY_RUN" in capsys.readouterr().out and not (tmp_path / "ws").exists()
    cb.clone_all(_plan(remotes), tmp_path / "ws")
    assert cb.main([*argv, "--no-clone"]) == 0
    assert "CORPUS_BUILD=PASS" in capsys.readouterr().out
    assert cb.main(["--release", "x", "--config", str(tmp_path / "nope.json"), "--workspace", str(tmp_path / "w"), "--out", str(tmp_path / "o"), "--docs-qa", str(stand_in)]) == 1


def test_with_the_real_indexer_the_bundle_is_reproducible_and_loads_unsigned(tmp_path: Path, remotes: dict[str, Path]) -> None:
    docs_qa = Path(__file__).resolve().parents[2] / "HYDRA-UMC-DOCS-QA"
    if not (docs_qa / "src" / "hydra_umc_docs_qa" / "bundle.py").is_file():
        pytest.skip("no checkout of HYDRA-UMC-DOCS-QA next to this one")
    cb.clone_all(_plan(remotes), tmp_path / "ws")
    bundle = cb.build_twice(tmp_path / "ws", _config(list(remotes)), docs_qa, "0.3.0", tmp_path / "out")
    probe = (
        "import sys; sys.path.insert(0, sys.argv[2]); from hydra_umc_docs_qa.bundle import load_bundle; "
        "b = load_bundle(sys.argv[1], allow_unsigned=True); print(b.release, b.signed, len(b.documents))"
    )
    done = subprocess.run([sys.executable, "-I", "-c", probe, str(bundle), str(docs_qa / "src")], capture_output=True, text=True, check=True)
    assert done.stdout.split() == ["0.3.0", "False", "3"]
