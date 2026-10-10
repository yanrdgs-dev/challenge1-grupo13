"""Cliente de inferência LLM com suporte a múltiplos provedores e contingência automática."""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import httpx
from dotenv import load_dotenv

from src.core import provider_guard
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


class ProviderConfigError(ValueError):
    """Provedor mal configurado (chave ausente, nome desconhecido): não é indisponibilidade do serviço."""


# Provedores de nuvem no formato da OpenAI: URL, variável da chave, valor de exemplo do .env, modelo.
OPENAI_COMPATIBLE: Dict[str, Dict[str, str]] = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "placeholder": "sua_chave_groq_aqui",
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.1-8b-instant",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "key_env": "OPENAI_API_KEY",
        "placeholder": "sua_chave_openai_aqui",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
    },
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "placeholder": "sua_chave_deepseek_aqui",
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-flash",
    },
}


class LLMClient:
    """Cliente desacoplado para inferência LLM com cadeia ordenada de provedores.

    A cadeia (``LLM_PROVIDERS``, ex.: ``ollama,groq,deepseek``) é percorrida em ordem: o primeiro que
    responder vence. Cada provedor tem um disjuntor (para de ser tentado depois de falhas seguidas) e
    pode ter um teto diário de chamadas (por padrão, só o DeepSeek, que é pago). Ver ``provider_guard``.
    """

    SUPPORTED_PROVIDERS: Set[str] = {"ollama", "groq", "openai", "deepseek"}

    def __init__(
        self,
        primary_provider: Optional[str] = None,
        fallback_provider: Optional[str] = None,
        timeout: Optional[float] = None,
        providers: Optional[List[str]] = None,
    ):
        """Inicializa o cliente com base em parâmetros ou variáveis de ambiente.

        Args:
            primary_provider: Provedor principal. Se informado, a cadeia é só ele e o fallback.
            fallback_provider: Provedor de contingência (ou None/'' para desabilitar).
            timeout: Tempo limite do primeiro provedor, em segundos.
            providers: Cadeia ordenada completa (tem precedência sobre os demais).

        Sem nenhum argumento, vale ``LLM_PROVIDERS``; se ela não existir, ``LLM_PROVIDER`` + ``FALLBACK_PROVIDER``.
        """
        if providers is not None:
            chain = list(providers)
        elif primary_provider is None and fallback_provider is None and os.getenv("LLM_PROVIDERS", "").strip():
            chain = os.getenv("LLM_PROVIDERS", "").split(",")
        else:
            raw_fallback = (
                fallback_provider
                if fallback_provider is not None
                else os.getenv("FALLBACK_PROVIDER", "groq")
            )
            chain = [primary_provider or os.getenv("LLM_PROVIDER", "ollama"), raw_fallback or ""]

        self.providers: List[str] = []
        for name in chain:
            name = (name or "").strip().lower()
            if name and name not in self.providers:
                self.providers.append(name)
        if not self.providers:
            self.providers = ["ollama"]

        self.primary_provider = self.providers[0]
        self.fallback_provider = self.providers[1] if len(self.providers) > 1 else None

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

        def attempt(provider: str, index: int) -> str:
            logger.info("Executando inferência via: %s", provider.upper())
            return self._call_provider(
                provider, prompt, timeout=self.timeout if index == 0 else self.fallback_timeout
            )

        return self._run_chain(attempt)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        json_mode: bool = False,
        prompt: Any = None,
    ) -> ChatResult:
        """Executa um chat com mensagens (e tools opcionais), com fallback automático.

        Args:
            messages: Mensagens no formato role/content.
            tools: Catálogo de tools para function calling (opcional).
            model: Modelo a usar no provedor primário (o fallback usa o modelo do seu .env).
            json_mode: Se True, solicita saída JSON ao provedor.
            prompt: Cliente de prompt do Langfuse; liga a generation à versão usada (opcional).

        Returns:
            ChatResult com texto, tool calls normalizadas, uso de tokens e metadados.

        Raises:
            ValueError: Se a lista de mensagens for vazia.
            RuntimeError: Quando a inferência e o fallback falharem.
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("messages deve ser uma lista não vazia.")

        def attempt(provider: str, index: int) -> ChatResult:
            result = self._chat_provider(
                provider, messages, tools, model if index == 0 else None, json_mode,
                self.timeout if index == 0 else self.fallback_timeout,
                is_fallback=index > 0, prompt=prompt,
            )
            result.used_fallback = index > 0
            return result

        return self._run_chain(attempt)

    def _run_chain(self, attempt: Callable[[str, int], Any]) -> Any:
        """Percorre a cadeia em ordem, respeitando o teto diário e o disjuntor de cada provedor.

        Se todos os disjuntores estiverem abertos, tenta mesmo assim (falhar sem tentar é pior). Erro de
        configuração (chave ausente) passa ao próximo provedor sem contar como falha do serviço.
        """
        guards = provider_guard.guards
        errors: Dict[str, str] = {}
        skipped: List[str] = []
        attempted = False

        def call(provider: str) -> Tuple[bool, Any]:
            nonlocal attempted
            attempted = True
            breaker = guards.breaker(provider)
            guards.cap(provider).acquire()
            try:
                result = attempt(provider, self.providers.index(provider))
            except ProviderConfigError as exc:
                breaker.release_trial()
                errors[provider] = str(exc)
            except Exception as exc:
                breaker.record_failure()
                errors[provider] = str(exc)
                logger.warning("Falha no provedor '%s': %s", provider, exc)
            else:
                breaker.record_success()
                return True, result
            return False, None

        for provider in self.providers:
            if guards.cap(provider).exhausted():
                errors[provider] = "limite diário de chamadas atingido"
            elif not guards.breaker(provider).allow():
                skipped.append(provider)
                errors[provider] = "disjuntor aberto (falhas seguidas recentes)"
            else:
                ok, result = call(provider)
                if ok:
                    return result

        if not attempted:
            for provider in skipped:
                ok, result = call(provider)
                if ok:
                    return result

        raise RuntimeError(self._failure_message(errors))

    def _failure_message(self, errors: Dict[str, str]) -> str:
        if len(self.providers) == 1:
            only = self.providers[0]
            return f"Falha no provedor '{only}' e nenhum fallback disponível: {errors.get(only, 'sem detalhe')}"
        parts = [
            f"{'provedor' if i == 0 else 'fallback'} '{name}' ({errors.get(name, 'não tentado')})"
            for i, name in enumerate(self.providers)
        ]
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " e " + parts[-1]
        return f"Falha total nos serviços de LLM: {joined} falharam."

    def _default_model(self, provider: str) -> str:
        """Modelo configurado no ambiente para o provedor."""
        if provider == "ollama":
            return os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        spec = OPENAI_COMPATIBLE.get(provider)
        if spec:
            return os.getenv(spec["model_env"], spec["default_model"])
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
        prompt: Any = None,
    ) -> ChatResult:
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ProviderConfigError(
                f"Provedor desconhecido: '{provider}'. Provedores suportados: {sorted(self.SUPPORTED_PROVIDERS)}"
            )

        # Só o Ollama aceita o modelo informado; Groq, OpenAI e DeepSeek usam o modelo do ambiente.
        planned_model = (model if provider == "ollama" and model else None) or self._default_model(provider)
        base_metadata = {
            "provider": provider,
            "fallback": is_fallback,
            "json_mode": json_mode,
            "with_tools": bool(tools),
        }

        generation_kwargs: Dict[str, Any] = {}
        if prompt is not None:
            generation_kwargs["prompt"] = prompt

        with tracing.observation(
            "llm.chat",
            as_type="generation",
            model=planned_model,
            input=messages,
            metadata=base_metadata,
            model_parameters={"temperature": self._temperature()},
            **generation_kwargs,
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

    @staticmethod
    def _ollama_headers() -> Dict[str, str]:
        """Header do proxy que protege o Ollama exposto por túnel; vazio quando não há chave."""
        api_key = (os.getenv("OLLAMA_API_KEY") or "").strip()
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

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
            resp = client.post(f"{base_url}/api/chat", json=body, headers=self._ollama_headers())
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
        """Chat via APIs compatíveis com OpenAI (Groq, OpenAI e DeepSeek)."""
        spec = OPENAI_COMPATIBLE[provider]
        api_key = os.getenv(spec["key_env"])
        if not api_key or api_key == spec["placeholder"]:
            raise ProviderConfigError(f"{spec['key_env']} não configurada ou inválida no arquivo .env")
        url = spec["url"]
        used_model = os.getenv(spec["model_env"], spec["default_model"])

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
            raise ProviderConfigError(
                f"Provedor desconhecido: '{provider}'. Provedores suportados: {sorted(self.SUPPORTED_PROVIDERS)}"
            )

        if provider == "ollama":
            return self._call_ollama(prompt, timeout)
        elif provider == "groq":
            return self._call_groq(prompt, timeout)
        elif provider == "openai":
            return self._call_openai(prompt, timeout)
        elif provider == "deepseek":
            return self._call_deepseek(prompt, timeout)

        raise ProviderConfigError(f"Provedor não implementado: '{provider}'")

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
            response = client.post(
                f"{base_url}/api/generate", json=payload, headers=self._ollama_headers()
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

    def _call_groq(self, prompt: str, timeout: float) -> str:
        """Executa inferência em nuvem via API do Groq."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "sua_chave_groq_aqui":
            raise ProviderConfigError("GROQ_API_KEY não configurada ou inválida no arquivo .env")

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
            raise ProviderConfigError("OPENAI_API_KEY não configurada ou inválida no arquivo .env")

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

    def _call_deepseek(self, prompt: str, timeout: float) -> str:
        """Executa inferência em nuvem via API do DeepSeek (formato OpenAI)."""
        result = self._chat_openai_compatible(
            "deepseek", [{"role": "user", "content": prompt}], None, False, timeout
        )
        return result.content
