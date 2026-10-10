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
            "description": "Identifica formalmente matérias legislativas (PL, PEC, MPV, PDL) ou busca por nome popular na Câmara, Senado ou Congresso.",
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
                        "description": "Sigla do tipo formal (ex: 'PL', 'PEC', 'MPV').",
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
            "description": "Resolve o nome de um CANDIDATO de uma eleição (TSE) para o identificador oficial (SQ_CANDIDATO). Usar quando a claim cita um candidato de um ano de eleição específico.",
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
                    "turno": {"type": "integer", "description": "1 ou 2. NÃO invente: se a claim não diz o turno, deixe vazio."},
                    "uf": {"type": "string", "description": "UF da disputa (obrigatória para Governador, Senador e Deputados)."},
                    "top_n": {"type": "integer", "description": "Quantos candidatos listar (padrão 10)."},
                },
                "required": ["cargo", "ano", "turno"],
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
                    "turno": {"type": "integer", "description": "1 ou 2. NÃO invente."},
                    "cargo": {"type": "string", "enum": _CARGOS_ELEITORAIS, "description": "Cargo disputado, se a claim disser."},
                    "uf": {"type": "string", "description": "UF da disputa, para desambiguar homônimos."},
                    "numero": {"type": "integer", "description": "Número do candidato na urna, se citado."},
                },
                "required": ["nome_candidato", "ano", "turno"],
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
])

ROUTER_SYSTEM_PROMPT = (
    "Você é o Agente Roteador do sistema de fact-checking político brasileiro.\n"
    "Seu papel é analisar a alegação (claim) fornecida e escolher a ferramenta (tool) "
    "mais adequada do catálogo para iniciar a coleta de evidências primárias.\n\n"
    "⚠️ REGRA DE OURO (Princípio II da Constituição - Resolução Canônica Obrigatória):\n"
    "- NUNCA chame ferramentas de votações nominais diretamente com nomes em texto livre.\n"
    "- Se a alegação cita uma proposição legislativa formal (PL, PEC, MPV) ou nome popular de matéria "
    "(ex: 'PEC da Reforma Tributária', 'Marco Temporal', 'PL das Fake News'), você DEVE chamar OBRIGATORIAMENTE 'resolve_proposition' primeiro para obter o ID oficial.\n"
    "- Se a alegação cita o nome de um político/parlamentar para checar dados individuais, você DEVE chamar 'resolve_politician' primeiro para obter o identificador oficial.\n"
    "  ⚠️ ATENÇÃO PARA 'resolve_politician': Passe APENAS 'nome_busca' com o nome. NUNCA passe 'uf' ou 'cargo' se a alegação estiver justamente afirmando de qual estado ou cargo ele é (ex: 'Nikolas Ferreira é deputado de Distrito Federal'). Se passar 'uf': 'DF', a ferramenta buscará um Nikolas no DF, não achará e gerará um falso INCONCLUSIVO! Busque pelo nome para obter o estado real (MG) e permitir ao julgador cravar FALSO.\n"
    "- Se a alegação pergunta sobre ranking de gastos ou 'quem mais gastou a cota (CEAP/CEAPS)', utilize 'get_top_ceap_spender'.\n"
    "- Se a alegação questiona se um tipo de gasto é permitido ou elegível (ex: consultoria, combustível), utilize 'list_expense_categories'.\n"
    "- Se a alegação cita limites monetários numéricos de gastos (ex: 'R$ 500 por mês'), utilize 'check_parliamentary_expenses'.\n"
    "- Se a alegação trata do que é PERMITIDO ou de COMO FUNCIONA um procedimento (regra, regimento, lei), utilize 'check_institutional_rule' com o tópico mais próximo. "
    "Regras e normas NÃO são resolvidas com tools de dados.\n"
    "- Se a alegação afirma que um dado público pode (ou não) ser consultado numa fonte oficial (Portal da Transparência, TSE, Câmara), utilize 'check_data_source_coverage'.\n"
    "- Se a alegação trata do RESULTADO de uma eleição (quem ganhou, total de votos de um cargo, ranking), utilize 'get_election_result'; "
    "se trata dos votos ou da eleição de um CANDIDATO específico, utilize 'get_candidate_votes' (o nome é resolvido pelo sistema; use 'resolve_candidate' só para identificar o candidato). "
    "Para a SITUAÇÃO da candidatura (deferida, indeferida, renúncia, cassada) utilize 'check_candidate_status'; para o MOTIVO de um indeferimento ou cassação, 'check_disqualification_motive' (não precisam de turno). "
    "NÃO invente ano nem turno: se a alegação não diz o ano ('na última eleição') ou o turno, deixe o parâmetro vazio, para que a evidência seja INCONCLUSIVO. "
    "Se a alegação é sobre o resultado da eleição de 2026, chame mesmo assim a tool de resultado com ano 2026: o sistema informa que os dados abertos do TSE ainda não foram atualizados. Votos de eleição são do TSE; votos em plenário do Congresso são das tools de votação.\n"
    "Extraia todos os parâmetros possíveis (casa, número, ano, sigla, estado/UF) diretamente da frase."
)
