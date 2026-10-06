"""Testes unitários para o Grupo 6: Regras Institucionais e Disponibilidade de Dados.

Cobre a especificação de:
- 6.1 check_institutional_rule (11 tópicos normativos)
- 6.2 check_data_source_coverage (4 fontes primárias)
Valida a cobertura de 100% das claims correspondentes do golden_dataset_v1.json:
IDs 3, 6, 7, 8, 9, 10, 12, 13, 14, 16, 18, 19, 20, 21, 22, 23, 24.
Atende estritamente às regras 4, 7, 8 e 10 de AGENTS.md.
"""

from pathlib import Path
import pytest

from src.tools.knowledge_tools import (
    INSTITUTIONAL_TOPICS,
    DATA_SOURCES,
    check_institutional_rule,
    check_data_source_coverage,
)


# ---------------------------------------------------------------------------
# Testes de check_institutional_rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "topico,expected_veredito_regra",
    [
        ("calculo_cota_por_uf", "varia_por_uf"),          # Claim 6 (VERDADEIRO)
        ("sabatina_stf", "votacao_secreta"),              # Claim 10 (VERDADEIRO)
        ("votacao_simbolica", "permitida"),               # Claim 12 (VERDADEIRO)
        ("teto_categoria_combustivel", "sem_teto_500"),    # Claim 13 (FALSO: teto mensal bem superior)
        ("cota_compra_bens", "proibido"),                 # Claim 16 (FALSO)
        ("tramitacao_comissoes", "obrigatoria"),          # Claim 18 (FALSO: comissões são obrigatórias)
        ("prestacao_contas_partido", "obrigatoria"),      # Claim 19 (FALSO: obrigatória ao TSE)
        ("veto_presidencial", "sessao_conjunta"),         # Claim 20 (FALSO: votado em sessão conjunta)
        ("lai_gratuidade", "gratuito"),                   # Claim 21 (FALSO: acesso público e gratuito)
        ("cota_campanha_vs_mandato", "proibido"),         # Claim 22 (FALSO: proibido para campanha)
        ("teto_gastos_campanha", "publico"),              # Claim 24 (FALSO: limites são públicos)
    ],
)
def test_check_institutional_rule_all_11_topics(topico: str, expected_veredito_regra: str):
    """Valida que todos os 11 tópicos do Golden Dataset retornam resposta estruturada com citação normativa."""
    result = check_institutional_rule(topico=topico)

    assert result["encontrado"] is True
    assert result["topico"] == topico
    assert "resposta_resumida" in result and len(result["resposta_resumida"]) > 0
    assert "fonte_normativa" in result and len(result["fonte_normativa"]) > 0
    assert "fundamentacao" in result and len(result["fundamentacao"]) > 0
    assert result.get("veredito_regra") == expected_veredito_regra


def test_check_institutional_rule_not_found():
    """Valida comportamento seguro quando o tópico consultado não existe no enum curado."""
    result = check_institutional_rule(topico="topico_inexistente_xyz")

    assert result["encontrado"] is False
    assert result["topico"] == "topico_inexistente_xyz"
    assert result["resposta_resumida"] is None
    assert result["fonte_normativa"] is None
    assert "topicos_disponiveis" in result
    assert set(INSTITUTIONAL_TOPICS).issubset(set(result["topicos_disponiveis"]))


def test_check_institutional_rule_empty_raises_value_error():
    """Valida que passar tópico vazio ou None levanta ValueError."""
    with pytest.raises(ValueError, match="topico"):
        check_institutional_rule(topico="")

    with pytest.raises(ValueError, match="topico"):
        check_institutional_rule(topico=None)  # type: ignore


# ---------------------------------------------------------------------------
# Testes de check_data_source_coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fonte,tipo_dado,expected_disponivel",
    [
        ("portal_transparencia", "diarias_passagens_ministerios", True),     # Claim 3 (VERDADEIRO)
        ("camara_frequencia", "frequencia_plenario", True),                  # Claim 7 (VERDADEIRO)
        ("portal_transparencia", "emendas_relator_rp9", True),               # Claim 8 (VERDADEIRO)
        ("tse_prestacao_contas", "despesas_campanha_candidatos", True),       # Claim 9 (VERDADEIRO)
        ("portal_transparencia", "viagens_internacionais_ministros", True),   # Claim 14 (FALSO que escondeu 100%)
        ("portal_transparencia", "licitacoes_dados_abertos", True),           # Claim 21 (FALSO que precisa assinatura)
        ("camara_notas_taquigraficas", "atas_discursos_plenario", True),      # Claim 23 (FALSO que não registra em ata)
    ],
)
def test_check_data_source_coverage_happy_path(
    fonte: str,
    tipo_dado: str,
    expected_disponivel: bool,
):
    """Valida retorno estruturado de disponibilidade e URL de referência para cada fonte."""
    result = check_data_source_coverage(fonte=fonte, tipo_dado=tipo_dado)

    assert result["encontrado"] is True
    assert result["fonte"] == fonte
    assert result["tipo_dado"] == tipo_dado
    assert result["disponivel"] == expected_disponivel
    assert "url_referencia" in result and result["url_referencia"].startswith("http")
    assert "observacao" in result and len(result["observacao"]) > 0
    assert "base_legal" in result and len(result["base_legal"]) > 0


def test_check_data_source_coverage_invalid_fonte():
    """Valida erro ao passar fonte fora do enum permitido."""
    with pytest.raises(ValueError, match="fonte.*inválida"):
        check_data_source_coverage(fonte="fonte_ficticia", tipo_dado="diarias_passagens_ministerios")


def test_check_data_source_coverage_empty_tipo_dado():
    """Valida erro ao passar tipo_dado vazio."""
    with pytest.raises(ValueError, match="tipo_dado"):
        check_data_source_coverage(fonte="portal_transparencia", tipo_dado="")


def test_check_data_source_coverage_tipo_dado_not_found():
    """Valida comportamento quando o tipo de dado não é mapeado pela fonte."""
    result = check_data_source_coverage(
        fonte="portal_transparencia",
        tipo_dado="tipo_de_dado_inexistente_123",
    )

    assert result["encontrado"] is False
    assert result["disponivel"] is False
    assert result["url_referencia"] is None
    assert "tipos_disponiveis" in result


# ---------------------------------------------------------------------------
# Testes de Cobertura Específica do Golden Dataset
# ---------------------------------------------------------------------------

def test_golden_dataset_claim_6_calculo_cota_por_uf():
    """Claim 6: O valor da cota parlamentar que cada deputado recebe por mês muda de acordo com o estado que ele representa."""
    res = check_institutional_rule("calculo_cota_por_uf")
    assert "Ato da Mesa" in res["fonte_normativa"]
    assert "passagem aérea" in res["fundamentacao"].lower() or "distância" in res["fundamentacao"].lower()


def test_golden_dataset_claim_10_sabatina_stf():
    """Claim 10: A confirmação de ministros do STF pelo Senado é feita por votação secreta."""
    res = check_institutional_rule("sabatina_stf")
    assert "52" in res["fonte_normativa"]
    assert "secreta" in res["resposta_resumida"].lower()


def test_golden_dataset_claim_19_prestacao_contas_partido():
    """Claim 19: Um partido pode receber a cota do Fundo Partidário sem prestar contas ao TSE."""
    res = check_institutional_rule("prestacao_contas_partido")
    assert "9.096" in res["fonte_normativa"]
    assert res["veredito_regra"] == "obrigatoria"


def test_golden_dataset_claim_21_lai_gratuidade():
    """Claim 21: É preciso pagar assinatura para acessar dados abertos de licitações."""
    rule_res = check_institutional_rule("lai_gratuidade")
    assert "12.527" in rule_res["fonte_normativa"]

    cov_res = check_data_source_coverage("portal_transparencia", "licitacoes_dados_abertos")
    assert cov_res["disponivel"] is True
    assert "gratuito" in cov_res["observacao"].lower()
