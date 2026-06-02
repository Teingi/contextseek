# Configuration

ContextSeek loads settings from **environment variables** and an optional **`.env` file**. No configuration is required for the zero-config path: in-memory storage and keyword-only retrieval.

## How settings are loaded

### Resolution order for `.env`

The first existing file wins:

1. `./.env` (current working directory)
2. `{repo_root}/.env`
3. `{repo_root}/examples/configs/.env`
4. `python-dotenv` `find_dotenv(usecwd=True)` if installed

Copy [.env.example](../../../.env.example) to `.env` and edit.

### Environment variable naming

Nested sections use a **prefix + field name** (case-insensitive):

| Section class | Prefix | Example field → env var |
|---------------|--------|-------------------------|
| `StorageSettings` | `STORAGE_` | `backend` → `STORAGE_BACKEND` |
| `EmbeddingSettings` | `EMBEDDING_` | `provider` → `EMBEDDING_PROVIDER` |
| `LLMSettings` | `LLM_` | `model` → `LLM_MODEL` |
| `RetrievalSettings` | `RETRIEVAL_` | `reranker_mode` → `RETRIEVAL_RERANKER_MODE` |

### Constructing in code

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

Code overrides beat env for fields you set explicitly on `ContextSeekSettings(...)`.

---

## Configuration profiles

### Profile A — Local dev (default)

Nothing required. In-memory store, phrase+term recall, no API keys.

```python
ctx = ContextSeek.from_settings()
```

### Profile B — Persistent file + keywords

```env
STORAGE_BACKEND=file
STORAGE_PATH=.contextseek/data
```

Suitable for single-node apps and examples. Retrieval uses substring match on file-backed index.

### Profile C — Semantic search (OpenAI)

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

Install: `pip install "contextseek[langchain,openai]"`.

Enables L2/L1 generation on `add()`, vector recall, optional LLM rerank.

### Profile D — Production checklist

Add observability and evolution as needed:

```env
OBSERVABILITY_AUDIT_ENABLED=true
OBSERVABILITY_AUDIT_PATH=.contextseek/audit.jsonl
EVOLUTION_ENABLED=true
RETRIEVAL_RERANKER_MODE=llm
```

See phased LLM flags below before enabling all evolution LLM features at once.

---

## Section reference

### Storage (`STORAGE_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | `memory` | `memory` or `file` |
| `STORAGE_PATH` | `.contextseek/store` | Directory when `backend=file` |
| `STORAGE_URI_SCHEME` | `contextseek://` | URI scheme for refs |
| `STORAGE_COLD_BACKEND` | (empty) | Optional tiered cold tier |
| `STORAGE_COLD_PATH` | `.contextseek/cold` | Cold tier path |

OceanBase uses additional `OB_*` variables when built via runtime factory / examples — see [Storage backends](../guides/storage.md).

### Embedding (`EMBEDDING_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | `none` | `none` or `langchain` |
| `EMBEDDING_CLASS_PATH` | — | e.g. `langchain_openai.OpenAIEmbeddings` |
| `EMBEDDING_MODEL` | — | Model name for provider ctor |
| `EMBEDDING_DIMS` | `0` | Required when provider ≠ `none` |
| `EMBEDDING_BASE_URL` | (empty) | Optional base URL (for OpenAI-compatible endpoints, Ollama, etc.) |

Provider API keys (`OPENAI_API_KEY`, `DASHSCOPE_API_KEY`, …) are read by LangChain classes, not by ContextSeek directly.

### LLM (`LLM_*`)

Used for rerank, summarizer, evolution, dream, conflict judge — any feature that calls the shared LLM client.

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `none` | `none` or `langchain` |
| `LLM_CLASS_PATH` | — | e.g. `langchain_openai.ChatOpenAI` |
| `LLM_MODEL` | — | Chat model name |
| `LLM_BASE_URL` | (empty) | Optional base URL (for OpenAI-compatible endpoints, Ollama, etc.) |

### Summarizer (`SUMMARIZER_*`)

Drives L2 `abstract` and L1 `summary` on every `add()`.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMARIZER_PROVIDER` | `llm` | `none` disables; `llm` uses `LLM_*` |
| `SUMMARIZER_L2_MAX_CHARS` | `100` | L2 char budget |
| `SUMMARIZER_L1_MAX_CHARS` | `2000` | L1 char budget |

If `SUMMARIZER_PROVIDER=llm` but no LLM is configured, summarizer is skipped and retrieval falls back to L0-only behavior (with a one-time warning).

### Retrieval (`RETRIEVAL_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `RETRIEVAL_DEFAULT_K` | `20` | Default candidate pool sizing |
| `RETRIEVAL_RECALL_ROUTES` | `["phrase","terms"]` | JSON list: `phrase`, `terms`, `vector` |
| `RETRIEVAL_RERANKER_MODE` | `heuristic` | `heuristic` or `llm` |
| `RETRIEVAL_LLM_RERANK_TOP_N` | `20` | Candidates passed to LLM reranker |
| `RETRIEVAL_VECTOR_WEIGHT` | `0.7` | Hybrid score weight (vector backends) |
| `RETRIEVAL_FTS_WEIGHT` | `0.3` | Full-text weight |

Heuristic rerank also weighs token overlap, provenance, feedback (`relevance_boost`), and link penalties.

### Evolution (`EVOLUTION_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `EVOLUTION_ENABLED` | `false` | Master switch for `compact()` pipeline |
| `EVOLUTION_SEMANTIC_MERGE_THRESHOLD` | `0.72` | Similarity for merge clusters |
| `EVOLUTION_MIN_CLUSTER_SIZE` | `3` | Min items to merge into knowledge |
| `EVOLUTION_LLM_MERGE_ENABLED` | `false` | LLM merge synthesis |
| `EVOLUTION_LLM_CONFLICT_CHECK_ENABLED` | `false` | LLM contradiction judge on write |
| `EVOLUTION_LLM_STAGE_INFER_ENABLED` | `false` | LLM stage classification on write |
| `EVOLUTION_LLM_DISTILL_ENABLED` | `false` | LLM skill distill |
| `EVOLUTION_LLM_FEEDBACK_ENABLED` | `false` | LLM feedback reason parsing |

### Dream (`DREAM_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DREAM_LLM_ENABLED` | `false` | LLM in consolidation/divergence steps |

### Prompts (`PROMPT_*`)

Override templates for LLM-assisted steps. Placeholders vary by template (`{query}`, `{content}`, `{items}`, …). Escape literal braces in JSON examples as `{{` and `}}`.

See commented blocks in [.env.example](../../../.env.example) for all keys.

### Security (`SECURITY_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SECURITY_ACL_ENABLED` | `true` | Enforce read/write policies |
| `SECURITY_REDACT_SENSITIVE` | `false` | Redact fields on write |

### Observability (`OBSERVABILITY_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVABILITY_AUDIT_ENABLED` | `false` | JSONL audit log |
| `OBSERVABILITY_AUDIT_PATH` | `.contextseek/audit.jsonl` | Audit file path |
| `OBSERVABILITY_METRICS_ENABLED` | `false` | Prometheus text export |

Use `ctx.tag(actor=..., request_id=...)` to enrich audit records — see [Observability](../guides/observability.md).

### Lifecycle (`LIFECYCLE_*`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LIFECYCLE_AUTO_COMPACT` | `true` | Scheduler may run compaction |
| `LIFECYCLE_INTERVAL_SECONDS` | `3600` | Scheduler interval |

---

## Phased LLM rollout

Enable features incrementally to control cost and debug behavior:

| Phase | Enable | Effect |
|-------|--------|--------|
| **1** | `RETRIEVAL_RERANKER_MODE=llm`, `DREAM_LLM_ENABLED=true` | Better ranking; richer dream cycles |
| **2** | `EVOLUTION_LLM_MERGE_ENABLED`, `EVOLUTION_LLM_CONFLICT_CHECK_ENABLED` | Smarter merges; semantic conflict tags |
| **3** | `EVOLUTION_LLM_STAGE_INFER_ENABLED`, `EVOLUTION_LLM_DISTILL_ENABLED`, `EVOLUTION_LLM_FEEDBACK_ENABLED` | Stage inference, skills, feedback NLP |

Example `.env` skeleton:

```env
LLM_PROVIDER=langchain
LLM_CLASS_PATH=langchain_openai.ChatOpenAI
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...

# Phase 1
RETRIEVAL_RERANKER_MODE=llm
RETRIEVAL_LLM_RERANK_TOP_N=20
DREAM_LLM_ENABLED=true

# Phase 2
# EVOLUTION_LLM_MERGE_ENABLED=true
# EVOLUTION_LLM_CONFLICT_CHECK_ENABLED=true

# Phase 3
# EVOLUTION_LLM_STAGE_INFER_ENABLED=true
# EVOLUTION_LLM_DISTILL_ENABLED=true
# EVOLUTION_LLM_FEEDBACK_ENABLED=true
```

---

## Secrets and deployment

- **Never commit** `.env` with real keys (repo `.gitignore` already excludes it).
- In CI, inject env vars from your secret store; tests run without LLM by default.
- For Kubernetes/Docker, mount `.env` or set env from ConfigMap + Secret separately.

---

## Next steps

- [Write & retrieve](../guides/write-and-retrieve.md) — how settings affect `add` / `retrieve`
- [Settings reference](../reference/settings.md) — compact env index
- [Storage backends](../guides/storage.md) — OceanBase and tiered options
