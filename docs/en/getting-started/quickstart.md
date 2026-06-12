# Quickstart

> Get from install to first retrieval in about 10 minutes. See the [documentation home](../../README.md) for the full outline.

## 1. Prerequisites

**Python 3.11+** required.

### Using uv (recommended)

```bash
cd contextseek
uv sync
source .venv/bin/activate
```

### Using pip

```bash
cd contextseek
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

### Optional extras

```bash
pip install -e ".[http]"                    # HTTP server
pip install -e ".[langchain,openai]"        # LangChain + OpenAI embeddings
```

## 2. Minimal example (InMemory)

```python
from contextseek import ContextSeek

ctx = ContextSeek.from_settings()  # default InMemory backend

item = ctx.add(
    "User prefers answers in English",
    scope="acme/proj/user1",
    source="conversation",
)
print(f"Wrote: id={item.id}, stage={item.stage.value}")

response = ctx.retrieve("English answers", scope="acme/proj/user1", k=10)
for hit in response:
    preview = hit.item.summary or hit.item.content_text
    print(f"  [{hit.item.stage.value}] layer={hit.layer} | {preview[:50]}")
```

## 3. File persistence

```python
from contextseek import ContextSeek, ContextSeekSettings
from contextseek.config.settings import StorageSettings

settings = ContextSeekSettings(
    storage=StorageSettings(backend="file", path=".contextseek/data"),
)
ctx = ContextSeek.from_settings(settings)
```

Or use a `.env` file (see [.env.example](../../../.env.example) at the repo root):

```env
STORAGE_BACKEND=file
STORAGE_PATH=.contextseek/data
```

## 4. Retrieve, expand, and agent tools

```python
response = ctx.retrieve(
    "database",
    scope="acme/proj/user1",
    k=10,
    filters={"stage": "knowledge"},
)

full_items = ctx.expand(list(response)[:2])

for spec in ctx.tools():
    print(spec.to_openai())
```

## 5. Vector retrieval (optional)

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
RETRIEVAL_RECALL_ROUTES=["phrase","terms","vector"]
```

## 6. Example scripts

```bash
uv run python examples/full_pipeline_file.py
uv run python examples/research_agent_demo.py
```

## 7. HTTP / MCP / CLI

```bash
uvicorn contextseek.http.server:app --port 8000
contextseek-mcp-stdio
contextseek add --scope acme/proj/user --content "fact" --source cli
contextseek retrieve --scope acme/proj/user --query "fact" --k 5
```

Next: [Core concepts](../guides/core-concepts.md) · [Write & retrieve](../guides/write-and-retrieve.md)
