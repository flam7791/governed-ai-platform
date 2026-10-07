# AGENTS.md: governed-ai-platform

Instructions for coding agents (and people) changing this repository. Read this first.

The reference deployment that wires three components into one operable service:
governed-llm-gateway, policy-evidence-mcp and governed-agents, with Compose profiles
(demo, live, sovereign, monitoring, tracing), Kubernetes manifests (Kustomize), an Azure
deployment (Bicep) and an end-to-end smoke test. It holds deployment files and scripts, not a
Python package.

## Commands

The components are cloned side by side (see the README quick start); versions are pinned in
`components.env`.

```bash
ruff check . && ruff format --check .
pytest -q tests                                  # configuration invariants (needs pyyaml)
python scripts/new_env.py --demo                 # random keys and tokens in .env
docker compose --profile demo up -d --build --wait
python scripts/smoke_test.py                     # end-to-end checks; add --tracing with that profile
docker compose --profile demo down -v
```

CI also renders every Kubernetes overlay through `kubeconform`, compiles and lints the Bicep
file, and validates Prometheus rules with `promtool`; see `.github/workflows/ci.yml`.

## Layout

- `compose.yaml`: services and profiles; `config/gateway.*.json`: the gateway per profile
- `deploy/kubernetes/`: base, components and the demo, live and sovereign overlays
- `deploy/azure/`: Container Apps, Key Vault references, managed identity, Azure OpenAI
- `monitoring/`: Prometheus scrape configuration and alert rules
- `scripts/new_env.py`: generates `.env` and secrets; `scripts/smoke_test.py`: the platform's test
- `tests/`: invariants over the configuration files; `docs/runbook.md`: operations

## Invariants: never weaken these

1. **Sovereign has no route out** (design decisions 2): no external model in its gateway
   configuration, every team `local_only`, and no internet egress in its Kubernetes overlay.
   `tests/test_configs.py` and `tests/test_kubernetes.py` check it.
2. **Every model call goes through the gateway**, including the agents' calls and the MCP
   server's embeddings; the indexer's team stays `local_only`.
3. **The MCP server is not published outside the platform network**, and every call carries a
   bearer token mapped to a clearance (decision 7).
4. **Containers are hardened**: non-root, read-only file system, no capabilities, no privilege
   escalation, health checks (decision 4).
5. **Secrets never enter committed files or images** (decision 5); `.env` is generated and
   git-ignored. Azure uses a managed identity, not keys (decision 10).
6. **Component versions are pinned** in `components.env` (decision 3); upgrade them on purpose,
   with the smoke test.
7. **Traces carry no prompt, answer or document text** (decision 8).

## Working rules

- A production incident becomes a check in `scripts/smoke_test.py` or `tests/` before the fix.
- Record every change in `CHANGELOG.md`; a design change goes in `docs/decisions.md`; an
  operating change goes in `docs/runbook.md`.
- The scenarios and documents are fictional. Commits carry no AI co-author trailers.
