# Deploying on Azure: a design

How this platform maps to Azure services for an organisation that runs on Microsoft. This is a
design to discuss, not a tested deployment: nothing here has been deployed from this repository.

## Mapping

| Here (Compose) | On Azure | Why |
|---|---|---|
| Containers on one Docker network | **Azure Container Apps**, one environment with a virtual network | Managed containers, scale to zero, internal ingress |
| Published ports 8080 / 8090 | Container Apps **ingress**: gateway internal only, agents service behind the organisation's front door with single sign-on | Nothing public by default |
| MCP server, unpublished | Container App with **internal ingress only** | Same rule as here: no authentication of its own, so not reachable from outside |
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
