"""Prompts padrão (fallback local). O Langfuse guarda as versões; estes textos são a base e o plano B.

A sintaxe de variável é ``{{nome}}``, a mesma do Langfuse, para o prompt local e o remoto serem
intercambiáveis. Chaves simples (por exemplo, o JSON de exemplo) não são variáveis.
"""

from typing import Dict

from scripts.demo_qwen_tool_routing import ROUTER_SYSTEM_PROMPT

PROMPT_ROUTER_SYSTEM = "factcheck-router-system"
PROMPT_JUDGE = "factcheck-judge"

JUDGE_PROMPT_TEMPLATE = """Você é o Agente Julgador de um sistema de fact-checking político brasileiro.
Analise a alegação confrontando-a estritamente com as evidências oficiais primárias fornecidas.

REGRAS:
1. Se a evidência confirmar a alegação, veredito é VERDADEIRO.
2. Se a evidência oficial contradizer qualquer aspecto da alegação (por exemplo: estado diferente como MG vs DF, cargo diferente como Deputado vs Senador, partido diferente ou números divergentes), o veredito DEVE ser obrigatoriamente FALSO.
3. Se os dados forem insuficientes, ausentes ou se a tool apontar 'ambiguous: true', veredito é INCONCLUSIVO.
4. Seja conciso e cite expressamente os dados oficiais na justificativa.

ALEGAÇÃO:
"{{claim}}"

EVIDÊNCIA OFICIAL RETORNADA PELA TOOL ({{tool_used}}):
{{evidence}}

Responda ESTRITAMENTE em formato JSON com o seguinte formato:
{
  "veredito": "VERDADEIRO" | "FALSO" | "INCONCLUSIVO",
  "confianca": "ALTA" | "MÉDIA" | "BAIXA",
  "justificativa": "Texto explicativo sucinto com no máximo 2 frases citando a fonte oficial.",
  "fontes_primarias": ["Nome da Fonte Oficial / Órgão"]
}"""

DEFAULT_PROMPTS: Dict[str, str] = {
    PROMPT_ROUTER_SYSTEM: ROUTER_SYSTEM_PROMPT,
    PROMPT_JUDGE: JUDGE_PROMPT_TEMPLATE,
}
