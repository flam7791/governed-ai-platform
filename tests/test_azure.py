"""Azure deployment (Bicep): compiled when the Bicep CLI is installed, as in CI, then checked.

Only the agents service (and, when enabled, the Copilot Studio front door) is reachable from
outside; every key and token is a Key Vault reference; the gateway calls Azure OpenAI with the
managed identity, so no model key exists anywhere.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BICEP = shutil.which("bicep")

pytestmark = pytest.mark.skipif(BICEP is None, reason="the Bicep CLI is not installed")


@pytest.fixture(scope="module")
def apps() -> dict[str, dict]:
    compiled = subprocess.run(
        [BICEP, "build", str(ROOT / "deploy" / "azure" / "main.bicep"), "--stdout"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    resources = json.loads(compiled)["resources"]
    return {name: r for name, r in resources.items() if r["type"] == "Microsoft.App/containerApps"}


def test_only_the_approvals_page_and_the_copilot_front_door_are_external(apps):
    external = {
        n for n, a in apps.items() if a["properties"]["configuration"]["ingress"]["external"]
    }
    assert external == {"agents", "evidenceM365"}
    assert "condition" in apps["evidenceM365"]  # only when Copilot Studio is enabled


def test_every_secret_is_a_key_vault_reference(apps):
    for name, app in apps.items():
        secrets = app["properties"]["configuration"].get("secrets", [])
        assert secrets, name
        # each entry is built by kvSecret(): a Key Vault URL and the managed identity
        assert all(isinstance(s, str) and s.startswith("[__bicep.kvSecret(") for s in secrets), name


def test_keys_and_tokens_reach_containers_only_as_secret_references():
    source = (ROOT / "deploy" / "azure" / "main.bicep").read_text(encoding="utf-8")
    env_lines = re.findall(r"\{ name: '([A-Z_]+)', (\w+):", source)
    sensitive = [(name, kind) for name, kind in env_lines if "KEY" in name or "TOKEN" in name]
    assert sensitive and all(kind == "secretRef" for _, kind in sensitive), sensitive


def test_gateway_uses_the_managed_identity_and_no_model_key(apps):
    source = (ROOT / "deploy" / "azure" / "main.bicep").read_text(encoding="utf-8")
    assert "AZURE_CLIENT_ID" in source and "AZURE_OPENAI_API_KEY" not in source
    config = json.loads((ROOT / "config" / "gateway.azure.json").read_text(encoding="utf-8"))
    assert all(m["auth"] == "entra_id" for m in config["models"])


def test_stateful_services_run_one_replica(apps):
    for name in ("gateway", "agents", "evidence"):
        scale = apps[name]["properties"]["template"]["scale"]
        assert scale["minReplicas"] == scale["maxReplicas"] == 1, name
