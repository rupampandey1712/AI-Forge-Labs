# Interview Guide

How the Interview Arena scores you, what each seniority band adds, and how to
use the debrief.

---

## What makes it an interview rather than a quiz

1. **It follows up.** A strong answer earns a harder follow-up *on the same
   thread* — "okay, but how does a decorator preserve function metadata?" — not
   a new topic.
2. **It adapts.** Two strong answers raise the tier; two weak ones lower it.
3. **It scores seven dimensions**, and tells you which one was thin.
4. **It shows the gap.** Not just a score — what a Staff answer would have added.
5. **Pressure mode has a clock**, because real interviews do.

---

## The seven dimensions

| Dimension                 | Weight | What raises it                                        |
| ------------------------- | ------ | ----------------------------------------------------- |
| **Correctness**           | 0.34   | Covering the rubric's points                          |
| **Depth**                 | 0.18   | Mechanism language: *because*, *internally*, *which means* |
| **Trade-off awareness**   | 0.13   | *however*, *at the cost of*, *depends on*, *unless*   |
| **Practical experience**  | 0.11   | Concrete cases and **numbers**                        |
| **Production awareness**  | 0.10   | Latency, failure modes, blast radius, rollback        |
| **Architecture thinking** | 0.08   | Coupling, boundaries, scaling, queues, caching        |
| **Clarity**               | 0.06   | Structure; hedging is penalised                       |

**Correctness caps everything**: `ceiling = 0.35 + 0.65 × correctness`. A wrong
answer cannot be rescued by sounding senior — which is exactly how a real
interview works.

---

## The bands, on one question

> *Why is `time.sleep()` inside an async endpoint a problem?*

**Junior — 0.4/10**
> "It makes it slow."

Names a symptom. No mechanism, no consequence, nothing actionable.

**Mid — 5.0/10**
> "`time.sleep` blocks the event loop so other requests wait. Use
> `await asyncio.sleep` instead."

Correct and complete for the question asked. Stops there. No cost, no
alternative, no evidence it has ever happened to them.

**Senior — 7.6/10**
> "`time.sleep` blocks the event loop, so every other coroutine on that worker
> stalls. In production we saw p99 go from 120ms to 4s under 50 rps. The fix is
> `await asyncio.sleep`, or `asyncio.to_thread` for genuinely blocking work.
> The trade-off is that `to_thread` costs a thread per call, so for CPU-bound
> work a worker queue is better."

Adds **measurement** (120ms → 4s at 50 rps), an **alternative**, and the
**condition** under which you would choose the other one.

**Staff — 9.3/10**
> "Internally the event loop is a single thread running a selector loop;
> `time.sleep` parks that thread, so every pending coroutine stalls for the full
> duration. In production we measured p99 going from 120ms to 4s at 50 rps, and
> the blast radius was the whole worker, not just the one endpoint. However, the
> fix depends on the workload: `await asyncio.sleep` for genuine waiting,
> `asyncio.to_thread` for blocking I/O at the cost of a thread per call, and a
> queue with dedicated workers for CPU-bound work because threads buy you
> nothing under the GIL. Operationally I would add a blocking-call detector in
> CI rather than rely on review, since this regresses easily and only shows up
> under concurrency. The failure mode is silent: latency degrades, no error is
> logged."

Not longer for its own sake. It is **comparative** (three fixes, each with its
condition), **quantified**, **failure-aware** ("the failure mode is silent"),
and it proposes a **systemic** fix rather than a one-line one.

---

## The pattern

Every band adds one thing to the one below:

```
Junior     what happens
  ↓        + why (the mechanism)
Mid        + evidence (numbers, a real case)
  ↓        + the alternative, and when you would pick it
Senior     + what breaks, and who notices
  ↓        + how you stop it recurring systemically
Staff      + what it costs the organisation
  ↓
Principal
```

If you are stuck at 5–6/10, you are almost certainly answering *completely* and
stopping. The next point comes from volunteering the trade-off before you are
asked.

---

## Structuring an answer

**Lead with the answer.** Interviewers are listening for signal in the first
fifteen seconds. Do not build to it.

**Then the mechanism.** *Why* it works, not that it works.

**Then the trade-off.** Name one alternative and the condition that would make
you choose it. This single habit is the largest score jump available.

**Then the failure mode.** What breaks, how you would notice, what it costs.

**Stop.** A 400-word answer scores lower than a 150-word one that says the same
thing — verbosity is penalised under clarity, and rambling reads as uncertainty.

---

## Confidence is scored

The slider is not cosmetic. The retention engine compares your self-report
against your actual accuracy.

- **Confident and wrong** → extra penalty, and a much earlier review. This is
  the dangerous state: you will not study it, because you think you know it.
- **Unsure and right** → calibration improves; the schedule relaxes.

Miscalibration, not ignorance, is what sinks senior interviews. You are more
likely to be caught out by something you were sure about than by something you
flagged as uncertain.

---

## Pressure mode

A per-question clock, tier-scaled (60s at tier 1 → 360s at tier 10), and the
difficulty escalates regardless of how well it is going.

Use it when you can already answer well unhurried. It trains a different skill:
producing a *structured* answer under time pressure rather than a complete one.

---

## Reading the debrief

| Field                 | How to use it                                            |
| --------------------- | -------------------------------------------------------- |
| **Verdict**           | Calibrated to the level you selected, not absolute        |
| **Dimension radar**   | Your lowest bar is the cheapest point to gain             |
| **Missing points**    | Literally what a better answer said that yours did not    |
| **Level gap**         | What the next band adds — the most actionable line        |
| **Per-question**      | Where time went; 4 minutes on a tier-3 is a signal        |
| **Recommended**       | Concepts from the categories you scored under 6.0 in      |

**The gaps are worth more than the score.** Two players both at 6.2 need
completely different practice if one is losing points on correctness and the
other on trade-offs — and the radar is the only thing that tells them apart.

---

## Readiness

`/analytics/readiness` blends weighted skill mastery with your actual answer
history. Once you have answered 10+ questions, real performance starts
displacing self-study mastery in the estimate (up to 35% weight at 50 answers) —
because evidence outranks preparation.

It never returns a bare number. Every component reports its weight, current
value, contribution and **headroom**, so "where does an hour of work buy the
most" is answerable directly:

```
Python            82%  weight 18%   contributing 0.148   headroom 0.032
System Design     31%  weight 12%   contributing 0.037   headroom 0.083  ← here
Production        24%  weight 10%   contributing 0.024   headroom 0.076  ← or here
```

A composite score without its components is a number. With them, it is a plan.
