"""The LLM entry point used by the rest of the application.

Adds three things on top of a raw provider:

* **Automatic fallback.** If the configured provider fails (no key, quota,
  network, safety block), we log it and answer from the mock instead of
  raising. An LLM outage degrades a feature; it must not break the game.
* **Retries with backoff** on transient failures only.
* **Tracing hooks** so every call can be attributed in the Observability lab.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from app.ai.llm.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    LLMUnavailable,
    Message,
)
from app.ai.llm.providers import MockProvider, build_provider
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

RETRYABLE_HINTS = ("429", "500", "502", "503", "504", "timeout", "timed out", "connect")


class LLMClient:
    def __init__(self, provider: LLMProvider | None = None, cfg: Settings | None = None) -> None:
        self.cfg = cfg or get_settings()
        self.provider = provider or build_provider(self.cfg)
        self._fallback = MockProvider()

    @property
    def provider_name(self) -> str:
        return self.provider.name

    @property
    def is_simulated(self) -> bool:
        return self.provider.is_simulated

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
        model: str | None = None,
        history: list[Message] | None = None,
        retries: int = 2,
    ) -> CompletionResponse:
        request = CompletionRequest(
            messages=[*(history or []), Message("user", prompt)],
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=min(max_tokens or self.cfg.llm_max_tokens, self.cfg.llm_max_tokens),
            json_mode=json_mode,
        )

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await self.provider.complete(request)
            except LLMUnavailable as exc:
                last_error = exc
                message = str(exc).lower()
                retryable = any(hint in message for hint in RETRYABLE_HINTS)
                if not retryable or attempt == retries:
                    break
                # Exponential backoff. Jitter is omitted deliberately: this is a
                # single-tenant game, so there is no thundering herd to smooth.
                await asyncio.sleep(0.5 * (2**attempt))

        log.warning(
            "llm.fallback_to_mock", provider=self.provider.name, error=str(last_error)[:300]
        )
        response = await self._fallback.complete(request)
        response.raw["fallback_reason"] = str(last_error)[:300]
        return response

    async def complete_json(
        self, prompt: str, *, system: str | None = None, temperature: float = 0.0, **kwargs
    ) -> tuple[dict, CompletionResponse]:
        """Complete and parse JSON, tolerating the ```json fences models add."""
        import json
        import re

        response = await self.complete(
            prompt, system=system, temperature=temperature, json_mode=True, **kwargs
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        try:
            return json.loads(text), response
        except json.JSONDecodeError:
            # Last resort: pull the outermost {...}. Models occasionally prefix
            # a sentence even in JSON mode, and losing the whole grade over that
            # would be worse than a slightly fuzzy parse.
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0)), response
                except json.JSONDecodeError:
                    pass
            log.warning("llm.json_parse_failed", preview=text[:200])
            return {}, response

    async def healthcheck(self) -> tuple[bool, str]:
        return await self.provider.healthcheck()


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    return LLMClient()
