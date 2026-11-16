from dataclasses import dataclass


@dataclass
class ChatMessage:
    """Provider-independent chat message."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str


class LLMError(Exception):
    """Base error for LLM operations. Message must not contain secrets."""


class LLMProviderError(LLMError):
    """Recoverable provider-side failure (rate limit, 5xx, timeout,
    authentication). Eligible for fallback to the next provider."""


class LLMRequestError(LLMError):
    """Non-recoverable request problem (bad request, unknown model,
    malformed response). Not eligible for fallback."""
