"""CD (5.3): deploy na VM do Azure com Docker Compose, disparado depois do CI na main.

Estrutura validada aqui: docker-compose.prod.yml e .github/workflows/cd.yml. Nada é executado.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.prod.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "cd.yml"


# ------------------------------------ compose de produção ------------------------------------ #

@pytest.fixture(scope="module")
def compose():
    assert COMPOSE.exists(), "falta docker-compose.prod.yml"
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_images_come_from_ghcr_pinned_by_the_deployed_commit(compose):
    for name in ("router-service", "judge-service"):
        image = compose["services"][name]["image"]
        assert image.startswith("ghcr.io/${GHCR_OWNER:?")
        assert ":${IMAGE_TAG:?" in image, "IMAGE_TAG obrigatório, sem valor padrão"


def test_no_service_uses_a_mutable_tag(compose):
    for service in compose["services"].values():
        assert "latest" not in service["image"]


def test_only_the_router_is_published_the_judge_stays_internal(compose):
    assert "ports" not in compose["services"]["judge-service"]
    assert compose["services"]["router-service"]["ports"]


def test_router_reads_parquets_from_the_vm_disk_read_only(compose):
    volumes = compose["services"]["router-service"]["volumes"]
    assert any(v.endswith(":/app/data/processed:ro") for v in volumes)
    assert not any(v.startswith("./") for v in volumes), "caminho absoluto da VM, não relativo ao checkout"


def test_secrets_come_from_an_env_file_on_the_vm_not_from_the_repository(compose):
    for service in compose["services"].values():
        assert service["env_file"]
    text = COMPOSE.read_text(encoding="utf-8")
    assert not re.search(r"(KEY|SECRET|TOKEN)\s*[:=]\s*[A-Za-z0-9]{8,}", text)


def test_services_restart_and_report_health(compose):
    for service in compose["services"].values():
        assert service["restart"] == "unless-stopped"
        assert "healthcheck" in service


def test_router_waits_for_a_healthy_judge(compose):
    assert compose["services"]["router-service"]["depends_on"]["judge-service"]["condition"] == "service_healthy"


# ------------------------------------ workflow de CD ------------------------------------ #

@pytest.fixture(scope="module")
def text():
    assert WORKFLOW.exists(), "falta .github/workflows/cd.yml"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(text):
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def job(workflow):
    return workflow["jobs"]["deploy"]


def triggers(workflow):
    return workflow.get("on") or workflow.get(True)


def test_deploys_only_after_a_successful_ci_on_main(workflow, job):
    run = triggers(workflow)["workflow_run"]
    assert run["workflows"] == ["CI"] and run["types"] == ["completed"] and run["branches"] == ["main"]
    assert "github.event.workflow_run.conclusion == 'success'" in str(job["if"])


def test_manual_deploy_of_a_given_commit_is_possible(workflow):
    assert "workflow_dispatch" in triggers(workflow)


def test_deploys_are_serialized_and_never_cancelled_midway(workflow):
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_job_uses_the_production_environment_and_read_only_token(workflow, job):
    assert job["environment"] == "production"
    assert workflow["permissions"] == {"contents": "read"}


def test_deployed_tag_is_the_ci_commit_and_is_validated_as_a_sha(job, text):
    assert "github.event.workflow_run.head_sha" in text
    assert re.search(r"\^\[0-9a-f\]\{40\}\$", text), "valida o formato do SHA antes de usá-lo em comando remoto"


def test_ssh_pins_the_host_key_instead_of_trusting_on_first_use(text):
    assert "StrictHostKeyChecking=no" not in text
    assert "known_hosts" in text
    assert "secrets.AZURE_VM_SSH_KEY" in text and "vars.AZURE_VM_HOST" in text


def test_private_key_file_is_locked_down_and_removed(text):
    assert "chmod 600" in text
    assert "rm -f" in text


def test_deploy_pulls_then_starts_and_checks_health(text):
    assert "docker compose" in text and " pull" in text and "up -d" in text
    assert "/health" in text


def test_failed_health_check_rolls_back_to_the_previous_tag(text):
    assert "PREVIOUS_TAG" in text or "previous_tag" in text
    assert "exit 1" in text


def test_no_third_party_ssh_action_is_used(workflow):
    for step in workflow["jobs"]["deploy"]["steps"]:
        uses = step.get("uses", "")
        assert not uses or uses.startswith(("actions/",)), uses


def test_every_action_is_pinned_to_a_version(job):
    for step in job["steps"]:
        uses = step.get("uses")
        if uses:
            assert "@" in uses and not uses.endswith(("@main", "@master")), uses
