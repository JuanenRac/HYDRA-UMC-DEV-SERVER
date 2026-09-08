# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Real CLI entry point for DS01 only:

- `config validate` - loads and validates one host-profile/toolchain/
  task-policy JSON document against the real schema in config.py.
- `inventory scan` - discovers real hydra-umc.project.json manifests
  under a workspace root (inventory.py).

No workspace, task runner, queue or AI provider integration exists yet -
those are DS02/DS04/DS05/DS06, later deliveries. Nothing here executes a
task or deploys anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigValidationError, HostProfile, TaskPolicy, ToolchainPolicy, load_json_document
from .inventory import scan_project_manifests

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydra-umc-dev-server",
        description="Reproducible development host for the HYDRA-UMC/URTC ecosystem - DS01 only: config schema validation and read-only manifest inventory.",
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
