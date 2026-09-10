<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/AI_PROVIDER.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Interchangeable AI provider (DS06)

DS06 defines a provider seam and the safety contract around it. Only the
**deterministic fake** provider ships. Which real provider to use
(Claude, ChatGPT, a local model, ...) and its authorization, cost and
terms are a **user decision** - `ProviderConfig.kind` accepts `"fake"`
and rejects everything else with a message that says so.

## The seam

```python
class AIProvider(Protocol):
    def complete(self, prompt: str, *, timeout_seconds: int) -> RawCompletion: ...
```

`RawCompletion` is `text` + `tokens` + `cost_usd`. A provider signals an
adverse condition by raising `ProviderTimeout`, `ProviderQuotaExhausted`
or `ProviderMalformed` - never by returning a broken object.

`FakeProvider(scenario=...)` is fully deterministic. `scenario="ok"`
returns a stable suggestion derived from a hash of the prompt; `timeout`,
`quota`, `malformed` and `injection` exercise each path the contract has
to handle.

## The contract - `run_provider_step(config, provider, prompt)`

| Situation | Outcome | Notes |
| --- | --- | --- |
| provider raises `ProviderTimeout` | `timed-out` | bounded; no exception escapes |
| provider raises `ProviderQuotaExhausted` | `budget-exhausted` | stop |
| provider raises `ProviderMalformed`, or returns empty text | `rejected` | not a partial success |
| a `ProviderBudget` limit (calls / tokens / cost) is already reached | `budget-exhausted` | **the provider is not called** |
| a normal answer | `suggested` | `suggested_text` carries it verbatim |

For **every** outcome the result reports `grants_no_permissions = True`
and `triggers_no_deploy = True`. The suggestion is **data a human
reads** - `run_provider_step` never parses it for instructions and wires
it to nothing (not `task run`, not `queue`, not any deploy path). A
suggestion that contains instruction-shaped text ("ignore previous
instructions", "deploy now", "grant me root", "curl ... | sh") is copied
in unchanged and `injection_flagged` is set, so a reviewer sees it - it
still changes no permission and starts no action.

## `ai-provider.example.json`

```json
{ "kind": "fake", "timeout_seconds": 30,
  "budget": { "max_calls": 4, "max_tokens": 20000, "max_cost_usd": 1.0 } }
```

## CLI

```
provider suggest --config ai-provider.example.json --prompt-file prompt.txt [--scenario ok|timeout|malformed|quota|injection]
```

Prints the `ProviderResult` JSON. Exits `0` only on `suggested`.

## What DS06 still does not do

- no real provider (a user decision - kind, key, terms, cost, ARM64
  support, editor-session vs automated-path separation)
- no worker loop that feeds a queued task's context to `provider
  suggest` and then to `task run` - that glue is DS07/DS08
- consumption is measured against the budget; a real per-request cost
  meter comes with the real provider
