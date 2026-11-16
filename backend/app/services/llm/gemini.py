from app.core.logger import logger
from app.services.llm.base import (
    ChatMessage,
    LLMError,
    LLMProviderError,
    LLMRequestError,
    LLMResponse,
)

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover - dependency always installed
    genai = None
    genai_types = None


_NON_RETRYABLE_CODES = {400, 404, 422}


class GeminiProvider:
    """Google Gemini adapter built on the official google-genai SDK."""

    name = "gemini"

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
            if genai is None:
                raise LLMProviderError("google-genai package is not installed")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @staticmethod
    def _map_error(exc: Exception) -> Exception:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = None

        if code in _NON_RETRYABLE_CODES:
            return LLMRequestError(f"Gemini rejected the request (HTTP {code})")
        if code is not None:
            return LLMProviderError(f"Gemini provider error (HTTP {code})")
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return LLMProviderError("Gemini request timed out or connection failed")
        name = type(exc).__name__.lower()
        if "timeout" in name or "connection" in name:
            return LLMProviderError("Gemini request timed out or connection failed")
        return LLMProviderError(f"Gemini provider error: {type(exc).__name__}")

    def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        client = self._get_client()

        system_parts = [m.content for m in messages if m.role == "system"]
        contents = []
        for m in messages:
            if m.role == "system":
                continue
            role = "user" if m.role == "user" else "model"
            contents.append(
                genai_types.Content(
                    role=role, parts=[genai_types.Part(text=m.content)]
                )
            )

        config = genai_types.GenerateContentConfig(
            system_instruction="\n\n".join(system_parts) if system_parts else None,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            http_options=genai_types.HttpOptions(
                timeout=int(self.timeout_seconds * 1000)
            ),
        )

        try:
            response = client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except Exception as e:
            mapped = self._map_error(e)
            logger.warning(
                "Gemini generation failed (%s): %s",
                type(mapped).__name__,
                mapped,
            )
            raise mapped from e

        text = getattr(response, "text", None)
        if text is None:
            # e.g. blocked by safety filters; surface candidates for diagnosis
            candidates = getattr(response, "candidates", None) or []
            finish = getattr(candidates[0], "finish_reason", None) if candidates else None
            raise LLMRequestError(
                f"Gemini returned no text (finish_reason={finish})"
            )

        return LLMResponse(text=text, provider=self.name, model=self.model)
