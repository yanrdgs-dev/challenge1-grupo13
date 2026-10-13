"""Data da base citada no veredito: calculada de forma determinística a partir do ingestion_info.json."""

import json
import os

import pytest

from src.services import data_freshness
from src.services.data_freshness import data_date, ensure_data_date_cited, format_data_date, load_ingestion_info

INFO = {
    "gerado_em": "2026-10-10T14:21:12+00:00",
    "dados_atualizados_em": "2026-10-10T14:19:06+00:00",
    "fontes": {
        "camara-ceap-2023": {"baixado_em": "2026-10-10T14:13:18+00:00", "url": "u"},
        "camara-ceap-2026": {"baixado_em": "2026-10-10T14:13:20+00:00", "url": "u"},
        "senado-ceaps-2026": {"baixado_em": "2026-10-10T14:15:00+00:00", "url": "u"},
        "senado-ceaps-2024": {"baixado_em": None, "url": "u"},  # adotada, sem data de download
        "camara-proposicoes-2025": {"baixado_em": "2026-10-10T14:14:00+00:00", "url": "u"},
        "camara-proposicoes-2026": {"baixado_em": "2026-10-10T14:16:30+00:00", "url": "u"},
        "senado-materias-2026": {"baixado_em": "2026-10-10T14:44:00+00:00", "url": "u"},
        "camara-deputados": {"baixado_em": "2026-10-10T14:13:30+00:00", "url": "u"},
        "senado-senadores": {"baixado_em": "2026-10-10T14:18:00+00:00", "url": "u"},
        "tse-consulta_cand_2026": {"baixado_em": "2026-10-10T14:19:06+00:00", "url": "u"},
    },
}


# ------------------------------- qual fonte vale para qual tool ------------------------------- #

def test_expenses_use_the_ceap_of_the_requested_year_and_house():
    assert data_date("check_parliamentary_expenses", {"casa": "camara", "ano": 2023}, {"qtd_lancamentos": 3}, INFO) \
        == "2026-10-10T14:13:18+00:00"
    assert data_date("get_top_ceap_spender", {"casa": "senado", "ano": 2026}, {"gastadores": [1]}, INFO) \
        == "2026-10-10T14:15:00+00:00"


def test_expenses_without_year_use_the_most_recent_ceap_of_the_house():
    assert data_date("list_expense_categories", {"casa": "camara"}, {"categorias": [1]}, INFO) == "2026-10-10T14:13:20+00:00"


def test_year_without_download_date_falls_back_to_the_house_sources():
    # senado-ceaps-2024 foi só adotada (sem data): usa a mais recente da casa
    assert data_date("check_parliamentary_expenses", {"casa": "senado", "ano": 2024}, {"qtd_lancamentos": 3}, INFO) \
        == "2026-10-10T14:15:00+00:00"


def test_tramitation_uses_propositions_of_the_house():
    assert data_date("get_proposition_tramitation_history", {"casa": "camara"}, {"encontrado": True}, INFO) \
        == "2026-10-10T14:16:30+00:00"
    assert data_date("check_bill_apensamentos", {"casa": "senado"}, {"encontrado": True}, INFO) \
        == "2026-10-10T14:44:00+00:00"


def test_resolve_politician_uses_the_catalog_sources_it_was_built_from():
    assert data_date("resolve_politician", {"nome_busca": "x"}, {"ideCadastro": 1}, INFO) == "2026-10-10T14:19:06+00:00"


def test_tools_that_do_not_read_ingested_data_have_no_date():
    for tool in ("resolve_proposition", "get_proposition_vote_result", "check_institutional_rule",
                 "check_data_source_coverage", "tool_inexistente"):
        assert data_date(tool, {"casa": "camara"}, {"encontrado": True}, INFO) is None, tool


def test_failed_evidence_has_no_date():
    assert data_date("check_parliamentary_expenses", {"casa": "camara", "ano": 2023}, {"erro": "x"}, INFO) is None
    assert data_date("check_parliamentary_expenses", {"casa": "camara", "ano": 2023}, None, INFO) is None


def test_missing_info_or_unknown_house_has_no_date():
    assert data_date("check_parliamentary_expenses", {"casa": "camara", "ano": 2023}, {"qtd_lancamentos": 1}, None) is None
    assert data_date("check_parliamentary_expenses", {"casa": "marte"}, {"qtd_lancamentos": 1}, INFO) is None
    assert data_date("check_parliamentary_expenses", {"casa": "camara"}, {"qtd_lancamentos": 1}, {"fontes": {}}) is None


# ------------------------------- texto ------------------------------- #

def test_format_uses_brasilia_time():
    assert format_data_date("2026-10-10T14:23:58+00:00") == "10/10/2026 às 11:23 (horário de Brasília)"
    assert format_data_date("2026-10-11T01:30:00+00:00") == "10/10/2026 às 22:30 (horário de Brasília)"


def test_format_of_garbage_is_none():
    assert format_data_date("lixo") is None and format_data_date(None) is None


def test_citation_is_appended_once_and_is_neutral():
    text = ensure_data_date_cited("A despesa existe. Fonte: Câmara.", "2026-10-10T14:13:18+00:00")
    assert text.endswith("Base de dados consultada atualizada em 10/10/2026 às 11:13 (horário de Brasília).")
    assert ensure_data_date_cited(text, "2026-10-10T14:13:18+00:00") == text  # idempotente


def test_citation_wording_does_not_depend_on_the_verdict():
    base = "x"
    a = ensure_data_date_cited(base, "2026-10-10T14:13:18+00:00")
    assert "falso" not in a.lower() and "verdadeiro" not in a.lower() and a == ensure_data_date_cited(base, "2026-10-10T14:13:18+00:00")


def test_no_date_leaves_text_untouched():
    assert ensure_data_date_cited("texto", None) == "texto"


# ------------------------------- leitura do arquivo ------------------------------- #

def write_info(directory, info):
    (directory / "ingestion_info.json").write_text(json.dumps(info), encoding="utf-8")


def test_load_reads_the_file_from_processed_dir_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path))
    write_info(tmp_path, INFO)
    assert load_ingestion_info()["gerado_em"] == INFO["gerado_em"]


def test_load_missing_or_corrupt_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path))
    assert load_ingestion_info() is None
    (tmp_path / "ingestion_info.json").write_text("{nao", encoding="utf-8")
    assert load_ingestion_info() is None


def test_load_picks_up_a_new_file_without_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path))
    write_info(tmp_path, INFO)
    assert load_ingestion_info()["gerado_em"] == "2026-10-10T14:21:12+00:00"
    newer = {**INFO, "gerado_em": "2026-10-11T00:00:00+00:00"}
    write_info(tmp_path, newer)
    st = (tmp_path / "ingestion_info.json").stat()
    os.utime(tmp_path / "ingestion_info.json", ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert load_ingestion_info()["gerado_em"] == "2026-10-11T00:00:00+00:00"


def test_load_does_not_reread_an_unchanged_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path))
    write_info(tmp_path, INFO)
    load_ingestion_info()
    reads = []
    real = data_freshness.json.loads
    monkeypatch.setattr(data_freshness.json, "loads", lambda *a, **k: reads.append(1) or real(*a, **k))
    for _ in range(5):
        load_ingestion_info()
    assert reads == []
