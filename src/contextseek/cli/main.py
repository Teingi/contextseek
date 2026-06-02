"""Local CLI for ContextSeek business-level operations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from contextseek.client.contextseek import ContextSeek
from contextseek.domain.serialization import (
    deserialize_context_item,
    serialize_context_item,
)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for commands."""
    parser = argparse.ArgumentParser(prog="contextseek")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add
    add_parser = subparsers.add_parser("add", help="add a context item")
    add_parser.add_argument("--scope", required=True)
    add_parser.add_argument("--content", required=True)
    add_parser.add_argument("--source", default="cli")
    add_parser.add_argument("--tags", default="")

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="retrieve ranked SearchHits (L1 summaries by default; --full for L0)",
    )
    retrieve_parser.add_argument("--scope", required=True)
    retrieve_parser.add_argument("--query", required=True)
    retrieve_parser.add_argument("--k", type=int, default=10)
    retrieve_parser.add_argument(
        "--full",
        action="store_true",
        help="return L0 full content instead of L1 summaries",
    )

    expand_parser = subparsers.add_parser(
        "expand",
        help="expand previously-retrieved item ids to L0 full content",
    )
    expand_parser.add_argument("--scope", required=True)
    expand_parser.add_argument(
        "--ids",
        required=True,
        help="comma-separated list of item ids",
    )

    # compact
    compact_parser = subparsers.add_parser("compact", help="compact/evolve scope")
    compact_parser.add_argument("--scope", required=True)
    compact_parser.add_argument("--dry-run", action="store_true")

    # forget
    forget_parser = subparsers.add_parser("forget", help="soft-delete an item")
    forget_parser.add_argument("--scope", required=True)
    forget_parser.add_argument("--item-id", required=True)
    forget_parser.add_argument("--reason", default="cli_forget")

    delete_parser = subparsers.add_parser(
        "delete", help="permanently remove an item from storage (adapter delete)"
    )
    delete_parser.add_argument("--scope", required=True)
    delete_parser.add_argument("--item-id", required=True)
    delete_parser.add_argument("--reason", default="cli_delete")
    delete_parser.add_argument(
        "--no-propagate",
        action="store_true",
        help="skip invalidation propagation to dependent items",
    )

    # overview (stage distribution + evolution candidate counts)
    evo_parser = subparsers.add_parser(
        "overview", help="scope summary: stage counts and evolution-style hints"
    )
    evo_parser.add_argument("--scope", required=True)

    # tools — print LLM tool spec for retrieve/expand
    tools_parser = subparsers.add_parser(
        "tools",
        help="print ContextSeek LLM tool spec (OpenAI/Anthropic format)",
    )
    tools_parser.add_argument(
        "--format",
        choices=["openai", "anthropic"],
        default="openai",
    )

    # metrics
    subparsers.add_parser("metrics", help="print prometheus metrics")

    # dream
    dream_parser = subparsers.add_parser(
        "dream", help="trigger dream cycle (consolidation + divergence)"
    )
    dream_parser.add_argument("--scope", required=True)
    dream_parser.add_argument("--dry-run", action="store_true")

    # feedback
    feedback_parser = subparsers.add_parser(
        "feedback", help="apply relevance feedback to an item"
    )
    feedback_parser.add_argument("--scope", required=True)
    feedback_parser.add_argument("--item-id", required=True)
    feedback_parser.add_argument(
        "--score", type=float, required=True, help="feedback score delta (-1.0 to 1.0)"
    )
    feedback_parser.add_argument("--reason", default="")

    # upstream
    upstream_parser = subparsers.add_parser(
        "upstream", help="walk derived_from/supported_by links to find upstream items"
    )
    upstream_parser.add_argument("--scope", required=True)
    upstream_parser.add_argument("--item-id", required=True)

    # evidence-chain
    ec_parser = subparsers.add_parser(
        "evidence-chain", help="compute full evidence chain DAG for an item"
    )
    ec_parser.add_argument("--scope", required=True)
    ec_parser.add_argument("--item-id", required=True)
    ec_parser.add_argument("--max-depth", type=int, default=10)

    # chain-confidence
    cc_parser = subparsers.add_parser(
        "chain-confidence", help="quick propagated confidence lookup for an item"
    )
    cc_parser.add_argument("--scope", required=True)
    cc_parser.add_argument("--item-id", required=True)

    # skill-tools
    st_parser = subparsers.add_parser(
        "skill-tools", help="export tool/mcp skills as LLM tool definitions"
    )
    st_parser.add_argument("--scope", required=True)
    st_parser.add_argument(
        "--fmt", choices=["openai", "anthropic", "mcp"], default="openai"
    )
    st_parser.add_argument(
        "--query", default=None, help="optional semantic search query"
    )
    st_parser.add_argument("--k", type=int, default=20)

    # skill-context
    sc_parser = subparsers.add_parser(
        "skill-context", help="render prompt skills as a system prompt block"
    )
    sc_parser.add_argument("--scope", required=True)
    sc_parser.add_argument(
        "--query", default=None, help="optional semantic search query"
    )
    sc_parser.add_argument("--k", type=int, default=5)

    # skill-import
    si_parser = subparsers.add_parser(
        "skill-import", help="import skills from Hermes, OpenAI, or MCP format"
    )
    si_parser.add_argument("--scope", required=True)
    si_parser.add_argument(
        "--format", choices=["hermes", "openai", "mcp"], required=True
    )
    si_parser.add_argument(
        "--path",
        required=True,
        help="directory path (hermes) or JSON file path (openai/mcp)",
    )

    # items
    items_parser = subparsers.add_parser("items", help="list all items in a scope")
    items_parser.add_argument("--scope", required=True)
    items_parser.add_argument(
        "--stage", default=None, help="filter by stage (raw/extracted/knowledge/skill)"
    )

    return parser


def run_cli(
    argv: Sequence[str] | None = None, *, client: ContextSeek | None = None
) -> int:
    """Execute CLI command and return process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = client or ContextSeek.from_settings()

    if args.command == "add":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        item = ctx.add(
            args.content,
            scope=args.scope,
            source=args.source,
            tags=tags,
        )
        print(
            json.dumps({"id": item.id, "stage": item.stage.value}, ensure_ascii=False)
        )
        return 0

    if args.command == "retrieve":
        response = ctx.retrieve(
            args.query,
            scope=args.scope,
            k=args.k,
            full=args.full,
        )
        output = {
            "items": [
                {
                    "id": h.item.id,
                    "score": h.score,
                    "layer": h.layer,
                    "summary": h.item.summary,
                    "content": h.item.content_text if h.layer == "full" else None,
                }
                for h in response
            ],
            "_meta": {
                "layer": response.meta.layer,
                "full_via": response.meta.full_via,
                "hint": response.meta.hint,
            },
        }
        print(json.dumps(output, ensure_ascii=False))
        return 0

    if args.command == "expand":
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
        items: list = []
        for iid in ids:
            ref = ctx.resolver.ref_for(args.scope, iid)
            payload = ctx.adapter.read(ref)
            if payload is None:
                continue
            try:
                items.append(deserialize_context_item(payload))
            except (KeyError, TypeError, ValueError):
                continue
        print(
            json.dumps(
                {"items": [serialize_context_item(it) for it in items]},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "compact":
        report = ctx.compact(scope=args.scope, dry_run=args.dry_run)
        print(
            json.dumps(
                {
                    "merged": report.merged_count,
                    "archived": report.archived_count,
                    "evolved": report.evolved_count,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "forget":
        ref = (
            args.item_id
            if args.item_id.startswith(ctx.resolver.scheme)
            else ctx.resolver.ref_for(args.scope, args.item_id)
        )
        ctx.forget(ref, scope=args.scope, reason=args.reason)
        print(json.dumps({"status": "ok", "id": args.item_id}, ensure_ascii=False))
        return 0

    if args.command == "delete":
        ref = (
            args.item_id
            if args.item_id.startswith(ctx.resolver.scheme)
            else ctx.resolver.ref_for(args.scope, args.item_id)
        )
        ctx.delete(
            ref,
            scope=args.scope,
            reason=args.reason,
            propagate=not args.no_propagate,
        )
        print(json.dumps({"status": "ok", "id": args.item_id}, ensure_ascii=False))
        return 0

    if args.command == "overview":
        report = ctx.overview(scope=args.scope)
        print(
            json.dumps(
                {
                    "total_items": report.total_items,
                    "stage_distribution": report.stage_distribution,
                    "pending_extraction": report.pending_extraction,
                    "pending_convergence": report.pending_convergence,
                    "distill_candidates": report.distill_candidates,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "tools":
        specs = ctx.tools()
        if args.format == "openai":
            payload = [s.to_openai() for s in specs]
        else:
            payload = [s.to_anthropic() for s in specs]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "metrics":
        print(ctx.audit_log.export_prometheus() if ctx.audit_log is not None else "")
        return 0

    if args.command == "dream":
        report = ctx.dream(scope=args.scope, dry_run=args.dry_run)
        print(
            json.dumps(
                {
                    "total_dream_items": report.total_dream_items,
                    "consolidation_patterns": report.consolidation.patterns_found,
                    "consolidation_items": len(report.consolidation.items),
                    "divergence_items": len(report.divergence.items)
                    if report.divergence
                    else 0,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "feedback":
        ref = (
            args.item_id
            if args.item_id.startswith(ctx.resolver.scheme)
            else ctx.resolver.ref_for(args.scope, args.item_id)
        )
        ctx.feedback(ref, scope=args.scope, score=args.score, reason=args.reason)
        print(json.dumps({"status": "ok", "id": args.item_id}, ensure_ascii=False))
        return 0

    if args.command == "upstream":
        ref = (
            args.item_id
            if args.item_id.startswith(ctx.resolver.scheme)
            else ctx.resolver.ref_for(args.scope, args.item_id)
        )
        chain = ctx.upstream(ref, scope=args.scope)
        print(
            json.dumps(
                {"items": [serialize_context_item(it) for it in chain]},
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "evidence-chain":
        ref = (
            args.item_id
            if args.item_id.startswith(ctx.resolver.scheme)
            else ctx.resolver.ref_for(args.scope, args.item_id)
        )
        chain = ctx.evidence_chain(ref, scope=args.scope, max_depth=args.max_depth)
        print(json.dumps(chain.to_dict(), ensure_ascii=False))
        return 0

    if args.command == "chain-confidence":
        ref = (
            args.item_id
            if args.item_id.startswith(ctx.resolver.scheme)
            else ctx.resolver.ref_for(args.scope, args.item_id)
        )
        confidence = ctx.chain_confidence(ref, scope=args.scope)
        print(json.dumps({"confidence": confidence}, ensure_ascii=False))
        return 0

    if args.command == "skill-tools":
        tools = ctx.skill_tools(
            args.scope, fmt=args.fmt, query=args.query or None, k=args.k
        )
        print(json.dumps({"tools": tools}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "skill-context":
        context = ctx.skill_context(args.scope, query=args.query or None, k=args.k)
        print(json.dumps({"context": context}, ensure_ascii=False))
        return 0

    if args.command == "skill-import":
        from contextseek.plugs.skills import (
            HermesSkillImporter,
            MCPToolImporter,
            OpenAIFunctionImporter,
        )

        if args.format == "hermes":
            plug = HermesSkillImporter(args.path)
        elif args.format == "openai":
            with open(args.path, encoding="utf-8") as f:
                functions = json.load(f)
            plug = OpenAIFunctionImporter(functions)
        else:  # mcp
            with open(args.path, encoding="utf-8") as f:
                mcp_data = json.load(f)
            tools_list = (
                mcp_data if isinstance(mcp_data, list) else mcp_data.get("tools", [])
            )
            plug = MCPToolImporter(tools_list)

        ctx.plug(plug, scope=args.scope)
        skills = ctx.skills(args.scope)
        print(
            json.dumps(
                {"imported": len(skills), "scope": args.scope}, ensure_ascii=False
            )
        )
        return 0

    if args.command == "items":
        from contextseek.domain.stages import Stage

        stage = Stage(args.stage) if args.stage else None
        result_items = ctx.items(scope=args.scope, stage=stage)
        print(
            json.dumps(
                {"items": [serialize_context_item(it) for it in result_items]},
                ensure_ascii=False,
            )
        )
        return 0

    return 1


def main() -> int:
    """Entry point used by `python -m contextseek.cli.main`."""
    return run_cli()
