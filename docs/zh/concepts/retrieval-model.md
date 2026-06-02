# 检索模型

ContextSeek 的检索是多阶段流水线：**召回** → **重排** → **分层输出**。了解各阶段有助于调优质量并控制 token 成本。

---

## 内容分层：L0 / L1 / L2

每条 `ContextItem` 最多持有三个粒度层级的内容：

| 层级 | 字段 | 大小 | 作用 |
|------|------|------|------|
| **L0** | `content` | 完整正文 | `full=True` 或 `expand()` 按需获取 |
| **L1** | `summary` | 约 2k 字 | `retrieve()` 默认返回 |
| **L2** | `abstract` | 约 100 字 | 向量索引输入 |

**L2 和 L1 在 `add()` 时由 Summarizer 自动生成：**

```
add(content)
     │
     ▼
Summarizer ──── abstract (L2) ──▶ Embedder ──▶ 向量索引
            └── summary  (L1) ──▶ 随条目存储

retrieve() ──▶ 默认返回 L1
expand()   ──▶ 将选中命中升档为 L0
```

未配置 Summarizer 时，L2 和 L1 字段为空，`retrieve()` 直接返回 L0 正文，并发出一次性警告。这是有意为之：零配置开发/测试无需 API Key；生产环境建议启用 `SUMMARIZER_PROVIDER=llm`。

---

## 召回路由

召回是流水线第一阶段：在评分前收集候选条目。三条路由可同时启用（由 `RETRIEVAL_RECALL_ROUTES` 控制）：

| 路由 | 工作方式 | 适合场景 |
|------|----------|----------|
| `phrase` | L2 或 L0 上的精确/近似子串匹配 | 短而精确的查询 |
| `terms` | 对分词内容的倒排索引 | 关键词密集型查询 |
| `vector` | L2 向量的近似最近邻 | 语义相似性 |

默认为 `["phrase", "terms"]`（无需向量模型）。配置了 Embedding 后加入 `vector`：

```env
RETRIEVAL_RECALL_ROUTES=["phrase","terms","vector"]
```

所有启用的路由并行运行，候选集合并后进入重排。

---

## 重排

召回后，候选集按分数排名。两种模式：

### 启发式重排（默认）

多信号加权求和：

| 信号 | 权重变量 | 含义 |
|------|----------|------|
| 向量相似度 | `RETRIEVAL_VECTOR_WEIGHT`（0.7） | 语义接近度 |
| 全文搜索分 | `RETRIEVAL_FTS_WEIGHT`（0.3） | BM25 式关键词匹配 |
| 词条重叠 | `RETRIEVAL_TERM_WEIGHT`（0.15） | Token 共现 |
| 时近性 | `RETRIEVAL_RECENCY_WEIGHT`（0.05） | 写入时间早晚 |
| 相关性加权 | `RETRIEVAL_FEEDBACK_WEIGHT`（0.20） | 累积 `feedback()` 信号 |
| Provenance 置信度 | `RETRIEVAL_PROVENANCE_WEIGHT`（0.15） | 来源可信度 |
| 链接加成 | `RETRIEVAL_LINK_BOOST`（0.10） | 有佐证链接 |
| 归档惩罚 | `RETRIEVAL_ARCHIVE_PENALTY`（0.50） | 已归档/已替代条目 |

### LLM 重排

设置 `RETRIEVAL_RERANKER_MODE=llm`，将召回的前 `RETRIEVAL_LLM_RERANK_TOP_N` 个候选送入 LLM 相关性评分器。这是 LLM 分阶段上线中 Phase 1 的核心功能，对大多数场景而言性价比最高。

```env
RETRIEVAL_RERANKER_MODE=llm
RETRIEVAL_LLM_RERANK_TOP_N=20
```

---

## 分层输出：摘要 vs 全文

重排后，`retrieve()` 通过分层控制 token 用量：

```python
# 默认：L1 摘要（省 token）
response = ctx.retrieve("query", scope="acme/bot", k=10)
for hit in response:
    print(hit.item.summary)     # L1 — 约 2k 字/条
    print(hit.layer)            # "summary"

# 将选中命中升档为 L0
interesting = [h for h in response if h.score > 0.7]
full_items = ctx.expand(interesting)

# 直接返回 L0（更多 token，省去 expand 往返）
response = ctx.retrieve("query", scope="acme/bot", k=5, full=True)
for hit in response:
    print(hit.item.content)     # L0 — 完整正文
```

**推荐的 Agent 模式：**
1. 用 `retrieve()` 召回 top-k（L1，低成本）
2. 按 `hit.score` 或其他条件筛选
3. 只对需要完整上下文的 1–3 条调用 `expand()`

这样大多数 prompt 注入控制在约 2k 字，同时在必要时仍可获取完整内容。

---

## 过滤

在评分前缩小候选集：

```python
from contextseek.domain.stages import Stage

# 按 stage 过滤
response = ctx.retrieve("query", scope="acme/bot",
                         stage=Stage.knowledge)

# 按 tags 过滤（所有 tag 必须全部匹配）
response = ctx.retrieve("query", scope="acme/bot",
                         tags=["deploy", "prod"])

# 最低置信度
response = ctx.retrieve("query", scope="acme/bot",
                         filters={"min_confidence": 0.7})
```

---

## 超采样与重排模式

为获得高质量结果，召回时超采样，让重排器精简：

```python
# 内部取 30 个候选，重排后返回 top 5
response = ctx.retrieve("query", scope="acme/bot", k=5)
# RETRIEVAL_DEFAULT_K=20 控制初始候选池；
# RETRIEVAL_CANDIDATE_MULTIPLIER=4 控制送入重排前的原始候选数。
```

---

## 架构示意

```
retrieve(query, scope, k)
        │
        ▼
  ┌──────────────────────────────────────┐
  │ 召回（并行路由）                       │
  │  phrase 召回  ─┐                     │
  │  terms 召回   ─┼─▶ 合并候选池         │
  │  vector 召回  ─┘                     │
  └─────────────────┬────────────────────┘
                    │
                    ▼
  ┌──────────────────────────────────────┐
  │ 重排（启发式或 LLM）                   │
  │  得分 = 多信号加权                    │
  │  选出 top-k                          │
  └─────────────────┬────────────────────┘
                    │
                    ▼
  ┌──────────────────────────────────────┐
  │ 分层输出                               │
  │  full=False → 替换 content → L1 摘要  │
  │  full=True  → 保留 content → L0 正文  │
  └──────────────────────────────────────┘
```

---

## 下一步

- [写入与检索](../guides/write-and-retrieve.md) — 完整 API 模式与过滤
- [配置](../getting-started/configuration.md) — 检索与 LLM 分阶段上线设置
- [ContextItem 对象模型](context-model.md) — 字段与分层详情
