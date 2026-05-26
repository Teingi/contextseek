# 溯源与审计

每条 `ContextItem` 都携带一条 `Provenance` 记录和类型化的 `Link` 边。这些信息让你可以追溯知识的来源、评估系统置信度，并对每次操作留下审计记录。

---

## 追溯条目来源

### `upstream(ref, *, scope) → list[ContextItem]`

从某条 item 出发，沿 `derived_from` 和 `supported_by` 链接进行广度优先遍历，返回起始 item 及其在 scope 内所有可达的祖先条目。

```python
sources = ctx.upstream(item.ref, scope="acme/bot")
for src in sources:
    print(f"  [{src.stage.value}] {src.provenance.source_id}: {src.content_text[:60]}")
```

`upstream()` 适用于快速回答"这条知识从哪里来"，无需运行完整的证据链分析。

### `evidence_chain(ref, *, scope, max_depth=10) → EvidenceChain`

以某条 item 为根，构建完整的溯源 DAG。遍历所有类型的 `Link` 边（不仅限于衍生关系），使用 Noisy-OR 传播置信度，检测矛盾，并识别权重最高的关键路径。

```python
chain = ctx.evidence_chain(item.ref, scope="acme/bot")

print(f"综合置信度: {chain.overall_confidence:.2f}")
print(f"链中节点数: {len(chain.nodes)}")
print(f"冲突数: {len(chain.conflicts)}")

# 遍历关键路径
for node in chain.critical_path:
    print(f"  {node.item_id} — confidence={node.confidence:.2f}")
```

`EvidenceChain` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `nodes` | `list[EvidenceNode]` | DAG 中所有条目 |
| `overall_confidence` | `float` | 根节点传播后的置信度（0.0–1.0） |
| `conflicts` | `list[ConflictReport]` | 链中检测到的矛盾 |
| `critical_path` | `list[EvidenceNode]` | 到叶节点的最高权重路径 |
| `broken_links` | `list[str]` | 已不存在的链接目标 |

### `chain_confidence(ref, *, scope) → float`

`evidence_chain()` 的轻量版，仅需有效置信度时使用。

```python
conf = ctx.chain_confidence(item.ref, scope="acme/bot")
print(f"有效置信度: {conf:.2f}")
```

---

## 审计追踪

### `tag()` — 附加操作者元数据

`ctx.tag()` 是一个上下文管理器，将操作者和请求元数据注入到 `with` 块内所有操作发出的 `AuditRecord` 中。需要 `OBSERVABILITY_AUDIT_ENABLED=true`。

```python
with ctx.tag(
    actor={"user": "alice", "role": "admin"},
    request={"request_id": "req-9f2a", "endpoint": "/review"},
    reason="每周知识审查",
):
    ctx.retrieve("部署手册", scope="acme/sre")
    ctx.add("新回滚步骤", scope="acme/sre", source="runbook/v5")
```

`with` 块内的所有 `add`、`retrieve`、`expand`、`compact`、`forget`、`delete` 调用都会在审计记录中附加上述元数据。

**启用审计日志：**

```env
OBSERVABILITY_AUDIT_ENABLED=true
OBSERVABILITY_AUDIT_PATH=.contextseek/audit.jsonl
```

每条操作对应一条 `AuditRecord`，以 JSON Lines 格式追加写入，包含：

| 字段 | 说明 |
|---|---|
| `request_id` | 每次操作的 UUID |
| `action` | `add`、`retrieve`、`expand`、`compact`、`forget`、`delete` 等 |
| `scope` | 目标 scope |
| `policy_version` | 策略版本标签（见 `pin()`） |
| `status` | `ok` 或 `error` |
| `detail` | 操作级元数据（命中数、ref、score 等） |
| `actor` | 来自 `ctx.tag(actor=…)` |
| `request` | 来自 `ctx.tag(request=…)` |
| `source` | 来自 `ctx.tag(source=…)` |
| `reason` | 来自 `ctx.tag(reason=…)` |
| `ts` | UTC 时间戳 |

---

## 软删除与硬删除

### `forget(ref, *, scope, reason, propagate=True)`

将 item 标记为已删除，但不从存储中移除。Item 获得 `is_deleted=True` 和墓碑时间戳，不再出现在 `retrieve()` 结果中（除非 `include_deleted=True`），但仍可审计。

```python
ctx.forget(
    item.ref,
    scope="acme/bot",
    reason="已被 policy-v3 取代",
)
```

**传播：** `propagate=True`（默认）时，从该 item 衍生置信度的条目会被重新评估。有效置信度低于重新验证阈值（`EVOLUTION_REVERIFICATION_THRESHOLD`，默认 0.4）的条目会被标记 `needs_reverification`。

### `delete(ref, *, scope, reason, propagate=True)`

从存储中彻底删除 item 的数据载荷，不可撤销。需要保留可审计性时请使用 `forget()`；仅当数据不能持久化（如误写入 PII）时才使用 `delete()`。

```python
ctx.delete(item.ref, scope="acme/bot", reason="GDPR 数据删除请求")
```

传播语义与 `forget()` 相同，在删除载荷前执行。

---

## Provenance 字段

每条 `ContextItem.provenance` 是一个 `Provenance` 对象：

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_type` | `SourceType` | 数据进入系统的方式 |
| `source_id` | `str` | 来源标识符（URL、轨迹 ID、用户 ID 等） |
| `confidence` | `float` | 初始置信度（0.0–1.0） |
| `ingested_at` | `datetime` | 条目创建时间 |

`SourceType` 枚举值：`human_input`、`llm_output`、`tool_call`、`retrieval`、`trace_extraction`、`distillation`、`external_api`、`system`、`document`。

## Link 类型

`ContextItem.links` 是 `Link` 对象列表：

| `LinkType` | 语义 |
|---|---|
| `supports` | 当前 item 为目标提供证据 |
| `refutes` | 当前 item 与目标矛盾 |
| `derived_from` | 当前 item 由目标合成而来 |
| `supported_by` | 当前 item 的置信度依赖目标 |
| `supersedes` | 当前 item 取代目标 |
| `refuted_by` | 当前 item 的声明被目标反驳 |
| `related_to` | 无向关联 |

---

[← 演化](evolution.md) · [写入与检索](write-and-retrieve.md) · [API 参考](../reference/api.md)
