"""Proteções dos provedores de LLM: disjuntor (para de insistir num provedor fora do ar) e teto diário.

O estado fica em memória, por processo e por provedor. Um reinício do container zera as contagens, então
o teto diário limita o gasto de forma aproximada, não como um orçamento rígido.
"""

import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Mapping, Optional

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 120.0
# Só o provedor pago tem teto por padrão; os gratuitos seguem sem limite próprio.
DEFAULT_DAILY_CAPS: Dict[str, int] = {"deepseek": 200}

Clock = Callable[[], float]


class CircuitBreaker:
    """Fechado: deixa passar. Aberto: bloqueia por ``cooldown_seconds``. Meio aberto: libera uma tentativa de teste.

    Só falhas seguidas abrem o disjuntor; qualquer sucesso zera a contagem.
    """

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock: Clock = time.time,
    ):
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "closed"
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def allow(self) -> bool:
        """True se uma chamada pode ser feita. Em estado aberto vencido, concede a única tentativa de teste."""
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open" and self._clock() - self._opened_at >= self._cooldown:
                self._state = "half_open"
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._state = "closed"
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state in ("half_open", "open") or self._failures >= self._threshold:
                self._state = "open"
                self._opened_at = self._clock()

    def release_trial(self) -> None:
        """Devolve a vaga de teste quando a tentativa nem mediu o provedor (ex.: chave ausente)."""
        with self._lock:
            if self._state == "half_open":
                self._state = "open"


class DailyCap:
    """Limite de chamadas por dia UTC. ``limit=None`` desliga o teto."""

    def __init__(self, limit: Optional[int], clock: Clock = time.time):
        self._limit = limit
        self._clock = clock
        self._lock = threading.Lock()
        self._day = self._today()
        self._used = 0

    def _today(self):
        return datetime.fromtimestamp(self._clock(), tz=timezone.utc).date()

    def _roll_day(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._used = 0

    @property
    def used(self) -> int:
        with self._lock:
            self._roll_day()
            return self._used

    def exhausted(self) -> bool:
        with self._lock:
            self._roll_day()
            return self._limit is not None and self._used >= self._limit

    def acquire(self) -> None:
        """Conta uma tentativa. Tentativas que falham também contam: o custo real pode ter ocorrido."""
        with self._lock:
            self._roll_day()
            self._used += 1


def _positive_number(raw: Optional[str], default: float, cast: Callable[[str], float]) -> float:
    try:
        value = cast((raw or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


class ProviderGuards:
    """Um disjuntor e um teto por provedor, criados na primeira consulta com a configuração do ambiente."""

    def __init__(self, clock: Clock = time.time, env: Optional[Mapping[str, str]] = None):
        self._clock = clock
        self._env = os.environ if env is None else env
        self._lock = threading.Lock()
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._caps: Dict[str, DailyCap] = {}

    def breaker(self, provider: str) -> CircuitBreaker:
        with self._lock:
            if provider not in self._breakers:
                self._breakers[provider] = CircuitBreaker(
                    failure_threshold=int(
                        _positive_number(self._env.get("LLM_BREAKER_FAILURES"), DEFAULT_FAILURE_THRESHOLD, int)
                    ),
                    cooldown_seconds=_positive_number(
                        self._env.get("LLM_BREAKER_COOLDOWN"), DEFAULT_COOLDOWN_SECONDS, float
                    ),
                    clock=self._clock,
                )
            return self._breakers[provider]

    def cap(self, provider: str) -> DailyCap:
        with self._lock:
            if provider not in self._caps:
                self._caps[provider] = DailyCap(self._cap_limit(provider), clock=self._clock)
            return self._caps[provider]

    def _cap_limit(self, provider: str) -> Optional[int]:
        """``<PROVEDOR>_DAILY_CAP``: número positivo define o teto, ``0`` desliga, inválido volta ao padrão."""
        default = DEFAULT_DAILY_CAPS.get(provider)
        raw = (self._env.get(f"{provider.upper()}_DAILY_CAP") or "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        if value == 0:
            return None
        return value if value > 0 else default


guards = ProviderGuards()


def configure(clock: Optional[Clock] = None, env: Optional[Mapping[str, str]] = None) -> None:
    """Recria o registro (usado em testes para injetar relógio e variáveis de ambiente)."""
    global guards
    guards = ProviderGuards(clock=clock or time.time, env=env)


def reset() -> None:
    """Zera todo o estado e volta ao relógio e ao ambiente reais."""
    configure()
