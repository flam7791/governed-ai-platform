"""Kubernetes manifests: the hardening and the network rules, checked on every change.

The manifests are read as YAML (no cluster needed). When `kustomize` is installed, as in CI,
each overlay is also rendered and the rendered objects are checked: everything in the platform's
namespace, generated secrets and configuration resolved, and no route out in sovereign mode.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "deploy" / "kubernetes"
OVERLAYS = {
    "demo": "gateway.demo.json",
    "live": "gateway.json",
    "sovereign": "gateway.sovereign.json",
}


def documents(paths) -> list[dict]:
    docs = []
    for path in paths:
        docs += [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    return docs


def manifests() -> list[dict]:
    files = [p for p in K8S.rglob("*.yaml") if p.name != "kustomization.yaml"]
    return documents(files)


def of_kind(docs, kind) -> dict[str, dict]:
    return {d["metadata"]["name"]: d for d in docs if d["kind"] == kind}


def pod_specs(docs):
    for name, deployment in of_kind(docs, "Deployment").items():
        yield name, deployment["spec"]["template"]["spec"]


@pytest.mark.parametrize("name,spec", list(pod_specs(manifests())), ids=lambda x: x)
def test_every_pod_is_hardened(name, spec):
    pod = spec["securityContext"]
    assert pod["runAsNonRoot"] is True
    assert pod["seccompProfile"]["type"] == "RuntimeDefault"
    assert spec.get("automountServiceAccountToken") is False, "no Kubernetes API token in pods"
    for container in spec["containers"] + spec.get("initContainers", []):
        ctx = container["securityContext"]
        assert ctx["allowPrivilegeEscalation"] is False
        assert ctx["readOnlyRootFilesystem"] is True
        assert ctx["capabilities"]["drop"] == ["ALL"]
        assert {"requests", "limits"} <= set(container["resources"])
        assert not container["image"].endswith(":latest")
    for container in spec["containers"]:
        assert "readinessProbe" in container, f"{name}/{container['name']} has no readiness probe"


def test_secrets_come_from_secrets_never_literals():
    for _, spec in pod_specs(manifests()):
        for container in spec["containers"] + spec.get("initContainers", []):
            for env in container.get("env", []):
                if any(word in env["name"] for word in ("KEY", "TOKEN")):
                    assert "secretKeyRef" in env.get("valueFrom", {}), env["name"]


def test_network_is_default_deny_and_the_mcp_server_is_reached_only_by_agents():
    policies = of_kind(manifests(), "NetworkPolicy")
    deny = policies["default-deny"]["spec"]
    assert deny["podSelector"] == {} and set(deny["policyTypes"]) == {"Ingress", "Egress"}
    assert "ingress" not in deny and "egress" not in deny
    [rule] = policies["evidence-mcp"]["spec"]["ingress"]
    assert rule["from"] == [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "agents"}}}]
    model = policies["model-server"]["spec"]["ingress"][0]["from"]
    assert model == [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "gateway"}}}]


def test_nothing_is_exposed_outside_the_cluster():
    for name, service in of_kind(manifests(), "Service").items():
        assert service["spec"].get("type", "ClusterIP") == "ClusterIP", name


def test_sovereign_overlay_has_no_route_out():
    overlay = yaml.safe_load((K8S / "overlays" / "sovereign" / "kustomization.yaml").read_text())
    components = " ".join(overlay.get("components", []))
    assert "internet-egress" not in components and "model-pull" not in components


@pytest.mark.parametrize("overlay,config", OVERLAYS.items())
def test_overlay_gateway_config_is_the_reviewed_one(overlay, config):
    copy = (K8S / "overlays" / overlay / "gateway.json").read_bytes()
    assert copy == (ROOT / "config" / config).read_bytes(), "copy config/ into the overlay"


def test_overlay_secrets_are_ignored_by_git():
    assert "deploy/kubernetes/overlays/*/secrets/" in (ROOT / ".gitignore").read_text()


KUSTOMIZE = shutil.which("kustomize")


@pytest.mark.skipif(KUSTOMIZE is None, reason="kustomize is not installed")
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_rendered_overlay(overlay, tmp_path, monkeypatch):
    secrets = K8S / "overlays" / overlay / "secrets"
    if not (secrets / "platform.env").exists():
        sys.path.insert(0, str(ROOT / "scripts"))
        import new_env

        flag = {"demo": ["--demo"], "live": [], "sovereign": ["--sovereign"]}[overlay]
        monkeypatch.setattr(sys, "argv", ["new_env.py", *flag, "--kubernetes"])
        assert new_env.main() == 0
    rendered = subprocess.run(
        [KUSTOMIZE, "build", str(K8S / "overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    docs = [d for d in yaml.safe_load_all(rendered) if d]
    for doc in docs:
        if doc["kind"] != "Namespace":
            assert doc["metadata"]["namespace"] == "governed-ai", doc["metadata"]["name"]
    secret_names = set(of_kind(docs, "Secret"))
    for _, spec in pod_specs(docs):
        for container in spec["containers"] + spec.get("initContainers", []):
            for env in container.get("env", []):
                ref = env.get("valueFrom", {}).get("secretKeyRef")
                if ref:
                    assert ref["name"] in secret_names, f"unresolved secret {ref['name']}"
    egress = [
        rule
        for policy in of_kind(docs, "NetworkPolicy").values()
        for rule in policy["spec"].get("egress", [])
    ]
    leaves = any("ipBlock" in peer for rule in egress for peer in rule.get("to", []))
    assert leaves == (overlay == "live")
