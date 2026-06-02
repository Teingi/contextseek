# 故障排查

常见问题及解决方案。

---

## 安装

### `ModuleNotFoundError: No module named 'contextseek'`

确认包已安装在当前 Python 环境中：

```bash
pip show contextseek
python -c "from contextseek import ContextSeek"
```

使用 `uv` 时：
```bash
uv run python -c "from contextseek import ContextSeek"
```

### `ModuleNotFoundError: No module named 'langchain_openai'`

需要安装可选 extra：

```bash
pip install "contextseek[langchain,openai]"      # OpenAI
pip install "contextseek[langchain,ollama]"       # Ollama
pip install "contextseek[langchain,huggingface]"  # HuggingFace
pip install "contextseek[oceanbase]"              # OceanBase
pip install "contextseek[http]"                   # FastAPI 服务
```

---

## 配置

### 没有从 `.env` 加载设置

ContextSeek 按以下顺序查找 `.env`：
1. `./`（当前工作目录）
2. `{repo_root}/`
3. `{repo_root}/examples/configs/`
4. 如已安装 `python-dotenv`，则使用 `find_dotenv(usecwd=True)`

从包含 `.env` 的目录运行脚本，或显式传入 settings：

```python
from contextseek import ContextSeek, ContextSeekSettings
from contextseek.config.settings import StorageSettings

ctx = ContextSeek.from_settings(
    ContextSeekSettings(storage=StorageSettings(backend="file", path="/data/ctx"))
)
```

### `OPENAI_API_KEY` 不生效

ContextSeek 不直接读取 API Key，由 LangChain 类读取。确保 Key 在环境中：

```bash
export OPENAI_API_KEY=sk-...
# 或在 .env 中：
OPENAI_API_KEY=sk-...
```

---

## 检索

### `retrieve()` 返回 0 条命中

**检查 1 — scope 中有内容吗？**
```python
items = ctx.items(scope="your/scope")
print(f"scope 中的条目数: {len(items)}")
```

**检查 2 — scope 拼写错误？** `retrieve(scope=...)` 是前缀匹配。`acme/bot` 能匹配 `acme/bot/user-1`，但不能匹配 `acme/bots`。

**检查 3 — 所有条目都被软删除了？**
```python
response = ctx.retrieve("query", scope="your/scope", include_deleted=True, k=10)
print(len(list(response)))
```

**检查 4 — 召回路由配置错误？** 如果条目写入时没有向量，但 `RETRIEVAL_RECALL_ROUTES=["vector"]` 仅用向量路由，则什么都找不到。确保 `phrase` 或 `terms` 在路由列表中。

### 命中结果不相关

- 启用 LLM 重排：`RETRIEVAL_RERANKER_MODE=llm`
- 召回路由加入 `vector`（需配置 Embedding）
- 检查条目是否有 L2 `abstract` 字段：运行 `ctx.items()` 并查看 `item.abstract`
- 尝试更宽泛的 `scope` 前缀，覆盖更多条目

### `retrieve()` 返回 L0 正文而非摘要（并伴有警告）

Summarizer 未配置。L1 字段为空，ContextSeek 回退为 L0 模式。开启方式：

```env
SUMMARIZER_PROVIDER=llm
LLM_PROVIDER=langchain
LLM_CLASS_PATH=langchain_openai.ChatOpenAI
LLM_MODEL=gpt-4o-mini
```

零配置开发模式下此为有意设计，并非 bug。

---

## 写入

### `ValueError: exact duplicate exists: <id>`

scope 中已存在内容完全相同的条目。处理方式：

1. 跳过本次 `add()`——条目已存在。
2. 如果相关性发生变化，通过 `feedback()` 更新现有条目。
3. 传入 `check_conflicts=False` 绕过去重（生产环境不推荐）。
4. 先调用 `ctx.forget(existing_id, ...)` 删除旧条目（如其已过时）。

### 写入成功但 `retrieve()` 找不到

- 检查 `item.searchable`——若条目立即被软删除（如去重冲突），该字段为 `False`。
- 检查 `item.stage`——若 `RETRIEVAL_RECALL_ROUTES` 过滤的 stage 与条目不符，则不会命中。
- 验证向量：若 `retrieve()` 使用 `vector` 路由，但条目写入时 Summarizer 未启用导致无向量，则不会出现在向量检索结果中。

---

## 演化

### `compact()` 无任何效果（merged=0, archived=0, evolved=0）

- 默认 `EVOLUTION_ENABLED=false`，只运行哈希去重。设置 `EVOLUTION_ENABLED=true`。
- 条目太少：`LIFECYCLE_COMPACT_MIN_ITEMS=5` 要求 scope 内至少 5 条。
- 条目太新：`EVOLUTION_EXTRACT_MIN_AGE_SECONDS=60`，等待条目达到最小年龄后才尝试提取。
- 聚类太小：`EVOLUTION_MIN_CLUSTER_SIZE=3`，需至少 3 条相似条目才能合并。

### `dream()` 生成 0 条条目

- scope 内条目太少（需要多条才能发现模式）。
- `DREAM_LLM_ENABLED=false` 且条目间关键词重叠不足以触发启发式模式。
- 先向 scope 中写入更多多样化内容再试。

---

## HTTP 服务

### 找不到 `uvicorn`

```bash
pip install "contextseek[http]"
uvicorn contextseek.http.server:app --port 8000
```

### 服务启动但 `/add` 返回 500

检查服务日志。常见原因：存储路径不可写，或 Embedding 模型未配置。先在本地用 `ContextSeek.from_settings()` 验证。

---

## MCP 服务

### MCP 客户端无法连接 stdio 服务

确认 `contextseek-mcp-stdio` 命令已通过 pip 安装。验证：

```bash
which contextseek-mcp-stdio
contextseek-mcp-stdio --help
```

---

## OceanBase

### 找不到 `pyobvector`

```bash
pip install "contextseek[oceanbase]"
```

### 连接被拒绝 / 超时

检查 `OB_HOST`、`OB_PORT`、`OB_USER`、`OB_PASSWORD` 是否正确设置，且 OceanBase 可从当前主机访问。OceanBase 需通过 `from_runtime_config()` 配合运行时配置文件实例化——默认 `from_settings()` 路径不实例化 OceanBase。

---

## 调试技巧

**查看审计记录：**
```python
import json
with open(".contextseek/audit.jsonl") as f:
    for line in f:
        rec = json.loads(line)
        if rec["status"] != "ok":
            print(rec)
```

**开启详细日志：**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
ctx = ContextSeek.from_settings()
```

**检查 settings 实际加载值：**
```python
from contextseek.config.settings import ContextSeekSettings
s = ContextSeekSettings()
print(s.storage.backend, s.embedding.provider, s.llm.provider)
```

---

[← 安装](getting-started/installation.md) · [配置](getting-started/configuration.md) · [GitHub Issues](https://github.com/ob-labs/contextseek/issues)
