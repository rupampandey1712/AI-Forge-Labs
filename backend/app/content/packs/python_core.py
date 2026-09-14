"""Python Academy — Levels 1 and 2 (fundamentals through intermediate).

Authoring standard every entry in this file follows:

* **Concepts** explain the *mechanism*, not the syntax. "A list is ordered" is
  documentation; "a list is a dynamic array of pointers, which is why appending
  is amortised O(1) and inserting at the front is O(n)" is a concept.
* **Challenges** have hidden tests and a reference solution. Debug-tier
  challenges ship broken code whose bug is a *named* mistake pattern.
* **Questions** carry a rubric with surface forms, an ideal senior answer, the
  common wrong answer, and follow-ups the interviewer can escalate to.
"""

from __future__ import annotations

from app.content.schema import (
    ChallengeSpec,
    ConceptSpec,
    ContentPack,
    MissionSpec,
    MissionStepSpec,
    QuestionSpec,
    eq,
    example,
    mistake,
    opt,
    point,
    predicate,
    raises,
    script,
)
from app.domain.enums import (
    Category,
    Severity,
)
from app.domain.enums import (
    DifficultyTier as T,
)
from app.domain.enums import (
    InterviewLevel as L,
)
from app.domain.enums import (
    QuestionKind as Q,
)

C = Category.PYTHON

# ═════════════════════════════════════════════════════════════════════════════
# CONCEPTS
# ═════════════════════════════════════════════════════════════════════════════
CONCEPTS = [
    ConceptSpec(
        slug="python-names-and-objects",
        title="Names, Objects and Assignment",
        category=C,
        skill_node="python.syntax",
        difficulty=2,
        summary="Python variables are names bound to objects, not boxes holding values.",
        explanation="""
Python has no variables in the C sense. `x = [1, 2]` does two separate things:
it creates a list object somewhere in memory, and it binds the **name** `x` to
that object. Assignment never copies.

That single fact explains a family of behaviours that otherwise look like bugs:

    a = [1, 2]
    b = a          # b is bound to the SAME object
    b.append(3)
    print(a)       # [1, 2, 3]

`b = a` copied a reference, not a list. `a` and `b` are two names for one
object, so mutating through either is visible through both.

Rebinding is different from mutating:

    b = [9]        # rebinds the NAME b; `a` is untouched
    b.append(9)    # mutates the object b currently names

Every object has an identity (`id(x)`), a type, and a value. `is` compares
identity; `==` compares value. They coincide for small ints and interned
strings *by implementation accident*, which is exactly why relying on that is a
bug waiting for a bigger input.
""",
        examples=[
            example(
                "Aliasing bites",
                """
grid = [[0] * 3] * 3      # three references to ONE inner list
grid[0][0] = 1
print(grid)
""",
                output="[[1, 0, 0], [1, 0, 0], [1, 0, 0]]",
                note="`* 3` repeated the reference, not the list. Use a comprehension: [[0]*3 for _ in range(3)]",
            ),
            example(
                "is vs ==",
                """
a, b = 256, 256
print(a is b)             # True  - small ints are cached
c, d = 257, 257
print(c is d)             # False - outside the cache (in CPython)
print(c == d)             # True  - equal values
""",
                note="Never use `is` for value comparison. Reserve it for None, True, False and sentinels.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Using `is` to compare values",
                "It compares identity. It appears to work for small integers and short strings "
                "because CPython caches them, then fails on larger values.",
                "Use `==` for equality; `is` only for singletons (`is None`).",
                Severity.MEDIUM,
            ),
            mistake(
                "Assuming assignment copies",
                "`b = a` binds a second name to the same object. Mutating through one is visible "
                "through the other.",
                "Copy explicitly: `list(a)`, `a.copy()`, or `copy.deepcopy(a)` for nested data.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "A shared default config dict mutated by one request leaking into the next.",
            "`[[]] * n` producing a grid where every row is the same list.",
        ],
        related=["python-mutable-defaults", "python-shallow-vs-deep-copy"],
        tags=["fundamentals", "memory"],
        estimated_minutes=7,
        visualization={"type": "reference_graph", "scenario": "aliasing"},
    ),
    ConceptSpec(
        slug="python-list-vs-tuple-vs-set-vs-dict",
        title="Choosing a Collection",
        category=C,
        skill_node="python.collections",
        difficulty=3,
        summary="Four containers with four different cost models — picking wrong is an O(n²) bug.",
        explanation="""
The four core containers are not stylistic choices. They have different
complexity characteristics, and choosing wrongly is one of the most common
causes of code that works on 100 rows and dies on 100,000.

| Operation        | list    | tuple   | set      | dict     |
|------------------|---------|---------|----------|----------|
| index access     | O(1)    | O(1)    | —        | —        |
| key access       | —       | —       | —        | O(1)     |
| `x in c`         | **O(n)**| **O(n)**| O(1)     | O(1)     |
| append           | O(1)*   | —       | O(1)     | O(1)     |
| insert at front  | O(n)    | —       | —        | —        |
| ordered          | yes     | yes     | no       | insertion|
| mutable          | yes     | no      | yes      | yes      |
| hashable         | no      | yes**   | no       | no       |

\\* amortised — a list is a dynamic array that occasionally reallocates.
\\*\\* only if every element is hashable.

**The single highest-value rule:** membership testing against a list is O(n).
Inside a loop over m items, that is O(n·m). Converting the container to a set
first turns it into O(n + m). This one change routinely takes a function from
minutes to milliseconds.

Sets and dicts are hash tables, which is where their O(1) comes from — and
also why their elements/keys must be hashable and why their iteration order is
not something to rely on (dicts do guarantee insertion order since 3.7; sets do
not guarantee anything).

Use a tuple when the size is fixed and meaningful (a coordinate, a record) or
when you need a dict key. Use a list when it is a homogeneous sequence you will
grow. Use a set for membership and de-duplication. Use a dict for lookup by key.
""",
        examples=[
            example(
                "The O(n·m) trap",
                """
# 10,000 lookups against a 10,000-element list = 100,000,000 comparisons
banned = load_banned_ids()          # list
flagged = [u for u in users if u.id in banned]

# Same logic, ~4 orders of magnitude faster
banned = set(load_banned_ids())
flagged = [u for u in users if u.id in banned]
""",
                note="The only change is the container. This is the most valuable one-line optimisation in Python.",
            ),
            example(
                "Tuples as dict keys",
                """
cache: dict[tuple[int, int], float] = {}
cache[(3, 7)] = 0.42       # works: tuple is hashable
# cache[[3, 7]] = 0.42     # TypeError: unhashable type: 'list'
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "`in` against a list inside a loop",
                "Linear scan per iteration turns an O(n) job into O(n·m).",
                "Build a set once outside the loop.",
                Severity.HIGH,
            ),
            mistake(
                "Using a list to de-duplicate",
                "`if x not in result: result.append(x)` is O(n²).",
                "Use a set, or `dict.fromkeys(items)` when you must preserve order.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "A permission check doing `role in user.roles` (list) on every request.",
            "De-duplicating 10M order IDs — set membership vs. list scan is minutes vs. seconds.",
        ],
        requires=["python-names-and-objects"],
        related=["python-hashing-and-eq", "python-performance-big-o"],
        tags=["collections", "performance"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="python-mutable-defaults",
        title="Mutable Default Arguments",
        category=C,
        skill_node="python.functions",
        difficulty=4,
        summary="Default values are evaluated once, at definition — not per call.",
        explanation="""
    def add_item(item, basket=[]):
        basket.append(item)
        return basket

This is one of Python's most famous traps, and the reason is the object model:
the `def` statement is *executed* when the module is imported. At that moment
the default `[]` is created, exactly once, and stored on the function object
(`add_item.__defaults__`). Every call that relies on the default gets **the same
list**.

    add_item("a")   # ['a']
    add_item("b")   # ['a', 'b']   <- not a fresh basket

The bug is invisible on the first call and in most unit tests, which is why it
reaches production. In a long-running server, state accumulates across unrelated
requests — which turns a correctness bug into a data-leak bug.

The fix is a sentinel:

    def add_item(item, basket=None):
        if basket is None:
            basket = []
        basket.append(item)
        return basket

Use `None` rather than a falsy check (`if not basket`), because an empty list
the caller deliberately passed is a different case from "no argument given".

Note this is not a wart so much as a consequence: defaults being evaluated once
is also what makes the `def f(x, _cache={})` memoisation idiom work, and what
makes `def f(x, _len=len)` a (now-obsolete) speed trick.
""",
        examples=[
            example(
                "Proving it",
                """
def f(x, acc=[]):
    acc.append(x)
    return acc

print(f(1), f(2), f(3))
print(f.__defaults__)
""",
                output="[1] [1, 2] [1, 2, 3]\n([1, 2, 3],)",
                note="__defaults__ holds the one shared list.",
            ),
        ],
        common_mistakes=[
            mistake(
                "`def f(x, items=[])` / `def f(x, opts={})`",
                "One shared object across all calls.",
                "Default to None and build inside the function.",
                Severity.HIGH,
            ),
            mistake(
                "`def f(x, when=datetime.now())`",
                "The timestamp is frozen at import time, so every call reports when the "
                "process started.",
                "Default to None and call `datetime.now()` in the body.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "A FastAPI helper with `headers={}` accumulating auth tokens across requests.",
            "A retry decorator with `attempts=[]` whose history never resets.",
        ],
        requires=["python-names-and-objects"],
        related=["python-closures"],
        tags=["functions", "gotcha"],
        estimated_minutes=6,
    ),
    ConceptSpec(
        slug="python-args-kwargs",
        title="*args, **kwargs and Argument Passing",
        category=C,
        skill_node="python.functions",
        difficulty=3,
        summary="Packing, unpacking, and the positional/keyword-only boundary.",
        explanation="""
`*args` collects extra **positional** arguments into a tuple. `**kwargs`
collects extra **keyword** arguments into a dict. In a call, the same symbols
mean the opposite: they *unpack*.

    def f(a, b, *args, key=None, **kwargs): ...

    f(1, 2, 3, 4, key="x", other=5)
    # a=1, b=2, args=(3, 4), key="x", kwargs={"other": 5}

    values = [1, 2, 3]
    f(*values)            # unpacks into a, b, args

Two markers control how arguments may be supplied:

    def f(a, b, /, c, d, *, e, f): ...
      #         ^ positional-only    ^ keyword-only

* Everything before `/` **must** be positional. Useful when the parameter name
  is an implementation detail you do not want to freeze into your public API.
* Everything after `*` **must** be keyword. Use this for boolean flags and
  options — `send(msg, retry=True)` is readable where `send(msg, True)` is not.

`**kwargs` is powerful and easily overused. A function whose signature is
`def handle(**kwargs)` has no discoverable contract: no IDE completion, no type
checking, and a typo in a caller becomes a silent no-op instead of a TypeError.
Reach for it when genuinely forwarding arguments (decorators, wrappers), not to
avoid writing a signature.
""",
        examples=[
            example(
                "Forwarding in a decorator",
                """
import functools

def logged(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        print(f"calling {fn.__name__}")
        return fn(*args, **kwargs)
    return wrapper
""",
                note="*args/**kwargs here are exactly right: the wrapper must forward whatever it is given.",
            ),
            example(
                "Keyword-only flags",
                """
def export(rows, *, dry_run=False, fmt="csv"):
    ...

export(rows, dry_run=True)     # readable
# export(rows, True)           # TypeError - and that is the point
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "`**kwargs` as a substitute for a signature",
                "Destroys type checking, IDE help and error messages; a caller's typo silently "
                "does nothing.",
                "Name the parameters. Use **kwargs only to forward.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Every decorator in a codebase forwards with *args/**kwargs.",
            "`Model(**row)` to build a Pydantic model from a database row.",
        ],
        requires=["python-names-and-objects"],
        related=["python-decorators-basics"],
        tags=["functions"],
        estimated_minutes=7,
    ),
    ConceptSpec(
        slug="python-comprehensions",
        title="Comprehensions and Generator Expressions",
        category=C,
        skill_node="python.comprehensions",
        difficulty=3,
        summary="Build a collection in one expression — and know when not to.",
        explanation="""
A comprehension builds a collection from an iterable in a single expression:

    squares   = [x * x for x in nums]           # list
    unique    = {x % 10 for x in nums}          # set
    by_id     = {u.id: u for u in users}        # dict
    lazy      = (x * x for x in nums)           # GENERATOR - nothing runs yet

The fourth is different in kind, not just in brackets. A generator expression
produces values on demand: it holds one item in memory at a time instead of n.
Over a 10-million-row file that is the difference between running and an OOM
kill.

    total = sum(len(line) for line in open("huge.log"))   # constant memory
    total = sum([len(line) for line in open("huge.log")]) # builds the whole list first

Comprehensions are faster than the equivalent `for` loop with `.append()`,
because the list-building happens in C rather than through repeated attribute
lookup and method calls.

**When not to use one.** A comprehension is an expression, so it cannot contain
statements — no `try`, no early `break`, no logging. If you find yourself
nesting three `for` clauses with two conditions, you have written something
nobody (including you, in a month) can read. The rule of thumb: one `for`, at
most one `if`, and it fits on a line. Otherwise write the loop.
""",
        examples=[
            example(
                "Lazy vs eager",
                """
import sys
eager = [x * x for x in range(1_000_000)]
lazy  = (x * x for x in range(1_000_000))
print(sys.getsizeof(eager), sys.getsizeof(lazy))
""",
                output="8448728 200",
                note="Same logic. 40,000x the memory.",
            ),
            example(
                "Unreadable — write the loop instead",
                """
result = [transform(x) for sub in matrix for x in sub if check(x) and x.flag if sub.active]
""",
                note="Three clauses and two filters. This is a loop wearing a costume.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Building a list only to iterate it once",
                "Pays full memory cost for no benefit.",
                "Use a generator expression, or pass it straight to sum()/any()/max().",
                Severity.MEDIUM,
            ),
            mistake(
                "Consuming a generator twice",
                "Generators are exhausted after one pass; the second loop sees nothing.",
                "Materialise with list() if you need multiple passes — and then you wanted a list.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Streaming a multi-GB log file through a generator pipeline in constant memory.",
            "`{row.id: row for row in rows}` to index a result set for O(1) joins in memory.",
        ],
        requires=["python-list-vs-tuple-vs-set-vs-dict"],
        related=["python-generators"],
        tags=["collections", "performance"],
        estimated_minutes=8,
    ),
    ConceptSpec(
        slug="python-exceptions",
        title="Exceptions: EAFP, Narrow Catches and Custom Hierarchies",
        category=C,
        skill_node="python.errors",
        difficulty=4,
        summary="Errors are values in the control flow — catch what you can handle, and nothing else.",
        explanation="""
Python prefers **EAFP** (easier to ask forgiveness than permission) over LBYL
(look before you leap):

    # LBYL - racy and slower
    if os.path.exists(path):
        with open(path) as f: ...     # the file can vanish between the two lines

    # EAFP - atomic
    try:
        with open(path) as f: ...
    except FileNotFoundError:
        ...

**The cardinal rule: catch the narrowest exception you can actually handle.**

    except:              # catches SystemExit and KeyboardInterrupt too. Never.
    except Exception:    # catches every bug, including your typos
    except (KeyError, ValueError):   # a real decision

`except Exception: pass` is how a service ends up "running" while quietly doing
nothing, and why the incident has no log line pointing at the cause.

The full form has four clauses:

    try:        ...   # the risky operation, kept as small as possible
    except E:   ...   # handle
    else:       ...   # runs only if no exception — keeps the try block tight
    finally:    ...   # always runs, even on return/raise — cleanup

**Chaining** preserves the cause: `raise MyError("...") from exc` keeps the
original traceback attached. Bare `raise MyError(...)` inside an `except` block
still chains implicitly (as "During handling..."), but `from exc` states intent.
`from None` suppresses the chain — use it only when the inner error is noise.

**Custom hierarchies** let callers choose their granularity:

    class ForgeError(Exception): ...
    class NotFoundError(ForgeError): ...
    class ConflictError(ForgeError): ...

A caller can now catch `ForgeError` for "anything our domain raised" or
`NotFoundError` for one case — without catching unrelated library errors.
""",
        examples=[
            example(
                "else and finally earn their keep",
                """
try:
    conn = pool.acquire()
except PoolExhausted:
    metrics.incr("pool.exhausted")
    raise
else:
    # Only runs if acquire() succeeded - so this code is not accidentally
    # inside the try, where its own KeyError would be caught above.
    result = conn.execute(query)
finally:
    pool.release(conn)
""",
            ),
            example(
                "Chaining",
                """
try:
    value = payload["user_id"]
except KeyError as exc:
    raise ValidationFailedError("user_id is required") from exc
""",
                note="The API caller sees a clean message; the log keeps the KeyError.",
            ),
        ],
        common_mistakes=[
            mistake(
                "`except Exception: pass`",
                "Silences real bugs. The system continues in an undesigned state.",
                "Catch specific types; log with context; re-raise what you cannot handle.",
                Severity.CRITICAL,
            ),
            mistake(
                "A try block wrapping 30 lines",
                "You no longer know which line raised, and unrelated errors get caught by the "
                "same handler.",
                "Wrap the smallest risky operation; use `else` for the follow-on work.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "A domain exception hierarchy mapped to HTTP status codes in one place.",
            "Retry logic that catches only transient errors and lets logic errors surface.",
        ],
        requires=["python-args-kwargs"],
        related=["python-context-managers"],
        tags=["errors", "robustness"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="python-closures",
        title="Closures and the Late-Binding Trap",
        category=C,
        skill_node="python.functions",
        difficulty=5,
        summary="Inner functions capture variables by reference, not by value.",
        explanation="""
A closure is a function that remembers the enclosing scope it was created in.
The captured names live in a cell object, reachable via `fn.__closure__`.

The critical detail: **closures capture the variable, not its value at
creation time.** This is late binding, and it produces the classic surprise:

    fns = [lambda: i for i in range(3)]
    [f() for f in fns]        # [2, 2, 2]   - not [0, 1, 2]

All three lambdas close over the *same* `i`, and by the time they are called
the loop has finished with `i == 2`.

Two fixes, with different meanings:

    fns = [lambda i=i: i for i in range(3)]   # bind now, as a default argument
    fns = [partial(lambda i: i, i) for i in range(3)]   # bind now, explicitly

`nonlocal` lets an inner function *rebind* an enclosing name (not just read
it) — that is the difference between a counter that works and an
`UnboundLocalError`:

    def counter():
        n = 0
        def tick():
            nonlocal n      # without this, `n += 1` makes n local and raises
            n += 1
            return n
        return tick

Closures are how decorators carry configuration, how callbacks remember
context, and how `functools.partial` is conceptually implemented.
""",
        examples=[
            example(
                "Inspecting the cell",
                """
def make(x):
    def inner():
        return x
    return inner

f = make(42)
print(f.__closure__[0].cell_contents)
""",
                output="42",
            ),
        ],
        common_mistakes=[
            mistake(
                "Creating closures in a loop",
                "Every closure shares the loop variable, so they all see its final value.",
                "Bind per-iteration with a default argument or functools.partial.",
                Severity.HIGH,
            ),
            mistake(
                "Assigning to an enclosing name without `nonlocal`",
                "The assignment makes the name local to the inner function, so reading it first "
                "raises UnboundLocalError.",
                "Declare `nonlocal name` (or `global` at module level).",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Decorators storing their arguments.",
            "Event callbacks in an async server that must remember which request they belong to.",
        ],
        requires=["python-args-kwargs"],
        related=["python-decorators-basics"],
        tags=["functions", "scope"],
        estimated_minutes=8,
    ),
    ConceptSpec(
        slug="python-decorators-basics",
        title="Decorators",
        category=C,
        skill_node="python.decorators",
        difficulty=5,
        summary="A decorator is a function that takes a function and returns a replacement.",
        explanation="""
`@decorator` is pure syntax sugar:

    @timed
    def work(): ...
    # is exactly
    def work(): ...
    work = timed(work)

That is the whole idea. Everything else is consequence.

**Always use `functools.wraps`.** Without it the returned wrapper has its own
`__name__`, `__doc__`, `__module__`, type hints and signature — so `help()`,
tracebacks, Sphinx, `inspect.signature`, and every framework that dispatches on
function metadata (FastAPI reads the signature to build the request model!)
sees `wrapper` instead of `work`.

    import functools

    def timed(fn):
        @functools.wraps(fn)          # copies metadata AND sets __wrapped__
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                log.info("timing", fn=fn.__name__, ms=(time.perf_counter()-start)*1000)
        return wrapper

**Decorators with arguments** need one more layer, because `@retry(3)` is
*called* first and its return value is the decorator:

    def retry(times):
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                for attempt in range(times):
                    try:
                        return fn(*args, **kwargs)
                    except TransientError:
                        if attempt == times - 1:
                            raise
            return wrapper
        return decorator

**Async functions need an async wrapper.** A plain `def wrapper` around an
`async def` returns the coroutine object without awaiting it — the decorator
appears to work and the timing is always ~0. Check with
`inspect.iscoroutinefunction(fn)` and return an `async def wrapper` that awaits.

**The cost.** Every decorator adds a frame to the traceback and a layer of
indirection. A framework three decorators deep is genuinely harder to debug, and
"should we keep this decorator-heavy architecture?" is a real staff-level
question with a real answer: it depends on whether the cross-cutting concern is
stable (auth, tracing — yes) or business logic (no).
""",
        examples=[
            example(
                "Without wraps, metadata is destroyed",
                """
def bad(fn):
    def wrapper(*a, **kw): return fn(*a, **kw)
    return wrapper

@bad
def greet(name: str) -> str:
    "Say hello."
    return f"hi {name}"

print(greet.__name__, repr(greet.__doc__))
""",
                output="wrapper None",
                note="FastAPI would now build the wrong request model for this endpoint.",
            ),
            example(
                "Async-aware decorator",
                """
import functools, inspect

def timed(fn):
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def awrapper(*a, **kw):
            return await fn(*a, **kw)
        return awrapper
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return fn(*a, **kw)
    return wrapper
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Forgetting functools.wraps",
                "Loses __name__, __doc__, signature and type hints; breaks introspection-based "
                "frameworks and makes tracebacks useless.",
                "Always @functools.wraps(fn) on the wrapper.",
                Severity.HIGH,
            ),
            mistake(
                "A sync wrapper around an async function",
                "Returns the un-awaited coroutine. The wrapped behaviour never happens.",
                "Branch on inspect.iscoroutinefunction and provide an async wrapper.",
                Severity.CRITICAL,
            ),
        ],
        real_world_usage=[
            "@app.get(...) in FastAPI, @pytest.fixture, @functools.lru_cache.",
            "Cross-cutting auth, tracing and rate limiting without touching business logic.",
        ],
        requires=["python-closures", "python-args-kwargs"],
        related=["python-generators", "fastapi-dependency-injection"],
        tags=["functions", "metaprogramming"],
        estimated_minutes=12,
        visualization={"type": "call_stack", "scenario": "decorator_layers"},
    ),
    ConceptSpec(
        slug="python-iterators",
        title="The Iterator Protocol",
        category=C,
        skill_node="python.iterators",
        difficulty=4,
        summary="`for` is sugar over `__iter__` and `__next__` — knowing that explains everything else.",
        explanation="""
A `for` loop is not a primitive. This:

    for item in things:
        use(item)

is compiled to roughly:

    it = iter(things)          # calls things.__iter__()
    while True:
        try:
            item = next(it)    # calls it.__next__()
        except StopIteration:
            break
        use(item)

Two distinct roles:

* **Iterable** — has `__iter__()` returning a fresh iterator. Lists, dicts,
  strings, files. Can be looped many times.
* **Iterator** — has `__next__()` and an `__iter__()` returning `self`. Stateful
  and one-shot: once exhausted it stays exhausted.

This is why a generator can only be consumed once, why `zip(a, b)` is empty the
second time, and why `list(it)` after a `for` over `it` gives you `[]`.

`StopIteration` is not an error condition; it is how an iterator says "done".
(Inside a generator, a `StopIteration` that escapes is converted to a
`RuntimeError` by PEP 479 — precisely because silently ending a loop from deep
inside a call was a bug factory.)

Writing one by hand is rarely necessary — a generator does it in three lines —
but understanding the protocol is what makes `itertools`, streaming pipelines
and lazy evaluation make sense rather than feel magical.
""",
        examples=[
            example(
                "A hand-written iterator",
                """
class Countdown:
    def __init__(self, n): self.n = n
    def __iter__(self): return self
    def __next__(self):
        if self.n <= 0:
            raise StopIteration
        self.n -= 1
        return self.n + 1

print(list(Countdown(3)))
c = Countdown(3); list(c); print(list(c))   # exhausted
""",
                output="[3, 2, 1]\n[]",
            ),
        ],
        common_mistakes=[
            mistake(
                "Expecting to iterate a generator twice",
                "Iterators are one-shot. The second pass sees an exhausted object, not an error.",
                "Materialise to a list, or create a fresh generator per pass.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Streaming database cursors and paginated API clients.",
            "itertools pipelines that never materialise the full dataset.",
        ],
        requires=["python-comprehensions"],
        related=["python-generators"],
        tags=["protocols", "iteration"],
        estimated_minutes=8,
    ),
    ConceptSpec(
        slug="python-generators",
        title="Generators",
        category=C,
        skill_node="python.generators",
        difficulty=5,
        summary="Functions that pause. Lazy, constant-memory pipelines in three lines.",
        explanation="""
Any function containing `yield` is a generator function. Calling it runs **no
code** — it returns a generator object. Execution starts at the first `next()`,
runs to the `yield`, and *freezes* the entire frame (locals, instruction
pointer) until the next `next()`.

    def read_lines(path):
        with open(path) as f:
            for line in f:
                yield line.strip()

That holds one line in memory regardless of file size, and — critically — the
`with` block stays open across yields, closing when the generator is exhausted
or garbage-collected.

**Pipelines** compose without materialising anything:

    lines    = read_lines("access.log")
    parsed   = (parse(l) for l in lines)
    errors   = (p for p in parsed if p.status >= 500)
    first_10 = itertools.islice(errors, 10)

Nothing has been read yet. Consuming `first_10` pulls exactly as many lines as
needed — possibly ten, not the whole file.

**Two-way communication.** `yield` is an expression, so a generator can receive:

    def accumulator():
        total = 0
        while True:
            value = yield total      # receives what .send(value) passes
            total += value

    acc = accumulator()
    next(acc)          # prime it: run to the first yield
    acc.send(10)       # 10
    acc.send(5)        # 15

`yield from sub()` delegates to another generator, forwarding values, `send`,
and exceptions — and is what made `async`/`await` expressible before it had its
own syntax.

**The trade-offs.** Generators cannot be indexed, have no `len()`, cannot be
re-iterated, and make debugging harder (the stack at the point of failure is
the consumer's, not the producer's). Use them when the data is large, the
source is streaming, or the pipeline may terminate early. Use a list when the
data is small and you will touch it more than once.
""",
        examples=[
            example(
                "Memory, measured",
                """
def squares(n):
    for i in range(n):
        yield i * i

import sys
print(sys.getsizeof(squares(10_000_000)))       # bytes
print(sys.getsizeof([i*i for i in range(1000)]))
""",
                output="200\n8856",
                note="The generator's size is constant no matter how many values it will produce.",
            ),
            example(
                "Early termination costs nothing",
                """
def naturals():
    n = 0
    while True:
        n += 1
        yield n

first_even_over_100 = next(n for n in naturals() if n > 100 and n % 2 == 0)
print(first_even_over_100)
""",
                output="102",
                note="An infinite sequence is fine because nothing is computed in advance.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Calling list() on a generator immediately",
                "Throws away the entire memory benefit.",
                "Keep it lazy until you genuinely need random access or multiple passes.",
                Severity.MEDIUM,
            ),
            mistake(
                "Assuming the function body ran at call time",
                "No code runs until the first next(). A validation `raise` at the top of a "
                "generator function fires late — at iteration, not at call.",
                "Validate in a thin wrapper function that returns the generator.",
                Severity.MEDIUM,
            ),
            mistake(
                "Leaking resources in an abandoned generator",
                "If a generator holding an open file is never exhausted, cleanup waits for GC.",
                "Use `with` inside the generator and close deterministically, or "
                "contextlib.closing.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Processing a 40GB CSV on a 2GB container.",
            "Paginated API clients that yield records while fetching pages behind the scenes.",
            "`yield` in a FastAPI dependency to run setup/teardown around a request.",
        ],
        requires=["python-iterators"],
        related=["python-context-managers", "python-asyncio-coroutines"],
        tags=["iteration", "performance", "memory"],
        estimated_minutes=12,
        visualization={"type": "generator_timeline", "scenario": "lazy_pipeline"},
    ),
    ConceptSpec(
        slug="python-context-managers",
        title="Context Managers",
        category=C,
        skill_node="python.context",
        difficulty=5,
        summary="Guaranteed setup and teardown, even when the body raises.",
        explanation="""
`with` guarantees cleanup. The protocol is two methods:

    class Transaction:
        def __enter__(self):
            self.conn = pool.acquire()
            self.conn.begin()
            return self.conn              # bound to the `as` name
        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            pool.release(self.conn)
            return False                  # False => re-raise; True => SWALLOW

The `__exit__` return value is the subtle part. Returning a truthy value
**suppresses the exception** — almost always wrong, and a silent one when it is.
Return `False` (or nothing) unless suppression is the explicit purpose, as in
`contextlib.suppress`.

`contextlib.contextmanager` turns a generator into a context manager, which is
usually clearer:

    from contextlib import contextmanager

    @contextmanager
    def transaction():
        conn = pool.acquire()
        conn.begin()
        try:
            yield conn          # everything before = __enter__, after = __exit__
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            pool.release(conn)

Note the `try/finally`: without it, an exception in the body would propagate
out of the `yield` and the release would never run — the exact bug the context
manager exists to prevent.

Async resources need `__aenter__`/`__aexit__` and `async with`
(`@contextlib.asynccontextmanager` for the generator form). Using plain `with`
on an async resource silently fails to acquire it.
""",
        examples=[
            example(
                "Suppressing on purpose",
                """
from contextlib import suppress

with suppress(FileNotFoundError):
    os.remove(path)          # fine if it is already gone
""",
            ),
            example(
                "Multiple resources",
                """
with open(src) as fin, open(dst, "w") as fout:
    fout.write(fin.read())
# Both closed, in reverse order, even if write() raises.
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Returning True from __exit__",
                "Swallows every exception raised in the body.",
                "Return False/None unless suppression is the documented purpose.",
                Severity.HIGH,
            ),
            mistake(
                "No try/finally around the yield in @contextmanager",
                "An exception in the body skips the teardown entirely.",
                "Wrap the yield in try/finally (or try/except/else/finally).",
                Severity.HIGH,
            ),
            mistake(
                "`with` on an async resource",
                "Calls __enter__, which does not exist; or worse, acquires nothing.",
                "Use `async with` for anything with __aenter__.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Database transactions, file handles, locks, temp directories.",
            "`async with session.begin()` in SQLAlchemy; FastAPI's `lifespan`.",
        ],
        requires=["python-exceptions", "python-generators"],
        related=["python-asyncio-basics"],
        tags=["resources", "protocols"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="python-dataclass-vs-pydantic",
        title="dataclass vs NamedTuple vs TypedDict vs Pydantic",
        category=C,
        skill_node="python.dataclasses",
        difficulty=5,
        summary="Four ways to model a record. They differ on validation, mutability and cost.",
        explanation="""
|                | validates | mutable | runtime cost | use when |
|----------------|-----------|---------|--------------|----------|
| `dataclass`    | no        | yes*    | lowest       | internal structured data |
| `NamedTuple`   | no        | no      | lowest       | small immutable records, tuple-compatible |
| `TypedDict`    | no**      | yes     | zero         | a dict shape you must keep as a dict |
| `pydantic.BaseModel` | **yes** | yes* | highest | data crossing a trust boundary |

\\* `frozen=True` / `model_config = ConfigDict(frozen=True)` makes them immutable.
\\*\\* TypedDict is a *static* type only — at runtime it is a plain dict with no checks.

**The decision rule is about trust.** Data arriving from outside your process —
an HTTP body, a queue message, a config file, an LLM response — is untrusted and
must be *parsed*, which means Pydantic. Data you constructed yourself five lines
ago is trusted and only needs *structure*, which means a dataclass.

Using Pydantic everywhere costs real time: validation runs on every
instantiation, and in a hot loop over a million rows that is measurable. Using
dataclasses at the boundary costs correctness: a `price: float` annotation on a
dataclass does not stop `price="abc"` — annotations are not enforced at runtime.

`NamedTuple` is worth remembering for one specific property: it *is* a tuple, so
it unpacks and indexes, which makes it a drop-in upgrade for code currently
returning anonymous tuples.

In this codebase: Pydantic for every request/response schema, dataclasses for
the pure game engines, `TypedDict` nowhere (we prefer real types).
""",
        examples=[
            example(
                "Annotations are not validation",
                """
from dataclasses import dataclass

@dataclass
class Product:
    name: str
    price: float

p = Product(name=123, price="free")   # no error at all
print(p)
""",
                output="Product(name=123, price='free')",
                note="If this came from a request body, you now have garbage in your database.",
            ),
            example(
                "Pydantic parses and coerces",
                """
from pydantic import BaseModel, Field

class Product(BaseModel):
    name: str = Field(min_length=1)
    price: float = Field(gt=0)

Product(name="Widget", price="19.99")   # -> price=19.99 (float)
Product(name="", price=-1)              # raises ValidationError with both problems
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Trusting dataclass annotations to validate",
                "They are hints. Nothing checks them at runtime.",
                "Use Pydantic at trust boundaries.",
                Severity.HIGH,
            ),
            mistake(
                "Pydantic models in a hot inner loop",
                "Validation on every instantiation dominates the loop.",
                "Validate once at the boundary, then pass plain dataclasses inward.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "FastAPI request/response models (Pydantic) vs. internal service DTOs (dataclass).",
            "`frozen=True` dataclasses as dict keys and cache keys.",
        ],
        requires=["python-names-and-objects"],
        related=["pydantic-validation"],
        tags=["typing", "modelling"],
        estimated_minutes=10,
    ),
]


# ═════════════════════════════════════════════════════════════════════════════
# CHALLENGES
# ═════════════════════════════════════════════════════════════════════════════
CHALLENGES = [
    ChallengeSpec(
        slug="py-dedupe-preserve-order",
        title="De-duplicate Without Losing Order",
        category=C,
        tier=T.IMPLEMENT,
        prompt="""
The ingest pipeline receives event IDs with duplicates. Downstream needs them
**de-duplicated but in first-seen order**.

Implement `dedupe(items)`. It must be O(n), not O(n²) — the production input is
8 million IDs and the current `if x not in result` version takes 40 minutes.
""",
        starter_code="def dedupe(items):\n    ...\n",
        reference_solution="""
def dedupe(items):
    # dict preserves insertion order (3.7+) and gives O(1) membership.
    return list(dict.fromkeys(items))
""",
        solution_explanation=(
            "`dict.fromkeys` is O(n): each key hashes once, and dicts have preserved insertion "
            "order since 3.7. A set would also be O(n) but loses order. The naive "
            "`if x not in result` on a list is O(n²) because each `in` is a linear scan."
        ),
        tests=[
            eq("preserves first-seen order", "dedupe([3, 1, 3, 2, 1])", [3, 1, 2]),
            eq("empty input", "dedupe([])", []),
            eq("no duplicates", "dedupe(['a', 'b'])", ["a", "b"]),
            eq("all identical", "dedupe([7, 7, 7])", [7], hidden=True),
            predicate(
                "does not mutate the input",
                "(lambda src: (dedupe(src), src)[1])([2, 1, 2])",
                "result == [2, 1, 2]",
                hidden=True,
            ),
            script(
                "is O(n), not O(n^2)",
                """
import time
data = list(range(60000)) * 2
start = time.perf_counter()
out = dedupe(data)
elapsed = time.perf_counter() - start
assert out == list(range(60000)), "wrong result on the large input"
assert elapsed < 1.0, f"took {elapsed:.2f}s - this looks quadratic"
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["python-list-vs-tuple-vs-set-vs-dict", "python-comprehensions"],
        hints=[
            "What is the time complexity of `x in some_list`? Now put that inside a loop.",
            "Which built-in container gives O(1) membership testing?",
            "Sets lose order. Which container has O(1) lookup *and* remembers insertion order?",
        ],
        explanation_prompts=[
            point(
                "States the naive version is O(n²)",
                "o(n^2)",
                "o(n2)",
                "quadratic",
                "n squared",
                weight=2,
            ),
            point("Explains why set/dict lookup is O(1)", "hash", "hash table", weight=2),
            point("Addresses order preservation", "order", "insertion", weight=1.5),
        ],
        expected_complexity="O(n)",
        par_seconds=300,
    ),
    ChallengeSpec(
        slug="py-fix-mutable-default",
        title="The Basket That Remembers",
        category=C,
        tier=T.DEBUG,
        prompt="""
🚨 **Incident #4412** — Customers are reporting other people's items in their baskets.

The cart service has been running for three days. The bug does not reproduce on
the first request. Find it and fix it.

The function's contract: `add_item(item, basket=None)` returns a basket
containing the item, creating a **fresh** basket when none is supplied.
""",
        broken_code="""
def add_item(item, basket=[]):
    basket.append(item)
    return basket
""",
        starter_code="""
def add_item(item, basket=[]):
    basket.append(item)
    return basket
""",
        reference_solution="""
def add_item(item, basket=None):
    # None sentinel: the default is evaluated once at def time, so a mutable
    # default would be shared by every call that relies on it.
    if basket is None:
        basket = []
    basket.append(item)
    return basket
""",
        solution_explanation=(
            "Default arguments are evaluated once, when the `def` statement executes. The list "
            "literal becomes a single object stored on the function and shared by every call "
            "that does not pass a basket. Using `None` as a sentinel and building the list "
            "inside the body gives each call its own. Note `is None` rather than `if not basket` "
            "— an empty basket the caller deliberately passed is a different case."
        ),
        tests=[
            eq("adds to a supplied basket", "add_item('x', ['a'])", ["a", "x"]),
            eq("first call with no basket", "add_item('x')", ["x"]),
            script(
                "consecutive calls do not share state",
                """
first = add_item("a")
second = add_item("b")
assert first == ["a"], f"first basket leaked: {first}"
assert second == ["b"], f"second basket inherited state: {second}"
assert first is not second, "both calls returned the same object"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "an explicitly empty basket is respected",
                """
supplied = []
out = add_item("z", supplied)
assert out is supplied, "should append to the caller's list, not a copy"
""",
                hidden=True,
            ),
        ],
        concepts=["python-mutable-defaults", "python-names-and-objects"],
        hints=[
            "When exactly is the expression `[]` in the signature evaluated?",
            "Try calling the function twice with no basket and printing both results.",
            "Inspect `add_item.__defaults__` after a few calls.",
        ],
        explanation_prompts=[
            point(
                "Says defaults are evaluated once at definition",
                "def time",
                "once",
                "definition",
                "import",
                weight=3,
            ),
            point(
                "Explains the shared-object consequence",
                "shared",
                "same object",
                "same list",
                weight=2,
            ),
            point("Names the None-sentinel fix", "none", "sentinel", weight=2),
            point("Notes `is None` over truthiness", "is none", weight=1, dimension="depth"),
        ],
        par_seconds=240,
    ),
    ChallengeSpec(
        slug="py-chunked-generator",
        title="Stream a File in Batches",
        category=C,
        tier=T.IMPLEMENT,
        prompt="""
The ingest worker must POST records to an API in batches of `size`, but the
source file is 40GB and the container has 2GB of RAM.

Implement `chunked(iterable, size)` as a **generator** that yields lists of at
most `size` items. It must never hold more than one chunk in memory, and must
work on an infinite iterable.

The final chunk may be shorter. A `size` below 1 is a programming error.
""",
        starter_code="def chunked(iterable, size):\n    ...\n",
        reference_solution="""
def chunked(iterable, size):
    if size < 1:
        raise ValueError("size must be >= 1")
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []          # rebind, do NOT clear() - the consumer holds it
    if batch:
        yield batch
""",
        solution_explanation=(
            "Accumulate into a list and yield when full. The critical detail is `batch = []` "
            "rather than `batch.clear()`: the consumer holds a reference to the list we just "
            "yielded, and clearing it would empty the batch they are still using. Because it is "
            "a generator, only one chunk exists at a time, so memory is O(size) rather than "
            "O(n) — which is what makes a 40GB file fit in 2GB."
        ),
        tests=[
            eq("even split", "list(chunked([1,2,3,4], 2))", [[1, 2], [3, 4]]),
            eq("ragged final chunk", "list(chunked([1,2,3,4,5], 2))", [[1, 2], [3, 4], [5]]),
            eq("empty source", "list(chunked([], 3))", []),
            eq("size larger than input", "list(chunked([1], 10))", [[1]], hidden=True),
            raises("rejects size 0", "list(chunked([1], 0))", "ValueError", hidden=True),
            predicate(
                "returns a generator, not a list",
                "chunked([1,2,3], 2)",
                "hasattr(result, '__next__')",
                points=2.0,
            ),
            script(
                "is lazy enough for an infinite source",
                """
import itertools
infinite = itertools.count()
gen = chunked(infinite, 3)
assert next(gen) == [0, 1, 2]
assert next(gen) == [3, 4, 5]
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "previously yielded chunks are not mutated",
                """
chunks = list(chunked([1, 2, 3, 4], 2))
assert chunks == [[1, 2], [3, 4]], f"earlier chunk was mutated: {chunks}"
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["python-generators", "python-iterators"],
        hints=[
            "Accumulate into a list; yield it when it reaches `size`.",
            "Don't forget the partial batch after the loop ends.",
            "After yielding, do you `clear()` the list or bind a new one? Who else is holding it?",
        ],
        explanation_prompts=[
            point("Explains constant memory", "memory", "constant", "o(size)", "lazy", weight=2),
            point(
                "Handles the trailing partial batch",
                "final",
                "partial",
                "remaining",
                "leftover",
                weight=1.5,
            ),
            point(
                "Notes rebinding vs clear()",
                "clear",
                "rebind",
                "new list",
                weight=2,
                dimension="depth",
            ),
        ],
        expected_complexity="O(n) time, O(size) memory",
        par_seconds=420,
    ),
    ChallengeSpec(
        slug="py-retry-decorator",
        title="Build a Retry Decorator",
        category=C,
        tier=T.IMPLEMENT,
        prompt="""
The payments client fails transiently ~2% of the time. Write a `retry`
decorator, parameterised by attempt count, that:

1. retries only on `TransientError` (provided in the setup),
2. gives up after `times` total attempts and re-raises the last exception,
3. preserves the wrapped function's `__name__` and `__doc__`,
4. exposes the number of attempts made as `wrapper.attempts`.

Usage: `@retry(3)`.
""",
        setup_code="""
class TransientError(Exception):
    pass
""",
        starter_code="""
import functools

def retry(times):
    ...
""",
        reference_solution="""
import functools

def retry(times):
    def decorator(fn):
        @functools.wraps(fn)          # preserves __name__, __doc__, signature
        def wrapper(*args, **kwargs):
            wrapper.attempts = 0
            last = None
            for _ in range(times):
                wrapper.attempts += 1
                try:
                    return fn(*args, **kwargs)
                except TransientError as exc:
                    last = exc
            raise last
        wrapper.attempts = 0
        return wrapper
    return decorator
""",
        solution_explanation=(
            "Three nested layers because `@retry(3)` is a *call* whose return value is the "
            "decorator. `functools.wraps` copies metadata — without it the wrapper reports its "
            "own name and loses the signature, which breaks introspection-based frameworks. "
            "Only `TransientError` is caught, so a genuine bug (a TypeError, say) surfaces "
            "immediately instead of being retried three times and then re-raised with a "
            "confusing stack."
        ),
        tests=[
            script(
                "succeeds first time",
                """
calls = []
@retry(3)
def ok():
    "docstring"
    calls.append(1)
    return "done"
assert ok() == "done"
assert len(calls) == 1, f"called {len(calls)} times, expected 1"
""",
            ),
            script(
                "retries then succeeds",
                """
state = {"n": 0}
@retry(3)
def flaky():
    state["n"] += 1
    if state["n"] < 3:
        raise TransientError("nope")
    return state["n"]
assert flaky() == 3
""",
            ),
            script(
                "gives up and re-raises",
                """
@retry(2)
def always():
    raise TransientError("always fails")
try:
    always()
except TransientError as exc:
    assert "always fails" in str(exc)
else:
    raise AssertionError("should have re-raised after exhausting attempts")
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "preserves metadata",
                """
@retry(2)
def documented():
    "the original docstring"
    return 1
assert documented.__name__ == "documented", f"__name__ is {documented.__name__!r}"
assert documented.__doc__ == "the original docstring"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "does not retry non-transient errors",
                """
count = {"n": 0}
@retry(5)
def bug():
    count["n"] += 1
    raise TypeError("a real bug")
try:
    bug()
except TypeError:
    pass
assert count["n"] == 1, f"retried a TypeError {count['n']} times - only TransientError should retry"
""",
                hidden=True,
                points=3.0,
            ),
        ],
        concepts=["python-decorators-basics", "python-closures", "python-exceptions"],
        hints=[
            "`@retry(3)` calls retry(3) first. What must that call return?",
            "Three levels: retry(times) -> decorator(fn) -> wrapper(*args, **kwargs).",
            "Catch only TransientError. What happens to a TypeError if you catch Exception?",
        ],
        explanation_prompts=[
            point(
                "Explains the three-layer structure",
                "three",
                "nested",
                "returns the decorator",
                weight=2,
            ),
            point("Justifies functools.wraps", "wraps", "metadata", "__name__", weight=2),
            point(
                "Argues for narrow exception catching",
                "narrow",
                "specific",
                "only transient",
                weight=2,
                dimension="depth",
            ),
            point(
                "Mentions backoff for real systems",
                "backoff",
                "jitter",
                "sleep",
                weight=1,
                dimension="production_awareness",
            ),
        ],
        par_seconds=600,
    ),
    ChallengeSpec(
        slug="py-fix-late-binding-closure",
        title="The Callbacks That All Do the Same Thing",
        category=C,
        tier=T.DEBUG,
        prompt="""
🚨 Every registered webhook handler is posting to the **last** configured URL.

`build_handlers(urls)` should return one callable per URL, each returning its
own URL. All of them return the last one instead. Fix it without changing the
function's signature or return type.
""",
        broken_code="""
def build_handlers(urls):
    handlers = []
    for url in urls:
        handlers.append(lambda: url)
    return handlers
""",
        starter_code="""
def build_handlers(urls):
    handlers = []
    for url in urls:
        handlers.append(lambda: url)
    return handlers
""",
        reference_solution="""
def build_handlers(urls):
    handlers = []
    for url in urls:
        # Default arguments are bound at definition time, which is exactly the
        # per-iteration capture we need here.
        handlers.append(lambda url=url: url)
    return handlers
""",
        solution_explanation=(
            "Closures capture the *variable*, not its value. All the lambdas share one `url` "
            "cell, and by the time any of them is called the loop has finished, so they all see "
            "the final value. Binding `url=url` as a default argument evaluates it immediately, "
            "once per iteration, giving each lambda its own. `functools.partial(lambda u: u, url)` "
            "is an equivalent fix that some teams prefer for being explicit about the capture."
        ),
        tests=[
            script(
                "each handler returns its own url",
                """
hs = build_handlers(["a", "b", "c"])
got = [h() for h in hs]
assert got == ["a", "b", "c"], f"got {got}"
""",
                points=3.0,
            ),
            eq("count matches", "len(build_handlers(['x', 'y']))", 2),
            script(
                "works with an empty list",
                "assert build_handlers([]) == []",
                hidden=True,
            ),
            script(
                "handlers are independent callables",
                """
hs = build_handlers([1, 2])
assert hs[0] is not hs[1]
assert hs[0]() == 1 and hs[1]() == 2
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["python-closures"],
        hints=[
            "Print the result of each handler. What do they all have in common?",
            "When is the value of `url` looked up — when the lambda is created, or when it is called?",
            "How can you force a value to be captured *now* rather than looked up later?",
        ],
        explanation_prompts=[
            point(
                "Names late binding",
                "late binding",
                "captures the variable",
                "by reference",
                weight=3,
            ),
            point(
                "Explains why all see the final value",
                "final value",
                "loop finished",
                "same cell",
                weight=2,
            ),
            point("Describes the default-argument fix", "default argument", "partial", weight=2),
        ],
        par_seconds=300,
    ),
    ChallengeSpec(
        slug="py-context-manager-transaction",
        title="A Transaction That Actually Rolls Back",
        category=C,
        tier=T.IMPLEMENT,
        prompt="""
Implement `transaction(conn)` as a context manager that:

* calls `conn.begin()` on entry,
* calls `conn.commit()` if the block completes normally,
* calls `conn.rollback()` if the block raises — and **lets the exception
  propagate**,
* always calls `conn.close()`, in both cases.

A fake connection that records its calls is provided as `FakeConn`.
""",
        setup_code="""
class FakeConn:
    def __init__(self):
        self.calls = []
    def begin(self):    self.calls.append("begin")
    def commit(self):   self.calls.append("commit")
    def rollback(self): self.calls.append("rollback")
    def close(self):    self.calls.append("close")
""",
        starter_code="""
from contextlib import contextmanager

@contextmanager
def transaction(conn):
    ...
""",
        reference_solution="""
from contextlib import contextmanager

@contextmanager
def transaction(conn):
    conn.begin()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise            # re-raise: swallowing here would hide the failure
    else:
        conn.commit()
    finally:
        conn.close()     # runs on both paths
""",
        solution_explanation=(
            "Everything before the `yield` is `__enter__`; everything after is `__exit__`. The "
            "`try/except/else/finally` shape matters: `except` handles the failure path and "
            "must `raise` (a context manager that swallows exceptions hides bugs), `else` runs "
            "only on success so the commit is not inside the try, and `finally` guarantees "
            "close on both paths. Without the try, an exception in the body would propagate "
            "straight out of the yield and neither rollback nor close would run."
        ),
        tests=[
            script(
                "commits on success",
                """
c = FakeConn()
with transaction(c) as conn:
    assert conn is c
assert c.calls == ["begin", "commit", "close"], c.calls
""",
                points=2.0,
            ),
            script(
                "rolls back and re-raises on failure",
                """
c = FakeConn()
try:
    with transaction(c):
        raise ValueError("boom")
except ValueError:
    pass
else:
    raise AssertionError("the exception was swallowed")
assert c.calls == ["begin", "rollback", "close"], c.calls
""",
                points=3.0,
            ),
            script(
                "closes even when rollback is not reached cleanly",
                """
c = FakeConn()
try:
    with transaction(c):
        raise KeyboardInterrupt()
except BaseException:
    pass
assert "close" in c.calls, c.calls
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["python-context-managers", "python-exceptions", "python-generators"],
        hints=[
            "Code before `yield` is entry; code after is exit.",
            "What happens to the code after `yield` if the body raises and you have no try?",
            "Which clause runs on both the success and failure paths?",
        ],
        explanation_prompts=[
            point(
                "Explains the yield split",
                "before the yield",
                "after the yield",
                "enter",
                "exit",
                weight=2,
            ),
            point("Justifies re-raising", "re-raise", "propagate", "swallow", weight=2),
            point("Explains finally", "finally", "both paths", "always", weight=2),
        ],
        par_seconds=480,
    ),
    ChallengeSpec(
        slug="py-flatten-nested",
        title="Flatten Arbitrarily Nested Lists",
        category=C,
        tier=T.IMPLEMENT,
        prompt="""
Implement `flatten(data)` yielding every non-list leaf of an arbitrarily nested
list structure, left to right. Strings are leaves, not sequences to descend into.

Return a generator so a deeply nested 100MB structure does not double in memory.
""",
        starter_code="def flatten(data):\n    ...\n",
        reference_solution="""
def flatten(data):
    for item in data:
        if isinstance(item, list):
            yield from flatten(item)     # delegates, forwarding every value
        else:
            yield item
""",
        solution_explanation=(
            "`yield from` delegates to the recursive call, forwarding each value without the "
            "intermediate `for x in flatten(item): yield x`. Strings are explicitly not "
            "descended into — `isinstance(item, list)` rather than checking for `__iter__` — "
            "because a string is iterable and would recurse down to single characters (and a "
            "one-character string is still iterable, so that path never terminates)."
        ),
        tests=[
            eq("flat input", "list(flatten([1, 2, 3]))", [1, 2, 3]),
            eq("one level", "list(flatten([1, [2, 3], 4]))", [1, 2, 3, 4]),
            eq("deep nesting", "list(flatten([1, [2, [3, [4, [5]]]]]))", [1, 2, 3, 4, 5]),
            eq("empty lists vanish", "list(flatten([[], [1], []]))", [1], hidden=True),
            eq(
                "strings are leaves",
                "list(flatten(['ab', ['cd']]))",
                ["ab", "cd"],
                hidden=True,
                points=2.0,
            ),
            predicate(
                "returns a generator", "flatten([1])", "hasattr(result, '__next__')", points=2.0
            ),
        ],
        concepts=["python-generators", "python-iterators"],
        hints=[
            "Recursion: for each item, is it a list or a leaf?",
            "`yield from` forwards every value from a sub-generator.",
            "Try `list(flatten(['ab']))` with an `__iter__` check instead of a list check. What happens?",
        ],
        explanation_prompts=[
            point("Explains yield from", "yield from", "delegate", weight=2),
            point(
                "Handles the string case deliberately",
                "string",
                "str",
                "character",
                weight=2,
                dimension="depth",
            ),
            point(
                "Mentions recursion depth limits",
                "recursion limit",
                "recursionerror",
                "depth",
                weight=1,
                dimension="production_awareness",
            ),
        ],
        expected_complexity="O(n)",
        par_seconds=360,
    ),
    ChallengeSpec(
        slug="py-group-by-key",
        title="Group Records Without a Second Pass",
        category=C,
        tier=T.IMPLEMENT,
        prompt="""
Implement `group_by(records, key)` returning a dict mapping each key value to
the list of records having it, **in first-seen order** within each group.

`records` is a list of dicts; `key` is the field name to group on. A record
missing the key goes under `None`.

Single pass. No sorting.
""",
        starter_code="def group_by(records, key):\n    ...\n",
        reference_solution="""
from collections import defaultdict

def group_by(records, key):
    out = defaultdict(list)
    for record in records:
        out[record.get(key)].append(record)
    return dict(out)     # return a plain dict: a defaultdict silently creates
                         # keys on read, which surprises callers
""",
        solution_explanation=(
            "`defaultdict(list)` removes the `if key not in out` branch, and `.get(key)` gives "
            "`None` for missing fields without a KeyError. Converting back to a plain dict "
            "before returning matters: a defaultdict handed to a caller will silently create an "
            "empty list the first time they check a key that does not exist, which turns a "
            "would-be KeyError into a subtle wrong-answer bug."
        ),
        tests=[
            script(
                "groups by field",
                """
rows = [{"t": "a", "n": 1}, {"t": "b", "n": 2}, {"t": "a", "n": 3}]
out = group_by(rows, "t")
assert set(out) == {"a", "b"}
assert [r["n"] for r in out["a"]] == [1, 3]
assert [r["n"] for r in out["b"]] == [2]
""",
                points=2.0,
            ),
            eq("empty input", "group_by([], 'x')", {}),
            script(
                "missing key groups under None",
                """
out = group_by([{"a": 1}, {"b": 2}], "a")
assert None in out, f"keys were {list(out)}"
assert out[None] == [{"b": 2}]
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "returns a plain dict, not a defaultdict",
                """
out = group_by([{"k": 1}], "k")
try:
    out["missing"]
except KeyError:
    pass
else:
    raise AssertionError("returned a defaultdict - callers will get silent empty lists")
""",
                hidden=True,
                points=3.0,
            ),
        ],
        concepts=["python-list-vs-tuple-vs-set-vs-dict", "python-comprehensions"],
        hints=[
            "`collections.defaultdict(list)` removes the 'create the list if missing' branch.",
            "`dict.get(key)` returns None instead of raising for a missing field.",
            "Should the *caller* get a defaultdict back? What happens when they check a key that isn't there?",
        ],
        explanation_prompts=[
            point("Explains defaultdict", "defaultdict", weight=1.5),
            point(
                "Justifies returning a plain dict",
                "plain dict",
                "silently",
                "surprise",
                weight=2,
                dimension="depth",
            ),
            point("Notes it is a single O(n) pass", "single pass", "o(n)", "one pass", weight=1.5),
        ],
        expected_complexity="O(n)",
        par_seconds=300,
    ),
]


# ═════════════════════════════════════════════════════════════════════════════
# QUESTIONS
# ═════════════════════════════════════════════════════════════════════════════
QUESTIONS = [
    QuestionSpec(
        slug="q-py-is-vs-eq",
        kind=Q.MCQ,
        category=C,
        tier=T.UNDERSTAND,
        level=L.JUNIOR,
        prompt="What does `a is b` test?",
        concepts=["python-names-and-objects"],
        options=[
            opt(
                "a", "Whether a and b have equal values", why="That is `==`, which calls `__eq__`."
            ),
            opt(
                "b",
                "Whether a and b are the same object in memory",
                correct=True,
                why="`is` compares identity — `id(a) == id(b)`. It never calls `__eq__`.",
            ),
            opt(
                "c",
                "Whether a and b have the same type",
                why="That is `type(a) is type(b)` or isinstance.",
            ),
            opt(
                "d",
                "Whether a and b are both truthy",
                why="Truthiness is `bool(a)`, unrelated to identity.",
            ),
        ],
        expected_answer="`is` compares object identity; `==` compares value.",
        ideal_senior_answer=(
            "`is` compares identity — literally whether both names point at the same object. "
            "`==` dispatches to `__eq__`. They appear interchangeable for small integers and "
            "interned strings because CPython caches those, which is an implementation detail "
            "you should never rely on: `257 is 257` can be False. Reserve `is` for singletons — "
            "`is None`, `is True`, and sentinel objects."
        ),
        common_wrong_answer="Assuming they are interchangeable because `x is 5` worked in the REPL.",
        rubric=[point("identity vs value", "identity", "same object", weight=3)],
        followups=[
            "Why does `256 is 256` return True but `257 is 257` return False in CPython?",
            "When would you deliberately choose `is` over `==`?",
        ],
        tags=["fundamentals"],
        par_seconds=60,
    ),
    QuestionSpec(
        slug="q-py-list-membership-complexity",
        kind=Q.SCENARIO,
        category=C,
        tier=T.OPTIMIZE,
        level=L.MID,
        prompt="""
This endpoint times out in production but is instant locally. `banned_ids` has
~50,000 entries in production and 12 in your fixtures.

What is wrong, why does it only show up in production, and what would you change?
""",
        context="""
def filter_users(users, banned_ids):
    return [u for u in users if u["id"] not in banned_ids]

# banned_ids is a list returned by the compliance service
""",
        concepts=["python-list-vs-tuple-vs-set-vs-dict"],
        expected_answer=(
            "`in` against a list is O(n). Inside a comprehension over m users that is O(n·m). "
            "Convert banned_ids to a set once, making each lookup O(1) and the whole function "
            "O(n + m)."
        ),
        ideal_senior_answer=(
            "Membership testing against a list is a linear scan, so this is O(n·m): 50,000 banned "
            "IDs times however many users. With 12 fixture entries the constant is invisible, "
            "which is why local testing passes — the bug is in the *data*, not the logic. "
            "The fix is one line: `banned = set(banned_ids)` before the comprehension, making "
            "each lookup an O(1) hash lookup. Beyond the fix, I would ask why the compliance "
            "service returns a list at all, add a test that exercises realistic cardinality, "
            "and consider whether 50k IDs belong in the application at all rather than as a "
            "`WHERE id NOT IN` or a join in the database — shipping the whole ban list over the "
            "network on every request is the deeper problem."
        ),
        common_wrong_answer=(
            "Blaming the database or adding caching, without noticing the complexity of the "
            "membership test."
        ),
        rubric=[
            point("Identifies O(n) list membership", "o(n)", "linear", "scan", weight=3),
            point(
                "Names the O(n·m) overall cost",
                "o(n*m)",
                "o(nm)",
                "quadratic",
                "n times m",
                weight=2,
            ),
            point("Proposes converting to a set", "set(", "set ", "hash", weight=3),
            point(
                "Explains why local testing misses it",
                "fixture",
                "small",
                "data size",
                "production data",
                weight=2,
                dimension="practical_experience",
            ),
            point(
                "Questions the data flow",
                "database",
                "join",
                "where",
                "network",
                weight=1.5,
                dimension="architecture_thinking",
            ),
        ],
        hints=[
            "What is the complexity of `x in some_list`?",
            "The logic is identical in both environments. What differs?",
        ],
        followups=[
            "How would you catch this class of bug before production next time?",
            "At what size would you stop sending the ban list to the application at all?",
        ],
        tags=["performance", "debugging"],
        par_seconds=240,
    ),
    QuestionSpec(
        slug="q-py-decorator-metadata",
        kind=Q.EXPLAIN,
        category=C,
        tier=T.EXPLAIN,
        level=L.SENIOR,
        prompt="How does a decorator preserve the wrapped function's metadata, and what breaks if it doesn't?",
        concepts=["python-decorators-basics"],
        expected_answer=(
            "`functools.wraps` copies __name__, __doc__, __module__, __qualname__, __dict__ and "
            "__annotations__ onto the wrapper and sets __wrapped__. Without it, introspection "
            "sees the wrapper."
        ),
        ideal_senior_answer=(
            "A decorator returns a *different* function object, so by default the caller sees "
            "`wrapper` — its name, its (empty) docstring, its `(*args, **kwargs)` signature. "
            "`functools.wraps` is a decorator that copies `__name__`, `__qualname__`, `__doc__`, "
            "`__module__`, `__dict__` and `__annotations__` across, and sets `__wrapped__` so "
            "`inspect.signature` can follow the chain back to the real function. "
            "What breaks without it is concrete and expensive: tracebacks say `wrapper`, "
            "`help()` is useless, Sphinx documents nothing, `pytest` fixtures misbehave, and — "
            "the one that actually bites — FastAPI reads the signature and type hints to build "
            "the request model, so a decorated endpoint without `wraps` silently gets the wrong "
            "validation. Note that `wraps` copies metadata but does not *fix* the signature for "
            "everything; libraries that inspect `__code__` directly still see the wrapper."
        ),
        common_wrong_answer=(
            '"You use @functools.wraps" with no explanation of what it copies or why it matters.'
        ),
        rubric=[
            point("Names functools.wraps", "functools.wraps", "wraps", weight=3),
            point(
                "Lists what is copied", "__name__", "__doc__", "annotations", "signature", weight=2
            ),
            point("Mentions __wrapped__", "__wrapped__", weight=1.5, dimension="depth"),
            point(
                "Gives a concrete breakage",
                "traceback",
                "fastapi",
                "help",
                "sphinx",
                "introspection",
                weight=2.5,
                dimension="practical_experience",
            ),
            point(
                "Notes the limits of wraps",
                "does not",
                "still sees",
                "__code__",
                weight=1,
                dimension="depth",
            ),
        ],
        hints=[
            "What is the `__name__` of a function after you decorate it without wraps?",
            "Think about a framework that reads type hints off your function.",
        ],
        followups=[
            "How would you write a decorator that works on both sync and async functions?",
            "A framework in your codebase is three decorators deep and nobody can debug it. Keep the architecture or change it?",
        ],
        tags=["decorators", "introspection"],
        par_seconds=300,
    ),
    QuestionSpec(
        slug="q-py-generator-vs-list",
        kind=Q.TRADEOFF,
        category=C,
        tier=T.DESIGN,
        level=L.SENIOR,
        prompt="When would you return a list instead of a generator, and vice versa? Give the cost of each choice.",
        concepts=["python-generators", "python-comprehensions"],
        expected_answer=(
            "Generator for large/streaming/early-terminating data (O(1) memory, lazy). List when "
            "you need len(), indexing, multiple passes, or the data is small."
        ),
        ideal_senior_answer=(
            "Generator when the data is large, streaming, possibly infinite, or when the consumer "
            "may stop early — memory is O(1) instead of O(n) and you pay only for what is "
            "consumed. List when you need `len()`, indexing, or more than one pass, when the "
            "collection is small enough that laziness buys nothing, or when the producer holds a "
            "resource you want released deterministically. "
            "The costs people forget: a generator's exception surfaces at *consumption* time, in "
            "the consumer's stack frame, which makes debugging harder and can mean a failure "
            "escapes a `try` you thought wrapped it; a generator holding a file or a DB cursor "
            "keeps it open until exhausted or GC'd; and a generator returned across an API "
            "boundary makes the contract 'you may iterate this exactly once', which callers "
            "routinely violate. In a public interface I lean toward returning a list — or an "
            "explicit `Iterator[T]` in the type signature so the one-shot contract is at least "
            "documented."
        ),
        common_wrong_answer='"Generators are more efficient, so always use generators."',
        rubric=[
            point("Names memory as the generator benefit", "memory", "lazy", "o(1)", weight=2.5),
            point(
                "Names len/index/multiple passes as list needs",
                "len",
                "index",
                "twice",
                "multiple",
                "re-iterate",
                weight=2.5,
            ),
            point(
                "Mentions early termination", "early", "short-circuit", "stop", "islice", weight=1.5
            ),
            point(
                "Raises deferred exceptions or debugging cost",
                "exception",
                "traceback",
                "debug",
                "consumption",
                weight=2,
                dimension="depth",
            ),
            point(
                "Raises resource lifetime",
                "open",
                "cursor",
                "resource",
                "close",
                weight=1.5,
                dimension="production_awareness",
            ),
            point(
                "Considers the API contract",
                "api",
                "contract",
                "caller",
                "interface",
                weight=2,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "A teammate returns a generator from a public API method. What do you say in review?",
            "How would you make a generator safely re-iterable?",
        ],
        tags=["generators", "design"],
        par_seconds=360,
    ),
    QuestionSpec(
        slug="q-py-mutable-default-predict",
        kind=Q.PREDICT_OUTPUT,
        category=C,
        tier=T.UNDERSTAND,
        level=L.JUNIOR,
        prompt="What does this print, and why?",
        context="""
def append(item, target=[]):
    target.append(item)
    return target

print(append(1))
print(append(2))
print(append(3, []))
print(append(4))
""",
        concepts=["python-mutable-defaults"],
        expected_answer="[1] / [1, 2] / [3] / [1, 2, 4]",
        ideal_senior_answer=(
            "`[1]`, then `[1, 2]`, then `[3]`, then `[1, 2, 4]`. The default `[]` is evaluated "
            "once when the `def` executes and stored on the function object, so calls that omit "
            "`target` all share it and accumulate. The third call passes its own list, so it is "
            "unaffected — and the fourth shows the shared list was still there the whole time. "
            "In a long-running server this leaks state between requests."
        ),
        common_wrong_answer="[1] / [2] / [3] / [4] — assuming a fresh list per call.",
        rubric=[
            point("Gets the sequence right", "[1, 2]", "1, 2", weight=3),
            point(
                "Explains once-at-definition evaluation",
                "once",
                "def",
                "definition",
                "import",
                weight=3,
            ),
            point(
                "Notes the explicit list is independent",
                "own list",
                "passed",
                "unaffected",
                weight=1.5,
            ),
        ],
        followups=["How would you fix it?", "Why `is None` rather than `if not target`?"],
        tags=["gotcha"],
        par_seconds=120,
    ),
    QuestionSpec(
        slug="q-py-dataclass-vs-pydantic-choice",
        kind=Q.TRADEOFF,
        category=C,
        tier=T.STAFF_TRADEOFF,
        level=L.STAFF,
        prompt="""
A service ingests 2 million records per hour from a partner feed, transforms
them through four internal stages, and writes to Postgres.

A teammate proposes Pydantic models at every stage "for safety". What is your
position, and where exactly would you draw the line?
""",
        concepts=["python-dataclass-vs-pydantic"],
        expected_answer=(
            "Validate once at the trust boundary with Pydantic; use dataclasses internally. "
            "Re-validating trusted data costs throughput for no safety gain."
        ),
        ideal_senior_answer=(
            "I would validate exactly once, at the boundary where untrusted data enters — the "
            "partner feed — and use frozen dataclasses for the four internal stages. "
            "The reasoning is about trust, not about safety-in-general: after stage one, the "
            "data was constructed by our own code, so re-validating it does not catch partner "
            "errors, it catches *our* bugs — and a type checker plus tests catch those earlier "
            "and for free. At 2M records/hour, Pydantic validation at four stages is four full "
            "passes of per-field coercion; that is a real throughput cost with no corresponding "
            "risk reduction. "
            "Where I would *keep* validation internally: at any boundary where the data leaves "
            "the process and comes back — a queue, a cache, a retry from a dead-letter topic — "
            "because at that point it is untrusted again. I would also keep it on the write "
            "path into Postgres if the schema has invariants the type system cannot express. "
            "And I would push back on the framing: the safety we actually want here is a "
            "quarantine path for records that fail boundary validation, plus a metric on the "
            "failure rate, not more validation layers."
        ),
        common_wrong_answer=(
            "Agreeing that more validation is always safer, or refusing validation entirely to "
            "'keep it fast'."
        ),
        rubric=[
            point("States validate-once-at-the-boundary", "boundary", "once", "edge", weight=3),
            point(
                "Explains the trust argument",
                "trust",
                "untrusted",
                "our own code",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "Quantifies the throughput cost",
                "throughput",
                "per record",
                "cost",
                "overhead",
                "2 million",
                weight=2,
                dimension="production_awareness",
            ),
            point(
                "Identifies re-entry points as re-validation",
                "queue",
                "cache",
                "dead-letter",
                "leaves the process",
                weight=2,
                dimension="architecture_thinking",
            ),
            point(
                "Proposes a quarantine/metrics path",
                "quarantine",
                "dead letter",
                "metric",
                "reject",
                weight=2,
                dimension="production_awareness",
            ),
            point(
                "Considers type checking as the internal guarantee",
                "mypy",
                "type checker",
                "static",
                weight=1.5,
                dimension="depth",
            ),
        ],
        hints=[
            "What is validation actually protecting you from at stage three?",
            "Where does the data stop being under your control?",
        ],
        followups=[
            "How would you measure whether the validation cost is actually material here?",
            "The partner changes their schema without telling you. Which design finds out first?",
        ],
        tags=["architecture", "performance", "pydantic"],
        par_seconds=420,
    ),
    QuestionSpec(
        slug="q-py-exception-swallowing",
        kind=Q.CODE_REVIEW,
        category=C,
        tier=T.DEBUG,
        level=L.MID,
        prompt="Review this code. What would you comment on, and how would you justify each point?",
        context="""
def process_batch(records):
    results = []
    for r in records:
        try:
            results.append(transform(r))
        except:
            pass
    return results
""",
        concepts=["python-exceptions"],
        expected_answer=(
            "Bare except catches KeyboardInterrupt/SystemExit; `pass` discards the error with no "
            "log; failures are silently dropped from the output with no count or dead-letter path."
        ),
        ideal_senior_answer=(
            "Three separate problems. First, the bare `except:` catches `BaseException`, "
            "including `KeyboardInterrupt` and `SystemExit` — you cannot Ctrl-C this loop and it "
            "will fight a graceful shutdown. Catch `Exception` at the widest, and ideally the "
            "specific errors `transform` can raise. Second, `pass` discards the exception "
            "entirely: when this batch silently returns 40 of 100 records, there is nothing in "
            "the logs to explain it. Log with the record identifier and the exception. Third, "
            "and most importantly, this is a *silent data-loss* design. Failed records vanish "
            "with no count, no metric and no way to reprocess them. I would collect failures "
            "into a separate list, emit a metric on the failure rate, and either raise if the "
            "rate exceeds a threshold or write them to a dead-letter store. "
            "The fourth thing I would raise in review is a question rather than a comment: is "
            "partial success even the right semantic here? If the batch is a unit of work "
            "downstream, returning 40 of 100 records may be worse than failing loudly."
        ),
        common_wrong_answer="Only noting that `except:` should be `except Exception:`.",
        rubric=[
            point(
                "Flags the bare except",
                "bare except",
                "baseexception",
                "keyboardinterrupt",
                weight=2.5,
            ),
            point("Flags the silent pass", "log", "silent", "swallow", "discard", weight=2.5),
            point(
                "Identifies silent data loss",
                "data loss",
                "dropped",
                "missing records",
                "lost",
                weight=3,
                dimension="production_awareness",
            ),
            point(
                "Proposes metrics or a dead-letter path",
                "metric",
                "dead letter",
                "count",
                "threshold",
                weight=2,
                dimension="production_awareness",
            ),
            point(
                "Questions partial-success semantics",
                "partial",
                "all or nothing",
                "semantics",
                "atomic",
                weight=2,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "What failure rate would make you fail the whole batch instead?",
            "How do you make the dropped records recoverable?",
        ],
        tags=["review", "errors"],
        par_seconds=300,
    ),
    QuestionSpec(
        slug="q-py-shallow-copy",
        kind=Q.MCQ,
        category=C,
        tier=T.UNDERSTAND,
        level=L.JUNIOR,
        prompt="What does this print?",
        context="""
import copy
original = {"tags": ["a", "b"], "n": 1}
shallow = copy.copy(original)
shallow["tags"].append("c")
shallow["n"] = 2
print(original)
""",
        concepts=["python-names-and-objects"],
        options=[
            opt(
                "a",
                "{'tags': ['a', 'b'], 'n': 1}",
                why="A shallow copy shares the nested list, so the append IS visible.",
            ),
            opt(
                "b",
                "{'tags': ['a', 'b', 'c'], 'n': 1}",
                correct=True,
                why="`copy.copy` copies the outer dict but the 'tags' value is the same list object, "
                "so append is shared. Rebinding 'n' only affects the copy's own key.",
            ),
            opt(
                "c",
                "{'tags': ['a', 'b', 'c'], 'n': 2}",
                why="Setting shallow['n'] changes only the copy's key.",
            ),
            opt("d", "{'tags': ['a', 'b'], 'n': 2}", why="Both halves of this are backwards."),
        ],
        expected_answer="{'tags': ['a', 'b', 'c'], 'n': 1}",
        ideal_senior_answer=(
            "A shallow copy duplicates the container but not what it contains: `shallow['tags']` "
            "*is* `original['tags']`, so mutating it is visible through both. Assigning "
            "`shallow['n']` rebinds a key in the copy only. `copy.deepcopy` would recurse, at "
            "the cost of copying everything — which is why deepcopy in a hot path is its own "
            "performance bug."
        ),
        common_wrong_answer="Assuming copy() is recursive.",
        rubric=[point("shallow vs deep", "shallow", "nested", "same object", weight=3)],
        followups=["When is deepcopy the wrong tool?", "How would you copy only one level deeper?"],
        tags=["fundamentals"],
        par_seconds=90,
    ),
]


# ═════════════════════════════════════════════════════════════════════════════
# MISSIONS
# ═════════════════════════════════════════════════════════════════════════════
MISSIONS = [
    MissionSpec(
        slug="m-python-onboarding",
        title="Day One at AI Forge Labs",
        kind="concept",
        category=C,
        building="python_academy",
        tier=T.UNDERSTAND,
        briefing="""
Welcome to AI Forge Labs.

Your first ticket is not glamorous: the ingest service has a de-duplication
function that takes 40 minutes on production data and 0.2 seconds on the test
fixtures. Before you touch it, your tech lead wants to know you understand *why*
that happens — not just how to make it stop.

This is how it works here. Fix the thing, then explain the thing.
""",
        objective="Diagnose and fix an O(n²) de-duplication, then justify the fix.",
        success_criteria=[
            "dedupe() passes all tests including the performance check",
            "You can state the complexity of both versions",
            "You can explain why the fixtures hid the problem",
        ],
        steps=[
            MissionStepSpec(
                step_type="question",
                title="Warm-up",
                question="q-py-list-membership-complexity",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Fix the de-duplication",
                challenge="py-dedupe-preserve-order",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Explain it to your tech lead",
                prompt=(
                    "In your own words: what was the complexity before and after, why did the "
                    "test suite pass, and what would you change so this class of bug is caught "
                    "next time?"
                ),
                config={
                    "pass_score": 5.0,
                    "rubric": [
                        point(
                            "Names both complexities",
                            "o(n^2)",
                            "o(n)",
                            "quadratic",
                            "linear",
                            weight=3,
                        ),
                        point(
                            "Explains the fixture blind spot",
                            "fixture",
                            "small",
                            "data size",
                            weight=2,
                        ),
                        point(
                            "Proposes a prevention",
                            "test",
                            "benchmark",
                            "realistic data",
                            "profil",
                            weight=2,
                        ),
                    ],
                    "concept_slugs": ["python-list-vs-tuple-vs-set-vs-dict"],
                },
            ),
            MissionStepSpec(step_type="journal", title="Engineering journal", required=False),
        ],
        concepts=["python-list-vs-tuple-vs-set-vs-dict", "python-comprehensions"],
        debrief="""
**What you actually learned**

The fix was one line. The valuable part is the diagnostic reflex: when code is
fast locally and slow in production and the *logic* is identical, suspect a
complexity difference that only data size reveals.

Three things to carry forward:

1. `in` against a list is O(n). Against a set or dict, O(1). Inside a loop that
   difference is the whole ballgame.
2. Test fixtures that are 1000x smaller than production hide an entire class of
   bug. Benchmarks with realistic cardinality are cheap insurance.
3. `dict.fromkeys()` de-duplicates *and* preserves order, because dicts have
   kept insertion order since Python 3.7.
""",
        estimated_minutes=18,
        par_seconds=1080,
    ),
    MissionSpec(
        slug="m-python-the-basket-incident",
        title="The Basket Incident",
        kind="debugging",
        category=C,
        building="python_academy",
        tier=T.DEBUG,
        briefing="""
🚨 **SEV-2 — 02:47**

Support has 31 tickets from customers seeing items they did not add. The cart
service has been up for three days without a deploy. The bug does not reproduce
on a fresh process.

Attached: the function, the error report, and the one log line that matters.
""",
        objective="Find the root cause of cross-customer state leakage and fix it.",
        success_criteria=[
            "add_item creates a fresh basket when none is supplied",
            "You can name the mechanism, not just the fix",
        ],
        artifacts={
            "logs": [
                "02:11:04 INFO  cart.add item=SKU-2201 basket_size=1 customer=c_8812",
                "02:11:39 INFO  cart.add item=SKU-9930 basket_size=2 customer=c_4471",
                "02:12:02 INFO  cart.add item=SKU-1180 basket_size=3 customer=c_9903",
                "02:12:55 INFO  cart.add item=SKU-7742 basket_size=4 customer=c_2218",
            ],
            "observation": (
                "basket_size increases monotonically across DIFFERENT customers. "
                "It resets to 1 only after a process restart."
            ),
            "deploy_history": "No deploys in 6 days. The last change touched the CSS.",
        },
        steps=[
            MissionStepSpec(
                step_type="challenge",
                title="Fix the leak",
                challenge="py-fix-mutable-default",
            ),
            MissionStepSpec(
                step_type="question",
                title="Prove you understand the mechanism",
                question="q-py-mutable-default-predict",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Write the postmortem",
                prompt=(
                    "Write the root-cause section of the postmortem. What happened, why did it "
                    "survive code review and testing, and what prevents a recurrence?"
                ),
                config={
                    "pass_score": 5.5,
                    "rubric": [
                        point(
                            "Root cause: default evaluated once",
                            "once",
                            "definition",
                            "def time",
                            "import",
                            weight=3,
                        ),
                        point(
                            "Explains the shared mutable object",
                            "shared",
                            "same list",
                            "same object",
                            weight=2.5,
                        ),
                        point(
                            "Why tests missed it",
                            "first call",
                            "fresh process",
                            "single call",
                            "test",
                            weight=2,
                            dimension="practical_experience",
                        ),
                        point(
                            "Prevention",
                            "lint",
                            "ruff",
                            "b006",
                            "review checklist",
                            "sentinel",
                            weight=2,
                            dimension="production_awareness",
                        ),
                    ],
                    "concept_slugs": ["python-mutable-defaults"],
                },
            ),
            MissionStepSpec(step_type="journal", title="Engineering journal", required=False),
        ],
        concepts=["python-mutable-defaults", "python-names-and-objects"],
        debrief="""
**Root cause**

`def add_item(item, basket=[])` creates the list once, when the module is
imported. Every call that omits `basket` mutates that one object. In a
long-running server, three days of requests accumulate in it.

**Why it survived review and CI**

The first call in any fresh process behaves correctly. Unit tests that call the
function once — or that run in a fresh process per test — never see it. This is
the signature of the bug class: *correct on the first call, wrong forever after*.

**Prevention**

Ruff's `B006` catches this statically. It costs nothing to enable and this
incident cost 31 tickets and a 3am page. That argument — "the lint rule is
cheaper than the incident" — is one you will make many times.
""",
        required_level=2,
        estimated_minutes=22,
        par_seconds=1320,
    ),
    MissionSpec(
        slug="m-python-boss-framework",
        title="BOSS: The Framework That Forgot Its Name",
        kind="boss",
        category=C,
        building="python_academy",
        tier=T.PRODUCTION,
        briefing="""
👹 **BOSS BATTLE**

The internal `forge-core` framework is on fire. Four separate teams have
reported that their FastAPI endpoints are validating the wrong request bodies,
tracebacks point at `wrapper` instead of real function names, and the retry
logic silently retries genuine bugs.

All three symptoms have the same root: whoever wrote the decorator layer did not
understand what a decorator actually does.

Rebuild it. Correctly. Then defend the architecture.
""",
        objective="Rebuild the decorator layer and defend whether it should exist at all.",
        success_criteria=[
            "The retry decorator preserves metadata and retries only transient errors",
            "You can explain what breaks without functools.wraps",
            "You take a defensible position on decorator-heavy architecture",
        ],
        artifacts={
            "symptoms": [
                "FastAPI builds request models from `(*args, **kwargs)` instead of the real signature",
                "Sentry groups every error under `wrapper`",
                "A TypeError in payment code is retried 5 times before surfacing",
            ],
            "stack_trace": (
                'File "forge_core/decorators.py", line 14, in wrapper\n'
                "    return fn(*args, **kwargs)\n"
                'File "forge_core/decorators.py", line 14, in wrapper\n'
                "    return fn(*args, **kwargs)\n"
                'File "forge_core/decorators.py", line 14, in wrapper\n'
                "    return fn(*args, **kwargs)\n"
                "TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'"
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="challenge",
                title="Rebuild the retry decorator",
                challenge="py-retry-decorator",
            ),
            MissionStepSpec(
                step_type="question",
                title="Metadata preservation",
                question="q-py-decorator-metadata",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Fix the handler factory",
                challenge="py-fix-late-binding-closure",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Defend the architecture",
                prompt=(
                    "`forge-core` applies four decorators to every endpoint: auth, tracing, "
                    "retry and caching. Debugging it is genuinely painful. Would you keep this "
                    "architecture? Argue the position you actually hold, and name what would "
                    "change your mind."
                ),
                config={
                    "pass_score": 6.0,
                    "rubric": [
                        point(
                            "Distinguishes stable cross-cutting concerns from business logic",
                            "cross-cutting",
                            "auth",
                            "tracing",
                            "business logic",
                            weight=3,
                        ),
                        point(
                            "Acknowledges the debugging cost honestly",
                            "traceback",
                            "stack",
                            "debug",
                            "indirection",
                            weight=2.5,
                        ),
                        point(
                            "Takes a position rather than hedging",
                            "i would",
                            "keep",
                            "remove",
                            "yes",
                            "no",
                            weight=2,
                        ),
                        point(
                            "Names what would change the decision",
                            "if",
                            "change my mind",
                            "depends",
                            "threshold",
                            weight=2.5,
                            dimension="tradeoff_awareness",
                        ),
                        point(
                            "Considers alternatives (middleware, explicit calls)",
                            "middleware",
                            "explicit",
                            "dependency",
                            "composition",
                            weight=2,
                            dimension="architecture_thinking",
                        ),
                    ],
                    "concept_slugs": ["python-decorators-basics", "python-closures"],
                },
            ),
            MissionStepSpec(step_type="journal", title="Engineering journal", required=False),
        ],
        concepts=["python-decorators-basics", "python-closures", "python-exceptions"],
        debrief="""
**What the boss was really testing**

Not "can you write a decorator" — that is tier 3. It was three tier-8 reflexes:

1. **`functools.wraps` is not cosmetic.** Frameworks dispatch on function
   metadata. FastAPI builds your request model from the signature. Losing it is
   a correctness bug that looks like a style nit.
2. **Catch narrowly.** `except Exception` inside a retry turns every bug into a
   slow bug with a confusing stack.
3. **Abstractions have a running cost.** Four decorators deep is four frames in
   every traceback and four places to look when behaviour surprises you. That
   cost is worth paying for auth and tracing — stable, universal, boring. It is
   rarely worth paying for anything that encodes business rules.

The last step had no right answer. It had defensible and indefensible ones, and
the difference was whether you named the condition under which you would decide
differently.
""",
        required_level=6,
        requires_missions=["m-python-the-basket-incident"],
        estimated_minutes=40,
        par_seconds=2400,
        xp_multiplier=1.5,
        is_boss=True,
    ),
]


PACK = ContentPack(
    name="python_core",
    concepts=CONCEPTS,
    challenges=CHALLENGES,
    questions=QUESTIONS,
    missions=MISSIONS,
)
