"""A stand-in model server for demos and CI: the whole platform runs with no API key and no GPU.

It speaks the OpenAI format (POST /v1/chat/completions and /v1/embeddings), like Ollama or a
cloud provider behind the gateway. It is not a language model:

- For the agents of the briefing desk, it plays a fixed script, one JSON action per turn, reading
  the case file and tool results it is sent. The script exercises every control: an MCP search,
  a refused publication, an email that needs a person's approval.
- For embeddings, it returns deterministic word-hashing vectors.
- For anything else, it answers with a short fixed text.

Standard library only, so the image needs nothing but Python.
"""

import hashlib
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIMENSIONS = 256


def case_file(messages: list[dict]) -> dict:
    first = next(m["content"] for m in messages if m["role"] == "user")
    text = first.split("Case file:\n", 1)[-1].rsplit("\n\nDo your part", 1)[0]
    try:
        return json.loads(text)
    except ValueError:
        return {}


def last_result(messages: list[dict], tool: str) -> dict | None:
    """The most recent successful result of a tool, as sent back by the agent runtime."""
    for m in reversed(messages):
        if m["role"] == "user" and m["content"].startswith(f"Result of {tool}:\n"):
            try:
                return json.loads(m["content"].split("\n", 1)[1])
            except ValueError:
                return None
    return None


def tool(name: str, **arguments) -> dict:
    return {"action": "tool", "tool": name, "arguments": arguments}


def finish(**output) -> dict:
    return {"action": "finish", "output": output}


def researcher_finish(messages):
    found = last_result(messages, "search_documents") or {}
    results = found.get("results") or []
    evidence = [{"point": r["text"][:160], "citation": r["citation"]} for r in results[:2]]
    if not evidence:  # the MCP server was not reachable: fall back to the local notes
        notes = last_result(messages, "search_notes") or []
        evidence = [
            {"point": n.get("text", "")[:160], "citation": n.get("citation", "notes")}
            for n in (notes if isinstance(notes, list) else [])[:2]
        ]
    return finish(evidence=evidence, gaps=[] if evidence else ["no evidence found"])


def researcher_search(messages):
    if any(m["content"].startswith("Error from search_documents") for m in messages[1:]):
        return tool("search_notes", query="approved AI tools restricted information")
    return tool(
        "search_documents", query="Which AI tools are approved for restricted information?", top_k=2
    )


SCRIPTS = {
    "intake": [
        lambda m: tool(
            "tracker_create",
            title="AI tools and restricted information",
            requester="head.of.unit@aurora.example",
            deadline="2026-10-15",
            topic="AI tools",
        ),
        lambda m: finish(
            case_id=(last_result(m, "tracker_create") or {}).get("case_id", "unknown"),
            requester="head.of.unit@aurora.example",
            deadline="2026-10-15",
            questions=["Which AI tools are approved?", "How long are AI prompts kept?"],
        ),
    ],
    "researcher": [
        researcher_search,
        lambda m: (
            researcher_finish(m)
            if last_result(m, "search_documents") or last_result(m, "search_notes") is not None
            else tool("search_notes", query="approved AI tools")
        ),
        researcher_finish,
    ],
    "drafter": [
        lambda m: tool(
            "save_draft",
            case_id=case_file(m).get("intake", {}).get("case_id", "unknown"),
            text="Demonstration draft based on the cited evidence [1].",
        ),
        lambda m: finish(
            draft_id=(last_result(m, "save_draft") or {}).get("draft_id", "unknown"),
            draft="Demonstration draft based on the cited evidence [1].",
        ),
    ],
    "reviewer": [lambda m: finish(approved=True, issues=[])],
    "dispatcher": [
        lambda m: tool("publish_to_website", title="Briefing note", body="..."),  # refused
        lambda m: tool(
            "send_email",
            to="head.of.unit@aurora.example",
            subject="Input: AI tools and restricted information",
            body="Demonstration draft based on the cited evidence [1].",
        ),
        lambda m: tool(
            "tracker_update",
            case_id=case_file(m).get("intake", {}).get("case_id", "unknown"),
            status="sent",
        ),
        lambda m: finish(sent=True, note="Sent after a person approved it."),
    ],
}


def chat_reply(messages: list[dict]) -> str:
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    match = re.search(r"You are the (\w+) agent", system)
    if not match or match.group(1) not in SCRIPTS:
        return "This is the demonstration model: it plays scripted agents and does not reason."
    script = SCRIPTS[match.group(1)]
    step = sum(1 for m in messages if m["role"] == "assistant")
    return json.dumps(script[min(step, len(script) - 1)](messages))


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMENSIONS
        vector[bucket] += 1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._send(200 if self.path == "/health" else 404, {"status": "ok"})

    def do_POST(self):  # noqa: N802
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self._send(400, {"error": {"message": "invalid JSON"}})
        if self.path.endswith("/chat/completions"):
            messages = request.get("messages") or []
            text = chat_reply(messages)
            prompt = sum(len(str(m.get("content", ""))) for m in messages) // 4
            return self._send(
                200,
                {
                    "object": "chat.completion",
                    "model": request.get("model", "demo"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
                    "usage": {"prompt_tokens": prompt, "completion_tokens": len(text) // 4},
                },
            )
        if self.path.endswith("/embeddings"):
            inputs = request.get("input")
            inputs = [inputs] if isinstance(inputs, str) else inputs or []
            return self._send(
                200,
                {
                    "object": "list",
                    "model": request.get("model", "demo-embed"),
                    "data": [
                        {"object": "embedding", "index": i, "embedding": embed(t)}
                        for i, t in enumerate(inputs)
                    ],
                    "usage": {"prompt_tokens": sum(len(t) // 4 + 1 for t in inputs)},
                },
            )
        return self._send(404, {"error": {"message": "not found"}})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("demo model server on :9000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
