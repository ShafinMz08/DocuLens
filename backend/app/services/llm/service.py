import asyncio

from app.core.config import settings
from app.core.logger import logger
from app.services.llm.base import (
    ChatMessage,
    LLMError,
    LLMProviderError,
    LLMRequestError,
    LLMResponse,
)
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider


class LLMService:
    """Provider-independent LLM gateway with ordered fallback.

    Providers are tried in configuration order (primary, then fallback).
    Recoverable provider failures (rate limits, 5xx, timeouts, auth)
    advance to the next provider; request-level errors and missing
    credentials short-circuit appropriately.
    """

    _PROVIDERS = {
        "gemini": GeminiProvider,
        "groq": GroqProvider,
    }

    def __init__(self, cfg=None):
        cfg = cfg or settings
        self.providers = []

        order = [cfg.LLM_PRIMARY_PROVIDER]
        if cfg.LLM_FALLBACK_PROVIDER and cfg.LLM_FALLBACK_PROVIDER != order[0]:
            order.append(cfg.LLM_FALLBACK_PROVIDER)

        for name in order:
            cls = self._PROVIDERS.get(name)
            if cls is None:
                logger.error("Unknown LLM provider configured: %s", name)
                continue
            if name == "gemini":
                provider = cls(
                    api_key=cfg.GEMINI_API_KEY,
                    model=cfg.GEMINI_MODEL,
                    temperature=cfg.LLM_TEMPERATURE,
                    max_output_tokens=cfg.LLM_MAX_OUTPUT_TOKENS,
                    timeout_seconds=cfg.LLM_TIMEOUT_SECONDS,
                )
            else:
                provider = cls(
                    api_key=cfg.GROQ_API_KEY,
                    model=cfg.GROQ_MODEL,
                    temperature=cfg.LLM_TEMPERATURE,
                    max_output_tokens=cfg.LLM_MAX_OUTPUT_TOKENS,
                    timeout_seconds=cfg.LLM_TIMEOUT_SECONDS,
                )
            self.providers.append(provider)
            if not provider.available:
                logger.warning(
                    "LLM provider %s has no API key configured; it will be skipped",
                    name,
                )

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        if not self.providers:
            raise LLMError("No LLM providers are configured")

        failures: list[str] = []
        for provider in self.providers:
            if not provider.available:
                failures.append(f"{provider.name}: missing API key")
                continue
            try:
                response = await asyncio.to_thread(provider.generate, messages)
                if failures:
                    logger.info(
                        "LLM request served by %s after earlier provider(s) failed: %s",
                        provider.name,
                        "; ".join(failures),
                    )
                return response
            except LLMRequestError:
                raise
            except LLMProviderError as e:
                logger.warning(
                    "LLM provider %s failed, trying fallback: %s",
                    provider.name,
                    e,
                )
                failures.append(f"{provider.name}: {e}")

        raise LLMError(
            "All configured LLM providers failed: " + "; ".join(failures)
        )


_service: LLMService | None = None
_service_lock = asyncio.Lock()


async def get_llm_service() -> LLMService:
    global _service
    if _service is None:
        async with _service_lock:
            if _service is None:
                _service = LLMService()
    return _service
