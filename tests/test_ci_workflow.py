"""Especifica o workflow de CI (.github/workflows/ci.yml): pytest sem rede e build das imagens por commit."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SERVICES = {"router": "docker/Dockerfile.router", "judge": "docker/Dockerfile.judge"}


@pytest.fixture(scope="module")
def workflow():
    assert WORKFLOW.exists(), "falta .github/workflows/ci.yml"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def triggers(workflow):
    return workflow.get("on") or workflow.get(True)   # PyYAML lê a chave `on` como True


def steps_text(job):
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def all_steps(workflow):
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


# ------------------------------ gatilhos e permissões ------------------------------ #

def test_runs_on_pull_requests_and_pushes_to_main(workflow):
    on = triggers(workflow)
    assert "pull_request" in on
    assert on["push"]["branches"] == ["main"]


def test_default_permissions_are_read_only(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_new_push_cancels_the_previous_run_of_the_same_ref(workflow):
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_every_job_has_a_timeout(workflow):
    assert all("timeout-minutes" in job for job in workflow["jobs"].values())


# ------------------------------------ job de testes ------------------------------------ #

def test_test_job_installs_frozen_dependencies_and_runs_pytest(workflow):
    run = steps_text(workflow["jobs"]["test"])
    assert "uv sync --frozen" in run
    assert "uv run pytest" in run


def test_tests_run_with_tracing_disabled_and_without_secrets(workflow):
    job = workflow["jobs"]["test"]
    env = {**workflow.get("env", {}), **job.get("env", {})}
    for step in job["steps"]:
        env.update(step.get("env", {}))
    assert str(env["LANGFUSE_TRACING_ENABLED"]).lower() == "false"
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8").split("build:")[0], \
        "o job de testes não pode depender de secrets (unitários rodam sem rede)"


# ------------------------------------ job de build ------------------------------------ #

def test_build_waits_for_tests(workflow):
    assert workflow["jobs"]["build"]["needs"] == "test"


def test_build_covers_router_and_judge_with_existing_dockerfiles(workflow):
    matrix = workflow["jobs"]["build"]["strategy"]["matrix"]["service"]
    assert set(matrix) == set(SERVICES)
    for dockerfile in SERVICES.values():
        assert (ROOT / dockerfile).exists()


def test_images_are_tagged_with_the_commit_and_pushed_to_ghcr(workflow):
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ghcr.io/" in text
    assert "factcheck-${{ matrix.service }}" in text
    assert "${{ github.sha }}" in text
    assert "latest" not in text, "tags mutáveis escondem qual commit está rodando"


def test_build_job_can_write_packages_and_only_it(workflow):
    assert workflow["jobs"]["build"]["permissions"]["packages"] == "write"
    assert "packages" not in workflow["jobs"]["test"].get("permissions", {})


def test_fork_pull_requests_build_but_do_not_push(workflow):
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.pull_request.head.repo.fork" in text


def test_ghcr_owner_is_lowercased(workflow):
    """O GHCR rejeita nomes com maiúsculas; o dono do repositório pode ter."""
    assert re.search(r"tr '\[:upper:\]' '\[:lower:\]'|,,\}", WORKFLOW.read_text(encoding="utf-8"))


# ------------------------------------ higiene ------------------------------------ #

def test_every_action_is_pinned_to_a_version(workflow):
    for step in all_steps(workflow):
        uses = step.get("uses")
        if uses:
            assert "@" in uses and not uses.endswith("@main") and not uses.endswith("@master"), uses


def test_image_names_match_the_kustomize_overlay(workflow):
    """O CD faz `kustomize edit set image` com estes nomes: precisam existir no overlay."""
    overlay = yaml.safe_load((ROOT / "k8s/overlays/dev/kustomization.yaml").read_text(encoding="utf-8"))
    assert {i["name"] for i in overlay["images"]} == {f"factcheck-{s}" for s in SERVICES}


@pytest.mark.parametrize("dockerfile", SERVICES.values())
def test_images_do_not_bake_in_the_processed_data(dockerfile):
    """Os parquets vêm de volume (gerados na VM); a imagem não depende da versão do dado."""
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    assert "data/processed" not in text
