# Troubleshooting

Common issues and how to resolve them.

---

## Installation

### `ModuleNotFoundError: No module named 'contextseek'`

Make sure the package is installed in the active Python environment:

```bash
pip show contextseek
python -c "from contextseek import ContextSeek"
```

If using `uv`:
```bash
uv run python -c "from contextseek import ContextSeek"
```

### `ModuleNotFoundError: No module named 'langchain_openai'`

You need an optional extra. Install the relevant one:

```bash
pip install "contextseek[langchain,openai]"      # OpenAI
pip install "contextseek[langchain,ollama]"       # Ollama
pip install "contextseek[langchain,huggingface]"  # HuggingFace
pip install "contextseek[oceanbase]"              # OceanBase
pip install "contextseek[http]"                   # FastAPI server
```

---

## Configuration

### Settings are not loading from `.env`

ContextSeek looks for `.env` in this order:
1. `./` (current working directory)
2. `{repo_root}/`
3. `{repo_root}/examples/configs/`
4. `python-dotenv` `find_dotenv(usecwd=True)` if installed

Run your script from the directory containing `.env`, or pass settings explicitly:

```python
from contextseek import ContextSeek, ContextSeekSettings
from contextseek.config.settings import StorageSettings

ctx = ContextSeek.from_settings(
    ContextSeekSettings(storage=StorageSettings(backend="file", path="/data/ctx"))
)
```

### `OPENAI_API_KEY` not recognized

ContextSeek does not read API keys directly — they are read by the LangChain class. Ensure the key is in your environment:

```bash
export OPENAI_API_KEY=sk-...
# or in .env:
OPENAI_API_KEY=sk-...
```

---

## Retrieval

### `retrieve()` returns 0 hits

**Check 1 — Is there anything in the scope?**
```python
items = ctx.items(scope="your/scope")
print(f"items in scope: {len(items)}")
```

**Check 2 — Scope typo?** `retrieve(scope=...)` is a prefix search. `acme/bot` matches `acme/bot/user-1` but not `acme/bots`.

**Check 3 — Are all items soft-deleted?**
```python
response = ctx.retrieve("query", scope="your/scope", include_deleted=True, k=10)
print(len(list(response)))
```

**Check 4 — Wrong recall route?** If items were added without embeddings but `RETRIEVAL_RECALL_ROUTES=["vector"]` only, nothing will be found. Ensure `phrase` or `terms` is in the list for keyword-based retrieval.

### Hits are not relevant

- Enable LLM reranking: `RETRIEVAL_RERANKER_MODE=llm`
- Add `vector` to recall routes (requires embedding config)
- Check that items have L2 `abstract` fields — run `ctx.items()` and inspect `item.abstract`
- Try a broader `scope` prefix that includes more items

### `retrieve()` returns L0 bodies instead of summaries (with a warning)

The summarizer is not configured. L1 summaries are empty so ContextSeek falls back to L0. To enable:

```env
SUMMARIZER_PROVIDER=llm
LLM_PROVIDER=langchain
LLM_CLASS_PATH=langchain_openai.ChatOpenAI
LLM_MODEL=gpt-4o-mini
```

This is intentional for zero-config dev — not a bug.

---

## Writing

### `ValueError: exact duplicate exists: <id>`

An item with identical content already exists in the scope. Options:

1. Skip the `add()` — the item is already there.
2. Update existing item via `feedback()` if relevance changed.
3. Pass `check_conflicts=False` to bypass deduplication (not recommended for production).
4. Call `ctx.forget(existing_id, ...)` first if the old item is outdated.

### Items written but not appearing in `retrieve()`

- Check `item.searchable` — it is `False` if the item was immediately soft-deleted (e.g., a dedup collision).
- Check `item.stage` — if `RETRIEVAL_RECALL_ROUTES` filters on a stage the item doesn't have, it won't match.
- Verify embedding: if `retrieve()` uses `vector` route but the item has no `embedding` (summarizer was disabled at write time), it won't appear in vector results.

---

## Evolution

### `compact()` does nothing (merged=0, archived=0, evolved=0)

- Default `EVOLUTION_ENABLED=false` — only hash dedup runs. Set `EVOLUTION_ENABLED=true`.
- Too few items: `LIFECYCLE_COMPACT_MIN_ITEMS=5` requires at least 5 items in the scope.
- Items are too new: `EVOLUTION_EXTRACT_MIN_AGE_SECONDS=60` — wait for items to age before extraction.
- Clusters too small: `EVOLUTION_MIN_CLUSTER_SIZE=3` — need ≥ 3 similar items to merge.

### `dream()` generates 0 items

- Too few items in scope (need multiple items for pattern detection).
- `DREAM_LLM_ENABLED=false` and items don't have sufficient keyword overlap for heuristic mode.
- Try adding more varied content to the scope first.

---

## HTTP server

### `uvicorn` not found

```bash
pip install "contextseek[http]"
uvicorn contextseek.http.server:app --port 8000
```

### Server starts but returns 500 on `/add`

Check server logs. Common cause: storage path is not writable or embedding model is not configured. Verify with a local `ContextSeek.from_settings()` first.

---

## MCP server

### MCP client can't connect to stdio server

Ensure the command is `contextseek-mcp-stdio` (installed as a script by pip). Verify:

```bash
which contextseek-mcp-stdio
contextseek-mcp-stdio --help
```

---

## OceanBase

### `pyobvector` not found

```bash
pip install "contextseek[oceanbase]"
```

### Connection refused / timeout

Check that `OB_HOST`, `OB_PORT`, `OB_USER`, and `OB_PASSWORD` are set correctly. OceanBase must be reachable from your host. Use `from_runtime_config()` with a runtime config file for OceanBase — the default `from_settings()` path does not instantiate OceanBase.

---

## Debugging tips

**Inspect audit records:**
```python
import json
with open(".contextseek/audit.jsonl") as f:
    for line in f:
        rec = json.loads(line)
        if rec["status"] != "ok":
            print(rec)
```

**Enable verbose output:**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
ctx = ContextSeek.from_settings()
```

**Check settings actually loaded:**
```python
from contextseek.config.settings import ContextSeekSettings
s = ContextSeekSettings()
print(s.storage.backend, s.embedding.provider, s.llm.provider)
```

---

[← Installation](getting-started/installation.md) · [Configuration](getting-started/configuration.md) · [GitHub Issues](https://github.com/ob-labs/contextseek/issues)
