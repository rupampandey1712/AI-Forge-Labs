# ADR-001 — A modular monolith with exactly one service split

**Status:** Accepted
**Date:** 2026-09-20

## Context

AI Forge Labs has clean internal seams: a pure game engine (XP, retention,
grading), a content pipeline, an AI layer (RAG, agents, evaluation), a sandbox,
and an HTTP API. Each has a well-defined interface and few dependencies on the
others.

A codebase shaped like that invites the question of whether the seams should be
network boundaries. The request that prompted this decision was explicit:
*"make it a microservice architecture"*, backed by an Azure subscription with
the services available to do it.

Two other facts bear on the decision:

- **Spec §49:** "Avoid unnecessary abstractions. Do NOT build enterprise
  architecture simply for the sake of looking enterprise. Every abstraction must
  have a reason."
- **Spec §35/§66:** "The game must NOT execute arbitrary player code directly
  inside the main FastAPI process… Clearly separate GAME SERVER from CODE
  EXECUTION SANDBOX."

Those two are not in tension. The first says do not split without a reason; the
second supplies a reason for exactly one split.

## Decision

**The application stays a modular monolith, except for the code execution
sandbox, which is a separate service.**

Concretely:

- `aiforge-api` — the game server. Owns the database, the JWT signing key, the
  game engines, the AI layer and the HTTP API. Executes no player code.
- `aiforge-sandbox-service` — executes player code. No database, no credentials,
  no public ingress. Authenticates one caller with a shared secret.
- `aiforge-web` — the built SPA behind nginx.

## Why the sandbox is split

The sandbox is the one component where a network boundary buys something a
module boundary cannot: **a trust boundary**.

The sandbox runs code written by an adversary who is invited to try. The
subprocess and Docker backends contain that on one host — rlimits, a scrubbed
environment, a throwaway working directory, dropped capabilities, no network.
Those are real, and they are all defences *within* a process tree that also
contains the database credentials and the signing key.

Splitting changes the shape of a compromise:

| | Game server | Sandbox |
|---|---|---|
| Public ingress | yes | **no** |
| Database credentials | yes | no |
| JWT signing key | yes | no |
| Can spawn processes | **no** | yes |
| Runs untrusted code | **no** | yes |
| Egress | to Postgres, Redis, LLM | none |

An attacker who escapes the interpreter inside the sandbox reaches a container
whose entire purpose is running arbitrary code, with no credentials and no
network. That is a materially different outcome from reaching the process that
holds the database.

The boundary is enforced by a test rather than by discipline:
`tests/integration/test_sandbox_service.py::test_the_service_imports_nothing_from_the_game`
parses the service's AST and fails if it imports anything outside `app.sandbox`.

## Why nothing else is split

Consider the candidates, and what a network boundary would cost each:

**Game engine (XP, retention, grading).** Pure functions with no I/O. A service
here would turn a microsecond function call into a millisecond HTTP round trip,
and submitting one challenge touches grading, XP, retention, skills, badges and
mistakes — six calls, six failure modes, and a distributed transaction problem
where there is currently a single database transaction. The seam is already
clean; making it remote adds only latency and partial-failure states.

**AI layer (RAG, agents, evaluation).** This is the most plausible candidate,
because its scaling profile genuinely differs — it is I/O-bound on a provider
API while the rest is database-bound. But it holds no state the API does not
already have, it is called synchronously in the request path, and its dependency
footprint (numpy, httpx) is already in the API image. The argument for splitting
it is "different scaling profile", and Container Apps scales the whole API on
concurrency anyway, so the win is theoretical.

**Content pipeline.** Runs at seed time, not at request time. It is a CLI.

**Auth.** One `users` table and one signing key, in the same database as
everything else. Splitting it means either a shared database — which is the
distributed monolith anti-pattern — or a network call on every single request.

### The costs that would be incurred

Every split adds: a network hop and its failure modes, serialisation at the
boundary, a contract to version, distributed tracing to debug what a stack trace
used to show, an independent deployment to coordinate, and the loss of
transactional consistency across the boundary.

For a single-player learning game running on one Container Apps environment,
those costs are paid in full and the benefits — independent scaling, independent
deployment, team autonomy, fault isolation — are worth close to nothing. There
is one team. There is one deployment. The load is one person practising.

## Consequences

**Good:**

- Submitting a challenge is one database transaction. It either all happened or
  none of it did, with no compensating actions and no saga.
- Debugging is a stack trace rather than a trace correlation across services.
- The security property the spec requires is enforced, and tested.
- The seams still exist as modules, so any of them *can* be extracted later if a
  real reason appears. The cost of deferring is low precisely because the
  internal boundaries are already clean.

**Bad, and accepted:**

- The API image carries the AI layer's dependencies even for deployments that
  never use them.
- Scaling the API scales everything in it.
- "Microservices" is not on the architecture diagram, which is a real
  conversation to have with anyone who expected it.

**The trigger to revisit:** if the AI layer's latency profile starts affecting
API tail latency in a way connection pooling and concurrency limits cannot fix,
or if a second team takes ownership of a subsystem. Neither is true today, and
"we might need it later" is the argument this ADR exists to reject.

## In the game

This decision is itself content. The Architecture Tower asks players to defend
a monolith-versus-microservices split on a system whose constraints are stated,
and the rubric rewards naming what the boundary *buys* over listing what
microservices are. The answer above is the one the mission is looking for: not
"monoliths are better" and not "microservices are better", but *which boundary
is a trust boundary, and what does a compromise cost on either side of it*.
