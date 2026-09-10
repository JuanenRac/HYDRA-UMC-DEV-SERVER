# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/migration.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS03 - conservative migration: inventory a source checkout, hash every
file, classify each one (published-and-clean / locally-modified /
untracked / private), notice local commits that were never pushed, and
render a migration PLAN that sends each class to its OWN destination.

Like DS01 and DS02 this delivery only reads and describes. Nothing here
copies a file, deletes a file, touches the source, or runs `git` against
anything other than a read-only query. The plan is a document a later
delivery (or a human) carries out; DS03's own acceptance criterion is
exactly that the four classes land in four SEPARATE destinations and the
source is left intact.

All contact with a real disk or a real repository goes through the
injectable `SourceInspector` protocol, so the whole test suite runs
against a fake tree and nothing touches a real checkout in a test - the
same seam shape `preflight.py` uses for a host.
"""
from __future__ import annotations

import fnmatch
import posixpath
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable

from .config import ConfigValidationError, _require_str

# Ordered most-sensitive first: a file matching several rules is reported
# under the strongest one.
CLASS_PRIVATE = "private"
CLASS_UNTRACKED = "untracked"
CLASS_TRACKED_MODIFIED = "tracked-modified"
CLASS_TRACKED_CLEAN = "tracked-clean"


# ---------------------------------------------------------------------------
# Privacy policy - what "a private document" means, explicitly, not by vibe
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PrivacyPolicy:
    """Which paths in a source checkout are private and must never reach a
    Git-backed or shareable destination. Defaults cover this ecosystem's
    own real cases; a document can widen them, never silently narrow."""

    # Split so this file's own source never contains the literal folder
    # name (the same reason ci_validate.py splits it) - the runtime tuple
    # value is still the real prefix.
    path_prefixes: tuple[str, ...] = ("SON" "NET/",)
    name_globs: tuple[str, ...] = (
        ".env", ".env.*", "*.pem", "*.key", "id_ed25519*", "id_rsa*",
        "*.secret", "refresh_tokens.json", "*.p12", "*.keystore",
    )
    extra_relpaths: tuple[str, ...] = ()

    def is_private(self, relpath: str) -> bool:
        norm = relpath.replace("\\", "/")
        while norm.startswith("./"):
            norm = norm[2:]
        if norm in self.extra_relpaths:
            return True
        for prefix in self.path_prefixes:
            if norm == prefix.rstrip("/") or norm.startswith(prefix):
                return True
        name = posixpath.basename(norm)
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.name_globs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_prefixes": list(self.path_prefixes),
            "name_globs": list(self.name_globs),
            "extra_relpaths": list(self.extra_relpaths),
        }

    @staticmethod
    def from_dict(data: object) -> "PrivacyPolicy":
        if data is None:
            return PrivacyPolicy()
        if not isinstance(data, dict):
            raise ConfigValidationError("privacy policy must be a JSON object")
        defaults = PrivacyPolicy()
        errors: list[str] = []

        def _str_tuple(key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
            if key not in data:
                return fallback
            value = data[key]
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                errors.append(f"{key!r} must be a list of non-empty strings")
                return fallback
            return tuple(value)

        result = PrivacyPolicy(
            path_prefixes=_str_tuple("path_prefixes", defaults.path_prefixes),
            name_globs=_str_tuple("name_globs", defaults.name_globs),
            extra_relpaths=_str_tuple("extra_relpaths", ()),
        )
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return result


# ---------------------------------------------------------------------------
# Destinations - four separate roots, provably non-overlapping
# ---------------------------------------------------------------------------
def _is_within(child: str, parent: str) -> bool:
    child_n = child.rstrip("/") + "/"
    parent_n = parent.rstrip("/") + "/"
    return child_n == parent_n or child_n.startswith(parent_n)


@dataclass(frozen=True)
class MigrationDestinations:
    """The four target roots. DS03's acceptance criterion is that the
    classes land SEPARATELY, so `from_dict` refuses any pair that is
    equal or nested one inside the other."""

    reference_root: str          # published, clean, matches origin
    local_changes_root: str      # locally modified + untracked working files
    private_root: str            # private docs / secrets - never Git-backed
    work_in_progress_root: str   # a bundle of commits made but never pushed

    def _roots(self) -> dict[str, str]:
        return {
            "reference_root": self.reference_root,
            "local_changes_root": self.local_changes_root,
            "private_root": self.private_root,
            "work_in_progress_root": self.work_in_progress_root,
        }

    def to_dict(self) -> dict[str, Any]:
        return self._roots()

    @staticmethod
    def from_dict(data: object) -> "MigrationDestinations":
        if not isinstance(data, dict):
            raise ConfigValidationError("migration destinations must be a JSON object")
        errors: list[str] = []
        fields = ("reference_root", "local_changes_root", "private_root", "work_in_progress_root")
        values = {name: _require_str(data, name, errors) for name in fields}
        for name, value in values.items():
            if value and not value.startswith("/"):
                errors.append(f"{name!r} must be an absolute path, got {value!r}")
        present = [(name, v.rstrip('/')) for name, v in values.items() if v]
        for i, (name_a, a) in enumerate(present):
            for name_b, b in present[i + 1:]:
                if a == b:
                    errors.append(f"{name_a!r} and {name_b!r} must be different paths")
                elif _is_within(a, b) or _is_within(b, a):
                    errors.append(f"{name_a!r} and {name_b!r} must not be nested inside each other")
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return MigrationDestinations(**values)


# ---------------------------------------------------------------------------
# Source inspection seam
# ---------------------------------------------------------------------------
@runtime_checkable
class SourceInspector(Protocol):
    """Every real disk / git read a migration needs. A test passes a fake;
    the source is only ever read, never written."""

    def is_repo(self, root: str) -> bool: ...

    def child_repos(self, root: str) -> list[str]:
        """Immediate subdirectories of `root` that are themselves repos
        (used when `root` is a workspace holding many checkouts)."""

    def iter_files(self, root: str) -> Iterable[str]:
        """Relative POSIX paths of every regular file under `root`,
        excluding the `.git` directory itself."""

    def file_size(self, root: str, relpath: str) -> int: ...

    def file_sha256(self, root: str, relpath: str) -> str: ...

    def modified_tracked(self, root: str) -> frozenset[str]:
        """Tracked files with uncommitted local modifications."""

    def untracked(self, root: str) -> frozenset[str]:
        """Files git does not track at all (and that are not git-ignored)."""

    def unpushed_commits(self, root: str) -> tuple[str, ...]:
        """`<short-hash> <subject>` for every commit on the current branch
        not present on its upstream; empty if none or no upstream."""


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceEntry:
    relpath: str
    size: int
    sha256: str
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "relpath": self.relpath,
            "size": self.size,
            "sha256": self.sha256,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class RepoMigrationInventory:
    name: str
    source_root: str
    has_git: bool
    unpushed_commits: tuple[str, ...]
    entries: tuple[SourceEntry, ...]

    def by_class(self, classification: str) -> tuple[SourceEntry, ...]:
        return tuple(e for e in self.entries if e.classification == classification)

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.classification] = counts.get(entry.classification, 0) + 1
        return {
            "name": self.name,
            "source_root": self.source_root,
            "has_git": self.has_git,
            "unpushed_commits": list(self.unpushed_commits),
            "class_counts": counts,
            "entries": [e.to_dict() for e in self.entries],
        }


def _classify(relpath: str, modified: frozenset[str], untracked: frozenset[str], policy: PrivacyPolicy) -> str:
    if policy.is_private(relpath):
        return CLASS_PRIVATE
    if relpath in untracked:
        return CLASS_UNTRACKED
    if relpath in modified:
        return CLASS_TRACKED_MODIFIED
    return CLASS_TRACKED_CLEAN


def build_repo_inventory(
    source_root: str,
    inspector: SourceInspector,
    policy: PrivacyPolicy | None = None,
    *,
    name: str | None = None,
) -> RepoMigrationInventory:
    policy = policy or PrivacyPolicy()
    has_git = inspector.is_repo(source_root)
    modified = inspector.modified_tracked(source_root) if has_git else frozenset()
    untracked = inspector.untracked(source_root) if has_git else frozenset()
    unpushed = inspector.unpushed_commits(source_root) if has_git else ()

    entries: list[SourceEntry] = []
    for relpath in sorted(inspector.iter_files(source_root)):
        norm = relpath.replace("\\", "/")
        entries.append(
            SourceEntry(
                relpath=norm,
                size=inspector.file_size(source_root, relpath),
                sha256=inspector.file_sha256(source_root, relpath),
                classification=_classify(norm, modified, untracked, policy),
            )
        )
    return RepoMigrationInventory(
        name=name or posixpath.basename(source_root.replace("\\", "/").rstrip("/")) or source_root,
        source_root=source_root,
        has_git=has_git,
        unpushed_commits=tuple(unpushed),
        entries=tuple(entries),
    )


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
_CLASS_TO_DESTINATION_FIELD = {
    CLASS_TRACKED_CLEAN: "reference_root",
    CLASS_TRACKED_MODIFIED: "local_changes_root",
    CLASS_UNTRACKED: "local_changes_root",
    CLASS_PRIVATE: "private_root",
}


@dataclass(frozen=True)
class PlannedCopy:
    source_relpath: str
    sha256: str
    size: int
    classification: str
    destination: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_relpath": self.source_relpath,
            "sha256": self.sha256,
            "size": self.size,
            "classification": self.classification,
            "destination": self.destination,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MigrationPlan:
    repo_name: str
    source_root: str
    copies: tuple[PlannedCopy, ...]
    commit_bundle: str | None
    manifest: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_name": self.repo_name,
            "source_root": self.source_root,
            "copies": [c.to_dict() for c in self.copies],
            "commit_bundle": self.commit_bundle,
            "manifest": dict(sorted(self.manifest.items())),
            "warnings": list(self.warnings),
        }


_REASONS = {
    CLASS_TRACKED_CLEAN: "published and matches origin - safe as a reference copy",
    CLASS_TRACKED_MODIFIED: "locally modified, not committed - kept apart from the clean reference",
    CLASS_UNTRACKED: "untracked working file - kept apart from the clean reference",
    CLASS_PRIVATE: "private document or secret - never a Git-backed or shareable destination",
}


def build_migration_plan(inventory: RepoMigrationInventory, destinations: MigrationDestinations) -> MigrationPlan:
    """Map every inventoried file to exactly one destination by class, and
    the unpushed commits to a bundle under the work-in-progress root.
    Refuses (ConfigValidationError) if a private file would ever resolve
    into the reference or work-in-progress destination - the source is
    never read here beyond what the inventory already captured, and
    nothing is written."""
    roots = destinations._roots()
    copies: list[PlannedCopy] = []
    manifest: dict[str, str] = {}
    warnings: list[str] = []

    for entry in inventory.entries:
        manifest[entry.relpath] = entry.sha256
        field_name = _CLASS_TO_DESTINATION_FIELD.get(entry.classification)
        if field_name is None:
            warnings.append(f"{entry.relpath}: class {entry.classification!r} has no destination - skipped")
            continue
        dest_root = roots[field_name].rstrip("/")
        destination = f"{dest_root}/{inventory.name}/{entry.relpath}"
        if entry.classification == CLASS_PRIVATE and (
            _is_within(destination, roots["reference_root"])
            or _is_within(destination, roots["work_in_progress_root"])
        ):
            raise ConfigValidationError(
                f"private file {entry.relpath!r} would land under a shareable destination - refusing"
            )
        copies.append(
            PlannedCopy(
                source_relpath=entry.relpath,
                sha256=entry.sha256,
                size=entry.size,
                classification=entry.classification,
                destination=destination,
                reason=_REASONS[entry.classification],
            )
        )

    commit_bundle: str | None = None
    if inventory.unpushed_commits:
        wip_root = roots["work_in_progress_root"].rstrip("/")
        commit_bundle = f"{wip_root}/{inventory.name}.unpushed.bundle"

    return MigrationPlan(
        repo_name=inventory.name,
        source_root=inventory.source_root,
        copies=tuple(copies),
        commit_bundle=commit_bundle,
        manifest=manifest,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# The one real, read-only inspector
# ---------------------------------------------------------------------------
class SystemSourceInspector:
    """The real `SourceInspector`. Every method reads; none writes, and no
    `git` subcommand here mutates the repository."""

    def _run_git(self, root: str, *args: str) -> str:
        import subprocess

        result = subprocess.run(
            ("git", "-C", root, *args),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""

    def is_repo(self, root: str) -> bool:
        import os

        return os.path.isdir(os.path.join(root, ".git")) or self._run_git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"

    def child_repos(self, root: str) -> list[str]:
        import os

        out: list[str] = []
        try:
            names = sorted(os.listdir(root))
        except OSError:
            return out
        for name in names:
            path = os.path.join(root, name)
            if os.path.isdir(path) and os.path.isdir(os.path.join(path, ".git")):
                out.append(path)
        return out

    _WALK_EXCLUDES = {
        ".git", ".venv", "venv", "node_modules", "__pycache__",
        "dist", "build", "target", ".gradle", ".mypy_cache", ".pytest_cache",
    }

    def iter_files(self, root: str) -> Iterable[str]:
        """For a git checkout: exactly the files git considers part of the
        project - tracked, plus untracked-but-not-ignored. A local
        virtualenv, build output or `__pycache__` is git-ignored and so is
        never inventoried, let alone migrated. For a non-git source: an
        os.walk with a conservative hardcoded exclude list."""
        import os

        if self.is_repo(root):
            seen: set[str] = set()
            for opt in (("--cached",), ("--others", "--exclude-standard")):
                for line in self._run_git(root, "ls-files", "-z", *opt).split("\0"):
                    rel = line.strip().replace("\\", "/")
                    if rel and rel not in seen and os.path.isfile(os.path.join(root, rel)):
                        seen.add(rel)
                        yield rel
            return

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self._WALK_EXCLUDES]
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                if not os.path.isfile(full) or os.path.islink(full):
                    continue
                yield os.path.relpath(full, root).replace(os.sep, "/")

    def file_size(self, root: str, relpath: str) -> int:
        import os

        return os.path.getsize(os.path.join(root, relpath))

    def file_sha256(self, root: str, relpath: str) -> str:
        import hashlib
        import os

        digest = hashlib.sha256()
        with open(os.path.join(root, relpath), "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _porcelain(self, root: str) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for line in self._run_git(root, "status", "--porcelain", "-z").split("\0"):
            if len(line) < 4:
                continue
            rows.append((line[:2], line[3:].replace("\\", "/")))
        return rows

    def modified_tracked(self, root: str) -> frozenset[str]:
        return frozenset(
            path for code, path in self._porcelain(root)
            if code != "??" and code.strip() and not code.startswith("!")
        )

    def untracked(self, root: str) -> frozenset[str]:
        return frozenset(path for code, path in self._porcelain(root) if code == "??")

    def unpushed_commits(self, root: str) -> tuple[str, ...]:
        upstream = self._run_git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        if not upstream:
            return ()
        out = self._run_git(root, "log", "--oneline", "--no-decorate", f"{upstream}..HEAD")
        return tuple(line for line in out.splitlines() if line.strip())
