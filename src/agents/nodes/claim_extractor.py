"""Nó Extrator de Alegações Atômicas (Claim Extractor).

Atende aos critérios da Task 4.2:
- Decomposição do texto bruto de notícias em alegações atômicas, concretas e verificáveis.
- Filtragem de opiniões, adjetivações retóricas e editoriais.
- Prompt com diretrizes estritas para checagem contra dados públicos (gastos, votações e alegações factuais).
- Saída estritamente compatível com o schema list[AtomicClaim] contendo no máximo 5 itens.
- Retorno de lista vazia para notícias sem alegações verificáveis ou falhas de inferência, sem quebrar o fluxo.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

from src.core.llm_client import LLMClient
from src.schemas.claims import AtomicClaim

logger = logging.getLogger("Agents.Nodes.ClaimExtractor")

CLAIM_EXTRACTOR_SYSTEM_PROMPT = """Você é um especialista em fact-checking político brasileiro e análise de alegações factuais.
Sua missão é analisar o texto de uma notícia e decompor seus fatos centrais em uma lista de até 5 alegações atômicas, concretas e factualmente verificáveis contra dados públicos oficiais (Câmara dos Deputados, Senado Federal, TSE e Portal da Transparência).

DIRETRIZES ESTRITAS DE EXTRAÇÃO:

1. O QUE DEVE SER EXTRAÍDO (Critérios de Inclusão):
- Afirmações factuais concretas, precisas e objetivas sobre:
  * GASTOS PÚBLICOS: uso da cota parlamentar (CEAP/CEAPS), despesas de gabinete, diárias, passagens aéreas, contratos e gastos eleitorais informados ao TSE.
  * ATIVIDADE LEGISLATIVA E VOTAÇÕES: votos nominais de parlamentares em PECs e projetos de lei, autoria de proposições, aprovação ou rejeição de matérias em plenário/comissões, presença ou ausência em sessões.
  * PATRIMÔNIO E CANDIDATURAS: declaração de bens e patrimônio de candidatos e políticos junto à Justiça Eleitoral.
  * REGRAS INSTITUCIONAIS: normas regimentais da Câmara, Senado e legislação eleitoral/administrativa.
- Decomposição atômica: cada afirmação deve ser autocontida, com apenas um fato verificável isolado.
- Manter nomes de parlamentares, partidos, órgãos oficiais, números de proposições e valores numéricos/datas quando citados.

2. O QUE DEVE SER FILTRADO E EXCLUÍDO (Critérios de Exclusão):
- Opiniões, julgamentos subjetivos e editoriais ("postura vergonhosa", "parlamentar brilhante", "governo desastroso").
- Adjetivações retóricas, ironias, metáforas e declarações de sentimentos/intenções ("ficou irritado", "planeja fazer").
- Boatos sem fundamentação oficial, especulações de bastidores ou comentários genéricos de redes sociais.
- Alegações vagas, genéricas ou subespecificadas sem âncora factual ("gastou muito", "faltou a várias sessões").
- Eventos futuros ou previsões ("o Congresso deve votar em breve").

3. FORMATO OBRIGATÓRIO DA SAÍDA:
- Retorne EXCLUSIVAMENTE um objeto JSON válido, sem texto conversacional antes ou depois:
{
  "claims": [
    {
      "claim": "Texto conciso, neutro e atômico da afirmação factual",
      "category": "GASTOS" | "VOTACOES" | "PATRIMONIO" | "INSTITUCIONAL" | "OUTRO",
      "target_entity": "Nome do parlamentar ou órgão público alvo",
      "context": "Citação breve ou trecho da notícia de onde a afirmação foi extraída"
    }
  ]
}

- A lista 'claims' deve conter no MÁXIMO 5 itens (selecione as 5 alegações mais relevantes e checáveis).
- Se a notícia não contiver nenhuma alegação factual verificável contra dados públicos (por exemplo, for um texto de opinião pura ou editorial retórico), retorne obrigatoriamente:
{
  "claims": []
}
"""


def _parse_llm_json_response(raw_response: str) -> List[Dict[str, Any]]:
    """Extrai e decodifica a lista de alegações a partir da resposta textual do LLM.

    Trata casos com blocos de markdown (```json ... ```), texto adicional
    e formatos alternativos de JSON.
    """
    if not raw_response or not raw_response.strip():
        return []

    text = raw_response.strip()

    # 1. Remove blocos de código markdown se existirem
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1).strip()

    # 2. Tenta decodificação direta
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "claims" in data and isinstance(data["claims"], list):
            return data["claims"]
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 3. Tenta localizar objeto JSON contendo "claims" via Regex
    obj_match = re.search(r"\{\s*\"claims\"\s*:\s*\[[\s\S]*?\]\s*\}", text)
    if obj_match:
        try:
            data = json.loads(obj_match.group(0))
            if isinstance(data, dict) and isinstance(data.get("claims"), list):
                return data["claims"]
        except json.JSONDecodeError:
            pass

    # 4. Tenta localizar lista JSON direta via Regex
    list_match = re.search(r"\[\s*\{[\s\S]*?\}\s*\]", text)
    if list_match:
        try:
            data = json.loads(list_match.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    logger.warning("Não foi possível decodificar JSON válido da resposta do LLM: %s", raw_response[:200])
    return []


class ClaimExtractor:
    """Componente desacoplado para extração e atomicização de alegações factuais."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        max_claims: int = 5,
    ):
        """Inicializa o extrator com cliente LLM e teto de alegações."""
        self.llm_client = llm_client or LLMClient()
        self.max_claims = max(1, max_claims)

    def extract(self, text: str) -> List[AtomicClaim]:
        """Extrai até max_claims alegações atômicas e verificáveis de um texto jornalístico.

        Args:
            text: Texto limpo ou corpo editorial da notícia.

        Returns:
            Lista contendo até max_claims instâncias de AtomicClaim.
            Retorna lista vazia caso o texto seja nulo/vazio, opinativo ou sem fatos verificáveis.
        """
        if not text or not isinstance(text, str) or not text.strip():
            logger.info("Texto de notícia vazio ou não fornecido. Retornando lista vazia.")
            return []

        user_content = f"TEXTO DA NOTÍCIA PARA EXTRAÇÃO:\n\"\"\"\n{text.strip()}\n\"\"\"\n\nRESPOSTA JSON:"
        prompt = f"{CLAIM_EXTRACTOR_SYSTEM_PROMPT}\n\n{user_content}"

        try:
            raw_response = self.llm_client.generate(prompt)
            raw_claims = _parse_llm_json_response(raw_response)

            atomic_claims: List[AtomicClaim] = []
            for item in raw_claims:
                try:
                    if isinstance(item, dict):
                        claim_obj = AtomicClaim.model_validate(item)
                    elif isinstance(item, str):
                        claim_obj = AtomicClaim(claim=item)
                    else:
                        continue
                    atomic_claims.append(claim_obj)
                except Exception as val_err:
                    logger.debug("Falha ao validar item de alegação: %s (%s)", item, val_err)
                    continue

                if len(atomic_claims) >= self.max_claims:
                    break

            return atomic_claims

        except Exception as e:
            logger.error("Falha durante execução do extrator de alegações: %s", e)
            # Em caso de erro do LLM, degrada de forma segura retornando lista vazia
            return []


def claim_extractor_node(
    input_data: Union[str, Dict[str, Any], None] = None,
    *,
    text: Optional[str] = None,
    state: Optional[Dict[str, Any]] = None,
    llm_client: Optional[LLMClient] = None,
    max_claims: int = 5,
) -> List[AtomicClaim]:
    """Nó do agente responsável por extrair alegações atômicas de uma matéria jornalística.

    Compatível com entradas diretas em string ou dicionários de estado de pipelines
    (ex.: saídas geradas por `extract_article` da Task 4.1).

    Args:
        input_data: Texto da notícia ou dicionário de estado contendo o texto.
        text: Parâmetro nomeado opcional contendo o texto da notícia.
        state: Parâmetro nomeado opcional contendo o dicionário de estado.
        llm_client: Instância opcional de LLMClient para injeção de dependência/testes.
        max_claims: Quantidade máxima de alegações atômicas a extrair (padrão: 5).

    Returns:
        Lista com até 5 objetos AtomicClaim, ou [] se nenhuma alegação verificável for encontrada.
    """
    raw_text: Optional[str] = None
    target_state_dict: Optional[Dict[str, Any]] = None

    if text is not None and isinstance(text, str):
        raw_text = text
    elif state is not None and isinstance(state, dict):
        target_state_dict = state
        raw_text = (
            state.get("clean_text")
            or state.get("text")
            or state.get("raw_text")
            or state.get("article_text")
            or state.get("content")
            or state.get("news_text")
        )
    elif isinstance(input_data, str):
        raw_text = input_data
    elif isinstance(input_data, dict):
        target_state_dict = input_data
        raw_text = (
            input_data.get("clean_text")
            or input_data.get("text")
            or input_data.get("raw_text")
            or input_data.get("article_text")
            or input_data.get("content")
            or input_data.get("news_text")
        )

    extractor = ClaimExtractor(llm_client=llm_client, max_claims=max_claims)
    claims = extractor.extract(raw_text or "")

    # Se a entrada foi um dicionário de estado, enriquece com as alegações extraídas
    if target_state_dict is not None:
        target_state_dict["atomic_claims"] = claims
        target_state_dict["claims"] = claims

    return claims
