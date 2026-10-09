"""Especifica o workflow de avaliação (.github/workflows/eval.yml): golden experiment como gate (regra 5).

Roda num runner self-hosted na VM (dados em data/processed e Ollama locais). Por isso nunca executa
código de PR vindo de fork, que ganharia acesso à máquina.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "eval.yml"


@pytest.fixture(scope="module")
def text():
    assert WORKFLOW.exists(), "falta .github/workflows/eval.yml"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(text):
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def job(workflow):
    assert list(workflow["jobs"]) == ["golden"]
    return workflow["jobs"]["golden"]


def triggers(workflow):
    return workflow.get("on") or workflow.get(True)


def run_text(job):
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def step_named(job, fragment):
    return next(s for s in job["steps"] if fragment.lower() in s.get("name", "").lower())


# ------------------------------ gatilhos e segurança ------------------------------ #

def test_triggers_on_pull_requests_main_and_manual_runs(workflow):
    on = triggers(workflow)
    assert {"pull_request", "push", "workflow_dispatch"} <= set(on)
    assert on["push"]["branches"] == ["main"]


def test_only_paths_that_change_behavior_trigger_the_pull_request_run(workflow):
    paths = triggers(workflow)["pull_request"]["paths"]
    for expected in ("src/**", "golden_dataset_v1.json", "evaluation/**", "pyproject.toml", "uv.lock"):
        assert expected in paths


def test_runs_on_the_self_hosted_vm_runner(job):
    assert "self-hosted" in job["runs-on"]


def test_fork_pull_requests_never_reach_the_self_hosted_runner(job):
    """Código de fork executaria na VM: o job só roda em PR do próprio repositório."""
    condition = str(job["if"])
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
    assert "github.event_name != 'pull_request'" in condition


def test_default_permissions_are_read_only(workflow):
    assert workflow["permissions"] == {"contents": "read"}


# ------------------------------ serialização e limites ------------------------------ #

def test_evals_are_serialized_because_they_share_the_ollama_host(workflow):
    concurrency = workflow["concurrency"]
    assert "cancel-in-progress" in concurrency and concurrency["cancel-in-progress"] is False
    assert "github.ref" not in str(concurrency["group"]), "um único grupo: o Ollama da VM é compartilhado"


def test_job_has_a_timeout_that_fits_30_claims_on_local_models(job):
    assert 60 <= job["timeout-minutes"] <= 180


# ------------------------------ execução do gate ------------------------------ #

def test_installs_frozen_dependencies(job):
    assert "uv sync --frozen" in run_text(job)


def test_starts_judge_and_router_and_waits_for_health(job):
    run = run_text(job)
    assert "src.services.judge_service:app" in run
    assert "src.services.router_service:app" in run
    assert "/health" in run
    assert "JUDGE_SERVICE_URL=http://localhost:8001" in run


def test_runs_the_golden_experiment_named_after_the_commit(job):
    run = run_text(job)
    assert "scripts/run_golden_experiment.py" in run
    assert "${{ github.sha }}" in run


def test_gate_failure_fails_the_job(job):
    experiment = step_named(job, "golden experiment")
    assert experiment.get("continue-on-error") is not True
    assert "pipefail" in str(experiment["run"]), "sem pipefail, `| tee` esconderia o código de saída do gate"


def test_experiment_environment_is_explicit(job, workflow):
    env = {**workflow.get("env", {}), **job.get("env", {})}
    assert str(env["LANGFUSE_TRACING_ENABLED"]).lower() == "true"
    assert env["GIT_SHA"] == "${{ github.sha }}"
    assert "LLM_TIMEOUT" in env, "o timeout do LLM local não pode depender do padrão do código"
    assert "LANGFUSE_PUBLIC_KEY" in env and "secrets." in str(env["LANGFUSE_PUBLIC_KEY"])
    assert "LANGFUSE_SECRET_KEY" in env and "secrets." in str(env["LANGFUSE_SECRET_KEY"])


def test_prompt_label_can_be_chosen_on_manual_runs(workflow):
    inputs = triggers(workflow)["workflow_dispatch"]["inputs"]
    assert inputs["prompt_label"]["default"] == "production"
    assert "LANGFUSE_PROMPT_LABEL" in str(workflow)


# ------------------------------ limpeza e artefatos ------------------------------ #

def test_services_are_always_stopped(job):
    cleanup = step_named(job, "encerra")
    assert cleanup["if"] == "always()"
    assert "kill" in cleanup["run"]


def test_log_is_uploaded_even_when_the_gate_fails(job):
    upload = step_named(job, "log")
    assert upload["if"] == "always()"
    assert upload["uses"].startswith("actions/upload-artifact@")


def test_every_action_is_pinned_to_a_version(job):
    for step in job["steps"]:
        uses = step.get("uses")
        if uses:
            assert "@" in uses and not uses.endswith(("@main", "@master")), uses


# ------------------------------ dados da VM ------------------------------ #

def test_links_the_vm_data_directory_and_fails_fast_when_it_is_missing(job):
    link = step_named(job, "dados")
    run = link["run"]
    assert "FACTCHECK_DATA_DIR" in run
    assert "ln -s" in run and "data/processed" in run
    assert "exit 1" in run, "sem os parquets o experiment mediria o dado errado: falhar antes"
    assert "vars.FACTCHECK_DATA_DIR" in str(link.get("env", ""))
