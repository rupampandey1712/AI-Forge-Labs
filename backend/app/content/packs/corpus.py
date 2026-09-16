"""The `forge-docs` corpus — the RAG Tower's playground.

DESIGN of this corpus, which is not accidental:

* **Short, factual, specific.** Every document contains precise claims ("15
  minutes", "three consecutive clean submissions") so retrieval either found
  the answer or it did not. Vague prose makes faithfulness unmeasurable.
* **Deliberate near-duplicates.** Several documents discuss timeouts, limits and
  expiry. That is the point: retrieval has to discriminate between them, and
  players get to watch it fail when chunk size is wrong.
* **Deliberate paraphrase traps.** The golden set asks "how long is a reset link
  valid" while the document says "expires after 15 minutes". The offline lexical
  embedder struggles with exactly this, which is the wall players are meant to
  hit before switching providers.
* **One unanswerable question.** The golden set includes a question no document
  answers, so refusal behaviour is measurable. A RAG system that never refuses
  is not grounded, it is lucky.
"""

from __future__ import annotations

from app.content.schema import ContentPack, DocumentSpec

DOCUMENTS = [
    DocumentSpec(
        slug="forge-security-policy",
        corpus="forge-docs",
        title="Authentication and Session Policy",
        source="internal/security/auth-policy.md",
        metadata={"team": "platform", "classification": "internal", "version": "3.2"},
        content="""
Authentication and Session Policy

Password requirements

Passwords must be at least 16 characters, or at least 8 characters containing
three of the following four classes: lowercase, uppercase, digit, symbol.
Length is the dominant factor in password strength, so a long passphrase is
accepted without symbol requirements.

Passwords are hashed with bcrypt at cost factor 12. Input is pre-hashed with
SHA-256 and base64-encoded before bcrypt, because bcrypt silently truncates
input at 72 bytes and a long passphrase would otherwise have its tail ignored.

Access tokens

Access tokens are JWTs signed with HS256 and expire after 60 minutes. They
carry a `typ` claim of "access". A refresh token presented where an access
token is required is rejected, which blocks token-type confusion attacks.

Refresh tokens and rotation

Refresh tokens expire after 30 days. Every refresh issues a new token and
revokes the previous one. This is token rotation: a stolen refresh token is
usable at most once.

Presenting an already-rotated refresh token is treated as evidence of theft.
Every session belonging to that user is revoked immediately, including the
legitimate one, and the user must re-authenticate. The revocation is committed
before the error is raised, because a request-scoped rollback would otherwise
silently undo it.

Password reset

A password reset link expires after 15 minutes. Users may request at most one
reset every 24 hours. Changing a password revokes every other active session.

Account recovery

If a user has lost access to their registered email, support must verify
identity using two of: the last four digits of a payment card, the last known
login IP address, or the answer to a security question.

Rate limiting

The API allows 240 requests per minute per client by default, using a sliding
window. The limiter counts per process, so with four workers the effective
limit is four times the configured value and it resets on deploy. A
distributed limiter backed by Redis sorted sets is the correct production
answer.
""",
    ),
    DocumentSpec(
        slug="forge-sandbox-design",
        corpus="forge-docs",
        title="Code Execution Sandbox Design",
        source="internal/platform/sandbox.md",
        metadata={"team": "platform", "classification": "internal", "version": "2.0"},
        content="""
Code Execution Sandbox Design

Why the game server never executes player code in-process

Python cannot sandbox itself. Any in-interpreter jail is defeated by ctypes,
frame walking, or a C extension. Isolation therefore requires a process or
container boundary, and the game server must never be on the wrong side of it.

The protocol

Everything crossing the boundary is plain JSON. The sandbox runner accepts a
request object on stdin and writes a framed result to stdout. Because the
protocol carries only data, the sandbox can be a subprocess today and a
container tomorrow with no change above it.

The runner is standalone: it imports nothing from the application. A test
parses its abstract syntax tree and fails the build if anyone adds an
application import, because the container image contains that one file and
nothing else.

Subprocess backend

The subprocess backend spawns a separate OS process with POSIX resource limits,
a scrubbed environment, a throwaway working directory, and a wall-clock timeout
that kills the entire process tree. Killing only the direct child would orphan
grandchildren, so a submission that spawns a busy loop would survive the
timeout and eat a core indefinitely.

This backend is defence in depth for local single-player use. It is not a
security boundary against a determined attacker on a shared host.

Docker backend

The docker backend runs each execution in a container with no network, a
read-only root filesystem, all capabilities dropped, no new privileges, a
non-root user, and limits on memory, CPU and process count. This is the
supported mode for any shared deployment.

Admission control

A bounded semaphore caps concurrent executions. Without it, twenty players each
submitting an accidental infinite loop would fork twenty CPU-burning processes
and the game server would be the component that falls over. That is the classic
failure where the sandbox was isolated but the host was not.

Static pre-screening

Submissions are parsed before execution. Imports of network and process modules
are rejected, as is reflection commonly used for escapes. This is a filter that
makes abuse loud and gives the player a useful error. It is explicitly not the
security boundary, and claiming otherwise would be more dangerous than having
no sandbox at all.

Environment scrubbing

The runner deletes every environment variable except a small allowlist. Even in
subprocess mode the parent environment holds the signing key and the database
URL, so inheriting it would make printing os.environ a credential dump.
""",
    ),
    DocumentSpec(
        slug="forge-retention-model",
        corpus="forge-docs",
        title="The Knowledge Retention Engine",
        source="internal/product/retention.md",
        metadata={"team": "product", "classification": "internal", "version": "1.4"},
        content="""
The Knowledge Retention Engine

The model

Every player-concept pair carries a memory state: stability, ease, mastery, and
a peak mastery high-water mark. Recall probability decays exponentially since
the last review, with R(t) = exp(-t / S). The stability constant S is derived
from the scheduled interval so that recall at the due date is exactly 90
percent.

Mastery and the savings floor

Effective mastery blends durable competence with current recall probability,
floored at 35 percent of peak. This encodes the savings effect: relearning is
dramatically faster than first learning, so a concept mastered and then
abandoned for a year is rust rather than amnesia.

The mastery ceiling

Mastery is capped by the deepest difficulty tier the player has actually
cleared. A player who has only ever answered tier-one recall questions cannot
exceed 25 percent mastery, no matter how many they answer. Clearing tier three
raises the ceiling to 58 percent, tier five to 80 percent, and tier eight to 96
percent. This is what stops the game asking "what is a list" forever.

Scheduling

Early reviews follow a ladder of 1, 3, 7, 14, 30, 60 and 90 days, modulated by
an ease factor so a player who answers perfectly moves through it faster. After
the ladder, the interval is multiplied by ease.

A failure reduces the interval to a quarter and records a lapse. Repeated
failures compound. Hints incur a quality penalty, because a solution reached
after three hints was reconstructed with help rather than recalled.

Being confident and wrong incurs an additional penalty and schedules a much
earlier review. Miscalibration rather than ignorance is what sinks senior
interviews.

Decay alerts

A concept below 90 percent recall is due. Below 72 percent it raises a decay
alert. Below 45 percent it is critical. Alerts are grouped by skill rather than
per concept, because twelve separate notifications are noise a player learns to
dismiss.

The mistake database

A detected mistake is stored as a named, reusable pattern rather than as a
wrong answer. Repeating it increments an occurrence counter instead of creating
a duplicate record. A mistake record closes only after three consecutive clean
submissions: getting it right once is luck, three times in a row is a changed
habit.
""",
    ),
    DocumentSpec(
        slug="forge-rag-runbook",
        corpus="forge-docs",
        title="RAG Incident Runbook",
        source="internal/ai/rag-runbook.md",
        metadata={"team": "ai", "classification": "internal", "version": "2.1"},
        content="""
RAG Incident Runbook

Symptom: the assistant gives a confident but wrong answer

Work the ladder in order. Most engineers start at step five and rewrite the
prompt. It is almost always step two or three.

Step one: is the answer in the corpus at all? Grep for it. A retrieval system
cannot return what was never ingested, and an ingestion failure presents
identically to a retrieval failure.

Step two: did retrieval return it? Check retrieval precision and recall against
the golden set. Low precision means most of what was retrieved is irrelevant.
Low recall means relevant material exists and was not returned.

Step three: did the chunk contain enough context to answer? Read the retrieved
chunks. A fact split across a chunk boundary appears in neither chunk
completely, so neither retrieves confidently for it.

Step four: did the prompt actually include it? Check the context assembly stage
for dropped chunks. Nothing errors when a prompt is silently truncated, which
is why this failure goes unnoticed for weeks.

Step five: did the model use the context, or answer from its priors? Check
faithfulness. Only at this point is the prompt or the temperature the problem.

Tuning parameters

Chunk size too small splits answers across boundaries. Too large dilutes
relevance, so the matching sentence is a small fraction of what is sent.

Overlap prevents boundary loss but duplicates text, and near-identical chunks
compete for the same top-k slots.

Top-k too small means the right answer ranked sixth is never seen. Too large
fills the context with noise and raises cost and latency.

Reranking helps only when retrieval over-fetches first. A reranker can promote
only what retrieval already returned, so fetching three times top-k is what
makes it useful rather than cosmetic.

Hybrid search combines lexical and vector retrieval because they fail
differently. Lexical search misses paraphrase; vector search misses exact
identifiers such as error codes and API names.

Multi-tenant safety

Metadata filters must be applied before ranking, not after. A filter applied
after ranking silently shrinks top-k and, in a multi-tenant corpus, is a
display concern rather than a security boundary.

Prompt injection

A retrieved document is untrusted input. Structural separation between
instructions and retrieved content is required, and the system prompt must state
that context is data rather than commands. The fix is never a better blocklist;
it is a boundary the data cannot cross.
""",
    ),
    DocumentSpec(
        slug="forge-agent-guidelines",
        corpus="forge-docs",
        title="Agent Design Guidelines",
        source="internal/ai/agents.md",
        metadata={"team": "ai", "classification": "internal", "version": "1.1"},
        content="""
Agent Design Guidelines

State and reducers

Agent nodes return a partial state update rather than a whole state. Each key
has a reducer describing how two writes combine. Message history uses an append
reducer; token counts use an addition reducer; scalars replace.

Getting the reducer wrong is the single most common agent bug, and it presents
as the agent forgetting everything, because whichever node ran last overwrote
the history instead of appending to it.

Termination

Every agent loops eventually. A recursion limit turns an unbounded run into a
clean, diagnosable halt rather than an overnight bill.

Raising the recursion limit is not a fix. The correct fix is a termination
condition: a counter that the loop increments and the router reads. A bounded
reflection loop and an infinite one have nearly identical topology, and that one
line is the entire difference.

Cycles are not bugs. Retry loops and reflection loops are cycles. Every cycle
does, however, need a termination argument.

Self-evaluation

An agent that answers and stops has no idea whether it was right. An agent that
scores its own answer and routes low confidence to a human is the difference
between a demo and something you would put in front of customers.

The absence of retrieved context is itself grounds for escalation regardless of
stated confidence. A fluent answer produced from nothing is the dangerous case.

Human in the loop

An interrupt pauses the graph before a designated node and persists the full
state. A human approves or rejects, and the run resumes from the checkpoint.

Tool failure

Tool-calling tutorials show the happy path. The important case is what happens
when the tool raises. Retries must be bounded: unbounded retry against a
genuinely broken dependency is a denial-of-service attack you wrote against
yourself.
""",
    ),
    DocumentSpec(
        slug="forge-oncall-runbook",
        corpus="forge-docs",
        title="On-Call Runbook: API Latency",
        source="internal/ops/oncall-latency.md",
        metadata={"team": "ops", "classification": "internal", "version": "4.0"},
        content="""
On-Call Runbook: API Latency

Alert: p99 latency above 2 seconds for 5 minutes

First, determine whether this is load or a regression. Check request rate
alongside latency. Latency rising with flat traffic is a regression; both rising
together is capacity.

Common cause: N+1 queries

A single request issuing hundreds of database queries is the most common cause
of a sudden latency regression after a deploy. The signature is high query
count with low per-query duration and low CPU.

The fix is to fetch related rows in one query using a selectin or joined load
strategy, or a single WHERE IN clause, and to group in memory. Add a query-count
assertion to the test suite so the regression cannot return silently.

Common cause: a blocking call in an async endpoint

A synchronous call inside an async handler blocks the event loop. While it runs,
no other coroutine on that worker can proceed, so one slow endpoint degrades
every concurrent request on that process.

This never appears in local testing with a single user. The signature is latency
that degrades sharply with concurrency while CPU stays low.

Common cause: connection pool exhaustion

Requests queue waiting for a database connection. The signature is latency that
rises in steps rather than smoothly, and a pool-wait metric that climbs while
query duration stays flat. Usually caused by a session that is never returned.

Common cause: cache unavailability

When the cache is unreachable, every request pays a connection timeout before
falling through to the database. The correct behaviour is to treat a cache
failure as a miss immediately rather than to retry.

Losing the cache must degrade performance and never correctness. Anything whose
loss changes correctness is not a cache.

Common cause: LLM provider rate limiting

Provider 429 responses with retries produce latency that rises in multiples of
the backoff interval. Check provider dashboards and token spend before
suspecting your own code.

Escalation

If the root cause is not identified within 30 minutes, escalate. Post a status
update every 15 minutes during an active incident. The postmortem is blameless
and focuses on why the failure was possible, not on who deployed it.
""",
    ),
]

PACK = ContentPack(name="corpus", documents=DOCUMENTS)
