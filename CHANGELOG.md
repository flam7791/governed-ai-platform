# Changelog

## 0.3.0 (2026-10)

- Sovereign mode: `config/gateway.sovereign.json` runs every tier and the embeddings on
  open-weight models through Ollama, with no external model defined and every team
  `local_only`; `new_env.py --sovereign`; `sovereign` compose profile; docs/sovereign.md.
- Configuration invariant tests (`tests/`), run in CI.
- Design decisions recorded in docs/decisions.md.

## 0.2.0 (2026-09)

- Compose stack of gateway, MCP evidence server and agents service; hardened containers;
  Prometheus monitoring with alert rules; pinned component versions; runbook, lifecycle and
  Azure design; end-to-end smoke test in CI.
