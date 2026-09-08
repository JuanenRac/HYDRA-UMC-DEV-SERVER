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

**Not yet applicable** - DS02 (remote host provisioning), DS04 (workspace/
task runner), DS05 (durable queue), DS06 (AI provider) and DS07-DS10 do
not exist yet in this delivery. There is no remote access, no task
execution, no AI-provider network call, and no durable queue anywhere in
this repository yet, so there is nothing there to have a vulnerability in.

Please report responsibly:

1. **Email**: Send a detailed report to `electrohobby3d@gmail.com`.
2. **Impact**: Describe the attack surface affected and a realistic
   scenario (this delivery has no network-facing service and no task
   runner of its own - the CLI only runs when explicitly invoked, so a
   realistic scenario today involves what a maliciously crafted
   configuration document could make `config validate`/`inventory scan`
   do, not a remote attacker directly reaching this tool).
3. **Response**: Initial acknowledgment within 48 hours.

We follow a coordinated disclosure policy.
