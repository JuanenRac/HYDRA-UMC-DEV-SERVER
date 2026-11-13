# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/corpus_build.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Builds the documentation corpus bundle of a release from the public repositories of the ecosystem, the same bytes every time.

The assistant that answers technicians (HYDRA-UMC-DOCS-QA) used to index documents on the small computer at every start. Here the index is built
once, in CI, from the PUBLIC repositories named in a configuration file, and the result is an UNSIGNED file: this code holds no key and signs
nothing. The release step signs the bundle on the maintainer's machine (FILE.sha256 and FILE.sig next to it), the image carries the signed
files, and the service checks them with a public key before it loads the index (see `docs/CORPUS_BUNDLE.md`).

What makes the build reproducible:

* every repository is taken at ONE commit and the commit is written to `corpus-<release>.sources.json`; a later build given that file
  (`--pin`) fetches exactly those commits again;
* the bundle is built TWICE, from two copies of the checkouts in different directories and under different hash seeds, and the build stops unless
  both files are identical byte for byte;
* the sources the index cites are `<repository>/<path>` (the nearest `hydra-umc.project.json` names the project), so the place of the workspace does
  not enter the file.

Nothing here reads a secret, a token or a private repository: the clones are anonymous HTTPS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SOURCES_SCHEMA = "hydra-corpus-sources/1"
CONFIG_SCHEMA = "hydra-corpus-repos/1"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RELEASE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")
MAX_BUNDLE_BYTES = 256 * 1024 * 1024

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class CorpusBuildError(ValueError):
    """The corpus cannot be built: a bad configuration, a missing checkout or two builds that differ."""


def load_config(path: Path) -> dict[str, Any]:
    """The list of public repositories and the patterns left out of the corpus."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CorpusBuildError(f"cannot read the corpus configuration: {error}") from error
    if not isinstance(raw, dict) or raw.get("schema") != CONFIG_SCHEMA:
        raise CorpusBuildError(f"the configuration must be an object with schema {CONFIG_SCHEMA!r}")
    owner, repos, exclude = raw.get("owner"), raw.get("repos"), raw.get("exclude", [])
    if not isinstance(owner, str) or not _NAME.match(owner):
        raise CorpusBuildError("owner must be a GitHub account name")
    if not isinstance(repos, list) or not repos or len(set(repos)) != len(repos):
        raise CorpusBuildError("repos must be a non-empty list without repeats")
    if not all(isinstance(r, str) and _NAME.match(r) for r in repos):
        raise CorpusBuildError("every repository name must be a plain name")
    if not isinstance(exclude, list) or not all(isinstance(p, str) and p and ".." not in p for p in exclude):
        raise CorpusBuildError("exclude must be a list of patterns")
    return {"owner": owner, "repos": sorted(repos), "exclude": list(exclude)}


def load_pins(path: Path) -> dict[str, str]:
    """`repository -> commit` from the sources file of an earlier build."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CorpusBuildError(f"cannot read the pins: {error}") from error
    if not isinstance(raw, dict) or raw.get("schema") != SOURCES_SCHEMA or not isinstance(raw.get("repositories"), list):
        raise CorpusBuildError("the pins file is not a corpus sources file")
    pins: dict[str, str] = {}
    for item in raw["repositories"]:
        if not isinstance(item, dict) or not _NAME.match(str(item.get("name"))) or not _SHA.match(str(item.get("commit"))):
            raise CorpusBuildError("a pin must name a repository and a full commit")
        pins[str(item["name"])] = str(item["commit"])
    return pins


def clone_plan(config: dict[str, Any], pins: dict[str, str] | None = None) -> list[dict[str, str]]:
    """What a build clones: one entry per repository, with the pinned commit when there is one (a pin for a repository not in the list is an error)."""
    pins = pins or {}
    unknown = sorted(set(pins) - set(config["repos"]))
    if unknown:
        raise CorpusBuildError(f"the pins name repositories the configuration does not list: {', '.join(unknown)}")
    return [
        {"name": name, "url": f"https://github.com/{config['owner']}/{name}.git", "commit": pins.get(name, "")}
        for name in config["repos"]
    ]


def _git(args: list[str], cwd: Path, runner: Runner) -> str:
    done = runner(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if done.returncode != 0:
        raise CorpusBuildError(f"git {args[0]} failed: {done.stderr.strip()[:200]}")
    return done.stdout.strip()


def clone_all(plan: list[dict[str, str]], workspace: Path, runner: Runner = subprocess.run) -> list[dict[str, str]]:
    """Clones every repository into `workspace/<name>` (shallow, anonymous) and returns `[{name, commit}]` of what was really checked out."""
    workspace.mkdir(parents=True, exist_ok=True)
    done: list[dict[str, str]] = []
    for item in plan:
        target = workspace / item["name"]
        if target.exists():
            raise CorpusBuildError(f"{target} already exists: use an empty workspace")
        target.mkdir()
        if item["commit"]:
            _git(["init", "-q"], target, runner)
            _git(["fetch", "-q", "--depth", "1", item["url"], item["commit"]], target, runner)
            _git(["checkout", "-q", "--detach", "FETCH_HEAD"], target, runner)
        else:
            shutil.rmtree(target)
            _git(["clone", "-q", "--depth", "1", item["url"], str(target)], workspace, runner)
        commit = _git(["rev-parse", "HEAD"], target, runner)
        if item["commit"] and commit != item["commit"]:
            raise CorpusBuildError(f"{item['name']} is at {commit}, not the pinned {item['commit']}")
        if not (target / "hydra-umc.project.json").is_file():
            raise CorpusBuildError(f"{item['name']} has no hydra-umc.project.json: it is not a project of the ecosystem")
        done.append({"name": item["name"], "commit": commit})
    return done


def write_manifest(config: dict[str, Any], workspace: Path, path: Path) -> Path:
    """The corpus manifest of DOCS-QA for these checkouts: the repositories are the roots, the configured patterns are left out."""
    roots = [str(workspace / name) for name in config["repos"]]
    path.write_text(json.dumps({"roots": roots, "exclude": config["exclude"], "documents": []}, indent=2), encoding="utf-8")
    return path


def _copy_workspace(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git"))


def _bundle_once(workspace: Path, config: dict[str, Any], docs_qa: Path, release: str, out: Path, hash_seed: str, runner: Runner) -> None:
    manifest = write_manifest(config, workspace, workspace / "corpus-manifest.json")
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(docs_qa / "src"), "HYDRA_UMC_DOCS_QA_CACHE_DIR": str(workspace / ".cache")}
    done = runner(
        [sys.executable, "-m", "hydra_umc_docs_qa.main", "bundle", "--release", release, "--corpus", str(manifest), "--out", str(out)],
        capture_output=True, text=True, check=False, env=env,
    )
    if done.returncode != 0:
        raise CorpusBuildError("the bundle could not be built: " + (done.stdout + done.stderr).strip()[-300:])


def build_twice(workspace: Path, config: dict[str, Any], docs_qa: Path, release: str, out_dir: Path, runner: Runner = subprocess.run) -> Path:
    """Builds the bundle from two copies of the checkouts in two directories and under two hash seeds; stops unless the two files are identical."""
    if not _RELEASE.match(release):
        raise CorpusBuildError(f"the release {release!r} is not a version such as 0.3.0")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="corpus-a-") as first, tempfile.TemporaryDirectory(prefix="corpus-b-") as second:
        copies = (Path(first) / "ws", Path(second) / "deeper" / "ws")
        outs = (Path(first) / "a.json", Path(second) / "b.json")
        for copy, out, seed in zip(copies, outs, ("1", "2"), strict=True):
            _copy_workspace(workspace, copy)
            _bundle_once(copy, config, docs_qa, release, out, seed, runner)
        a, b = outs[0].read_bytes(), outs[1].read_bytes()
        if a != b:
            raise CorpusBuildError("the two builds differ: the corpus is not reproducible from these checkouts")
        if len(a) > MAX_BUNDLE_BYTES:
            raise CorpusBuildError("the bundle is larger than DOCS-QA loads")
        target = out_dir / f"corpus-{release}.json"
        target.write_bytes(a)
    return target


def write_sources(bundle: Path, release: str, repositories: list[dict[str, str]], docs_qa_commit: str) -> Path:
    """`corpus-<release>.sources.json`: what the bundle was made from, and that it is NOT signed yet."""
    data = bundle.read_bytes()
    sources = {
        "schema": SOURCES_SCHEMA, "release": release, "docs_qa_commit": docs_qa_commit, "repositories": repositories,
        "bundle": {"name": bundle.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
        "signed": False, "reproducible": True,
    }
    path = bundle.with_name(f"corpus-{release}.sources.json")
    path.write_text(json.dumps(sources, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corpus_build", description="Build the unsigned, reproducible documentation corpus bundle of a release.")
    parser.add_argument("--release", required=True, help="The release the corpus belongs to, for example 0.3.0.")
    parser.add_argument("--config", type=Path, default=Path("configs/corpus-repos.json"), help="The list of public repositories (default configs/corpus-repos.json).")
    parser.add_argument("--workspace", type=Path, required=True, help="An empty directory the repositories are cloned into (or, with --no-clone, the checkouts).")
    parser.add_argument("--out", type=Path, required=True, help="Directory the bundle and its sources file are written to.")
    parser.add_argument("--docs-qa", type=Path, required=True, dest="docs_qa", help="A checkout of HYDRA-UMC-DOCS-QA.")
    parser.add_argument("--pin", type=Path, default=None, help="The sources file of an earlier build: fetch exactly those commits.")
    parser.add_argument("--no-clone", action="store_true", dest="no_clone", help="Use the checkouts already in --workspace (commits are read from them).")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Print what would be cloned and built, and do nothing else.")
    return parser


def main(argv: list[str] | None = None, runner: Runner = subprocess.run) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        plan = clone_plan(config, load_pins(args.pin) if args.pin else None)
        if args.dry_run:
            for item in plan:
                print(f"would use {item['url']} at {item['commit'] or 'the tip of the default branch'}")
            print(f"CORPUS_BUILD=DRY_RUN release {args.release}, {len(plan)} repositories, built twice, not signed")
            return 0
        if args.no_clone:
            repositories = [{"name": n, "commit": _git(["rev-parse", "HEAD"], args.workspace / n, runner)} for n in config["repos"]]
        else:
            repositories = clone_all(plan, args.workspace, runner)
        bundle = build_twice(args.workspace, config, args.docs_qa, args.release, args.out, runner)
        docs_qa_commit = _git(["rev-parse", "HEAD"], args.docs_qa, runner)
        sources = write_sources(bundle, args.release, repositories, docs_qa_commit)
    except CorpusBuildError as error:
        print(f"CORPUS_BUILD=FAIL {error}")
        return 1
    print(f"CORPUS_BUILD=PASS {bundle.name} {bundle.stat().st_size} bytes, sources {sources.name}, two identical builds, NOT signed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
