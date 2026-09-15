# Learning Path

The curriculum, band by band. Each band lists what you are expected to be able
to *do*, not what you have read.

A reminder on framing: these bands model **the problems an engineer at that
level is expected to solve**. Finishing them does not hand you the years, and
the game never claims otherwise.

---

## Band 0–1 · Fundamentals

**Rank**: Python Apprentice → Python Developer (levels 1–11)
**District**: Python Academy, Interview Arena (junior)

### You can

- Explain that names are bound to objects, and predict aliasing behaviour
- Choose between list / tuple / set / dict *from the cost model*, not habit
- Write comprehensions and know when a loop is more readable
- Use `*args`/`**kwargs` correctly, and know why `**kwargs` is usually a smell
- Catch narrowly, chain with `from`, and never write `except: pass`
- Recognise the mutable-default trap on sight

### The tier ladder here

| Tier | Looks like                                                  |
| ---- | ----------------------------------------------------------- |
| 1–2  | "What does `a is b` test?"                                   |
| 3    | "De-duplicate this list, preserving order, in O(n)"          |
| 4    | "Customers see each other's baskets. Find the bug."          |

### Boss

**The Basket Incident** — a `def add_item(item, basket=[])` leaking state across
three days of requests. You write the root-cause section of the postmortem, and
the debrief is about why code review and CI both missed it.

---

## Band 1–3 · Application development

**Rank**: Backend Engineer (levels 12–21)
**Districts**: Backend City, Production City, Data Science Lab

### You can

- Build a FastAPI service with real Pydantic contracts and response models that
  exclude internal fields
- Explain dependency injection and what breaks when a singleton depends on a
  request-scoped resource
- Model relationships in SQLAlchemy and choose a loading strategy deliberately
- Write an Alembic migration that reverses cleanly
- Vectorise a pandas pipeline and prove the speedup with a measurement
- Write tests that would actually catch a regression

### Key distinction taught here

**dataclass vs NamedTuple vs TypedDict vs Pydantic.** The rule is about *trust*,
not safety-in-general: data crossing a boundary must be parsed (Pydantic); data
you constructed five lines ago needs structure (dataclass). Validating four
times in an internal pipeline costs throughput and catches nothing a type
checker would not have caught earlier.

### Boss

**The Framework That Forgot Its Name** — `forge-core` applies four decorators to
every endpoint. FastAPI builds the wrong request model, Sentry groups every
error under `wrapper`, and a `TypeError` gets retried five times. You rebuild the
decorator layer, then argue whether the architecture should survive at all.

---

## Band 3–5 · Architecture and production debugging

**Rank**: Senior Python Engineer → ML Engineer (levels 22–41)
**Districts**: Debugging Dungeon, ML Arena, Architecture Tower

### You can

- Read logs, metrics, stack traces and query plans and form a hypothesis
- Find an N+1 from a query count, not from being told it is there
- Explain the GIL precisely, and choose between asyncio / threads / processes
  from the workload rather than from fashion
- Diagnose why async code is *slower* than the sync version it replaced
- Evaluate a model honestly — leakage, the right metric, bias/variance
- Design a system for 1M requests/day and say what changes at 10M

### The debugging method taught

1. Reproduce
2. Read the evidence before forming a theory
3. Bisect — in time, in code, in data
4. Form a falsifiable hypothesis
5. Test it cheaply
6. Fix the cause, not the symptom
7. Write down why it was missed

### Boss

**Database Performance Disaster** — a single request issuing 5,000 queries. You
get the slow-query log, the ORM code and the endpoint's latency trace.

---

## Band 5–7 · Distributed systems and AI

**Rank**: Deep Learning Engineer → LLM Engineer (levels 42–71)
**Districts**: Deep Learning Lab, Transformer Center, RAG Tower, Agent Factory

### You can

- Build and debug a PyTorch training loop — exploding gradients, NaN loss,
  a model that memorises the training set
- Derive attention from Q/K/V and explain why scaling by √d matters
- Explain why Transformers need positional information injected at all
- Build a RAG pipeline and debug *why* it retrieves the wrong document
- Choose chunk size and overlap from a measurement on a golden set
- Build a LangGraph agent whose termination you can prove
- Reason about token cost and latency as first-class design constraints

### The RAG debugging ladder

When the chatbot is confidently wrong, in order:

1. Is the answer *in* the corpus at all?
2. Did retrieval return it? (retrieval precision/recall)
3. Did the chunk contain enough context to answer? (chunking)
4. Did the prompt actually include it? (context window, truncation)
5. Did the model use it, or answer from its priors? (faithfulness)

Most teams start at step 5 and change the prompt. It is almost always step 2
or 3.

### Boss

**Enterprise Chatbot Hallucination Crisis** — the assistant cites a policy that
does not exist. You get the trace, the retrieved chunks, the prompt and the
golden set.

---

## Band 7–10 · Technical leadership

**Rank**: AI Platform Engineer → Staff AI Engineer (levels 72–94)
**Districts**: AI War Room, Staff Engineer HQ

### You can

- Run an incident: diagnose under time pressure, communicate status, write a
  blameless postmortem
- Design an evaluation pipeline that *gates a deploy*, and defend the threshold
- Build observability you would actually use at 3am
- Argue an abstraction's cost as confidently as its benefit
- Say what breaks at 10× and at 100×
- Name a decision you would reverse, and why

### Incidents

```
02:13  ALERT  API latency p99: 200ms → 8s

Available: logs · metrics · traces · database stats · code · deploy history
Scored on: time to diagnosis · correctness · explanation · fix quality
```

Possible root causes across the incident library include N+1 regressions, LLM
provider rate limits, Redis unavailability, GPU OOM, a connection pool
exhausted by a leaked session, and a cache stampede after a deploy.

---

## Band 10+ · Principal

**Rank**: Principal AI Engineer (levels 95–100)
**District**: Staff Engineer HQ

### The capstone

**AI-Powered Enterprise Catalogue Platform** — nine milestones:

| # | Milestone           | The acceptance criterion that actually matters                       |
| - | ------------------- | -------------------------------------------------------------------- |
| 1 | Foundation          | Migrations reverse cleanly; auth rejects wrong-*type* tokens          |
| 2 | Search              | EXPLAIN ANALYZE shows index scans; a query-count test guards N+1      |
| 3 | Async ingestion     | A worker crash mid-document loses and duplicates nothing              |
| 4 | RAG                 | Chunking parameters justified by measurement, not by defaults         |
| 5 | Agent               | The graph provably terminates on every path                           |
| 6 | Evaluation          | CI fails on a faithfulness regression; you can defend the threshold   |
| 7 | Observability       | A slow request is attributable to a span in under a minute            |
| 8 | Hardening           | Tenant A cannot read tenant B's documents — proven by a test          |
| 9 | **The Defence**     | Every box on your diagram is fair game                                |

The final milestone has no test suite. A Staff and a Principal engineer ask why,
what breaks at 100×, and what you would do differently. There is no right
answer — only defensible and indefensible ones, and the difference is whether
you can name the condition that would change your mind.

---

## How the game sequences this for you

You do not follow this document. The game builds each day's session from your
own state:

- **Repair** whatever the forgetting curve says is slipping
- **Target** the mistake patterns still open against you
- **Push** one tier above your demonstrated ceiling — never at it
- **Rotate** through areas you have been neglecting
- **Always** one interview question, at your current band

This document exists so you can see the shape of the thing. The daily mission is
how you actually walk it.
