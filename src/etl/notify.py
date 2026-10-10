"""Avisos da ingestão: webhook (Discord, Slack, ntfy ou JSON genérico) e heartbeat externo.

Configuração só por variáveis de ambiente (nada de segredo no repositório):
- `INGESTION_WEBHOOK_URL`: para onde mandar o aviso escrito (falha, recuperação, novidade).
- `INGESTION_HEARTBEAT_URL`: pingado a cada execução bem-sucedida (e em `/fail` na falha). Um serviço como
  healthchecks.io avisa quando os pings PARAM de chegar, que é o único jeito de saber que a ingestão deixou
  de rodar (VM fora, timer desligado, container morto por falta de memória).
- `INGESTION_NOTIFY`: `failures` (só falhas e recuperação), `changes` (padrão: também novidades),
  `always` (toda execução) ou `off`.

Nada aqui levanta exceção: um aviso que falha nunca derruba a ingestão.
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import Header
from typing import Any, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("ETL.Notify")

MODES = ("off", "failures", "changes", "always")
REPEAT_FAILURE_AFTER_HOURS = 6.0
DISCORD_LIMIT = 2000
TIMEOUT = httpx.Timeout(10.0)


@dataclass(frozen=True)
class NotifyConfig:
    webhook_url: Optional[str]
    heartbeat_url: Optional[str]
    mode: str

    @staticmethod
    def from_env(env: Mapping[str, str]) -> "NotifyConfig":
        mode = (env.get("INGESTION_NOTIFY") or "changes").strip().lower()
        return NotifyConfig(
            webhook_url=(env.get("INGESTION_WEBHOOK_URL") or "").strip() or None,
            heartbeat_url=(env.get("INGESTION_HEARTBEAT_URL") or "").strip() or None,
            mode=mode if mode in MODES else "changes",
        )


def send_webhook(url: str, title: str, text: str, client: httpx.Client) -> bool:
    host = urlparse(url).netloc.lower()
    try:
        if "discord.com" in host or "discordapp.com" in host:
            resp = client.post(url, json={"content": f"**{title}**\n{text}"[:DISCORD_LIMIT]})
        elif "slack.com" in host:
            resp = client.post(url, json={"text": f"*{title}*\n{text}"})
        elif "ntfy" in host:
            # cabeçalho HTTP é ASCII: o título acentuado vai em RFC 2047
            resp = client.post(url, content=text.encode("utf-8"), headers={"Title": Header(title, "utf-8").encode()})
        else:
            resp = client.post(url, json={"title": title, "text": text})
    except httpx.HTTPError as e:
        logger.warning("Webhook falhou: %s", e)
        return False
    if resp.status_code >= 400:
        logger.warning("Webhook devolveu HTTP %d", resp.status_code)
        return False
    return True


def ping_heartbeat(url: str, ok: bool, client: httpx.Client) -> bool:
    target = url if ok else url.rstrip("/") + "/fail"
    try:
        resp = client.get(target)
    except httpx.HTTPError as e:
        logger.warning("Heartbeat falhou: %s", e)
        return False
    return resp.status_code < 400


def format_message(run: Mapping[str, Any], recovered: bool) -> Tuple[str, str]:
    changes = list(run.get("changes", []))
    if run.get("exit_code", 0) != 0:
        lines = [f"Execução de {run.get('finished_at')} terminou com erro (código {run.get('exit_code')})."]
        lines += [f"- {f}" for f in run.get("failures", [])] or ["- sem detalhes (veja o journal da VM)"]
        lines.append("Os parquets publicados continuam os da carga anterior.")
        return "Ingestão falhou", "\n".join(lines)
    origins = ", ".join(f"{o} {n}" for o, n in sorted((run.get("changes_by_origin") or {}).items()))
    news = (f"{run.get('downloaded', 0)} fonte(s) com novidade" + (f" ({origins})" if origins else "") + ": "
            + ", ".join(changes[:8]) + (" ..." if run.get("downloaded", 0) > 8 else "")) if run.get("downloaded") else "sem novidades nas fontes"
    built = "Parquets publicados." if run.get("built") else "Parquets não foram reconstruídos."
    if recovered:
        return "Ingestão normalizada", f"A execução voltou a funcionar: {news}. {built}"
    if run.get("downloaded") or run.get("built"):
        return "Ingestão: novidade nas bases públicas", f"{news}. {built}"
    return "Ingestão executada", f"{news}."


def _hours_between(earlier: Optional[str], later: str) -> Optional[float]:
    try:
        a, b = datetime.fromisoformat(earlier), datetime.fromisoformat(later)
    except (TypeError, ValueError):
        return None
    return (b - a).total_seconds() / 3600


def notify_run(
    run: Mapping[str, Any],
    state: Any,
    env: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.Client] = None,
    now: Optional[str] = None,
) -> List[str]:
    """Avisa sobre uma execução conforme a configuração. Devolve o que foi enviado ("webhook", "heartbeat")."""
    cfg = NotifyConfig.from_env(os.environ if env is None else env)
    if cfg.mode == "off" or not (cfg.webhook_url or cfg.heartbeat_url):
        return []
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    failed = run.get("exit_code", 0) != 0
    # novidade só do Senado (adiada) não vale aviso: só o que dispara ou reflete um build
    news = bool(run.get("built") or (run.get("downloaded", 0) - run.get("deferred", 0)) > 0)

    send_text, recovered = False, False
    if failed:
        signature = hashlib.sha1("|".join(sorted(run.get("failures", []))).encode("utf-8")).hexdigest()[:12]
        previous = state.notify
        age = _hours_between(previous.get("last_failure_notified_at"), now)
        if previous.get("last_failure_signature") != signature or age is None or age >= REPEAT_FAILURE_AFTER_HOURS:
            send_text = True
            state.notify = {"last_failure_signature": signature, "last_failure_notified_at": now}
    else:
        recovered = bool(state.notify.get("last_failure_signature"))
        state.notify = {}
        send_text = recovered or (news and cfg.mode in ("changes", "always")) or cfg.mode == "always"

    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    sent: List[str] = []
    try:
        if cfg.webhook_url and send_text:
            title, text = format_message(run, recovered)
            if send_webhook(cfg.webhook_url, title, text, client):
                sent.append("webhook")
        if cfg.heartbeat_url and ping_heartbeat(cfg.heartbeat_url, ok=not failed, client=client):
            sent.append("heartbeat")
    finally:
        if own_client:
            client.close()
    return sent
