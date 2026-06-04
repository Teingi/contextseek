# 上下文演进

ContextSeek 中的条目不是静态的。它们通过 stage 流水线（`raw → extracted → knowledge → skill`）逐步成熟，并可随时间推移被整合、合成与蒸馏。本指南介绍四个演化控制接口：`compact()`、`dream()`、`feedback()` 和 `overview()`。

---

## Stage 流水线

每条 `ContextItem` 都有一个表示成熟度的 `stage`：

| Stage | 含义 | 典型来源 |
|-------|------|----------|
| `raw` | 未处理的原始观察 | Trace、Agent 日志、用户输入 |
| `extracted` | 已清洗和结构化 | 后处理、dream 合成 |
| `knowledge` | 经验证的稳定事实 | 文档摄入、合并产出 |
| `skill` | 可执行的操作流程 | 从高频知识蒸馏而来 |

Stage 通过 `compact()` 自动推进。也可在 `add()` 时显式覆盖：

```python
from contextseek.domain.stages import Stage

ctx.add("部署前必须通过集成测试。", scope="acme/sre", source="wiki",
        stage=Stage.knowledge)
```

---

## `compact()` — 演化流水线

`compact()` 是主要的维护操作。建议定期运行，或在大批量写入后执行。

```python
report = ctx.compact(scope="acme/bot/user_42")
print(f"merged={report.merged_count}, archived={report.archived_count}, evolved={report.evolved_count}")
```

**执行内容：**

`EVOLUTION_ENABLED=false`（默认）时：仅做哈希精确去重。

`EVOLUTION_ENABLED=true` 时，按顺序执行完整流水线：

1. **哈希去重** — 精确重复条目被软删除
2. **提取** — 年龄超过 `EVOLUTION_EXTRACT_MIN_AGE_SECONDS` 的 `raw` 条目晋升为 `extracted`
3. **语义合并** — 余弦相似度 ≥ `EVOLUTION_SEMANTIC_MERGE_THRESHOLD` 的 `extracted` 条目进行聚类；大小 ≥ `EVOLUTION_MIN_CLUSTER_SIZE` 的簇合并为新的 `knowledge` 条目
4. **蒸馏** — `access_count ≥ EVOLUTION_DISTILL_MIN_USE_COUNT` 且 `relevance_boost ≥ EVOLUTION_DISTILL_MIN_RELEVANCE_BOOST` 的 `knowledge` 条目成为技能蒸馏候选
5. **归档** — 超过 `EVOLUTION_EPHEMERAL_TTL_SECONDS` 的临时条目及低重要性陈旧条目被软归档

**预演模式（dry run）：**

```python
preview = ctx.compact(scope="acme/bot/user_42", dry_run=True)
print(f"将合并 {preview.merged_count} 条条目")
```

**推荐频率：** 每晚或大量写入后执行一次。搭配 `overview()` 判断是否值得压缩。

---

## `dream()` — 闲时合成

`dream()` 在空闲时运行两个创造性阶段：

- **整合（Consolidation）** — 在 scope 内发现多条目中的反复模式，合成为新的 `extracted` 条目
- **发散（Divergence）** — 生成跨越两个不相似簇的假设，创建置信度较低的推测性新条目

Dream 条目会带上 `dreamed` 加 `consolidation` 或 `divergence` 标签，初始 stage 为 `extracted`，置信度低，会自然衰减，除非通过 `feedback()` 加以强化。被持续强化的 dream 条目可毕业到 `Stage.knowledge`，并打上 `graduated` 标签。

```python
report = ctx.dream(scope="acme/bot/user_42")
print(f"生成 {report.total_dream_items} 条 dream 条目 "
      f"（整合 {len(report.consolidation.items)} 条，"
      f"发散 {len(report.divergence.items) if report.divergence else 0} 条）")
print(f"毕业 {len(report.graduated_items)} 条")
```

**运行时机：** 大批量写入后，或在低峰期通过调度器运行。不要在每次请求中运行 `dream()`。

**冷却行为：** `ctx.dream()` 默认 `force=True`，因此显式/手动调用会绕过冷却。若要让冷却生效，请传 `force=False`，或走调度器/daemon 路径（按 scope 持久化冷却）。

**LLM 模式：** `DREAM_LLM_ENABLED` 默认 `true`，可获得更丰富的合成效果。设为 `false` 可强制使用启发式回退路径。

```python
# 预演 — 查看但不持久化
preview = ctx.dream(scope="acme/bot/user_42", dry_run=True)
```

---

## `feedback()` — 引导检索与演化

`feedback()` 提供来自 Agent 或用户的显式相关性信号：

```python
# 正向反馈：条目很有用
ctx.feedback(hit.item.ref, scope="acme/bot", score=0.8, reason="正好是我需要的")

# 负向反馈：条目无用
ctx.feedback(hit.item.ref, scope="acme/bot", score=-0.5, reason="已过时")
```

**分值机制：**

| 分值范围 | 效果 |
|----------|------|
| `> 0` | 提升 `relevance_boost`（上限 5.0）；`access_count` +1；boost ≥ 2.0 时打 `"evolution_candidate"` 标签 |
| `< 0` | 降低 `relevance_boost`（下限 0.1）；为 `raw`/`extracted` 条目打 `"needs_review"`；≤ −0.5 时衰减 `importance` |

`relevance_boost` 是启发式重排器中的得分乘数。高 `access_count` + `relevance_boost` 的条目更早成为蒸馏候选。

**LLM 原因解析：** 设置 `EVOLUTION_LLM_FEEDBACK_ENABLED=true` 可对 `reason` 字符串进行结构化解析（如"已过时" → 标记待审；"非常有用" → 加速晋升）。

---

## `overview()` — Scope 健康检查

`overview()` 是只读扫描，不修改任何内容：

```python
report = ctx.overview(scope="acme/bot")
print(report)
```

报告包含：
- 各 stage 的条目数量（`raw`、`extracted`、`knowledge`、`skill`）
- 待提取条目数
- 待收敛/合并条目数
- 可蒸馏候选数

在运行 `compact()` 前用 `overview()` 判断是否值得执行，或在仪表板中监控 scope 健康状态。

---

## 推荐工作流

```
每天 / 大批量写入后：
    ctx.overview(scope=...)    # 检查健康状态
    ctx.compact(scope=...)     # 去重 + 演化

低峰期 / 每周：
    ctx.dream(scope=...)       # 模式合成

内联 / Agent 循环中：
    ctx.feedback(ref, ...)     # 每次检索/使用后
```

### 启用演化的最小配置

```env
EVOLUTION_ENABLED=true

# 推荐的第一阶段 LLM 功能：
RETRIEVAL_RERANKER_MODE=llm
DREAM_LLM_ENABLED=true
```

启用所有 `EVOLUTION_LLM_*` 开关前，请参阅[分阶段 LLM 上线](../getting-started/configuration.md#分阶段-llm-上线)。

---

[← 写入与检索](write-and-retrieve.md) · [溯源与审计](provenance-and-audit.md) · [API 参考](../reference/api.md)
