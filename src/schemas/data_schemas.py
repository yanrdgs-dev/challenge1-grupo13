"""Definição formal de esquemas, colunas obrigatórias e regras de poda (pruning).

Atende aos requisitos da Task 1.1 e 1.2:
- docs/data_schemas.md
- Poda estrutural (eliminação de atributos burocráticos/redundantes)
- Mapeamento e normalização de atributos oficiais (TSE e Câmara)
"""

from typing import Dict, List, Optional, Set

# 1. Esquema TSE - Despesas de Campanha
TSE_DESPESAS_COLUMNS: List[str] = [
    "ANO_ELEICAO",
    "SG_UF",
    "SQ_CANDIDATO",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "SG_PARTIDO",
    "DS_CARGO",
    "VR_PAGTO_DESPESA",
    # Suporte contextual opcional
    "DS_TIPO_DESPESA",
    "NM_FORNECEDOR",
]

# 2. Esquema TSE - Cadastro de Candidatos
TSE_CANDIDATOS_COLUMNS: List[str] = [
    "ANO_ELEICAO",
    "SG_UF",
    "SQ_CANDIDATO",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "SG_PARTIDO",
    "DS_CARGO",
    # Suporte contextual opcional
    "NR_CANDIDATO",
    "NM_SOCIAL_CANDIDATO",
    "DS_SITUACAO_CANDIDATURA",
]

# 3. Esquema TSE - Declaração de Bens dos Candidatos
TSE_BENS_COLUMNS: List[str] = [
    "ANO_ELEICAO",
    "SG_UF",
    "SQ_CANDIDATO",
    "DS_TIPO_BEM_CANDIDATO",
    "DS_BEM_CANDIDATO",
    "VR_BEM_CANDIDATO",
]

# 4. Esquema Câmara dos Deputados - Votações Nominais e Proposições
CAMARA_VOTACOES_COLUMNS: List[str] = [
    "idVotacao",
    "uriVotacao",
    "data",
    "dataHoraVoto",
    "idDeputado",
    "deputado_id",
    "nomeDeputado",
    "deputado_nome",
    "siglaPartido",
    "deputado_siglaPartido",
    "siglaUf",
    "deputado_siglaUf",
    "voto",
    "proposicao_id",
    "ultimaApresentacaoProposicao_idProposicao",
    # Suporte contextual opcional
    "proposicao_descricao",
    "descricao",
    "proposicao_ementa",
    "ementa",
]

# Mapeamento de normalização de colunas da Câmara (bruto -> canônico)
CAMARA_VOTACOES_RENAME: Dict[str, str] = {
    "dataHoraVoto": "data",
    "deputado_id": "idDeputado",
    "deputado_nome": "nomeDeputado",
    "deputado_siglaPartido": "siglaPartido",
    "deputado_siglaUf": "siglaUf",
    "ultimaApresentacaoProposicao_idProposicao": "proposicao_id",
    "descricao": "proposicao_descricao",
    "ementa": "proposicao_ementa",
}

# 5. Esquema Câmara dos Deputados - Cota Parlamentar (CEAP)
CAMARA_CEAP_COLUMNS: List[str] = [
    "idDeputado",
    "nuDeputadoId",
    "txNomeParlamentar",
    "sgPartido",
    "sgUF",
    "numAno",
    "numMes",
    "txtDescricao",
    "txtFornecedor",
    "txtCNPJCPF",
    "vlrLiquido",
]

CAMARA_CEAP_RENAME: Dict[str, str] = {
    "nuDeputadoId": "idDeputado",
}

# Dicionário centralizado de schemas conhecidos
DATA_SCHEMAS: Dict[str, List[str]] = {
    "tse_despesas": TSE_DESPESAS_COLUMNS,
    "tse_candidatos": TSE_CANDIDATOS_COLUMNS,
    "tse_bens": TSE_BENS_COLUMNS,
    "camara_votacoes": CAMARA_VOTACOES_COLUMNS,
    "camara_ceap": CAMARA_CEAP_COLUMNS,
}

# Dicionário de renomeação de colunas por schema
SCHEMA_RENAMES: Dict[str, Dict[str, str]] = {
    "camara_votacoes": CAMARA_VOTACOES_RENAME,
    "camara_ceap": CAMARA_CEAP_RENAME,
}


def get_schema_columns(schema_name: str) -> Optional[List[str]]:
    """Retorna a lista de colunas selecionadas para o schema especificado."""
    return DATA_SCHEMAS.get(schema_name.lower().strip())


def detect_schema_by_columns(columns: List[str]) -> Optional[str]:
    """Detecta automaticamente o tipo de schema a partir das colunas presentes no dataset.

    Args:
        columns: Lista de nomes de colunas do DataFrame bruto.

    Returns:
        Identificador do schema ('tse_despesas', 'tse_candidatos', etc.) ou None se não reconhecido.
    """
    cols_set: Set[str] = {c.strip() for c in columns}

    if "VR_PAGTO_DESPESA" in cols_set or "vr_pagto_despesa" in cols_set:
        return "tse_despesas"

    if "VR_BEM_CANDIDATO" in cols_set or "DS_TIPO_BEM_CANDIDATO" in cols_set:
        return "tse_bens"

    if "SQ_CANDIDATO" in cols_set and ("NM_URNA_CANDIDATO" in cols_set or "CD_CARGO" in cols_set):
        return "tse_candidatos"

    if "idVotacao" in cols_set or "deputado_nome" in cols_set or "dataHoraVoto" in cols_set:
        return "camara_votacoes"

    if "vlrLiquido" in cols_set or "txNomeParlamentar" in cols_set or "numSubCota" in cols_set:
        return "camara_ceap"

    return None
