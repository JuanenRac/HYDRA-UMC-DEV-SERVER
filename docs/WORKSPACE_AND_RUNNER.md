<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/WORKSPACE_AND_RUNNER.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
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
   `HOME`, `LANG`, `LC_ALL`, `TZ`; `PATH` is fixed to `/usr/local/bin:/usr/bin:/bin` on a POSIX host and `HOME` is the workspace; plus non-secret OS basics like
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

The child's stdout and stderr are read continuously while it runs, and only the
last 8 KiB of each is kept (invalid UTF-8 is replaced, not fatal). They used to be
read only after the child exited, so a task that printed more than a pipe holds
(64 KiB on Linux) blocked on its own write until the timeout killed it and lost its
output; now a verbose build or test run completes normally and the memory used is
bounded however much it prints.

`task run` exits `0` only on `completed` with exit code `0`.

## What DS04 still does not do

- no durable queue, lease, or execution journal (DS05)
- no AI provider (DS06)
- no network isolation beyond the scrubbed env, no cgroup/namespace
  sandbox yet - the workspace is a directory boundary, not a container
- it never deploys, and `allow_deploy` in the policy stays `False` by
  default the DS01 way

## Isolation, arguments and the life of a run

The scrubbed environment keeps secrets out of the *environment* of a task. To keep the files of the
service user (ssh keys, git credentials, the token file of the API) out of reach as well, the command
is wrapped in an operating-system sandbox when the host has one (`sandbox` in the task policy):

- **bubblewrap**: a private mount namespace with the system read-only, no home, an empty `/tmp`, the
  workspace as the only writable place, a new session and no network (`--unshare-all`) unless
  `sandbox_network` is `true`.
- **systemd-run**: a transient unit with `ProtectHome=yes`, `ProtectSystem=strict`, `PrivateTmp`,
  `PrivateDevices`, `NoNewPrivileges`, `PrivateNetwork` (unless the network is opened) and only the
  workspace writable; it needs a systemd that lets the service user start units.
- **none**: no isolation. `auto` falls back to it, `task run` says so on stderr, and
  `sandbox_required: true` refuses to run instead.

The result of a run says which one was used (`sandbox`). The command lines are built by pure functions
and covered by tests, but the kernel enforcing them has to be confirmed on the real host: this
repository's tests never ran a task inside bubblewrap or a systemd unit.

`allowed_commands` only names the program. `allowed_arguments` (optional, per command, `fnmatch`
patterns) lists what it may be given, and these rules always apply: no absolute, home or `..` path
(also in `--option=value`), no NUL byte, and none of the options that make a well-known tool run
code or read configuration the recipe did not declare (`pytest -p/-c/-o/--rootdir/--confcutdir`,
`python -c`, `bash -c`, `node -e`, ...) unless the policy lists that exact option.

`task run` also stages `repo@revision` (see `repo_sources`), refuses to start more than
`max_concurrent_tasks` tasks under one workspace base (one lock file per running task, a lock whose
process is gone is taken over), looks a bare script name up in the workspace (`./name` must exist
there) and removes the workspace afterwards according to `workspace_retention`.
