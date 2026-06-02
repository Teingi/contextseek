# ContextItem 对象模型

ContextSeek 将所有数据存储为 `ContextItem` 对象——记忆片段、知识库段落、Trace、蒸馏技能在类型上是同一种对象。Stage、Provenance 和 Tags 表达语义，类型本身不变。

---

## 统一对象

```python
from contextseek import ContextSeek
from contextseek.domain.provenance import SourceType
from contextseek.domain.stages import Stage, Stability

ctx = ContextSeek.from_settings()

item = ctx.add(
    "生产发布前必须跑集成测试。",
    scope="acme/platform/team-sre",
    source="runbook/deploy-v4",
    source_type=SourceType.document,
    tags=["deploy", "prod"],
    stage=Stage.knowledge,
    stability=Stability.stable,
)
```

## 字段参考

**身份**

| 字段 | 说明 |
|------|------|
| `id` | 自动生成的 hex ID |
| `scope` | 租户/项目/主体路径 |
| `content` | L0：字符串或可 JSON 序列化的 dict |

**可检索**

| 字段 | 说明 |
|------|------|
| `abstract` | L2（约 100 字）— 向量索引输入 |
| `summary` | L1（约 2k 字）— `retrieve()` 默认返回 |
| `tags` | 过滤维度；检索时须**全部匹配** |
| `embedding` | L2（无则 L0）的向量 |
| `searchable` | 归档/软删后为 `False` |
| `relevance_boost` | `feedback()` 正向反馈累积的得分乘数 |

**可溯源**

| 字段 | 说明 |
|------|------|
| `provenance` | 必填来源信息 |
| `links` | 指向其他 item 的 `Link` 列表 |

**可演进**

| 字段 | 说明 |
|------|------|
| `stage` | `raw` → `extracted` → `knowledge` → `skill` |
| `stability` | `ephemeral` / `transient` / `stable` / `permanent` |

**生命周期（多由系统维护）**

| 字段 | 说明 |
|------|------|
| `created_at` / `updated_at` | UTC 时间戳 |
| `access_count` / `last_accessed_at` | 出现在 `retrieve()` 命中时更新 |
| `superseded_by` | 替代本条的新 item ID |
| `deleted_at` / `deleted_reason` | 软删除元数据 |

通过 `item.content_text` 获取字符串正文；仅返回摘要时 `content` 可能为 `None`。

---

## Provenance

`Provenance` 回答数据**来自哪里**以及**信任程度**。

| `source_type` | 约略默认置信度 | 适用场景 |
|---------------|----------------|----------|
| `human_input` | 1.0 | 用户录入或运营审核 |
| `document` | 0.8 | 文档、Wiki、工单 |
| `trace_extraction` | 0.5 | Agent/运行 Trace 解析 |
| `agent_inference` | 0.6 | 模型生成摘要 |
| `external_api` | 0.5 | 工具/API 返回 |
| `merge_result` | 0.7 | 演化合并产出 |
| `distillation` | 0.7 | 批量蒸馏 |
| `dream_consolidation` | 0.4 | Dream 引擎整合 |
| `dream_divergence` | 0.3 | Dream 引擎假设 |

**关键 `Provenance` 字段：**

- `source_id` — 稳定标识（URL、Trace ID、文件名）
- `confidence` — 0.0–1.0，可通过 `add(..., confidence=0.9)` 覆盖
- `verified` — 人工或外部验证标志
- `context` — 自由文本备注（如"从 incident #4421 中提炼"）

**硬约束：** 无 Provenance 的条目不允许入库；`add()` 始终自动构建。

---

## Link 与证据链

`Link` 对象连接条目，用于审计追踪和演化：

| `LinkType` | 作用 |
|------------|------|
| `derived_from` | 本条从另一条提炼 |
| `supported_by` | 佐证 |
| `refuted_by` | 反驳（冲突检测也会自动建立） |
| `supersedes` | 新版本替代旧版 |
| `merged_from` | 合并来源 |
| `distilled_into` | 指向 skill 条目 |
| `related_to` | 宽泛关联 |
| `requires` | 前置依赖 |
| `synthesized_from` | Dream 合成来源 |

示例链：

```
knowledge: "部署前必须跑集成测试"
  provenance.source_type = trace_extraction
  links:
    derived_from → 失败部署的原始 trace
    supported_by → 官方部署文档条目
    supersedes   → 过时的检查清单条目
```

见 [溯源与审计](../guides/provenance-and-audit.md) 中的 `upstream()`、`evidence_chain()`、`chain_confidence()`。

---

## 为何统一为一种类型

早期 Agent 框架常将 profile、会话、知识库、Trace、技能分成不同表和 API。ContextSeek 统一为一种对象，因为：

1. 写入时不应让开发者猜类型；
2. 同一段文字会从 `raw` 演进为 `knowledge`；
3. 检索、审计、删除策略可统一执行。

用 **`source_type`**、**`tags`**、**`stage`** 表达意图，而非不同 SDK 类。

---

## 下一步

- [Scope 与 Stage](scope-and-stage.md) — 隔离边界与成熟度模型
- [检索模型](retrieval-model.md) — L0/L1/L2 分层与检索流水线
- [写入与检索](../guides/write-and-retrieve.md) — API 使用模式
