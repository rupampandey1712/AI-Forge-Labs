# AI Architecture

How the LLM, evaluation and observability layers are built — and why every one
of them works with **no API key**.

---

## 1. The non-negotiable constraint

Every AI feature in this game must be playable offline.

That is not a nice-to-have. It is what makes the AI labs *testable*, keeps the
evaluation experiments *reproducible*, and means a player without a billing
relationship can still finish the RAG Tower and the Agent Factory.

So `MockProvider` is not a stub that returns "TODO". It is a deterministic
provider seeded by a hash of the prompt, producing structurally plausible output
for the shapes the game actually asks for — JSON grading verdicts, RAG answers
grounded in the supplied context, interviewer follow-ups.

Determinism is the point. The same prompt always yields the same answer, so an
evaluation run is reproducible and an AI feature can have a real test.

---

## 2. The provider gateway

```
app/ai/llm/
  base.py       Message · CompletionRequest · CompletionResponse · LLMProvider
  providers.py  MockProvider · GeminiProvider · AnthropicProvider · OpenAIProvider
  client.py     retries · automatic fallback · JSON parsing
  pricing.py    cost table with an explicit as-of date
```

All four adapters are plain `httpx` rather than vendor SDKs. The SDKs pull in
large dependency trees for functionality this application does not use, and
having the raw request visible is itself educational — the LLM Lab shows players
the actual payload each provider expects.

### The shape differences, which is the lesson

|                 | Anthropic         | OpenAI                  | **Gemini**                      |
| --------------- | ----------------- | ----------------------- | ------------------------------- |
| Roles           | user/assistant    | system/user/assistant   | **user/model**                  |
| System prompt   | top-level `system`| a message               | **separate `systemInstruction`**|
| Sampling knobs  | top-level         | top-level               | **nested `generationConfig`**   |
| JSON mode       | prompt            | `response_format`       | **`responseMimeType`**          |
| Auth            | `x-api-key`       | `Authorization: Bearer` | **`x-goog-api-key` header**     |

Gemini's key goes in a header rather than the query string so it does not end up
in proxy logs or browser history. Its adapter also merges any stray system
messages into `systemInstruction` instead of dropping them — silently losing a
system prompt is a nasty bug — and reports "no candidates" (a safety block) as a
clear error rather than an `IndexError`.

Adding a provider is one class and one line in `build_provider`.

### Failure behaviour

`LLMClient` retries only genuinely transient failures (429, 5xx, timeouts) with
exponential backoff, then **falls back to the mock** rather than raising. An LLM
outage degrades a feature; it must never break the game.

`complete_json` tolerates the ```json fences models add even in JSON mode, and
falls back to extracting the outermost `{...}` — losing an entire grade to a
stray prefix sentence would be worse than a slightly fuzzy parse.

### Cost

`pricing.py` carries a table with an explicit `PRICES_AS_OF` date and
longest-prefix matching, so `gemini-2.5-flash-preview-09-2026` resolves to the
flash price rather than the default. An unknown model falls back to a
**mid-range** estimate, never to `$0.00` — a cost panel that shows zero is worse
than one that shows an estimate.

```bash
LLM_PROVIDER=gemini    # or anthropic | openai | mock
GEMINI_API_KEY=...
LLM_MODEL=             # blank = provider default
LLM_MAX_TOKENS=2048    # hard ceiling: a runaway prompt cannot generate a surprise bill
```

---

## 3. Grading: rubric first, LLM second

The deterministic rubric grader (`app/game/grading/rubric.py`) is the primary
path, not a fallback.

**Why**: it grades the same answer the same way twice, it works offline, and it
can tell the player *exactly* which points were missing. An LLM judge is better
at nuance and is available as an enhancement — but making it a prerequisite
would mean a player's score depends on a network call, which is both unfair and
unreproducible.

Measured discrimination on a single question: junior 0.4 → mid 5.0 → senior 7.6
→ staff 9.3 out of 10. See [GAME_DESIGN.md](GAME_DESIGN.md) §9 for the seven
dimensions and how each is detected.

---

## 4. Observability

`traces` + `spans` tables, shaped like OpenTelemetry — a span has a parent
pointer, a type (`llm`, `retriever`, `embedding`, `tool`, `node`, `chain`,
`db`, `http`), timings, token counts, cost and an evaluation score.

**Why store traces in Postgres rather than ship them to a real backend**: the
point of the Observability Lab is to make the player *build and read* traces.
The data has to be inspectable, queryable and seedable — and the shape is the
same one OpenTelemetry uses, so the lesson transfers to a real system.

```
REQUEST  ──► retriever (48ms, 4 docs)
         ──► embedding (12ms, 38 tokens, $0.000004)
         ──► llm       (1,204ms, 2,840 tokens, $0.0021)   ← 94% of latency
         ──► tool      (31ms)
         └─► answer    faithfulness 0.87
```

What the panel is designed to make obvious at 3am: which span owns the latency,
which owns the cost, and which one failed.

---

## 5. Evaluation

`Evaluation` rows carry the six metrics the Evals Lab teaches — retrieval
precision, retrieval recall, context relevance, faithfulness, answer relevance,
groundedness — as columns, because the dashboard charts them over time. Per-case
results live in `results` so an experiment is a single fetch.

The teaching sequence is deliberately **golden dataset → deterministic checks →
LLM-as-judge → human review**, in that order of preference. Reaching for an LLM
judge first is the most common and most expensive mistake in AI evaluation: it
is slower, non-deterministic, and often measures the judge rather than the
system.

A `verdict` field (`ship` / `hold` / `rollback`) exists because an evaluation
that does not gate a decision is a dashboard, not an evaluation.

---

## 6. Agents

`AgentRun` stores `state_history` — the state diff at every node transition.
That is the teaching artefact: stepping through how state mutated node by node
is the only way graph debugging ever clicks.

`halted_reason` records when a recursion guard fired, which is what turns
"Autonomous agent enters infinite loop" from a war story into a mission.

`needs_human_approval` / `human_decision` model the human-in-the-loop checkpoint
explicitly, because "the agent escalates when confidence is low" is the
difference between a demo and something you would actually deploy.
