import pytest

from app.services.llm import (
    ChatMessage,
    LLMError,
    LLMProviderError,
    LLMRequestError,
    LLMResponse,
    LLMService,
)
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider


def _messages():
    return [
        ChatMessage(role="system", content="You are helpful."),
        ChatMessage(role="user", content="What is in the docs?"),
    ]


class FakeGeminiModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return self.response


class FakeGeminiClient:
    def __init__(self, response=None, error=None):
        self.models = FakeGeminiModels(response, error)


class GeminiResponse:
    def __init__(self, text="gemini answer"):
        self.text = text
        self.candidates = []


def _gemini_provider(client, **kwargs):
    params = dict(
        api_key="test-key",
        model="gemini-test",
        temperature=0.2,
        max_output_tokens=100,
        timeout_seconds=5,
        client=client,
    )
    params.update(kwargs)
    return GeminiProvider(**params)


async def test_gemini_success():
    client = FakeGeminiClient(response=GeminiResponse("hello from gemini"))
    provider = _gemini_provider(client)

    resp = provider.generate(_messages())

    assert resp.text == "hello from gemini"
    assert resp.provider == "gemini"
    assert resp.model == "gemini-test"
    call = client.models.calls[0]
    # system message mapped to system_instruction, user to "user" role
    assert call["config"].system_instruction == "You are helpful."
    assert call["config"].temperature == 0.2
    assert call["config"].max_output_tokens == 100
    assert call["config"].http_options.timeout == 5000
    assert call["contents"][0].role == "user"
    assert call["contents"][0].parts[0].text == "What is in the docs?"


async def test_gemini_empty_text_is_request_error():
    client = FakeGeminiClient(response=GeminiResponse(text=None))
    provider = _gemini_provider(client)

    with pytest.raises(LLMRequestError):
        provider.generate(_messages())


async def test_gemini_error_mapping():
    class FakeAPIError(Exception):
        def __init__(self, code):
            super().__init__("api error")
            self.code = code

    for code, expected in [
        (400, LLMRequestError),
        (404, LLMRequestError),
        (429, LLMProviderError),
        (500, LLMProviderError),
        (503, LLMProviderError),
    ]:
        client = FakeGeminiClient(error=FakeAPIError(code))
        provider = _gemini_provider(client)
        with pytest.raises(expected):
            provider.generate(_messages())

    client = FakeGeminiClient(error=TimeoutError("timed out"))
    provider = _gemini_provider(client)
    with pytest.raises(LLMProviderError):
        provider.generate(_messages())


async def test_gemini_unavailable_without_key():
    provider = _gemini_provider(FakeGeminiClient(), api_key=None)
    assert not provider.available


class FakeGroqCompletions:
    def __init__(self, content="groq answer", error=None):
        self.content = content
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = type("Msg", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Completion", (), {"choices": [choice]})()


class FakeGroqChat:
    def __init__(self, content="groq answer", error=None):
        self.completions = FakeGroqCompletions(content, error)


class FakeGroqClient:
    def __init__(self, content="groq answer", error=None):
        self.chat = FakeGroqChat(content, error)


def _groq_provider(client, **kwargs):
    params = dict(
        api_key="test-key",
        model="groq-test",
        temperature=0.2,
        max_output_tokens=100,
        timeout_seconds=5,
        client=client,
    )
    params.update(kwargs)
    return GroqProvider(**params)


async def test_groq_success():
    client = FakeGroqClient(content="hello from groq")
    provider = _groq_provider(client)

    resp = provider.generate(_messages())

    assert resp.text == "hello from groq"
    assert resp.provider == "groq"
    assert resp.model == "groq-test"
    call = client.chat.completions.calls[0]
    assert call["model"] == "groq-test"
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 100
    assert call["timeout"] == 5
    assert call["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert call["messages"][1]["role"] == "user"


async def test_groq_error_mapping():
    class FakeStatusError(Exception):
        def __init__(self, status_code):
            super().__init__("api error")
            self.status_code = status_code

    for status, expected in [
        (400, LLMRequestError),
        (404, LLMRequestError),
        (429, LLMProviderError),
        (500, LLMProviderError),
    ]:
        client = FakeGroqClient(error=FakeStatusError(status))
        provider = _groq_provider(client)
        with pytest.raises(expected):
            provider.generate(_messages())

    client = FakeGroqClient(error=TimeoutError("timed out"))
    provider = _groq_provider(client)
    with pytest.raises(LLMProviderError):
        provider.generate(_messages())


async def test_groq_malformed_response():
    client = FakeGroqClient(content=None)
    provider = _groq_provider(client)
    with pytest.raises(LLMRequestError):
        provider.generate(_messages())


class FakeProvider:
    def __init__(self, name, available=True, result=None, error=None):
        self.name = name
        self.model = f"{name}-model"
        self._available = available
        self.result = result
        self.error = error
        self.calls = 0

    @property
    def available(self):
        return self._available

    def generate(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result or LLMResponse(
            text=f"{self.name} answer", provider=self.name, model=self.model
        )


def _service_with(providers):
    service = LLMService.__new__(LLMService)
    service.providers = providers
    return service


async def test_fallback_on_provider_error():
    primary = FakeProvider("gemini", error=LLMProviderError("rate limited"))
    fallback = FakeProvider("groq")
    service = _service_with([primary, fallback])

    resp = await service.generate(_messages())

    assert resp.provider == "groq"
    assert primary.calls == 1
    assert fallback.calls == 1


async def test_no_fallback_on_request_error():
    primary = FakeProvider("gemini", error=LLMRequestError("bad request"))
    fallback = FakeProvider("groq")
    service = _service_with([primary, fallback])

    with pytest.raises(LLMRequestError):
        await service.generate(_messages())
    assert fallback.calls == 0


async def test_all_providers_fail():
    primary = FakeProvider("gemini", error=LLMProviderError("down"))
    fallback = FakeProvider("groq", error=LLMProviderError("also down"))
    service = _service_with([primary, fallback])

    with pytest.raises(LLMError):
        await service.generate(_messages())


async def test_unavailable_provider_skipped():
    primary = FakeProvider("gemini", available=False)
    fallback = FakeProvider("groq")
    service = _service_with([primary, fallback])

    resp = await service.generate(_messages())
    assert resp.provider == "groq"
    assert primary.calls == 0


async def test_no_providers_configured():
    service = _service_with([])
    with pytest.raises(LLMError):
        await service.generate(_messages())


async def test_provider_order_primary_first():
    primary = FakeProvider("gemini")
    fallback = FakeProvider("groq")
    service = _service_with([primary, fallback])

    resp = await service.generate(_messages())
    assert resp.provider == "gemini"
    assert fallback.calls == 0
