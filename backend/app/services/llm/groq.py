from app.core.logger import logger
from app.services.llm.base import (
    ChatMessage,
    LLMError,
    LLMProviderError,
    LLMRequestError,
    LLMResponse,
)

try:
    from groq import Groq
except ImportError:  # pragma: no cover - dependency always installed
    Groq = None


_NON_RETRYABLE_CODES = {400, 404, 422}


class GroqProvider:
    """Groq adapter built on the official groq SDK (OpenAI-compatible)."""

    name = "groq"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        client=None,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self._client = client

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            if Groq is None:
                raise LLMProviderError("groq package is not installed")
            self._client = Groq(
                api_key=self.api_key, timeout=self.timeout_seconds
            )
        return self._client

    @staticmethod
    def _map_error(exc: Exception) -> Exception:
        status = getattr(exc, "status_code", None)
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None

        if status in _NON_RETRYABLE_CODES:
            return LLMRequestError(f"Groq rejected the request (HTTP {status})")
        if status is not None:
            return LLMProviderError(f"Groq provider error (HTTP {status})")
        name = type(exc).__name__.lower()
        if "timeout" in name or "connection" in name:
            return LLMProviderError("Groq request timed out or connection failed")
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return LLMProviderError("Groq request timed out or connection failed")
        return LLMProviderError(f"Groq provider error: {type(exc).__name__}")

    def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        client = self._get_client()

        try:
            completion = client.chat.completions.create(
                model=self.model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=self.temperature,
                max_tokens=self.max_output_tokens,
                timeout=self.timeout_seconds,
            )
        except Exception as e:
            mapped = self._map_error(e)
            logger.warning(
                "Groq generation failed (%s): %s",
                type(mapped).__name__,
                mapped,
            )
            raise mapped from e

        try:
            text = completion.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as e:
            raise LLMRequestError("Groq returned a malformed response") from e

        if not text:
            raise LLMRequestError("Groq returned an empty response")

        return LLMResponse(text=text, provider=self.name, model=self.model)
