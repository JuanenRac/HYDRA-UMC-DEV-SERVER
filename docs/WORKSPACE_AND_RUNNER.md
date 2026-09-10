<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/WORKSPACE_AND_RUNNER.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Bounded workspace and runner (DS04)

DS04 is the first delivery that executes a subprocess. It runs **one**
allow-listed command, in a **per-task isolated workspace**, with a
**scrubbed environment**, under a **bounded timeout** - and kills the
whole process group if it overruns or is cancelled. It deploys nothing.

## The recipe

`configs/task-recipe.example.json`. One JSON object:

| Field | Meaning |
| --- | --- |
| `task_id` | 1-128 chars of `[A-Za-z0-9._-]`, starts alphanumeric, no `..`. Becomes the workspace directory name. |
| `repo` | The repository this task is for. |
| `revision` | A **pinned** revision: a commit hash (7-64 hex), a `vX.Y.Z` tag, or `refs/tags/...`. A bare branch name is rejected - a task is pinned, not "whatever HEAD is now". |
| `command` | argv. `command[0]` must be in the task policy's own `allowed_commands` (`config validate --kind task-policy`). |
| `timeout_seconds` | Positive, at most 3600. |
| `input_paths` | Relative paths the recipe declares it needs. Each is resolved inside the workspace; a `..`, an absolute path, or (at run time) a symlink target outside the workspace is refused. |

`hydra-umc-dev-server task validate <recipe> --policy <task-policy>` checks
all of the above and runs nothing.

## The workspace

`allocate_workspace(base, task_id, fs)` makes `<base>/<task_id>/`. It
refuses:

- a non-absolute `base`
- an unsafe `task_id`
- a `task_id` whose directory **already exists** - two tasks never share
  one workspace

`Workspace.resolve(relpath)` is the only sanctioned way to turn a
recipe-supplied path into an absolute one. It refuses an absolute input
and a `..` that climbs past the workspace root.
`Workspace.resolve_with(relpath, fs)` additionally follows symlinks with
the real filesystem and refuses a link whose target lands outside the
workspace - a link planted inside the workspace cannot smuggle a
read/write out of it.

## The run

`hydra-umc-dev-server task run <recipe> --policy <task-policy>
--workspace-base <dir>`:

1. Validate the recipe against the policy. A disallowed command, or an
   input path that escapes the workspace, is `rejected` - **nothing is
   spawned**.
2. Build the child environment: the safe allow-list only (`PATH`,
   `HOME`, `LANG`, `LC_ALL`, `TZ`; plus non-secret OS basics like
   `SYSTEMROOT` on Windows). Nothing else is inherited - no
   `GITHUB_TOKEN`, no `AWS_SECRET_ACCESS_KEY`, no `ANTHROPIC_API_KEY`,
   no `SSH_AUTH_SOCK`. This is DS04's "acceso a secretos se rechaza":
   the runner never hands a task a credential it happened to hold.
3. Spawn `command` with `cwd` = the workspace root, that scrubbed env,
   and its own process group / job (POSIX `start_new_session`, Windows
   `CREATE_NEW_PROCESS_GROUP`).
4. Poll. On the recipe's `timeout_seconds`, or when a cancel token is
   set, kill the **whole process group** (`killpg` SIGTERM then SIGKILL
   on POSIX; `taskkill /F /T` on Windows) - every descendant, not just
   the direct child.
5. Return a `RunResult`: `outcome` (`completed` / `timed-out` /
   `cancelled` / `rejected`), `exit_code`, bounded stdout/stderr tails,
   `duration_seconds`, `killed_process_group`.

`task run` exits `0` only on `completed` with exit code `0`.

## What DS04 still does not do

- no durable queue, lease, or execution journal (DS05)
- no AI provider (DS06)
- no network isolation beyond the scrubbed env, no cgroup/namespace
  sandbox yet - the workspace is a directory boundary, not a container
- it never deploys, and `allow_deploy` in the policy stays `False` by
  default the DS01 way
