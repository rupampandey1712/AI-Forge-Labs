# Game Design

How progression, rewards, difficulty and retention actually work — with the
numbers, and the reasoning behind them.

---

## 1. The central problem

Most technical learning tools have the same failure mode: you finish, you feel
competent, and six months later you cannot remember how `functools.wraps` works.
The tool has no opinion about this, because its model of you is "completed: yes".

This game's model of you is a **forgetting curve per concept**. That single
decision drives everything else — the daily mission, the dashboard hierarchy,
the alerts, even why mastery has a ceiling.

---

## 2. The retention engine

### State

Every (player, concept) pair carries a `ReviewState`:

| Field            | Meaning                                                           |
| ---------------- | ----------------------------------------------------------------- |
| `stability_days` | Decay constant `S` — larger means slower forgetting                |
| `ease`           | SM-2 multiplier: how easily *this* concept sticks for *this* player |
| `interval_days`  | Current scheduling gap                                             |
| `mastery`        | Durable competence (EWMA over tier-weighted performance)            |
| `peak_mastery`   | High-water mark — what the dashboard measures the drop against     |
| `lapses`         | Failures after a success; compounds the schedule                   |

### The curve

```
R(t) = exp(-t / S)        S = interval / -ln(0.90)
```

Recall probability decays exponentially since the last review. `S` is derived
from the scheduled interval such that `R(interval) = 0.90` — so the scheduler's
promise is legible: *at your due date, you should recall this about 90% of the
time*.

**Why exponential rather than FSRS' power law**: one parameter, trivially
explainable to the player (the game teaches its own mechanics in the Retention
Dashboard), and the divergence from the power law only matters at intervals far
beyond this game's horizon. The adaptivity lives in the scheduler, not the curve.

### Effective mastery — the number on screen

```
effective = mastery × (0.35 + 0.65 × R(t))
```

The `0.35` floor is **Ebbinghaus' savings effect**: relearning is dramatically
faster than first learning. A concept you once mastered and abandoned for a year
lands at ~35% of peak, not 0%.

That is also the right game design. Returning after a long absence should feel
like **rust, not amnesia** — amnesia makes people quit.

### Scheduling

Early reviews follow the canonical ladder (**1, 3, 7, 14, 30, 60, 90 days**),
modulated by ease so a player who nails everything moves through it faster.
After the ladder, `interval × ease` takes over and the schedule becomes personal.

| Event                  | Effect                                                      |
| ---------------------- | ----------------------------------------------------------- |
| Clean pass             | Interval grows; ease +0.10 at perfect quality                |
| Barely passed          | Interval grows less (`0.75 + 0.35 × quality`)                |
| Failure                | Interval → ¼, repetitions reset, lapse recorded              |
| Repeated failures      | Compound — `0.25 / (1 + 0.5 × lapses)`                       |
| Hints used             | Quality penalty (0.15 each, capped) ⇒ shorter interval       |
| **Confident + wrong**  | Extra penalty. Miscalibration sinks interviews.              |

Hints are not free on purpose: a solution reached after three hints was
*reconstructed with help*, not recalled. Scheduling it like a clean recall would
make the player forget it again right before the interview that matters.

### Alerts

| Recall `R` | State      | What happens                                     |
| ---------- | ---------- | ------------------------------------------------ |
| < 0.90     | Due        | Appears in "due now", eligible for a daily slot  |
| < 0.72     | Decayed    | Dashboard alert, shown with the mastery drop     |
| < 0.45     | Critical   | Emergency framing, highest daily priority        |

Alerts are grouped **by skill, not per concept**. "12 separate concepts decayed"
is noise a player learns to dismiss; *"your RAG knowledge fell from 84% to 61% —
here is the repair mission"* is something they act on.

### Urgency

```
urgency = 0.55 × (1 − R) + 0.45 × min(1, drop / 0.5) + 0.05 × min(3, lapses)
```

Deliberately weights **how much was lost** as heavily as how low it is now.
Forgetting a concept you had at 95% matters more than one you only reached 40%
on — the first represents real invested effort now decaying.

---

## 3. Mastery has a ceiling

The most important anti-gaming rule in the game.

| Deepest tier cleared | Mastery ceiling |
| -------------------- | --------------- |
| 1 (Remember)         | 25%             |
| 3 (Implement)        | 58%             |
| 5 (Optimize)         | 80%             |
| 8 (Production)       | 96%             |
| 10 (Principal)       | 100%            |

You **cannot** reach 90% mastery of asyncio by answering tier-1/2 questions
about it forever. The ceiling forces depth, and it is what stops the game from
asking "what is a list?" for eternity — the answer stops moving the number.

Mastery gains are also **tier-weighted** (×0.35 at tier 1, ×1.10 at tier 10), so
clearing a staff-level trade-off says far more about competence than clearing
twenty recall questions.

---

## 4. Progression

### Levels

```
total_xp(level) = 100 × level^1.6
```

| Level | Cumulative XP | Rank                    |
| ----- | ------------- | ----------------------- |
| 1     | 0             | Python Apprentice       |
| 5     | 918           | Python Developer        |
| 12    | 4,636         | Backend Engineer        |
| 22    | 13,048        | Senior Python Engineer  |
| 52    | ~54,000       | AI Engineer             |
| 84    | ~118,000      | Staff AI Engineer       |
| 95    | 143,550       | Principal AI Engineer   |
| 100   | 155,961       | —                       |

Superlinear so early levels arrive fast enough to build a habit while
Principal-tier levels demand sustained work.

### Rewards

Base XP per tier is superlinear — a tier-9 trade-off is worth **13×** a tier-1
recall question:

| Tier | 1  | 3  | 5  | 8   | 10  |
| ---- | -- | -- | -- | --- | --- |
| XP   | 10 | 32 | 62 | 110 | 160 |

On top of that, bonuses point at what good engineering *is*:

| Bonus              | ×    | What it rewards                          |
| ------------------ | ---- | ---------------------------------------- |
| First attempt      | 0.30 | Getting it right without guessing        |
| Speed (under par)  | 0.20 | Fluency, capped so a lucky submit is not gamed |
| **Explanation**    | 0.35 | Articulating *why* — the highest single bonus |
| Architecture       | 0.40 | Reasoning about structure                |
| Bug found          | 0.50 | Reading evidence                         |
| Optimisation       | 0.45 | Logarithmic in speedup — 100× feels great, not 50× better than 2× |
| Clean code         | 0.25 | No critical defects in a passing solution |
| Boss               | 2.50 | —                                        |

**Every award is itemised** and shown to the player:

```
+110  challenge_passed      Tier 8 objective cleared
+33   first_attempt_bonus   Solved on the first attempt
+30   explanation_bonus     Explained the WHY
+27   bug_found             Identified 2 defect(s)
+27   difficulty_bonus      Senior-plus difficulty
```

That is not decoration. Players learn the reward function, and the reward
function is an argument about what matters.

**Failure still pays 8%.** The game must never punish *engaging* with a hard
problem — only reward solving it far more.

### The balance guarantee

`test_grinding_tier_one_cannot_beat_deep_work` asserts tier 9 > tier 1 × 10. If
a balance change ever breaks that, CI fails. Depth must always dominate volume.

---

## 5. The daily mission

Not a random quiz. Slots are filled from prioritised pools:

| Priority | Pool         | Max | Selected because                                    |
| -------- | ------------ | --- | --------------------------------------------------- |
| 1        | **Repair**   | 3   | Recall has fallen — highest urgency first           |
| 2        | **Mistake**  | 2   | Targets an open *pattern*, not the exact exercise   |
| 3        | **Frontier** | 2   | One tier above the demonstrated ceiling             |
| 4        | **Breadth**  | 1   | Least-recently-practised unlocked area              |
| 5        | **Interview**| 1   | Always exactly one, at the current level            |

**Every slot shows its reason**:

> *"Recall probability has fallen to 61% (34 days since practice). Mastery 88% → 54%."*
>
> *"You have hit "Mutable default argument" 3×. This exercises the same pattern."*
>
> *"Python: you have cleared tier 5. This is tier 6 — one step past your current ceiling."*

A daily that looks arbitrary gets skipped. A daily that explains itself gets
done. The reason line is the retention mechanism made legible.

**The plan is persisted and cannot be rerolled.** Regenerating would let players
dodge precisely the concepts the model says they are about to lose — which is
the one thing this feature exists to prevent.

---

## 6. Adaptive difficulty

Three mechanisms, all pulling the same direction:

1. **Never repeat.** Questions seen in the last 45 days are excluded.
2. **Frontier targeting.** The daily aims one tier above `highest_tier_cleared`,
   never at it.
3. **Interview pressure.** Two strong answers in a row raise the tier; two weak
   ones lower it. A strong answer also earns a *follow-up on the same thread*
   rather than a new topic.

So the progression for a single concept is:

```
"What is a list?"                                      → stops appearing
"Why might a list be inappropriate here?"              → tier 4
"What happens internally when you append?"             → tier 5
"This endpoint times out in production. Why?"          → tier 8
"Would you keep this design at 100× the data?"         → tier 9
```

---

## 7. Failure is a postmortem

Never the word "Wrong". A failed submission returns:

```
🚨 Production incident: request timeout

What happened
  Your code did not finish inside the 8s limit, so the request was killed.

Likely root cause
  An unbounded loop, runaway recursion, or an algorithm a complexity class
  too slow for this input size.

💡 What is the time complexity of `x in some_list`? Now put that inside a loop.
```

Plus: which tests failed and why, patterns detected in the code with the reason
each matters, and — after four genuine attempts — the reference solution with
its explanation.

Hidden tests reveal only *that* they failed, never their data. Otherwise a
player reconstructs the whole hidden suite from failure diffs.

---

## 8. The mistake database

A mistake is a **named, reusable pattern**, not a wrong answer.

```
pattern:          blocking_call_in_async
severity:         critical
why it matters:   One blocking call stalls every concurrent request on that
                  worker. It does not show up in local testing with one user.
correct approach: await asyncio.sleep(...), or asyncio.to_thread for genuinely
                  blocking work.
```

`occurrences` increments rather than creating duplicate rows — one pattern is
one lesson, not three cards. The record closes only after **3 consecutive clean
submissions**: getting it right once is luck, three times in a row is a changed
habit.

The daily generator then targets the *pattern*, not the exercise the player
failed.

---

## 9. Interview scoring

Seven dimensions (weights sum to 1.0):

| Dimension               | Weight | Detected from                                  |
| ----------------------- | ------ | ---------------------------------------------- |
| Correctness             | 0.34   | Weighted rubric-point coverage                 |
| Depth                   | 0.18   | Mechanism language, worked specifics           |
| Trade-off awareness     | 0.13   | Comparative language, stated conditions        |
| Practical experience    | 0.11   | Concrete cases, **numbers**                    |
| Production awareness    | 0.10   | Latency, failure modes, blast radius, rollback |
| Architecture thinking   | 0.08   | Coupling, boundaries, scaling                  |
| Clarity                 | 0.06   | Structure; penalised for hedging               |

**Correctness caps the total**: `ceiling = 0.35 + 0.65 × correctness`. An answer
that is wrong cannot be rescued by sounding senior.

Measured discrimination on one question:

| Answer  | Score | Verdict      |
| ------- | ----- | ------------ |
| Junior  | 0.4   | No hire      |
| Mid     | 5.0   | Lean no hire |
| Senior  | 7.6   | Hire         |
| Staff   | 9.3   | Strong hire  |

The staff answer is not *longer*. It is **comparative, quantified and
failure-aware** — which is exactly what the signal groups detect.

Every score ships with the gap:

> **A staff answer would** compare at least one alternative and state the
> condition under which you would choose the other one.

That gap is the part players actually learn from.

---

## 10. Streaks, and being humane about them

A streak survives **one missed day**. Rewarding perfection punishes the player
who gets sick on day 40, and losing a long streak is the single most common
reason people abandon a daily-practice app permanently.

The streak bonus is also **capped at 30 days**, so an unbounded multiplier never
distorts the XP economy.

---

## 11. The visual direction

> "modern software engineering + RPG + futuristic AI laboratory" — and
> explicitly **not childish**.

- Deep navy ground, not pure black. One cyan accent that *means* something
  (progress, focus, live).
- **Red is reserved for incidents.** When the Debugging Dungeon turns red it
  reads as an alarm, because red is not used for decoration anywhere else.
- No confetti, no mascots. A level-up is a precise number with an itemised
  breakdown — a system notification from a console that respects you.
- Animation is used where it carries information: the decay bar's ghosted
  segment, the pulsing ring on a building with an alert, the forecast line
  bending downward. `prefers-reduced-motion` is honoured throughout.

---

## 12. The badge/achievement split

**Badges** mark a moment ("you did the thing"). **Achievements** track a journey
and have a progress bar. Mixing the two makes both feel arbitrary.

Both are **declarative**: a small JSON criteria object interpreted by one
function in `app/game/achievements/rules.py`. Adding a badge is seed data, not
code — and CI verifies that every criteria key is one the interpreter actually
understands, so a badge can never be unearnable because of a typo.
