<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/INCIDENT_TRANSPORT.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Authenticated incident transport (DS07)

The round trip with HYDRA-UMC-OPS-AGENT over a real protocol object -
never a "write a JSON file and hope" exchange.

## Message

Every `IncidentMessage` carries `message_id`, `from_node`, `to_node`,
`kind` (`incident` / `diagnosis` / `deploy-verification` / `ack`),
`contract_version` (`incident-transport/1`), a `nonce`, a `sent_at`
(unix seconds), a `payload`, and a `mac` - HMAC-SHA256 over the
canonical message (minus the mac) keyed by the sender's shared secret.

## `verify_message(message, registry, policy, state, authenticated_as=, now=)`

`authenticated_as` is the identity the *channel* proved (a TLS client
cert CN, a connection login). Everything else is checked against it:

| Check | Rejection code |
| --- | --- |
| `authenticated_as` not in the registry | `unknown-identity` |
| `message.from_node` != `authenticated_as` | `impersonation` |
| `contract_version` not compatible | `incompatible-version` |
| HMAC mismatch / missing | `bad-signature` |
| `sent_at` more than `replay_window_seconds` from now | `stale` |
| `nonce` already accepted (in `state.seen_nonces`) | `replay` |
| more than `max_messages_per_minute` from this node | `overloaded` |

An accepted message adds its nonce to `state.seen_nonces` and its
timestamp to the per-node rate log.

## `IncidentSession` - the round trip

`submit_incident(incident_id, payload)` signs and sends an `incident`
message and moves to `pending-ack`. `pump()` consumes inbound messages:
an `ack` clears `pending-ack`; a `diagnosis` fills `session.diagnosis`
and moves to `diagnosed`; a `deploy-verification` fills
`session.deploy_verification` and moves to `deploy-verified` (or
`failed` if `verified` is false). The delivery is not done at "incident
sent" - it is done when the post-deploy verification has come back.

`reconcile()` - if the session is still `pending-ack` (a dropped
connection), it re-sends the **same incident** with a **fresh nonce**
(the anti-replay check stays strict). The peer de-dupes on the stable
`payload.incident_id`: it has already handled that incident, so it just
re-acks and does not run the diagnosis a second time. A network blip
loses nothing and double-counts nothing.

## `incident-transport.example.json`

```json
{ "contract_version": "incident-transport/1",
  "replay_window_seconds": 120, "max_messages_per_minute": 60 }
```

The **node registry** (`node id -> HMAC secret`) is operator-held and
**never committed** - keep it outside git, in a secrets store or an
environment-fed file. `incident verify --registry PATH` reads it.

## What DS07 still does not do

- no real network transport (TLS, mTLS, a message bus) - that is a
  deployment choice; DS07 is the protocol and the checks
- it does not run the repair itself - that is DS08
- it never counts a manual file copy as a completed transport
