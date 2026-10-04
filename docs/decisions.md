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

## 7. The MCP server authenticates its callers, even inside the platform

The private network already keeps outsiders away from the MCP server, but a network rule says
where a call comes from, not who makes it. The agents service therefore presents its own token,
and the server applies the clearance attached to that identity. A second client (another agent
team, an analyst's assistant) gets its own token and clearance, without touching the network.

## 8. One trace per agent run, with no content

Logs say what each service did; a trace says where the time and the decisions went across all
three. Spans carry identifiers, model names, tokens, costs and policy verdicts, and never prompts,
answers or documents, so traces can go to a shared backend without becoming a copy of the data.

## 9. Kubernetes manifests with Kustomize, not a Helm chart

Three modes are three overlays over one base, plus small components (tracing, egress, model
server). Kustomize keeps the manifests plain YAML that a reviewer can read and that `kubectl`
applies without another tool; a chart's templating would add indirection for no extra choice.

## 10. Azure: Container Apps and a managed identity, not keys

The Azure deployment keeps the shape of the other two (three services, the MCP server and the
gateway internal only) and changes how secrets and models are reached: one user-assigned
identity reads Key Vault and calls Azure OpenAI, so there is no model key to store, leak or
rotate. Container Apps rather than AKS, because three services at one replica each do not need a
cluster to operate; the Kubernetes manifests cover organisations that already run one.
