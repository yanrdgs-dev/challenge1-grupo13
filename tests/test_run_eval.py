"""scripts/run_eval.py: sobe judge e router, roda o golden experiment e derruba tudo (execução manual)."""

import pytest

from scripts import run_eval


class FakeProc:
    def __init__(self, cmd, env, exits_early=False, hangs=False):
        self.cmd, self.env = cmd, env
        self.returncode = 1 if exits_early else None
        self.hangs = hangs
        self.terminated = self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.hangs and not self.killed:
            raise run_eval.WaitTimeout()
        self.returncode = self.returncode if self.returncode is not None else 0


class Harness:
    """Dependências injetadas: nada de processo, porta ou rede reais."""

    def __init__(self, ollama=True, busy_ports=(), healthy=True, early_exit=None, hang=False, experiment_code=0):
        self.procs = []
        self.experiment_calls = []
        self.ollama, self.busy_ports, self.healthy = ollama, set(busy_ports), healthy
        self.early_exit, self.hang, self.experiment_code = early_exit, hang, experiment_code

    def spawn(self, cmd, env):
        service = "judge" if "judge_service" in " ".join(cmd) else "router"
        proc = FakeProc(cmd, env, exits_early=(service == self.early_exit), hangs=self.hang)
        self.procs.append(proc)
        return proc

    def experiment(self, argv):
        self.experiment_calls.append(argv)
        if isinstance(self.experiment_code, Exception):
            raise self.experiment_code
        return self.experiment_code

    def run(self, argv=None, env=None):
        return run_eval.main(
            argv or [],
            spawn=self.spawn,
            experiment=self.experiment,
            is_healthy=lambda url: self.healthy,
            port_in_use=lambda port: port in self.busy_ports,
            ollama_up=lambda url: self.ollama,
            sleep=lambda s: None,
            env=env if env is not None else {},
        )

    def by_service(self, name):
        return next(p for p in self.procs if name in " ".join(p.cmd))


# ------------------------------------ caminho feliz ------------------------------------ #

def test_happy_path_starts_both_services_runs_the_experiment_and_stops_them():
    h = Harness()
    assert h.run() == 0
    assert len(h.procs) == 2
    assert all(p.terminated for p in h.procs)
    assert len(h.experiment_calls) == 1


def test_services_use_dedicated_ports_and_the_router_points_to_the_judge():
    h = Harness()
    h.run()
    judge, router = h.by_service("judge_service"), h.by_service("router_service")
    assert "18001" in judge.cmd and "18000" in router.cmd
    assert router.env["JUDGE_SERVICE_URL"] == "http://localhost:18001"


def test_experiment_targets_the_router_and_receives_the_extra_arguments():
    h = Harness()
    h.run(["--run-name", "meu-run", "--local"])
    argv = h.experiment_calls[0]
    assert argv[argv.index("--router-url") + 1] == "http://localhost:18000"
    assert "--run-name" in argv and "meu-run" in argv and "--local" in argv


def test_own_options_are_not_forwarded_to_the_experiment():
    h = Harness()
    h.run(["--prompt-label", "staging", "--startup-timeout", "30"])
    argv = h.experiment_calls[0]
    assert "--prompt-label" not in argv and "--startup-timeout" not in argv


def test_experiment_exit_code_is_the_script_exit_code():
    for code in (0, 1, 2):
        assert Harness(experiment_code=code).run() == code


# ------------------------------------ ambiente dos serviços ------------------------------------ #

def test_llm_timeout_defaults_to_120_but_respects_the_environment():
    h = Harness()
    h.run(env={})
    assert h.by_service("router_service").env["LLM_TIMEOUT"] == "120"
    h2 = Harness()
    h2.run(env={"LLM_TIMEOUT": "300"})
    assert h2.by_service("router_service").env["LLM_TIMEOUT"] == "300"


def test_prompt_label_is_passed_to_the_services():
    h = Harness()
    h.run(["--prompt-label", "staging"])
    assert h.by_service("router_service").env["LANGFUSE_PROMPT_LABEL"] == "staging"
    assert h.by_service("judge_service").env["LANGFUSE_PROMPT_LABEL"] == "staging"


def test_prompt_label_is_not_set_unless_requested():
    h = Harness()
    h.run(env={})
    assert "LANGFUSE_PROMPT_LABEL" not in h.by_service("router_service").env


# ------------------------------------ pré-condições ------------------------------------ #

def test_unreachable_ollama_aborts_before_starting_anything(capsys):
    h = Harness(ollama=False)
    assert h.run() == 2
    assert h.procs == [] and h.experiment_calls == []
    assert "Ollama" in capsys.readouterr().err


@pytest.mark.parametrize("busy", [18000, 18001])
def test_busy_port_aborts_instead_of_measuring_someone_elses_service(busy, capsys):
    h = Harness(busy_ports=[busy])
    assert h.run() == 2
    assert h.procs == [] and h.experiment_calls == []
    assert str(busy) in capsys.readouterr().err


# ------------------------------------ falhas e limpeza ------------------------------------ #

def test_services_that_never_become_healthy_abort_and_are_stopped(capsys):
    h = Harness(healthy=False)
    assert h.run(["--startup-timeout", "2"]) == 2
    assert h.experiment_calls == []
    assert all(p.terminated for p in h.procs)
    assert "saudáveis" in capsys.readouterr().err


@pytest.mark.parametrize("service", ["judge", "router"])
def test_service_that_exits_early_fails_fast(service):
    h = Harness(early_exit=service)
    assert h.run() == 2
    assert h.experiment_calls == []
    assert all(p.terminated or p.returncode is not None for p in h.procs)


def test_experiment_crash_still_stops_the_services_and_exits_2():
    h = Harness(experiment_code=RuntimeError("explodiu"))
    assert h.run() == 2
    assert all(p.terminated for p in h.procs)


def test_stubborn_service_is_killed_after_terminate_times_out():
    h = Harness(hang=True)
    h.run()
    assert all(p.terminated and p.killed for p in h.procs)
