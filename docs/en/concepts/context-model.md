# ContextItem Model

ContextSeek stores all data as `ContextItem` objects — memory snippets, KB articles, traces, and distilled skills are the same type. Stage, provenance, and tags express semantics; the type never changes.

---

## The unified object

```python
from contextseek import ContextSeek
from contextseek.domain.provenance import SourceType
from contextseek.domain.stages import Stage, Stability

ctx = ContextSeek.from_settings()

item = ctx.add(
    "Always run integration tests before production deploy.",
    scope="acme/platform/team-sre",
    source="runbook/deploy-v4",
    source_type=SourceType.document,
    tags=["deploy", "prod"],
    stage=Stage.knowledge,
    stability=Stability.stable,
)
```

## Field reference

**Identity**

| Field | Description |
|-------|-------------|
| `id` | Auto-generated hex ID |
| `scope` | Tenant/project/subject path |
| `content` | L0 payload: string or JSON-serializable dict |

**Retrievable surface**

| Field | Description |
|-------|-------------|
| `abstract` | L2 (~100 chars) — embedding input when summarizer runs |
| `summary` | L1 (~2k chars) — default text returned by `retrieve()` |
| `tags` | Filter dimensions; **all** listed tags must match when filtering |
| `embedding` | Vector of L2 (or L0 fallback) |
| `searchable` | `False` after archive or soft-delete |
| `relevance_boost` | Score multiplier from positive `feedback()` calls |

**Traceable**

| Field | Description |
|-------|-------------|
| `provenance` | Required `Provenance` — source and confidence |
| `links` | List of `Link` objects to other item IDs |

**Evolvable**

| Field | Description |
|-------|-------------|
| `stage` | `raw` → `extracted` → `knowledge` → `skill` |
| `stability` | `ephemeral` / `transient` / `stable` / `permanent` |

**Lifecycle (system-managed)**

| Field | Description |
|-------|-------------|
| `created_at` / `updated_at` | UTC timestamps |
| `access_count` / `last_accessed_at` | Updated when item appears in `retrieve()` hits |
| `superseded_by` | ID of newer item that replaced this one |
| `deleted_at` / `deleted_reason` | Soft-delete metadata |

Access the string body via `item.content_text` (empty when `content` is `None` in summary-only hits).

---

## Provenance

`Provenance` answers *where* data came from and *how much* to trust it.

| `source_type` | Approx. default confidence | Use when |
|---------------|---------------------------|----------|
| `human_input` | 1.0 | User typed or operator approved |
| `document` | 0.8 | Docs, wikis, tickets |
| `trace_extraction` | 0.5 | Parsed agent/run traces |
| `agent_inference` | 0.6 | Model-generated summary |
| `external_api` | 0.5 | Tool/API payload |
| `merge_result` | 0.7 | Evolution merge output |
| `distillation` | 0.7 | Bulk distill |
| `dream_consolidation` | 0.4 | Dream engine — consolidation |
| `dream_divergence` | 0.3 | Dream engine — hypothesis |

**Key `Provenance` fields:**

- `source_id` — stable key (URL, trace ID, filename)
- `confidence` — 0.0–1.0, overridable with `add(..., confidence=0.9)`
- `verified` — human or external validation flag
- `context` — free-text note (e.g. "extracted from incident #4421")

**Hard rule:** items without provenance are not allowed. `add()` always constructs it automatically.

---

## Links and evidence

`Link` objects connect items for audit trails and evolution:

| `LinkType` | Role |
|------------|------|
| `derived_from` | This item was extracted from another |
| `supported_by` | Corroboration |
| `refuted_by` | Contradiction (also created by conflict detector) |
| `supersedes` | Newer version replaces older |
| `merged_from` | Merge provenance |
| `distilled_into` | Points to skill item |
| `related_to` | Loose association |
| `requires` | Prerequisite |
| `synthesized_from` | Dream synthesis |

Example link chain:

```
knowledge: "Run integration tests before deploy"
  provenance.source_type = trace_extraction
  links:
    derived_from → raw trace of failed deploy
    supported_by → official deploy doc item
    supersedes   → outdated checklist item
```

See `upstream()`, `evidence_chain()`, and `chain_confidence()` in [Provenance & audit](../guides/provenance-and-audit.md).

---

## Why one type instead of eight

Earlier agent stacks often define separate types: profile, session, KB, trace, skill, etc. ContextSeek collapses them because:

1. You should not have to choose a type at write time.
2. The same text may start as `raw` and become `knowledge` after evolution.
3. Retrieval, audit, and deletion policies apply uniformly.

Use **`source_type`**, **`tags`**, and **`stage`** to express intent — not different SDK classes.

---

## Next steps

- [Scope & Stage](scope-and-stage.md) — isolation and maturity model
- [Retrieval model](retrieval-model.md) — L0/L1/L2 tiers and search pipeline
- [Write & retrieve](../guides/write-and-retrieve.md) — API patterns
