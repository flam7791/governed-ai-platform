# Runbook

Everyday operations of the platform. Commands run in the repository folder.

## Start, stop, status

| Task | Command |
|---|---|
| Start (demonstration model) | `docker compose --profile demo up -d --build --wait` |
| Start (live, local models) | `docker compose --profile local up -d --build --wait` |
| Add monitoring | add `--profile monitoring` to the start command |
| Status and health | `docker compose ps` |
| Logs of one service | `docker compose logs -f gateway` |
| Stop, keep data | `docker compose down` |
| Stop and delete all data | `docker compose down -v` (runs, audit trail, ledger: gone) |
| Check everything works | `python scripts/smoke_test.py` |

## Keys and tokens

- **Create or rotate everything:** `python scripts/new_env.py --force`, then
  `docker compose up -d` so services pick up the new values. Old keys stop working at once.
- **Team keys** (`LLMGW_KEY_*`) identify applications at the gateway. One key per team; the
  gateway stores only a hash.
- **People** (`GOVAGENTS_API_TOKENS`, `name:role:token`): `requester` starts runs, `approver`
  decides, `admin` does both and can halt runs. Add a person by adding an entry and restarting
  the agents service.
- **MCP server** (`EVIDENCE_MCP_TOKEN_AGENTS`): the agents service's token for the evidence
  server, which holds only its hash in `secrets/evidence-mcp-tokens.json` (clearance
  `internal`). Rotated with everything else by `new_env.py --force`. Another client gets its own
  entry, created with `evidence-mcp token create --name <client> --clearance <level>`.
- **Provider keys** (`ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY`) exist only in `.env`. On Azure,
  use managed identity instead and there is no model key at all.

## Approvals

- The approvals page is at http://127.0.0.1:8090. Pending actions show the tool, the agent,
  why a person is needed, and the exact arguments; the approver's name is recorded.
- Whoever requested a run cannot approve its actions. Rejections need a reason, which the
  agent reads and must deal with.
- Alert `ApprovalWaitingTooLong` fires after four hours: remind the approvers, or reject.

## Kill switches

- **One run:** as an admin, `POST /api/runs/{id}/halt` (or `govagents halt RUN_ID` inside the
  container). Pending approvals are cancelled; the run cannot resume.
- **All runs:** `docker compose exec agents touch /data/HALT`. Every run stops before its next
  model call. Delete the file to resume new work.
- **All model traffic:** `docker compose stop gateway`. Agents fail cleanly and the reason is
  in each run's audit trail.

## Budgets and spend

- `docker compose exec gateway llmgw report --config /config/gateway.json` prints this
  month's usage and cost by team and model (the basis for chargeback).
- Alert `TeamBudgetAbove80Percent` fires at 80%. At 100%, the team is blocked or degraded to a
  cheaper model, as its configuration says.
- Budgets and data policies live in `config/gateway.json`; change, then
  `docker compose restart gateway`.

## Backups

State is in three named volumes: `gateway-data` (ledger), `agents-data` (runs, audit trail,
approvals, outbox) and `evidence-index` (rebuilt at every start). Back up the first two, for
example:

```bash
docker run --rm -v governed-ai-platform_agents-data:/data -v "$PWD":/backup \
  python:3.12-slim tar czf /backup/agents-data.tgz -C /data .
```

The audit trail is evidence: keep backups for as long as the organisation keeps records of the
decisions the agents supported.

## Incidents

| Symptom | First checks |
|---|---|
| Runs fail with "HTTP 502" | Gateway logs: which model failed and why (`provider_error`); provider status; keys |
| Runs fail with "HTTP 402" | The team's budget is exhausted (`/v1/usage` with the team key) |
| Search is keyword-only | `evidence-mcp` logs: "embeddings unavailable"; is the embedding model pulled? |
| Many refused actions | Trace of recent runs: a changed prompt, a new tool, or injected content in documents |
| A suspected data leak | Halt all runs (HALT file), keep the volumes, read the audit trail and the gateway ledger |
