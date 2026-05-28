"""Launch-event demo: LangGraph graphs for white-screen comparison.

baseline         — plain LangChain agent, no context memory
contextseek_agent — same agent + ContextSeekMiddleware drawing from prior-session lessons
contextseek_live  — same agent + ContextSeekMiddleware learning in-session (no seed)

Run server:   langgraph dev
Seed lessons: python seed.py  (run once before the event)
UI:           https://agentchat.vercel.app  →  Deployment URL: http://localhost:2024
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `contextseek` importable when running from examples/demo/
_src = Path(__file__).resolve().parents[2] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)
except Exception:
    pass

import seekvfs
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from contextseek import ContextSeek
from contextseek.bridges.langchain.middleware import ContextSeekMiddleware
from contextseek.storage import FileBackend, SeekVFSStorageAdapter

from tools import TOOLS  # noqa: E402  (local import, resolved by langgraph dev CWD)


# Persistent store — seeded once by seed.py, read on every demo run.
DEMO_SCOPE = "demo/launch-2026"
LIVE_SCOPE = "demo/live"
_STORE_ROOT = Path(__file__).resolve().parent / ".contextseek" / "demo_store"


def _build_ctx() -> ContextSeek:
    _STORE_ROOT.mkdir(parents=True, exist_ok=True)
    backend = FileBackend(root_dir=_STORE_ROOT, scheme="contextseek://")
    vfs = seekvfs.VFS({"contextseek://": {"backend": backend}}, scheme="contextseek://")
    adapter = SeekVFSStorageAdapter(vfs)
    return ContextSeek(adapter=adapter)


_model = ChatOpenAI(
    model=os.getenv("LLM_MODEL", "gpt-4o"),
    temperature=0.0,
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("LLM_BASE_URL") or None,
)

# ── Graph 1: baseline (no context memory) ────────────────────────────────────
baseline_graph = create_agent(model=_model, tools=TOOLS, middleware=[])

# ── Graph 2: ContextSeek-enhanced (reads prior-session lessons) ──────────────
_ctx = _build_ctx()

contextseek_graph = create_agent(
    model=_model,
    tools=TOOLS,
    middleware=[
        ContextSeekMiddleware(
            ctx=_ctx,
            retrieval_k=3,
            retrieval_tags=["demo_policy_lesson"],
            tool_arg_overrides={
                "query_monthly_spend": {"page_limit": 20, "mode": "safe"},
                "create_budget_plan": {"currency": "CNY", "schema_version": "v2"},
            },
            auto_store=False,
            auto_compact=False,
            scope=DEMO_SCOPE,
        )
    ],
)

# ── Graph 3: ContextSeek live-learning (no seed required) ────────────────────
contextseek_live_graph = create_agent(
    model=_model,
    tools=TOOLS,
    middleware=[
        ContextSeekMiddleware(
            ctx=_ctx,
            retrieval_k=5,
            auto_store=True,
            auto_compact=False,
            scope=LIVE_SCOPE,
        )
    ],
)
