"""compare_providers: um provedor por execução, sem rotação nem fallback, com nome de run por provedor."""

from scripts import compare_providers


def test_provider_env_pins_a_single_provider_without_rotation_or_fallback():
    env = compare_providers.provider_env(
        {"LLM_PROVIDERS": "ollama,groq,deepseek", "LLM_STRATEGY": "round_robin", "LLM_PROVIDER": "x", "FALLBACK_PROVIDER": "y",
         "GROQ_API_KEY": "k"},
        "groq",
    )
    assert env["LLM_PROVIDERS"] == "groq" and env["LLM_STRATEGY"] == "fallback"
    assert "LLM_PROVIDER" not in env and "FALLBACK_PROVIDER" not in env
    assert env["GROQ_API_KEY"] == "k"                       # as chaves seguem para os serviços


def test_deepseek_cap_does_not_cut_the_comparison_but_an_explicit_cap_is_kept():
    assert compare_providers.provider_env({}, "deepseek")["DEEPSEEK_DAILY_CAP"] == "0"
    assert compare_providers.provider_env({"DEEPSEEK_DAILY_CAP": "50"}, "deepseek")["DEEPSEEK_DAILY_CAP"] == "50"


def test_each_provider_runs_once_with_its_own_run_name_and_claims_file():
    calls = []

    def fake_run_eval(argv, env):
        calls.append((argv, env["LLM_PROVIDERS"]))
        return 0

    code = compare_providers.main(["--providers", "groq,ollama"], run_eval_main=fake_run_eval, base_env={})
    assert code == 0
    assert [p for _, p in calls] == ["groq", "ollama"]
    for argv, provider in calls:
        assert argv[argv.index("--run-name") + 1] == f"demo-{provider}"
        assert "--local" in argv and argv[argv.index("--golden-path") + 1].endswith("golden_demo_claims.json")


def test_failed_gate_is_not_an_error_but_an_infrastructure_failure_is():
    assert compare_providers.main(["--providers", "groq"], run_eval_main=lambda a, env: 1, base_env={}) == 0
    assert compare_providers.main(["--providers", "groq"], run_eval_main=lambda a, env: 2, base_env={}) == 2


def test_unknown_provider_is_rejected_without_running_anything():
    ran = []
    assert compare_providers.main(["--providers", "gemini"], run_eval_main=lambda *a, **k: ran.append(1), base_env={}) == 2
    assert not ran
