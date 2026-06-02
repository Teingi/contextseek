# Retrieval Model

ContextSeek's retrieval is a multi-stage pipeline: **recall** → **rerank** → **layer selection**. Understanding each stage helps you tune quality and control token costs.

---

## Content tiers: L0 / L1 / L2

Every `ContextItem` holds content at up to three levels of granularity:

| Tier | Field | Size | Role |
|------|-------|------|------|
| **L0** | `content` | Full body | On-demand via `full=True` or `expand()` |
| **L1** | `summary` | ~2k chars | Default surface returned by `retrieve()` |
| **L2** | `abstract` | ~100 chars | Embedding input — feeds the vector index |

**L2 and L1 are generated automatically** on `add()` when a `Summarizer` is configured:

```
add(content)
     │
     ▼
Summarizer ──── abstract (L2) ──▶ Embedder ──▶ index
            └── summary  (L1) ──▶ stored alongside item

retrieve() ──▶ returns L1 by default
expand()   ──▶ upgrades selected hits to L0
```

Without a summarizer, L2 and L1 fields are empty, `retrieve()` returns L0 bodies directly, and a one-time warning is emitted. This is intentional: zero-config dev/test works without API keys; production should enable `SUMMARIZER_PROVIDER=llm`.

---

## Recall routes

Recall is the first stage: collect candidate items before scoring. Three routes can be active simultaneously (controlled by `RETRIEVAL_RECALL_ROUTES`):

| Route | How it works | Best for |
|-------|-------------|----------|
| `phrase` | Exact/near-exact substring match on L2 or L0 | Short, precise queries |
| `terms` | Inverted index on tokenized content | Keyword-heavy queries |
| `vector` | Approximate nearest-neighbor on L2 embeddings | Semantic similarity |

The default is `["phrase", "terms"]` (no embedding required). Add `vector` when you have an embedding model configured:

```env
RETRIEVAL_RECALL_ROUTES=["phrase","terms","vector"]
```

All active routes run in parallel; their candidate sets are merged before reranking.

---

## Reranking

After recall, candidates are scored and ranked. Two modes:

### Heuristic reranker (default)

A weighted sum of several signals:

| Signal | Weight variable | What it measures |
|--------|----------------|------------------|
| Vector similarity | `RETRIEVAL_VECTOR_WEIGHT` (0.7) | Semantic closeness |
| Full-text score | `RETRIEVAL_FTS_WEIGHT` (0.3) | BM25-style keyword match |
| Term overlap | `RETRIEVAL_TERM_WEIGHT` (0.15) | Token co-occurrence |
| Recency | `RETRIEVAL_RECENCY_WEIGHT` (0.05) | How recently written |
| Relevance boost | `RETRIEVAL_FEEDBACK_WEIGHT` (0.20) | Accumulated `feedback()` signal |
| Provenance confidence | `RETRIEVAL_PROVENANCE_WEIGHT` (0.15) | Source trust |
| Link boost | `RETRIEVAL_LINK_BOOST` (0.10) | Has corroborating links |
| Archive penalty | `RETRIEVAL_ARCHIVE_PENALTY` (0.50) | Archived/superseded items |

### LLM reranker

Set `RETRIEVAL_RERANKER_MODE=llm` to pass the top `RETRIEVAL_LLM_RERANK_TOP_N` candidates through an LLM relevance scorer. This is Phase 1 of the LLM rollout and is the highest-value LLM investment for most deployments.

```env
RETRIEVAL_RERANKER_MODE=llm
RETRIEVAL_LLM_RERANK_TOP_N=20
```

---

## Layer selection: summary vs. full

After reranking, `retrieve()` shapes results to control token usage:

```python
# Default: L1 summaries (token-efficient)
response = ctx.retrieve("query", scope="acme/bot", k=10)
for hit in response:
    print(hit.item.summary)     # L1 — ~2k chars per item
    print(hit.layer)            # "summary"

# Upgrade selected hits to L0
interesting = [h for h in response if h.score > 0.7]
full_items = ctx.expand(interesting)

# Full L0 directly (more tokens, skips expand round-trip)
response = ctx.retrieve("query", scope="acme/bot", k=5, full=True)
for hit in response:
    print(hit.item.content)     # L0 — full body
```

**Recommended pattern for agents:**
1. Recall top-k with `retrieve()` (L1, cheap)
2. Filter by `hit.score` or other criteria
3. `expand()` only the 1–3 items that need full context

This keeps most prompt injections at ~2k chars while still providing full context when needed.

---

## Filtering

Narrow the candidate set before scoring:

```python
from contextseek.domain.stages import Stage

# Filter by stage
response = ctx.retrieve("query", scope="acme/bot",
                         stage=Stage.knowledge)

# Filter by tags (ALL tags must match)
response = ctx.retrieve("query", scope="acme/bot",
                         tags=["deploy", "prod"])

# Minimum confidence
response = ctx.retrieve("query", scope="acme/bot",
                         filters={"min_confidence": 0.7})
```

---

## Oversample and rerank pattern

For high-quality results, oversample at recall and let the reranker trim:

```python
# Fetch 30 candidates internally, return top 5 after reranking
response = ctx.retrieve("query", scope="acme/bot", k=5)
# RETRIEVAL_DEFAULT_K=20 controls the initial pool; RETRIEVAL_CANDIDATE_MULTIPLIER=4
# governs how many raw candidates are fed to reranking before trimming to k.
```

---

## Architecture diagram

```
retrieve(query, scope, k)
        │
        ▼
  ┌─────────────────────────────────────┐
  │ Recall (parallel routes)            │
  │  phrase recall  ─┐                  │
  │  terms recall   ─┼─▶ merged pool   │
  │  vector recall  ─┘                  │
  └──────────────────┬──────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────┐
  │ Rerank (heuristic or LLM)            │
  │  score = weighted signals            │
  │  top-k selected                      │
  └──────────────────┬───────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────┐
  │ Layer shape                          │
  │  full=False → swap content → L1 sum  │
  │  full=True  → keep content → L0 body │
  └──────────────────────────────────────┘
```

---

## Next steps

- [Write & retrieve](../guides/write-and-retrieve.md) — full API patterns and filtering
- [Configuration](../getting-started/configuration.md) — retrieval and LLM rollout settings
- [Context model](context-model.md) — ContextItem fields and tiers
