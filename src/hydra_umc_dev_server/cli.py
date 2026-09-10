# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real CLI entry point for DS01 + DS02:

- `config validate` - loads and validates one host-profile/toolchain/
  task-policy JSON document against the real schema in config.py (DS01).
- `inventory scan` - discovers real hydra-umc.project.json manifests
  under a workspace root (inventory.py, DS01).
- `station validate` - loads and validates one remote-station profile
  (remote_station.py, DS02).
- `station preflight` - reads that profile and reports, read-only,
  whether THIS host is ready to become the station (preflight.py, DS02).
  This is the one command that inspects the real host - it still changes
  nothing.
- `station plan` - prints the dry-run provisioning plan for that profile
  (provision.py, DS02). Never executes a step.
- `migrate inventory` - hashes and classifies every file in a source
  checkout (migration.py, DS03). Read-only.
- `migrate plan` - renders the conservative-migration plan: clean,
  locally-modified, untracked and private files each go to their own
  destination; unpushed commits get a bundle. Copies nothing and never
  touches the source (migration.py, DS03).
- `task validate` - checks a task recipe against a task policy (pinned
  revision, allowed command). Runs nothing (recipe.py, DS04).
- `task run` - allocates an isolated per-task workspace and runs the
  recipe's allow-listed command in it, with a scrubbed environment and a
  bounded timeout; kills the whole process group on timeout
  (workspace.py + runner.py, DS04).
- `queue enqueue / status / reconcile / journal` - a SQLite-backed
  durable queue with leases and an append-only execution journal that
  survives a restart (durable_queue.py, DS05). A duplicate `enqueue` is
  a no-op; `reconcile` returns an expired lease to `queued`; a result
  from a worker that no longer holds the lease is rejected, not accepted
  as done; a base that moved since enqueue blocks promotion.
- `provider suggest` - runs one step of a deterministic FAKE AI provider
  through a safety contract (ai_provider.py, DS06): a timeout, malformed
  output or quota exhaustion is a bounded named outcome; a configured
  budget stops the step; the suggestion is returned as inert data with
  `grants_no_permissions` / `triggers_no_deploy` always true, and an
  instruction-like suggestion is flagged, never acted on. Which real
  provider to use is a user decision - only `kind: "fake"` is accepted.

`task run` is the only command that executes a subprocess, and only an
allow-listed command, in an isolated workspace, with no inherited
secrets; it still deploys nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigValidationError, HostProfile, TaskPolicy, ToolchainPolicy, load_json_document
from .inventory import scan_project_manifests
from .migration import (
    MigrationDestinations,
    PrivacyPolicy,
    SystemSourceInspector,
    build_migration_plan,
    build_repo_inventory,
)
from .ai_provider import FakeProvider, ProviderConfig, run_provider_step
from .durable_queue import DurableQueue
from .preflight import SystemHostInspector, run_preflight
from .provision import build_provision_plan
from .recipe import TaskRecipe
from .remote_station import RemoteStationProfile
from .runner import SubprocessLauncher, run_task
from .workspace import SystemWorkspaceFs, allocate_workspace

_KIND_LOADERS = {
    "host-profile": HostProfile.from_dict,
    "toolchain": ToolchainPolicy.from_dict,
    "task-policy": TaskPolicy.from_dict,
}


def _cmd_config_validate(args: argparse.Namespace) -> int:
    path = Path(args.config_file)
    try:
        data = load_json_document(path)
        document = _KIND_LOADERS[args.kind](data)
    except ConfigValidationError as exc:
        print(f"INVALID: {path} ({args.kind}): {exc}", file=sys.stderr)
        return 1
    print(f"VALID: {path} ({args.kind})")
    print(json.dumps(document.to_dict(), indent=2))
    return 0


def _cmd_inventory_scan(args: argparse.Namespace) -> int:
    result = scan_project_manifests(Path(args.root))
    payload = {
        "root": args.root,
        "projects": [
            {"name": p.name, "version": p.version, "maturity": p.maturity, "manifest_path": p.manifest_path}
            for p in result.projects
        ],
        "issues": [{"path": i.path, "reason": i.reason} for i in result.issues],
    }
    text = json.dumps(payload, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote inventory to {args.out} ({len(result.projects)} project(s), {len(result.issues)} issue(s)).")
    else:
        print(text)
    return 0


def _load_station_profile(config_file: str) -> RemoteStationProfile:
    return RemoteStationProfile.from_dict(load_json_document(Path(config_file)))


def _cmd_station_validate(args: argparse.Namespace) -> int:
    path = Path(args.config_file)
    try:
        profile = _load_station_profile(args.config_file)
    except ConfigValidationError as exc:
        print(f"INVALID: {path} (remote-station): {exc}", file=sys.stderr)
        return 1
    print(f"VALID: {path} (remote-station)")
    print(json.dumps(profile.to_dict(), indent=2))
    return 0


def _cmd_station_preflight(args: argparse.Namespace) -> int:
    path = Path(args.config_file)
    try:
        profile = _load_station_profile(args.config_file)
    except ConfigValidationError as exc:
        print(f"INVALID: {path} (remote-station): {exc}", file=sys.stderr)
        return 1
    report = run_preflight(profile, SystemHostInspector())
    print(json.dumps(report.to_dict(), indent=2))
    if not report.ok:
        print(f"PREFLIGHT=FAIL {', '.join(c.name for c in report.failures())}", file=sys.stderr)
        return 1
    print("PREFLIGHT=PASS")
    return 0


def _cmd_station_plan(args: argparse.Namespace) -> int:
    path = Path(args.config_file)
    try:
        profile = _load_station_profile(args.config_file)
        report = run_preflight(profile, SystemHostInspector()) if args.preflight else None
        plan = build_provision_plan(profile, report)
    except ConfigValidationError as exc:
        print(f"INVALID: {path} (remote-station): {exc}", file=sys.stderr)
        return 1
    print(json.dumps(plan.to_dict(), indent=2))
    return 0


def _cmd_migrate_inventory(args: argparse.Namespace) -> int:
    root = str(Path(args.source_root))
    inspector = SystemSourceInspector()
    if inspector.is_repo(root):
        roots = [root]
    else:
        roots = inspector.child_repos(root)
        if not roots:
            print(f"no git checkout found at {root} or in its immediate subdirectories", file=sys.stderr)
            return 1
    payload = [build_repo_inventory(r, inspector).to_dict() for r in roots]
    print(json.dumps(payload if len(payload) != 1 else payload[0], indent=2))
    return 0


def _cmd_migrate_plan(args: argparse.Namespace) -> int:
    root = str(Path(args.source_root))
    try:
        document = load_json_document(Path(args.destinations))
        destinations = MigrationDestinations.from_dict(document)
        policy = PrivacyPolicy.from_dict(document.get("privacy_policy"))
    except ConfigValidationError as exc:
        print(f"INVALID: {args.destinations} (migration-destinations): {exc}", file=sys.stderr)
        return 1

    inspector = SystemSourceInspector()
    roots = [root] if inspector.is_repo(root) else inspector.child_repos(root)
    if not roots:
        print(f"no git checkout found at {root} or in its immediate subdirectories", file=sys.stderr)
        return 1
    try:
        plans = [build_migration_plan(build_repo_inventory(r, inspector, policy), destinations) for r in roots]
    except ConfigValidationError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    out = [p.to_dict() for p in plans]
    print(json.dumps(out if len(out) != 1 else out[0], indent=2))
    return 0


def _load_task_policy(path: str) -> TaskPolicy:
    return TaskPolicy.from_dict(load_json_document(Path(path)))


def _cmd_task_validate(args: argparse.Namespace) -> int:
    recipe_path = Path(args.recipe_file)
    try:
        recipe = TaskRecipe.from_dict(load_json_document(recipe_path))
        policy = _load_task_policy(args.policy)
        recipe.validate_against(policy)
    except ConfigValidationError as exc:
        print(f"INVALID: {recipe_path} (task-recipe): {exc}", file=sys.stderr)
        return 1
    print(f"VALID: {recipe_path} (task-recipe)")
    print(json.dumps(recipe.to_dict(), indent=2))
    return 0


def _cmd_task_run(args: argparse.Namespace) -> int:
    recipe_path = Path(args.recipe_file)
    try:
        recipe = TaskRecipe.from_dict(load_json_document(recipe_path))
        policy = _load_task_policy(args.policy)
    except ConfigValidationError as exc:
        print(f"INVALID: {recipe_path} (task-recipe): {exc}", file=sys.stderr)
        return 1
    try:
        workspace = allocate_workspace(str(Path(args.workspace_base)), recipe.task_id, SystemWorkspaceFs())
    except ConfigValidationError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    result = run_task(recipe, policy, workspace, SubprocessLauncher())
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.outcome == "completed" and result.exit_code == 0 else 1


def _cmd_queue_enqueue(args: argparse.Namespace) -> int:
    try:
        recipe = TaskRecipe.from_dict(load_json_document(Path(args.recipe_file)))
    except ConfigValidationError as exc:
        print(f"INVALID: {args.recipe_file} (task-recipe): {exc}", file=sys.stderr)
        return 1
    with DurableQueue(args.db) as queue:
        outcome = queue.enqueue(recipe, args.base_fingerprint)
    print(json.dumps({"created": outcome.created, "entry": outcome.entry.to_dict()}, indent=2))
    return 0


def _cmd_queue_status(args: argparse.Namespace) -> int:
    with DurableQueue(args.db) as queue:
        reclaimed = queue.reconcile() if args.reconcile else 0
        stats = queue.stats()
    print(json.dumps({"reconciled": reclaimed, **stats}, indent=2))
    return 0


def _cmd_queue_reconcile(args: argparse.Namespace) -> int:
    with DurableQueue(args.db) as queue:
        count = queue.reconcile()
    print(json.dumps({"returned_to_queued": count}, indent=2))
    return 0


def _cmd_queue_journal(args: argparse.Namespace) -> int:
    with DurableQueue(args.db) as queue:
        events = queue.journal_for(args.task_id)
    if not events:
        print(f"no journal entries for task {args.task_id!r}", file=sys.stderr)
        return 1
    print(json.dumps(events, indent=2))
    return 0


def _cmd_provider_suggest(args: argparse.Namespace) -> int:
    try:
        config = ProviderConfig.from_dict(load_json_document(Path(args.config)))
    except ConfigValidationError as exc:
        print(f"INVALID: {args.config} (ai-provider): {exc}", file=sys.stderr)
        return 1
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    result = run_provider_step(config, FakeProvider(args.scenario), prompt)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.outcome == "suggested" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydra-umc-dev-server",
        description="Reproducible development host for the HYDRA-UMC/URTC ecosystem - DS01 (config schema, manifest inventory), DS02 (remote-station profile, host preflight, provisioning plan), DS03 (conservative-migration inventory and plan), DS04 (bounded task recipe + isolated workspace runner), DS05 (durable SQLite queue + execution journal) and DS06 (interchangeable AI provider - deterministic fake only, behind a safety contract). Only 'task run' executes anything, and only an allow-listed command in an isolated workspace with no inherited secrets.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    config = subparsers.add_parser("config", help="Configuration document commands.")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    validate = config_sub.add_parser("validate", help="Validate one configuration document against its real schema.")
    validate.add_argument("config_file", help="Path to a JSON configuration document.")
    validate.add_argument("--kind", required=True, choices=sorted(_KIND_LOADERS), help="Which schema to validate against.")
    validate.set_defaults(func=_cmd_config_validate)

    inventory = subparsers.add_parser("inventory", help="Manifest discovery commands.")
    inventory_sub = inventory.add_subparsers(dest="inventory_command", required=True)
    scan = inventory_sub.add_parser("scan", help="Scan a workspace root for real hydra-umc.project.json manifests.")
    scan.add_argument("--root", required=True, help="Directory whose immediate subdirectories are scanned.")
    scan.add_argument("--out", help="Write the inventory JSON here instead of stdout.")
    scan.set_defaults(func=_cmd_inventory_scan)

    station = subparsers.add_parser("station", help="Remote-station profile commands (DS02).")
    station_sub = station.add_subparsers(dest="station_command", required=True)

    station_validate = station_sub.add_parser("validate", help="Validate one remote-station profile document.")
    station_validate.add_argument("config_file", help="Path to a remote-station profile JSON document.")
    station_validate.set_defaults(func=_cmd_station_validate)

    station_preflight = station_sub.add_parser(
        "preflight", help="Read-only check of whether THIS host is ready to become the station. Changes nothing."
    )
    station_preflight.add_argument("config_file", help="Path to a remote-station profile JSON document.")
    station_preflight.set_defaults(func=_cmd_station_preflight)

    station_plan = station_sub.add_parser(
        "plan", help="Print the dry-run provisioning plan for the profile. Never executes a step."
    )
    station_plan.add_argument("config_file", help="Path to a remote-station profile JSON document.")
    station_plan.add_argument(
        "--preflight",
        action="store_true",
        help="Run the read-only host preflight first and refuse the plan if the host is not ready.",
    )
    station_plan.set_defaults(func=_cmd_station_plan)

    migrate = subparsers.add_parser("migrate", help="Conservative-migration commands (DS03).")
    migrate_sub = migrate.add_subparsers(dest="migrate_command", required=True)

    migrate_inventory = migrate_sub.add_parser(
        "inventory",
        help="Hash and classify every file in a source checkout (or every checkout under a root). Read-only.",
    )
    migrate_inventory.add_argument("source_root", help="A git checkout, or a directory of them.")
    migrate_inventory.set_defaults(func=_cmd_migrate_inventory)

    migrate_plan = migrate_sub.add_parser(
        "plan",
        help="Render the migration plan: each file class to its own destination. Copies nothing, touches nothing in the source.",
    )
    migrate_plan.add_argument("source_root", help="A git checkout, or a directory of them.")
    migrate_plan.add_argument(
        "--destinations", required=True, help="Path to a migration-destinations JSON document."
    )
    migrate_plan.set_defaults(func=_cmd_migrate_plan)

    task = subparsers.add_parser("task", help="Bounded task recipe/runner commands (DS04).")
    task_sub = task.add_subparsers(dest="task_command", required=True)

    task_validate = task_sub.add_parser(
        "validate",
        help="Validate a task recipe against a task-policy document (pinned revision, allowed command). Runs nothing.",
    )
    task_validate.add_argument("recipe_file", help="Path to a task-recipe JSON document.")
    task_validate.add_argument("--policy", required=True, help="Path to a task-policy JSON document (DS01 schema).")
    task_validate.set_defaults(func=_cmd_task_validate)

    task_run = task_sub.add_parser(
        "run",
        help="Allocate an isolated workspace and run the recipe's allowed command in it, with a scrubbed environment and a bounded timeout. Kills the whole process group on timeout.",
    )
    task_run.add_argument("recipe_file", help="Path to a task-recipe JSON document.")
    task_run.add_argument("--policy", required=True, help="Path to a task-policy JSON document.")
    task_run.add_argument("--workspace-base", required=True, help="Absolute directory under which the per-task workspace is created.")
    task_run.set_defaults(func=_cmd_task_run)

    queue = subparsers.add_parser("queue", help="Durable task queue + execution journal commands (DS05).")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)

    queue_enqueue = queue_sub.add_parser(
        "enqueue", help="Add one task recipe to the durable queue. A duplicate task_id is a no-op, never a second job."
    )
    queue_enqueue.add_argument("recipe_file", help="Path to a task-recipe JSON document.")
    queue_enqueue.add_argument("--db", required=True, help="Path to the SQLite queue database (created if absent).")
    queue_enqueue.add_argument(
        "--base-fingerprint", required=True,
        help="Opaque fingerprint of the source base this task is pinned to; a different one at result time blocks promotion.",
    )
    queue_enqueue.set_defaults(func=_cmd_queue_enqueue)

    queue_status = queue_sub.add_parser("status", help="Print entry counts by state and the journal row count.")
    queue_status.add_argument("--db", required=True, help="Path to the SQLite queue database.")
    queue_status.add_argument("--reconcile", action="store_true", help="Return expired leases to 'queued' first.")
    queue_status.set_defaults(func=_cmd_queue_status)

    queue_reconcile = queue_sub.add_parser(
        "reconcile", help="Return every entry with an expired lease to 'queued'. Safe on every startup; idempotent."
    )
    queue_reconcile.add_argument("--db", required=True, help="Path to the SQLite queue database.")
    queue_reconcile.set_defaults(func=_cmd_queue_reconcile)

    queue_journal = queue_sub.add_parser("journal", help="Print the append-only execution journal for one task.")
    queue_journal.add_argument("task_id", help="The task id.")
    queue_journal.add_argument("--db", required=True, help="Path to the SQLite queue database.")
    queue_journal.set_defaults(func=_cmd_queue_journal)

    provider = subparsers.add_parser("provider", help="Interchangeable AI provider commands (DS06, deterministic fake only).")
    provider_sub = provider.add_subparsers(dest="provider_command", required=True)
    provider_suggest = provider_sub.add_parser(
        "suggest",
        help="Run one provider step through the safety contract and print the inert ProviderResult. Wires the suggestion to nothing.",
    )
    provider_suggest.add_argument("--config", required=True, help="Path to an ai-provider JSON document (kind must be 'fake').")
    provider_suggest.add_argument("--prompt-file", required=True, help="Path to a text file with the prompt.")
    provider_suggest.add_argument(
        "--scenario", default="ok", choices=("ok", "timeout", "malformed", "quota", "injection"),
        help="Which fake-provider path to exercise (default: ok).",
    )
    provider_suggest.set_defaults(func=_cmd_provider_suggest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
