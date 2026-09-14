"""Provider-agnostic LLM interface.

WHY an interface rather than calling a vendor SDK directly
----------------------------------------------------------
1. **The game must run with no API key at all.** Every AI feature degrades to a
   deterministic ``MockProvider`` so a player can finish the RAG Tower, the
   Agent Factory and the Interview Arena entirely offline. An LLM is an
   *enhancement* here, never a dependency.
2. **Swapping providers is a teaching moment.** The LLM Lab asks the player to
   compare providers, temperatures and costs; that is only honest if the
   application itself is not welded to one vendor.
3. **Tracing.** Every call goes through one place, so token counts, latency and
   cost land in the observability tables without each call site remembering to
   record them.

TRADEOFF: a thin common interface cannot expose every provider-specific
feature. We accept that — the ~5 knobs below (model, temperature, max tokens,
system prompt, JSON mode) cover everything the game needs, and a provider
adapter is free to read extra settings from ``extra``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class Message:
    role: Role
    content: str


@dataclass(slots=True)
class CompletionRequest:
    messages: list[Message]
    system: str | None = None
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1024
    top_p: float | None = None
    #: Ask the provider for strict JSON. Each adapter maps this to its own
    #: mechanism (response_format / responseMimeType / a prompt suffix).
    json_mode: bool = False
    stop: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class CompletionResponse:
    text: str
    model: str
    provider: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)
    #: True when this came from the offline mock, so the UI can say so rather
    #: than presenting a canned string as a real model response.
    simulated: bool = False

    @property
    def cost_usd(self) -> float:
        from app.ai.llm.pricing import estimate_cost

        return estimate_cost(self.model, self.usage.prompt_tokens, self.usage.completion_tokens)


class LLMProvider(abc.ABC):
    name: str = "abstract"
    default_model: str = ""

    @abc.abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...

    async def healthcheck(self) -> tuple[bool, str]:
        return True, "ok"

    @property
    def is_simulated(self) -> bool:
        return False


class LLMUnavailable(RuntimeError):
    """Raised when a configured provider cannot be reached.

    Callers are expected to catch this and fall back to the mock/rubric path —
    an LLM outage must never take the game down.
    """
