"""Provider registry – factory for scoring providers."""
from __future__ import annotations

from .base import BaseProvider
from .gemini_provider import GeminiProvider
from .openai_stub import OpenAIProvider
from .anthropic_stub import AnthropicProvider
from .local_provider import LocalLLMProvider
from .qwen_provider import QwenProvider
from .deepseek_provider import DeepSeekProvider

_PROVIDERS: dict[str, type[BaseProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "local_llm": LocalLLMProvider,
    "qwen": QwenProvider,
    "deepseek": DeepSeekProvider,
}


def get_provider_instance(provider_id: str, api_key: str, config: dict,
                          mock: bool = False) -> BaseProvider:
    cls = _PROVIDERS.get(provider_id)
    if cls is None:
        raise ValueError(f"Unknown provider: {provider_id}")
    return cls(api_key=api_key, config=config, mock=mock)


def list_provider_ids() -> list[str]:
    return list(_PROVIDERS.keys())
