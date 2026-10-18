# Security Policy 🔒 (HYDRA-UMC-DEV-SERVER)

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.x.x   | ✅ Yes    |

## Reporting a Vulnerability

**CRITICAL: Do not report vulnerabilities through public GitHub issues.**

This project is designed, from its very first delivery, around a
non-negotiable limit: no task may deploy anything unless a real
configuration document explicitly grants it, and no secret (an SSH key, a
Wi-Fi credential, an API token) is ever meant to live inside this
repository's own tracked files. If you discover a vulnerability affecting:

- **`TaskPolicy.allow_deploy`'s own default-deny guarantee** - any way to
  produce a `TaskPolicy` with `allow_deploy=True` from a document that
  does not literally set the JSON boolean `true`, or any way a missing/
  malformed/non-boolean value could be interpreted as granting it. This
  is the single most safety-critical invariant in this delivery: every
  later delivery that actually runs a task (DS04 onward) depends on this
  gate already being honest.
- **What `scan_project_manifests()` trusts** - a way to make it read a
  file outside the intended workspace root, or to make a malformed
  manifest crash discovery instead of being reported as a real, contained
  `ManifestScanIssue`.
- **What `load_json_document()`/the `config validate` CLI command
  accepts** - a way to make it execute, evaluate, or otherwise treat
  configuration content as anything other than inert JSON data (this
  module never uses `eval`/`exec`/`pickle` on untrusted input - a
  vulnerability report showing a path that does would be taken very
  seriously).

Also in scope, because they exist and run:

- **The task runner** (`runner.py`, `workspace.py`, `recipe.py`) - a way to
  run a command outside the allow-listed ones, to read or write outside the
  task workspace, to inherit a secret from the service user's environment,
  or to leave a process alive after a task ends or is cancelled. The runner
  is NOT a sandbox: a task has the file-system reach of the service user, so
  run it as a dedicated account.
- **The durable queue** (`durable_queue.py`) - a result accepted from a
  worker that no longer holds the lease, a task leased twice, or a lost journal
  entry.
- **The local API and plugins** (`api.py`, `plugins.py`) - the API listens on
  loopback only and needs a bearer token for everything except the health
  check; a plugin is trusted code that runs in the API's own process once an
  operator approves its SHA-256. Report any way to reach a route without the
  token, to bind beyond loopback, or to load a plugin that was not approved.
- **The remote-station plan and the migration** (`remote_station.py`,
  `provision.py`, `migration.py`) - text that reaches a generated systemd unit,
  an address that opens an editor to the whole network, or a private file
  classified as publishable.
- **The incident transport and the repair cycle** (`incident_transport.py`,
  `repair_cycle.py`) - a forged, replayed or misaddressed message accepted as
  genuine, or a repair step that can be skipped or replayed.
- **Backup and restore** (`operations.py`) - a path in a manifest that writes
  outside the restore root.

Please report responsibly:

1. **Email**: Send a detailed report to `electrohobby3d@gmail.com`.
2. **Impact**: Describe the attack surface affected and a realistic
   scenario (the only network-facing part is the local API on loopback
   with a bearer token, and a plugin runs in its process; most other attack
   surface is a crafted configuration, recipe, manifest or plugin).
3. **Response**: Initial acknowledgment within 48 hours.

We follow a coordinated disclosure policy.
