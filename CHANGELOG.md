# Changelog

## Unreleased

- `AGENTS.md` (commands, layout, invariants) for coding agents; `CLAUDE.md` imports it.

## 0.5.0 (2026-10)

- Azure: `deploy/azure/main.bicep` (Container Apps in a virtual network, Key Vault references
  through a user-assigned managed identity, Azure OpenAI with no key, Azure Files for SQLite,
  optional Copilot Studio front door), `main.bicepparam` reading secrets from the environment,
  `new_env.py --azure`, `config/gateway.azure.json`; compiled, linted and tested in CI.
- Components: policy-evidence-mcp 0.3.1 (Microsoft 365 Copilot through Copilot Studio; hosts
  without a port behind TLS), governed-agents 0.3.1 (tool work nested under its span).
- README: screenshots of the approvals page, the audit trail and one trace across the services.

## 0.4.0 (2026-10)

- Components 0.3.0: MCP access management, OpenTelemetry tracing, SharePoint through Microsoft
  Graph (evidence server), MCP bearer tokens (agents).
- The MCP server requires a token; the agents service has its own, mapped to the clearance
  "internal". `new_env.py` generates both sides (the server holds only the hash).
- Tracing: `tracing` compose profile with Jaeger, `new_env.py --tracing`; the smoke test checks
  that a run is one trace across the three services, with no request text on any span.
- Kubernetes: Kustomize base, components and overlays (demo, live, sovereign); restricted Pod
  Security Standard, default-deny network policies, secrets by reference, optional tracing.
  CI renders and schema-validates every overlay; a workflow deploys the demo to kind and runs
  the smoke test there. docs/kubernetes.md, with the AKS mapping.
- The demonstration model server's image is published to GitHub Container Registry on a tag.

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
