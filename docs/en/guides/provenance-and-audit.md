# Provenance & audit

Every `ContextItem` carries a `Provenance` record and typed `Link` edges. These let you trace where knowledge came from, measure how confident the system is, and audit every operation.

---

## Tracing item origins

### `upstream(ref, *, scope) → list[ContextItem]`

Breadth-first walk from an item along `derived_from` and `supported_by` links. Returns the starting item followed by all ancestors reachable within the scope.

```python
sources = ctx.upstream(item.ref, scope="acme/bot")
for src in sources:
    print(f"  [{src.stage.value}] {src.provenance.source_id}: {src.content_text[:60]}")
```

Use `upstream()` for quick "where did this come from?" answers without running the full evidence chain analysis.

### `evidence_chain(ref, *, scope, max_depth=10) → EvidenceChain`

Builds the full provenance DAG rooted at an item. Traverses all `Link` edge types (not just derivation), propagates confidence with Noisy-OR, detects contradictions, and identifies the highest-weight critical path.

```python
chain = ctx.evidence_chain(item.ref, scope="acme/bot")

print(f"Overall confidence: {chain.overall_confidence:.2f}")
print(f"Nodes in chain: {len(chain.nodes)}")
print(f"Conflicts: {len(chain.conflicts)}")

# Walk the critical path
for node in chain.critical_path:
    print(f"  {node.item_id} — confidence={node.confidence:.2f}")
```

`EvidenceChain` fields:

| Field | Type | Description |
|---|---|---|
| `nodes` | `list[EvidenceNode]` | All items in the DAG |
| `overall_confidence` | `float` | Propagated root confidence (0.0–1.0) |
| `conflicts` | `list[ConflictReport]` | Contradictions detected in the chain |
| `critical_path` | `list[EvidenceNode]` | Highest-weight path to a leaf |
| `broken_links` | `list[str]` | Link targets that no longer exist |

### `chain_confidence(ref, *, scope) → float`

Lightweight alternative to `evidence_chain()` when only the effective confidence is needed.

```python
conf = ctx.chain_confidence(item.ref, scope="acme/bot")
print(f"Effective confidence: {conf:.2f}")
```

---

## Audit trail

### `tag()` — attach actor metadata

`ctx.tag()` is a context manager that injects actor and request metadata into every `AuditRecord` emitted inside the block. Requires `OBSERVABILITY_AUDIT_ENABLED=true`.

```python
with ctx.tag(
    actor={"user": "alice", "role": "admin"},
    request={"request_id": "req-9f2a", "endpoint": "/review"},
    reason="weekly knowledge review",
):
    ctx.retrieve("deployment runbook", scope="acme/sre")
    ctx.add("New rollback step", scope="acme/sre", source="runbook/v5")
```

All `add`, `retrieve`, `expand`, `compact`, `forget`, and `delete` calls inside the block emit records with the tagged metadata attached.

**Enabling the audit log:**

```env
OBSERVABILITY_AUDIT_ENABLED=true
OBSERVABILITY_AUDIT_PATH=.contextseek/audit.jsonl
```

Each `AuditRecord` (one per operation) is appended as a JSON line with:

| Field | Description |
|---|---|
| `request_id` | UUID per operation |
| `action` | `add`, `retrieve`, `expand`, `compact`, `forget`, `delete`, etc. |
| `scope` | Target scope |
| `policy_version` | Strategy version label (see `pin()`) |
| `status` | `ok` or `error` |
| `detail` | Operation-specific metadata (hit count, ref, score, …) |
| `actor` | From `ctx.tag(actor=…)` |
| `request` | From `ctx.tag(request=…)` |
| `source` | From `ctx.tag(source=…)` |
| `reason` | From `ctx.tag(reason=…)` |
| `ts` | UTC timestamp |

---

## Soft-delete and hard-delete

### `forget(ref, *, scope, reason, propagate=True)`

Marks an item as deleted without removing it from storage. The item gains `is_deleted=True` and a tombstone timestamp. It no longer appears in `retrieve()` results (unless `include_deleted=True`) but remains auditable.

```python
ctx.forget(
    item.ref,
    scope="acme/bot",
    reason="superseded by policy-v3",
)
```

**Propagation:** when `propagate=True` (default), items that derive their confidence from the forgotten item are re-evaluated. Items whose effective confidence drops below the reverification threshold (`EVOLUTION_REVERIFICATION_THRESHOLD`, default 0.4) are tagged `needs_reverification`.

### `delete(ref, *, scope, reason, propagate=True)`

Hard-removes the item's payload from storage. Cannot be undone. Use `forget()` when auditability or GDPR traceability matters; use `delete()` only when the payload must not persist (e.g., accidental PII ingestion).

```python
ctx.delete(item.ref, scope="acme/bot", reason="GDPR erasure")
```

Propagation semantics are identical to `forget()` and run before the payload is removed.

---

## Provenance fields

Every `ContextItem.provenance` is a `Provenance` object:

| Field | Type | Description |
|---|---|---|
| `source_type` | `SourceType` | How data entered the system |
| `source_id` | `str` | Identifier of the source (URL, trace ID, user ID, …) |
| `confidence` | `float` | Initial confidence (0.0–1.0) |
| `ingested_at` | `datetime` | When the item was created |

`SourceType` values: `human_input`, `llm_output`, `tool_call`, `retrieval`, `trace_extraction`, `distillation`, `external_api`, `system`, `document`.

## Link types

`ContextItem.links` is a list of `Link` objects:

| `LinkType` | Meaning |
|---|---|
| `supports` | This item provides evidence for the target |
| `refutes` | This item contradicts the target |
| `derived_from` | This item was synthesized from the target |
| `supported_by` | This item relies on the target for confidence |
| `supersedes` | This item replaces the target |
| `refuted_by` | This item's claim is contradicted by the target |
| `related_to` | Non-directional association |

---

[← Evolution](evolution.md) · [Write & retrieve](write-and-retrieve.md) · [API reference](../reference/api.md)
