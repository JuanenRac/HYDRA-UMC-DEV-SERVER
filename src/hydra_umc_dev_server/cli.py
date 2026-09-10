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

No workspace, task runner, queue or AI provider integration exists yet -
those are DS04/DS05/DS06, later deliveries. Nothing here executes a task,
provisions a host, or deploys anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigValidationError, HostProfile, TaskPolicy, ToolchainPolicy, load_json_document
from .inventory import scan_project_manifests
from .preflight import SystemHostInspector, run_preflight
from .provision import build_provision_plan
from .remote_station import RemoteStationProfile

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydra-umc-dev-server",
        description="Reproducible development host for the HYDRA-UMC/URTC ecosystem - DS01 (config schema validation, read-only manifest inventory) and DS02 (remote-station profile, read-only host preflight, dry-run provisioning plan).",
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
