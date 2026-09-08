# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/inventory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real, read-only manifest discovery for DS01 - the concrete form of this
delivery's own acceptance criterion "el catalogo reconoce el nuevo
manifiesto en fixtures" (this project's own private development plan, section 13.13).
Same real, tested pattern HYDRA-UMC-OPS-AGENT's own edge role already uses
for the same job (src/hydra_umc_ops_agent/inventory.py's
scan_project_manifests()) - reused rather than reimplemented, since the
underlying problem (find real hydra-umc.project.json files under a
workspace root, report malformed ones honestly instead of dropping them)
is identical here.

Nothing in this module mutates anything, and it does not yet drive any
workspace or task - that is DS04/DS05, later deliveries.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_MANIFEST_FILENAME = "hydra-umc.project.json"
_REQUIRED_FIELDS = ("name", "version", "maturity")


@dataclass(frozen=True)
class ProjectManifest:
    """One real project's own declared identity, read straight from its
    hydra-umc.project.json - never re-derived or guessed from a directory
    name."""
    name: str
    version: str
    maturity: str
    manifest_path: str


@dataclass(frozen=True)
class ManifestScanIssue:
    """A real, named reason ONE candidate directory did not yield a
    ProjectManifest - kept distinct from a silently-skipped entry so a
    caller can tell "no project here at all" apart from "a project is
    here, but its manifest is broken"."""
    path: str
    reason: str


@dataclass(frozen=True)
class ManifestScanResult:
    projects: tuple[ProjectManifest, ...]
    issues: tuple[ManifestScanIssue, ...]


def scan_project_manifests(root: Path) -> ManifestScanResult:
    """Scans the immediate subdirectories of `root` for a real
    hydra-umc.project.json each, reading its own name/version/maturity.

    A subdirectory with no manifest at all is not an issue (most
    subdirectories of a workspace root are not HYDRA-UMC/URTC checkouts) -
    only a PRESENT-but-unreadable/malformed/incomplete manifest is
    recorded as a ManifestScanIssue, so real, honest partial failures are
    visible rather than silently dropped.
    """
    if not root.is_dir():
        return ManifestScanResult(projects=(), issues=(ManifestScanIssue(path=str(root), reason="root is not a real directory"),))

    projects: list[ProjectManifest] = []
    issues: list[ManifestScanIssue] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue
        try:
            raw = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(ManifestScanIssue(path=str(manifest_path), reason=f"could not read: {exc}"))
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(ManifestScanIssue(path=str(manifest_path), reason=f"not valid JSON: {exc}"))
            continue
        if not isinstance(data, dict):
            issues.append(ManifestScanIssue(path=str(manifest_path), reason="manifest is not a JSON object"))
            continue
        missing = [f for f in _REQUIRED_FIELDS if not isinstance(data.get(f), str) or not data.get(f)]
        if missing:
            issues.append(ManifestScanIssue(path=str(manifest_path), reason=f"missing/empty required field(s): {', '.join(missing)}"))
            continue
        projects.append(ProjectManifest(
            name=data["name"],
            version=data["version"],
            maturity=data["maturity"],
            manifest_path=str(manifest_path),
        ))
    return ManifestScanResult(projects=tuple(projects), issues=tuple(issues))
