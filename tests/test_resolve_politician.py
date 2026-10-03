"""Testes unitários para a tool canônica resolve_politician.

Atende com rigor absoluto aos seguintes princípios da Constituição:
- Princípio II: Resolução canônica obrigatória antes de consultas de dados e proibição de CPF;
- Princípio VII: Test-Driven Development (TDD) estrito (Red-Green-Refactor);
- Princípio VIII: Cobertura dos 4 quadrantes com isolamento offline 100% livre de rede;
- Princípio X: Stack unificada Python.
"""

import socket
import pytest

from src.tools.resolve_politician import resolve_politician


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Garante isolamento offline (Princípio VIII): qualquer chamada de rede falhará imediatamente."""
    def no_network(*args, **kwargs):
        raise RuntimeError("Chamada de rede detectada! Tools devem operar 100% offline.")

    monkeypatch.setattr(socket, "socket", no_network)


# ==============================================================================
# FASE 3: USER STORY 1 - RESOLUÇÃO CANÔNICA DIRETA (P1 - MVP)
# ==============================================================================

def test_resolve_politician_exact_name():
    """Valida resolução por nome civil exato com retorno dos IDs oficiais (T009)."""
    result = resolve_politician(nome_busca="DARCI POMPEO DE MATTOS", uf="RS")

    assert result["ambiguous"] is False
    assert result["ideCadastro"] == 73486
    assert result["sq_candidato"] == 210001621272
    assert result["cod_senador"] is None
    assert result["nome_civil"] == "DARCI POMPEO DE MATTOS"
    assert result["nome_urna"] == "Pompeo de Mattos"
    assert result["uf"] == "RS"
    assert result["partido"] == "PDT"
    assert result["casa"] == "Câmara dos Deputados"
    assert result["candidatos_alternativos"] == []
    assert result["match_score"] is not None
    assert result["match_score"] >= 95.0


def test_resolve_politician_ballot_name_and_accent_resilience():
    """Valida resolução por nome de urna em minúsculas e sem acentos (T009)."""
    result = resolve_politician(nome_busca="tabata amaral")

    assert result["ambiguous"] is False
    assert result["ideCadastro"] == 204534
    assert result["uf"] == "SP"
    assert result["partido"] == "PSB"
    assert "TABATA" in result["nome_civil"]
    assert result["casa"] == "Câmara dos Deputados"
    assert result["candidatos_alternativos"] == []
    assert result["match_score"] >= 85.0


def test_resolve_politician_senador():
    """Valida resolução de membro do Senado Federal (T009)."""
    result = resolve_politician(nome_busca="Alan Rick", uf="AC", cargo="Senador")

    assert result["ambiguous"] is False
    assert result["casa"] == "Senado Federal"
    assert result["uf"] == "AC"
    assert result["nome_urna"] == "ALAN RICK"
    assert result["candidatos_alternativos"] == []


def test_resolve_politician_contract_keys():
    """Valida aderência estrita às chaves do contrato JSON Schema (T009)."""
    result = resolve_politician(nome_busca="Pompeo de Mattos")

    expected_keys = {
        "sq_candidato",
        "ideCadastro",
        "cod_senador",
        "nome_civil",
        "nome_urna",
        "casa",
        "cargo",
        "uf",
        "partido",
        "ambiguous",
        "candidatos_alternativos",
        "match_score",
    }
    assert set(result.keys()) == expected_keys


def test_resolve_politician_cpf_strict_prohibition():
    """Garante cumprimento do Princípio II: CPF NUNCA deve constar no retorno (T010)."""
    result = resolve_politician(nome_busca="Pompeo de Mattos", uf="RS")

    # Verifica ausência de chave cpf
    assert "cpf" not in result
    assert "CPF" not in result

    # Verifica que nenhum valor retornado contém padrão de CPF (11 dígitos numéricos)
    for k, v in result.items():
        if isinstance(v, str):
            digits = "".join(filter(str.isdigit, v))
            assert len(digits) != 11, f"Possível CPF detectado no campo '{k}': {v}"


def test_resolve_politician_invalid_inputs():
    """Valida rejeição de inputs vazios ou compostos exclusivamente por espaços (T013)."""
    res_empty = resolve_politician(nome_busca="")
    assert res_empty["ambiguous"] is False
    assert res_empty["ideCadastro"] is None
    assert res_empty["candidatos_alternativos"] == []

    res_spaces = resolve_politician(nome_busca="   ")
    assert res_spaces["ambiguous"] is False
    assert res_spaces["ideCadastro"] is None


# ==============================================================================
# FASE 4: USER STORY 2 - HOMÔNIMOS E DESAMBIGUAÇÃO (P2)
# ==============================================================================

def test_resolve_politician_homonym_ambiguity():
    """Valida detecção de homônimos sem UF retornando ambiguous=True e lista de alternativas (T015)."""
    # 'Thomaz Jose Coelho de Almeida' possui múltiplos registros em estados diferentes (PE e RJ)
    result = resolve_politician(nome_busca="Thomaz Jose Coelho de Almeida")

    assert result["ambiguous"] is True
    assert result["ideCadastro"] is None
    assert result["sq_candidato"] is None
    assert len(result["candidatos_alternativos"]) >= 2

    # Verifica estrutura dos candidatos_alternativos
    for alt in result["candidatos_alternativos"]:
        assert "nome_civil" in alt
        assert "uf" in alt
        assert "cargo" in alt


def test_resolve_politician_homonym_disambiguation_with_uf():
    """Valida que fornecer a UF desambigua com sucesso o homônimo (T016)."""
    result = resolve_politician(nome_busca="Thomaz Jose Coelho de Almeida", uf="PE")

    assert result["ambiguous"] is False
    assert result["uf"] == "PE"
    assert result["candidatos_alternativos"] == []


def test_resolve_politician_fuzzy_cluster_ambiguity():
    """Valida que termos comuns que geram múltiplos matches próximos retornam ambiguidade (T015)."""
    result = resolve_politician(nome_busca="Marcelo")

    # 'Marcelo' corresponde a dezenas de parlamentares e gera cluster ambíguo
    assert result["ambiguous"] is True
    assert result["ideCadastro"] is None
    assert len(result["candidatos_alternativos"]) > 1


def test_resolve_politician_cargo_filter_disambiguation():
    """Valida desambiguação utilizando o parâmetro de cargo (T016)."""
    # Alan Rick foi deputado e senador
    result_senador = resolve_politician(nome_busca="Alan Rick", cargo="Senador")
    assert result_senador["ambiguous"] is False
    assert result_senador["cargo"] == "Senador"
    assert result_senador["casa"] == "Senado Federal"


# ==============================================================================
# FASE 5: USER STORY 3 - VALIDAÇÃO DE RANKING E ENTIDADE INEXISTENTE (P3)
# ==============================================================================

def test_resolve_politician_golden_dataset_case_1_pompeo_validation():
    """Valida o cenário exato do Golden Dataset Caso 1: validação do maior gastador da CEAP (T020)."""
    # Na esteira do Golden Dataset, a tool get_top_ceap_spender retorna 'Pompeo de Mattos' (RS).
    # O Agente Sintetizador chama resolve_politician para validar que não é homônimo.
    result = resolve_politician(nome_busca="Pompeo de Mattos", uf="RS")

    assert result["ambiguous"] is False
    assert result["ideCadastro"] == 73486
    assert result["uf"] == "RS"
    assert result["partido"] == "PDT"
    assert result["casa"] == "Câmara dos Deputados"
    assert result["candidatos_alternativos"] == []


def test_resolve_politician_unknown_entity():
    """Valida retorno estruturado seguro para personalidades sem mandato federal registrado (T021)."""
    result = resolve_politician(nome_busca="Personalidade Inexistente da Silva Sauro")

    assert result["ambiguous"] is False
    assert result["ideCadastro"] is None
    assert result["sq_candidato"] is None
    assert result["cod_senador"] is None
    assert result["nome_civil"] is None
    assert result["match_score"] is None
    assert result["candidatos_alternativos"] == []


def test_resolve_politician_gibberish_query():
    """Valida que termos aleatórios ou sem sentido não geram falsos positivos (T021)."""
    result = resolve_politician(nome_busca="xyzqwe 998877")

    assert result["ambiguous"] is False
    assert result["ideCadastro"] is None
    assert result["match_score"] is None
    assert result["candidatos_alternativos"] == []


# ==============================================================================
# FASE 6: POLISH & BENCHMARK DE PERFORMANCE (T025)
# ==============================================================================

def test_resolve_politician_latency_benchmark():
    """Valida que o tempo de resolução atende ao critério de sucesso SC-005 (< 50ms por query)."""
    import time

    # Executa warm-up
    resolve_politician(nome_busca="Pompeo de Mattos")

    names_to_test = [
        ("Nikolas Ferreira", None),
        ("Tabata Amaral", "SP"),
        ("Alan Rick", "AC"),
        ("Pompeo de Mattos", "RS"),
        ("Marcelo", None),
        ("Personalidade Inexistente Sauro", None),
    ]

    durations = []
    for nome, uf in names_to_test:
        start = time.perf_counter()
        resolve_politician(nome_busca=nome, uf=uf)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        durations.append(elapsed_ms)

    avg_ms = sum(durations) / len(durations)
    max_ms = max(durations)

    # Garante meta operacional estabelecida na especificação e plano
    assert avg_ms < 50.0, f"Tempo médio ({avg_ms:.2f}ms) excedeu limite de 50ms"
    assert max_ms < 100.0, f"Tempo máximo ({max_ms:.2f}ms) excedeu limite tolerado"


