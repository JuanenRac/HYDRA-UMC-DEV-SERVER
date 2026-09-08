@echo off
REM HYDRA_UMC_SCRIPT_STANDARD_HEADER_BEGIN
REM *****************************************************************************
REM Project   : HYDRA-UMC-DEV-SERVER
REM Script    : run.bat
REM Purpose   : Runtime workflow for the project entry point.
REM Author    : JuanenRac (Electro Hobby 3D)
REM Email     : electrohobby3d@gmail.com
REM Copyright : (C) 2026 JuanenRac
REM License   : GPL-3.0 - see LICENSE
REM *****************************************************************************
REM HYDRA_UMC_SCRIPT_STANDARD_HEADER_END
REM HYDRA_UMC_SCRIPT_STANDARD_BANNER_BEGIN
echo.
echo *****************************************************************************
echo * HYDRA-UMC-DEV-SERVER - run.bat
echo * Mode      : RUN WORKFLOW
echo * Author    : JuanenRac (Electro Hobby 3D)
echo * Email     : electrohobby3d@gmail.com
echo * Copyright : (C) 2026 JuanenRac
echo * License   : GPL-3.0 - see LICENSE
echo * ------------------------------------------------------------------------- *
echo * 1. Resolve the runtime prerequisites declared by this script.
echo * 2. Start the project entry point and forward user arguments unchanged.
echo * 3. Preserve its result and keep an interactive terminal open.
echo *****************************************************************************
echo.
REM HYDRA_UMC_SCRIPT_STANDARD_BANNER_END
REM Runs HYDRA-UMC-DEV-SERVER. Run build.bat first.
REM
REM Usage:
REM   run.bat                                        - real demo: inventory
REM                                                     scan against this
REM                                                     GitHub workspace,
REM                                                     then config validate
REM                                                     against the real
REM                                                     example task policy
REM   run.bat inventory scan --root DIR
REM   run.bat config validate configs\task-policy.example.json --kind task-policy
REM This delivery (DS01) is CLI-only (no GUI yet) - see cli.py's own header
REM comment. No workspace/task runner exists yet (that is DS04).
setlocal enabledelayedexpansion
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
    set "HYDRA_UMC_PY=.venv\Scripts\python.exe"
) else (
    set "HYDRA_UMC_PY=python"
)

if "%~1"=="" (
    echo No arguments given - running a real demo: inventory scan against this GitHub workspace, then config validate against the real example task policy.
    for %%I in ("%~dp0..") do set "HYDRA_UMC_DEMO_ROOT=%%~fI"
    "!HYDRA_UMC_PY!" -m hydra_umc_dev_server.cli inventory scan --root "!HYDRA_UMC_DEMO_ROOT!"
    if errorlevel 1 goto :done
    echo.
    "!HYDRA_UMC_PY!" -m hydra_umc_dev_server.cli config validate configs\task-policy.example.json --kind task-policy
) else (
    "!HYDRA_UMC_PY!" -m hydra_umc_dev_server.cli %*
)

:done
pause
