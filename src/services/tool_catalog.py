"""Catálogo de tools e prompt do router de fact-checking.

Vive em src/ (e não em scripts/) porque o router, o judge e a validação de parâmetros dependem dele em
tempo de execução, e as imagens Docker só levam o que o serviço precisa. O script de demonstração
(scripts/demo_qwen_tool_routing.py) reexporta estes objetos.
"""

from typing import Any, Dict, List

from src.tools.knowledge_tools import DATA_SOURCES, INSTITUTIONAL_TOPICS, available_data_types

TOOLS_CATALOG: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "resolve_politician",
            "description": "Resolve e valida o nome de um político para identificadores oficiais (Deputado Federal ou Senador). Usar sempre que um parlamentar for citado pelo nome.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_busca": {
                        "type": "string",
                        "description": "Nome civil, nome de urna ou apelido político citado (ex: 'Nikolas Ferreira', 'Pompeo de Mattos').",
                    },
                    "uf": {
                        "type": "string",
                        "description": "Sigla da UF com 2 letras (ex: 'MG', 'RS', 'SP'). ATENÇÃO: NÃO preencha se a frase estiver afirmando de qual estado o político é (ex: 'X é deputado de DF'). Preencha APENAS se a UF for mera referência para desambiguar homônimos.",
                    },
                    "cargo": {
                        "type": "string",
                        "enum": ["Deputado Federal", "Senador"],
                        "description": "NÃO preencha se a frase estiver afirmando o cargo dele.",
                    },
                    "ano": {
                        "type": "integer",
                        "description": "Ano de referência do mandato, se houver.",
                    },
                },
                "required": ["nome_busca"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_proposition",
            "description": "Identifica formalmente matérias legislativas (PL, PLP, PLN, PEC, MPV, PDL) ou busca por nome popular na Câmara, Senado ou Congresso.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado", "congresso"],
                        "description": "Casa legislativa de tramitação da matéria.",
                    },
                    "sigla_tipo": {
                        "type": "string",
                        "description": "Sigla do tipo formal (ex: 'PL', 'PLN', 'PEC', 'MPV'). PLN é Projeto de Lei do Congresso Nacional (diretrizes orçamentárias, orçamento, créditos).",
                    },
                    "numero": {
                        "type": "integer",
                        "description": "Número oficial da matéria (ex: 2630, 45).",
                    },
                    "ano": {
                        "type": "integer",
                        "description": "Ano de apresentação da matéria (ex: 2020, 2023).",
                    },
                    "termo_busca": {
                        "type": "string",
                        "description": "Nome popular, apelido ou tema quando não há número (ex: 'Marco Temporal', 'Reforma Tributária').",
                    },
                },
                "required": ["casa"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_ceap_spender",
            "description": "Consulta o ranking dos maiores gastadores da cota parlamentar (CEAP da Câmara ou CEAPS do Senado) em um ano de referência.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado"],
                        "description": "Casa legislativa ('camara' ou 'senado').",
                    },
                    "ano": {
                        "type": "integer",
                        "description": "Ano de referência dos gastos (ex: 2023).",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Quantidade de parlamentares no topo do ranking (padrão 1).",
                    },
                },
                "required": ["casa", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_expense_categories",
            "description": "Verifica se uma categoria ou tipo de gasto é permitido ou registrado na cota parlamentar (CEAP/CEAPS). Usar para claims sobre elegibilidade de despesas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado"],
                        "description": "Casa legislativa alvo da consulta.",
                    },
                    "incluir_exemplos": {
                        "type": "boolean",
                        "description": "Se deve incluir exemplos reais de notas e lançamentos.",
                    },
                },
                "required": ["casa"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_parliamentary_expenses",
            "description": "Consulta gastos específicos, limites monetários ou reembolsos parlamentares por categoria de despesa ou nome do parlamentar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado"],
                        "description": "Casa legislativa ('camara' ou 'senado').",
                    },
                    "ano": {
                        "type": "integer",
                        "description": "Ano de referência dos gastos.",
                    },
                    "categoria": {
                        "type": "string",
                        "description": "Categoria específica da despesa (ex: 'Combustíveis', 'Passagens Aéreas').",
                    },
                    "parlamentar_id": {
                        "type": "string",
                        "description": "ID ou nome do parlamentar se restrito a um indivíduo.",
                    },
                },
                "required": ["casa", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_member_expenses",
            "description": "Consulta quanto a cota parlamentar (CEAP/CEAPS) reembolsou a UM parlamentar específico em um ano, com total, detalhamento por categoria (combustíveis, passagens, etc.) e maiores lançamentos. É reembolso de despesa, não salário nem benefício pago em dinheiro.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado"],
                        "description": "Casa legislativa do parlamentar ('camara' para deputado, 'senado' para senador).",
                    },
                    "ano": {
                        "type": "integer",
                        "description": "Ano de referência dos gastos (ex: 2023).",
                    },
                    "parlamentar": {
                        "type": "string",
                        "description": "Nome do parlamentar exatamente como citado na alegação. Nunca invente nem deduza um nome: se a alegação não cita nenhum parlamentar, não use esta tool. É resolvido para o ID oficial antes da consulta.",
                    },
                    "uf": {
                        "type": "string",
                        "description": "Sigla do estado citada na alegação (ex: 'DF'), usada só para desambiguar homônimos.",
                    },
                    "categoria": {
                        "type": "string",
                        "description": "Categoria da despesa quando a alegação cita uma (ex: 'Combustíveis', 'Passagens Aéreas').",
                    },
                },
                "required": ["casa", "ano", "parlamentar"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_proposition_tramitation_history",
            "description": "Histórico de tramitação de uma proposição (PL, PEC, MPV...): órgãos e despachos pelos quais passou, se passou por comissão temática e a situação atual. Resolve a proposição pelo número/ano ou nome popular antes de consultar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado", "congresso"],
                        "description": "Casa legislativa da matéria ('congresso' tenta Câmara e depois Senado).",
                    },
                    "sigla_tipo": {"type": "string", "description": "Sigla do tipo formal (ex: 'PL', 'PLN', 'PEC')."},
                    "numero": {"type": "integer", "description": "Número oficial da matéria (ex: 2630, 45)."},
                    "ano": {"type": "integer", "description": "Ano de apresentação da matéria (ex: 2019)."},
                    "termo_busca": {
                        "type": "string",
                        "description": "Nome popular da matéria quando não há número (ex: 'Marco Temporal'). Nunca invente.",
                    },
                },
                "required": ["casa"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_bill_apensamentos",
            "description": "Verifica se uma proposição tramita sozinha ou apensada (anexada) a outra proposição principal. Resolve a proposição pelo número/ano ou nome popular antes de consultar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado", "congresso"],
                        "description": "Casa legislativa da matéria ('congresso' tenta Câmara e depois Senado).",
                    },
                    "sigla_tipo": {"type": "string", "description": "Sigla do tipo formal (ex: 'PL', 'PLN', 'PEC')."},
                    "numero": {"type": "integer", "description": "Número oficial da matéria (ex: 2630, 45)."},
                    "ano": {"type": "integer", "description": "Ano de apresentação da matéria (ex: 2019)."},
                    "termo_busca": {
                        "type": "string",
                        "description": "Nome popular da matéria quando não há número (ex: 'Marco Temporal'). Nunca invente.",
                    },
                },
                "required": ["casa"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_proposition_vote_result",
            "description": "Consulta o resultado e os votos nominais dos parlamentares em uma votação na Câmara ou Senado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "casa": {
                        "type": "string",
                        "enum": ["camara", "senado"],
                        "description": "Casa onde ocorreu a votação.",
                    },
                    "id_proposicao": {
                        "type": "integer",
                        "description": "ID oficial da matéria previamente resolvido via resolve_proposition.",
                    },
                    "ano": {
                        "type": "integer",
                        "description": "Ano em que ocorreu a deliberação em Plenário.",
                    },
                },
                "required": ["casa"],
            },
        },
    },
]

_TOPIC_HINTS = (
    "calculo_cota_por_uf (o valor da cota parlamentar varia por UF), "
    "sabatina_stf (como o Senado aprova ministros do STF), "
    "votacao_simbolica (aprovação por acordo de líderes), "
    "teto_categoria_combustivel (existe teto fixo para combustível), "
    "prestacao_contas_partido (partido prestar contas ao TSE / Fundo Partidário), "
    "veto_presidencial (como o Congresso aprecia vetos), "
    "lai_gratuidade (acesso gratuito a dados públicos), "
    "cota_campanha_vs_mandato (usar a cota parlamentar em campanha), "
    "teto_gastos_campanha (divulgação do teto de gastos de campanha), "
    "cota_compra_bens (usar a cota para comprar bens/imóveis), "
    "tramitacao_comissoes (passagem de projetos por comissões temáticas), "
    "consultoria_ceaps (senadores contratarem consultoria com a verba CEAPS)"
)

TOOLS_CATALOG.extend([
    {
        "type": "function",
        "function": {
            "name": "check_institutional_rule",
            "description": (
                "Consulta a base normativa curada para claims sobre o que é PERMITIDO ou COMO FUNCIONA "
                "um procedimento (regimento, legislação, normas da cota parlamentar e eleitorais). "
                "NÃO use para valores, rankings ou votos que aconteceram (para isso use as tools de dados). "
                f"Tópicos: {_TOPIC_HINTS}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topico": {
                        "type": "string",
                        "enum": list(INSTITUTIONAL_TOPICS),
                        "description": "Tópico normativo que melhor corresponde à claim.",
                    },
                },
                "required": ["topico"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_data_source_coverage",
            "description": (
                "Confirma se um tipo de dado público está DISPONÍVEL (e se é gratuito/público) numa fonte oficial. "
                "Usar para claims do tipo 'dá para consultar X no Portal da Transparência/TSE/Câmara'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fonte": {
                        "type": "string",
                        "enum": list(DATA_SOURCES),
                        "description": "Fonte oficial citada na claim.",
                    },
                    "tipo_dado": {
                        "type": "string",
                        "enum": list(available_data_types()),
                        "description": "Recorte do dado cuja disponibilidade se quer confirmar.",
                    },
                },
                "required": ["fonte", "tipo_dado"],
            },
        },
    },
])

_CARGOS_ELEITORAIS = ["Presidente", "Governador", "Senador", "Deputado Federal", "Deputado Estadual", "Deputado Distrital"]

TOOLS_CATALOG.extend([
    {
        "type": "function",
        "function": {
            "name": "resolve_candidate",
            "description": "Identifica um CANDIDATO de uma eleição (TSE): devolve número na urna, partido, cargo, UF e SQ_CANDIDATO. Usar SOMENTE quando a claim é sobre QUEM é o candidato (número, partido, cargo). NÃO use para resultado, votos, situação, patrimônio, redes sociais ou campanha: as tools de candidato já resolvem o nome sozinhas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_busca": {"type": "string", "description": "Nome de urna ou civil do candidato (ex: 'Lula', 'Jair Bolsonaro')."},
                    "ano": {"type": "integer", "description": "Ano da eleição citado na claim (ex: 2022). NÃO invente: só se a claim disser."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa (2 letras), para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_busca", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_election_result",
            "description": "Resultado oficial de uma eleição (TSE): ranking de votos válidos de um cargo em um ano e turno, e quem foi eleito. Usar para 'quem ganhou', 'quem ficou em segundo', 'total de votos do cargo'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "turno": {"type": "integer", "description": "1 ou 2. NÃO invente: se a claim não diz o turno, deixe vazio. Deputados e senadores só têm 1º turno: o sistema completa."},
                    "uf": {"type": "string", "description": "UF da disputa (obrigatória para Governador, Senador e Deputados)."},
                    "top_n": {"type": "integer", "description": "Quantos candidatos listar (padrão 10)."},
                },
                "required": ["cargo", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_candidate_votes",
            "description": "Votos de um CANDIDATO específico (TSE) em um ano e turno: votos válidos, percentual, posição e situação (eleito ou não). Usar para 'fulano teve X votos', 'fulano foi eleito'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "turno": {"type": "integer", "description": "1 ou 2. NÃO invente: deixe vazio se a claim não diz. Deputados e senadores só têm 1º turno: o sistema completa."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_candidate_status",
            "description": "Situação da candidatura de um CANDIDATO no TSE (deferida, indeferida, renúncia, cancelada, cassada) e se foi eleito em cada turno. Usar para 'fulano teve a candidatura indeferida', 'fulano foi eleito'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_disqualification_motive",
            "description": "Motivos de indeferimento ou cassação da candidatura de um CANDIDATO registrados no TSE (ex.: Ficha Limpa, ausência de requisito). Usar para 'por que fulano foi barrado/inelegível'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_candidate_profile",
            "description": "Perfil declarado de um CANDIDATO ao TSE: gênero, grau de instrução, estado civil, cor/raça, ocupação, naturalidade, idade na posse, reeleição. Usar para claims sobre escolaridade, profissão ou perfil do candidato.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_candidate_assets",
            "description": "Bens declarados por um CANDIDATO ao TSE: total, quantidade, composição por tipo e maior bem. Usar para claims sobre patrimônio ('declarou R$ X em bens').",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_cash_and_special_assets",
            "description": "Dinheiro em espécie e bens especiais (aeronave, embarcação, joias, ouro) declarados por um CANDIDATO ao TSE. Usar para claims sobre dinheiro vivo, avião, barco ou joias declarados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_official_social_media",
            "description": "Links de redes sociais que um CANDIDATO registrou no TSE. Usar para claims sobre perfil oficial; informe 'termo' (perfil ou URL) para checar se foi registrado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                    "termo": {"type": "string", "description": "Perfil ou endereço citado na claim (ex: '@lulaoficial'), para checar se o candidato o registrou."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_campaign_finances",
            "description": "Prestação de contas de campanha de um CANDIDATO no TSE: total de receitas, despesas contratadas e despesas pagas, com composição por origem. Usar para 'fulano gastou/arrecadou R$ X na campanha'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_candidato": {"type": "string", "description": "Nome de urna ou civil do candidato (resolvido pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_campaign_finances",
            "description": "Ranking de candidatos de um cargo por gasto ou arrecadação de campanha (TSE). Usar para 'quem mais gastou/arrecadou na campanha para presidente/governador'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "metrica": {"type": "string", "enum": ["receitas", "despesas_contratadas"], "description": "'despesas_contratadas' para gasto (padrão); 'receitas' para arrecadação."},
                    "uf": {"type": "string", "description": "UF da disputa, se a claim restringir a um estado."},
                    "top_n": {"type": "integer", "description": "Quantos candidatos listar (padrão 5)."},
                },
                "required": ["cargo", "ano"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_candidates",
            "description": "Compara DOIS A QUATRO candidatos do TSE numa mesma métrica: votos válidos (exige turno), patrimônio declarado, receitas ou despesas contratadas de campanha. Usar para 'fulano teve mais votos/gastou mais/declarou mais que sicrano'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidatos": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4, "description": "Nomes de urna ou civis dos candidatos citados na claim (os nomes são resolvidos pelo sistema antes da consulta)."},
                    "ano": {"type": "integer", "description": "Ano da eleição (ex: 2022). NÃO invente."},
                    "metrica": {"type": "string", "enum": ["votos_validos", "patrimonio", "receitas", "despesas_contratadas"], "description": "O que comparar. 'despesas_contratadas' é o gasto de campanha."},
                    "turno": {"type": "integer", "description": "1 ou 2; obrigatório só para votos_validos. NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                },
                "required": ["candidatos", "ano", "metrica"],
            },
        },
    },
])

ROUTER_SYSTEM_PROMPT = (
    "Você é o Agente Roteador do sistema de fact-checking político brasileiro.\n"
    "Seu papel é analisar a alegação (claim) fornecida e escolher a ferramenta (tool) "
    "mais adequada do catálogo para iniciar a coleta de evidências primárias.\n\n"
    "⚠️ REGRA DE OURO (Princípio II da Constituição - Resolução Canônica Obrigatória):\n"
    "- NUNCA chame ferramentas de votações nominais diretamente com nomes em texto livre.\n"
    "- Se a alegação cita uma proposição legislativa formal (PL, PLP, PLN, PEC, MPV, PDL) ou nome popular de matéria "
    "(ex: 'PEC da Reforma Tributária', 'Marco Temporal', 'PL das Fake News'), você DEVE chamar OBRIGATORIAMENTE 'resolve_proposition' primeiro para obter o ID oficial.\n"
    "  Numeração no formato 'número/ano' (ex: 'PLN 2/2025' = sigla 'PLN', numero 2, ano 2025) é proposição legislativa, não eleição nem campanha: use 'resolve_proposition' (casa 'congresso' para PLN, LDO e LOA).\n"
    "- Se a alegação cita o nome de um político/parlamentar para checar dados individuais, você DEVE chamar 'resolve_politician' primeiro para obter o identificador oficial.\n"
    "  ⚠️ ATENÇÃO PARA 'resolve_politician': Passe APENAS 'nome_busca' com o nome. NUNCA passe 'uf' ou 'cargo' se a alegação estiver justamente afirmando de qual estado ou cargo ele é (ex: 'Nikolas Ferreira é deputado de Distrito Federal'). Se passar 'uf': 'DF', a ferramenta buscará um Nikolas no DF, não achará e gerará um falso INCONCLUSIVO! Busque pelo nome para obter o estado real (MG) e permitir ao julgador cravar FALSO.\n"
    "- Se a alegação pergunta sobre ranking de gastos ou 'quem mais gastou a cota (CEAP/CEAPS)', utilize 'get_top_ceap_spender'.\n"
    "- Se a alegação questiona se um tipo de gasto é permitido ou elegível (ex: consultoria, combustível), utilize 'list_expense_categories'.\n"
    "- Se a alegação pergunta quanto um parlamentar ESPECÍFICO gastou ou teve reembolsado da cota (ex: combustível, passagens, \"vale-combustível\"), utilize 'get_member_expenses' com o nome em 'parlamentar', a sigla do estado em 'uf' quando citada e SEMPRE a 'categoria' quando a alegação citar um tipo de gasto (\"vale-combustível\", gasolina e combustível = 'Combustíveis'; passagem = 'Passagens Aéreas'). A cota reembolsa despesas, não paga salário nem vale em dinheiro.\n"
    "- Se a alegação trata da TRAMITAÇÃO de uma proposição (por quais comissões passou, em que fase está, onde está parada), utilize 'get_proposition_tramitation_history'; se pergunta se está APENSADA a outra, 'check_bill_apensamentos'. Passe a sigla, o número e o ano citados (ou o nome popular).\n"
    "- Se a alegação cita limites monetários numéricos de gastos (ex: 'R$ 500 por mês'), utilize 'check_parliamentary_expenses'.\n"
    "- Se a alegação trata do que é PERMITIDO ou de COMO FUNCIONA um procedimento (regra, regimento, lei), utilize 'check_institutional_rule' com o tópico mais próximo. "
    "Regras e normas NÃO são resolvidas com tools de dados.\n"
    "- Se a alegação afirma que um dado público pode (ou não) ser consultado numa fonte oficial (Portal da Transparência, TSE, Câmara), utilize 'check_data_source_coverage'.\n"
    "- Se a alegação trata do RESULTADO de uma eleição (quem ganhou, total de votos de um cargo, ranking), utilize 'get_election_result'; "
    "se trata dos votos ou da eleição de um CANDIDATO específico, utilize 'get_candidate_votes' (o nome é resolvido pelo sistema; use 'resolve_candidate' só para identificar o candidato). "
    "Para a SITUAÇÃO da candidatura (deferida, indeferida, renúncia, cassada) utilize 'check_candidate_status'; para o MOTIVO de um indeferimento ou cassação, 'check_disqualification_motive' (não precisam de turno). "
    "Para PERFIL do candidato (escolaridade, profissão, naturalidade) utilize 'check_candidate_profile'; para PATRIMÔNIO declarado, 'get_candidate_assets'; "
    "para dinheiro em espécie e bens como aeronave, embarcação ou joias, 'check_cash_and_special_assets'; para perfis de redes sociais registrados no TSE, 'verify_official_social_media' (com 'termo'). Nenhuma precisa de turno.\n"
    "Para GASTO ou ARRECADAÇÃO de campanha de um candidato utilize 'get_campaign_finances'; para o ranking de quem mais gastou ou arrecadou num cargo, 'get_top_campaign_finances' (gasto = 'despesas_contratadas'). Não precisam de turno. "
    "Gastos da cota parlamentar (CEAP) são outra coisa: usam as tools de cota.\n"
    "Candidatos de ELEIÇÃO (resultado, votos, situação, patrimônio, campanha) usam as tools de candidato do TSE: NUNCA use 'resolve_politician' para candidato de eleição, "
    "ela vale só para parlamentar em mandato (Câmara/Senado). Para 'quem mais gastou/arrecadou' num cargo use 'get_top_campaign_finances' (uma única tool por alegação).\n"
    "Para COMPARAR candidatos nomeados (quem teve mais votos, gastou, arrecadou ou declarou mais patrimônio) utilize 'compare_candidates' com todos os nomes da alegação; "
    "ela faz a comparação inteira numa só chamada.\n"
    "NÃO invente ano nem turno: se a alegação não diz o ano ('na última eleição') ou o turno, deixe o parâmetro vazio, para que a evidência seja INCONCLUSIVO. "
    "Se a alegação é sobre o resultado da eleição de 2026, chame mesmo assim a tool de resultado com ano 2026: o sistema informa que os dados abertos do TSE ainda não foram atualizados. Votos de eleição são do TSE; votos em plenário do Congresso são das tools de votação.\n"
    "Extraia todos os parâmetros possíveis (casa, número, ano, sigla, estado/UF) diretamente da frase."
)
