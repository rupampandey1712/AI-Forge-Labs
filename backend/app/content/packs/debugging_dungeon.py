"""The Debugging Dungeon — method, evidence, and production incidents.

WHY DEBUGGING GETS ITS OWN PACK: it is the highest-leverage engineering skill and
almost the only one never taught deliberately. People learn syntax from courses
and debugging from suffering.

The distinguishing claim of this pack is that debugging is a *method*, not a
talent. The method is: reproduce, bisect the search space, form one falsifiable
hypothesis, test it cheaply, and only then change code. Engineers who look fast
are not guessing better — they are guessing less. Every concept here is an
instance of that method applied to a domain where the evidence is unusual:
async, concurrency, memory, or a probabilistic model.

Incident missions carry real artefacts — logs, metrics, stack traces, a p99
graph — because a debugging exercise with no evidence to read is a quiz.
"""

from __future__ import annotations

from app.content.schema import (
    ChallengeSpec,
    ConceptSpec,
    ContentPack,
    MissionSpec,
    MissionStepSpec,
    QuestionSpec,
    example,
    mistake,
    opt,
    point,
    script,
)
from app.domain.enums import Category, Severity
from app.domain.enums import DifficultyTier as T
from app.domain.enums import InterviewLevel as L
from app.domain.enums import QuestionKind as Q

D = Category.DEBUGGING
P = Category.PRODUCTION

# ═════════════════════════════════════════════════════════════════════════════
# CONCEPTS
# ═════════════════════════════════════════════════════════════════════════════
CONCEPTS = [
    ConceptSpec(
        slug="debug-method",
        title="The Method — Why Fast Debuggers Guess Less",
        category=D,
        skill_node="dbg.method",
        difficulty=4,
        summary=(
            "Debugging is binary search over a space of hypotheses. The skill is halving the "
            "space cheaply, not intuiting the answer."
        ),
        explanation="""
Watch someone debug quickly and it looks like intuition. It is almost never
intuition. It is a loop, run deliberately:

**1. Reproduce it reliably.** A bug you cannot trigger on demand cannot be
verified as fixed — you will only ever know it has not happened *recently*. If
it is intermittent, work on reproduction first; that is the real task, and it is
worth hours.

**2. Bisect the space.** Not the code — the *space of possible causes*. Is it
the client or the server? Before or after deployment? One user or all users?
Each answer halves what remains. `git bisect` is the mechanised version of this
idea, and it is underused because people forget the bug is in a commit range.

**3. One falsifiable hypothesis at a time.** "The cache is stale" is testable.
"Something is wrong with caching" is not. The discipline is stating what you
expect to observe *before* you look, because otherwise any observation can be
made to fit.

**4. Test it as cheaply as possible.** A print statement beats a debugger
session; a debugger session beats a code change; a code change beats a deploy.
Most people skip straight to the expensive end.

**5. Change one thing.** Change three and the bug disappears — and you have
learned nothing, cannot revert safely, and will meet it again.

**The anti-pattern this replaces** is changing plausible-looking things until
the symptom stops. It sometimes works, teaches nothing, and leaves two unrelated
modifications in the codebase that nobody can justify later.

**And the question that ends most hard bugs**: *what changed?* Code, config,
data, dependency, traffic, or time. A system that worked on Tuesday and fails on
Wednesday has a diff somewhere, and finding it is nearly always faster than
reasoning from first principles about the code.
""",
        examples=[
            example(
                "Bisecting a space, not a file",
                """
# Symptom: checkout fails for some users.
# Bad:  read checkout.py looking for something wrong.
# Good: halve the space with one cheap observation each time.
#
#   All users or some?          -> some        (rules out global config)
#   Do the failures share a trait? -> all have >1 saved card
#   When did it start?          -> Tuesday's deploy touched payment methods
#
# Three questions, and the search space is one function in one commit.
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Changing several things at once",
                "If the symptom stops you cannot attribute the fix, so you have not learned the "
                "cause and cannot be sure it is gone.",
                "One change, one observation. Revert anything that did not help.",
                Severity.HIGH,
            ),
            mistake(
                "Debugging without a reliable reproduction",
                "Every 'fix' is unfalsifiable. You can only observe that it has not recurred "
                "yet, which is indistinguishable from luck.",
                "Invest in reproduction first, even when it takes longer than the fix.",
                Severity.HIGH,
            ),
            mistake(
                "Never asking what changed",
                "Reasoning from first principles about code that worked yesterday ignores the "
                "single most informative piece of evidence available.",
                "Check deploys, config changes, dependency updates, data shape and traffic "
                "before reading code.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Cutting a four-hour investigation to twenty minutes by asking what changed",
            "The interview question behind every 'tell me about a hard bug' prompt",
        ],
        related=["debug-async-blocking", "debug-performance-evidence"],
        tags=["debugging", "method"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="debug-performance-evidence",
        title="Profile, Don't Guess",
        category=D,
        skill_node="dbg.performance",
        difficulty=5,
        summary=(
            "Intuition about where time goes is reliably wrong. The bottleneck is almost never "
            "the clever code you remember writing."
        ),
        explanation="""
Every experienced engineer has a story about optimising the wrong thing for a
day. It happens because attention is drawn to complexity, and complexity is not
where time goes — waiting is.

**Measure before, and measure after.** "It feels faster" is not a result. Record
the before number so the after number means something, and so a regression later
has a baseline to be compared against.

**Know which tool answers which question:**

* `cProfile` — where CPU time goes, per function. First stop for a slow script.
* `py-spy` — samples a *running* process without restarting it. The only option
  that works on a production service you cannot stop.
* `tracemalloc` — where memory was allocated. Answers "why is this growing".
* `EXPLAIN ANALYZE` — where database time goes. For most web services this is
  the answer, and no Python profiler will ever tell you.
* Distributed tracing — where the time went across services. Nothing local can
  see this.

**Read `tottime`, not `cumtime`.** Cumulative time includes callees, so `main`
is always at the top and always useless. Total time is the work done *in* that
function, and that is what you can act on.

**The counter-intuitive shape of real profiles:** the hot function is usually
boring — a `.sum()` inside a loop, a serialiser, a repeated database round-trip.
It is boring precisely because nobody looked at it. The clever algorithm you
remember tuning runs once.

**And check whether you are CPU-bound at all.** If the process is at 4% CPU, no
amount of Python optimisation will help — you are waiting on I/O, and the fix is
concurrency, batching, or a database index. Profiling CPU time in an I/O-bound
service is a day spent measuring the wrong axis.
""",
        examples=[
            example(
                "The N+1 that no Python profiler blames",
                """
# Profile says: 78% of time in `execute`. Not a Python problem.
for order in orders:              # 500 orders
    customer = db.get(order.customer_id)   # 500 round trips at 2ms = 1s

# One query instead of 501:
customers = db.get_many({o.customer_id for o in orders})
""",
                note="The Python code looks innocent and is innocent. The cost is the round "
                "trips, which is why the database answers this question and cProfile does not.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Optimising without profiling",
                "Attention is drawn to complex code, and time is spent in boring code. The "
                "correlation between the two is close to zero.",
                "Profile first. Every time, including when you are sure.",
                Severity.HIGH,
            ),
            mistake(
                "Reading cumtime and optimising main()",
                "Cumulative time includes everything called, so the top of the list is always "
                "the entry point and always unactionable.",
                "Sort by tottime to find where the work actually happens.",
                Severity.MEDIUM,
            ),
            mistake(
                "Profiling CPU in an I/O-bound service",
                "The process is idle waiting on the network or disk. Optimising the 4% that is "
                "CPU changes nothing.",
                "Check CPU utilisation first. If it is low, the answer is concurrency, batching "
                "or the database.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Finding that 78% of an endpoint is one unindexed query",
            "Attaching py-spy to a wedged production worker without restarting it",
        ],
        requires=["debug-method"],
        tags=["debugging", "performance"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="debug-async-blocking",
        title="The Blocking Call in the Event Loop",
        category=D,
        skill_node="dbg.concurrency",
        difficulty=7,
        summary=(
            "One synchronous call inside an async handler stalls every concurrent request on "
            "that worker. It is invisible under light load and catastrophic under real load."
        ),
        explanation="""
An async event loop runs one task at a time and switches at `await`. That is the
entire contract, and it is why a single blocking call is so destructive: while
`requests.get()` waits three seconds, the loop cannot run *anything else*. Every
other in-flight request on that worker waits too.

**Why it survives code review and staging.** With one request at a time, the
behaviour is identical to synchronous code — the endpoint takes 300ms and nobody
notices. The failure only appears under concurrency, which is exactly the
condition staging does not have. It ships.

**What it looks like in production:** p50 fine, p99 catastrophic. Latency that
grows with traffic rather than with payload size. CPU low, throughput capped,
and adding workers helps linearly — which is the tell, because a genuinely
async service should not need that.

**The usual offenders**, all of which look harmless:

* `requests` instead of `httpx.AsyncClient`
* `time.sleep()` instead of `asyncio.sleep()`
* a synchronous database driver under an async ORM
* `open().read()` on anything larger than trivial
* CPU-bound work — a big JSON parse, a hash, an image resize

**The fixes, in order of preference.** Use the async library if one exists. If
not, `await asyncio.to_thread(blocking_fn)` moves it off the loop. For CPU-bound
work a thread does not help because of the GIL — that needs a process pool.

**Detection is mechanical**, which is the good news. `asyncio` debug mode logs
any callback that blocks longer than 100ms. Ruff's ASYNC rules catch most of
these statically. A CI lint rule is better than a review habit, because review
habits do not survive a busy week.
""",
        examples=[
            example(
                "Same code, two behaviours",
                """
@app.get("/report")
async def report():
    data = requests.get(UPSTREAM).json()    # blocks the WHOLE loop for 3s
    return summarise(data)

# 1 concurrent request:   3s   (looks fine)
# 50 concurrent requests: 150s for the last one (the loop is serialised)

@app.get("/report")
async def report():
    async with httpx.AsyncClient() as client:
        data = (await client.get(UPSTREAM)).json()
    return summarise(data)
# 50 concurrent requests: ~3s for all of them
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Using a sync HTTP client inside an async handler",
                "The event loop is blocked for the whole call, so concurrency drops to one and "
                "p99 latency grows with traffic.",
                "Use httpx.AsyncClient, or wrap the call in asyncio.to_thread if no async "
                "client exists.",
                Severity.CRITICAL,
            ),
            mistake(
                "Assuming a thread pool fixes CPU-bound work",
                "The GIL means threads do not run Python bytecode in parallel. The loop is "
                "unblocked but the work is not faster and CPU contention gets worse.",
                "Use a process pool for CPU-bound work, or move it out of the request path.",
                Severity.HIGH,
            ),
            mistake(
                "Validating async behaviour with a single request",
                "The bug is invisible without concurrency, which is precisely why it reaches "
                "production.",
                "Load-test with real concurrency, and enable asyncio debug mode in CI.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Diagnosing a service whose p99 tripled after a traffic increase",
            "Explaining why adding workers 'fixed' it and why that is not a fix",
        ],
        requires=["debug-method"],
        related=["debug-performance-evidence"],
        tags=["debugging", "async", "production"],
        estimated_minutes=11,
    ),
    ConceptSpec(
        slug="debug-ai-nondeterminism",
        title="Debugging Systems That Are Not Deterministic",
        category=D,
        skill_node="dbg.ai",
        difficulty=8,
        summary=(
            "You cannot bisect a probabilistic system one run at a time. The method still "
            "applies — but the unit of evidence becomes a distribution."
        ),
        explanation="""
Every debugging habit assumes reproducibility, and an LLM-backed system breaks
that assumption. Adapting is mostly about changing what counts as evidence.

**One run is an anecdote.** A change that fixes the failing example may have
done nothing — you resampled. The unit of evidence is a *set* of cases and a
rate, so nothing is debugged until it is measured over the eval set. This is the
hardest habit to acquire, because a single dramatic before/after is very
persuasive and usually meaningless.

**Pin what you can, and know what you cannot.** Seed and temperature reduce
variance. They do not eliminate it: batched GPU inference reorders
floating-point reductions, so identical requests can still diverge at
temperature 0. Treat determinism as best-effort and version-pin the model —
a silent provider-side model update is a real and common cause of "it broke and
nothing changed".

**Bisect the pipeline, not the model.** An AI system is mostly deterministic
components with one probabilistic component in the middle. Retrieval, parsing,
tool dispatch and post-processing are all testable normally. Isolate the
stochastic part before concluding it is at fault — and it usually is not, which
is the finding people skip past.

**Log the inputs, not just the outputs.** Reproducing an AI bug requires the
exact prompt, the retrieved context, the model version, the temperature and the
seed. Logging only the response makes the bug permanently unreproducible, and
this is the most common observability gap in AI systems.

**Distinguish the three failure shapes**, because they have different fixes:

* **Consistent** — wrong the same way every time. Almost always a deterministic
  bug: a prompt, a parsing error, missing context. Debug it normally.
* **Intermittent** — wrong sometimes. Sampling variance, or an input that varies.
  Needs distributional evidence.
* **Drifted** — used to work, now does not, with no code change. Model version,
  corpus change, or the input distribution moved.
""",
        examples=[
            example(
                "Evidence, not anecdote",
                """
# Anecdote: it works now.
result = agent.run(failing_case)

# Evidence: it works at a rate you can compare to the rate before.
before = evaluate(agent, golden_set)          # 0.62 pass rate
agent.prompt = improved_prompt
after = evaluate(agent, golden_set)           # 0.64 pass rate
# On 50 cases, +2pp is one case. That is noise, not a fix.
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Declaring a fix after one successful run",
                "Resampling produces a different answer. The change may have done nothing at "
                "all, and the next report will be the same bug.",
                "Measure the pass rate over the eval set before and after, and know how large "
                "a difference the set can actually detect.",
                Severity.CRITICAL,
            ),
            mistake(
                "Logging only the model's output",
                "Without the prompt, retrieved context, model version and parameters, the bug "
                "cannot be reproduced at all.",
                "Log the full input state per call, with the model version.",
                Severity.HIGH,
            ),
            mistake(
                "Blaming the model before isolating it",
                "Most of an AI pipeline is deterministic. Retrieval and parsing bugs present as "
                "model failures and are far cheaper to find.",
                "Test the deterministic stages first. Confirm the model received correct input "
                "before concluding it misused it.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Proving a prompt change was noise rather than an improvement",
            "Tracking a sudden quality drop to a provider-side model update",
        ],
        requires=["debug-method"],
        tags=["debugging", "ai", "evaluation"],
        estimated_minutes=12,
    ),
    ConceptSpec(
        slug="production-incident-response",
        title="Incident Response — Stop the Bleeding First",
        category=P,
        skill_node="comm.incident",
        difficulty=8,
        summary=(
            "Mitigation and diagnosis are different jobs with different priorities. Doing them "
            "in the wrong order is how a ten-minute outage becomes two hours."
        ),
        explanation="""
The instinct during an incident is to find the cause. That instinct is wrong, and
resisting it is most of the skill.

**Mitigate first.** Roll back, disable the feature flag, fail over, shed load.
Restoring service is the priority; understanding is the priority *after*. A
rollback that takes ninety seconds beats a root cause that takes ninety minutes,
and the evidence is still there afterwards — logs, metrics and traces do not
evaporate because you rolled back.

**Someone runs the incident and does not debug it.** The incident commander
coordinates, communicates and decides. The moment they start reading stack
traces, nobody is tracking what has been tried, nobody is updating stakeholders,
and two people start making conflicting changes to production.

**Communicate on a timer, not on progress.** Every fifteen minutes, even when the
update is "no change, still investigating". Silence makes people escalate and
join the call, which is strictly worse. The format that works: what is broken,
who is affected, what we are doing, when the next update is.

**Record what you tried as you try it.** Otherwise the postmortem is written from
memory forty-eight hours later and is largely fiction. A running timeline in the
channel is enough.

**And the postmortem is blameless for an engineering reason, not a kind one.** If
naming a person is the outcome, people will hide information, and the next
incident is debugged with less evidence. The question is never "who deployed it"
but "what allowed a change like that to reach production" — which is a question
with an actionable answer.

**Action items must be specific and owned.** "Improve monitoring" appears in
every postmortem and is completed in none. "Alert when the merge step emits more
rows than it consumed — owner: X, by Friday" is a thing that either happens or
visibly does not.
""",
        examples=[
            example(
                "The order that matters",
                """
14:02  Alert: error rate 34%
14:03  Declare incident. Commander: A (coordinating, not debugging).
14:05  MITIGATE: roll back to the previous release. Errors drop to 0.2%.
14:06  Update posted. Next update 14:20.
14:07  NOW diagnose, with service restored and no clock pressure.
""",
                note="Five minutes to mitigation. Root cause was found at 15:40 — and it did "
                "not matter, because nobody was affected after 14:05.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Diagnosing before mitigating",
                "Users stay broken while you investigate. A rollback takes ninety seconds and "
                "the evidence survives it.",
                "Mitigate, then diagnose. Always in that order.",
                Severity.CRITICAL,
            ),
            mistake(
                "The incident commander also debugging",
                "Nobody tracks what has been tried, stakeholders get no updates, and two people "
                "change production at the same time.",
                "The commander coordinates and communicates. Someone else touches the system.",
                Severity.HIGH,
            ),
            mistake(
                "Vague postmortem actions",
                "'Improve monitoring' cannot be completed, assigned or verified, so it is not "
                "an action item — it is a feeling.",
                "Every action names a specific change, one owner and a date.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Running your first incident as commander",
            "Writing a postmortem that produces changes rather than paragraphs",
        ],
        requires=["debug-method"],
        tags=["production", "incident", "communication"],
        estimated_minutes=11,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# CHALLENGES
# ═════════════════════════════════════════════════════════════════════════════
CHALLENGES = [
    ChallengeSpec(
        slug="dbg-bisect-the-failure",
        title="Mechanise the Bisection",
        category=D,
        tier=T.IMPLEMENT,
        prompt="""
A regression was introduced somewhere in a run of commits. Implement
`find_first_bad(commits, is_bad)` returning the **first** commit for which
`is_bad(commit)` is `True`.

`commits` is ordered oldest-first, and `is_bad` is monotonic: once it becomes
`True` it stays `True`. It is also *expensive* — each call builds and tests the
project.

Requirements:

* return the first bad commit, or `None` if none is bad,
* call `is_bad` at most `ceil(log2(n)) + 1` times — a linear scan is the bug,
  not the solution.
""",
        starter_code="def find_first_bad(commits, is_bad):\n    ...\n",
        reference_solution="""
def find_first_bad(commits, is_bad):
    if not commits:
        return None

    # Binary search for the boundary. `is_bad` is monotonic, so the answer is
    # the leftmost True — which is exactly what `lo` converges to.
    lo, hi = 0, len(commits) - 1
    found = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if is_bad(commits[mid]):
            # Record it and keep looking left: an earlier commit may also be bad.
            found = commits[mid]
            hi = mid - 1
        else:
            lo = mid + 1

    return found
""",
        solution_explanation=(
            "This is `git bisect`, and writing it once makes clear why bisection is the "
            "default debugging move rather than a special technique: 1,000 commits take ten "
            "tests instead of a thousand. The subtlety is continuing to search left after a "
            "hit — stopping at the first True found gives *a* bad commit, not the *first* one, "
            "and the first is the one that tells you what changed."
        ),
        tests=[
            script(
                "finds the boundary",
                """
commits = [f"c{i}" for i in range(20)]
first_bad = find_first_bad(commits, lambda c: int(c[1:]) >= 13)
assert first_bad == "c13", first_bad
""",
                points=2.0,
            ),
            script(
                "returns None when nothing is bad",
                """
commits = [f"c{i}" for i in range(10)]
assert find_first_bad(commits, lambda c: False) is None
""",
            ),
            script(
                "handles the first commit being bad",
                """
commits = [f"c{i}" for i in range(10)]
assert find_first_bad(commits, lambda c: True) == "c0"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "actually bisects rather than scanning",
                """
import math
commits = [f"c{i}" for i in range(1000)]
calls = []
def is_bad(c):
    calls.append(c)
    return int(c[1:]) >= 742
assert find_first_bad(commits, is_bad) == "c742"
budget = math.ceil(math.log2(1000)) + 1
assert len(calls) <= budget, f"{len(calls)} calls, budget {budget} - this is a linear scan"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "empty and single-element ranges",
                """
assert find_first_bad([], lambda c: True) is None
assert find_first_bad(["only"], lambda c: True) == "only"
assert find_first_bad(["only"], lambda c: False) is None
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["debug-method"],
        hints=[
            "`is_bad` is monotonic. What does that let you do that a linear scan does not?",
            "When you find a bad commit, are you finished? Could an earlier one also be bad?",
            "Count the calls: 1000 commits should cost about 10 tests, not 742.",
        ],
        explanation_prompts=[
            point(
                "Names it as binary search over the commit range",
                "binary search",
                "bisect",
                "halve",
                weight=3,
            ),
            point(
                "Explains why you keep searching left after a hit",
                "first",
                "leftmost",
                "earlier",
                "boundary",
                weight=2.5,
            ),
            point(
                "Relates it to bisecting a hypothesis space generally",
                "hypothesis",
                "search space",
                "halve",
                weight=2,
                dimension="depth",
            ),
        ],
        expected_complexity="O(log n)",
        par_seconds=360,
    ),
    ChallengeSpec(
        slug="dbg-find-blocking-calls",
        title="Static Detection of Blocking Calls in Async Code",
        category=D,
        tier=T.PRODUCTION,
        prompt="""
Implement `find_blocking_calls(source)` — a static check that returns a sorted
list of `(line_number, call_name)` for blocking calls made inside `async def`
functions.

Flag these call names: `time.sleep`, `requests.get`, `requests.post`,
`open`, `subprocess.run`.

Rules:

* only inside an `async def` — the same call in a regular `def` is fine,
* a nested regular `def` inside an `async def` is **not** flagged: it does not
  run on the loop unless awaited,
* a nested `async def` **is** flagged.

This is the shape of the real lint rule. Writing it makes the reason it is a lint
rule rather than a review habit obvious: it is mechanical, and review is not.
""",
        starter_code="import ast\n\n\ndef find_blocking_calls(source):\n    ...\n",
        reference_solution="""
import ast

BLOCKING = {"time.sleep", "requests.get", "requests.post", "open", "subprocess.run"}


def _call_name(node):
    # Rebuild the dotted name: `requests.get` is Attribute(Name('requests'), 'get').
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.found = []
        # A stack, not a flag: entering a plain `def` inside an `async def`
        # leaves async context, and a nested `async def` re-enters it. A single
        # boolean gets both of those wrong.
        self.async_depth = []

    def visit_AsyncFunctionDef(self, node):
        self.async_depth.append(True)
        self.generic_visit(node)
        self.async_depth.pop()

    def visit_FunctionDef(self, node):
        # A sync function nested in an async one does not run on the loop
        # unless it is awaited, so its body is not flagged.
        self.async_depth.append(False)
        self.generic_visit(node)
        self.async_depth.pop()

    def visit_Call(self, node):
        if self.async_depth and self.async_depth[-1]:
            name = _call_name(node.func)
            if name in BLOCKING:
                self.found.append((node.lineno, name))
        self.generic_visit(node)


def find_blocking_calls(source):
    visitor = _Visitor()
    visitor.visit(ast.parse(source))
    return sorted(visitor.found)
""",
        solution_explanation=(
            "The stack is the whole challenge. A boolean 'am I in an async function' flag "
            "reports a false positive for every helper defined inside an async function, and "
            "false positives are how a lint rule gets disabled. The AST also means the check "
            "understands scope in a way a regex never can — `# requests.get` in a comment and "
            '`"requests.get"` in a string are both correctly ignored for free.'
        ),
        tests=[
            script(
                "flags a blocking call in an async function",
                """
src = '''
async def handler():
    time.sleep(1)
'''
assert find_blocking_calls(src) == [(3, "time.sleep")], find_blocking_calls(src)
""",
                points=2.0,
            ),
            script(
                "ignores the same call in a sync function",
                """
src = '''
def worker():
    time.sleep(1)
    requests.get("http://x")
'''
assert find_blocking_calls(src) == []
""",
                points=2.0,
            ),
            script(
                "finds dotted attribute calls",
                """
src = '''
async def fetch():
    requests.get("http://x")
    subprocess.run(["ls"])
'''
out = find_blocking_calls(src)
assert out == [(3, "requests.get"), (4, "subprocess.run")], out
""",
                points=2.0,
            ),
            script(
                "does not flag a nested sync helper",
                """
src = '''
async def handler():
    def helper():
        time.sleep(1)
    return helper
'''
assert find_blocking_calls(src) == [], "flagged a nested sync def - false positive"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "does flag a nested async function",
                """
src = '''
async def outer():
    async def inner():
        time.sleep(1)
    await inner()
'''
assert find_blocking_calls(src) == [(4, "time.sleep")], find_blocking_calls(src)
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "comments and strings are not code",
                """
src = '''
async def handler():
    # time.sleep(1)
    note = "call requests.get here"
    return note
'''
assert find_blocking_calls(src) == [], "matched a comment or a string - not using the AST"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "results are sorted",
                """
src = '''
async def a():
    subprocess.run(["x"])
    open("f")
    time.sleep(1)
'''
out = find_blocking_calls(src)
assert out == sorted(out), out
assert len(out) == 3, out
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["debug-async-blocking"],
        hints=[
            "Use `ast.parse` and a `NodeVisitor`. A regex cannot know whether it is in a string.",
            "How do you track whether the *innermost* enclosing function is async?",
            "`requests.get` is an Attribute whose `.value` is a Name. Rebuild the dotted name.",
        ],
        explanation_prompts=[
            point(
                "Explains why the innermost scope decides",
                "innermost",
                "nested",
                "stack",
                "scope",
                weight=3,
            ),
            point(
                "Says why the AST beats a regex here",
                "ast",
                "string",
                "comment",
                "syntax",
                weight=2.5,
            ),
            point(
                "Notes false positives get lint rules disabled",
                "false positive",
                "disabled",
                "noise",
                "ignored",
                weight=2,
                dimension="production_awareness",
            ),
        ],
        expected_complexity="O(n) in AST nodes",
        par_seconds=600,
    ),
    ChallengeSpec(
        slug="dbg-detect-n-plus-one",
        title="Catch the N+1 Before It Ships",
        category=D,
        tier=T.OPTIMIZE,
        prompt="""
Implement `batch_lookup(ids, fetch_many)` replacing an N+1 access pattern.

* `ids` may contain duplicates and may be empty.
* `fetch_many(unique_ids)` takes a **list** of distinct ids and returns a dict
  mapping id to record. It is the only way to fetch, and each call is a round
  trip.
* Return a list of records in the **same order as `ids`**, including repeats.
* Ids with no record are skipped.

Call `fetch_many` **at most once**. That constraint is the entire lesson: the
N+1 is not slow because the query is slow, it is slow because there are N of
them.
""",
        starter_code="def batch_lookup(ids, fetch_many):\n    ...\n",
        reference_solution="""
def batch_lookup(ids, fetch_many):
    if not ids:
        # Zero round trips for zero work. Calling fetch_many([]) is a wasted
        # trip, and on a hot path that is the whole cost.
        return []

    # dict.fromkeys de-duplicates while preserving order, which keeps the
    # query deterministic — useful when reading slow-query logs.
    unique = list(dict.fromkeys(ids))
    records = fetch_many(unique)

    return [records[i] for i in ids if i in records]
""",
        solution_explanation=(
            "One round trip regardless of input size. Two details that matter beyond the "
            "obvious: de-duplicating before the query means 500 orders from 3 customers fetch "
            "3 records rather than 500, and returning early on empty input avoids a pointless "
            "trip that shows up on hot paths. Order preservation matters because callers "
            "routinely zip the result back against the input."
        ),
        tests=[
            script(
                "one round trip, correct order",
                """
calls = []
def fetch_many(unique):
    calls.append(list(unique))
    return {i: f"rec-{i}" for i in unique}

out = batch_lookup([3, 1, 3, 2], fetch_many)
assert out == ["rec-3", "rec-1", "rec-3", "rec-2"], out
assert len(calls) == 1, f"{len(calls)} round trips - still an N+1"
""",
                points=3.0,
            ),
            script(
                "de-duplicates before querying",
                """
calls = []
def fetch_many(unique):
    calls.append(list(unique))
    return {i: i * 10 for i in unique}

batch_lookup([1, 1, 1, 2, 2], fetch_many)
assert sorted(calls[0]) == [1, 2], f"queried duplicates: {calls[0]}"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "missing records are skipped, not None",
                """
out = batch_lookup([1, 99, 2], lambda u: {i: i for i in u if i != 99})
assert out == [1, 2], out
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "empty input does no work at all",
                """
calls = []
def fetch_many(unique):
    calls.append(unique)
    return {}

assert batch_lookup([], fetch_many) == []
assert calls == [], "made a round trip for an empty input"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "scales to a large input with one call",
                """
calls = []
def fetch_many(unique):
    calls.append(len(unique))
    return {i: i for i in unique}

ids = list(range(5000)) * 2
out = batch_lookup(ids, fetch_many)
assert len(out) == 10000
assert calls == [5000], calls
""",
                hidden=True,
                points=3.0,
            ),
        ],
        concepts=["debug-performance-evidence"],
        hints=[
            "How many times may you call `fetch_many`? Design backwards from that.",
            "What if the same id appears 400 times — should it be fetched 400 times?",
            "What is the right number of round trips for an empty list?",
        ],
        explanation_prompts=[
            point(
                "Explains that latency comes from round trips, not query time",
                "round trip",
                "latency",
                "n+1",
                "network",
                weight=3,
            ),
            point("Mentions de-duplication", "dedup", "unique", "distinct", weight=2),
            point(
                "Notes it would not show in a Python CPU profile",
                "profil",
                "io",
                "waiting",
                "database",
                weight=2,
                dimension="depth",
            ),
        ],
        expected_complexity="O(n) with 1 round trip",
        par_seconds=360,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# QUESTIONS
# ═════════════════════════════════════════════════════════════════════════════
QUESTIONS = [
    QuestionSpec(
        slug="q-dbg-p99-under-load",
        kind=Q.DEBUGGING,
        category=D,
        tier=T.DEBUG,
        level=L.SENIOR,
        prompt=(
            "A FastAPI service has p50 of 40ms and p99 of 11 seconds. CPU sits at 12%. "
            "Latency grows with request rate, not with payload size. Adding workers helps "
            "roughly linearly. What is your first hypothesis?"
        ),
        concepts=["debug-async-blocking", "debug-performance-evidence"],
        expected_answer=(
            "A blocking call inside an async handler is serialising the event loop on each worker."
        ),
        ideal_senior_answer=(
            "A blocking call in an async handler. Every piece of evidence points the same way: "
            "low CPU means the process is waiting rather than computing; latency scaling with "
            "*rate* rather than payload means requests are queueing behind each other; and "
            "workers helping linearly is the giveaway, because each worker has its own event "
            "loop, so buying concurrency by adding processes is exactly what you would expect "
            "if each loop is serialised to one request at a time.\n\n"
            "The p50/p99 split fits too — a request arriving at an idle loop is fast, and one "
            "arriving behind three blocking calls waits for all of them.\n\n"
            "I would confirm it cheaply before changing anything: enable asyncio debug mode, "
            "which logs any callback blocking over 100ms, or attach py-spy to a live worker and "
            "look at where it is parked. Both take minutes and neither requires a deploy.\n\n"
            "The usual culprits are `requests` instead of `httpx.AsyncClient`, `time.sleep`, a "
            "synchronous database driver, or CPU-bound work like a large JSON parse. The fix is "
            "the async library where one exists, `asyncio.to_thread` where it does not — though "
            "not for CPU-bound work, where the GIL means a thread does not help and it needs a "
            "process pool.\n\n"
            "Afterwards I would add a ruff ASYNC lint rule in CI, because this bug is invisible "
            "in review and in staging, and it reaches production every time it is written."
        ),
        common_wrong_answer=(
            "Concluding the service needs more workers. That is treating the symptom — it works, "
            "it costs money proportional to the bug, and the next blocking call has the same "
            "effect on top."
        ),
        rubric=[
            point(
                "Identifies a blocking call in the event loop",
                "block",
                "event loop",
                "sync",
                weight=3,
            ),
            point(
                "Uses low CPU as evidence of waiting rather than computing",
                "cpu",
                "waiting",
                "io",
                "idle",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "Explains why more workers helps without being the fix",
                "worker",
                "own loop",
                "process",
                "symptom",
                weight=2.5,
            ),
            point(
                "Proposes a cheap confirmation before changing code",
                "asyncio debug",
                "py-spy",
                "confirm",
                "verify",
                weight=2,
                dimension="practical_experience",
            ),
            point(
                "Knows threads do not fix CPU-bound work",
                "gil",
                "process pool",
                "cpu-bound",
                weight=2,
            ),
            point(
                "Adds a lint rule so it cannot recur",
                "lint",
                "ci",
                "ruff",
                "async rule",
                weight=2,
                dimension="production_awareness",
            ),
        ],
        followups=[
            "How would you prove it before deploying a fix?",
            "Why did staging not catch this?",
        ],
        tags=["debugging", "async", "interview"],
        par_seconds=420,
    ),
    QuestionSpec(
        slug="q-dbg-profile-tottime",
        kind=Q.MCQ,
        category=D,
        tier=T.UNDERSTAND,
        level=L.MID,
        prompt=(
            "In a cProfile report, the top entry by `cumtime` is your `main()` function at 100%. "
            "What does that tell you?"
        ),
        concepts=["debug-performance-evidence"],
        options=[
            opt(
                "a",
                "Nothing useful — cumtime includes callees, so the entry point is always at the top. Sort by tottime",
                correct=True,
                why="Cumulative time counts everything a function called, so `main` is 100% by "
                "definition in every program ever profiled. Total time is work done *in* the "
                "function itself, and that is the actionable column.",
            ),
            opt(
                "b",
                "main() is the bottleneck and should be optimised",
                why="main() is the entry point; it contains the whole program by definition.",
            ),
            opt("c", "The profiler is misconfigured", why="This is the expected, correct output."),
            opt(
                "d",
                "The program is CPU-bound",
                why="cumtime on main says nothing about CPU versus I/O. Check actual CPU "
                "utilisation for that.",
            ),
        ],
        expected_answer="Nothing — sort by tottime instead.",
        ideal_senior_answer=(
            "Nothing actionable. `cumtime` includes everything the function called, so the entry "
            "point is always 100% — that is arithmetic, not a finding. `tottime` is time spent "
            "in the function's own bytecode, and that is where you can actually make a change. "
            "I would also check overall CPU utilisation before trusting any CPU profile at all: "
            "if the process is at 12%, the time is going to I/O and no Python-level optimisation "
            "will touch it."
        ),
        rubric=[point("Names tottime as the actionable column", "tottime", "cumtime", weight=3)],
        followups=["When is cumtime genuinely useful?", "What if CPU utilisation is 8%?"],
        tags=["debugging", "profiling"],
        par_seconds=120,
    ),
    QuestionSpec(
        slug="q-dbg-ai-one-run",
        kind=Q.MCQ,
        category=D,
        tier=T.PRODUCTION,
        level=L.SENIOR,
        prompt=(
            "A teammate changed a prompt, re-ran the one failing case, saw it pass, and opened "
            "a PR titled 'fix hallucination'. What is the problem?"
        ),
        concepts=["debug-ai-nondeterminism"],
        options=[
            opt(
                "a",
                "One run is a sample, not evidence — the change may have done nothing and they resampled",
                correct=True,
                why="Sampling means the same prompt can produce a different answer, so a single "
                "pass is consistent both with a real fix and with no change at all. The unit of "
                "evidence for a probabilistic system is a pass rate over a set of cases.",
            ),
            opt(
                "b",
                "Prompts should never be changed to fix bugs",
                why="Prompt changes are a legitimate fix; the problem is the evidence, not the intervention.",
            ),
            opt(
                "c",
                "They should have used a larger model",
                why="Unrelated, more expensive, and equally unvalidated.",
            ),
            opt(
                "d",
                "Nothing — the failing case now passes",
                why="That observation is equally consistent with having changed nothing.",
            ),
        ],
        expected_answer="A single run cannot distinguish a fix from resampling.",
        ideal_senior_answer=(
            "The evidence does not support the claim. Sampling means the same prompt can produce "
            "a different answer, so one pass is consistent with a real improvement and with "
            "having changed nothing at all. I would ask for the pass rate over the eval set "
            "before and after — and for a sense of how large a difference the set can actually "
            "detect, because on 50 cases a two-point move is one case and is noise.\n\n"
            "I would also want the failing case added to the golden set permanently, so whatever "
            "the fix turns out to be, the regression is caught next time rather than "
            "rediscovered."
        ),
        rubric=[
            point("Identifies sampling variance", "sampl", "variance", "one run", "noise", weight=3)
        ],
        followups=["How many cases do you need?", "What would convince you?"],
        tags=["debugging", "ai", "review"],
        par_seconds=180,
    ),
    QuestionSpec(
        slug="q-incident-first-action",
        kind=Q.SCENARIO,
        category=P,
        tier=T.PRODUCTION,
        level=L.SENIOR,
        prompt=(
            "03:12. You are paged: checkout error rate is 34%. A release went out at 02:50. "
            "You are the only person awake. What are your first three actions, in order, "
            "and why that order?"
        ),
        concepts=["production-incident-response"],
        expected_answer=(
            "Mitigate by rolling back, communicate, then diagnose with service restored."
        ),
        ideal_senior_answer=(
            "**First, roll back.** A release twenty minutes before a 34% error rate is the "
            "hypothesis, and I do not need to confirm it to act on it — a rollback takes about "
            "ninety seconds, and if the errors clear I have both mitigated *and* confirmed the "
            "hypothesis in one action. If they do not clear, I have eliminated the most likely "
            "cause for the same ninety seconds. The instinct to read logs first is the one to "
            "resist: every minute spent diagnosing is a minute of users failing to check out, "
            "and the logs will still be there afterwards.\n\n"
            "**Second, communicate.** Declare the incident in the channel even though I am "
            "alone — it starts the timeline, and the timeline is what the postmortem is written "
            "from rather than my memory at 3am. Post what is broken, who is affected, what I "
            "have done and when the next update lands. If it is not resolved in ten minutes I "
            "wake someone, because a solo incident at 3am is how avoidable mistakes get made.\n\n"
            "**Third, now diagnose** — with service restored, no clock pressure and full "
            "evidence. What was in the release, what does the error actually say, why did no "
            "pre-deploy check catch it.\n\n"
            "The order is the whole answer. Mitigation and diagnosis are different jobs, and "
            "doing them in the wrong order turns a ten-minute outage into a two-hour one while "
            "somebody builds a complete understanding of a problem they could have stopped."
        ),
        common_wrong_answer=(
            "Reading logs and tracing the root cause first. It feels rigorous and it keeps users "
            "broken for the duration."
        ),
        rubric=[
            point("Rolls back first", "roll back", "rollback", "revert", "mitigat", weight=3),
            point(
                "Explains mitigation before diagnosis",
                "mitigat",
                "first",
                "before",
                "restore",
                weight=3,
            ),
            point(
                "Communicates and starts a timeline",
                "communicat",
                "declare",
                "update",
                "timeline",
                weight=2.5,
            ),
            point(
                "Uses the rollback as a cheap test of the hypothesis",
                "confirm",
                "hypothesis",
                "eliminat",
                "test",
                weight=2,
                dimension="depth",
            ),
            point(
                "Escalates rather than working alone indefinitely",
                "wake",
                "escalat",
                "second pair",
                "help",
                weight=2,
                dimension="practical_experience",
            ),
            point(
                "Asks why no pre-deploy check caught it",
                "why",
                "check",
                "caught",
                "prevent",
                weight=1.5,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "The rollback does not fix it. What now?",
            "What goes in the postmortem, and what makes an action item real?",
        ],
        tags=["production", "incident", "interview"],
        par_seconds=420,
    ),
    QuestionSpec(
        slug="q-incident-blameless-why",
        kind=Q.EXPLAIN,
        category=P,
        tier=T.STAFF_TRADEOFF,
        level=L.STAFF,
        prompt=(
            "A postmortem is described as 'blameless'. A manager objects that the engineer who "
            "deployed the change should be accountable. Make the engineering case for "
            "blamelessness — not the cultural one."
        ),
        concepts=["production-incident-response"],
        expected_answer=(
            "Blame suppresses information, and incident analysis is entirely dependent on "
            "information. It is an evidence-quality argument, not a kindness argument."
        ),
        ideal_senior_answer=(
            "The argument I would make is about evidence, because the cultural case tends to "
            "sound like a preference and gets overruled.\n\n"
            "An incident analysis is only as good as the information people volunteer. Much of "
            "what matters is only known to the person involved: what they were trying to do, "
            "what the dashboard looked like, what they almost did instead, which warning they "
            "dismissed and why it seemed reasonable at the time. None of that is in a log. If "
            "naming a person is a possible outcome, that information stops being volunteered — "
            "not through dishonesty, but because people describe events more carefully when "
            "they are exposed. The analysis then proceeds on worse evidence and reaches a "
            "shallower conclusion.\n\n"
            "The second half is that 'who deployed it' is almost never the interesting question, "
            "because the answer generalises to nothing. The interesting question is what allowed "
            "a change of that kind to reach production: what did review not look at, what did CI "
            "not test, what did the deploy tooling make easy that should have been hard. Those "
            "have fixes. 'Be more careful' does not — it is not a change to any system, and the "
            "next person will be equally careful and equally caught.\n\n"
            "I would also point out that accountability is not what is being given up. The "
            "engineer is still expected to write the postmortem, present it, and own the action "
            "items. That is more accountability than a reprimand produces, not less — it is just "
            "directed at fixing the system instead of at the person.\n\n"
            "And empirically: teams that blame have fewer reported incidents, which reads as an "
            "improvement and is the opposite. The incidents still happen; they stop being "
            "written down."
        ),
        common_wrong_answer=(
            "Arguing it on kindness or morale alone. True, and easy to overrule when the outage "
            "was expensive — the durable argument is that blame degrades the evidence."
        ),
        rubric=[
            point(
                "Blame suppresses information",
                "hide",
                "suppress",
                "volunteer",
                "information",
                weight=3,
            ),
            point(
                "Key evidence exists only in the person's head",
                "only they know",
                "context",
                "not in the log",
                "what they were",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "'Who' does not generalise; 'what allowed it' does",
                "what allowed",
                "system",
                "generalis",
                "actionable",
                weight=3,
                dimension="architecture_thinking",
            ),
            point(
                "'Be more careful' is not a system change",
                "be more careful",
                "not actionable",
                "not a fix",
                weight=2,
            ),
            point(
                "Distinguishes blamelessness from lack of accountability",
                "accountab",
                "own",
                "still responsible",
                "action item",
                weight=2.5,
                dimension="tradeoff_awareness",
            ),
            point(
                "Notes fewer reported incidents is not fewer incidents",
                "report",
                "fewer",
                "hidden",
                "stop being",
                weight=2,
                dimension="production_awareness",
            ),
        ],
        followups=[
            "When is individual accountability appropriate?",
            "What makes a postmortem action item real rather than decorative?",
        ],
        tags=["production", "incident", "leadership"],
        par_seconds=480,
    ),
    QuestionSpec(
        slug="q-dbg-what-changed",
        kind=Q.MCQ,
        category=D,
        tier=T.DEBUG,
        level=L.JUNIOR,
        prompt=(
            "A batch job that has run nightly for eight months failed last night. Nobody "
            "deployed anything. Where do you look first?"
        ),
        concepts=["debug-method"],
        options=[
            opt(
                "a",
                "What else changed — the data, a dependency, disk, an upstream API, or a date boundary",
                correct=True,
                why="Code is only one of the things that can change. Eight months of success "
                "means the code is probably fine and something around it moved: an input shape, "
                "a transitive dependency upgrade, a full disk, an upstream contract change, or a "
                "calendar boundary like a month or year end.",
            ),
            opt(
                "b",
                "Read the job's source code looking for a bug",
                why="It worked for eight months. The code is the least likely thing to have "
                "changed, and reading it is the slowest way to find out.",
            ),
            opt(
                "c",
                "Rerun it and see whether it passes",
                why="Worth doing, and it is a test rather than an investigation — it tells you whether the condition persists, not what it is.",
            ),
            opt(
                "d",
                "Increase the timeout and retry",
                why="A guess at both the symptom and the cause.",
            ),
        ],
        expected_answer="Look for what changed outside the code.",
        ideal_senior_answer=(
            "What changed — and code is only one candidate. After eight months of success the "
            "likely culprits are around the job: the input data grew or changed shape, an "
            "unpinned transitive dependency upgraded, disk or memory ran out, an upstream API "
            "changed its response, or a date boundary was crossed — month end and year end break "
            "an astonishing amount of code exactly once a year. I would diff the input size and "
            "schema against the previous run first, then the environment, then the dependency "
            "tree, and read the source last."
        ),
        rubric=[
            point("Looks beyond the code for the change", "data", "dependency", "changed", weight=3)
        ],
        followups=[
            "How would you check the data changed?",
            "Which of those would you check first and why?",
        ],
        tags=["debugging", "method"],
        par_seconds=120,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# MISSIONS
# ═════════════════════════════════════════════════════════════════════════════
MISSIONS = [
    MissionSpec(
        slug="mission-p99-collapse",
        title="Incident: p99 at Eleven Seconds",
        kind="incident",
        category=D,
        building="debugging_dungeon",
        tier=T.DEBUG,
        briefing="""
**11:40.** The checkout service is timing out for some users. Not all — the
dashboard shows p50 at a healthy 40ms and p99 at 11 seconds.

Traffic is up 3x this week after a marketing push. Nothing was deployed. The
on-call runbook says "scale up if latency is high", and someone has already
doubled the workers, which helped exactly as much as doubling the workers should.

That is a clue, not a fix.
""",
        objective="Find why concurrency is serialised, fix it, and stop it recurring.",
        artifacts={
            "metrics": (
                "               p50      p95       p99     cpu    rps\n"
                "last week     38ms    120ms     310ms     11%    140\n"
                "today         40ms   4,800ms  11,200ms     12%    420\n"
                "after 2x workers  39ms  2,300ms  5,600ms   13%    420"
            ),
            "the_handler": (
                "@app.get('/checkout/quote')\n"
                "async def quote(cart_id: str):\n"
                "    cart = await db.get_cart(cart_id)\n"
                "    rates = requests.get(f'{TAX_API}/rates', timeout=10).json()\n"
                "    return compute(cart, rates)"
            ),
            "py_spy_dump": (
                "$ py-spy dump --pid 1\n"
                'Thread 1 (active): "MainThread"\n'
                "    read (socket.py:705)\n"
                "    readinto (socket.py:...)\n"
                "    _read_status (http/client.py:288)\n"
                "    getresponse (http/client.py:1377)\n"
                "    send (requests/adapters.py:486)\n"
                "    quote (app/api/checkout.py:42)"
            ),
            "the_tell": (
                "CPU is 12% at 3x traffic, and doubling workers halved p99 almost exactly. "
                "A service that is genuinely async should not scale that way."
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="question",
                title="Form the hypothesis",
                question="q-dbg-p99-under-load",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Build the detector",
                challenge="dbg-find-blocking-calls",
            ),
            MissionStepSpec(
                step_type="question",
                title="Read the profile correctly",
                question="q-dbg-profile-tottime",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Postmortem",
                prompt=(
                    "Explain why this was invisible in staging and in code review, why doubling "
                    "the workers 'worked', and what you are adding so the next blocking call is "
                    "caught before it ships."
                ),
                config={
                    "rubric": [
                        point(
                            "Explains staging lacks the concurrency to expose it",
                            "concurren",
                            "load",
                            "staging",
                            "single request",
                            weight=3,
                        ),
                        point(
                            "Explains why more workers helps without fixing anything",
                            "own loop",
                            "per worker",
                            "process",
                            "symptom",
                            weight=3,
                        ),
                        point(
                            "Adds a static check rather than a review habit",
                            "lint",
                            "ci",
                            "ruff",
                            "async",
                            "static",
                            weight=2.5,
                            dimension="production_awareness",
                        ),
                        point(
                            "Names a specific, owned action item",
                            "owner",
                            "by ",
                            "specific",
                            weight=2,
                        ),
                    ]
                },
            ),
        ],
        concepts=["debug-async-blocking", "debug-performance-evidence", "debug-method"],
        success_criteria=[
            "Blocking call identified from the evidence, not guessed",
            "Understands why workers helped and why that is not a fix",
            "A static check proposed so it cannot recur",
        ],
        debrief="""
Three pieces of evidence all said the same thing and none of them was the code.
CPU at 12% under 3x traffic means the process is waiting, not computing. Latency
scaling with request *rate* rather than payload size means queueing. And workers
helping linearly is the specific signature of a serialised event loop — each
worker has its own loop, so adding processes buys back the concurrency the
blocking call destroyed.

The py-spy dump then named the line. `requests.get` inside `async def`, sitting
in a socket read, with the entire loop waiting on it.

The part worth keeping is why nobody caught it. It is invisible at one request
per second, which is what staging and manual testing produce. It is invisible in
review because the line looks completely normal. That combination — invisible in
every cheap check, catastrophic under production concurrency — is exactly the
profile of a bug that needs a *mechanical* detector. Ruff's ASYNC rules catch
this statically, in CI, in under a second. A review habit would not have.
""",
        required_level=13,
        estimated_minutes=35,
        par_seconds=2100,
    ),
    MissionSpec(
        slug="mission-nightly-job-failed",
        title="The Job That Ran For Eight Months",
        kind="debugging",
        category=D,
        building="debugging_dungeon",
        tier=T.DEBUG,
        briefing="""
**06:15.** The nightly reconciliation job failed. It has run every night for
eight months without incident. Nothing was deployed — the last commit to that
repository was in April.

The stack trace is a `MemoryError`. The obvious response is to give the
container more memory, and that will probably work tonight.

Find out what actually changed.
""",
        artifacts={
            "traceback": (
                "Traceback (most recent call last):\n"
                '  File "reconcile.py", line 88, in build_matrix\n'
                "    matrix = np.zeros((len(a), len(b)))\n"
                "numpy._core._exceptions._ArrayMemoryError: Unable to allocate 47.8 GiB "
                "for an array with shape (80000, 80000) and data type float64"
            ),
            "run_history": (
                "date        rows_a   rows_b   peak_mem   duration\n"
                "2026-09-14   11,204   11,190     1.1 GB      4m12s\n"
                "2026-09-15   11,318   11,301     1.1 GB      4m20s\n"
                "2026-09-16   11,402   11,388     1.1 GB      4m18s\n"
                "2026-09-17   79,981   79,974    OOM-killed      -\n"
                "\n"
                "(a marketing import backfilled three years of historical records on the 17th)"
            ),
            "the_code": (
                "def build_matrix(a, b):\n"
                "    matrix = np.zeros((len(a), len(b)))\n"
                "    for i, row_a in enumerate(a):\n"
                "        for j, row_b in enumerate(b):\n"
                "            matrix[i, j] = distance(row_a, row_b)\n"
                "    return matrix"
            ),
            "the_question": (
                "The code is unchanged and correct. It has an O(n²) memory footprint that "
                "was invisible at n=11,000 and fatal at n=80,000. Whose bug is this?"
            ),
        },
        objective="Find the real change, and decide what the right fix is versus the easy one.",
        steps=[
            MissionStepSpec(
                step_type="question",
                title="Where do you look first?",
                question="q-dbg-what-changed",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Mechanise the search",
                challenge="dbg-bisect-the-failure",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Right fix versus easy fix",
                prompt=(
                    "Raising the memory limit makes tonight's run succeed. Explain why that is "
                    "the wrong fix here, what the right one is, and — since the right one costs "
                    "more than tonight's window allows — what you would actually do this "
                    "morning and what you would schedule."
                ),
                config={
                    "rubric": [
                        point(
                            "Identifies the quadratic memory growth as the real issue",
                            "o(n^2)",
                            "quadratic",
                            "n squared",
                            "grows",
                            weight=3,
                        ),
                        point(
                            "Recognises the 7x data growth as the trigger, not the cause",
                            "data",
                            "grew",
                            "backfill",
                            "trigger",
                            weight=2.5,
                        ),
                        point(
                            "Separates the immediate mitigation from the durable fix",
                            "mitigat",
                            "today",
                            "schedule",
                            "short term",
                            weight=3,
                            dimension="tradeoff_awareness",
                        ),
                        point(
                            "Proposes a real alternative — chunking, blocking or an index",
                            "chunk",
                            "batch",
                            "block",
                            "index",
                            "candidate",
                            weight=2.5,
                            dimension="depth",
                        ),
                        point(
                            "Adds an alert on input size, not just on failure",
                            "alert",
                            "monitor",
                            "input size",
                            "row count",
                            weight=2,
                            dimension="production_awareness",
                        ),
                    ]
                },
            ),
            MissionStepSpec(
                step_type="journal",
                title="The question you will ask sooner",
                prompt="What will you check first the next time something that always worked stops working?",
                required=False,
            ),
        ],
        concepts=["debug-method", "debug-performance-evidence"],
        success_criteria=[
            "Identified the data change rather than hunting a code bug",
            "Recognised the latent O(n²) that was always there",
            "Separated the immediate mitigation from the durable fix",
        ],
        debrief="""
Nothing was deployed and nothing was broken. The code had a quadratic memory
footprint from the day it was written, and at 11,000 rows that was 1.1GB — fine,
invisible, never questioned. A backfill took it to 80,000 rows and the same code
asked for 47.8 GiB.

This is the most useful shape of "what changed" to have seen once: the change was
in the *data*, and the bug was a latent property of the code that the data had
been hiding. Reading `reconcile.py` looking for a mistake would have found
nothing, because there is no mistake in it — there is an assumption about scale
that stopped holding.

The two-track answer is the professional one. Raise the limit this morning so
finance gets its reconciliation, and schedule the real fix — blocking or
candidate generation so the matrix is never materialised at all. And add an
alert on *input size*, because the job that fails tonight is always the job whose
input quietly grew last week.
""",
        required_level=9,
        estimated_minutes=30,
        par_seconds=1800,
    ),
]

PACK = ContentPack(
    name="debugging_dungeon",
    concepts=CONCEPTS,
    challenges=CHALLENGES,
    questions=QUESTIONS,
    missions=MISSIONS,
)
