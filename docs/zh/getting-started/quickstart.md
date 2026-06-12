# 快速上手

> 从安装到第一次检索，约 10 分钟。完整文档结构见 [文档中心](../../README.md)。

## 1. 环境准备

需要 **Python 3.11+**。

### 使用 uv（推荐）

```bash
cd contextseek
uv sync
source .venv/bin/activate
```

### 使用 pip

```bash
cd contextseek
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

### 可选依赖

```bash
pip install -e ".[http]"                    # HTTP 服务
pip install -e ".[langchain,openai]"        # LangChain + OpenAI embedding
```

## 2. 最小示例（InMemory）

```python
from contextseek import ContextSeek

ctx = ContextSeek.from_settings()  # 默认 InMemory 后端

item = ctx.add(
    "用户偏好使用中文回答",
    scope="acme/proj/user1",
    source="conversation",
)
print(f"写入: id={item.id}, stage={item.stage.value}")

response = ctx.retrieve("中文回答", scope="acme/proj/user1", k=10)
for hit in response:
    preview = hit.item.summary or hit.item.content_text
    print(f"  [{hit.item.stage.value}] layer={hit.layer} | {preview[:50]}")
```

## 3. 文件持久化

```python
from contextseek import ContextSeek, ContextSeekSettings
from contextseek.config.settings import StorageSettings

settings = ContextSeekSettings(
    storage=StorageSettings(backend="file", path=".contextseek/data"),
)
ctx = ContextSeek.from_settings(settings)
```

或通过 `.env`（参见仓库根目录 [.env.example](../../../.env.example)）：

```env
STORAGE_BACKEND=file
STORAGE_PATH=.contextseek/data
```

## 4. 检索、升档与 Agent 工具

```python
response = ctx.retrieve(
    "数据库",
    scope="acme/proj/user1",
    k=10,
    filters={"stage": "knowledge"},
)

full_items = ctx.expand(list(response)[:2])

for spec in ctx.tools():
    print(spec.to_openai())
```

## 5. 向量检索（可选）

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
RETRIEVAL_RECALL_ROUTES=["phrase","terms","vector"]
```

## 6. 示例脚本

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

下一步：[核心概念](../guides/core-concepts.md) · [写入与检索](../guides/write-and-retrieve.md)
