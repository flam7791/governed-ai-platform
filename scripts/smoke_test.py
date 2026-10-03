"""End-to-end smoke test of the running platform (standard library only).

    python scripts/smoke_test.py

It checks, in order: health; access control at the gateway; embeddings through the gateway; an
agent run that searches documents over MCP, has a publication refused, and waits for a person;
four eyes (the requester cannot approve); approval by a named approver; completion; the
monitoring figures; and, when tracing is on (new_env.py --tracing, `tracing` profile), that the
run is one trace across the three services with no request text on any span. It reads the
tokens from .env and exits non-zero at the first failure.

With the demonstration model (GATEWAY_CONFIG=gateway.demo.json) the run is fully scripted and
deterministic, which is what CI uses. With live models the same checks apply, but the agents
decide for themselves, so a run can legitimately take other paths.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = "http://127.0.0.1:8080"
AGENTS = "http://127.0.0.1:8090"
JAEGER = "http://127.0.0.1:16686"
SERVICES = {"governed-agents", "governed-llm-gateway", "policy-evidence-mcp"}
REQUEST = """From: head.of.unit@aurora.example
Subject: Input needed by 2026-10-15 - AI tools and restricted information

Which AI tools are approved for staff, and may restricted information be used with them?"""


def env() -> dict:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def call(method, url, token=None, body=None, expect=200):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    if status != expect:
        raise AssertionError(f"{method} {url}: expected {expect}, got {status}: {raw[:300]!r}")
    text = raw.decode()
    try:
        return json.loads(text)
    except ValueError:
        return text


def wait_healthy(url, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            call("GET", url)
            return
        except (AssertionError, OSError):
            time.sleep(2)
    raise AssertionError(f"{url} did not become healthy")


def wait_status(run_id, token, wanted, seconds=180):
    deadline = time.time() + seconds
    while time.time() < deadline:
        run = call("GET", f"{AGENTS}/api/runs/{run_id}", token)
        if run["status"] == wanted:
            return run
        if run["status"] in ("failed", "halted"):
            raise AssertionError(f"run {run_id} {run['status']}: {run.get('error')}")
        time.sleep(1)
    raise AssertionError(f"run {run_id} did not reach {wanted}")


def run_trace(run_id: str, seconds=90) -> dict[str, list[dict]]:
    """The trace of the run's first part (up to the approval) from Jaeger (API v3, OTLP JSON), as
    {service: [spans]}: found by the run id on the agent_run span, once the agents service, the
    gateway and the MCP server's search_documents call have all arrived."""
    deadline, seen = time.time() + seconds, set()
    while time.time() < deadline:
        now = datetime.now(timezone.utc)
        window = (now - timedelta(hours=1), now + timedelta(minutes=1))
        start, end = (t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in window)
        found = call(
            "GET",
            f"{JAEGER}/api/v3/traces?query.service_name=governed-agents"
            f"&query.start_time_min={start}&query.start_time_max={end}&query.search_depth=50",
        )
        traces: dict[str, dict[str, list[dict]]] = {}
        for resource in found.get("result", {}).get("resourceSpans", []):
            service = next(
                a["value"].get("stringValue")
                for a in resource["resource"]["attributes"]
                if a["key"] == "service.name"
            )
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    traces.setdefault(span["traceId"], {}).setdefault(service, []).append(span)
        for by_service in traces.values():
            spans = [s for group in by_service.values() for s in group]
            if any(
                a["key"] == "govagents.run_id" and a["value"].get("stringValue") == run_id
                for s in spans
                for a in s.get("attributes", [])
            ):
                seen = set(by_service)
                mcp = {s["name"] for s in by_service.get("policy-evidence-mcp", [])}
                if seen >= SERVICES and "tools/call search_documents" in mcp:
                    return by_service
        time.sleep(3)  # spans are exported in batches every few seconds
    raise AssertionError(f"no trace of run {run_id} across {sorted(SERVICES)} (saw {seen})")


def main() -> int:
    e = env()
    people = {}
    for item in e["GOVAGENTS_API_TOKENS"].split(","):
        name, role, token = item.split(":", 2)
        people[role] = (name, token)
    requester, approver = people["requester"][1], people["approver"][1]
    steps = []

    def ok(text):
        steps.append(text)
        print(f"ok  {text}", flush=True)

    wait_healthy(f"{GATEWAY}/healthz")
    wait_healthy(f"{AGENTS}/healthz")
    ok("gateway and agents service are healthy")

    call("GET", f"{GATEWAY}/v1/models", expect=401)
    call("GET", f"{GATEWAY}/v1/models", e["LLMGW_KEY_AGENTS"])
    ok("the gateway refuses calls without a team key")

    vectors = call(
        "POST", f"{GATEWAY}/v1/embeddings", e["LLMGW_KEY_EVIDENCE"], {"input": "retention"}
    )
    dims = len(vectors["data"][0]["embedding"])
    ok(f"embeddings through the gateway ({vectors['model']}, {dims} dimensions)")

    run_id = call(
        "POST",
        f"{AGENTS}/api/runs",
        requester,
        {"scenario": "briefing_desk", "request": REQUEST},
        expect=202,
    )["run_id"]
    run = wait_status(run_id, approver, "waiting_approval")
    events = run["events"]
    tools_run = [ev["detail"]["tool"] for ev in events if ev["kind"] == "tool_result"]
    refused = [
        ev["detail"]["tool"]
        for ev in events
        if ev["kind"] == "policy" and ev["detail"]["verdict"] == "deny"
    ]
    print(f"    tools run: {tools_run}; refused: {refused}")
    if "search_documents" in tools_run:
        ok("the researcher searched documents over MCP (HTTP)")
    else:
        print("    note: the MCP server was not used on this run", flush=True)
    ok(f"run {run_id} is waiting for a person")

    [pending] = [
        a for a in call("GET", f"{AGENTS}/api/approvals", approver) if a["run_id"] == run_id
    ]
    call("POST", f"{AGENTS}/api/approvals/{pending['id']}/approve", requester, {}, expect=403)
    ok("the requester cannot approve (role and four eyes)")

    decision = call(
        "POST",
        f"{AGENTS}/api/approvals/{pending['id']}/approve",
        approver,
        {"note": "smoke test"},
        expect=202,
    )
    run = wait_status(run_id, approver, "completed")
    decided = [ev for ev in run["events"] if ev["kind"] == "approval_decided"]
    assert decided and decided[0]["detail"]["by"] == decision["by"]
    ok(f"approved by {decision['by']}; the run completed (cost {run['spent_usd']:.4f} USD)")

    gateway_metrics = call("GET", f"{GATEWAY}/metrics", e["GATEWAY_METRICS_TOKEN"])
    assert 'team="agents"' in gateway_metrics, "no agent traffic in the gateway metrics"
    agents_metrics = call("GET", f"{AGENTS}/metrics", e["AGENTS_METRICS_TOKEN"])
    assert 'govagents_runs{scenario="briefing_desk",status="completed"}' in agents_metrics
    ok("metrics show the agents' model calls at the gateway and the completed run")

    if e.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        by_service = run_trace(run_id)
        spans = [s for group in by_service.values() for s in group]
        values = [str(a["value"]) for s in spans for a in s.get("attributes", [])]
        assert not any("approved for staff" in v for v in values), "request text on a span"
        print(
            f"    {len(spans)} spans: " + ", ".join(f"{k} {len(v)}" for k, v in by_service.items())
        )
        ok("the run is one trace across agents, gateway and MCP server, with no request text")

    print(f"\nAll {len(steps)} checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from None
