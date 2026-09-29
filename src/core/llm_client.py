"""Cliente de inferência LLM com suporte a múltiplos provedores e contingência automática."""

import logging
import os
from typing import Optional, Set
import httpx
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env caso exista
load_dotenv()

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("LLMClient")


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
