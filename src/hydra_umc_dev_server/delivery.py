# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/delivery.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS10 - the delivery package and an HONEST maturity evaluation.

`build_delivery_manifest()` enumerates what this repository actually
ships (modules, docs, configs, CLI subcommands, version) with a sha256
per file. `evaluate_maturity()` reports each of the ten deliveries as
`shipped` / `partial` / `not-started` against real evidence, lists the
known limitations plainly, and - the point of DS10 - never returns
`"established"`. What is here is contracts, limits and a verifiable
skeleton; the evaluation says exactly that.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__

# One entry per delivery: (id, one-line scope, the module that carries it,
# whether it is fully shipped in this repo today).
_DELIVERIES: tuple[tuple[str, str, str | None, str], ...] = (
    ("DS01", "config schema + read-only manifest inventory", "config.py", "shipped"),
    ("DS02", "remote-station profile + read-only host preflight + dry-run provisioning plan", "remote_station.py", "shipped"),
    ("DS03", "conservative migration: hash + classify + separate-destination plan, source untouched", "migration.py", "shipped"),
    ("DS04", "bounded task recipe + isolated workspace runner (scrubbed env, process-group kill)", "runner.py", "shipped"),
    ("DS05", "durable SQLite queue + append-only execution journal, survives a restart", "durable_queue.py", "shipped"),
    ("DS06", "interchangeable AI provider behind a safety contract - deterministic fake only", "ai_provider.py", "partial"),
    ("DS07", "authenticated incident transport for the OPS-AGENT round trip", "incident_transport.py", "shipped"),
    ("DS08", "one fully controlled repair cycle, gated at every step with rollback", "repair_cycle.py", "shipped"),
    ("DS09", "stable-operation health checks + verified state backup/restore", "operations.py", "shipped"),
    ("DS10", "this delivery package + honest maturity evaluation", "delivery.py", "shipped"),
)

# Stated plainly so no reader mistakes the skeleton for a running system.
_KNOWN_LIMITATIONS: tuple[str, ...] = (
    "No real AI provider is wired - only the deterministic fake. The real "
    "provider, its authorization, cost and terms are a user decision (DS06).",
    "The incident transport is a protocol object with an injectable channel; "
    "no real network transport (TLS/mTLS/a bus) is implemented (DS07).",
    "`task run` isolates by a workspace directory and a scrubbed environment, "
    "not a container / namespace / cgroup sandbox (DS04).",
    "There is no worker loop wiring the queue -> provider -> runner -> repair "
    "cycle together; each piece is exercised in isolation.",
    "Provisioning, migration and repair install are all described or dry-run; "
    "nothing here creates a user, opens a port, copies a file to a real "
    "destination, or deploys anything.",
    "No target hardware (Raspberry Pi 5 / CM5) has been provisioned or "
    "validated - platform choice and hardware verification are still open.",
    "Every 'real host' contact in the codebase is behind an injectable seam "
    "and is never touched in a test.",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class DeliveryManifest:
    project: str
    version: str
    files: dict[str, str] = field(default_factory=dict)  # relpath -> sha256
    cli_subcommands: tuple[str, ...] = ()
    test_files: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "version": self.version,
            "cli_subcommands": list(self.cli_subcommands),
            "test_files": self.test_files,
            "files": dict(sorted(self.files.items())),
        }


def build_delivery_manifest(repo_root: str | Path) -> DeliveryManifest:
    root = Path(repo_root)
    files: dict[str, str] = {}

    def _add(rel: str) -> None:
        p = root / rel
        if p.is_file():
            files[rel] = _sha256_bytes(p.read_bytes())

    src = root / "src" / "hydra_umc_dev_server"
    for module in sorted(src.glob("*.py")):
        _add(str(module.relative_to(root)).replace("\\", "/"))
    for doc in sorted((root / "docs").glob("*.md")):
        _add(str(doc.relative_to(root)).replace("\\", "/"))
    for cfg in sorted((root / "configs").glob("*.json")):
        _add(str(cfg.relative_to(root)).replace("\\", "/"))
    for name in ("pyproject.toml", "hydra-umc.project.json", "CHANGELOG.md", "README.md"):
        _add(name)

    cli_text = (src / "cli.py").read_text(encoding="utf-8") if (src / "cli.py").is_file() else ""
    subs = tuple(sorted({
        line.split('add_parser("', 1)[1].split('"', 1)[0]
        for line in cli_text.splitlines()
        if "subparsers.add_parser(" in line and 'add_parser("' in line
    }))
    test_files = len(list((root / "tests").glob("test_*.py"))) if (root / "tests").is_dir() else 0

    return DeliveryManifest(
        project="HYDRA-UMC-DEV-SERVER",
        version=__version__,
        files=files,
        cli_subcommands=subs,
        test_files=test_files,
    )


@dataclass(frozen=True)
class DeliveryStatus:
    delivery_id: str
    scope: str
    module: str | None
    status: str            # shipped | partial | not-started
    module_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "scope": self.scope,
            "module": self.module,
            "status": self.status,
            "module_present": self.module_present,
        }


@dataclass(frozen=True)
class MaturityEvaluation:
    project: str
    version: str
    overall_maturity: str          # always "scaffolding" from this code
    deliveries: tuple[DeliveryStatus, ...]
    known_limitations: tuple[str, ...]
    honest_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "version": self.version,
            "overall_maturity": self.overall_maturity,
            "deliveries": [d.to_dict() for d in self.deliveries],
            "known_limitations": list(self.known_limitations),
            "honest_summary": self.honest_summary,
        }


def evaluate_maturity(repo_root: str | Path) -> MaturityEvaluation:
    root = Path(repo_root)
    src = root / "src" / "hydra_umc_dev_server"
    statuses: list[DeliveryStatus] = []
    for delivery_id, scope, module, status in _DELIVERIES:
        present = bool(module) and (src / module).is_file()
        statuses.append(DeliveryStatus(
            delivery_id=delivery_id, scope=scope, module=module,
            status=status if present or module is None else "not-started",
            module_present=present,
        ))

    shipped = sum(1 for s in statuses if s.status == "shipped")
    partial = sum(1 for s in statuses if s.status == "partial")
    summary = (
        f"All ten deliveries are in the repository ({shipped} shipped, {partial} partial - "
        f"DS06 ships only the deterministic fake provider). The maturity stays "
        f"'scaffolding': this is contracts, limits and a verifiable skeleton, not a "
        f"running system. Nothing here provisions a host, executes a deploy, or has "
        f"touched target hardware. See known_limitations."
    )
    return MaturityEvaluation(
        project="HYDRA-UMC-DEV-SERVER",
        version=__version__,
        overall_maturity="scaffolding",   # deliberately not derivable to anything higher
        deliveries=tuple(statuses),
        known_limitations=_KNOWN_LIMITATIONS,
        honest_summary=summary,
    )
