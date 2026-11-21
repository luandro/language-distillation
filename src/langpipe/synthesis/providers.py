"""Pluggable LLM Providers for Synthetic Phrase Generation.

Supports Poolside (Laguna S 2.1 / Laguna XS 2.1), OpenAI, and deterministic Mock.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class LLMProvider(Protocol):
    """Protocol for LLM completions."""

    provider_name: str
    model_name: str

    def complete(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """Execute chat completion and return response string."""
        ...


class BaseOpenAICompatibleProvider:
    """Base provider for OpenAI-compatible HTTP chat completion endpoints."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        provider_name: str,
        timeout: float = 45.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.provider_name = provider_name
        self.timeout = timeout

    def complete(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                return str(res_body["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"HTTP {e.code} error from {self.provider_name} API: {err_msg}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Connection failure to {self.provider_name} at {url}: {e}") from e


class PoolsideProvider(BaseOpenAICompatibleProvider):
    """Poolside Foundation Model Provider (Laguna)."""

    DEFAULT_BASE_URL = "https://inference.poolside.ai/v1"
    DEFAULT_MODEL = "poolside/laguna-s-2.1"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("POOLSIDE_API_KEY", "")
        if not key:
            raise ValueError(
                "POOLSIDE_API_KEY is not set. Provide api_key argument or set environment variable."
            )
        super().__init__(
            base_url=base_url or os.environ.get("POOLSIDE_BASE_URL", self.DEFAULT_BASE_URL),
            api_key=key,
            model_name=model_name or os.environ.get("POOLSIDE_MODEL", self.DEFAULT_MODEL),
            provider_name="Poolside",
        )


class OpenAIProvider(BaseOpenAICompatibleProvider):
    """OpenAI API Provider."""

    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Provide api_key argument or set environment variable."
            )
        super().__init__(
            base_url=base_url or os.environ.get("OPENAI_BASE_URL", self.DEFAULT_BASE_URL),
            api_key=key,
            model_name=model_name or os.environ.get("OPENAI_MODEL", self.DEFAULT_MODEL),
            provider_name="OpenAI",
        )


class MockProvider:
    """Deterministic Mock Provider for offline testing, CI, and zero-network execution."""

    provider_name: str = "Mock"
    model_name: str = "mock-grounded-v1"

    def complete(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        # Returns verified grounded target-language phrases in JSON
        mock_output = [
            {
                "target": "vaki-n isu yamama-katsai.",
                "igt": "vaki-n isu yamama-katsai\ncriança-ERG macaco matar-FUT\n"
                "O menino matará o macaco.",
                "portugues": "O menino matará o macaco.",
                "stems": ["vaki", "isu", "yamama"],
                "affixes": ["-n", "-katsai"],
            },
            {
                "target": "vaki nuku-ai.",
                "igt": "vaki nuku-ai\ncriança chegar-PRES\nO menino está chegando.",
                "portugues": "O menino está chegando.",
                "stems": ["vaki", "nuku"],
                "affixes": ["-ai"],
            },
            {
                "target": "nuki-n nami nun-pi-ai.",
                "igt": "nuki-n nami nun-pi-ai\n1PL-ERG carne 1PL.AGT-comer-PRES\n"
                "Nós comemos carne todo dia.",
                "portugues": "Nós comemos carne todo dia.",
                "stems": ["nuki", "nami", "pi"],
                "affixes": ["-n", "-ai"],
            },
            {
                "target": "chai nuya-tinpa.",
                "igt": "chai nuya-tinpa\npássaro voar-IMPOS\nO pássaro não pode voar.",
                "portugues": "O pássaro não pode voar.",
                "stems": ["chai", "nuya"],
                "affixes": ["-tinpa"],
            },
        ]
        return json.dumps(mock_output, ensure_ascii=False)


def get_provider(
    provider_name: str = "poolside",
    api_key: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
) -> LLMProvider:
    """Factory function for LLM providers."""
    norm_name = provider_name.strip().lower()
    if norm_name in ("poolside", "laguna"):
        return PoolsideProvider(api_key=api_key, base_url=base_url, model_name=model_name)
    elif norm_name in ("openai", "gpt"):
        return OpenAIProvider(api_key=api_key, base_url=base_url, model_name=model_name)
    elif norm_name in ("mock", "offline", "test"):
        return MockProvider()
    else:
        raise ValueError(
            f"Unknown provider '{provider_name}'. Supported: 'poolside', 'openai', 'mock'."
        )
