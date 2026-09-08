#!/usr/bin/env bash
# HYDRA_UMC_SCRIPT_STANDARD_HEADER_BEGIN
# *****************************************************************************
# Project   : HYDRA-UMC-DEV-SERVER
# Script    : run.sh
# Purpose   : Runtime workflow for the project entry point.
# Author    : JuanenRac (Electro Hobby 3D)
# Email     : electrohobby3d@gmail.com
# Copyright : (C) 2026 JuanenRac
# License   : GPL-3.0 - see LICENSE
# *****************************************************************************
# HYDRA_UMC_SCRIPT_STANDARD_HEADER_END
# HYDRA_UMC_SCRIPT_STANDARD_BANNER_BEGIN
printf '\n*******************************************************************************\n'
printf '%s\n' "* HYDRA-UMC-DEV-SERVER - run.sh"
printf '%s\n' "* Mode      : RUN WORKFLOW"
printf '%s\n' "* Author    : JuanenRac (Electro Hobby 3D)"
printf '%s\n' "* Email     : electrohobby3d@gmail.com"
printf '%s\n' "* Copyright : (C) 2026 JuanenRac"
printf '%s\n' "* License   : GPL-3.0 - see LICENSE"
printf '%s\n' "* ------------------------------------------------------------------------- *"
printf '%s\n' "* 1. Resolve the runtime prerequisites declared by this script."
printf '%s\n' "* 2. Start the project entry point and forward user arguments unchanged."
printf '%s\n' "* 3. Preserve its result and keep an interactive terminal open."
printf '%s\n' "*******************************************************************************"
printf '\n'
# HYDRA_UMC_SCRIPT_STANDARD_BANNER_END
# Runs HYDRA-UMC-DEV-SERVER. Run ./build.sh first.
#
# Usage:
#   ./run.sh                                          - real demo: inventory
#                                                        scan against this
#                                                        GitHub workspace,
#                                                        then config validate
#                                                        against the real
#                                                        example task policy
#   ./run.sh inventory scan --root DIR
#   ./run.sh config validate configs/task-policy.example.json --kind task-policy
# This delivery (DS01) is CLI-only (no GUI yet) - see cli.py's own header
# comment. No workspace/task runner exists yet (that is DS04).
set -uo pipefail  # no -e: we need to reach the trap below even if the process exits non-zero
cd "$(dirname "$0")"

# Keep the window open if this was double-clicked instead of run from an
# already-open terminal - real output would otherwise flash-close before
# it's readable. Only prompts when stdin is actually a terminal (never in
# CI/piped/non-interactive runs).
trap '[ -t 0 ] && read -r -p "Press Enter to close..." _' EXIT

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif [ -f .venv/Scripts/activate ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
fi

if [ "$#" -eq 0 ]; then
    printf '%s\n' "No arguments given - running a real demo: inventory scan against this GitHub workspace, then config validate against the real example task policy."
    demo_root="$(cd "$(pwd)/.." && pwd)"
    python -m hydra_umc_dev_server.cli inventory scan --root "$demo_root"
    status=$?
    if [ "$status" -eq 0 ]; then
        echo
        python -m hydra_umc_dev_server.cli config validate configs/task-policy.example.json --kind task-policy
        status=$?
    fi
else
    python -m hydra_umc_dev_server.cli "$@"
    status=$?
fi
exit "$status"
