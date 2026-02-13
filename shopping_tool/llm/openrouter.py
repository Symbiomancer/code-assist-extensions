"""OpenRouter LLM provider — unified access to DeepSeek, Grok, Claude, etc."""
import os
from typing import AsyncIterator, Any

from openai import AsyncOpenAI

from .base import LLMProvider, LLMResponse


# Model shortcuts
OPENROUTER_MODELS = {
    # DeepSeek (default for element resolution — cheap and fast)
    "deepseek": "deepseek/deepseek-chat",
    "deepseek-v3": "deepseek/deepseek-chat",
    "deepseek-v3.2": "deepseek/deepseek-v3.2",

    # Grok
    "grok": "x-ai/grok-code-fast-1",
    "grok-fast": "x-ai/grok-code-fast-1",

    # Kimi (reasoning)
    "kimi": "moonshotai/kimi-k2.5",
    "kimi-k2": "moonshotai/kimi-k2.5",

    # Qwen3 (free tier)
    "qwen-free": "qwen/qwen3-coder:free",

    # Claude via OpenRouter
    "claude-haiku": "anthropic/claude-haiku-4.5",
    "claude-sonnet": "anthropic/claude-sonnet-4",
    "claude-opus": "anthropic/claude-opus-4.6",

    # Gemini
    "gemini-flash": "google/gemini-3-flash-preview",
    "gemini-pro": "google/gemini-3-pro-preview",
}


def get_provider(
    model: str = "deepseek",
    api_key: str | None = None,
) -> "OpenRouterProvider":
    """Factory function to create an OpenRouter provider."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise ValueError("OPENROUTER_API_KEY not set")
    return OpenRouterProvider(api_key=key, model=model)


class OpenRouterProvider(LLMProvider):
    """OpenRouter provider — uses OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek",
        site_name: str = "Shopping Assistant",
    ):
        resolved_model = OPENROUTER_MODELS.get(model, model)
        super().__init__(api_key, resolved_model)

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"X-Title": site_name},
        )

    def _resolve_model(self, kwargs: dict[str, Any]) -> str:
        """Resolve model, supporting shortcuts."""
        if "model" in kwargs:
            model = kwargs.pop("model")
            return OPENROUTER_MODELS.get(model, model)
        return self.model

    async def run(self, query: str, **kwargs: Any) -> LLMResponse:
        """Execute a query against OpenRouter."""
        model = self._resolve_model(kwargs)

        messages = []
        if kwargs.get("system"):
            messages.append({"role": "system", "content": kwargs.pop("system")})
        messages.append({"role": "user", "content": query})

        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 4096),
        )

        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            usage={
                "input": response.usage.prompt_tokens if response.usage else 0,
                "output": response.usage.completion_tokens if response.usage else 0,
            },
            raw_response=response.model_dump(),
        )

    async def run_stream(self, query: str, **kwargs: Any) -> AsyncIterator[str]:
        """Execute a streaming query against OpenRouter."""
        model = self._resolve_model(kwargs)

        messages = []
        if kwargs.get("system"):
            messages.append({"role": "system", "content": kwargs.pop("system")})
        messages.append({"role": "user", "content": query})

        stream = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 4096),
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
