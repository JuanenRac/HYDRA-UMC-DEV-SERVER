# Plugins

A plugin adds named items to the development server: **checks**, **reports**
and **generators**. It is a directory with two files, `plugin.json` and one
Python module. By default every call runs in its own Python process (see
"Isolation" below), so a plugin sees nothing of the API process; enable only
what you have read all the same.

## Manifest (`plugin.json`)

```json
{"name": "host-report", "version": "0.1.0", "api_version": 1,
 "entry": "plugin.py", "provides": ["reports"]}
```

| Field | Rule |
|---|---|
| `name` | 1-40 characters: lowercase letters, digits, hyphens. Unique among the discovered plugins. |
| `version` | `MAJOR.MINOR.PATCH`. |
| `api_version` | Must be `1`. |
| `entry` | A plain `.py` file name inside the plugin directory. |
| `provides` | Optional. A non-empty list of distinct kinds from `checks`, `reports`, `generators`. Defaults to `["checks"]`, so plugins written before the other kinds existed need no change. |

An unknown field, a bad value or a missing entry file makes the directory a
*problem* (reported by `plugin list` and `GET /v1/plugins`); the other plugins
are not affected.

## The three kinds

The module defines `register(registry)`. It may call only the methods of the
kinds its manifest declares; calling another one fails the whole plugin.

| Kind | Registered with | Function | Returns |
|---|---|---|---|
| check | `registry.add_check(name, fn)` | `fn()` | a JSON dict |
| report | `registry.add_report(name, fn)` | `fn()` | a JSON dict that describes a state, to be read |
| generator | `registry.add_generator(name, fn)` | `fn(params)` with a dict | `{"filename": "...", "content": "..."}` |

Item names follow the same rule as plugin names and are unique within a kind
(a check and a report may share a name). A report must not change anything; it
only describes. A generator returns one text file to the caller: the server
never writes it to disk, and `filename` must be a plain name (letters, digits,
`.`, `_`, `-`, at most 80 characters, no path).

## Lifecycle

1. **discovered**: `plugin.json` was read and validated; nothing was imported.
   The SHA-256 over the manifest and the module (in that order) is shown.
2. **enabled**: the operator names the approved SHA-256. If the files no longer
   match, the plugin is `failed`. Otherwise the module is loaded and
   `register` runs. Enabling is all or nothing: if `register` raises, or adds a
   kind the manifest does not declare, the plugin ends `failed` with nothing
   registered.
3. **disabled**: every item is dropped. Enabling again needs the digest again.
4. **failed**: the reason is in `detail`. A failed or disabled plugin runs
   nothing.

Rescanning keeps the state of a plugin whose files did not change and resets
one whose files did.

## Sandbox limits

These apply to checks, reports and generators alike.

- Each call runs in its own worker thread with a timeout of 10 seconds. One
  that does not finish is reported as an error (the thread cannot be killed:
  a plugin that never returns keeps its thread, which is one more reason to
  enable only code you trust).
- An exception, including `SystemExit`, is an error entry, never a crash and
  never a change of the plugin's state.
- The answer must be JSON, of the right shape, and at most 256 KiB
  (`MAX_RESULT_BYTES`). Anything else is an error entry.
- Generator parameters must be a JSON object of at most 4096 bytes; the plugin
  receives a copy.
- The server hands the plugin no credential, route or file handle. This is a
  limit on what the server offers, not an isolation from the process: the
  plugin can import anything Python can.

An error entry looks like `{"status": "error", "error": "..."}`; a good answer
is `{"status": "ok", "result": ...}`.

## CLI

```
plugin list --plugins-root DIR
plugin run --plugins-root DIR --plugin NAME --sha256 HEX \
           --kind check|report|generator --item NAME [--params JSON]
```

`plugin run` enables the plugin for that one process against the digest you
name, runs the item and prints the answer. It exits `1` when the digest does
not match, the item does not exist, the parameters are not a JSON object, or
the item answers with an error.

## HTTP

All routes need `Authorization: Bearer <token>`, like the rest of the API.

| Route | Purpose |
|---|---|
| `GET /v1/plugins` | every plugin with its `provides` and the `checks`, `reports` and `generators` it registered |
| `POST /v1/plugins/<name>/reports/<report>` | run one report |
| `POST /v1/plugins/<name>/generators/<generator>` | run one generator; optional body `{"params": {...}}` |

A plugin that is not enabled, or an item it does not have, answers `409`; an
unknown plugin answers `404`; a body over 4096 bytes answers `413`. An item
that fails answers `200` with an error entry, as checks do.

## Examples

`examples/plugins/host-report` provides one report (`host-summary`: system,
Python version, CPU count and disk space) and `examples/plugins/readme-generator`
provides one generator (`readme-skeleton`: a README skeleton from a name and a
summary). Copy a directory next to your plugins, change it, and approve the new
digest that `plugin list` shows.

## Isolation

`PluginRegistry(isolation="process")` is the default, and what `serve` and `plugin run` use
(`HYDRA_DEV_SERVER_PLUGIN_ISOLATION=thread` brings back the old behaviour for a plugin that
needs to keep state between calls).

- **process** (default): enabling and every call start a separate Python process (`python -I`),
  in an empty temporary directory that is also its `HOME`, with a scrubbed environment (no
  token, no key, no variable of the API), limits on its CPU time and on the size of the files it
  writes, and the whole process group killed when the call overruns its timeout or finishes. The
  module is handed to it as the bytes that were approved, not as a path, so it cannot import a
  file next to it and a file changed after the approval is never run. What it returns follows a
  marker, so anything it prints cannot be taken for the answer. At most four calls run at once.
  A plugin keeps no state from one call to the next, and the process has the permissions of the
  service user: it is isolation from the API process, not an operating-system sandbox.
- **thread**: the module runs in the API process (trusted code), still from the approved bytes
  and not from the file read a second time. A call that overruns cannot be cancelled; such calls
  are counted and no new call starts once eight are still running.

Rescanning, enabling and disabling are serialised, so parallel requests cannot corrupt the
registry.
