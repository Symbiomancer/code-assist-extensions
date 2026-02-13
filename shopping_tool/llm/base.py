"""Abstract base class for LLM providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Any


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    async def run(self, query: str, **kwargs: Any) -> LLMResponse:
        """Execute a query against the LLM."""
        ...

    @abstractmethod
    async def run_stream(self, query: str, **kwargs: Any) -> AsyncIterator[str]:
        """Execute a streaming query against the LLM."""
        ...
