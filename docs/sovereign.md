# Sovereign mode: open-weight models only

For restricted information, air-gapped networks, or any team that may not send text to an
external provider. The whole platform (gateway, MCP evidence server, agents) runs on open-weight
models on the organisation's own hardware, and nothing can leave by configuration error,
because no external model is defined.

```bash
python scripts/new_env.py --sovereign
docker compose --profile sovereign up -d --build --wait
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull qwen2.5:7b
docker compose exec ollama ollama pull qwen2.5:14b
docker compose exec ollama ollama pull nomic-embed-text
docker compose restart evidence-mcp      # re-index with local vectors
```

## What changes

| | `local` profile (`gateway.json`) | `sovereign` profile (`gateway.sovereign.json`) |
|---|---|---|
| Fast and strong tiers | Claude (external) | Open-weight models through Ollama |
| Local tier | Llama 3.2 3B | Llama 3.2 3B |
| Embeddings | nomic-embed-text, local | nomic-embed-text, local |
| Team data policies | `mask_pii`; indexer `local_only` | every team `local_only` |
| External models defined | yes | **none** |
| API key needed | Anthropic | none |
| Cost per request | per token | zero API cost; hardware and operation |

Two independent controls hold the promise: the configuration defines no external model, and
every team is `local_only`, so even a model added later with `external: true` would be refused
for these teams. `tests/test_configs.py` fails the build if either is edited away.

## Sizing

The default models suit a workstation with a recent GPU or a patient CPU: Llama 3.2 3B and
Qwen 2.5 7B run on a laptop, Qwen 2.5 14B wants a GPU with about 12 GB or more. Change the model
names in `config/gateway.sovereign.json` to what your hardware runs, then re-run the agents'
and the gateway's evaluations: quality and latency on your own cases decide, not the model card.

## Serving at volume (vLLM)

Ollama is the simplest model server; for many users, serve the same open-weight models with
[vLLM](https://docs.vllm.ai) on GPU servers, which exposes the same OpenAI-compatible API.
Only `base_url` (and the model names) in `config/gateway.sovereign.json` change, for example
`http://vllm:8000/v1`. No application changes.

## Licences

Open-weight is not open source: Llama models use Meta's community licence, Qwen 2.5 models use
Apache 2.0 for most sizes (check each size), nomic-embed-text uses Apache 2.0. Confirm the
licence of every model before production use.
