# Running on Kubernetes

The same three services as the Compose stack, as Kubernetes manifests in
[`deploy/kubernetes`](../deploy/kubernetes): a [Kustomize](https://kustomize.io) base, optional
components, and one overlay per mode. Any conformant cluster works: AKS, a managed cluster
elsewhere, or a local one (kind, k3d, Docker Desktop).

```
deploy/kubernetes/
├── base/                     namespace, gateway, evidence-mcp, agents, network policies
├── components/
│   ├── mock-llm/             the demonstration model server
│   ├── ollama/               open-weight models inside the cluster
│   ├── model-pull/           lets Ollama download models (HTTPS out, nothing else)
│   ├── internet-egress/      HTTPS out for the gateway and the MCP server (live mode)
│   └── tracing/              Jaeger, and the services sending spans to it
└── overlays/
    ├── demo/                 mock-llm; nothing leaves the cluster
    ├── live/                 Claude + Ollama; ollama, model-pull, internet-egress
    └── sovereign/            Ollama only; no route out of the namespace
```

## Deploy

```bash
python scripts/new_env.py --demo --kubernetes      # secrets for the overlay (git-ignored)
kubectl apply -k deploy/kubernetes/overlays/demo
kubectl -n governed-ai wait --for=condition=Available deployment --all --timeout=600s

kubectl -n governed-ai port-forward svc/agents 8090:8090     # the approvals page
```

`new_env.py --kubernetes` prints the sign-in tokens. Images come from GitHub Container Registry
(`ghcr.io/flam7791/<component>:<version>`), published by each component's release workflow with
an SBOM and build provenance. To use your own registry, add an `images:` entry to the overlay.

The [Kubernetes end-to-end workflow](../.github/workflows/kubernetes.yml) deploys the demo
overlay to a kind cluster, runs the smoke test through port-forwards and checks that a pod
without the agents' label cannot reach the MCP server. CI renders every overlay and validates
it against the Kubernetes API schemas on every push; [`tests/test_kubernetes.py`](../tests/test_kubernetes.py)
checks the hardening and the network rules.

## What the manifests enforce

| Concern | How |
|---|---|
| Pods cannot run privileged | The namespace enforces the **restricted Pod Security Standard**: non-root, no privilege escalation, no capabilities, seccomp `RuntimeDefault`. Every container also has a read-only root file system. |
| No Kubernetes API access | Each service has its own service account with `automountServiceAccountToken: false`; none of them calls the API. |
| Network | **Default deny** in and out, then only: agents → gateway and MCP server; MCP server → gateway; gateway → model servers; DNS. The MCP server accepts connections from the agents service only, and every call still needs a bearer token. |
| Nothing exposed | Every Service is `ClusterIP`. People reach the approvals page through your ingress controller (the agents policy admits the `ingress-nginx` namespace; change the label for another controller) or a port-forward. |
| Secrets | Keys and tokens come from Secrets by reference (`secretKeyRef`), one key per variable, never literal values. The MCP server receives only the hash of the agents service's token. |
| Sovereign | The sovereign overlay has no egress rule to any address outside the cluster; a test fails if someone adds one. |
| Resources | Requests and limits on every container, so a runaway service cannot starve the others. |

Network policies need a network plugin that enforces them: Azure CNI with Azure Network Policy
Manager, Calico or Cilium on AKS; Calico or Cilium elsewhere; kindnet in kind.

## Models

The live and sovereign overlays run Ollama with models on a 40 GiB volume. Pull them once:

```bash
kubectl -n governed-ai exec deploy/ollama -- ollama pull llama3.1:8b
kubectl -n governed-ai exec deploy/ollama -- ollama pull nomic-embed-text
kubectl -n governed-ai rollout restart deployment/evidence-mcp    # re-index with vectors
```

In the sovereign overlay the model server has no route out. Add `../../components/model-pull`
to the overlay's components while pulling, then remove it and apply again; or load the volume
from an internal mirror. For a GPU, add `nvidia.com/gpu: 1` to the Ollama container's limits and a node
selector for the GPU node pool; for volume, replace Ollama with vLLM (a change of image and URL).

## Tracing

Add `../../components/tracing` to an overlay's `components`. Jaeger runs in the namespace, the
three services send spans to it, and an agent run becomes one trace: the run, each agent step,
each model call through the gateway and each MCP tool call, with policy decisions and costs but
no prompts or document text. `kubectl -n governed-ai port-forward svc/jaeger 16686` opens the UI.
For Azure Monitor or Grafana Tempo, point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OpenTelemetry
Collector instead.

## On AKS

| Here | On AKS |
|---|---|
| Secrets generated from files | **Azure Key Vault** through the Secrets Store CSI driver, or External Secrets; the `secretKeyRef` names stay the same |
| `ANTHROPIC_API_KEY` | For Azure OpenAI, **workload identity** for the gateway's service account (`"auth": "entra_id"` in the gateway's configuration): no model key exists |
| ghcr.io images | **Azure Container Registry**, attached to the cluster; an `images:` override in the overlay |
| `ReadWriteOnce` volumes, SQLite | Azure Disk for a pilot; Azure Database for PostgreSQL for several replicas (a change in the store and ledger) |
| Port-forward | Application Gateway for Containers or NGINX ingress, with Entra ID single sign-on in front of the approvals page |
| Jaeger | Azure Monitor (Application Insights) through the OpenTelemetry Collector |
| Ollama | Azure OpenAI in the organisation's tenant, or a GPU node pool for open-weight models |

## Limits

- One replica per service: SQLite holds the gateway's ledger and the agents' runs, and the MCP
  server keeps sessions in memory. High availability needs PostgreSQL and a stateless MCP
  transport (or session affinity).
- The kind workflow proves the demo overlay; the live and sovereign overlays are validated
  (rendered, schema-checked, tested for their network rules) but need a cluster with models.
