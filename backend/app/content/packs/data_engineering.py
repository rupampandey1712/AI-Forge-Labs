"""The Data Foundry — NumPy, pandas and the habits that survive production.

AUTHORING STANDARD (inherited from ``python_core``, restated because it is what
makes this content worth doing at all):

* Concepts explain the *mechanism*. "pandas is fast" is marketing. "pandas is
  fast when the operation stays in C and catastrophically slow the moment you
  iterate rows in Python, because every row materialises a Series object" is a
  concept you can act on.
* Every challenge has hidden tests, and the performance challenges assert an
  actual wall-clock bound — a vectorisation lesson graded only on correctness
  teaches nothing, because the slow answer passes.
* Questions carry the *common wrong answer*, because the wrong answer is the
  thing the player is most likely to already believe.

WHY THIS PACK EXISTS BEFORE THE ML PACK: almost every "the model is broken"
incident is really a data incident — a leaked feature, a silent dtype coercion,
a join that multiplied rows. Debugging those requires knowing what pandas
actually did, not what you meant.
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

NP = Category.NUMPY
PD = Category.PANDAS
ML = Category.ML

# ═════════════════════════════════════════════════════════════════════════════
# CONCEPTS
# ═════════════════════════════════════════════════════════════════════════════
CONCEPTS = [
    ConceptSpec(
        slug="numpy-ndarray-memory-model",
        title="The ndarray Memory Model",
        category=NP,
        skill_node="numpy.arrays",
        difficulty=3,
        summary=(
            "An ndarray is one contiguous block of same-typed bytes plus a shape and strides. "
            "Nearly every NumPy surprise follows from that sentence."
        ),
        explanation="""
A Python list of a million integers is a million pointers to a million separate
`PyObject`s, each with a refcount, a type pointer and a value. An ndarray of a
million `int64`s is **eight megabytes of nothing but numbers**.

That single difference explains most of NumPy:

**Why it is fast.** The loop runs in C over contiguous memory, one cache line
feeding the next, with no per-element type check and no pointer chase. There is
no interpreter in the inner loop at all.

**Why the dtype is fixed.** The block is homogeneous, so every element occupies
the same number of bytes and `data + i * itemsize` finds element `i` in constant
time with no indirection. Put a string in an int array and NumPy must either
reject it or upcast the *entire* array.

**Why slicing is free.** `a[::2]` allocates no data. It creates a new view onto
the same buffer with a doubled stride. This is why modifying a slice modifies
the original — a fact that produces silent, hard-to-trace bugs when a function
"defensively" slices its input and then writes to it.

**Strides** are the whole trick. A `(3, 4)` int64 array has strides `(32, 8)`:
move 32 bytes for the next row, 8 for the next column. Transposing does not move
a single byte — it swaps the strides to `(8, 32)`. That is why `a.T` is instant
and why `a.T` is not C-contiguous, which in turn is why some later operation
silently copies.
""",
        examples=[
            example(
                "A slice is a view, not a copy",
                """
import numpy as np
a = np.arange(6)
view = a[::2]
view[0] = 999
print(a)            # the ORIGINAL changed
print(view.base is a)
""",
                output="[999   1   2   3   4   5]\nTrue",
                note="`.base` is not None means you are holding a view. Check it when debugging.",
            ),
            example(
                "Transpose only swaps strides",
                """
import numpy as np
a = np.zeros((3, 4))
print(a.strides, a.T.strides)
print(a.flags['C_CONTIGUOUS'], a.T.flags['C_CONTIGUOUS'])
""",
                output="(32, 8) (8, 32)\nTrue False",
            ),
        ],
        common_mistakes=[
            mistake(
                "Assuming a slice is a copy and mutating it",
                "Slices are views. Writing to one writes through to the parent array, so a "
                "function that 'works on its own copy' silently corrupts its caller's data.",
                "Call `.copy()` explicitly when you intend a copy. Assert `arr.base is None` "
                "in the rare places where ownership genuinely matters.",
                Severity.HIGH,
            ),
            mistake(
                "Growing an array with np.append in a loop",
                "`np.append` allocates a whole new array and copies every existing element, so "
                "the loop is O(n²) in both time and allocator pressure.",
                "Collect into a Python list and call `np.array(rows)` once, or preallocate with "
                "`np.empty(n)` when the size is known.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Diagnosing a 40x slowdown that turned out to be an accidental dtype=object array",
            "Explaining in review why a 'defensive' slice did not defend anything",
        ],
        related=["numpy-broadcasting-rules", "numpy-vectorization"],
        tags=["numpy", "memory", "performance"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="numpy-broadcasting-rules",
        title="Broadcasting",
        category=NP,
        skill_node="numpy.broadcasting",
        difficulty=4,
        summary=(
            "Broadcasting stretches shapes without copying data — and it is also the most "
            "common source of an array that is accidentally 1000x larger than intended."
        ),
        explanation="""
The rule is short. Align shapes **from the right**, then for each dimension:

* equal sizes → fine
* one of them is 1 → that one is stretched (by repeating a stride-0 view, so no
  memory is allocated)
* neither → `ValueError`

    (3, 4) and    (4,)  ->  (3, 4)      the (4,) is reused for every row
    (3, 4) and (3, 1)   ->  (3, 4)      the column is reused across columns
    (3, 4) and (3,)     ->  ERROR       4 and 3 do not align

**The trap, and it is a serious one.** `(1000, 1)` against `(1000,)` broadcasts
to `(1000, 1000)`. That is a million floats — 8MB — from two arrays that were 8KB
each. No error is raised because nothing is wrong by the rules; you simply asked
for an outer product when you meant an element-wise subtraction. In a training
loop this shows up as an out-of-memory kill, and the traceback points at a line
that looks innocent.

The fix is a habit, not a trick: when two arrays *should* be the same shape,
assert it. `assert a.shape == b.shape` costs nothing and turns a silent 8MB
allocation into an immediate, located failure.
""",
        examples=[
            example(
                "The accidental outer product",
                """
import numpy as np
predictions = np.zeros((1000, 1))   # a column, e.g. from a model
targets = np.zeros(1000)            # a flat vector
print((predictions - targets).shape)   # NOT (1000, 1)
""",
                output="(1000, 1000)",
                note="One million elements. The loss computed from this is meaningless.",
            ),
            example(
                "Centring rows vs columns",
                """
import numpy as np
x = np.arange(12, dtype=float).reshape(3, 4)
print(x - x.mean(axis=0))            # per-column mean, shape (4,)
print(x - x.mean(axis=1, keepdims=True))  # per-row mean, needs keepdims
""",
                note="Without keepdims the (3,) row-means align to the columns and centre the "
                "wrong axis — silently, because 3 != 4 would error but 3 == 3 would not.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Forgetting keepdims=True when reducing along an axis",
                "The reduced array loses the dimension, so it broadcasts against the wrong axis "
                "— or errors confusingly when the sizes happen not to match.",
                "Use `keepdims=True` whenever the result will be broadcast back against the "
                "original array.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Normalising a feature matrix per-column without a loop",
            "Finding the OOM in a training loop that was really an unintended (N, N) array",
        ],
        requires=["numpy-ndarray-memory-model"],
        related=["numpy-vectorization"],
        tags=["numpy", "broadcasting"],
        estimated_minutes=8,
    ),
    ConceptSpec(
        slug="numpy-vectorization",
        title="Vectorisation, and When It Is Not the Answer",
        category=NP,
        skill_node="numpy.vectorization",
        difficulty=5,
        summary=(
            "Vectorising moves the loop from Python into C. It usually wins by 50–100x — and "
            "sometimes it loses, which is the part nobody teaches."
        ),
        explanation="""
A Python-level loop over an array pays, per element: a bounds check, a
`PyObject` box for the scalar, a dynamic dispatch on `+`, a refcount increment
and decrement. Vectorised, that per-element overhead disappears entirely and the
work becomes a tight C loop, often SIMD-widened.

**The honest caveats**, because "always vectorise" is advice that will eventually
cost you:

1. **`np.vectorize` is not vectorisation.** It is a for-loop with a NumPy-shaped
   API. The docs say so. It is for convenience, never for speed.
2. **Vectorising materialises intermediates.** `(a * b + c) ** 2` on a 100M-element
   array allocates three temporary 800MB arrays. The loop version allocates
   nothing. At that size, chunking or `numexpr` beats both.
3. **You cannot vectorise a genuinely sequential dependency.** If element `i`
   depends on element `i-1`, you need `np.cumsum`-style primitives, an algorithm
   change, or a compiled kernel. Contorting it into array operations produces
   code that is slower *and* unreadable.
4. **Boolean masking copies.** `a[a > 0] = 0` builds a full boolean array and
   then a copy. For a sparse condition, that can be worse than the obvious loop.

The rule that actually holds: **measure**. A 5-line benchmark settles in ten
seconds an argument that a code review will otherwise run for three days.
""",
        examples=[
            example(
                "The 60x that motivates the habit",
                """
import numpy as np, time
a = np.random.rand(2_000_000)

t = time.perf_counter()
slow = [x * 2 + 1 for x in a]
py = time.perf_counter() - t

t = time.perf_counter()
fast = a * 2 + 1
np_time = time.perf_counter() - t
print(f"python {py:.3f}s  numpy {np_time:.4f}s  speedup {py / np_time:.0f}x")
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Reaching for np.vectorize to make something fast",
                "It is documented as a convenience wrapper around a Python loop. It provides no "
                "speed-up and creates the false impression the code has been optimised.",
                "Express the operation with real array primitives, or accept the loop and say "
                "so in a comment.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Turning a 40-minute nightly feature job into a 20-second one",
            "Arguing in review that a particular loop should stay a loop",
        ],
        requires=["numpy-broadcasting-rules"],
        tags=["numpy", "performance"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="pandas-copy-vs-view",
        title="Copies, Views and SettingWithCopyWarning",
        category=PD,
        skill_node="pandas.basics",
        difficulty=5,
        summary=(
            "The warning everybody silences is pandas telling you your write may have gone "
            "nowhere. It is right often enough to be worth reading."
        ),
        explanation="""
`SettingWithCopyWarning` is the most-ignored warning in data work, and the
reason it is ignored is that it fires on code that *sometimes* works.

Here is the actual mechanism. Indexing a DataFrame may return a **view** (sharing
the parent's memory) or a **copy** (independent). Which one you get depends on
the dtypes and the memory layout, and it is not something you can reliably
predict from reading the expression. So:

    subset = df[df.score > 0.5]    # probably a copy
    subset['flag'] = True          # writes to the copy — df is unchanged

Chained indexing is the same trap with a shorter fuse:

    df[df.score > 0.5]['flag'] = True   # writes to a temporary, then discards it

Nothing errors. The warning is the only signal, and the data is silently wrong
downstream. The fix is always the same: **one indexing operation**, via `.loc`:

    df.loc[df.score > 0.5, 'flag'] = True

And when you genuinely want a separate object, say so: `subset = df[mask].copy()`.

**Note on pandas 3.0:** Copy-on-Write is now the default, which makes this far
more predictable — every indexing result behaves as a copy, and the warning
largely disappears. The reasoning above still matters, both because you will
maintain code written before it and because the `.loc` habit is correct
regardless.
""",
        examples=[
            example(
                "The write that goes nowhere",
                """
import pandas as pd
df = pd.DataFrame({"score": [0.2, 0.9], "flag": [False, False]})

high = df[df.score > 0.5]
high["flag"] = True        # may warn; may not affect df

print(df.flag.tolist())    # often still [False, False]

df.loc[df.score > 0.5, "flag"] = True   # always correct
print(df.flag.tolist())
""",
                output="[False, False]\n[False, True]",
            ),
        ],
        common_mistakes=[
            mistake(
                "Suppressing the warning instead of reading it",
                "`pd.options.mode.chained_assignment = None` hides the one signal that your "
                "update did not land. The bug then surfaces as wrong numbers, far from here.",
                "Rewrite as a single `.loc` assignment. If you truly want an independent "
                "object, take an explicit `.copy()`.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Tracking down why a cleaning step 'ran' but the column never changed",
        ],
        related=["pandas-groupby-mechanics"],
        tags=["pandas", "correctness"],
        estimated_minutes=8,
    ),
    ConceptSpec(
        slug="pandas-groupby-mechanics",
        title="Split-Apply-Combine",
        category=PD,
        skill_node="pandas.groupby",
        difficulty=4,
        summary=(
            "groupby is three operations. Knowing which one you are in tells you why your "
            "result has the wrong shape — and why `.apply` is so much slower than `.agg`."
        ),
        explanation="""
`groupby` splits rows into groups, applies something to each, and combines the
results. The confusion is almost always about *what* gets applied and *what
shape* comes back.

**`.agg`** — many rows in, one row out per group. Runs in C for the built-in
reducers (`sum`, `mean`, `count`, `max`). Result is indexed by group.

**`.transform`** — many rows in, the *same number* of rows out, aligned to the
original index. This is the one people miss, and it is the right tool whenever
you want a group statistic attached back to each row:

    df["pct_of_group"] = df.amount / df.groupby("region").amount.transform("sum")

Doing that with `.agg` forces a merge; `.transform` aligns automatically.

**`.filter`** — keeps or drops whole groups by a predicate on the group.

**`.apply`** is the escape hatch, and it is slow for a specific reason: it calls
a Python function once per group, materialising a full sub-DataFrame each time.
For 100,000 groups that is 100,000 DataFrame constructions. Where a built-in
aggregation exists, it is typically 10–100x faster. Reach for `.apply` when the
operation genuinely does not decompose — and then say so in a comment, so the
next reader does not "optimise" it back into something incorrect.

**observed=True.** With categorical keys, pandas defaults to emitting *every*
category combination, including empty ones. Group by three categoricals with 50
levels each and you get 125,000 rows out of a 200-row frame.
""",
        examples=[
            example(
                "transform is the one you keep forgetting",
                """
import pandas as pd
df = pd.DataFrame({"region": ["a", "a", "b"], "amount": [10.0, 30.0, 5.0]})

df["share"] = df.amount / df.groupby("region").amount.transform("sum")
print(df)
""",
                output="  region  amount  share\n0      a    10.0   0.25\n1      a    30.0   0.75\n2      b     5.0   1.00",
            ),
        ],
        common_mistakes=[
            mistake(
                "Using .apply where .agg or .transform would do",
                "`.apply` runs a Python callable per group and builds a sub-DataFrame each "
                "time. On many small groups this dominates the runtime completely.",
                "Use named aggregations for reductions and `.transform` for per-row group "
                "statistics. Keep `.apply` for genuinely irreducible logic.",
                Severity.MEDIUM,
            ),
            mistake(
                "Grouping on categoricals without observed=True",
                "pandas emits the full cartesian product of categories, most of them empty, "
                "which can turn a small frame into millions of rows.",
                "Pass `observed=True` whenever the keys are categorical.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Per-customer share of revenue without a self-join",
            "Explaining why a nightly aggregation suddenly emitted 40 million rows",
        ],
        related=["pandas-copy-vs-view", "pandas-join-cardinality"],
        tags=["pandas", "aggregation"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="pandas-join-cardinality",
        title="Join Cardinality — Where Row Counts Explode",
        category=PD,
        skill_node="pandas.joins",
        difficulty=6,
        summary=(
            "A merge that duplicates rows produces no error and no warning. It produces wrong "
            "numbers, and it is the single most common silent data bug."
        ),
        explanation="""
You merge orders with customers and your revenue total doubles. Nothing failed.
What happened is that the right-hand frame had two rows per key — a duplicate
customer record, or a slowly-changing dimension with two validity rows — so
every order matched twice and every amount got counted twice.

The defence is one argument that almost nobody uses:

    orders.merge(customers, on="customer_id", how="left", validate="many_to_one")

`validate` raises immediately if the cardinality is not what you claimed. It
turns a silent doubling into a loud failure at the exact line responsible, which
is the entire difference between a ten-minute fix and a week of "the dashboard
looks off".

Also worth stating plainly:

* **`indicator=True`** adds a `_merge` column so you can count how many rows
  matched, left-only, right-only. A left join that matches 60% of rows is
  usually a bug in the key, not a fact about the data.
* **Check row counts across the join.** `assert len(result) == len(orders)` for
  a many-to-one left join is a one-line invariant that catches the whole class.
* **Key dtype mismatches silently produce zero matches.** `int64` against
  `object` (string) matches nothing, and a left join happily returns all-NaN
  columns. Nothing warns.
""",
        examples=[
            example(
                "validate turns silence into a failure",
                """
import pandas as pd
orders = pd.DataFrame({"customer_id": [1, 2], "amount": [10.0, 20.0]})
customers = pd.DataFrame({"customer_id": [1, 1, 2], "tier": ["a", "b", "c"]})

bad = orders.merge(customers, on="customer_id", how="left")
print(len(bad), bad.amount.sum())   # 3 rows, 40.0 - revenue inflated

try:
    orders.merge(customers, on="customer_id", how="left", validate="many_to_one")
except Exception as exc:
    print(type(exc).__name__, exc)
""",
                output="3 40.0\nMergeError Merge keys are not unique in right dataset; not a many-to-one merge",
            ),
        ],
        common_mistakes=[
            mistake(
                "Merging without asserting cardinality",
                "Duplicate keys on either side silently multiply rows, inflating every "
                "downstream sum, mean and count with no error anywhere.",
                "Pass `validate=` on every merge. It costs one argument and catches an entire "
                "class of silent corruption.",
                Severity.CRITICAL,
            ),
            mistake(
                "Joining columns with mismatched dtypes",
                "int64 keys never match string keys. The join returns all-NaN and looks like "
                "missing data rather than a bug.",
                "Normalise key dtypes before merging, and check the match rate with "
                "`indicator=True`.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Root-causing a revenue dashboard that reported 2.4x actual",
            "Reviewing an ETL PR and asking 'what is the cardinality of this join?'",
        ],
        requires=["pandas-groupby-mechanics"],
        tags=["pandas", "joins", "correctness"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="pandas-dtypes-and-memory",
        title="Dtypes, object Columns and Silent Coercion",
        category=PD,
        skill_node="pandas.cleaning",
        difficulty=5,
        summary=(
            "An object-dtype column is a column of Python pointers. It is usually 10x the "
            "memory and 50x the runtime of the typed column it should have been."
        ),
        explanation="""
`object` is pandas' way of saying "I gave up and stored pointers to Python
objects". Every operation on such a column falls back to a Python-level loop.
A `category` or a proper numeric dtype is both smaller and dramatically faster.

**How columns become `object` without you noticing:**

* One malformed value in a CSV — a `"N/A"` in a numeric column — and the whole
  column is parsed as strings.
* Mixed types from a JSON source.
* Any string column at all, unless you convert it to `category` or `string`.

**Silent coercion is the sharper edge.** Historically, an integer column that
acquires a single NaN becomes `float64`, because NumPy integers cannot represent
NaN. IDs then become `1.0`, `2.0`, and once past 2^53 they lose precision
outright — user IDs that silently collide. The nullable `Int64` dtype (capital I)
exists specifically for this and should be the default for any ID column.

**Checking is cheap:**

    df.info(memory_usage="deep")     # real memory, following object pointers
    df.dtypes                        # the two-second check nobody runs

Converting a low-cardinality string column to `category` routinely cuts memory
by 90%, because it stores small integer codes plus one copy of each distinct
value instead of one Python string object per row.
""",
        examples=[
            example(
                "One NaN turns integers into floats",
                """
import pandas as pd, numpy as np
ids = pd.Series([1, 2, 3])
print(ids.dtype)
with_gap = pd.Series([1, 2, np.nan])
print(with_gap.dtype, with_gap.tolist())

nullable = pd.Series([1, 2, None], dtype="Int64")
print(nullable.dtype, nullable.tolist())
""",
                output="int64\nfloat64 [1.0, 2.0, nan]\nInt64 [1, 2, <NA>]",
            ),
        ],
        common_mistakes=[
            mistake(
                "Leaving ID columns as float after a join introduces NaN",
                "Floats above 2^53 cannot represent consecutive integers, so large IDs collide "
                "and rows get attributed to the wrong entity.",
                "Use the nullable `Int64` dtype for IDs, and assert the dtype after every "
                "join that can introduce missing values.",
                Severity.CRITICAL,
            ),
        ],
        real_world_usage=[
            "Cutting a 12GB frame to 1.4GB before a job that kept getting OOM-killed",
        ],
        related=["pandas-copy-vs-view"],
        tags=["pandas", "dtypes", "memory"],
        estimated_minutes=8,
    ),
    ConceptSpec(
        slug="data-leakage",
        title="Data Leakage",
        category=ML,
        skill_node="ml.evaluation",
        difficulty=7,
        summary=(
            "Leakage is when information from outside the training window reaches the model. "
            "It looks exactly like success, right up until production."
        ),
        explanation="""
A model scoring 0.99 AUC is not good news. It is a hypothesis, and the first
thing to test is leakage.

**The four forms that account for nearly all of it:**

1. **Target leakage.** A feature that is a consequence of the label, not a
   predictor of it. `days_since_account_closed` predicts churn perfectly because
   it only exists *after* churn. The classic version is subtler: an
   `updated_at` timestamp that gets touched when the outcome is recorded.

2. **Train/test contamination.** Fitting the scaler, imputer or encoder on the
   full dataset before splitting. The test set's mean has now informed the
   training transform. The fix is a `Pipeline`, so `fit` can only ever see the
   training fold.

3. **Temporal leakage.** Random splits on time-series data let the model train
   on Thursday and predict Wednesday. Any production model predicts forward
   only, so evaluation must too — split by time, always.

4. **Group leakage.** The same user appearing in both splits. The model learns
   that user, not the pattern. Split on the group key, not the row.

**The diagnostic question**, and it is the one to ask in an interview and in a
review: *at the moment of prediction in production, would this value be known?*
If the answer is "no" or "only after the event we are predicting", it is
leakage. Nothing about the metric will tell you — leakage always improves the
metric. That is what makes it dangerous.
""",
        examples=[
            example(
                "Contaminated scaling vs a pipeline",
                """
# WRONG - the scaler has seen the test set's distribution
scaler.fit(X_all)
X_train, X_test = split(scaler.transform(X_all))

# RIGHT - fit happens inside cross-validation, per fold
pipe = Pipeline([("scale", StandardScaler()), ("model", LogisticRegression())])
cross_val_score(pipe, X, y, cv=TimeSeriesSplit(5))
""",
                note="The pipeline is not style. It is what makes the leak structurally "
                "impossible rather than merely unintended.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Random train/test split on time-ordered data",
                "The model trains on the future and is evaluated on the past, which no "
                "production deployment can ever do. The offline metric is unachievable.",
                "Split by time. Use `TimeSeriesSplit` for cross-validation.",
                Severity.CRITICAL,
            ),
            mistake(
                "Celebrating a suspiciously high score",
                "A large jump in a metric is far more often leakage than insight, and every "
                "hour spent not checking is an hour of building on sand.",
                "Treat any unexpected jump as a leakage hypothesis first. Ablate the "
                "strongest feature and see whether the score collapses.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Explaining why a 0.99 AUC model scored 0.61 in its first production week",
            "The most common senior-level ML interview question there is",
        ],
        related=["pandas-join-cardinality"],
        tags=["ml", "evaluation", "leakage"],
        estimated_minutes=11,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# CHALLENGES
# ═════════════════════════════════════════════════════════════════════════════
CHALLENGES = [
    ChallengeSpec(
        slug="np-normalise-features",
        title="Per-Column Normalisation Without a Loop",
        category=NP,
        tier=T.IMPLEMENT,
        prompt="""
Implement `normalise(x)` for a 2-D array of shape `(n_samples, n_features)`.
Return a new array where **each column** has mean 0 and standard deviation 1.

Two things the naive version gets wrong:

* A constant column has std 0. Dividing by it yields `nan`, which then poisons
  every downstream computation. Leave such columns as zeros.
* The input must not be modified. Callers rely on that.
""",
        starter_code="import numpy as np\n\n\ndef normalise(x):\n    ...\n",
        reference_solution="""
import numpy as np


def normalise(x):
    x = np.asarray(x, dtype=float)
    mean = x.mean(axis=0, keepdims=True)
    std = x.std(axis=0, keepdims=True)
    # A zero std means a constant column: centring already made it all zeros,
    # so dividing by 1 leaves it at zero instead of producing nan.
    safe = np.where(std == 0, 1.0, std)
    return (x - mean) / safe
""",
        solution_explanation=(
            "`keepdims=True` is what makes the (n_features,) statistics broadcast back against "
            "the (n_samples, n_features) input along the right axis. `np.where` replaces the "
            "zero divisors before the division rather than cleaning up nan afterwards — once "
            "nan exists it propagates through every subsequent operation."
        ),
        tests=[
            script(
                "columns end up standardised",
                """
import numpy as np
x = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]])
out = normalise(x)
assert np.allclose(out.mean(axis=0), 0), out.mean(axis=0)
assert np.allclose(out.std(axis=0), 1), out.std(axis=0)
""",
            ),
            script(
                "a constant column becomes zeros, not nan",
                """
import numpy as np
x = np.array([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]])
out = normalise(x)
assert not np.isnan(out).any(), "nan leaked from a zero-variance column"
assert np.allclose(out[:, 0], 0.0)
""",
                points=2.0,
            ),
            script(
                "the input is not modified",
                """
import numpy as np
x = np.array([[1.0, 2.0], [3.0, 4.0]])
before = x.copy()
normalise(x)
assert np.array_equal(x, before), "normalise mutated its input"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "normalises columns, not rows",
                """
import numpy as np
# Distinct per-column scales: a row-wise implementation gets this wrong.
x = np.array([[0.0, 100.0], [2.0, 300.0], [4.0, 500.0]])
out = normalise(x)
assert abs(out[:, 0].mean()) < 1e-9 and abs(out[:, 1].mean()) < 1e-9
assert abs(out[0, 0] - out[0, 1]) < 1e-9, "columns should standardise identically here"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "works on a single row without dividing by zero",
                """
import numpy as np
out = normalise(np.array([[1.0, 2.0]]))
assert not np.isnan(out).any()
""",
                hidden=True,
            ),
        ],
        concepts=["numpy-broadcasting-rules", "numpy-vectorization"],
        hints=[
            "What shape does `x.mean(axis=0)` return, and does it broadcast back correctly?",
            "What is the standard deviation of a column where every value is the same?",
            "Replace the zero divisors *before* dividing — nan is much harder to remove after.",
        ],
        explanation_prompts=[
            point("Explains why keepdims matters", "keepdims", "broadcast", "axis", weight=2),
            point(
                "Handles the zero-variance column", "zero", "constant", "divide", "nan", weight=2
            ),
            point("Notes the input is not mutated", "copy", "mutate", "in-place", weight=1),
        ],
        expected_complexity="O(n * f)",
        par_seconds=420,
    ),
    ChallengeSpec(
        slug="np-vectorise-distance",
        title="Pairwise Distances, 100x Faster",
        category=NP,
        tier=T.OPTIMIZE,
        prompt="""
`pairwise_distances(a, b)` returns the matrix of Euclidean distances between
every row of `a` (shape `(n, d)`) and every row of `b` (shape `(m, d)`), giving
shape `(n, m)`.

The version below is correct and unusably slow. Make it **at least 25x faster**
without changing the result.

This is the inner loop of every k-NN, every clustering step and every brute-force
vector search, so the difference is not academic.
""",
        baseline_code="""
import numpy as np


def pairwise_distances(a, b):
    out = np.empty((len(a), len(b)))
    for i in range(len(a)):
        for j in range(len(b)):
            out[i, j] = np.sqrt(((a[i] - b[j]) ** 2).sum())
    return out
""",
        starter_code=(
            "import numpy as np\n\n\ndef pairwise_distances(a, b):\n"
            "    # Hint: think about what shapes broadcast to (n, m, d).\n    ...\n"
        ),
        reference_solution="""
import numpy as np


def pairwise_distances(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    # (n, 1, d) against (1, m, d) broadcasts to (n, m, d): every pair, no loop.
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt((diff ** 2).sum(axis=-1))
""",
        solution_explanation=(
            "Inserting length-1 axes makes broadcasting enumerate every (i, j) pair inside C. "
            "The cost is memory: the intermediate is n*m*d floats, so for large inputs the "
            "expansion `|a|² + |b|² - 2ab` is preferred — it never materialises the (n, m, d) "
            "array, at the price of some floating-point accuracy near zero."
        ),
        target_speedup=25.0,
        tests=[
            script(
                "matches the naive result",
                """
import numpy as np
rng = np.random.default_rng(0)
a, b = rng.random((7, 3)), rng.random((5, 3))
expected = np.empty((7, 5))
for i in range(7):
    for j in range(5):
        expected[i, j] = np.sqrt(((a[i] - b[j]) ** 2).sum())
assert np.allclose(pairwise_distances(a, b), expected)
""",
                points=2.0,
            ),
            script(
                "shape is (n, m)",
                """
import numpy as np
assert pairwise_distances(np.zeros((4, 2)), np.zeros((9, 2))).shape == (4, 9)
""",
            ),
            script(
                "distance from a point to itself is zero",
                """
import numpy as np
a = np.array([[1.0, 2.0], [3.0, 4.0]])
d = pairwise_distances(a, a)
assert np.allclose(np.diag(d), 0.0)
""",
                hidden=True,
            ),
            script(
                "fast enough to be genuinely vectorised",
                """
import numpy as np, time
rng = np.random.default_rng(1)
a, b = rng.random((400, 16)), rng.random((400, 16))
start = time.perf_counter()
out = pairwise_distances(a, b)
elapsed = time.perf_counter() - start
assert out.shape == (400, 400)
assert elapsed < 0.35, f"took {elapsed:.3f}s - still looping in Python"
""",
                hidden=True,
                points=3.0,
            ),
        ],
        concepts=["numpy-broadcasting-rules", "numpy-vectorization"],
        hints=[
            "You want every (i, j) pair. What shapes broadcast together to give (n, m, d)?",
            "`a[:, None, :]` has shape (n, 1, d). What does that broadcast against?",
            "After subtracting, you have an (n, m, d) array. Sum over which axis?",
        ],
        explanation_prompts=[
            point("Explains the broadcast to (n, m, d)", "broadcast", "none", "newaxis", weight=2),
            point(
                "Mentions the memory cost of the intermediate",
                "memory",
                "intermediate",
                "n*m*d",
                "allocat",
                weight=2,
            ),
            point(
                "Knows the expansion trick for large inputs",
                "expansion",
                "dot",
                "matmul",
                "squared norm",
                weight=1.5,
            ),
        ],
        expected_complexity="O(n * m * d)",
        par_seconds=480,
    ),
    ChallengeSpec(
        slug="pd-safe-merge",
        title="The Merge That Refuses to Corrupt Your Totals",
        category=PD,
        tier=T.DEBUG,
        prompt="""
This function is used across the reporting pipeline. Finance reports that
revenue totals are roughly double what the source system says.

The code runs without error. Find the bug and fix it so that:

* a duplicate key in `customers` raises immediately rather than silently
  multiplying rows,
* the row count of the result equals the row count of `orders`,
* orders with no matching customer are **kept** (they are still revenue).
""",
        broken_code="""
import pandas as pd


def enrich_orders(orders, customers):
    return orders.merge(customers, on="customer_id", how="inner")
""",
        starter_code="",
        reference_solution="""
import pandas as pd


def enrich_orders(orders, customers):
    # `validate` turns a silent row multiplication into a loud failure at the
    # line responsible. Without it, a duplicate customer row doubles revenue
    # and nothing anywhere reports a problem.
    #
    # `how="left"` keeps orders that have no customer record: an unmatched
    # order is still revenue, and dropping it quietly understates the total
    # in exactly the way that is hardest to notice.
    return orders.merge(
        customers,
        on="customer_id",
        how="left",
        validate="many_to_one",
    )
""",
        solution_explanation=(
            "Two bugs, both silent. `how='inner'` drops orders whose customer is missing, "
            "understating revenue. And with no `validate`, duplicate customer rows multiply "
            "every matching order — which is what doubled the totals. `validate='many_to_one'` "
            "makes the assumption explicit and enforces it."
        ),
        tests=[
            script(
                "duplicate customer keys raise instead of doubling revenue",
                """
import pandas as pd
orders = pd.DataFrame({"customer_id": [1, 2], "amount": [10.0, 20.0]})
dupes = pd.DataFrame({"customer_id": [1, 1, 2], "tier": ["a", "b", "c"]})
try:
    enrich_orders(orders, dupes)
except Exception:
    pass
else:
    raise AssertionError("duplicate keys silently multiplied rows")
""",
                points=3.0,
            ),
            script(
                "row count is preserved",
                """
import pandas as pd
orders = pd.DataFrame({"customer_id": [1, 2, 3], "amount": [1.0, 2.0, 3.0]})
customers = pd.DataFrame({"customer_id": [1, 2, 3], "tier": ["a", "b", "c"]})
assert len(enrich_orders(orders, customers)) == 3
""",
            ),
            script(
                "unmatched orders are kept, not dropped",
                """
import pandas as pd
orders = pd.DataFrame({"customer_id": [1, 99], "amount": [10.0, 5.0]})
customers = pd.DataFrame({"customer_id": [1], "tier": ["a"]})
out = enrich_orders(orders, customers)
assert len(out) == 2, "an order with no customer record was dropped"
assert out.amount.sum() == 15.0, "revenue was understated"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "the enrichment column is actually present",
                """
import pandas as pd
orders = pd.DataFrame({"customer_id": [1], "amount": [10.0]})
customers = pd.DataFrame({"customer_id": [1], "tier": ["gold"]})
assert enrich_orders(orders, customers).tier.iloc[0] == "gold"
""",
                hidden=True,
            ),
        ],
        concepts=["pandas-join-cardinality"],
        hints=[
            "The totals are doubled. What does a merge do when the right side has two rows per key?",
            "pandas has an argument that asserts the cardinality of a join. What is it?",
            "Separately: what happens to an order whose customer_id is not in `customers`?",
        ],
        explanation_prompts=[
            point(
                "Identifies the duplicate-key row multiplication",
                "duplicate",
                "cardinality",
                "multipl",
                weight=3,
            ),
            point("Uses validate=", "validate", "many_to_one", weight=2),
            point("Notices inner join drops unmatched orders", "inner", "left", "drop", weight=2),
        ],
        par_seconds=420,
    ),
    ChallengeSpec(
        slug="pd-groupby-share",
        title="Group Share Without a Merge",
        category=PD,
        tier=T.IMPLEMENT,
        prompt="""
Given a DataFrame with `region` and `amount`, add a column `share` holding each
row's fraction of its own region's total.

Do it **without** a merge, a join, or an `.apply`. There is a groupby method
that returns a result aligned to the original index — find it.

Regions whose total is zero should get a share of 0, not `nan`.
""",
        starter_code="import pandas as pd\n\n\ndef add_share(df):\n    ...\n",
        reference_solution="""
import pandas as pd


def add_share(df):
    out = df.copy()
    # `transform` returns one value per ROW (the group's total, repeated),
    # already aligned to the original index. `agg` would return one row per
    # group and force a merge to get back here.
    totals = out.groupby("region")["amount"].transform("sum")
    out["share"] = (out["amount"] / totals).fillna(0.0)
    out.loc[totals == 0, "share"] = 0.0
    return out
""",
        solution_explanation=(
            "`transform` is the split-apply-combine variant that returns the original number "
            "of rows, index-aligned — which is exactly what 'attach a group statistic to each "
            "row' needs. `agg` collapses to one row per group and then requires a merge, which "
            "is both slower and an opportunity to get the cardinality wrong."
        ),
        tests=[
            script(
                "shares sum to 1 within each region",
                """
import pandas as pd
df = pd.DataFrame({"region": ["a", "a", "b"], "amount": [10.0, 30.0, 5.0]})
out = add_share(df)
assert abs(out.loc[0, "share"] - 0.25) < 1e-9
assert abs(out.loc[1, "share"] - 0.75) < 1e-9
assert abs(out.loc[2, "share"] - 1.0) < 1e-9
""",
                points=2.0,
            ),
            script(
                "row count is unchanged",
                """
import pandas as pd
df = pd.DataFrame({"region": ["a", "b", "a", "c"], "amount": [1.0, 2.0, 3.0, 4.0]})
assert len(add_share(df)) == 4
""",
            ),
            script(
                "a zero-total region gets 0, not nan",
                """
import pandas as pd
df = pd.DataFrame({"region": ["z", "z"], "amount": [0.0, 0.0]})
out = add_share(df)
assert not out.share.isna().any(), "nan leaked from a zero-total group"
assert (out.share == 0).all()
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "the input frame is not modified",
                """
import pandas as pd
df = pd.DataFrame({"region": ["a"], "amount": [1.0]})
add_share(df)
assert "share" not in df.columns, "add_share mutated its argument"
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["pandas-groupby-mechanics", "pandas-copy-vs-view"],
        hints=[
            "`.agg('sum')` gives one row per group. You need one value per original row.",
            "Look at `GroupBy.transform`. What shape does it return?",
            "Division by a zero total gives nan. Handle it explicitly.",
        ],
        explanation_prompts=[
            point(
                "Explains transform vs agg", "transform", "align", "same number of rows", weight=3
            ),
            point("Avoids the merge", "merge", "join", "no merge", weight=1.5),
            point("Handles the zero-total group", "zero", "nan", "fillna", weight=1.5),
        ],
        par_seconds=360,
    ),
    ChallengeSpec(
        slug="pd-detect-leakage",
        title="Find the Leaked Feature",
        category=ML,
        tier=T.PRODUCTION,
        prompt="""
A churn model scores 0.98 AUC offline and 0.61 in production. Somebody leaked a
feature.

Implement `find_leaky_features(df, target, known_at_prediction)` returning the
**sorted list** of column names that should be considered leakage:

* any column not listed in `known_at_prediction` (i.e. not available at the
  moment of prediction), excluding the target itself, **or**
* any column whose absolute Pearson correlation with the target is ≥ 0.95,
  which is almost never a real signal and almost always the label in disguise.

Ignore non-numeric columns for the correlation test — but they still count as
leakage if they are not known at prediction time.
""",
        starter_code=(
            "import pandas as pd\n\n\n"
            "def find_leaky_features(df, target, known_at_prediction):\n    ...\n"
        ),
        reference_solution="""
import pandas as pd


def find_leaky_features(df, target, known_at_prediction):
    known = set(known_at_prediction)
    leaks = set()

    for column in df.columns:
        if column == target:
            continue
        # Availability is the primary test, and it is the one that does not
        # depend on the data at all: if the value does not exist at prediction
        # time, no correlation is relevant.
        if column not in known:
            leaks.add(column)
            continue
        # A near-perfect correlation with the label is overwhelmingly more
        # likely to be the label re-encoded than a genuinely perfect predictor.
        if pd.api.types.is_numeric_dtype(df[column]) and pd.api.types.is_numeric_dtype(df[target]):
            correlation = df[column].corr(df[target])
            if pd.notna(correlation) and abs(correlation) >= 0.95:
                leaks.add(column)

    return sorted(leaks)
""",
        solution_explanation=(
            "The availability check is the one that matters, because it is a fact about the "
            "system rather than about this sample. The correlation check is a heuristic "
            "backstop for a feature that *is* nominally available but is a re-encoding of the "
            "outcome. Note the ordering: availability is checked first and short-circuits, so "
            "a leaked non-numeric column is still caught."
        ),
        tests=[
            script(
                "catches a column unavailable at prediction time",
                """
import pandas as pd
df = pd.DataFrame({
    "tenure": [1, 2, 3, 4],
    "days_since_closed": [0, 0, 5, 9],
    "churned": [0, 0, 1, 1],
})
out = find_leaky_features(df, "churned", ["tenure"])
assert "days_since_closed" in out, out
""",
                points=2.0,
            ),
            script(
                "catches a near-perfect correlate even when nominally available",
                """
import pandas as pd
df = pd.DataFrame({
    "tenure": [1, 5, 2, 8],
    "churn_flag_copy": [0, 0, 1, 1],
    "churned": [0, 0, 1, 1],
})
out = find_leaky_features(df, "churned", ["tenure", "churn_flag_copy"])
assert "churn_flag_copy" in out, out
""",
                points=2.0,
            ),
            script(
                "does not flag the target itself",
                """
import pandas as pd
df = pd.DataFrame({"a": [1, 2, 3, 4], "y": [0, 0, 1, 1]})
assert "y" not in find_leaky_features(df, "y", ["a"])
""",
                hidden=True,
            ),
            script(
                "leaves an honest weak feature alone",
                """
import pandas as pd
df = pd.DataFrame({
    "tenure": [1, 9, 2, 7, 3, 8],
    "churned": [0, 1, 0, 1, 1, 0],
})
assert find_leaky_features(df, "churned", ["tenure"]) == []
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "returns a sorted list",
                """
import pandas as pd
df = pd.DataFrame({"z_after": [1, 2], "a_after": [3, 4], "y": [0, 1]})
out = find_leaky_features(df, "y", [])
assert out == sorted(out) and out == ["a_after", "z_after"], out
""",
                hidden=True,
            ),
            script(
                "a non-numeric unavailable column is still caught",
                """
import pandas as pd
df = pd.DataFrame({"note": ["a", "b"], "y": [0, 1]})
assert find_leaky_features(df, "y", []) == ["note"]
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["data-leakage"],
        hints=[
            "Which check does not depend on the data at all? Do that one first.",
            "`pd.api.types.is_numeric_dtype` tells you whether `.corr()` is meaningful.",
            "`.corr()` returns NaN for a constant column. Guard against it.",
        ],
        explanation_prompts=[
            point(
                "States the availability-at-prediction-time test",
                "prediction time",
                "available",
                "known at",
                weight=3,
            ),
            point(
                "Explains why a high correlation is suspicious rather than good",
                "too good",
                "suspicious",
                "label",
                "leak",
                weight=2,
            ),
            point(
                "Notes that leakage always improves the offline metric",
                "improve",
                "inflat",
                "offline",
                weight=2,
            ),
        ],
        par_seconds=600,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# QUESTIONS
# ═════════════════════════════════════════════════════════════════════════════
QUESTIONS = [
    QuestionSpec(
        slug="q-numpy-view-vs-copy",
        kind=Q.MCQ,
        category=NP,
        tier=T.UNDERSTAND,
        level=L.JUNIOR,
        prompt="What does `b = a[::2]` do, for a NumPy array `a`?",
        concepts=["numpy-ndarray-memory-model"],
        options=[
            opt(
                "a",
                "Creates a view sharing a's memory; writing to b changes a",
                correct=True,
                why="Basic slicing returns a view with adjusted strides. No data is copied, "
                "which is why writes propagate back to the parent array.",
            ),
            opt(
                "b",
                "Creates an independent copy of every second element",
                why="That is what `a[::2].copy()` does. Plain slicing does not allocate.",
            ),
            opt(
                "c",
                "Creates a copy only if a is large enough",
                why="There is no size heuristic. Basic slicing always returns a view.",
            ),
            opt(
                "d",
                "Creates a view, but writes to it raise an error",
                why="Views are writable by default. That is precisely the hazard.",
            ),
        ],
        expected_answer="A view sharing memory with the original.",
        ideal_senior_answer=(
            "A view. Basic slicing adjusts the strides and offset onto the same buffer, so no "
            "data is copied and `b.base is a`. The practical consequence is that writing to `b` "
            "writes through to `a` — which is why a function that slices its input and then "
            "mutates the slice has silently corrupted its caller's array. When I want "
            "independence I say `.copy()` explicitly; when I am debugging unexplained mutation "
            "the first thing I check is `.base`."
        ),
        hints=["Check `b.base` — what does it point at?"],
        tags=["numpy"],
        par_seconds=60,
    ),
    QuestionSpec(
        slug="q-broadcasting-shape",
        kind=Q.MCQ,
        category=NP,
        tier=T.IMPLEMENT,
        level=L.MID,
        prompt=(
            "`a` has shape `(1000, 1)` and `b` has shape `(1000,)`. What is the shape of `a - b`?"
        ),
        concepts=["numpy-broadcasting-rules"],
        options=[
            opt(
                "a",
                "(1000, 1000) — one million elements",
                correct=True,
                why="Aligning from the right: 1 vs 1000 stretches to 1000, and a's leading 1000 "
                "has nothing to align against so it is kept. This is the classic accidental "
                "outer product, and it is a common cause of OOM in training loops.",
            ),
            opt("b", "(1000, 1)", why="That would require b to have shape (1,) or (1000, 1)."),
            opt("c", "(1000,)", why="Broadcasting never reduces dimensionality."),
            opt(
                "d",
                "ValueError — the shapes are incompatible",
                why="They are compatible by the rules, which is exactly why this bug is silent.",
            ),
        ],
        expected_answer="(1000, 1000).",
        ideal_senior_answer=(
            "(1000, 1000). Aligned from the right, b's 1000 meets a's 1 and stretches it. "
            "That is 8MB from two 8KB arrays, and it is almost always a bug — the author meant "
            "`a.ravel() - b` or `a - b[:, None]`. I would add `assert a.shape == b.shape` at "
            "the point where the two are supposed to match."
        ),
        common_wrong_answer="(1000, 1) — assuming the trailing 1 is simply ignored.",
        rubric=[point("States (1000, 1000)", "1000, 1000", "1000x1000", weight=3)],
        followups=[
            "How would you defend against this in code you have to maintain?",
            "Where would this bite hardest in a training loop?",
        ],
        tags=["numpy", "broadcasting"],
        par_seconds=90,
    ),
    QuestionSpec(
        slug="q-vectorize-is-not-fast",
        kind=Q.MCQ,
        category=NP,
        tier=T.DEBUG,
        level=L.MID,
        prompt=(
            "A colleague replaces a Python loop with `np.vectorize(f)(arr)` and reports the "
            "code is now 'vectorised'. What should you say in review?"
        ),
        concepts=["numpy-vectorization"],
        options=[
            opt(
                "a",
                "np.vectorize is a convenience wrapper around a Python loop and gives essentially no speed-up",
                correct=True,
                why="NumPy's own documentation says this explicitly. It exists for broadcasting "
                "semantics, not performance. The change makes the code look optimised without "
                "making it faster, which is worse than leaving the loop.",
            ),
            opt(
                "b",
                "Correct — np.vectorize compiles the function to C",
                why="No compilation happens. That is numba or Cython.",
            ),
            opt(
                "c",
                "Correct, but only for float64 arrays",
                why="The dtype makes no difference; it is a Python-level loop either way.",
            ),
            opt(
                "d",
                "It is faster but uses more memory",
                why="It is not faster.",
            ),
        ],
        expected_answer="np.vectorize does not vectorise; it loops in Python.",
        ideal_senior_answer=(
            "I would point at NumPy's own documentation, which states that `np.vectorize` is "
            "provided for convenience and is essentially a Python-level loop. It exists to give "
            "a scalar function broadcasting semantics, not to make it fast. So the change is "
            "worse than neutral: the code now *looks* optimised, which means nobody revisits it "
            "when the job is still slow.\n\n"
            "What I would suggest instead depends on the function. If it decomposes into array "
            "primitives, write it that way. If it genuinely does not — a sequential dependency, "
            "say — then keep the loop and put a numba decorator on it, or accept the cost and "
            "leave a comment explaining why the loop is correct here. Either way I would want a "
            "benchmark in the PR, because both of us are guessing otherwise."
        ),
        common_wrong_answer="Assuming the name describes the behaviour.",
        followups=["What would you actually suggest instead?"],
        tags=["numpy", "performance", "review"],
        par_seconds=90,
    ),
    QuestionSpec(
        slug="q-explain-groupby-transform",
        kind=Q.EXPLAIN,
        category=PD,
        tier=T.EXPLAIN,
        level=L.MID,
        prompt=(
            "Explain the difference between `groupby().agg()`, `groupby().transform()` and "
            "`groupby().apply()`. When would you reach for each, and why is `.apply()` slow?"
        ),
        concepts=["pandas-groupby-mechanics"],
        expected_answer=(
            "agg reduces each group to one row; transform returns a value per original row "
            "aligned to the index; apply is the general escape hatch and is slow because it "
            "calls a Python function per group."
        ),
        ideal_senior_answer=(
            "They differ in the shape of what comes back. `.agg` reduces: many rows in, one row "
            "per group out, indexed by the group key — and for the built-in reducers it runs in "
            "C. `.transform` preserves shape: one value per original row, index-aligned, which "
            "is what you want whenever a group statistic needs to be attached back to each row. "
            "`df['share'] = df.amount / df.groupby('region').amount.transform('sum')` is the "
            "canonical use, and doing it with `.agg` would force a merge — slower and an "
            "opportunity to get the cardinality wrong.\n\n"
            "`.apply` is the escape hatch for logic that does not decompose into either. It is "
            "slow because it invokes a Python callable once per group and materialises a full "
            "sub-DataFrame each time; with 100,000 small groups, the construction cost dominates "
            "entirely. I reach for it only when the operation genuinely needs the whole group as "
            "a frame, and I leave a comment saying why, so the next reader does not 'optimise' "
            "it into something subtly different.\n\n"
            "One related trap: grouping on categorical keys without `observed=True` emits every "
            "unobserved category combination, which can turn a small frame into millions of rows."
        ),
        common_wrong_answer=(
            "Saying apply is 'more flexible' without being able to say what it costs or what "
            "transform is for — which usually means transform never gets used."
        ),
        rubric=[
            point("agg reduces to one row per group", "agg", "reduce", "one row", weight=2),
            point(
                "transform preserves row count and aligns to the index",
                "transform",
                "same number of rows",
                "align",
                "per row",
                weight=3,
            ),
            point(
                "Explains apply's cost as per-group Python calls",
                "python",
                "per group",
                "overhead",
                "sub-dataframe",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "Gives a concrete case for transform",
                "share",
                "percentage",
                "normali",
                "attach",
                weight=1.5,
                dimension="practical_experience",
            ),
            point(
                "Mentions observed=True or another production trap",
                "observed",
                "categor",
                weight=1.5,
                dimension="production_awareness",
            ),
        ],
        followups=[
            "How would you compute a per-group rank without apply?",
            "What happens with observed=False on three categorical keys?",
        ],
        tags=["pandas"],
        par_seconds=300,
    ),
    QuestionSpec(
        slug="q-explain-data-leakage",
        kind=Q.EXPLAIN,
        category=ML,
        tier=T.STAFF_TRADEOFF,
        level=L.SENIOR,
        prompt=(
            "Your team's churn model scores 0.98 AUC in offline evaluation and 0.61 in its "
            "first production week. Walk me through how you would investigate."
        ),
        concepts=["data-leakage"],
        expected_answer=(
            "Treat it as leakage until proven otherwise: audit features for availability at "
            "prediction time, check the split strategy, and verify preprocessing was fitted "
            "inside the folds."
        ),
        ideal_senior_answer=(
            "A 37-point gap is not drift and it is not bad luck — that is leakage until proven "
            "otherwise, so I would spend the first hour there rather than on the model.\n\n"
            "First, the availability audit, because it needs no experiments: for every feature, "
            "at the moment of prediction in production, would this value be populated? Anything "
            "derived from an event at or after the outcome is leakage. The subtle ones are "
            "timestamps — an `updated_at` touched when the outcome is recorded encodes the label.\n\n"
            "Second, the split. Churn is inherently temporal, so a random split trains on the "
            "future and predicts the past — which no deployment can do. It should be a time "
            "split. I would also check for group leakage: the same customer in both folds means "
            "the model memorised customers.\n\n"
            "Third, preprocessing. If the scaler or target encoder was fitted before the split, "
            "the test fold's statistics informed the training transform. Wrapping everything in "
            "a Pipeline makes that structurally impossible rather than merely unintended.\n\n"
            "The fastest diagnostic is ablation: drop the single most important feature and "
            "re-evaluate. If the score collapses to roughly production levels, you have found "
            "it. And the thing I would say to the team afterwards is that no metric would ever "
            "have caught this, because leakage always makes the number look better. The "
            "protection has to be a review question — 'is this known at prediction time?' — not "
            "a threshold."
        ),
        common_wrong_answer=(
            "Jumping straight to distribution shift or retraining. Both are real phenomena, but "
            "neither explains a gap this large in week one, and pursuing them burns days."
        ),
        rubric=[
            point("Names leakage as the leading hypothesis", "leak", weight=3),
            point(
                "Applies the availability-at-prediction-time test",
                "prediction time",
                "available",
                "known at",
                "future",
                weight=3,
            ),
            point(
                "Raises temporal splitting",
                "time split",
                "temporal",
                "timeseriessplit",
                "chronolog",
                weight=2.5,
            ),
            point(
                "Catches preprocessing fitted outside the fold",
                "pipeline",
                "fit",
                "scaler",
                "before the split",
                weight=2,
                dimension="depth",
            ),
            point(
                "Proposes ablation as a concrete diagnostic",
                "ablat",
                "drop the feature",
                "remove",
                weight=2,
                dimension="practical_experience",
            ),
            point(
                "Notes leakage always improves the offline metric",
                "always improves",
                "looks better",
                "inflat",
                weight=2,
                dimension="production_awareness",
            ),
            point(
                "Suggests a process fix, not just this fix",
                "review",
                "checklist",
                "process",
                "pipeline",
                weight=1.5,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "How would you split data where customers churn and later return?",
            "What would you add to code review to stop this recurring?",
            "When is a 0.98 AUC legitimately believable?",
        ],
        tags=["ml", "leakage", "interview"],
        par_seconds=480,
    ),
    QuestionSpec(
        slug="q-merge-doubled-revenue",
        kind=Q.DEBUGGING,
        category=PD,
        tier=T.DEBUG,
        level=L.MID,
        prompt=(
            "After adding a `customers` join to the reporting pipeline, total revenue in the "
            "dashboard is exactly 2x the source system. The job logs no errors. "
            "What is the most likely cause, and what one argument would have caught it?"
        ),
        concepts=["pandas-join-cardinality"],
        expected_answer=(
            "Duplicate keys on the right side of the merge multiplied rows. `validate='many_to_one'` "
            "would have raised at the merge."
        ),
        ideal_senior_answer=(
            "Duplicate keys in `customers`. Every order matched two customer rows, so every "
            "amount is counted twice — an exact 2x is the signature of a uniform duplication, "
            "which usually means a dimension table loaded twice or a slowly-changing dimension "
            "with two validity rows per entity.\n\n"
            "`validate='many_to_one'` on the merge would have raised a MergeError at the line "
            "responsible instead of shipping wrong numbers to a dashboard. I would add that "
            "argument to every merge in the pipeline, not just this one, plus an "
            "`assert len(result) == len(orders)` invariant — the two together make this class "
            "of bug impossible to ship silently.\n\n"
            "I would also check the load job for why duplicates appeared, because fixing the "
            "merge without fixing the source just moves the failure."
        ),
        common_wrong_answer=(
            "Blaming the aggregation or double-counting in the dashboard query, and spending a "
            "day in the BI tool while the bug is upstream in the join."
        ),
        rubric=[
            point(
                "Identifies duplicate keys multiplying rows",
                "duplicate",
                "cardinality",
                "multipl",
                weight=3,
            ),
            point("Names validate=", "validate", "many_to_one", weight=3),
            point(
                "Suggests a row-count invariant",
                "row count",
                "assert",
                "len",
                weight=2,
                dimension="production_awareness",
            ),
            point(
                "Looks upstream for why duplicates exist",
                "upstream",
                "source",
                "load",
                weight=1.5,
                dimension="depth",
            ),
        ],
        followups=[
            "How would you find which keys are duplicated?",
            "What does indicator=True give you?",
        ],
        tags=["pandas", "debugging"],
        par_seconds=300,
    ),
    QuestionSpec(
        slug="q-dtype-id-precision",
        kind=Q.MCQ,
        category=PD,
        tier=T.PRODUCTION,
        level=L.SENIOR,
        prompt=(
            "A left join introduces NaN into a column of 19-digit user IDs, and the column "
            "becomes float64. What is the production consequence?"
        ),
        concepts=["pandas-dtypes-and-memory"],
        options=[
            opt(
                "a",
                "IDs above 2^53 lose precision and distinct users collide into the same ID",
                correct=True,
                why="float64 has 53 bits of mantissa, so consecutive integers above ~9.0e15 are "
                "not representable. Two different 19-digit IDs can round to the same float, and "
                "rows get silently attributed to the wrong user. Nothing errors.",
            ),
            opt(
                "b",
                "Nothing — floats represent integers exactly",
                why="Only up to 2^53. 19-digit IDs are far beyond that.",
            ),
            opt(
                "c",
                "The join fails on the next step with a dtype error",
                why="pandas will happily continue. That is the problem.",
            ),
            opt(
                "d",
                "Only display is affected; the underlying values are intact",
                why="The precision is lost in the stored value, not in formatting.",
            ),
        ],
        expected_answer="Precision loss above 2^53 causes distinct IDs to collide.",
        ideal_senior_answer=(
            "Above 2^53 float64 cannot represent consecutive integers, so 19-digit IDs round and "
            "distinct users collide. Everything downstream — joins, groupbys, dedupe — then "
            "attributes rows to the wrong entity, with no error anywhere. The fix is the nullable "
            "`Int64` dtype for any ID column, and an explicit dtype assertion after every join "
            "that can introduce missing values."
        ),
        rubric=[point("Names the 2^53 precision limit", "2^53", "53 bit", "precision", weight=3)],
        followups=["What dtype would you use instead?"],
        tags=["pandas", "dtypes"],
        par_seconds=120,
    ),
    QuestionSpec(
        slug="q-tradeoff-vectorise-or-not",
        kind=Q.TRADEOFF,
        category=NP,
        tier=T.STAFF_TRADEOFF,
        level=L.SENIOR,
        prompt=(
            "A batch job iterates 200 million rows and applies a rule that depends on the "
            "previous row's output. A colleague wants to vectorise it. Argue both sides and "
            "state what you would do."
        ),
        concepts=["numpy-vectorization"],
        expected_answer=(
            "A sequential dependency cannot be naively vectorised; the options are a scan "
            "primitive, a compiled kernel, or accepting the loop — decided by measurement."
        ),
        ideal_senior_answer=(
            "The dependency is the whole question. If row i depends on row i-1, there is no "
            "element-wise formulation — vectorising it means either finding a scan primitive "
            "that expresses the recurrence (`cumsum`, `cumprod`, `np.maximum.accumulate` cover "
            "more cases than people expect, and many rules reduce to one), or leaving the loop "
            "and compiling it with numba, which typically gets within a small factor of C for a "
            "one-line decorator.\n\n"
            "The case *for* trying: 200M rows in a Python loop is likely hours, and if the rule "
            "does decompose into a scan, the win is enormous.\n\n"
            "The case *against*: a contorted array formulation that is neither fast nor "
            "readable is the worst outcome, and at 200M rows a vectorised version materialises "
            "multi-gigabyte intermediates that may not fit at all — so the 'fast' version gets "
            "OOM-killed while the loop would have finished.\n\n"
            "What I would do: spend thirty minutes checking whether the recurrence is a known "
            "scan. If it is, vectorise. If not, numba the loop and measure. I would not accept "
            "either answer without a benchmark on realistic data volume, because both of us are "
            "guessing until then — and the benchmark costs less than the argument."
        ),
        common_wrong_answer=(
            "'Always vectorise' as a rule, which produces an unreadable expression that is "
            "slower than the loop it replaced and allocates 12GB doing it."
        ),
        rubric=[
            point(
                "Identifies the sequential dependency as the blocker",
                "sequential",
                "depends on",
                "previous",
                "recurrence",
                weight=3,
            ),
            point(
                "Offers scan primitives as the vectorised route",
                "cumsum",
                "scan",
                "accumulate",
                "prefix",
                weight=2,
                dimension="depth",
            ),
            point(
                "Raises memory cost of intermediates at this scale",
                "memory",
                "intermediate",
                "oom",
                "allocat",
                weight=2,
                dimension="production_awareness",
            ),
            point(
                "Mentions a compiled option",
                "numba",
                "cython",
                "compil",
                "rust",
                weight=1.5,
            ),
            point(
                "Insists on measurement before deciding",
                "measure",
                "benchmark",
                "profil",
                weight=2.5,
                dimension="tradeoff_awareness",
            ),
            point(
                "Weighs readability against speed",
                "readab",
                "maintain",
                "unreadable",
                weight=1.5,
                dimension="clarity",
            ),
        ],
        followups=[
            "Which recurrences reduce to a cumulative operation?",
            "How would you chunk this if memory is the binding constraint?",
        ],
        tags=["numpy", "performance", "tradeoff"],
        par_seconds=420,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# MISSIONS
# ═════════════════════════════════════════════════════════════════════════════
MISSIONS = [
    MissionSpec(
        slug="mission-revenue-doubled",
        title="Incident: Revenue Reported at 2x",
        kind="incident",
        category=PD,
        building="data_science_lab",
        tier=T.DEBUG,
        briefing="""
**07:40.** Finance opens the weekly revenue dashboard and sees £4.8M against a
source-system figure of £2.4M. Exactly double.

The pipeline ran green. No alert fired. The only change in the last deploy was a
new `customers` join added to enrich orders with account tier.

You are on call. Find it.
""",
        objective="Diagnose the doubling, fix the join, and propose the guard that prevents a recurrence.",
        artifacts={
            "pipeline_log": (
                "07:02:11 INFO  extract.orders rows=184,203\n"
                "07:02:19 INFO  extract.customers rows=41,559\n"
                "07:02:24 INFO  transform.enrich_orders rows=368,406\n"
                "07:02:31 INFO  aggregate.revenue_by_region rows=14\n"
                "07:02:31 INFO  pipeline complete status=success duration=20.4s"
            ),
            "the_change": ('orders.merge(customers, on="customer_id", how="inner")'),
            "source_check": (
                "SELECT customer_id, COUNT(*) c FROM customers GROUP BY 1 HAVING c > 1 LIMIT 3;\n"
                " customer_id | c\n"
                "-------------+---\n"
                "     8801234 | 2\n"
                "     8801901 | 2\n"
                "     8802044 | 2"
            ),
            "hint_if_stuck": (
                "Compare the row counts in the log. 184,203 orders went into the enrichment "
                "step and 368,406 came out. The join is not enriching; it is multiplying."
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="question",
                title="Read the evidence",
                question="q-merge-doubled-revenue",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Fix the join",
                challenge="pd-safe-merge",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Write the postmortem",
                prompt=(
                    "Write the incident summary: what happened, why no alert fired, what you "
                    "changed, and what guard you are adding so the next duplicate-key load "
                    "fails loudly instead of silently. Be specific about the guard."
                ),
                config={
                    "rubric": [
                        point(
                            "States the root cause as duplicate join keys",
                            "duplicate",
                            "cardinality",
                            weight=3,
                        ),
                        point(
                            "Explains why nothing alerted",
                            "no error",
                            "silent",
                            "success",
                            "green",
                            weight=2,
                            dimension="production_awareness",
                        ),
                        point(
                            "Names a concrete guard", "validate", "assert", "row count", weight=3
                        ),
                        point(
                            "Addresses the upstream duplicate load",
                            "upstream",
                            "source",
                            "load",
                            weight=2,
                            dimension="architecture_thinking",
                        ),
                    ]
                },
            ),
            MissionStepSpec(
                step_type="journal",
                title="What will you check next time?",
                prompt="One sentence you will actually remember at 07:40 next time a total looks wrong.",
                required=False,
            ),
        ],
        concepts=["pandas-join-cardinality", "pandas-dtypes-and-memory"],
        success_criteria=[
            "Root cause identified as duplicate keys, not aggregation",
            "Merge fixed with validate= and a left join",
            "A guard proposed that would have caught this before the dashboard",
        ],
        debrief="""
The row counts were in the log the whole time: 184,203 in, 368,406 out. Nothing
alerted because nothing was *wrong* by any check the pipeline performed — it
checked that the job completed, not that it produced sane data.

That is the general lesson. Green pipelines and correct data are different
properties, and only one of them was being monitored. A single
`validate="many_to_one"` on each merge, plus row-count invariants between
stages, converts this entire class of bug from a silent corruption into a
loud failure at the responsible line.
""",
        required_level=6,
        estimated_minutes=25,
        par_seconds=1500,
    ),
    MissionSpec(
        slug="mission-vectorise-the-nightly",
        title="The Nightly Job That Takes Nine Hours",
        kind="data_lab",
        category=NP,
        building="data_science_lab",
        tier=T.OPTIMIZE,
        briefing="""
The feature-generation job starts at 22:00 and is supposed to finish before the
06:00 model retrain. It now finishes at 07:10, so the retrain uses yesterday's
features and nobody noticed for three weeks.

The profile is unambiguous: 94% of wall time is in one distance computation.
""",
        objective="Make the hot loop fast enough, and be able to say why it was slow.",
        artifacts={
            "profile": (
                "ncalls  tottime  percall  cumtime  percall filename:lineno(function)\n"
                "     1   31402.1  31402.1  32651.7  32651.7 features.py:88(pairwise_distances)\n"
                "160000     892.4     0.006    892.4     0.006 {method 'sum' of 'numpy.ndarray'}\n"
                "     1      41.2     41.2  32694.0  32694.0 features.py:12(build_features)"
            ),
            "note": (
                "31,402 seconds is 8.7 hours in one function. The 160,000 calls to .sum() are "
                "the tell: a vectorised implementation would call it once."
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="challenge",
                title="Vectorise the distance computation",
                challenge="np-vectorise-distance",
            ),
            MissionStepSpec(
                step_type="question",
                title="Know what you did not do",
                question="q-vectorize-is-not-fast",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Justify the trade",
                prompt=(
                    "Your fix builds an (n, m, d) intermediate. At the production scale of "
                    "n=m=200,000 that array does not fit in memory. Explain what you would do "
                    "instead at that scale, and what you would give up."
                ),
                config={
                    "rubric": [
                        point(
                            "Recognises the intermediate does not scale",
                            "memory",
                            "does not fit",
                            "oom",
                            "intermediate",
                            weight=3,
                        ),
                        point(
                            "Offers chunking or the norm expansion",
                            "chunk",
                            "batch",
                            "expansion",
                            "matmul",
                            "dot",
                            weight=3,
                            dimension="depth",
                        ),
                        point(
                            "States what the alternative costs",
                            "accuracy",
                            "precision",
                            "complexity",
                            "readab",
                            weight=2,
                            dimension="tradeoff_awareness",
                        ),
                    ]
                },
            ),
        ],
        concepts=["numpy-vectorization", "numpy-broadcasting-rules"],
        success_criteria=[
            "Distance computation at least 25x faster",
            "Can explain why np.vectorize would not have helped",
            "Aware the vectorised version has its own scaling limit",
        ],
        debrief="""
The speed-up is the easy part. The part worth keeping is the second-order
thinking: the vectorised version trades time for memory, and at production scale
that trade stops being free.

"Vectorise everything" and "loops are fine" are both wrong as rules. What
actually works is knowing the three regimes — Python loop, vectorised with
intermediates, and chunked or compiled — and measuring which one your data size
puts you in.
""",
        required_level=10,
        estimated_minutes=30,
        par_seconds=1800,
    ),
]

PACK = ContentPack(
    name="data_engineering",
    concepts=CONCEPTS,
    challenges=CHALLENGES,
    questions=QUESTIONS,
    missions=MISSIONS,
)
