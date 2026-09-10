# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/workspace.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS04, part 1 - a bounded, per-task workspace.

Two of DS04's acceptance invariants live here, defended by test:

  * two tasks never collide - each task id gets its own directory under a
    shared base, and allocating one that already exists is refused rather
    than silently reused.
  * a path that escapes the workspace is refused - a `..` segment, an
    absolute path, or a symlink whose real target lands outside the
    workspace all raise `WorkspaceEscapeError`. Resolution uses the real,
    symlink-followed path, so a link planted inside the workspace can't
    smuggle a read/write outside it.

Every filesystem touch goes through the injectable `WorkspaceFs`
protocol, so the control tests run against a fake and never a real
private tree - matching the plan's "los controles se prueban con
fixtures, no con archivos privados reales".
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import ConfigValidationError

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class WorkspaceError(ConfigValidationError):
    """Base for every workspace-boundary refusal - a subclass of
    ConfigValidationError so the CLI reports it the same honest way as a
    bad config document, never as a raw traceback."""


class WorkspaceEscapeError(WorkspaceError):
    """A path resolved to somewhere outside its workspace."""


class WorkspaceCollisionError(WorkspaceError):
    """A task tried to allocate a workspace id that already exists."""


@runtime_checkable
class WorkspaceFs(Protocol):
    """The minimum filesystem surface a workspace needs. A test passes a
    fake; nothing here reads a real private path in a control test."""

    def exists(self, path: str) -> bool: ...

    def make_dir(self, path: str) -> None:
        """Create `path` (and only `path` - the parent must already
        exist), failing if it is already there."""

    def realpath(self, path: str) -> str:
        """`path` with every `..` and symlink resolved - the value the OS
        would actually open."""


def _normalise_abs(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/")).rstrip("/") or "/"


@dataclass(frozen=True)
class Workspace:
    """One task's private directory. `root` is absolute and already
    resolved; `resolve()` is the only sanctioned way to turn a
    recipe-supplied relative path into an absolute one."""

    task_id: str
    root: str

    def resolve(self, relpath: str) -> str:
        """Absolute, real path for `relpath` inside this workspace, or
        `WorkspaceEscapeError`. Rejects an absolute input, a `..` that
        climbs past `root`, and (via the caller's `realpath`, see
        `resolve_with`) a symlink target outside `root`."""
        cleaned = relpath.replace("\\", "/")
        if cleaned.startswith("/"):
            raise WorkspaceEscapeError(f"{relpath!r} is absolute - only paths inside the workspace are allowed")
        candidate = _normalise_abs(f"{self.root}/{cleaned}")
        if candidate != self.root and not candidate.startswith(self.root + "/"):
            raise WorkspaceEscapeError(f"{relpath!r} escapes the workspace {self.root!r}")
        return candidate

    def resolve_with(self, relpath: str, fs: WorkspaceFs) -> str:
        """Like `resolve()`, then also confirm the OS-real path (symlinks
        followed) is still inside `root` - the symlink-escape defence."""
        lexical = self.resolve(relpath)
        real = _normalise_abs(fs.realpath(lexical))
        real_root = _normalise_abs(fs.realpath(self.root))
        if real != real_root and not real.startswith(real_root + "/"):
            raise WorkspaceEscapeError(
                f"{relpath!r} resolves (via a symlink) to {real!r}, outside the workspace {real_root!r}"
            )
        return real


def _require_safe_id(task_id: str) -> str:
    if not isinstance(task_id, str) or not _SAFE_ID.match(task_id) or ".." in task_id:
        raise WorkspaceError(
            f"task id {task_id!r} must be 1-128 chars of [A-Za-z0-9._-], start alphanumeric, and contain no '..'"
        )
    return task_id


def allocate_workspace(base_root: str, task_id: str, fs: WorkspaceFs) -> Workspace:
    """Create `<base_root>/<task_id>/` for one task. Refuses a base that
    is not absolute, an unsafe id, and - the "two tasks never collide"
    invariant - a target directory that already exists."""
    if not base_root.startswith("/"):
        raise WorkspaceError(f"workspace base {base_root!r} must be an absolute path")
    safe_id = _require_safe_id(task_id)
    root = _normalise_abs(f"{base_root}/{safe_id}")
    if fs.exists(root):
        raise WorkspaceCollisionError(
            f"workspace for task {safe_id!r} already exists at {root!r} - two tasks must not share one"
        )
    fs.make_dir(root)
    return Workspace(task_id=safe_id, root=root)


class SystemWorkspaceFs:
    """The real `WorkspaceFs`. Used by `task run`; the control tests use a
    fake instead."""

    def exists(self, path: str) -> bool:
        import os

        return os.path.exists(path)

    def make_dir(self, path: str) -> None:
        import os

        os.mkdir(path, mode=0o750)

    def realpath(self, path: str) -> str:
        import os

        return os.path.realpath(path).replace(os.sep, "/")
