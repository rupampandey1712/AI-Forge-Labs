"""Concrete LLM adapters: mock, Anthropic, OpenAI and Google Gemini.

All four speak the same ``LLMProvider`` interface, and all four are implemented
over plain ``httpx`` rather than vendor SDKs. WHY: the SDKs pull in large
dependency trees for functionality this application does not use, and having
the raw request/response visible is itself educational — the LLM Lab shows
players the actual HTTP payload each provider expects.

Adding a provider is one class plus one line in ``build_provider``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx

from app.ai.llm.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    LLMUnavailable,
    Message,
    Usage,
)
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _flatten(messages: list[Message], system: str | None) -> str:
    parts = [f"[system] {system}"] if system else []
    parts += [f"[{m.role}] {m.content}" for m in messages]
    return "\n".join(parts)


def _approx_tokens(text: str) -> int:
    """~4 characters per token. Crude, but it keeps the cost/latency panels
    populated in mock mode, and the LLM Lab has a real tokenizer lesson that
    explains precisely why this approximation is wrong."""
    return max(1, len(text) // 4)


# ── Mock ─────────────────────────────────────────────────────────────────────
class MockProvider(LLMProvider):
    """Deterministic offline provider.

    Not a stub that returns "TODO": it produces structurally plausible output
    for the shapes the game actually asks for (JSON grading verdicts, RAG
    answers grounded in the supplied context, interviewer follow-ups), seeded
    by a hash of the prompt so the same prompt always yields the same answer.
    That determinism is what makes the evaluation labs reproducible without a
    key — and it makes tests of AI features possible at all.
    """

    name = "mock"
    default_model = "aiforge-mock-1"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        started = time.perf_counter()
        prompt = _flatten(request.messages, request.system)
        seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)

        # Simulate a little latency so the UI's loading states are exercised.
        await asyncio.sleep(0.02 + (seed % 7) / 100)

        text = self._synthesise(prompt, request, seed)
        return CompletionResponse(
            text=text,
            model=request.model or self.default_model,
            provider=self.name,
            usage=Usage(_approx_tokens(prompt), _approx_tokens(text)),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            simulated=True,
        )

    def _synthesise(self, prompt: str, request: CompletionRequest, seed: int) -> str:
        lowered = prompt.lower()
        if request.json_mode or "respond with json" in lowered or '"score"' in lowered:
            score = 5 + (seed % 5)
            return json.dumps(
                {
                    "score": score,
                    "reasoning": (
                        "Simulated grader: no LLM provider is configured, so this score comes "
                        "from the deterministic mock. Configure LLM_PROVIDER for real grading."
                    ),
                    "missing": ["trade-offs", "failure modes"][: 1 + (seed % 2)],
                    "simulated": True,
                }
            )
        # RAG-shaped prompt: answer only from the provided context, and refuse
        # when there is none. Teaching grounding by example, even in mock mode.
        if "context:" in lowered:
            body = prompt.split("Context:", 1)[-1] if "Context:" in prompt else ""
            snippet = " ".join(body.split()[:60]).strip()
            if not snippet:
                return "I don't have enough context to answer that. [simulated]"
            return f"Based on the retrieved context: {snippet}… [simulated answer]"
        return (
            "[simulated response] No LLM provider is configured. Set LLM_PROVIDER to "
            "`gemini`, `anthropic` or `openai` (with the matching API key) to enable "
            "real model responses. Everything else in this lab works offline."
        )

    @property
    def is_simulated(self) -> bool:
        return True


# ── Shared HTTP behaviour ────────────────────────────────────────────────────
class _HTTPProvider(LLMProvider):
    def __init__(self, api_key: str, *, timeout: float = 45.0, model: str = "") -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.model = model or self.default_model

    async def _post(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> dict:
        if not self.api_key:
            raise LLMUnavailable(f"{self.name}: no API key configured")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"{self.name}: {exc}") from exc
        if response.status_code >= 400:
            # Surface the provider's own message: "model not found" and
            # "quota exceeded" need very different responses from us.
            detail = response.text[:500]
            raise LLMUnavailable(f"{self.name} returned {response.status_code}: {detail}")
        return response.json()


class AnthropicProvider(_HTTPProvider):
    name = "anthropic"
    default_model = "claude-sonnet-5"
    API_URL = "https://api.anthropic.com/v1/messages"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
                if m.role in ("user", "assistant")
            ],
        }
        if request.system:
            payload["system"] = request.system
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop:
            payload["stop_sequences"] = request.stop
        payload.update(request.extra)

        data = await self._post(
            self.API_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload=payload,
        )
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return CompletionResponse(
            text=text,
            model=data.get("model", payload["model"]),
            provider=self.name,
            usage=Usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            finish_reason=data.get("stop_reason", "stop"),
            raw=data,
        )


class OpenAIProvider(_HTTPProvider):
    name = "openai"
    default_model = "gpt-4o-mini"
    API_URL = "https://api.openai.com/v1/chat/completions"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        started = time.perf_counter()
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages += [{"role": m.role, "content": m.content} for m in request.messages]

        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop:
            payload["stop"] = request.stop
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload.update(request.extra)

        data = await self._post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage", {})
        return CompletionResponse(
            text=(choice.get("message") or {}).get("content", ""),
            model=data.get("model", payload["model"]),
            provider=self.name,
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
        )


class GeminiProvider(_HTTPProvider):
    """Google Gemini via the Generative Language REST API.

    Three shape differences from the OpenAI/Anthropic adapters, all of which
    the LLM Lab points at explicitly because they trip people up:

    * roles are ``user``/``model`` (not ``assistant``);
    * the system prompt is a separate ``systemInstruction`` object, not a
      message in the list;
    * sampling knobs live under ``generationConfig``, and JSON mode is
      ``responseMimeType``, not a ``response_format`` object.

    The API key goes in the ``x-goog-api-key`` header rather than the query
    string so it does not end up in proxy logs or browser history.
    """

    name = "gemini"
    #: Configurable via ``LLM_MODEL``. Google ships models faster than any
    #: default can track, so treat this as a starting point, not a guarantee —
    #: an unknown model name comes back as a clear 404 from ``_post``.
    default_model = "gemini-2.5-flash"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        started = time.perf_counter()
        model = request.model or self.model

        contents = [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in request.messages
            if m.role != "system"
        ]
        # Any stray system messages are merged into systemInstruction rather
        # than dropped — silently losing a system prompt is a nasty bug.
        inline_system = [m.content for m in request.messages if m.role == "system"]
        system_text = "\n\n".join(filter(None, [request.system, *inline_system]))

        generation_config: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        }
        if request.top_p is not None:
            generation_config["topP"] = request.top_p
        if request.stop:
            generation_config["stopSequences"] = request.stop
        if request.json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation_config}
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        payload.update(request.extra)

        data = await self._post(
            f"{self.BASE_URL}/{model}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            payload=payload,
        )

        candidates = data.get("candidates") or []
        if not candidates:
            # A prompt blocked by safety filters returns no candidates at all,
            # with the reason in promptFeedback. Reporting that is far more
            # useful than an IndexError.
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
            raise LLMUnavailable(f"gemini returned no completion ({reason})")

        candidate = candidates[0]
        text = "".join(
            part.get("text", "") for part in (candidate.get("content") or {}).get("parts", [])
        )
        usage = data.get("usageMetadata", {})
        return CompletionResponse(
            text=text,
            model=data.get("modelVersion", model),
            provider=self.name,
            usage=Usage(
                usage.get("promptTokenCount", 0),
                # Thinking models bill reasoning tokens separately; counting
                # them keeps the cost panel honest.
                usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
            ),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            finish_reason=candidate.get("finishReason", "STOP"),
            raw=data,
        )

    async def healthcheck(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "GEMINI_API_KEY is not set"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.BASE_URL}/{self.model}",
                    headers={"x-goog-api-key": self.api_key},
                )
        except httpx.HTTPError as exc:
            return False, str(exc)
        return (True, "ok") if r.status_code == 200 else (False, f"HTTP {r.status_code}")


def build_provider(cfg: Settings | None = None) -> LLMProvider:
    cfg = cfg or get_settings()
    match cfg.llm_provider:
        case "anthropic":
            key = cfg.anthropic_api_key
            return (
                AnthropicProvider(key, timeout=cfg.llm_timeout_seconds, model=cfg.llm_model)
                if key
                else MockProvider()
            )
        case "openai":
            key = cfg.openai_api_key
            return (
                OpenAIProvider(key, timeout=cfg.llm_timeout_seconds, model=cfg.llm_model)
                if key
                else MockProvider()
            )
        case "gemini" | "google":
            key = cfg.gemini_api_key
            return (
                GeminiProvider(key, timeout=cfg.llm_timeout_seconds, model=cfg.llm_model)
                if key
                else MockProvider()
            )
        case _:
            return MockProvider()
