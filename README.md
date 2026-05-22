# ContextSeek

[![PyPI version](https://img.shields.io/pypi/v/contextseek)](https://pypi.org/project/contextseek/)
[![PyPI downloads](https://img.shields.io/pypi/dm/contextseek)](https://pypi.org/project/contextseek/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://pypi.org/project/contextseek/)
[![License Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-community-5865F2?logo=discord&logoColor=white)](https://discord.com/invite/74cF8vbNEs)

Semantic context infrastructure for AI agents. [中文文档](README_CN.md)

## What ContextSeek is

ContextSeek is a context layer that sits between LLMs and agent runtimes. It gives agents a place to store, retrieve, and evolve context across sessions — without scattering that context across JSONL logs, vector stores, or separate memory services.

Everything is represented as a `ContextItem` — a single unit that carries content, provenance (where it came from and how confident the system is), links to related items, and maturity metadata. Items advance through a lifecycle — `raw → extracted → knowledge → skill` — that the system drives automatically, so agents do not manage tiering or summarization by hand.

ContextSeek is storage-agnostic. InMemory and file backends work for development and single-process use. OceanBase adds hybrid HNSW vector + full-text search for production deployments.

## Why it exists

Agents accumulate runtime data quickly: execution traces, retrieved passages, tool results, user feedback. That data is often discarded at session end or scattered across multiple persistence layers with no consistent schema, source tracking, or quality metadata.

ContextSeek starts from the assumption that context should be a first-class asset: retrievable by semantic query, auditable by provenance chain, and evolvable from raw observations toward refined knowledge. The same context can then serve retrieval during inference, debugging after a run, evaluation across trajectory comparisons, and offline training — without re-ingestion into separate pipelines.

## Quick Start

```bash
pip install contextseek
```

```python
from contextseek import ContextSeek

ctx = ContextSeek.from_settings()  # reads .env or environment variables

# Write
ctx.add(
    "OceanBase is a financial-grade distributed database supporting HTAP workloads",
    scope="acme/db/engineer",
    source="wiki",
)

# Retrieve (ranked SearchHits; L1 summaries by default)
for hit in ctx.retrieve("distributed database", scope="acme/db/engineer", k=10):
    print(f"[{hit.item.stage.value}] score={hit.score:.2f} | {hit.item.summary[:60]}")
```

Configure via `.env` (see [.env.example](.env.example)) or `ContextSeekSettings` in code. A storage backend, an embedding provider, and an LLM are the three required pieces.

## Documentation

- [Getting started (EN)](docs/en/getting-started/quickstart.md) / [快速上手 (ZH)](docs/zh/getting-started/quickstart.md): installation, `.env` setup, and a walkthrough of the core operations.
- [Client API reference](docs/en/reference/api.md): full method signatures for `add`, `retrieve`, `expand`, `compact`, `dream`, `evidence_chain`, and more.
- [Configuration reference](docs/en/getting-started/configuration.md): all environment variables and `ContextSeekSettings` fields.
- [DataPlugs](docs/en/guides/integrations/dataplugs.md): how to ingest from RAG pipelines, memory stores, execution traces, and skill / tool registries.
- [Examples](examples/README.md): annotated scripts for common workflows.
- [AppWorld eval](eval/appworld/README.md) / [τ-bench eval](eval/taubench/README.md): optional evaluation harnesses with their own setup requirements.

## How it works

- **Unified object model** — all context — memory, knowledge, traces, skills — is a `ContextItem`. Items carry mandatory `Provenance` (source type, source id, confidence) and typed `Link` edges (supports, refutes, derives, supersedes), enabling a full `EvidenceChain` DAG with confidence propagation.
- **Content tiers** — L0 (~100 tokens) feeds embedding recall. L1 (~2 k tokens) is the default surface returned by `retrieve()`. L2 (full body) is available on demand via `expand()`.
- **Retrieval orchestrator** — keyword + vector hybrid recall, optional LLM reranking, and scope-based routing. Returns ranked `SearchHit` rows. Exposes tool specs for OpenAI and Anthropic agents via `ctx.tools()`.
- **EvolutionEngine** — watches for items that can be merged, resolved, advanced in stage, or distilled into skills. Runs incrementally after writes or on an explicit `compact()` call.
- **DreamEngine** — idle-time pattern consolidation and cross-cluster hypothesis generation, triggered via `dream()`.
- **HTTP + MCP servers** — expose the same operations over FastAPI and the Model Context Protocol for remote agent integrations.

## Development

```bash
uv sync
uv run pytest tests/ -q
uv run python examples/full_pipeline_file.py
```

## Related Projects

- [seekvfs](https://github.com/ob-labs/seekvfs) — underlying virtual filesystem

## License

[Apache License 2.0](LICENSE)
