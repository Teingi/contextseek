# ContextSeek

[![PyPI version](https://img.shields.io/pypi/v/contextseek)](https://pypi.org/project/contextseek/)
[![PyPI downloads](https://img.shields.io/pypi/dm/contextseek)](https://pypi.org/project/contextseek/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://pypi.org/project/contextseek/)
[![License Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-community-5865F2?logo=discord&logoColor=white)](https://discord.com/invite/74cF8vbNEs)

面向 AI Agent 的语义上下文基础设施。[English](README.md)

## ContextSeek 是什么

ContextSeek 是一个位于 LLM 与 Agent 运行时之间的上下文层，让 Agent 能够跨会话持久化、检索和演进上下文——而不必把这些数据分散到 JSONL 日志、向量库或独立的记忆服务里。

所有数据统一表示为 `ContextItem`：一个携带内容、来源（数据从哪来、置信度多少）、关联关系以及成熟度元信息的基本单元。条目沿 `raw → extracted → knowledge → skill` 的生命周期自动推进，Agent 不需要手动管理分层或摘要。

ContextSeek 与存储无关。InMemory 和文件后端适合开发与单进程场景；OceanBase 后端在生产环境提供 HNSW 向量 + 全文混合检索能力。

## 为什么需要它

Agent 运行时会快速积累大量数据：执行轨迹、检索片段、工具调用结果、用户反馈。这些数据往往在会话结束时丢弃，或散落在多个持久化层中，缺乏统一的 schema、来源追踪和质量元信息。

ContextSeek 从一个不同的前提出发：上下文应当是一等资产——可按语义查询检索，可按证据链审计，可从原始观测演进为精炼知识。同一份上下文可以服务于推理时的召回、运行后的调试、轨迹对比评测，以及离线训练，无需重新导入独立的流水线。

## 快速开始

```bash
pip install contextseek
```

```python
from contextseek import ContextSeek

ctx = ContextSeek.from_settings()  # 自动读取 .env 或环境变量

# 写入
ctx.add(
    "OceanBase 是一款金融级分布式数据库，支持 HTAP 混合负载",
    scope="acme/db/engineer",
    source="wiki",
)

# 检索（排名 SearchHit；默认返回 L1 摘要）
for hit in ctx.retrieve("分布式数据库", scope="acme/db/engineer", k=10):
    print(f"[{hit.item.stage.value}] score={hit.score:.2f} | {hit.item.summary[:60]}")
```

通过 `.env` 配置（参见 [.env.example](.env.example)）或在代码中构造 `ContextSeekSettings`。存储后端、Embedding 提供方和 LLM 是三个必要配置项。

## 文档

- [快速上手 (ZH)](docs/zh/getting-started/quickstart.md) / [Getting started (EN)](docs/en/getting-started/quickstart.md)：安装、`.env` 配置，以及核心操作的完整演示。
- [客户端 API 参考](docs/zh/reference/api.md)：`add`、`retrieve`、`expand`、`compact`、`dream`、`evidence_chain` 等方法的完整签名。
- [配置参考](docs/zh/getting-started/configuration.md)：所有环境变量与 `ContextSeekSettings` 字段。
- [DataPlug 指南](docs/zh/guides/integrations/dataplugs.md)：如何从 RAG 流水线、记忆库、执行轨迹及工具注册表导入数据。
- [示例](examples/README.md)：常见工作流的完整示例脚本。
- [AppWorld 评测](eval/appworld/README.md) / [τ-bench 评测](eval/taubench/README.md)：可选评测脚手架，有独立的依赖与配置要求。

## 工作原理

- **统一对象模型** — 记忆、知识、轨迹、技能全部是 `ContextItem`。每条条目携带强制 `Provenance`（来源类型、来源 id、置信度）和有类型的 `Link` 边（支持、反驳、衍生、替代），支持构建完整的 `EvidenceChain` DAG 及置信度传播。
- **内容分层** — L0（约 100 token）用于 Embedding 召回；L1（约 2k token）是 `retrieve()` 的默认返回面；L2（完整正文）通过 `expand()` 按需升档。
- **检索编排器** — 关键词 + 向量混合召回，可选 LLM 重排序，基于 scope 路由。返回排名 `SearchHit` 行，通过 `ctx.tools()` 向 OpenAI 或 Anthropic Agent 暴露工具描述。
- **EvolutionEngine** — 监测可合并、可消解冲突、可推进阶段或可提炼为技能的条目，在写入后增量运行，也可通过 `compact()` 显式触发。
- **DreamEngine** — 闲时进行模式整合与跨簇假设生成，通过 `dream()` 触发。
- **HTTP + MCP 服务** — 通过 FastAPI 和 Model Context Protocol 对外暴露相同的操作，支持远程 Agent 集成。

## 开发

```bash
uv sync
uv run pytest tests/ -q
uv run python examples/full_pipeline_file.py
```

## 相关项目

- [seekvfs](https://github.com/ob-labs/seekvfs) — 底层虚拟文件系统

## License

[Apache License 2.0](LICENSE)
