"""Valida a estrutura Kustomize (base + overlays) renderizando com `kubectl kustomize`."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "k8s"

pytestmark = pytest.mark.skipif(
    shutil.which("kubectl") is None, reason="kubectl não instalado"
)


def render(path: Path):
    out = subprocess.run(
        ["kubectl", "kustomize", str(path)], capture_output=True, text=True, check=True
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def by_kind(docs, kind):
    return [d for d in docs if d["kind"] == kind]


@pytest.mark.parametrize("target", ["base", "overlays/dev"])
def test_renders_all_resources(target):
    docs = render(K8S / target)
    assert {d["metadata"]["name"] for d in by_kind(docs, "Deployment")} == {
        "router-deployment",
        "judge-deployment",
    }
    assert {d["metadata"]["name"] for d in by_kind(docs, "Service")} == {
        "router-service",
        "judge-service",
    }
    assert len(by_kind(docs, "ConfigMap")) == 1


def test_base_images_have_no_hardcoded_tag():
    """O fim das tags fixas: a base declara só o nome da imagem."""
    for dep in by_kind(render(K8S / "base"), "Deployment"):
        image = dep["spec"]["template"]["spec"]["containers"][0]["image"]
        assert ":" not in image, f"{image} não deve ter tag na base"


def test_dev_overlay_sets_image_tags_via_kustomize():
    deployments = {
        d["metadata"]["name"]: d["spec"]["template"]["spec"]["containers"][0]["image"]
        for d in by_kind(render(K8S / "overlays/dev"), "Deployment")
    }
    assert deployments["router-deployment"].startswith("factcheck-router:")
    assert deployments["judge-deployment"].startswith("factcheck-judge:")


def test_config_is_preserved_in_dev_overlay():
    cfg = by_kind(render(K8S / "overlays/dev"), "ConfigMap")[0]["data"]
    assert cfg["ROUTER_MODEL"] == "qwen2.5:7b"
    assert cfg["JUDGE_MODEL"] == "qwen2.5:14b"
    assert cfg["JUDGE_SERVICE_URL"] == "http://judge-service:8000"
    assert cfg["OLLAMA_BASE_URL"] == "http://host.docker.internal:11434"


def test_old_flat_manifests_were_moved():
    """Evita que `kubectl apply -f k8s/` aplique manifests duplicados."""
    assert not list(K8S.glob("*.yaml"))
