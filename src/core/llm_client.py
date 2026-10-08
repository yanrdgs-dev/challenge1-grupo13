"""Cliente de inferência LLM com suporte a múltiplos provedores e contingência automática."""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import httpx
from dotenv import load_dotenv

from src.observability import tracing

# Carrega as variáveis do arquivo .env caso exista
load_dotenv()

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("LLMClient")


@dataclass
class ChatResult:
    """Resultado normalizado de uma chamada de chat, independente do provedor."""

    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Optional[int]] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    used_fallback: bool = False


class LLMClient:
    """Cliente desacoplado para inferência LLM com fallback automático.

    Permite chaveamento transparente entre inferência local (Ollama)
    e provedores em nuvem (Groq ou OpenAI).
    """

    SUPPORTED_PROVIDERS: Set[str] = {"ollama", "groq", "openai"}

    def __init__(
        self,
        primary_provider: Optional[str] = None,
        fallback_provider: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """Inicializa o cliente com base em parâmetros ou variáveis de ambiente.

        Args:
            primary_provider: Provedor principal ('ollama', 'groq' ou 'openai').
            fallback_provider: Provedor de contingência (ou None/'' para desabilitar).
            timeout: Tempo limite para requisições em segundos.
        """
        self.primary_provider = (
            primary_provider or os.getenv("LLM_PROVIDER", "ollama")
        ).strip().lower()

        raw_fallback = (
            fallback_provider
            if fallback_provider is not None
            else os.getenv("FALLBACK_PROVIDER", "groq")
        )
        self.fallback_provider = raw_fallback.strip().lower() if raw_fallback else None

        env_timeout = os.getenv("LLM_TIMEOUT", "3.0")
        try:
            self.timeout = float(timeout if timeout is not None else env_timeout)
        except ValueError:
            self.timeout = 3.0

        # Timeout estendido para provedores em nuvem (contingência)
        env_fallback_timeout = os.getenv("FALLBACK_TIMEOUT", "10.0")
        try:
            self.fallback_timeout = float(env_fallback_timeout)
        except ValueError:
            self.fallback_timeout = 10.0

    def generate(self, prompt: str) -> str:
        """Executa a inferência no provedor configurado e aplica fallback em caso de falha.

        Args:
            prompt: Texto do prompt enviado para o modelo.

        Returns:
            Texto gerado pelo modelo LLM.

        Raises:
            ValueError: Se o prompt for inválido.
            RuntimeError: Quando a inferência e o fallback falharem.
        """
        if not prompt or not isinstance(prompt, str):
            raise ValueError("O prompt deve ser uma string não vazia.")

        try:
            logger.info("Executando inferência via: %s", self.primary_provider.upper())
            return self._call_provider(self.primary_provider, prompt, timeout=self.timeout)
        except Exception as e:
            logger.warning(
                "Falha no provedor '%s': %s",
                self.primary_provider,
                e,
            )

            # Se houver fallback configurado e for diferente do primário, tenta contingência
            if self.fallback_provider and self.fallback_provider != self.primary_provider:
                logger.info(
                    "Ativando contingência nuvem via: %s",
                    self.fallback_provider.upper(),
                )
                try:
                    return self._call_provider(
                        self.fallback_provider,
                        prompt,
                        timeout=self.fallback_timeout,
                    )
                except Exception as fallback_err:
                    logger.error(
                        "Erro crítico em ambos os provedores (primário: %s, fallback: %s): %s",
                        self.primary_provider,
                        self.fallback_provider,
                        fallback_err,
                    )
                    raise RuntimeError(
                        f"Falha total nos serviços de LLM: provedor '{self.primary_provider}' "
                        f"({e}) e fallback '{self.fallback_provider}' ({fallback_err}) falharam."
                    ) from fallback_err
            else:
                raise RuntimeError(
                    f"Falha no provedor '{self.primary_provider}' e nenhum fallback disponível: {e}"
                ) from e

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        json_mode: bool = False,
    ) -> ChatResult:
        """Executa um chat com mensagens (e tools opcionais), com fallback automático.

        Args:
            messages: Mensagens no formato role/content.
            tools: Catálogo de tools para function calling (opcional).
            model: Modelo a usar no provedor primário (o fallback usa o modelo do seu .env).
            json_mode: Se True, solicita saída JSON ao provedor.

        Returns:
            ChatResult com texto, tool calls normalizadas, uso de tokens e metadados.

        Raises:
            ValueError: Se a lista de mensagens for vazia.
            RuntimeError: Quando a inferência e o fallback falharem.
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("messages deve ser uma lista não vazia.")

        try:
            return self._chat_provider(
                self.primary_provider, messages, tools, model, json_mode, self.timeout
            )
        except Exception as e:
            logger.warning("Falha no provedor '%s' (chat): %s", self.primary_provider, e)
            if self.fallback_provider and self.fallback_provider != self.primary_provider:
                try:
                    result = self._chat_provider(
                        self.fallback_provider, messages, tools, None, json_mode,
                        self.fallback_timeout, is_fallback=True,
                    )
                    result.used_fallback = True
                    return result
                except Exception as fallback_err:
                    raise RuntimeError(
                        f"Falha total nos serviços de LLM: provedor '{self.primary_provider}' "
                        f"({e}) e fallback '{self.fallback_provider}' ({fallback_err}) falharam."
                    ) from fallback_err
            raise RuntimeError(
                f"Falha no provedor '{self.primary_provider}' e nenhum fallback disponível: {e}"
            ) from e

    def _default_model(self, provider: str) -> str:
        """Modelo configurado no ambiente para o provedor."""
        if provider == "ollama":
            return os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        if provider == "groq":
            return os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _chat_provider(
        self,
        provider: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        model: Optional[str],
        json_mode: bool,
        timeout: float,
        is_fallback: bool = False,
    ) -> ChatResult:
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Provedor desconhecido: '{provider}'. Provedores suportados: {sorted(self.SUPPORTED_PROVIDERS)}"
            )

        # Só o Ollama aceita o modelo informado; Groq/OpenAI usam o modelo do ambiente.
        planned_model = (model if provider == "ollama" and model else None) or self._default_model(provider)
        base_metadata = {
            "provider": provider,
            "fallback": is_fallback,
            "json_mode": json_mode,
            "with_tools": bool(tools),
        }

        with tracing.observation(
            "llm.chat",
            as_type="generation",
            model=planned_model,
            input=messages,
            metadata=base_metadata,
            model_parameters={"temperature": self._temperature()},
        ) as generation:
            start = time.perf_counter()
            try:
                if provider == "ollama":
                    result = self._chat_ollama(messages, tools, planned_model, json_mode, timeout)
                else:
                    result = self._chat_openai_compatible(provider, messages, tools, json_mode, timeout)
            except Exception as exc:
                generation.update(level="ERROR", status_message=str(exc))
                raise

            result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            usage = {
                key: value
                for key, value in (
                    ("input", result.usage.get("input_tokens")),
                    ("output", result.usage.get("output_tokens")),
                )
                if value is not None
            }
            update: Dict[str, Any] = {
                "model": result.model,
                "output": result.tool_calls or result.content,
                "metadata": {**base_metadata, "latency_ms": result.latency_ms},
            }
            if usage:
                update["usage_details"] = usage
            generation.update(**update)
            return result

    def _chat_ollama(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        model: str,
        json_mode: bool,
        timeout: float,
    ) -> ChatResult:
        """Chat via API do Ollama (/api/chat)."""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self._temperature()},
        }
        if tools:
            body["tools"] = tools
        if json_mode:
            body["format"] = "json"
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base_url}/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()
        message = data.get("message", {})
        return ChatResult(
            content=message.get("content") or "",
            tool_calls=self._normalize_tool_calls(message.get("tool_calls")),
            usage={
                "input_tokens": data.get("prompt_eval_count"),
                "output_tokens": data.get("eval_count"),
            },
            provider="ollama",
            model=data.get("model") or model,
        )

    def _chat_openai_compatible(
        self,
        provider: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        json_mode: bool,
        timeout: float,
    ) -> ChatResult:
        """Chat via APIs compatíveis com OpenAI (Groq e OpenAI)."""
        if provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key or api_key == "sua_chave_groq_aqui":
                raise ValueError("GROQ_API_KEY não configurada ou inválida no arquivo .env")
            url = "https://api.groq.com/openai/v1/chat/completions"
            used_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key or api_key == "sua_chave_openai_aqui":
                raise ValueError("OPENAI_API_KEY não configurada ou inválida no arquivo .env")
            url = "https://api.openai.com/v1/chat/completions"
            used_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        body: Dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": self._temperature(),
        }
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return ChatResult(
            content=message.get("content") or "",
            tool_calls=self._normalize_tool_calls(message.get("tool_calls")),
            usage={
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            },
            provider=provider,
            model=data.get("model") or used_model,
        )

    @staticmethod
    def _temperature() -> float:
        """Temperatura de amostragem (``LLM_TEMPERATURE``). Padrão 0: respostas reproduzíveis."""
        try:
            return float(os.getenv("LLM_TEMPERATURE", "0"))
        except ValueError:
            return 0.0

    @staticmethod
    def _normalize_tool_calls(raw_calls: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Converte tool calls de qualquer provedor para {name, arguments(dict)}."""
        normalized: List[Dict[str, Any]] = []
        for call in raw_calls or []:
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            normalized.append({"name": fn.get("name"), "arguments": args})
        return normalized

    def _call_provider(self, provider: str, prompt: str, timeout: float) -> str:
        """Roteia a chamada para a função correspondente ao provedor.

        Args:
            provider: Identificador do provedor ('ollama', 'groq', 'openai').
            prompt: Conteúdo da mensagem do usuário.
            timeout: Tempo limite da requisição em segundos.

        Returns:
            Resposta textual da LLM.
        """
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Provedor desconhecido: '{provider}'. Provedores suportados: {sorted(self.SUPPORTED_PROVIDERS)}"
            )

        if provider == "ollama":
            return self._call_ollama(prompt, timeout)
        elif provider == "groq":
            return self._call_groq(prompt, timeout)
        elif provider == "openai":
            return self._call_openai(prompt, timeout)

        raise ValueError(f"Provedor não implementado: '{provider}'")

    def _call_ollama(self, prompt: str, timeout: float) -> str:
        """Executa inferência local via API do Ollama."""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }

        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

    def _call_groq(self, prompt: str, timeout: float) -> str:
        """Executa inferência em nuvem via API do Groq."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "sua_chave_groq_aqui":
            raise ValueError("GROQ_API_KEY não configurada ou inválida no arquivo .env")

        model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }

        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _call_openai(self, prompt: str, timeout: float) -> str:
        """Executa inferência em nuvem via API da OpenAI."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == "sua_chave_openai_aqui":
            raise ValueError("OPENAI_API_KEY não configurada ou inválida no arquivo .env")

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }

        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
