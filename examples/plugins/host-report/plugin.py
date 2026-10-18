# =============================================================================
# HYDRA-UMC-DEV-SERVER - examples/plugins/host-report/plugin.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Example plugin that provides one REPORT: a read-only summary of this host.

A report takes no arguments and returns a JSON-serializable dict. It must not
change anything: it only describes. Copy this directory, change the report and
approve the new SHA-256 shown by `plugin list`.
"""
import os
import platform
import shutil
import sys


def host_summary() -> dict:
    total, used, free = shutil.disk_usage(os.getcwd())
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "disk_total_bytes": total,
        "disk_free_bytes": free,
    }


def register(registry) -> None:
    registry.add_report("host-summary", host_summary)
