"""Testes unitários para o Grupo de Gastos (CEAP e CEAPS).

Cobre a especificação da Seção 3 de docs/tools_specification.md:
- get_top_ceap_spender (3.1) -> Golden Dataset ID 1
- list_expense_categories (3.2) -> Golden Dataset IDs 2, 11, 16, 17, 22
- check_parliamentary_expenses (3.3) -> Golden Dataset ID 13

Atende rigorosamente aos princípios da Constituição do Projeto:
- Princípio I: Evidência rastreável
- Princípio IV: Separação entre dado transacional e regra normativa
- Princípio VII: TDD obrigatório (testes independentes e isolados)
- Princípio VIII: Isolamento unitário via fixtures sintéticas
"""

from pathlib import Path
from typing import Any, Dict, List
import polars as pl
import pytest

from src.tools.gastos_tools import (
    TopSpenderItem,
    TopSpenderResponse,
    ExpenseCategoryItem,
    ExpenseCategoriesResponse,
    ExpenseAuditResult,
    _resolve_ceap_dataset,
    get_top_ceap_spender,
    list_expense_categories,
    check_parliamentary_expenses,
)


@pytest.fixture
def mock_ceap_data_dir(tmp_path: Path) -> Path:
    """Fixture que gera dados sintéticos particionados de CEAP (Câmara) e CEAPS (Senado)."""
    base_dir = tmp_path / "data" / "processed"

    # 1. Base Câmara dos Deputados (CEAP) - 2023
    camara_dir = base_dir / "camara" / "ceap" / "ano=2023"
    camara_dir.mkdir(parents=True, exist_ok=True)
    df_camara_2023 = pl.DataFrame({
        "idDeputado": ["101", "102", "101", "103"],
        "txNomeParlamentar": [
            "Pompeo de Mattos",
            "Deputado Silva",
            "Pompeo de Mattos",
            "Deputada Maria",
        ],
        "sgUF": ["RS", "SP", "RS", "RJ"],
        "sgPartido": ["PDT", "PL", "PDT", "PT"],
        "numAno": [2023, 2023, 2023, 2023],
        "numMes": [1, 2, 3, 4],
        "txtDescricao": [
            "COMBUSTÍVEIS E LUBRIFICANTES.",
            "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR",
            "PASSAGEM AÉREA - SIGEPA",
            "COMBUSTÍVEIS E LUBRIFICANTES.",
        ],
        "txtFornecedor": [
            "POSTO IPIRANGA",
            "RESTAURANTE CENTRAL",
            "GOL LINHAS AEREAS",
            "POSTO BR DISTRIBUIDORA",
        ],
        "txtCNPJCPF": [
            "00.000.000/0001-00",
            "11.111.111/0001-11",
            "22.222.222/0001-22",
            "33.333.333/0001-33",
        ],
        "vlrLiquido": [2500.0, 150.0, 3000.0, 750.0],
    })
    df_camara_2023.write_parquet(camara_dir / "ceap_2023.parquet")

    # 2. Base Senado Federal (CEAPS) - 2023
    senado_dir = base_dir / "senado" / "ceaps" / "ano=2023"
    senado_dir.mkdir(parents=True, exist_ok=True)
    df_senado_2023 = pl.DataFrame({
        "COD_SENADOR": ["201", "202", "201"],
        "SENADOR": ["Senador Almeida", "Senadora Beatriz", "Senador Almeida"],
        "UF": ["MG", "BA", "MG"],
        "PARTIDO": ["PSD", "PT", "PSD"],
        "ANO": [2023, 2023, 2023],
        "TIPO_DESPESA": [
            "Contratação de consultorias, assessorias, pesquisas, trabalhos técnicos",
            "Passagens aéreas, aquáticas e terrestres nacionais",
            "Contratação de consultorias, assessorias, pesquisas, trabalhos técnicos",
        ],
        "FORNECEDOR": [
            "CONSULTORIA JURIDICA LTDA",
            "LATAM AIRLINES",
            "ESTUDOS ECONOMICOS SA",
        ],
        "VALOR_REEMBOLSADO": [15000.0, 2200.0, 10000.0],
    })
    df_senado_2023.write_parquet(senado_dir / "ceaps_2023.parquet")

    return base_dir


# ==============================================================================
# Phase 2: Testes dos Modelos Estruturados e Resolução de Dados
# ==============================================================================

def test_top_spender_models():
    """Valida modelos estruturados de ranking de gastos."""
    item = TopSpenderItem(
        posicao=1,
        nome_parlamentar="Pompeo de Mattos",
        uf="RS",
        partido="PDT",
        valor_total=5500.0,
        id_parlamentar="101",
    )
    assert item.posicao == 1
    assert item.valor_total == 5500.0
    assert item.to_dict()["nome_parlamentar"] == "Pompeo de Mattos"

    resp = TopSpenderResponse(
        casa="camara",
        ano=2023,
        top_n=1,
        gastadores=[item],
        total_parlamentares_analisados=3,
    )
    assert resp.casa == "camara"
    assert len(resp.gastadores) == 1
    assert len(resp.to_dict()["gastadores"]) == 1


def test_expense_category_models():
    """Valida modelos estruturados de categorias de despesa."""
    cat = ExpenseCategoryItem(
        categoria="COMBUSTÍVEIS E LUBRIFICANTES.",
        qtd_lancamentos=10,
        valor_total=3500.0,
        exemplos=[{"fornecedor": "POSTO X", "valor": 200.0}],
    )
    assert cat.qtd_lancamentos == 10

    resp = ExpenseCategoriesResponse(
        casa="camara",
        total_categorias=1,
        categorias=[cat],
    )
    assert resp.total_categorias == 1
    assert len(resp.to_dict()["categorias"]) == 1


def test_expense_audit_result_model():
    """Valida modelo estruturado de auditoria de despesas."""
    audit = ExpenseAuditResult(
        casa="camara",
        ano=2023,
        filtros_aplicados={"categoria": "combustivel"},
        qtd_lancamentos=2,
        valor_min=750.0,
        valor_max=2500.0,
        valor_medio=1625.0,
        valor_total=3250.0,
        amostra=[{"fornecedor": "POSTO IPIRANGA", "valor": 2500.0}],
    )
    assert audit.valor_max == 2500.0
    assert audit.qtd_lancamentos == 2
    assert audit.to_dict()["valor_total"] == 3250.0


def test_resolve_ceap_dataset_invalid_house(mock_ceap_data_dir: Path):
    """Garante que casa inválida levante ValueError."""
    with pytest.raises(ValueError, match="Casa legislativa inválida"):
        _resolve_ceap_dataset("assembleia", ano=2023, base_dir=mock_ceap_data_dir)


def test_resolve_ceap_dataset_existing_partitions(mock_ceap_data_dir: Path):
    """Valida carregamento de LazyFrame tanto para Câmara quanto para Senado."""
    lf_camara = _resolve_ceap_dataset("camara", ano=2023, base_dir=mock_ceap_data_dir)
    assert lf_camara is not None
    df_c = lf_camara.collect()
    assert df_c.height == 4

    lf_senado = _resolve_ceap_dataset("senado", ano=2023, base_dir=mock_ceap_data_dir)
    assert lf_senado is not None
    df_s = lf_senado.collect()
    assert df_s.height == 3


# ==============================================================================
# Phase 3: User Story 1 - get_top_ceap_spender (P1 - MVP)
# ==============================================================================

def test_get_top_ceap_spender_camara(mock_ceap_data_dir: Path):
    """Valida cálculo do maior gastador da Câmara em 2023 (Golden Dataset ID 1)."""
    resultado = get_top_ceap_spender(
        casa="camara",
        ano=2023,
        top_n=1,
        base_dir=mock_ceap_data_dir,
    )
    assert isinstance(resultado, TopSpenderResponse)
    assert resultado.casa == "camara"
    assert resultado.ano == 2023
    assert len(resultado.gastadores) == 1

    top1 = resultado.gastadores[0]
    assert top1.posicao == 1
    assert "Pompeo de Mattos" in top1.nome_parlamentar
    assert top1.uf == "RS"
    assert top1.partido == "PDT"
    assert top1.valor_total == 5500.0  # 2500 + 3000


def test_get_top_ceap_spender_senado_multiplos(mock_ceap_data_dir: Path):
    """Valida ranking com top_n > 1 no Senado Federal."""
    resultado = get_top_ceap_spender(
        casa="senado",
        ano=2023,
        top_n=2,
        base_dir=mock_ceap_data_dir,
    )
    assert len(resultado.gastadores) == 2
    # Senador Almeida teve 15000 + 10000 = 25000; Senadora Beatriz teve 2200
    assert resultado.gastadores[0].nome_parlamentar == "Senador Almeida"
    assert resultado.gastadores[0].valor_total == 25000.0
    assert resultado.gastadores[1].nome_parlamentar == "Senadora Beatriz"
    assert resultado.gastadores[1].valor_total == 2200.0


def test_get_top_ceap_spender_ano_sem_dados(mock_ceap_data_dir: Path):
    """Valida que ano inexistente retorna lista vazia de forma segura."""
    resultado = get_top_ceap_spender(
        casa="camara",
        ano=1990,
        top_n=5,
        base_dir=mock_ceap_data_dir,
    )
    assert len(resultado.gastadores) == 0
    assert resultado.total_parlamentares_analisados == 0


def test_get_top_ceap_spender_invalid_casa():
    """Valida que casa inválida rejeita a chamada."""
    with pytest.raises(ValueError):
        get_top_ceap_spender(casa="congresso", ano=2023)


# ==============================================================================
# Phase 4: User Story 2 - list_expense_categories (P1)
# ==============================================================================

def test_list_expense_categories_senado(mock_ceap_data_dir: Path):
    """Valida identificação de categorias reais do Senado (Golden Dataset ID 2 e 17)."""
    resultado = list_expense_categories(
        casa="senado",
        incluir_exemplos=True,
        base_dir=mock_ceap_data_dir,
    )
    assert isinstance(resultado, ExpenseCategoriesResponse)
    assert resultado.total_categorias == 2

    # Verifica presença de consultoria (Golden ID 2)
    nomes_cat = [c.categoria for c in resultado.categorias]
    assert any("consultorias" in c.lower() for c in nomes_cat)

    cat_consultoria = next(c for c in resultado.categorias if "consultorias" in c.categoria.lower())
    assert cat_consultoria.qtd_lancamentos == 2
    assert cat_consultoria.valor_total == 25000.0
    assert len(cat_consultoria.exemplos) > 0


def test_list_expense_categories_camara(mock_ceap_data_dir: Path):
    """Valida identificação de categorias na Câmara (Golden Dataset IDs 11 e 16)."""
    resultado = list_expense_categories(
        casa="camara",
        incluir_exemplos=False,
        base_dir=mock_ceap_data_dir,
    )
    nomes_cat = [c.categoria for c in resultado.categorias]
    # Alimentação presente (Golden ID 11)
    assert any("alimentação" in c.lower() or "alimentacao" in c.lower() for c in nomes_cat)
    # Combustíveis presente
    assert any("combustíveis" in c.lower() or "combustiveis" in c.lower() for c in nomes_cat)
    # Imóveis NÃO deve estar presente (Golden ID 16)
    assert not any("imóvel" in c.lower() or "imovel" in c.lower() for c in nomes_cat)

    # Exemplos vazios quando flag é False
    for cat in resultado.categorias:
        assert cat.exemplos == []


# ==============================================================================
# Phase 5: User Story 3 - check_parliamentary_expenses (P2)
# ==============================================================================

def test_check_parliamentary_expenses_combustivel(mock_ceap_data_dir: Path):
    """Valida auditoria de gastos com combustível refutando teto fixo de R$ 500 (Golden Dataset ID 13)."""
    resultado = check_parliamentary_expenses(
        casa="camara",
        ano=2023,
        categoria="combustivel",
        base_dir=mock_ceap_data_dir,
    )
    assert isinstance(resultado, ExpenseAuditResult)
    assert resultado.qtd_lancamentos == 2  # Dois lançamentos de combustível (2500 e 750)
    assert resultado.valor_min == 750.0
    assert resultado.valor_max == 2500.0
    assert resultado.valor_total == 3250.0
    assert resultado.valor_medio == 1625.0
    # O valor máximo de 2500 refuta formalmente o teto de R$ 500 alegado
    assert resultado.valor_max > 500.0
    assert len(resultado.amostra) == 2


def test_check_parliamentary_expenses_filtro_parlamentar(mock_ceap_data_dir: Path):
    """Valida filtro específico por parlamentar_id."""
    resultado = check_parliamentary_expenses(
        casa="camara",
        ano=2023,
        parlamentar_id="101",
        base_dir=mock_ceap_data_dir,
    )
    assert resultado.qtd_lancamentos == 2
    assert resultado.valor_total == 5500.0
    assert resultado.valor_max == 3000.0


def test_check_parliamentary_expenses_categoria_inexistente(mock_ceap_data_dir: Path):
    """Valida retorno estruturado seguro quando categoria não é encontrada."""
    resultado = check_parliamentary_expenses(
        casa="camara",
        ano=2023,
        categoria="categoria_fantasma_xyz",
        base_dir=mock_ceap_data_dir,
    )
    assert resultado.qtd_lancamentos == 0
    assert resultado.valor_min == 0.0
    assert resultado.valor_max == 0.0
    assert resultado.valor_medio == 0.0
    assert resultado.valor_total == 0.0
    assert resultado.amostra == []


# ==============================================================================
# Phase 6: Validação de Ponta a Ponta contra Claims do Golden Dataset v1
# ==============================================================================

def test_golden_dataset_claim_1_top_spender(mock_ceap_data_dir: Path):
    """Claim 1: 'Em 2023, o deputado que mais gastou a cota parlamentar (CEAP) foi Pompeo de Mattos (PDT-RS).' -> VERDADEIRO"""
    res = get_top_ceap_spender(casa="camara", ano=2023, top_n=1, base_dir=mock_ceap_data_dir)
    assert len(res.gastadores) == 1
    top = res.gastadores[0]
    assert "Pompeo de Mattos" in top.nome_parlamentar
    assert top.partido == "PDT"
    assert top.uf == "RS"
    assert top.posicao == 1


def test_golden_dataset_claim_2_consultorias_senado(mock_ceap_data_dir: Path):
    """Claim 2: 'Senadores podem usar a verba indenizatória (CEAPS) para pagar consultorias e assessorias técnicas...' -> VERDADEIRO"""
    res = list_expense_categories(casa="senado", incluir_exemplos=True, base_dir=mock_ceap_data_dir)
    consultorias = [c for c in res.categorias if "consultorias" in c.categoria.lower()]
    assert len(consultorias) > 0
    assert consultorias[0].qtd_lancamentos > 0


def test_golden_dataset_claim_11_alimentacao_camara(mock_ceap_data_dir: Path):
    """Claim 11: 'Deputados podem pedir reembolso de gastos com alimentação usando a cota parlamentar.' -> VERDADEIRO"""
    res = list_expense_categories(casa="camara", base_dir=mock_ceap_data_dir)
    alimentacao = [c for c in res.categorias if "alimenta" in c.categoria.lower()]
    assert len(alimentacao) > 0
    assert alimentacao[0].qtd_lancamentos > 0


def test_golden_dataset_claim_13_combustivel_teto(mock_ceap_data_dir: Path):
    """Claim 13: 'Todo deputado federal tem um teto fixo de R$ 500,00 por ano para gastar com combustível...' -> FALSO"""
    res = check_parliamentary_expenses(casa="camara", ano=2023, categoria="combustivel", base_dir=mock_ceap_data_dir)
    assert res.qtd_lancamentos > 0
    # O teto de 500 é refutado pois há lançamentos que superam 500
    assert res.valor_max > 500.0


def test_golden_dataset_claim_16_imoveis_camara(mock_ceap_data_dir: Path):
    """Claim 16: 'Um deputado pode usar a cota parlamentar para comprar um imóvel em seu próprio nome.' -> FALSO"""
    res = list_expense_categories(casa="camara", base_dir=mock_ceap_data_dir)
    imovel = [c for c in res.categorias if "imovel" in c.categoria.lower() or "imóvel" in c.categoria.lower()]
    assert len(imovel) == 0


def test_golden_dataset_claim_17_passagens_aereas_senado(mock_ceap_data_dir: Path):
    """Claim 17: 'O Senado proibiu totalmente o uso da cota de gastos (CEAPS) para pagar passagens aéreas.' -> FALSO"""
    res = list_expense_categories(casa="senado", base_dir=mock_ceap_data_dir)
    passagens = [c for c in res.categorias if "passagens" in c.categoria.lower()]
    assert len(passagens) > 0
    # Desmente a alegação de proibição total mostrando presença contínua de despesas
    assert passagens[0].qtd_lancamentos > 0


def test_golden_dataset_claim_22_campanha_eleitoral_senado(mock_ceap_data_dir: Path):
    """Claim 22: 'Um senador pode usar a cota parlamentar para pagar os gastos da própria campanha eleitoral.' -> FALSO"""
    res = list_expense_categories(casa="senado", base_dir=mock_ceap_data_dir)
    campanha = [c for c in res.categorias if "eleitoral" in c.categoria.lower() or "campanha" in c.categoria.lower()]
    assert len(campanha) == 0



# --------------------------------------------------------------------------- #
# ID canônico: o CEAP real traz ideCadastro (o mesmo do resolve_politician) e
# nuDeputadoId (ID interno diferente). O join com a resolução usa ideCadastro.
# --------------------------------------------------------------------------- #

@pytest.fixture
def real_schema_ceap_dir(tmp_path: Path) -> Path:
    base_dir = tmp_path / "data" / "processed"
    camara_dir = base_dir / "camara" / "ceap" / "ano=2023"
    camara_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "txNomeParlamentar": ["Pompeo de Mattos", "Pompeo de Mattos", "Deputado Silva"],
        "ideCadastro": ["73486", "73486", "999"],
        "nuDeputadoId": [1458, 1458, 2000],
        "sgUF": ["RS", "RS", "SP"],
        "sgPartido": ["PDT", "PDT", "PL"],
        "numAno": [2023, 2023, 2023],
        "txtDescricao": ["COMBUSTÍVEIS E LUBRIFICANTES.", "PASSAGEM AÉREA", "COMBUSTÍVEIS E LUBRIFICANTES."],
        "txtFornecedor": ["POSTO", "GOL", "POSTO"],
        "vlrLiquido": [1000.0, 3000.0, 50.0],
    }).write_parquet(camara_dir / "ceap_2023.parquet")
    return base_dir


def test_expenses_filter_by_ide_cadastro_matches_resolver_id(real_schema_ceap_dir: Path):
    resultado = check_parliamentary_expenses(
        casa="camara", ano=2023, parlamentar_id="73486", base_dir=real_schema_ceap_dir
    )
    assert resultado.qtd_lancamentos == 2
    assert resultado.valor_total == 4000.0


def test_expenses_internal_id_no_longer_identifies_parliamentarian(real_schema_ceap_dir: Path):
    resultado = check_parliamentary_expenses(
        casa="camara", ano=2023, parlamentar_id="1458", base_dir=real_schema_ceap_dir
    )
    assert resultado.qtd_lancamentos == 0


def test_top_spender_exposes_ide_cadastro_as_id(real_schema_ceap_dir: Path):
    resultado = get_top_ceap_spender(casa="camara", ano=2023, base_dir=real_schema_ceap_dir)
    assert resultado.gastadores[0].id_parlamentar == "73486"
