"""End-to-end coverage for the M1-M3 ContextSeek flow."""

from datetime import datetime, timedelta, timezone
from typing import Iterator

from contextseek.plugs.core.protocols import PlugMeta, RawEvent
from contextseek.client.contextseek import ContextSeek
from contextseek.domain.links import LinkType
from contextseek.domain.provenance import SourceType
from contextseek.domain.stages import Stage
from contextseek.evolution.engine import EvolutionEngine
from contextseek.evolution.rules import EvolutionRule


class StaticPlug:
    """Tiny plug used to verify scope and provenance semantics."""

    def metadata(self) -> PlugMeta:
        return PlugMeta(
            name="static_plug",
            source_type=SourceType.document.value,
            description="test plug",
        )

    def stream(self) -> Iterator[RawEvent]:
        yield RawEvent(
            content="Deployment requires migration checks from plug",
            source="wiki://deploy",
            tags=["deploy"],
        )


def test_m1_to_m3_context_flow() -> None:
    scope = "acme/bot/user_123"
    ctx = ContextSeek(
        evolution_engine=EvolutionEngine(
            rules=[
                EvolutionRule(
                    name="extract_from_trace",
                    source_stage=Stage.raw,
                    target_stage=Stage.extracted,
                    link_type=LinkType.derived_from,
                    min_age_seconds=0,
                    content_filter="trace_structure",
                )
            ]
        )
    )

    ctx.plug(StaticPlug(), scope=scope)
    plug_response = ctx.retrieve("migration checks", scope=scope, k=10)
    assert len(plug_response) > 0
    first = plug_response.items[0].item
    assert first.scope == scope
    assert first.provenance.source_id == "wiki://deploy"

    long_item = ctx.add(
        "deployment budget sentinel " + ("detail " * 200),
        scope=scope,
        source="wiki://long",
        source_type=SourceType.document,
    )
    long_item.summary = "deployment budget sentinel summary"
    ctx._write_item(long_item)

    # Default retrieve returns L1 summary in content when summary is present
    summary_response = ctx.retrieve("budget sentinel", scope=scope, k=5)
    matched = [h for h in summary_response if h.item.id == long_item.id]
    assert matched, "long_item should be retrievable"
    assert matched[0].layer == "summary"
    assert matched[0].item.summary == long_item.summary

    # full=True returns the full L0 content
    full_response = ctx.retrieve("budget sentinel", scope=scope, k=5, full=True)
    matched_full = [h for h in full_response if h.item.id == long_item.id]
    assert matched_full and matched_full[0].layer == "full"
    assert matched_full[0].item.content_text.startswith("deployment budget sentinel")

    item_ref = ctx.resolver.ref_for(scope, long_item.id)
    # Capture boost before feedback: retrieve() in inject mode (module 0 signal
    # loop) already applied small per-injection boosts, so assert the feedback
    # *delta* rather than an absolute value.
    before_item = ctx._read_item(item_ref)
    assert before_item is not None
    boost_before = before_item.relevance_boost
    ctx.feedback(item_ref, scope=scope, score=0.5, reason="accepted")
    updated_item = ctx._read_item(item_ref)
    assert updated_item is not None
    assert abs(updated_item.relevance_boost - (boost_before + 0.5)) < 1e-9
    assert updated_item.access_count >= 1

    raw_trace = ctx.add(
        {"input": "deploy failed", "tool_calls": [], "output": "migration missing"},
        scope=scope,
        source="trace-1",
        source_type=SourceType.trace_extraction,
    )
    raw_trace.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    ctx._write_item(raw_trace)

    report = ctx.compact(scope=scope)
    assert report.evolved_count > 0

    extracted = [
        item
        for item in ctx.items(scope=scope, stage=Stage.extracted)
        if any(link.target_id == raw_trace.id for link in item.links)
    ]
    assert extracted

    extracted_ref = ctx.resolver.ref_for(scope, extracted[0].id)
    chain = ctx.upstream(extracted_ref, scope=scope)
    assert [item.id for item in chain] == [extracted[0].id, raw_trace.id]


def test_signal_loop_drives_extraction_without_manual_feedback() -> None:
    """Module 0 end-to-end: pure retrieval (no feedback()) supplies the fuel
    (access_count + boost) that lets a plain-text raw item reach extracted."""
    scope = "acme/bot/signal_loop"
    ctx = ContextSeek(evolution_engine=EvolutionEngine())

    item = ctx.add(
        "remember to rotate the staging database credentials every release",
        scope=scope,
        source="note://ops",
        source_type=SourceType.external_api,
    )
    assert item.stage == Stage.raw
    item_ref = ctx.resolver.ref_for(scope, item.id)

    # Retrieve several times — inject-mode attribution accrues access + boost.
    for _ in range(4):
        ctx.retrieve("rotate database credentials", scope=scope, k=5)

    fueled = ctx._read_item(item_ref)
    assert fueled is not None
    assert fueled.access_count >= 3  # text_extract_min_access default
    assert fueled.lineage_access_count >= 3
    assert fueled.relevance_boost > 1.0  # injection boosts accumulated

    report = ctx.compact(scope=scope)
    assert report.evolved_count > 0
    extracted = list(ctx.items(scope=scope, stage=Stage.extracted))
    assert extracted, "pure-retrieval signal loop should drive raw → extracted"


def test_compact_flushes_evolution_metrics_to_audit() -> None:
    """Module 5: compact() writes the funnel (stage inventory + conversion +
    events) into the audit sink and emits Prometheus-exportable metric points."""
    from contextseek.observability.audit import AuditLog

    scope = "acme/bot/observability"
    audit = AuditLog()
    ctx = ContextSeek(evolution_engine=EvolutionEngine(), audit_log=audit)

    ctx.add(
        "rotate the staging database credentials before every production release",
        scope=scope,
        source="note://ops",
        source_type=SourceType.external_api,
    )
    for _ in range(4):
        ctx.retrieve("rotate credentials", scope=scope, k=5)

    ctx.compact(scope=scope)

    record = audit.latest(action="compact")
    assert record is not None
    detail = record.detail
    assert "stage_distribution" in detail
    assert "conversion" in detail
    assert "events" in detail and detail["events"]
    # Funnel metrics are exportable for the dashboard.
    metric_names = {m.name for m in record.metrics}
    assert "evolution_stage_inventory" in metric_names
    assert "evolution_conversion_rate" in metric_names

    # The retrieve path recorded usage_recorded events (module 0 attribution).
    retrieve_rec = audit.latest(action="retrieve")
    assert retrieve_rec is not None
    assert retrieve_rec.detail.get("usage_events")
