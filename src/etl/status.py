"""Estado da ingestão em forma legível: última execução, novidades, falhas e atraso.

Usado pelo `--status` do pipeline, pelo arquivo `ingestion_status.json` publicado junto dos parquets e
pelo endpoint `GET /api/ingestion/status`.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.etl.ingestion_state import IngestionState, count_by_origin, origin_of

STATUS_FILE = "ingestion_status.json"
HISTORY_SHOWN = 10
SOURCES_SHOWN = 8


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def hours_since(iso: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    moment = _parse(iso)
    if moment is None:
        return None
    return round((_now(now) - moment).total_seconds() / 3600, 4)


def _build_label(run: Dict[str, Any]) -> str:
    if run.get("built"):
        return "publicado"
    return "falhou" if run.get("exit_code", 0) != 0 else "ignorado"


def _origins(run: Dict[str, Any], state: IngestionState) -> Dict[str, int]:
    """Novidades por origem. Execuções gravadas antes do campo existir têm só os ids truncados: nesse caso as
    fontes registradas cuja data de download cai dentro da execução dão a contagem real."""
    if run.get("changes_by_origin"):
        return dict(run["changes_by_origin"])
    if not run.get("downloaded"):
        return {}
    started, finished = _parse(run.get("started_at")), _parse(run.get("finished_at"))
    if started is None or finished is None:
        return count_by_origin(list(run.get("changes", [])))
    in_window = [fid for fid, rec in state.files.items()
                 if (when := _parse(rec.get("downloaded_at"))) is not None and started <= when <= finished]
    return count_by_origin(in_window) if in_window else count_by_origin(list(run.get("changes", [])))


def _summary(run: Dict[str, Any], state: IngestionState) -> Dict[str, Any]:
    started, finished = _parse(run.get("started_at")), _parse(run.get("finished_at"))
    return {
        "iniciou_em": run.get("started_at"),
        "terminou_em": run.get("finished_at"),
        "duracao_segundos": int((finished - started).total_seconds()) if started and finished else None,
        "resultado": "ok" if run.get("exit_code", 0) == 0 else "falhou",
        "exit_code": run.get("exit_code"),
        "fontes_com_novidade": list(run.get("changes", [])),
        "total_novidades": run.get("downloaded", 0),
        "novidades_por_origem": _origins(run, state),
        "novidades_adiadas": run.get("deferred", 0),
        "build": _build_label(run),
        "falhas": list(run.get("failures", [])),
    }


def build_status(state: IngestionState, now: Optional[datetime] = None) -> Dict[str, Any]:
    history: List[Dict[str, Any]] = state.history or ([state.last_run] if state.last_run else [])
    last_ok = next((r for r in reversed(history) if r.get("exit_code", 0) == 0), None)
    last_news = next((r for r in reversed(history) if r.get("downloaded", 0) > 0), None)
    streak = 0
    for r in reversed(history):
        if r.get("exit_code", 0) == 0:
            break
        streak += 1
    downloaded_dates = [rec["downloaded_at"] for rec in state.files.values() if rec.get("downloaded_at")]
    return {
        "gerado_em": _now(now).isoformat(timespec="seconds"),
        "ultima_execucao": _summary(history[-1], state) if history else None,
        "ultimo_sucesso_em": last_ok["finished_at"] if last_ok else None,
        "ultima_novidade": (
            {"em": last_news["finished_at"], "total": last_news["downloaded"],
             "por_origem": _origins(last_news, state), "fontes": list(last_news.get("changes", []))}
            if last_news else None
        ),
        "carga_pendente": bool(state.pending_build),
        "dados_atualizados_em": max(downloaded_dates) if downloaded_dates else None,
        "fontes_registradas": len(state.files),
        "aguardando_build": len(state.deferred),
        "falhas_seguidas": streak,
        "historico": [
            {"terminou_em": r.get("finished_at"), "resultado": "ok" if r.get("exit_code", 0) == 0 else "falhou",
             "novidades": r.get("downloaded", 0), "build": _build_label(r)}
            for r in history[-HISTORY_SHOWN:]
        ],
    }


def is_stale(status: Dict[str, Any], max_age_hours: float, now: Optional[datetime] = None) -> bool:
    """Desatualizada = nunca teve sucesso ou o último sucesso é mais velho que o limite."""
    age = hours_since(status.get("ultimo_sucesso_em"), now)
    return age is None or age > max_age_hours


def _ago(iso: Optional[str], now: datetime) -> str:
    hours = hours_since(iso, now)
    if hours is None:
        return "—"
    if hours < 1:
        return f"há {max(int(hours * 60), 0)} min"
    if hours < 48:
        return f"há {int(hours)} h"
    return f"há {int(hours // 24)} dias"


def _fmt(iso: Optional[str]) -> str:
    moment = _parse(iso)
    return moment.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC") if moment else "—"


def format_status(status: Dict[str, Any], now: Optional[datetime] = None) -> str:
    now = _now(now)
    run = status.get("ultima_execucao")
    lines = ["Ingestão das bases públicas", ""]
    if run is None:
        lines.append("A ingestão nunca rodou neste diretório de dados.")
        return "\n".join(lines)

    ok = run["resultado"] == "ok"
    dur = run.get("duracao_segundos")
    dur_txt = f", {dur // 60} min {dur % 60:02d} s" if dur is not None else ""
    lines.append(f"Última execução: {_fmt(run['terminou_em'])} ({_ago(run['terminou_em'], now)}): "
                 f"{'OK' if ok else 'FALHOU'}{dur_txt}")
    if run["total_novidades"]:
        shown = run["fontes_com_novidade"][:SOURCES_SHOWN]
        extra = run["total_novidades"] - len(shown)
        origins = ", ".join(f"{o} {n}" for o, n in sorted(run.get("novidades_por_origem", {}).items()))
        lines.append(f"Novidades: {run['total_novidades']} fonte(s)" + (f" ({origins})" if origins else "")
                     + f": {', '.join(shown)}" + (f" e mais {extra}" if extra > 0 else ""))
    else:
        lines.append("Novidades: nenhuma")
    ignorado = ("ignorado (as novidades do Senado aguardam o próximo build)" if run.get("novidades_adiadas")
                else "ignorado (sem novidades e parquets já publicados)")
    build_txt = {"publicado": "parquets publicados", "ignorado": ignorado, "falhou": "não concluído"}[run["build"]]
    lines.append(f"Build: {build_txt}")
    if run["falhas"]:
        lines.append("Falhas:")
        lines += [f"  - {f}" for f in run["falhas"]]
    if status["falhas_seguidas"] > 1:
        lines.append(f"Atenção: {status['falhas_seguidas']} execuções seguidas com falha.")
    lines.append("")
    lines.append(f"Último sucesso: {_fmt(status['ultimo_sucesso_em'])} ({_ago(status['ultimo_sucesso_em'], now)})"
                 if status["ultimo_sucesso_em"] else "Último sucesso: nunca")
    news = status.get("ultima_novidade")
    lines.append(f"Última carga com novidade: {_fmt(news['em'])} ({_ago(news['em'], now)}), {news['total']} fonte(s)"
                 if news else "Última carga com novidade: nenhuma registrada")
    lines.append(f"Dados atualizados em: {_fmt(status['dados_atualizados_em'])}")
    if status.get("aguardando_build"):
        lines.append(f"Aguardando o próximo build: {status['aguardando_build']} novidade(s) do Senado "
                     "(são baixadas, mas não disparam sozinhas o rebuild dos parquets).")
    if status["carga_pendente"]:
        lines.append("Carga pendente: há dados baixados ainda não convertidos em parquet (o próximo build os publica).")
    lines.append(f"Fontes registradas: {status['fontes_registradas']}")
    if status["historico"]:
        n = len(status["historico"])
        lines += ["", "Execução registrada:" if n == 1 else f"Últimas {n} execuções:"]
        for h in reversed(status["historico"]):
            lines.append(f"  {_fmt(h['terminou_em'])}  {'ok    ' if h['resultado'] == 'ok' else 'FALHOU'}  "
                         f"novidades: {h['novidades']}  build: {h['build']}")
    return "\n".join(lines)


def write_status_file(directory: Path, status: Dict[str, Any]) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / STATUS_FILE
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=STATUS_FILE + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def read_status_file(directory: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads((Path(directory) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
