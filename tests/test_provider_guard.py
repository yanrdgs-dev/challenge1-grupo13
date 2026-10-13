"""Disjuntor e teto diário dos provedores de LLM (src/core/provider_guard.py).

Tempo simulado por um relógio falso: nenhum teste espera de verdade.
"""

import pytest

from src.core import provider_guard
from src.core.provider_guard import CircuitBreaker, DailyCap, ProviderGuards


class FakeClock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


# ------------------------------------ disjuntor ------------------------------------ #

def make_breaker(clock, threshold=3, cooldown=120.0):
    return CircuitBreaker(failure_threshold=threshold, cooldown_seconds=cooldown, clock=clock)


def test_breaker_starts_closed_and_allows_calls(clock):
    breaker = make_breaker(clock)
    assert breaker.state == "closed" and breaker.allow()


def test_breaker_opens_after_consecutive_failures_and_blocks_calls(clock):
    breaker = make_breaker(clock, threshold=3)
    for _ in range(2):
        breaker.record_failure()
    assert breaker.state == "closed" and breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open" and not breaker.allow()


def test_a_success_resets_the_failure_count(clock):
    breaker = make_breaker(clock, threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "closed", "as falhas não eram seguidas"


def test_breaker_stays_open_during_the_cooldown(clock):
    breaker = make_breaker(clock, threshold=1, cooldown=120)
    breaker.record_failure()
    clock.advance(119)
    assert not breaker.allow()


def test_after_the_cooldown_exactly_one_trial_call_is_allowed(clock):
    breaker = make_breaker(clock, threshold=1, cooldown=120)
    breaker.record_failure()
    clock.advance(120)
    assert breaker.allow() is True
    assert breaker.state == "half_open"
    assert breaker.allow() is False, "só uma requisição de teste por vez"


def test_successful_trial_closes_the_breaker(clock):
    breaker = make_breaker(clock, threshold=1, cooldown=120)
    breaker.record_failure()
    clock.advance(120)
    breaker.allow()
    breaker.record_success()
    assert breaker.state == "closed" and breaker.allow()


def test_failed_trial_reopens_with_a_fresh_cooldown(clock):
    breaker = make_breaker(clock, threshold=1, cooldown=120)
    breaker.record_failure()
    clock.advance(120)
    breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open"
    clock.advance(119)
    assert not breaker.allow()
    clock.advance(1)
    assert breaker.allow()


def test_releasing_an_unused_trial_lets_the_next_call_try_again(clock):
    """Se a tentativa de teste nem chegou a medir o provedor (ex.: chave ausente), a vaga não pode travar."""
    breaker = make_breaker(clock, threshold=1, cooldown=120)
    breaker.record_failure()
    clock.advance(120)
    assert breaker.allow()
    breaker.release_trial()
    assert breaker.allow()


# ------------------------------------ teto diário ------------------------------------ #

def test_cap_allows_calls_up_to_the_limit_then_blocks(clock):
    cap = DailyCap(limit=2, clock=clock)
    assert not cap.exhausted()
    cap.acquire()
    cap.acquire()
    assert cap.exhausted() and cap.used == 2


def test_cap_resets_on_the_next_utc_day(clock):
    clock.now = 1_700_000_000.0  # 2023-11-14 22:13 UTC
    cap = DailyCap(limit=1, clock=clock)
    cap.acquire()
    assert cap.exhausted()
    clock.advance(2 * 3600)  # passou da meia-noite UTC
    assert not cap.exhausted() and cap.used == 0


def test_cap_does_not_reset_within_the_same_day(clock):
    clock.now = 1_700_000_000.0
    cap = DailyCap(limit=1, clock=clock)
    cap.acquire()
    clock.advance(3600)  # 23:13 UTC, ainda o mesmo dia
    assert cap.exhausted()


def test_cap_without_limit_never_blocks(clock):
    cap = DailyCap(limit=None, clock=clock)
    for _ in range(1000):
        cap.acquire()
    assert not cap.exhausted()


# ------------------------------------ registro por provedor (env) ------------------------------------ #

def test_registry_returns_the_same_breaker_for_a_provider(clock):
    guards = ProviderGuards(clock=clock, env={})
    assert guards.breaker("groq") is guards.breaker("groq")
    assert guards.breaker("groq") is not guards.breaker("ollama")


def test_default_breaker_opens_after_three_failures_for_two_minutes(clock):
    guards = ProviderGuards(clock=clock, env={})
    breaker = guards.breaker("ollama")
    for _ in range(3):
        breaker.record_failure()
    assert not breaker.allow()
    clock.advance(120)
    assert breaker.allow()


def test_breaker_is_configurable_by_env(clock):
    guards = ProviderGuards(clock=clock, env={"LLM_BREAKER_FAILURES": "1", "LLM_BREAKER_COOLDOWN": "10"})
    breaker = guards.breaker("ollama")
    breaker.record_failure()
    assert not breaker.allow()
    clock.advance(10)
    assert breaker.allow()


@pytest.mark.parametrize("bad", ["", "abc", "0", "-3"])
def test_invalid_breaker_env_falls_back_to_defaults(clock, bad):
    guards = ProviderGuards(clock=clock, env={"LLM_BREAKER_FAILURES": bad, "LLM_BREAKER_COOLDOWN": bad})
    breaker = guards.breaker("ollama")
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow(), "padrão: 3 falhas seguidas"


def test_only_deepseek_has_a_daily_cap_by_default(clock):
    guards = ProviderGuards(clock=clock, env={})
    for _ in range(500):
        guards.cap("ollama").acquire()
        guards.cap("groq").acquire()
    assert not guards.cap("ollama").exhausted() and not guards.cap("groq").exhausted()
    for _ in range(200):
        guards.cap("deepseek").acquire()
    assert guards.cap("deepseek").exhausted(), "padrão: 200 chamadas por dia"


def test_daily_cap_is_configurable_per_provider_by_env(clock):
    guards = ProviderGuards(clock=clock, env={"DEEPSEEK_DAILY_CAP": "2", "GROQ_DAILY_CAP": "1"})
    for provider, limit in (("deepseek", 2), ("groq", 1)):
        for _ in range(limit):
            guards.cap(provider).acquire()
        assert guards.cap(provider).exhausted()


def test_zero_or_blank_daily_cap_env_means_no_limit_except_invalid_falls_back(clock):
    unlimited = ProviderGuards(clock=clock, env={"DEEPSEEK_DAILY_CAP": "0"})
    for _ in range(300):
        unlimited.cap("deepseek").acquire()
    assert not unlimited.cap("deepseek").exhausted(), "0 desliga o teto de propósito"
    invalid = ProviderGuards(clock=clock, env={"DEEPSEEK_DAILY_CAP": "muitas"})
    for _ in range(200):
        invalid.cap("deepseek").acquire()
    assert invalid.cap("deepseek").exhausted(), "valor inválido volta ao padrão seguro (200)"


def test_module_reset_clears_state_and_accepts_a_clock(clock):
    provider_guard.configure(clock=clock, env={"LLM_BREAKER_FAILURES": "1"})
    provider_guard.guards.breaker("ollama").record_failure()
    assert not provider_guard.guards.breaker("ollama").allow()
    provider_guard.reset()
    assert provider_guard.guards.breaker("ollama").allow()
