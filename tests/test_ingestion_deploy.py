"""Arquivos de deploy da ingestão agendada na VM (script, service e timer do systemd) e sua documentação."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "ingestion"
SCRIPT = DEPLOY / "run-ingestion.sh"
SERVICE = DEPLOY / "factcheck-ingestion.service"
TIMER = DEPLOY / "factcheck-ingestion.timer"
DOC = ROOT / "docs" / "ingestion.md"


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_script_is_executable_and_valid_bash():
    assert os.access(SCRIPT, os.X_OK)
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_script_runs_the_pipeline_inside_the_judge_image_with_the_data_volume():
    s = text(SCRIPT)
    assert "set -euo pipefail" in s
    assert "/srv/factcheck/.current_tag" in s or ".current_tag" in s
    assert "factcheck-judge" in s
    assert "/srv/factcheck/data:/app/data" in s
    assert "python -m src.etl.pipeline" in s
    assert "--datasets-dir /app/data/datasets" in s and "--processed-dir /app/data/processed" in s
    assert '"$@"' in s  # repassa --check, --force etc.


def test_script_limits_container_memory_so_the_build_cannot_take_the_vm_down():
    s = text(SCRIPT)
    assert "--memory" in s and "--memory-swap" in s


def test_script_does_not_leak_secrets_or_use_the_env_file():
    s = text(SCRIPT)
    assert "env-file" not in s and ".env" not in s.replace(".current_tag", "")


def test_service_is_a_oneshot_run_by_the_deploy_user_with_a_generous_timeout():
    s = text(SERVICE)
    assert "Type=oneshot" in s
    assert "ExecStart=/srv/factcheck/run-ingestion.sh" in s
    assert "User=deploy" in s
    assert "TimeoutStartSec=" in s
    assert "Requires=docker.service" in s or "After=docker.service" in s


def test_timer_is_persistent_and_targets_the_service():
    s = text(TIMER)
    assert "OnCalendar=" in s
    assert "Persistent=true" in s
    assert "Unit=factcheck-ingestion.service" in s
    assert "WantedBy=timers.target" in s
    assert "RandomizedDelaySec=" in s


def test_doc_explains_install_check_force_logs_and_rollback():
    d = text(DOC)
    for expected in (
        "systemctl enable --now factcheck-ingestion.timer",
        "--check", "--force", "--force-build", "--allow-partial",
        "journalctl -u factcheck-ingestion",
        "ingestion_info.json", ".ingestion_state.json", ".ingestion.lock",
        "systemctl disable --now factcheck-ingestion.timer",
        "df -h", "free -h",
    ):
        assert expected in d, expected
