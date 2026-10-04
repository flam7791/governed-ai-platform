# Deploying on Azure

How this platform maps to Azure services for an organisation that runs on Microsoft, and the
Bicep that deploys it: [`deploy/azure/main.bicep`](../deploy/azure/main.bicep). CI compiles it
and runs the Bicep linter on every change, and `tests/test_azure.py` checks its security
properties; it has not been deployed from this repository (that needs a subscription).

## Deploy

Prerequisites: a resource group, an Azure OpenAI account in it with three deployments (a small
chat model, a larger one, an embedding model), and the Azure CLI signed in.

```bash
python scripts/new_env.py --azure                       # deploy/azure/secrets.env (git-ignored)
set -a; . deploy/azure/secrets.env; set +a
export AZURE_OPENAI_ENDPOINT=https://<account>.openai.azure.com AZURE_OPENAI_ACCOUNT=<account>
az deployment group create -g <resource group> -f deploy/azure/main.bicep \
    -p deploy/azure/main.bicepparam
```

What it creates:

| Resource | Purpose |
|---|---|
| Log Analytics workspace | Container logs (one JSON line per request from the gateway) |
| Virtual network, Container Apps environment | The services, on a delegated subnet |
| User-assigned managed identity | Reads Key Vault secrets; calls Azure OpenAI (`Cognitive Services OpenAI User`): no model key exists |
| Key Vault (RBAC, purge protection) | Every key and token, written by the deployment from parameters read from the environment |
| Storage account, two file shares | The gateway's ledger and the agents' runs (SQLite, one replica each) |
| `gateway` | Internal ingress only; `config/gateway.azure.json` with the account's endpoint and deployments filled in |
| `evidence-mcp` | Internal ingress only; the agents service's token, clearance internal |
| `agents` | External ingress for the approvals page; `approvalsAllowedCidrs` limits who reaches it |
| `evidence-m365` (optional) | `enableCopilotStudio=true`: the evidence server with external ingress and Entra ID tokens, for a Copilot Studio agent (see policy-evidence-mcp's `integrations/copilot-studio`) |

In `gateway.azure.json` the Azure OpenAI models are marked internal (`"external": false`):
the account is in the organisation's tenant and region, so the document indexer (`local_only`)
may use its embedding model. If your policy treats Azure OpenAI as external, set them to `true`
and the indexer will be refused, as it should be.

Before production: private endpoints for Key Vault, storage and Azure OpenAI; Entra ID
authentication (Easy Auth) in front of the approvals page; PostgreSQL instead of SQLite for more
than one replica; an OpenTelemetry Collector to Application Insights (`otlpEndpoint`).

## Mapping

| Here (Compose) | On Azure | Why |
|---|---|---|
| Containers on one Docker network | **Azure Container Apps**, one environment with a virtual network | Managed containers, scale to zero, internal ingress |
| Published ports 8080 / 8090 | Container Apps **ingress**: gateway internal only, agents service behind the organisation's front door with single sign-on | Nothing public by default |
| MCP server, unpublished, bearer token | Container App with **internal ingress only**, callers authenticated with **Entra ID** tokens (`--auth entra`, clearance from app roles) | Defence in depth: the network and the identity both decide |
| `.env` secrets | **Azure Key Vault**, referenced by the Container Apps as secrets | Rotation and access audit |
| `ANTHROPIC_API_KEY` / Azure keys | **Managed identity** for Azure OpenAI (`"auth": "entra_id"` in the gateway): no model key exists | Nothing to leak or rotate |
| Ollama for local models | **Azure OpenAI** deployments in the organisation's tenant and region, or open-weight models on Azure Machine Learning or AKS with GPUs | Data stays in the tenant; open-weight where sovereignty requires |
| Named volumes, SQLite | **Azure Database for PostgreSQL** (a small change in the store and ledger), Azure Files for the evidence index | Backups, several replicas |
| Prometheus + alert rules | **Azure Monitor managed Prometheus** with the same rules, and Azure Managed Grafana | No monitoring servers to run |
| JSON logs on stdout | **Log Analytics** workspace | Search, retention, alerts on log content |
| Tokens for people | **Microsoft Entra ID** single sign-on, with roles (requester, approver, admin) as app roles or groups | Identity from the directory; four eyes on real identities |
| GitHub Actions CI | GitHub Actions or Azure DevOps pushing images to **Azure Container Registry**, deploying with Bicep or Terraform | Repeatable environments (dev, test, prod) |

## Network

- One virtual network; Container Apps environment inside it.
- **Private endpoints** for Azure OpenAI, Key Vault, PostgreSQL and the container registry, so
  model traffic and data never cross the public internet.
- Outbound traffic from the gateway restricted to the model providers it is configured for.

## What changes in the code

- Store and ledger on PostgreSQL instead of SQLite (the SQL is standard).
- People's identity from Entra ID tokens instead of static tokens (the roles and four-eyes rule
  stay as they are).
- Nothing else: providers, policies, metrics and logs are already configuration and standard
  formats.

## Cost drivers to estimate before building

Model usage (visible per team in the gateway ledger from day one), Container Apps compute,
PostgreSQL, Log Analytics ingestion, and GPU capacity if open-weight models are hosted.
