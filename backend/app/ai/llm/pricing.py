"""Token pricing table for the cost panels.

WHY hardcode a table at all: the LLM Lab's cost missions ("your LLM bill
suddenly doubled — find out why") need a number to reason about, and the
Observability dashboard attributes cost per span. Prices move, so this is a
*reference* table with an explicit as-of date, not a billing system. Anything
unknown falls back to a conservative default rather than silently reporting
$0.00 — a cost panel that shows zero is worse than one that shows an estimate.

Prices are USD per 1,000,000 tokens, as published for the standard (non-batch,
non-cached) tier.
"""

from __future__ import annotations

PRICES_AS_OF = "2026-05"

#: model prefix -> (input $/Mtok, output $/Mtok)
PRICE_TABLE: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-opus-5": (15.00, 75.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    # Google Gemini
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.0-flash": (0.10, 0.40),
    # The offline mock is free, and saying so explicitly keeps the panel honest.
    "aiforge-mock-1": (0.0, 0.0),
}

#: Used when a model name is not in the table. Deliberately mid-range: an
#: unknown model reporting $0 would hide a real cost regression.
DEFAULT_PRICE = (1.00, 5.00)


def price_for(model: str) -> tuple[float, float]:
    """Longest-prefix match, so ``gemini-2.5-flash-preview-09-2026`` still
    resolves to the flash price rather than the default."""
    name = (model or "").lower()
    best: tuple[str, tuple[float, float]] | None = None
    for prefix, price in PRICE_TABLE.items():
        if name.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, price)
    return best[1] if best else DEFAULT_PRICE


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = price_for(model)
    return round((prompt_tokens * inp + completion_tokens * out) / 1_000_000, 6)


def is_known_model(model: str) -> bool:
    return price_for(model) != DEFAULT_PRICE or (model or "").lower() in PRICE_TABLE
