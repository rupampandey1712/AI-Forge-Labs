"""The RAG Tower — retrieval, grounding, and how to know whether it works.

THE THESIS OF THIS PACK: almost every "the LLM is hallucinating" bug is a
retrieval bug. The model was handed context that did not contain the answer and
did the only thing it could. Debugging at the prompt layer when the fault is at
the retrieval layer is the single most common waste of time in AI engineering,
and the concepts here are ordered to make that diagnosis fast.

The companion RAG Tuning Bench lab runs this same pipeline with every
intermediate exposed. Read the chunking concept, then go and drag the chunk_size
slider — the two together do something neither does alone.
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

R = Category.RAG
E = Category.EVALS

# ═════════════════════════════════════════════════════════════════════════════
# CONCEPTS
# ═════════════════════════════════════════════════════════════════════════════
CONCEPTS = [
    ConceptSpec(
        slug="rag-why-it-fails",
        title="Where RAG Actually Fails",
        category=R,
        skill_node="rag.pipeline",
        difficulty=4,
        summary=(
            "RAG has five stages and any of them can be the fault. Knowing which one takes ten "
            "minutes; guessing takes a week."
        ),
        explanation="""
A RAG pipeline is: **ingest → chunk → embed → retrieve → generate**. When the
answer is wrong, exactly one of those is usually at fault, and they fail in very
different ways.

Work down the ladder in this order, because each step is cheaper than the one
after it:

**1. Is the fact in the corpus at all?** Grep for it. If it is not there, no
amount of retrieval tuning helps, and the correct system behaviour is to refuse.
This takes thirty seconds and eliminates a surprising fraction of reports.

**2. Did chunking destroy it?** A fact split across a boundary exists in the
corpus but in no single chunk. "The timeout is 30" ends one chunk and "seconds
for premium accounts" starts the next. Both chunks are useless; the fact is
gone. Look at the actual chunk text, not the chunk count.

**3. Was it retrieved?** Print what came back with its scores. If the right
chunk is at rank 8 with k=4, that is a ranking problem — reranking or hybrid
search. If it is not in the top 50 at all, the embedding is not capturing the
query, which is a different and harder problem.

**4. Did it survive context assembly?** Truncation at the context limit silently
drops the tail. If the right chunk was retrieved at rank 4 and the window fit
three, it never reached the model.

**5. Did the model ignore it?** Only now is it a generation problem. This is
rarer than people expect, and when it does happen the cause is usually context
that contradicts itself — two documents disagreeing, and the model picking the
wrong one.

**Why the order matters so much.** Stages 1–4 are checked by printing things.
Stage 5 is where prompt engineering lives, and it is the expensive, uncertain,
hard-to-validate one. Going straight there — which is what everybody does — means
spending days on prompts to fix a chunking bug.
""",
        examples=[
            example(
                "The five-minute diagnosis",
                """
# 1. Is it in the corpus?
print([d for d in docs if "15 minutes" in d.text])

# 2. Is it in any single chunk?
print([c for c in chunks if "15 minutes" in c.text])

# 3. Was it retrieved, and at what rank?
for i, c in enumerate(retrieved):
    print(i, round(c.score, 3), c.text[:70])

# 4. Did it survive assembly?
print("15 minutes" in final_prompt)

# 5. Only now is the prompt the suspect.
""",
                note="Four prints. Most 'hallucination' tickets are closed by the second one.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Rewriting the prompt first",
                "Prompt work is the slowest and least certain fix available, and it cannot "
                "repair context that does not contain the answer.",
                "Walk the ladder. Confirm the fact reached the model before touching how the "
                "model was asked.",
                Severity.HIGH,
            ),
            mistake(
                "Treating a refusal as a failure",
                "When the corpus genuinely lacks the answer, refusing is correct behaviour. "
                "Tuning until the system answers anyway produces confident invention.",
                "Include unanswerable cases in the eval set, and score refusal as a pass.",
                Severity.HIGH,
            ),
        ],
        real_world_usage=[
            "Triaging a 'the bot is hallucinating' ticket in ten minutes rather than a week",
        ],
        related=["rag-chunking-tradeoffs", "rag-hybrid-retrieval"],
        tags=["rag", "debugging"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="rag-chunking-tradeoffs",
        title="Chunking Is a Semantic Decision",
        category=R,
        skill_node="rag.chunking",
        difficulty=5,
        summary=(
            "chunk_size is not a memory setting. It decides whether a chunk still means "
            "anything on its own — which is the only thing the embedding can capture."
        ),
        explanation="""
An embedding represents a chunk as a single vector. That vector can only encode
what the chunk *says*, so the real question for any chunk size is: **does this
piece of text still mean something without the text around it?**

**Small chunks (100–300 chars)** retrieve precisely — a query matching one
sentence pulls exactly that sentence. But they lose the context that made the
sentence meaningful. "It expires after 15 minutes" retrieves beautifully and
tells the model nothing, because *what* expires is in the previous chunk.

**Large chunks (1500+ chars)** keep the context and dilute the embedding. One
vector now averages six unrelated topics, so it is moderately similar to every
query and strongly similar to none. It also burns context window: at k=5, five
2,000-character chunks is 10,000 characters of prompt, most of it irrelevant.

**Overlap** is insurance against a fact being cut in half. It costs duplicated
storage and — the part people miss — it lets one document occupy several top-k
slots with near-identical text, crowding out genuinely different sources.

**Structure-aware splitting beats any fixed size.** Split on paragraph
boundaries first, then sentences, then words, and only cut mid-word as a last
resort. A chunk that ends mid-sentence is a chunk whose embedding is partly
noise. This is the single highest-value improvement in most pipelines and it
requires no model change.

**The thing worth internalising:** there is no universal best chunk size.
Reference documentation with short independent sections wants small chunks.
Narrative prose where meaning accumulates across paragraphs wants large ones.
The only way to know is to measure against your own questions — which is what
the eval set is for.
""",
        examples=[
            example(
                "The fact that survives neither chunk",
                """
text = "Password reset tokens are single-use. The link expires after 15 minutes."

# chunk_size=45, no overlap, no structure awareness:
#   chunk 0: "Password reset tokens are single-use. The li"
#   chunk 1: "nk expires after 15 minutes."
#
# "How long is the reset link valid?" matches neither well. The fact is in the
# corpus and in no retrievable unit.
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Picking a chunk size by memory or token limits",
                "The limit is a constraint, not a design input. Chunk size is about whether the "
                "text is self-contained, which is a property of the document.",
                "Choose by semantic unit — usually a section or a few paragraphs — then check "
                "it fits the budget.",
                Severity.MEDIUM,
            ),
            mistake(
                "Fixed-size splitting with no structure awareness",
                "Chunks end mid-sentence and sometimes mid-word, so part of every embedding is "
                "noise and part of every fact is missing.",
                "Split on paragraphs, then sentences, then words. Cut mid-word only as a last "
                "resort.",
                Severity.HIGH,
            ),
            mistake(
                "Large overlap to be safe",
                "Near-duplicate chunks occupy multiple top-k slots, so k=5 returns three copies "
                "of one passage and crowds out the other sources.",
                "Keep overlap around 10–20% of chunk size, and deduplicate by document when "
                "assembling context.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Fixing a bot that could not answer a question its own docs plainly stated",
        ],
        requires=["rag-why-it-fails"],
        tags=["rag", "chunking"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="rag-hybrid-retrieval",
        title="Hybrid Retrieval — Why Vectors Alone Miss",
        category=R,
        skill_node="rag.retrieval",
        difficulty=6,
        summary=(
            "Embeddings capture meaning and lose exact tokens. Error codes, flag names and "
            "version numbers are exactly the queries where meaning is not the point."
        ),
        explanation="""
Dense vector search finds text that *means* something similar. That is its
strength and its precise limitation.

Search for `ERR_CONN_4021`. Semantically, that string means almost nothing — it
is an arbitrary token. The embedding places it somewhere near other
error-code-shaped strings, and the chunk containing the actual definition may
not be in the top 50. A keyword index finds it instantly, because exact match is
the entire problem.

The reverse also holds: search for "how do I stop the service from dying under
load", and BM25 finds nothing because none of those words appear in a document
titled "Configuring OOM thresholds". Dense retrieval handles that easily.

**So run both, and fuse.** Reciprocal Rank Fusion is the standard method and it
is almost suspiciously simple:

    score(d) = Σ  1 / (k + rank_i(d))      over each retriever i, k ≈ 60

It uses only *ranks*, never raw scores, which is what makes it work: a cosine
similarity of 0.82 and a BM25 score of 14.3 are not comparable quantities, and
any attempt to normalise them into a weighted sum requires tuning that does not
transfer between corpora. Ranks are always comparable. A document ranked highly
by both retrievers wins; a document ranked highly by one still places.

**When to add it.** Hybrid roughly doubles retrieval latency and adds an index to
maintain. It earns that when the corpus contains identifiers people search for
literally — error codes, API names, SKUs, config keys, version numbers. For
prose-only corpora the gain is usually small. Measure on your own eval set
rather than adopting it because it is best practice.
""",
        examples=[
            example(
                "RRF in six lines",
                """
def rrf(rankings, k=60):
    scores = {}
    for ranking in rankings:                 # one list of doc ids per retriever
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)
""",
                note="No score normalisation anywhere. That is the point — ranks are "
                "comparable across retrievers in a way raw scores never are.",
            ),
        ],
        common_mistakes=[
            mistake(
                "Normalising and weighting raw scores instead of fusing ranks",
                "Cosine similarity and BM25 live on different scales with different "
                "distributions, so the weights need retuning for every corpus and silently "
                "stop being right as the corpus grows.",
                "Fuse on ranks with RRF. It has one parameter and it transfers.",
                Severity.MEDIUM,
            ),
            mistake(
                "Adding hybrid search without measuring it",
                "It doubles retrieval latency and adds an index to keep in sync. On a "
                "prose-only corpus the improvement can be nil.",
                "Run the eval set with and without. Adopt it on evidence.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Making error codes findable in a support bot that had 'meaning' covered",
        ],
        requires=["rag-chunking-tradeoffs"],
        related=["rag-reranking"],
        tags=["rag", "retrieval", "bm25"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="rag-reranking",
        title="Reranking — Retrieve Broadly, Then Be Picky",
        category=R,
        skill_node="rag.reranking",
        difficulty=6,
        summary=(
            "A bi-encoder compares two vectors computed separately. A reranker reads the query "
            "and the document together. The second is far better and far too slow to use first."
        ),
        explanation="""
The architectural distinction is the whole idea.

A **bi-encoder** embeds the query and each document *independently*, then
compares vectors. Document embeddings are precomputed, so search over a million
documents is one vector operation. The cost is that the document embedding was
produced without any knowledge of the query — it has to be a general-purpose
summary of the text.

A **cross-encoder** takes `(query, document)` as a single input and attends
across both. It can tell that this paragraph answers *this specific question*
rather than merely being about the same topic. It is dramatically more accurate,
and it must run once per candidate pair — so scoring a million documents is
impossible.

**Which gives the standard two-stage design:** retrieve 50 candidates with the
cheap bi-encoder, rerank them with the expensive cross-encoder, keep the top 5.
You get cross-encoder quality over a set the cross-encoder could actually
process.

**How to tell whether it is earning its cost.** Look at the *rank movement*. If
reranking reorders the top 10 substantially, it is finding things the embedding
missed. If the order barely changes, you are paying latency for nothing — which
usually means either the retrieval was already good or the reranker is not suited
to the domain. The movement is the metric, not the score.

**The trap:** reranking cannot rescue a bad first stage. If the right document is
not in the 50 candidates, no amount of reranking finds it. Reranking improves
*ordering*, never *recall*. When recall is the problem, the fix is chunking,
hybrid search or a better embedding model — and reranking will quietly hide that
by making the wrong answers better-ordered.
""",
        examples=[
            example(
                "Two stages, two jobs",
                """
candidates = vector_search(query, k=50)      # cheap, high recall, rough order
top = cross_encoder.rerank(query, candidates)[:5]   # expensive, precise order

# The diagnostic: how much did the order actually change?
moved = sum(1 for new, c in enumerate(top) if c.original_rank != new)
print(f"{moved}/5 changed position")   # 0 means you bought nothing
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Expecting reranking to fix low recall",
                "It reorders the candidate set. A document absent from that set cannot be "
                "promoted into it, so recall is unchanged by construction.",
                "Fix recall first — chunking, hybrid, embedding model. Rerank after.",
                Severity.HIGH,
            ),
            mistake(
                "Reranking a candidate set that is too small",
                "Reranking the top 5 to produce the top 5 can only reorder five items. The "
                "value comes from being picky over a broad set.",
                "Retrieve 30–100 candidates, rerank, then cut to k.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Deciding whether 180ms of reranking latency is buying anything measurable",
        ],
        requires=["rag-hybrid-retrieval"],
        tags=["rag", "reranking"],
        estimated_minutes=9,
    ),
    ConceptSpec(
        slug="rag-grounding-and-refusal",
        title="Grounding, Citation and the Right to Refuse",
        category=R,
        skill_node="rag.grounding",
        difficulty=6,
        summary=(
            "A system that cannot say 'I don't know' will invent. Refusal is a feature, and it "
            "has to be designed, prompted and measured for."
        ),
        explanation="""
Given context that does not contain the answer, a model will still produce one.
That is not malfunction — it is what next-token prediction does. The system has
to make refusal both *permitted* and *attractive*.

**Permitted, in the prompt.** Explicitly: "If the context does not contain the
answer, say so. Do not use knowledge outside the provided context." Without that
sentence the model treats answering as the task and will reach for parametric
knowledge, which is exactly the knowledge you built RAG to avoid relying on.

**Attractive, through citation.** Requiring a citation per claim changes the
generation problem. A claim with nothing to cite becomes visibly unsupported to
the model itself while it is generating, and inline citations `[doc-3]` are far
more effective than a bibliography at the end — a list of sources at the bottom
can be produced without any claim actually coming from them.

**Measured, with faithfulness.** Faithfulness is the proportion of claims in the
answer supported by the retrieved context. Distinguish it clearly from accuracy:
an answer can be *faithful* to a context that is wrong, and it can be *accurate*
while inventing a citation. Both matter, for different reasons — faithfulness is
the property RAG is supposed to deliver, and it is the one you can measure
without a human.

**And put unanswerable cases in the eval set.** A golden set where every question
has an answer cannot detect confident invention at all. Somewhere between 10 and
20% of cases should be unanswerable, and a refusal on those should score as a
pass. Without them you are optimising a system toward always answering, which is
precisely the failure mode.
""",
        examples=[
            example(
                "What the instruction actually has to say",
                """
SYSTEM = '''Answer using ONLY the numbered context below.
Cite the source inline for every claim, e.g. [2].
If the context does not contain the answer, reply exactly:
"The provided context does not contain that information."
Do not use knowledge from outside the context.'''
""",
                note="The exact refusal string matters: it makes refusals mechanically "
                "detectable in evaluation instead of requiring a judge.",
            ),
        ],
        common_mistakes=[
            mistake(
                "No unanswerable cases in the eval set",
                "The suite cannot distinguish a system that knows from one that invents "
                "fluently, so every metric improves while the dangerous behaviour goes "
                "unmeasured.",
                "Make 10–20% of golden cases unanswerable. Score a refusal as a pass.",
                Severity.CRITICAL,
            ),
            mistake(
                "Citations as a trailing source list",
                "A bibliography can be generated without any specific claim deriving from it, "
                "so it provides the appearance of grounding without the substance.",
                "Require inline per-claim citations. Verify that cited spans support the claim.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Shipping a legal or medical assistant where inventing is unacceptable",
        ],
        requires=["rag-why-it-fails"],
        related=["rag-evaluation-metrics"],
        tags=["rag", "grounding", "safety"],
        estimated_minutes=10,
    ),
    ConceptSpec(
        slug="rag-evaluation-metrics",
        title="Evaluating Retrieval and Generation Separately",
        category=E,
        skill_node="rag.evaluation",
        difficulty=7,
        summary=(
            "One end-to-end score tells you the system got worse. Separate retrieval and "
            "generation metrics tell you which half to fix."
        ),
        explanation="""
A single quality score is almost useless for debugging, because it conflates two
independent subsystems. Measure them apart.

**Retrieval metrics** — did the right documents come back?

* **precision@k** — of what you retrieved, how much was relevant. *Falls* as k
  rises, mechanically.
* **recall@k** — of what was relevant, how much you retrieved. *Rises* as k
  rises. Precision and recall move in opposite directions with k, which is why
  reporting one without the other is meaningless.
* **MRR** — the reciprocal rank of the first relevant hit. 1.0 means it was
  first. Good proxy for "did the user see it immediately".
* **nDCG@k** — rewards putting the *best* document first, not merely including
  it. The right metric when ordering matters, which for a context window it does.

**A subtlety that produces wrong numbers.** Retrieved items are *chunks*;
relevance is usually defined at the *document* level. If three chunks from one
relevant document come back, that is one document covered, not three hits. Count
distinct documents for recall — otherwise recall exceeds 1.0, which is a real
bug that ships regularly.

**Generation metrics** — given that context, was the answer good?

* **faithfulness** — fraction of claims supported by the context. The
  hallucination metric.
* **answer relevance** — does it address the question asked?
* **context relevance** — was the retrieved context on-topic at all? This one
  bridges the two halves.

**Reading them together is the diagnosis.** Low precision with high faithfulness
means retrieval is noisy but the model is coping. High precision with low
faithfulness means the model is ignoring good context — genuinely a generation
problem, and rarer than assumed. Both low means start at retrieval, always,
because generation cannot be evaluated on context that was never right.

**Thresholds are a decision, not a discovery.** "Ship if faithfulness ≥ 0.85 and
precision@k ≥ 0.70" is a policy someone has to own. Writing it down before the
experiment is what stops the number being reinterpreted afterwards to justify
whatever happened.
""",
        examples=[
            example(
                "The recall bug that ships",
                """
retrieved = ["doc-a#c1", "doc-a#c2", "doc-a#c3"]   # three chunks, ONE document
relevant = {"doc-a"}

# WRONG: counts chunks -> recall 3.0
recall = sum(1 for c in retrieved if c.split("#")[0] in relevant) / len(relevant)

# RIGHT: counts distinct covered documents -> recall 1.0
covered = {c.split("#")[0] for c in retrieved} & relevant
recall = len(covered) / len(relevant)
""",
            ),
        ],
        common_mistakes=[
            mistake(
                "Reporting precision@k without recall@k",
                "They move in opposite directions as k changes, so either alone can be improved "
                "by changing k while the system gets worse overall.",
                "Always report both, plus the k they were measured at.",
                Severity.HIGH,
            ),
            mistake(
                "Counting chunks as hits when relevance is per-document",
                "Multiple chunks from one relevant document each count, so recall can exceed "
                "1.0 and a configuration looks better than perfect.",
                "Deduplicate to distinct documents before computing recall.",
                Severity.HIGH,
            ),
            mistake(
                "Choosing the ship threshold after seeing the result",
                "The threshold becomes a description of what happened rather than a decision "
                "about what is acceptable.",
                "Write thresholds down before running the experiment.",
                Severity.MEDIUM,
            ),
        ],
        real_world_usage=[
            "Deciding whether a retrieval change is safe to deploy",
            "Telling a stakeholder which half of the system is the problem",
        ],
        requires=["rag-grounding-and-refusal"],
        tags=["rag", "evaluation", "metrics"],
        estimated_minutes=12,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# CHALLENGES
# ═════════════════════════════════════════════════════════════════════════════
CHALLENGES = [
    ChallengeSpec(
        slug="rag-structure-aware-chunking",
        title="Chunk Without Cutting Sentences in Half",
        category=R,
        tier=T.IMPLEMENT,
        prompt="""
Implement `chunk(text, size, overlap)`.

Split `text` into chunks of at most `size` characters, preferring to break at a
**paragraph** boundary (`\\n\\n`), then a **sentence** boundary (`. `), and only
then a **word** boundary. Never cut mid-word unless a single word is longer than
`size`.

Consecutive chunks overlap by up to `overlap` characters, so a fact that lands
near a boundary appears whole in at least one chunk.

Requirements:

* every chunk is at most `size` characters,
* no chunk is empty or only whitespace,
* the chunks, de-overlapped, cover the whole text,
* `overlap` is always less than `size` (raise `ValueError` otherwise — an
  overlap at or above the size makes no forward progress and loops forever).
""",
        starter_code="def chunk(text, size=200, overlap=40):\n    ...\n",
        reference_solution="""
def chunk(text, size=200, overlap=40):
    # An overlap >= size means the next window starts at or before the current
    # one, so the loop never advances. Raising here turns an infinite loop into
    # an immediate, obvious error.
    if overlap >= size:
        raise ValueError(f"overlap ({overlap}) must be smaller than size ({size})")

    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))

        if end < len(text):
            # Prefer the most semantic boundary available inside the window.
            # A chunk ending mid-sentence has an embedding that is partly noise.
            window = text[start:end]
            for separator in ("\\n\\n", ". ", " "):
                cut = window.rfind(separator)
                # Require the break past the halfway mark: a paragraph boundary
                # at character 5 of a 200-char window produces a useless chunk.
                if cut > size // 2:
                    end = start + cut + len(separator)
                    break

        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)

        if end >= len(text):
            break
        start = max(start + 1, end - overlap)

    return chunks
""",
        solution_explanation=(
            "Three details carry the weight. Trying separators in descending semantic order "
            "means a chunk ends where meaning ends. The `cut > size // 2` guard stops a "
            "boundary near the start of the window producing a tiny chunk. And "
            "`max(start + 1, end - overlap)` guarantees forward progress even when the overlap "
            "would otherwise push the next window backwards — which is the infinite loop this "
            "kind of function is famous for."
        ),
        tests=[
            script(
                "respects the size limit",
                """
text = "word " * 200
for c in chunk(text, size=100, overlap=20):
    assert len(c) <= 100, f"chunk of {len(c)} exceeds size 100"
""",
                points=2.0,
            ),
            script(
                "prefers sentence boundaries",
                """
text = "First sentence here. Second sentence here. Third sentence here."
chunks = chunk(text, size=45, overlap=0)
assert len(chunks) >= 2
assert chunks[0].endswith("."), f"cut mid-sentence: {chunks[0]!r}"
""",
                points=2.0,
            ),
            script(
                "no empty or whitespace-only chunks",
                """
text = "a\\n\\n\\n\\nb\\n\\n\\n\\nc"
for c in chunk(text, size=10, overlap=2):
    assert c.strip(), f"empty chunk: {c!r}"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "covers the whole text",
                """
text = "The quick brown fox jumps over the lazy dog. " * 6
joined = "".join(chunk(text, size=80, overlap=0))
assert "lazy dog" in joined
assert len(joined) >= len(text.strip()) - 10, "content was lost"
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "an overlap at or above size is rejected, not looped on",
                """
try:
    chunk("some text here", size=50, overlap=50)
except ValueError:
    pass
else:
    raise AssertionError("overlap >= size must raise, not spin")
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "terminates on a word longer than the chunk size",
                """
out = chunk("x" * 500, size=100, overlap=20)
assert out, "returned nothing"
assert all(len(c) <= 100 for c in out)
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "empty input gives an empty list",
                """
assert chunk("", size=100, overlap=10) == []
assert chunk("   \\n\\n  ", size=100, overlap=10) == []
""",
                hidden=True,
            ),
        ],
        concepts=["rag-chunking-tradeoffs"],
        hints=[
            "Take a window of `size` characters, then search backwards inside it for a boundary.",
            "Try separators in order of how semantic they are: paragraph, sentence, word.",
            "What happens when the boundary you find is at position 3 of a 200-character window?",
            "What guarantees `start` always increases? Test with a single 500-character word.",
        ],
        explanation_prompts=[
            point(
                "Explains why boundaries matter for the embedding",
                "embedding",
                "meaning",
                "mid-sentence",
                "noise",
                weight=3,
            ),
            point(
                "Names the cost of overlap",
                "duplicate",
                "storage",
                "top-k",
                "crowd",
                weight=2,
            ),
            point(
                "Identifies the infinite-loop guard",
                "progress",
                "infinite",
                "advance",
                "loop",
                weight=2.5,
            ),
        ],
        expected_complexity="O(n)",
        par_seconds=600,
    ),
    ChallengeSpec(
        slug="rag-reciprocal-rank-fusion",
        title="Fuse Two Rankings Without Comparing Scores",
        category=R,
        tier=T.IMPLEMENT,
        prompt="""
Implement `rrf(rankings, k=60)`.

`rankings` is a list of ranked lists of document ids — one per retriever, best
first. Return a single ranked list fusing them by Reciprocal Rank Fusion:

    score(d) = Σ over retrievers  1 / (k + rank(d) + 1)

using 0-based `rank`. Documents absent from a retriever's list contribute
nothing from it.

Ties must break **deterministically**: equal scores are ordered by first
appearance across the input lists, scanned in order. A non-deterministic
retriever makes an eval suite unreproducible, which defeats its purpose.

Note what you are *not* doing: no score normalisation. That is the whole idea —
ranks are comparable across retrievers and raw scores are not.
""",
        starter_code="def rrf(rankings, k=60):\n    ...\n",
        reference_solution="""
def rrf(rankings, k=60):
    scores = {}
    first_seen = {}
    order = 0

    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            # Only ranks enter the formula. A cosine similarity of 0.82 and a
            # BM25 score of 14.3 are not comparable quantities; rank 0 and
            # rank 0 always are.
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            if doc_id not in first_seen:
                first_seen[doc_id] = order
                order += 1

    # Sorting on (-score, first_seen) makes ties deterministic. Without the
    # tiebreak, dict iteration order decides, and an eval suite that reorders
    # between runs cannot detect a regression.
    return sorted(scores, key=lambda d: (-scores[d], first_seen[d]))
""",
        solution_explanation=(
            "RRF's strength is that it never touches raw scores, so it needs no per-corpus "
            "normalisation and transfers between domains. The explicit tiebreak matters more "
            "than it looks: retrieval results feed an eval suite, and a suite whose output "
            "reorders between identical runs cannot distinguish a regression from noise."
        ),
        tests=[
            script(
                "a document ranked first by both wins",
                """
out = rrf([["a", "b", "c"], ["a", "c", "b"]])
assert out[0] == "a", out
""",
                points=2.0,
            ),
            script(
                "a document found by only one retriever still places",
                """
out = rrf([["a", "b"], ["c"]])
assert set(out) == {"a", "b", "c"}
assert out.index("c") < out.index("b"), f"rank-0 in one list should beat rank-1: {out}"
""",
                points=2.0,
            ),
            script(
                "no score normalisation is needed - ranks only",
                """
# Identical rankings from retrievers with wildly different score scales must
# fuse identically, because only the ranks are used.
assert rrf([["x", "y"], ["x", "y"]]) == ["x", "y"]
""",
                hidden=True,
            ),
            script(
                "ties break deterministically by first appearance",
                """
first = rrf([["a", "b"], ["b", "a"]])
for _ in range(25):
    assert rrf([["a", "b"], ["b", "a"]]) == first, "output is not deterministic"
assert first == ["a", "b"], f"expected first-appearance tiebreak, got {first}"
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "handles empty rankings",
                """
assert rrf([]) == []
assert rrf([[], []]) == []
assert rrf([[], ["a"]]) == ["a"]
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "k damps the advantage of the top rank",
                """
# With a large k the 1/(k+rank) curve flattens, so two rank-0 hits from
# different retrievers matter more than one rank-0 hit.
out = rrf([["a", "b"], ["b", "c"]], k=60)
assert out[0] == "b", f"b appears in both lists and should win: {out}"
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["rag-hybrid-retrieval"],
        hints=[
            "Accumulate a score per document across all the lists, then sort.",
            "`enumerate` gives you the rank. Remember the formula uses rank + 1.",
            "What decides the order when two documents have exactly the same score?",
        ],
        explanation_prompts=[
            point(
                "Explains why ranks rather than raw scores",
                "not comparable",
                "different scale",
                "normalis",
                "rank",
                weight=3,
            ),
            point(
                "Says what k controls",
                "damp",
                "flatten",
                "top rank",
                "constant",
                weight=2,
            ),
            point(
                "Justifies the deterministic tiebreak",
                "determin",
                "reproduc",
                "eval",
                "same result",
                weight=2,
                dimension="production_awareness",
            ),
        ],
        expected_complexity="O(n log n)",
        par_seconds=420,
    ),
    ChallengeSpec(
        slug="rag-fix-recall-metric",
        title="The Recall Above 1.0",
        category=E,
        tier=T.DEBUG,
        prompt="""
The evaluation dashboard is reporting `recall@k` values of 2.00 and 3.00. A
proportion cannot exceed 1.0, so a configuration currently looks *better than
perfect* and the ship/hold decision is being made on it.

`recall_at_k(retrieved_chunk_ids, relevant_doc_ids)` receives:

* `retrieved_chunk_ids` — chunk ids of the form `"doc-slug#3"`,
* `relevant_doc_ids` — **document** slugs, no chunk suffix.

Fix it. An empty `relevant_doc_ids` should return 1.0 — there was nothing to
find and nothing was missed, which is the correct score for an unanswerable
question.
""",
        broken_code="""
def recall_at_k(retrieved_chunk_ids, relevant_doc_ids):
    relevant = set(relevant_doc_ids)
    hits = sum(1 for cid in retrieved_chunk_ids if cid.split("#")[0] in relevant)
    return hits / len(relevant)
""",
        starter_code="",
        reference_solution="""
def recall_at_k(retrieved_chunk_ids, relevant_doc_ids):
    relevant = set(relevant_doc_ids)
    # Nothing to find means nothing was missed. This is the right score for an
    # unanswerable eval case, and it also avoids dividing by zero.
    if not relevant:
        return 1.0

    # The bug: retrieved items are CHUNKS but relevance is per DOCUMENT, so
    # three chunks from one relevant document were counted as three hits and
    # recall exceeded 1.0. Recall asks how many distinct relevant documents
    # were covered, never how many chunks came back.
    covered = {cid.split("#")[0] for cid in retrieved_chunk_ids} & relevant
    return len(covered) / len(relevant)
""",
        solution_explanation=(
            "A units mismatch: the numerator counted chunks while the denominator counted "
            "documents. Deduplicating to distinct covered documents makes both sides the same "
            "unit and bounds the result at 1.0 by construction. The empty-relevant case "
            "returning 1.0 is a deliberate choice — an unanswerable question has nothing to "
            "recall, and scoring it 0.0 would penalise the correct behaviour."
        ),
        tests=[
            script(
                "many chunks from one document is still one document covered",
                """
out = recall_at_k(["doc-a#1", "doc-a#2", "doc-a#3"], ["doc-a"])
assert out == 1.0, f"expected 1.0, got {out}"
""",
                points=3.0,
            ),
            script(
                "never exceeds 1.0",
                """
cases = [
    (["d1#1", "d1#2", "d1#3", "d1#4"], ["d1"]),
    (["d1#1", "d2#1", "d1#2"], ["d1", "d2"]),
    (["d1#1"] * 20, ["d1", "d2"]),
]
for retrieved, relevant in cases:
    value = recall_at_k(retrieved, relevant)
    assert 0.0 <= value <= 1.0, f"{value} out of bounds for {relevant}"
""",
                points=3.0,
            ),
            script(
                "partial coverage is reported correctly",
                """
out = recall_at_k(["d1#1", "d1#2"], ["d1", "d2"])
assert abs(out - 0.5) < 1e-9, out
""",
                points=2.0,
            ),
            script(
                "no relevant documents scores 1.0, not a crash",
                """
assert recall_at_k(["d1#1"], []) == 1.0
assert recall_at_k([], []) == 1.0
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "retrieving nothing when something was relevant scores 0.0",
                """
assert recall_at_k([], ["d1"]) == 0.0
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "irrelevant documents do not count",
                """
out = recall_at_k(["junk#1", "junk#2", "d1#1"], ["d1"])
assert out == 1.0, out
out = recall_at_k(["junk#1", "junk#2"], ["d1"])
assert out == 0.0, out
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["rag-evaluation-metrics"],
        hints=[
            "What unit is the numerator counting? What unit is the denominator?",
            "If three chunks come from one relevant document, how many documents were covered?",
            "What should an unanswerable question — no relevant documents — score?",
        ],
        explanation_prompts=[
            point(
                "Names the chunk-versus-document unit mismatch",
                "chunk",
                "document",
                "unit",
                "distinct",
                weight=3,
            ),
            point(
                "Explains why the bound is now structural",
                "subset",
                "cannot exceed",
                "bounded",
                "intersect",
                weight=2,
            ),
            point(
                "Defends 1.0 for the empty-relevant case",
                "nothing to find",
                "unanswerable",
                "refus",
                "divide by zero",
                weight=2,
                dimension="depth",
            ),
        ],
        par_seconds=420,
    ),
    ChallengeSpec(
        slug="rag-faithfulness-check",
        title="Detect the Unsupported Claim",
        category=E,
        tier=T.PRODUCTION,
        prompt="""
Implement `unsupported_claims(answer, context_chunks)`.

Split the answer into sentences (on `. `, `! `, `? ` and the end of the string)
and return the sentences that are **not** supported by any context chunk, where
"supported" means: at least **60%** of the sentence's content words appear
somewhere in that chunk.

* Content words: lowercase alphanumeric tokens of 4 or more characters. Shorter
  words are mostly function words and match everything.
* A sentence with no content words counts as supported — there is nothing to
  check, and flagging "Yes." as a hallucination is noise.
* A refusal — an answer containing "does not contain" — has nothing to verify
  and returns an empty list.

This is the deterministic backstop that runs on every eval case, before any
LLM-as-judge. It is crude, it is free, and it catches the confident inventions
that matter most.
""",
        starter_code=("def unsupported_claims(answer, context_chunks):\n    ...\n"),
        reference_solution="""
import re


def _content_words(text):
    # 4+ characters drops the function words ("the", "is", "a") that appear in
    # every chunk and would make every sentence look supported.
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


def unsupported_claims(answer, context_chunks):
    # A refusal makes no claims, so there is nothing to verify. Scoring it as
    # unfaithful would penalise the single most important correct behaviour a
    # RAG system has.
    if "does not contain" in answer.lower():
        return []

    chunk_words = [_content_words(c) for c in context_chunks]
    unsupported = []

    for sentence in re.split(r"(?<=[.!?])\\s+", answer):
        sentence = sentence.strip()
        if not sentence:
            continue
        words = _content_words(sentence)
        if not words:
            # "Yes." has nothing to check. Flagging it is noise, and noise in a
            # faithfulness metric is what makes people stop reading it.
            continue
        if not any(len(words & chunk) / len(words) >= 0.6 for chunk in chunk_words):
            unsupported.append(sentence)

    return unsupported
""",
        solution_explanation=(
            "A lexical overlap heuristic, and its limits should be stated plainly: it will miss "
            "a paraphrased invention and will flag a correct answer written in different words. "
            "It earns its place by being free, deterministic and running on every case — which "
            "means it catches the fabricated specifics (numbers, names, product terms) that are "
            "the most damaging kind of hallucination. An LLM judge runs on top of it, not "
            "instead of it, because a judge that is itself a model cannot be the only check."
        ),
        tests=[
            script(
                "a grounded answer has no unsupported claims",
                """
ctx = ["The password reset link expires after 15 minutes for security reasons."]
out = unsupported_claims("The password reset link expires after 15 minutes.", ctx)
assert out == [], out
""",
                points=2.0,
            ),
            script(
                "an invented sentence is caught",
                """
ctx = ["The password reset link expires after 15 minutes."]
answer = "The link expires after 15 minutes. Premium accounts receive unlimited quota."
out = unsupported_claims(answer, ctx)
assert len(out) == 1, out
assert "Premium" in out[0], out
""",
                points=3.0,
            ),
            script(
                "a refusal is not a hallucination",
                """
out = unsupported_claims("The provided context does not contain that information.", [])
assert out == [], out
""",
                hidden=True,
                points=3.0,
            ),
            script(
                "a sentence with no content words is not flagged",
                """
assert unsupported_claims("Yes.", ["anything at all"]) == []
assert unsupported_claims("No. Yes.", []) == []
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "support may come from any chunk, not only the first",
                """
ctx = ["Unrelated content about billing.", "Timeouts default to thirty seconds."]
out = unsupported_claims("Timeouts default to thirty seconds.", ctx)
assert out == [], out
""",
                hidden=True,
                points=2.0,
            ),
            script(
                "everything is unsupported when there is no context at all",
                """
out = unsupported_claims("The service runs on port 8080.", [])
assert len(out) == 1, out
""",
                hidden=True,
                points=2.0,
            ),
        ],
        concepts=["rag-grounding-and-refusal", "rag-evaluation-metrics"],
        hints=[
            "Why drop short words? Consider how often 'the' appears in any chunk.",
            "A sentence is supported if ANY single chunk covers it — not the chunks combined.",
            "What should a refusal score? What behaviour are you rewarding either way?",
        ],
        explanation_prompts=[
            point(
                "States the limits of lexical overlap",
                "paraphrase",
                "heuristic",
                "false positive",
                "crude",
                weight=3,
                dimension="tradeoff_awareness",
            ),
            point(
                "Explains why a refusal must not be penalised",
                "refus",
                "correct behaviour",
                "nothing to verify",
                weight=2.5,
            ),
            point(
                "Positions it alongside rather than instead of an LLM judge",
                "judge",
                "on top",
                "backstop",
                "cheap",
                weight=2,
                dimension="architecture_thinking",
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
        slug="q-rag-hallucination-triage",
        kind=Q.DEBUGGING,
        category=R,
        tier=T.DEBUG,
        level=L.MID,
        prompt=(
            "A user reports the support bot invented a refund policy that does not exist. "
            "What do you check first, and in what order?"
        ),
        concepts=["rag-why-it-fails"],
        expected_answer=(
            "Walk the pipeline: is the fact in the corpus, in a chunk, retrieved, in the "
            "assembled context — and only then look at the prompt."
        ),
        ideal_senior_answer=(
            "I walk the ladder from cheapest to most expensive, because four of the five steps "
            "are just printing things.\n\n"
            "First: is the real policy in the corpus at all? Thirty seconds with grep. If it is "
            "not there, retrieval is working correctly and the bug is that the system answered "
            "instead of refusing — a grounding problem, not a retrieval one.\n\n"
            "Second: is it in any single chunk? A fact split across a boundary exists in the "
            "corpus and in no retrievable unit. I look at the chunk text, not the chunk count.\n\n"
            "Third: was it retrieved, and at what rank? If it is at rank 8 with k=4 that is a "
            "ranking problem — rerank or go hybrid. If it is not in the top 50, the embedding is "
            "not capturing the query, which is harder.\n\n"
            "Fourth: did it survive context assembly? Truncation drops the tail silently.\n\n"
            "Only then the prompt. Generation is genuinely at fault less often than people "
            "assume, and prompt work is the slowest, least certain fix available — so going "
            "there first means potentially days spent on a chunking bug.\n\n"
            "Separately, I would add this question to the eval set as a case, so whatever fixes "
            "it stays fixed."
        ),
        common_wrong_answer=(
            "Starting with the prompt, or reaching for a bigger model. Neither can put a fact "
            "into context that was never retrieved."
        ),
        rubric=[
            point("Checks the corpus first", "corpus", "grep", "is it there", "exists", weight=3),
            point("Inspects chunk boundaries", "chunk", "boundary", "split", weight=2.5),
            point(
                "Checks retrieval rank and scores",
                "rank",
                "retriev",
                "top-k",
                "score",
                weight=2.5,
            ),
            point(
                "Checks context assembly and truncation",
                "truncat",
                "context window",
                "assembl",
                "dropped",
                weight=2,
                dimension="depth",
            ),
            point(
                "Leaves the prompt until last and says why",
                "last",
                "prompt",
                "expensive",
                "slow",
                weight=2,
                dimension="tradeoff_awareness",
            ),
            point(
                "Adds the case to the eval set",
                "eval",
                "golden",
                "regression",
                "test case",
                weight=1.5,
                dimension="production_awareness",
            ),
        ],
        followups=[
            "The fact is not in the corpus. Now what?",
            "How would you prove the fix worked?",
        ],
        tags=["rag", "debugging", "interview"],
        par_seconds=360,
    ),
    QuestionSpec(
        slug="q-rag-precision-recall-k",
        kind=Q.MCQ,
        category=E,
        tier=T.UNDERSTAND,
        level=L.MID,
        prompt="You increase `top_k` from 3 to 10. What happens to precision@k and recall@k?",
        concepts=["rag-evaluation-metrics"],
        options=[
            opt(
                "a",
                "Precision falls or stays equal; recall rises or stays equal",
                correct=True,
                why="Mechanically: adding more retrieved items can only add relevant ones "
                "(recall cannot fall) while the denominator of precision grows regardless. "
                "This is why reporting one without the other is meaningless — you can always "
                "improve either by changing k.",
            ),
            opt(
                "b",
                "Both rise — more context is strictly better",
                why="Precision cannot rise when the denominator grows and the numerator is bounded.",
            ),
            opt("c", "Both fall", why="Recall is monotonically non-decreasing in k."),
            opt(
                "d",
                "Neither changes; k affects only latency",
                why="Both are defined in terms of k.",
            ),
        ],
        expected_answer="Precision down, recall up.",
        ideal_senior_answer=(
            "Precision falls or holds; recall rises or holds. They move in opposite directions "
            "in k by construction, which is exactly why a team reporting only precision@k can "
            "'improve' it by lowering k while making the system worse. I always report both "
            "with the k they were measured at, and pick k by what the generation step actually "
            "needs — more context is not free, it dilutes attention and costs tokens."
        ),
        rubric=[point("Precision down, recall up", "precision", "recall", weight=3)],
        followups=["So how do you choose k?", "What does nDCG add over these two?"],
        tags=["rag", "metrics"],
        par_seconds=120,
    ),
    QuestionSpec(
        slug="q-rag-explain-hybrid",
        kind=Q.EXPLAIN,
        category=R,
        tier=T.EXPLAIN,
        level=L.SENIOR,
        prompt=(
            "Explain hybrid retrieval. Why fuse on ranks rather than normalising scores, and "
            "when is the extra complexity not worth it?"
        ),
        concepts=["rag-hybrid-retrieval"],
        expected_answer=(
            "Run dense and keyword retrieval together and fuse with RRF, which uses ranks "
            "because scores from different retrievers are not comparable."
        ),
        ideal_senior_answer=(
            "Dense retrieval finds text that means something similar; keyword retrieval finds "
            "text containing the same tokens. Those fail on opposite queries. An error code "
            "like `ERR_CONN_4021` is semantically almost empty, so the embedding places it "
            "arbitrarily and the right chunk may not be in the top 50 — BM25 finds it instantly. "
            "Conversely 'how do I stop the service dying under load' shares no words with a "
            "document titled 'Configuring OOM thresholds', and dense handles that easily.\n\n"
            "On fusion: cosine similarity and BM25 are not the same kind of quantity. Cosine is "
            "bounded in [-1, 1] with a corpus-dependent distribution; BM25 is unbounded and "
            "scales with term rarity and document length. Normalising them into a weighted sum "
            "means choosing weights that need retuning per corpus and silently stop being right "
            "as the corpus grows. RRF sidesteps it entirely by using only ranks — rank 0 means "
            "the same thing from either retriever — and it has one parameter, k, which damps how "
            "much the top rank dominates.\n\n"
            "When it is not worth it: hybrid roughly doubles retrieval latency and adds a "
            "keyword index to keep in sync with the vector store, which is real operational "
            "cost. On a prose-only corpus with no identifiers people search literally, the gain "
            "is often within noise. I would run the eval set with and without and adopt it on "
            "the measured difference, not because it is best practice."
        ),
        common_wrong_answer=(
            "'Hybrid is better, always use it.' That skips the cost and skips the reason, which "
            "means it cannot be applied to decide anything."
        ),
        rubric=[
            point(
                "Explains what each retriever is good at",
                "semantic",
                "keyword",
                "exact",
                "bm25",
                weight=2.5,
            ),
            point(
                "Gives a concrete case where dense fails",
                "error code",
                "identifier",
                "exact",
                "sku",
                "version",
                weight=2.5,
                dimension="practical_experience",
            ),
            point(
                "Explains rank fusion over score normalisation",
                "not comparable",
                "different scale",
                "rank",
                "rrf",
                weight=3,
                dimension="depth",
            ),
            point(
                "Names the operational cost",
                "latency",
                "index",
                "sync",
                "complexity",
                weight=2,
                dimension="tradeoff_awareness",
            ),
            point(
                "Requires measurement before adopting",
                "measure",
                "eval",
                "a/b",
                "evidence",
                weight=2,
                dimension="production_awareness",
            ),
        ],
        followups=["What does k control in RRF?", "How would you keep the two indexes in sync?"],
        tags=["rag", "retrieval", "interview"],
        par_seconds=420,
    ),
    QuestionSpec(
        slug="q-rag-reranking-limit",
        kind=Q.MCQ,
        category=R,
        tier=T.DEBUG,
        level=L.SENIOR,
        prompt=(
            "Recall@10 is 0.45 — the right documents often are not retrieved at all. A "
            "teammate proposes adding a cross-encoder reranker. Will it help?"
        ),
        concepts=["rag-reranking"],
        options=[
            opt(
                "a",
                "No — reranking reorders the candidate set and cannot add documents that were never retrieved",
                correct=True,
                why="Reranking improves ordering, never recall. With recall at 0.45 the right "
                "document is absent from the candidates over half the time, and no reordering "
                "reaches it. Worse, it will make the wrong answers better-ordered and so hide "
                "the real problem.",
            ),
            opt(
                "b",
                "Yes — cross-encoders are more accurate than bi-encoders",
                why="More accurate at ranking what they are given. They are never given the missing document.",
            ),
            opt(
                "c",
                "Yes, if the reranker sees the full corpus",
                why="A cross-encoder scoring the full corpus per query is computationally "
                "infeasible — that is the entire reason for the two-stage design.",
            ),
            opt(
                "d",
                "Only if you also raise k",
                why="Raising k might help recall, but that is the fix — not the reranker.",
            ),
        ],
        expected_answer="No. Reranking improves ordering, not recall.",
        ideal_senior_answer=(
            "No. Reranking operates on the candidate set, so a document that never made the "
            "candidates cannot be promoted into the top 5 — recall is unchanged by "
            "construction. With recall@10 at 0.45 the first stage is the problem, and I would "
            "look at chunking, hybrid retrieval and the embedding model in that order.\n\n"
            "There is a real hazard in adding it anyway: it improves the ordering of the wrong "
            "documents, so the answers look more confident and the underlying recall problem "
            "becomes harder to see. Once recall is healthy — retrieve 50 candidates rather than "
            "10 — a reranker is exactly the right next step."
        ),
        rubric=[
            point("Reranking does not affect recall", "recall", "reorder", "candidate", weight=3)
        ],
        followups=[
            "What would you do instead?",
            "How would you tell whether reranking is earning its latency?",
        ],
        tags=["rag", "reranking"],
        par_seconds=180,
    ),
    QuestionSpec(
        slug="q-rag-golden-set-design",
        kind=Q.DESIGN,
        category=E,
        tier=T.PRINCIPAL_ARCHITECTURE,
        level=L.STAFF,
        prompt=(
            "Design the evaluation strategy for a RAG system that answers regulatory compliance "
            "questions, where a confidently wrong answer carries legal exposure. What do you "
            "measure, what gates a deploy, and what do you do about the things you cannot "
            "measure automatically?"
        ),
        concepts=["rag-evaluation-metrics", "rag-grounding-and-refusal"],
        expected_answer=(
            "Separate retrieval and generation metrics, a golden set with unanswerable cases, "
            "explicit pre-registered thresholds, and human review for the tail."
        ),
        ideal_senior_answer=(
            "The domain changes the whole shape of the answer: in compliance, a confident wrong "
            "answer is far worse than a refusal, so the evaluation has to be asymmetric in the "
            "same direction.\n\n"
            "**The golden set.** Built with a compliance specialist, not by engineers, because "
            "the hard part is knowing what correct is. Every case carries the question, the "
            "relevant source documents, and the expected answer. Critically, 15–20% of cases "
            "are unanswerable — questions the corpus genuinely does not cover — and a refusal "
            "on those scores as a pass. A suite where everything has an answer cannot detect "
            "invention at all, and invention is the failure that matters here. I would also "
            "include adversarial cases: questions whose answer changed between regulation "
            "versions, where the wrong-but-plausible answer is in the corpus too.\n\n"
            "**Metrics, split by subsystem.** Retrieval: precision@k, recall@k and nDCG@k, so a "
            "regression can be attributed. Generation: faithfulness first, then answer "
            "relevance and citation accuracy — every claim must cite a source, and the cited "
            "span must actually support it. That last check catches the failure where the model "
            "cites a real document for a claim the document does not make, which reads as "
            "well-grounded and is not.\n\n"
            "**The gate, pre-registered.** Faithfulness ≥ 0.95 and zero unsupported claims on "
            "any case — in this domain that is a hard floor, not an average. Recall@k ≥ 0.90. "
            "Refusal precision ≥ 0.95 on the unanswerable set. And no regression over 2% on any "
            "metric against the current production baseline. Written down before the "
            "experiment, because a threshold chosen afterwards is a description rather than a "
            "decision.\n\n"
            "**What automation cannot cover.** A lexical faithfulness check misses a paraphrased "
            "invention; an LLM judge inherits the generator's blind spots and correlates with "
            "its errors, so it cannot be the only check. So: sample 50 production answers weekly "
            "for specialist review, and track the disagreement rate between the judge and the "
            "human — when that drifts, the automated metric has stopped meaning what it meant. "
            "Log every refusal too, since a rising refusal rate is either corpus drift or a "
            "retrieval regression, and both are worth knowing early.\n\n"
            "**And the honest part**: I would put the residual risk in writing. The eval set "
            "covers what we thought to ask. For a legal-exposure system the answer has to "
            "include a human in the loop for anything the system is not highly confident about "
            "— evaluation reduces risk, it does not remove it, and saying so is part of the "
            "design."
        ),
        common_wrong_answer=(
            "A single 'accuracy' number and an LLM judge. That cannot attribute a regression to "
            "retrieval or generation, and using a model to grade a model in a legal context has "
            "correlated failure modes nobody has bounded."
        ),
        rubric=[
            point(
                "Separates retrieval and generation metrics",
                "retrieval",
                "generation",
                "separate",
                "attribut",
                weight=3,
            ),
            point(
                "Includes unanswerable cases and scores refusal as a pass",
                "unanswerable",
                "refus",
                "cannot answer",
                weight=3,
            ),
            point(
                "Pre-registers explicit thresholds",
                "threshold",
                "before",
                "pre-regist",
                "written down",
                weight=2.5,
                dimension="production_awareness",
            ),
            point(
                "Requires citation accuracy, not just presence",
                "citation",
                "cited span",
                "supports",
                "verify",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "Notes the LLM judge shares the generator's blind spots",
                "judge",
                "correlat",
                "blind spot",
                "same model",
                weight=2.5,
                dimension="depth",
            ),
            point(
                "Plans sampled human review and drift tracking",
                "human",
                "sample",
                "review",
                "drift",
                weight=2.5,
                dimension="architecture_thinking",
            ),
            point(
                "States the residual risk honestly",
                "residual",
                "does not remove",
                "risk",
                "cannot guarantee",
                weight=2,
                dimension="tradeoff_awareness",
            ),
        ],
        followups=[
            "How large does the golden set need to be to detect a 2% regression?",
            "What would you do when the judge and the human disagree?",
            "How do you keep the golden set current as regulations change?",
        ],
        tags=["rag", "evaluation", "interview", "staff"],
        par_seconds=720,
    ),
    QuestionSpec(
        slug="q-rag-chunk-size-choice",
        kind=Q.TRADEOFF,
        category=R,
        tier=T.DESIGN,
        level=L.SENIOR,
        prompt=(
            "Your corpus is a mix of API reference pages (short, independent sections) and "
            "long architecture decision records where meaning accumulates across paragraphs. "
            "One chunk_size, or two pipelines? Defend your choice."
        ),
        concepts=["rag-chunking-tradeoffs"],
        expected_answer=(
            "The two document types want different chunk sizes; the decision is whether the "
            "gain justifies maintaining two paths."
        ),
        ideal_senior_answer=(
            "These genuinely want different sizes, and the reason is the semantic-unit "
            "question. An API reference section is self-contained — 'returns 404 when the "
            "resource does not exist' means something alone, so small chunks retrieve it "
            "precisely. An ADR builds an argument across paragraphs; a 200-character slice of "
            "'we chose Postgres because' is worse than useless, because it retrieves well and "
            "informs nothing.\n\n"
            "So on quality, two configurations win. The question is whether they win enough.\n\n"
            "Against: two pipelines means two ingestion paths, two sets of parameters to tune, "
            "a routing decision at ingest that will be wrong for documents that do not fit "
            "either category, and a much harder debugging story — 'which pipeline produced this "
            "chunk' becomes a question you have to answer at 2am.\n\n"
            "For: the alternative is one compromise size that is wrong for both, and on an ADR "
            "corpus that shows up as answers that cite the right document and miss the "
            "reasoning.\n\n"
            "What I would actually do: start with structure-aware splitting and a single size, "
            "because respecting section boundaries already adapts somewhat to document shape — "
            "an API section ends where it ends. Measure per document type on the eval set. If "
            "the ADR cases are materially worse and I can attribute that to chunk size rather "
            "than retrieval, then split the pipeline, and store the chunking parameters in the "
            "chunk metadata so a later debugging session can see which path produced what.\n\n"
            "The general principle: pay the complexity when the measurement demands it, not "
            "when the argument sounds good."
        ),
        common_wrong_answer=(
            "Picking a number like 512 because it is common, with no reference to what the "
            "documents actually are."
        ),
        rubric=[
            point(
                "Identifies the semantic-unit difference between the types",
                "self-contained",
                "accumulat",
                "independent",
                "across paragraph",
                weight=3,
            ),
            point(
                "Names the complexity cost of two pipelines",
                "two pipeline",
                "maintain",
                "routing",
                "complexity",
                weight=2.5,
                dimension="tradeoff_awareness",
            ),
            point(
                "Proposes structure-aware splitting as the first move",
                "structure",
                "section",
                "boundary",
                "paragraph",
                weight=2.5,
            ),
            point(
                "Decides on measurement, per document type",
                "measure",
                "eval",
                "per type",
                "attribut",
                weight=2.5,
                dimension="production_awareness",
            ),
            point(
                "Suggests recording chunking metadata",
                "metadata",
                "which pipeline",
                "provenance",
                weight=1.5,
                dimension="architecture_thinking",
            ),
        ],
        followups=[
            "How would you measure per document type?",
            "What would make you reverse the decision later?",
        ],
        tags=["rag", "chunking", "tradeoff"],
        par_seconds=480,
    ),
]

# ═════════════════════════════════════════════════════════════════════════════
# MISSIONS
# ═════════════════════════════════════════════════════════════════════════════
MISSIONS = [
    MissionSpec(
        slug="mission-rag-hallucination",
        title="Incident: The Refund Policy That Does Not Exist",
        kind="incident",
        category=R,
        building="rag_tower",
        tier=T.DEBUG,
        briefing="""
**14:20.** A customer forwards a screenshot. The support bot told them refunds
are available for 90 days. The actual policy is 30 days, and the customer is
quoting the bot back at an agent.

Support has paused the bot. Legal has been notified. You have the trace.
""",
        objective="Find which stage failed, fix it, and add the regression case.",
        artifacts={
            "the_answer": (
                "Refunds are available within 90 days of purchase for all account tiers."
            ),
            "retrieved_chunks": (
                "rank 0  score 0.71  billing-faq#4    'for all account tiers. Contact support '\n"
                "                                    'to begin a refund request.'\n"
                "rank 1  score 0.68  billing-faq#9    'Shipping is refunded separately and may '\n"
                "                                    'take 5 working days.'\n"
                "rank 2  score 0.61  tos-general#2    'These terms may be updated at any time.'"
            ),
            "corpus_grep": (
                "$ grep -rn '30 days' corpus/\n"
                "corpus/billing-faq.md:41: Refunds are available within 30 days of purchase\n"
                "\n"
                "$ grep -rn '90 days' corpus/\n"
                "(no matches)"
            ),
            "chunk_boundaries": (
                "billing-faq#3 ends: '...Refunds are available within 30 days of purchase'\n"
                "billing-faq#4 starts: 'for all account tiers. Contact support to begin...'\n"
                "\n"
                "chunk_size=120  chunk_overlap=0  respect_structure=False"
            ),
            "the_prompt": (
                "Answer the user's question using the context below.\n"
                "Context: {context}\n"
                "Question: {question}"
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="question",
                title="Triage in the right order",
                question="q-rag-hallucination-triage",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Fix the chunking",
                challenge="rag-structure-aware-chunking",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Add the deterministic faithfulness check",
                challenge="rag-faithfulness-check",
            ),
            MissionStepSpec(
                step_type="explanation",
                title="Write the postmortem",
                prompt=(
                    "Two things went wrong here, not one. Name both — the reason the fact was "
                    "unavailable, and the reason the system answered anyway instead of "
                    "refusing. Then say what you are changing for each."
                ),
                config={
                    "rubric": [
                        point(
                            "Identifies the chunk boundary splitting the fact",
                            "boundary",
                            "split",
                            "chunk",
                            "30 days",
                            weight=3,
                        ),
                        point(
                            "Identifies the missing refusal instruction",
                            "refus",
                            "does not contain",
                            "prompt",
                            "instruct",
                            weight=3,
                        ),
                        point(
                            "Notes zero overlap and no structure awareness",
                            "overlap",
                            "structure",
                            "respect",
                            weight=2,
                        ),
                        point(
                            "Adds a regression case to the eval set",
                            "eval",
                            "golden",
                            "regression",
                            "test case",
                            weight=2.5,
                            dimension="production_awareness",
                        ),
                    ]
                },
            ),
            MissionStepSpec(
                step_type="journal",
                title="What you will check first next time",
                prompt="One sentence. The first thing you will do on the next hallucination report.",
                required=False,
            ),
        ],
        concepts=["rag-why-it-fails", "rag-chunking-tradeoffs", "rag-grounding-and-refusal"],
        success_criteria=[
            "Diagnosed as a chunking failure, not a model failure",
            "Also identified the missing refusal instruction",
            "Regression case added to the eval set",
        ],
        debrief="""
The fact was in the corpus. `grep` found it on line 41 of the file the retriever
actually returned a chunk from. What it was not in was any single chunk — "within
30 days of purchase" ended chunk 3 and "for all account tiers" began chunk 4,
with `chunk_overlap=0` and no structure awareness. The retriever did its job
perfectly and returned a chunk containing half a sentence.

But notice the second failure, because it is the one with legal exposure. Given
context that did not contain the answer, the system produced one. The prompt
never told it that refusing was allowed, so it did what next-token prediction
does. Fixing the chunking makes this particular answer right; adding the refusal
instruction and an unanswerable case to the eval set is what makes the *class*
of failure detectable.

Two bugs. One of them would have been invisible if you had only fixed the other.
""",
        required_level=12,
        estimated_minutes=35,
        par_seconds=2100,
    ),
    MissionSpec(
        slug="mission-rag-tuning-bench",
        title="Earn the Right to Ship a Retrieval Change",
        kind="rag_lab",
        category=E,
        building="rag_tower",
        tier=T.PRODUCTION,
        briefing="""
You have a retrieval change you believe is better. Your team's rule is that
"believe" is not sufficient — a change ships when the evidence says so, against
thresholds written down beforehand.

Open the RAG Tuning Bench alongside this mission. Run the golden set at k=1,
at k=8, and with hybrid retrieval plus reranking, and read what the numbers
actually say rather than what you hoped.
""",
        objective="Produce a defensible ship/hold/rollback recommendation with its reasoning.",
        artifacts={
            "lab_link": (
                "The Evaluation Lab runs the golden set against a configuration and returns a "
                "verdict with reasons. Run at least three configurations before deciding."
            ),
            "team_thresholds": (
                "ship     faithfulness >= 0.85 AND precision@k >= 0.70 AND no metric regressed >5%\n"
                "hold     any metric between its floor and 5% below baseline\n"
                "rollback faithfulness < 0.80 OR any unanswerable case answered confidently"
            ),
            "the_trap": (
                "One configuration will score better on precision@k and worse on the "
                "unanswerable case. The thresholds already say what to do about that. The "
                "question is whether you will follow them when the headline number improved."
            ),
        },
        steps=[
            MissionStepSpec(
                step_type="challenge",
                title="Fix the metric before you trust it",
                challenge="rag-fix-recall-metric",
            ),
            MissionStepSpec(
                step_type="question",
                title="Know which way the metrics move",
                question="q-rag-precision-recall-k",
            ),
            MissionStepSpec(
                step_type="challenge",
                title="Implement rank fusion",
                challenge="rag-reciprocal-rank-fusion",
            ),
            MissionStepSpec(
                step_type="review",
                title="Make the call",
                prompt=(
                    "Write the ship/hold/rollback recommendation. State the configuration, the "
                    "metrics, which threshold decided it, and — if the headline metric improved "
                    "while a safety metric regressed — say explicitly why that is still not a "
                    "ship."
                ),
                config={
                    "rubric": [
                        point(
                            "States a clear verdict with the deciding threshold",
                            "ship",
                            "hold",
                            "rollback",
                            "threshold",
                            weight=3,
                        ),
                        point(
                            "Reports precision and recall together with k",
                            "precision",
                            "recall",
                            "k=",
                            weight=2.5,
                        ),
                        point(
                            "Treats the unanswerable case as a gate, not an average",
                            "unanswerable",
                            "refus",
                            "hard floor",
                            "gate",
                            weight=3,
                            dimension="production_awareness",
                        ),
                        point(
                            "Refuses to reinterpret the threshold after the fact",
                            "pre-regist",
                            "written down",
                            "beforehand",
                            "not going to",
                            weight=2.5,
                            dimension="tradeoff_awareness",
                        ),
                    ]
                },
            ),
        ],
        concepts=["rag-evaluation-metrics", "rag-hybrid-retrieval", "rag-reranking"],
        success_criteria=[
            "Recall metric corrected before being used to decide anything",
            "Verdict follows the pre-registered thresholds",
            "The unanswerable case is treated as a gate rather than averaged away",
        ],
        debrief="""
The recall bug came first for a reason. A metric that can exceed 1.0 was making
one configuration look better than perfect, and every decision built on it was
worthless. Fixing the instrument before reading it is not pedantry — it is the
difference between evidence and confident noise.

The real test was the last step. A configuration that improves precision@k and
starts answering the unanswerable case has got *worse* in the way that matters,
and the thresholds said so in advance. The entire value of pre-registering them
is that they are harder to reinterpret once you can see the result you wanted.
""",
        required_level=15,
        estimated_minutes=40,
        par_seconds=2400,
    ),
]

PACK = ContentPack(
    name="rag_tower",
    concepts=CONCEPTS,
    challenges=CHALLENGES,
    questions=QUESTIONS,
    missions=MISSIONS,
)
