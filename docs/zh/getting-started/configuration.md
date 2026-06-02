# 配置

ContextSeek 从**环境变量**和可选的 **`.env` 文件**加载配置。零配置路径无需任何设置：内存存储 + 关键词召回。

## 配置如何加载

### `.env` 查找顺序

使用第一个存在的文件：

1. `./.env`（当前工作目录）
2. `{仓库根}/.env`
3. `{仓库根}/examples/configs/.env`
4. 若已安装 `python-dotenv`，则 `find_dotenv(usecwd=True)`

将 [.env.example](../../../.env.example) 复制为 `.env` 后修改。

### 环境变量命名

嵌套配置段使用 **前缀 + 字段名**（大小写不敏感）：

| 配置类 | 前缀 | 示例 |
|--------|------|------|
| `StorageSettings` | `STORAGE_` | `STORAGE_BACKEND` |
| `EmbeddingSettings` | `EMBEDDING_` | `EMBEDDING_PROVIDER` |
| `LLMSettings` | `LLM_` | `LLM_MODEL` |
| `RetrievalSettings` | `RETRIEVAL_` | `RETRIEVAL_RERANKER_MODE` |

### 代码中构造

```python
from contextseek import ContextSeek, ContextSeekSettings
from contextseek.config.settings import (
    StorageSettings,
    EmbeddingSettings,
    LLMSettings,
    RetrievalSettings,
)

settings = ContextSeekSettings(
    storage=StorageSettings(backend="file", path="/var/lib/contextseek"),
    embedding=EmbeddingSettings(
        provider="langchain",
        class_path="langchain_openai.OpenAIEmbeddings",
        model="text-embedding-3-small",
        dims=1536,
    ),
    llm=LLMSettings(
        provider="langchain",
        class_path="langchain_openai.ChatOpenAI",
        model="gpt-4o-mini",
    ),
    retrieval=RetrievalSettings(
        recall_routes=["phrase", "terms", "vector"],
        reranker_mode="llm",
    ),
)

ctx = ContextSeek.from_settings(settings)
```

在 `ContextSeekSettings(...)` 里显式赋值的字段优先于环境变量。

---

## 典型配置档

### 档 A — 本地开发（默认）

无需配置，`ContextSeek.from_settings()` 即可。

### 档 B — 文件持久化 + 关键词

```env
STORAGE_BACKEND=file
STORAGE_PATH=.contextseek/data
```

适合单机与示例；召回为文件索引上的子串匹配。

### 档 C — 语义检索（OpenAI）

```env
STORAGE_BACKEND=file
STORAGE_PATH=.contextseek/data

EMBEDDING_PROVIDER=langchain
EMBEDDING_CLASS_PATH=langchain_openai.OpenAIEmbeddings
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMS=1536
OPENAI_API_KEY=sk-...

RETRIEVAL_RECALL_ROUTES=["phrase","terms","vector"]

LLM_PROVIDER=langchain
LLM_CLASS_PATH=langchain_openai.ChatOpenAI
LLM_MODEL=gpt-4o-mini

SUMMARIZER_PROVIDER=llm
```

安装：`pip install "contextseek[langchain,openai]"`。

`add()` 会生成 L2/L1，检索可走向量；可选 LLM 重排。

### 档 D — 生产补充项

```env
OBSERVABILITY_AUDIT_ENABLED=true
OBSERVABILITY_AUDIT_PATH=.contextseek/audit.jsonl
EVOLUTION_ENABLED=true
RETRIEVAL_RERANKER_MODE=llm
```

演进相关 LLM 开关建议按下方分阶段开启。

---

## 配置段说明

### 存储（`STORAGE_*`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `STORAGE_BACKEND` | `memory` | `memory` 或 `file` |
| `STORAGE_PATH` | `.contextseek/store` | `file` 时目录 |
| `STORAGE_URI_SCHEME` | `contextseek://` | ref 协议 |
| `STORAGE_COLD_BACKEND` | 空 | 可选冷层 |
| `STORAGE_COLD_PATH` | `.contextseek/cold` | 冷层路径 |

OceanBase 另见 `OB_*` 与 [存储后端](../guides/storage.md)。

### Embedding（`EMBEDDING_*`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `EMBEDDING_PROVIDER` | `none` | `none` 或 `langchain` |
| `EMBEDDING_CLASS_PATH` | — | 如 `langchain_openai.OpenAIEmbeddings` |
| `EMBEDDING_MODEL` | — | 模型名 |
| `EMBEDDING_DIMS` | `0` | 非 `none` 时必填 |
| `EMBEDDING_BASE_URL` | （空） | 可选基地址（OpenAI 兼容端点、Ollama 等） |

`OPENAI_API_KEY` 等由 LangChain 类读取，非 ContextSeek 直接解析。

### LLM（`LLM_*`）

重排、summarizer、演进、dream、冲突判断等共用。

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_PROVIDER` | `none` | `none` 或 `langchain` |
| `LLM_CLASS_PATH` | — | 如 `langchain_openai.ChatOpenAI` |
| `LLM_MODEL` | — | 对话模型名 |
| `LLM_BASE_URL` | （空） | 可选基地址（OpenAI 兼容端点、Ollama 等） |

### Summarizer（`SUMMARIZER_*`）

每次 `add()` 生成 L2/L1。

| 变量 | 默认 | 说明 |
|------|------|------|
| `SUMMARIZER_PROVIDER` | `llm` | `none` 关闭；`llm` 用 `LLM_*` |
| `SUMMARIZER_L2_MAX_CHARS` | `100` | L2 字符上限 |
| `SUMMARIZER_L1_MAX_CHARS` | `2000` | L1 字符上限 |

`SUMMARIZER_PROVIDER=llm` 但未配 LLM 时，summarizer 跳过，检索退化为 L0（一次性警告）。

### 检索（`RETRIEVAL_*`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `RETRIEVAL_DEFAULT_K` | `20` | 候选池规模相关 |
| `RETRIEVAL_RECALL_ROUTES` | `["phrase","terms"]` | JSON：`phrase` / `terms` / `vector` |
| `RETRIEVAL_RERANKER_MODE` | `heuristic` | `heuristic` 或 `llm` |
| `RETRIEVAL_LLM_RERANK_TOP_N` | `20` | 送入 LLM 重排的候选数 |

启发式重排还考虑词重叠、provenance、feedback（`relevance_boost`）、链接惩罚等。

### 演进（`EVOLUTION_*`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `EVOLUTION_ENABLED` | `false` | `compact()` 总开关 |
| `EVOLUTION_SEMANTIC_MERGE_THRESHOLD` | `0.72` | 合并相似度阈值 |
| `EVOLUTION_MIN_CLUSTER_SIZE` | `3` | 合并为 knowledge 的最小簇大小 |
| `EVOLUTION_LLM_*` | `false` | 各 LLM 增强子功能 |

### Dream（`DREAM_*`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `DREAM_LLM_ENABLED` | `false` | 整合/发散是否用 LLM |

### 提示词（`PROMPT_*`）

覆盖各 LLM 步骤模板；JSON 示例中大括号写 `{{` `}}`。完整列表见 [.env.example](../../../.env.example)。

### 安全（`SECURITY_*`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `SECURITY_ACL_ENABLED` | `true` | 读写策略 |
| `SECURITY_REDACT_SENSITIVE` | `false` | 写入脱敏 |

### 可观测（`OBSERVABILITY_*`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `OBSERVABILITY_AUDIT_ENABLED` | `false` | JSONL 审计 |
| `OBSERVABILITY_AUDIT_PATH` | `.contextseek/audit.jsonl` | 路径 |

配合 `ctx.tag(actor=..., request_id=...)`，见 [可观测性](../guides/observability.md)。

---

## LLM 能力分阶段上线

| 阶段 | 建议开启 | 效果 |
|------|----------|------|
| **1** | `RETRIEVAL_RERANKER_MODE=llm`、`DREAM_LLM_ENABLED=true` | 更好排序；Dream 质量提升 |
| **2** | `EVOLUTION_LLM_MERGE_ENABLED`、`EVOLUTION_LLM_CONFLICT_CHECK_ENABLED` | 合并与矛盾判断 |
| **3** | `EVOLUTION_LLM_STAGE_INFER_ENABLED`、`EVOLUTION_LLM_DISTILL_ENABLED`、`EVOLUTION_LLM_FEEDBACK_ENABLED` | 阶段推断、技能蒸馏、反馈解析 |

```env
LLM_PROVIDER=langchain
LLM_CLASS_PATH=langchain_openai.ChatOpenAI
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...

RETRIEVAL_RERANKER_MODE=llm
RETRIEVAL_LLM_RERANK_TOP_N=20
DREAM_LLM_ENABLED=true
```

---

## 密钥与部署

- **勿提交**含真实密钥的 `.env`（已在 `.gitignore`）。
- CI 用密钥管理注入环境变量；默认测试不依赖 LLM。
- K8s/Docker 可用 Secret 挂载或环境变量。

---

## 下一步

- [写入与检索](../guides/write-and-retrieve.md)
- [配置项参考](../reference/settings.md)
- [存储后端](../guides/storage.md)
