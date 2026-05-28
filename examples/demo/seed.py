"""Seed the ContextSeek store with prior-session lessons.

Run this once before the launch-event demo to simulate an agent that has already
learned how the compliance gateway works through previous trial-and-error.

    uv run python examples/demo/seed.py

The seeded lessons will be retrieved by `contextseek_graph` at demo time.
`baseline_graph` has no access to this store and will fail as expected.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_src = Path(__file__).resolve().parents[2] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)
except Exception:
    pass

import seekvfs

from contextseek import ContextSeek, SourceType
from contextseek.bridges.deepagents import TraceSink
from contextseek.storage import FileBackend, SeekVFSStorageAdapter

DEMO_SCOPE = "demo/launch-2026"
STORE_ROOT = Path(__file__).resolve().parent / ".contextseek" / "demo_store"

# Prior-session lessons — what the agent discovered after hitting compliance errors.
_LESSONS = [
    {
        "id": "query_monthly_spend_params",
        "tags": [
            "compliance",
            "demo_policy_lesson",
            "query_monthly_spend",
            "gateway",
            "spend",
            "transaction",
            "月度支出",
            "交易总额",
            "总交易支出",
        ],
        "content": (
            "Tool: query_monthly_spend. "
            "Use this tool to look up monthly spend, total transaction spend, or transaction totals for a given month. "
            "IMPORTANT: the compliance gateway requires page_limit=20 and mode='safe'. "
            "Default values (page_limit=100, mode='fast') return COMPLIANCE_REJECTED. "
            "Always pass page_limit=20 and mode='safe' on the first call. "
            "中文提示：查询月度总交易支出时，必须传 page_limit=20 且 mode='safe'。"
        ),
        "trace_summary": (
            "Agent tried page_limit=100 mode='fast' to query monthly spend → COMPLIANCE_REJECTED. "
            "Retried page_limit=20 mode='safe' → TX_TOTAL:335.5. Lesson extracted."
        ),
    },
    {
        "id": "create_budget_plan_params",
        "tags": [
            "compliance",
            "demo_policy_lesson",
            "create_budget_plan",
            "gateway",
            "budget",
            "plan",
            "预算",
            "预算计划",
            "月度预算",
        ],
        "content": (
            "Tool: create_budget_plan. "
            "Use this tool to create a budget plan or monthly budget with spending categories. "
            "IMPORTANT: the compliance gateway requires currency='CNY' and schema_version='v2'. "
            "Default values (currency='USD', schema_version='v1') return COMPLIANCE_REJECTED. "
            "items_json must be a JSON list of objects each with 'name' and 'limit' fields. "
            "Example: [{\"name\": \"Rent\", \"limit\": 3000}, {\"name\": \"Food\", \"limit\": 1200}]. "
            "中文提示：创建预算计划时，必须传 currency='CNY' 且 schema_version='v2'。"
        ),
        "trace_summary": (
            "Agent tried currency='USD' schema_version='v1' to create budget plan → COMPLIANCE_REJECTED. "
            "Retried currency='CNY' schema_version='v2' with correct JSON → BUDGET_OK. "
            "Lesson extracted."
        ),
    },
    {
        "id": "policy_required_params_map",
        "tags": [
            "compliance",
            "demo_policy_lesson",
            "required_parameters",
            "required_params",
            "gateway_policy",
            "query_monthly_spend",
            "create_budget_plan",
        ],
        "content": (
            "Gateway policy required parameters map (must override tool defaults): "
            "query_monthly_spend requires page_limit=20 and mode='safe'; "
            "create_budget_plan requires currency='CNY' and schema_version='v2'. "
            "Even if these appear optional in tool signatures, they are required by policy. "
            "中文：网关策略要求覆盖默认值。query_monthly_spend 必须 page_limit=20、mode='safe'；"
            "create_budget_plan 必须 currency='CNY'、schema_version='v2'。"
        ),
        "trace_summary": (
            "Consolidated policy lesson: required parameter values override tool default values."
        ),
    },
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed launch-event demo lessons into ContextSeek store."
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not wipe the existing demo store before seeding.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not args.no_reset and STORE_ROOT.exists():
        shutil.rmtree(STORE_ROOT)
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    backend = FileBackend(root_dir=STORE_ROOT, scheme="contextseek://")
    vfs = seekvfs.VFS({"contextseek://": {"backend": backend}}, scheme="contextseek://")
    adapter = SeekVFSStorageAdapter(vfs)
    ctx = ContextSeek(adapter=adapter)

    traces = TraceSink.from_client(ctx, scope=DEMO_SCOPE)

    print(f"Seeding ContextSeek store at: {STORE_ROOT}")
    print(f"Scope: {DEMO_SCOPE}")
    print()

    for lesson in _LESSONS:
        item = ctx.add(
            lesson["content"],
            scope=DEMO_SCOPE,
            source="prior_session",
            source_type=SourceType.trace_extraction,
            tags=lesson["tags"],
        )
        # Pre-set summary so the middleware's _format_context_block injects it
        # (format_context_block reads item.summary, not item.content).
        item.summary = lesson["content"]
        ctx._write_item(item)

        traces.write_trace(
            task_id=lesson["id"],
            input_text="[prior session tool call]",
            output_text=lesson["trace_summary"],
            tool_calls=[{"tool": lesson["id"].split("_params")[0]}],
            status="success",
        )
        print(f"  ✓  [{lesson['id']}] seeded")

    print()
    print("Done. The contextseek_agent graph will retrieve these lessons at demo time.")
    print("The baseline_graph has no memory and will hit compliance errors as expected.")


if __name__ == "__main__":
    main()
