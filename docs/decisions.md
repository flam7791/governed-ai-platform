# Design decisions

## 1. One compose file, several profiles

Demo (a scripted stand-in model, no keys), local (Claude plus local models), sovereign
(open-weight only) and monitoring are profiles of the same file, so the services, hardening and
wiring are identical in every mode. Only the gateway configuration and the model server change.

## 2. Sovereign is configuration, not code

The applications never know which mode they run in: they ask the gateway for a tier. Sovereign
mode is a gateway configuration with no external model and every team `local_only`. Tests check
both properties on every change.

## 3. Pinned component versions

`components.env` names the exact tag of each component. CI checks out those tags, builds and runs
the stack, so a platform version is a combination that passed the end-to-end test together.

## 4. Hardened by default

Read-only containers, no Linux capabilities, `no-new-privileges`, non-root users, ports bound
to 127.0.0.1, and the MCP server reachable only on the platform network because it has no
authentication of its own.

## 5. Secrets outside files that are committed

Keys and tokens are generated into a git-ignored `.env` by `scripts/new_env.py`, and monitoring
tokens reach Prometheus as Compose secrets. In production they come from a secret store (see
`docs/azure.md`).

## 6. The end-to-end test is the platform's test

Components carry their own unit tests and evaluations. The platform's job is the wiring, so its
gate is the smoke test that starts everything and walks an agent run through a human approval,
plus the configuration invariants in `tests/`.
