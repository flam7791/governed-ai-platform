"""Configuration invariants, checked on every change (no containers needed).

The sovereign configuration's promise is structural: no model it defines is external, and every
team is local_only. These tests make that promise fail loudly if someone edits it away.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = sorted((ROOT / "config").glob("gateway*.json"))
INTERNAL_HOSTS = {"ollama", "vllm", "mock-llm", "host.docker.internal", "localhost", "127.0.0.1"}


def load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.name)
def test_every_reference_points_to_a_defined_model(path):
    cfg = json.loads(path.read_text(encoding="utf-8"))
    aliases = {m["alias"] for m in cfg["models"]}
    assert set(cfg["tier_models"].values()) <= aliases
    assert set(cfg["fallback_order"]) <= aliases
    assert cfg["embedding_model"] in aliases
    for team in cfg["teams"]:
        assert team["allowed_models"] == ["*"] or set(team["allowed_models"]) <= aliases
        assert "key" not in team, "keys come from the environment, never the file"


def test_sovereign_has_no_route_out():
    cfg = load("gateway.sovereign.json")
    for model in cfg["models"]:
        assert model["external"] is False, model["alias"]
        assert model["provider"] == "openai_compatible", model["alias"]
        assert urlparse(model["base_url"]).hostname in INTERNAL_HOSTS, model["alias"]
        assert model["price_input"] == model["price_output"] == 0.0
    assert {t["data_policy"] for t in cfg["teams"]} == {"local_only"}
    assert set(cfg["tier_models"]) == {"local", "fast", "strong"}


def test_demo_needs_no_key_and_no_external_model():
    cfg = load("gateway.demo.json")
    assert not any(m["external"] for m in cfg["models"])
    assert all(m["provider"] == "openai_compatible" for m in cfg["models"])


def test_live_config_keeps_the_indexer_local():
    cfg = load("gateway.json")
    indexer = next(t for t in cfg["teams"] if t["name"] == "evidence-indexer")
    assert indexer["data_policy"] == "local_only"


def test_sovereign_profile_starts_the_model_server():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    block = re.search(r"\n  ollama:\n(.*?)\n\n", compose, re.S).group(1)
    assert "sovereign" in block


@pytest.mark.parametrize(
    "flag,expected",
    [
        ([], "gateway.json"),
        (["--demo"], "gateway.demo.json"),
        (["--sovereign"], "gateway.sovereign.json"),
    ],
)
def test_new_env_selects_the_configuration(tmp_path, monkeypatch, flag, expected):
    sys.path.insert(0, str(ROOT / "scripts"))
    import new_env

    monkeypatch.setattr(new_env, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["new_env.py", *flag])
    assert new_env.main() == 0
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"GATEWAY_CONFIG={expected}" in env
