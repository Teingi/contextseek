"""Evolution engine — orchestrates the full Stage progression pipeline.

Called by compact() and LifecycleScheduler to drive:
  raw → extracted → knowledge → skill
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from contextseek.domain.context_item import ContextItem, _utc_now
from contextseek.domain.inference import _is_trace_structure
from contextseek.domain.links import Link, LinkType
from contextseek.domain.provenance import Provenance, SourceType
from contextseek.domain.results import CompactReport, EvolutionEvent
from contextseek.domain.skill_ir import SkillIR
from contextseek.domain.stages import Stability, Stage
from contextseek.evolution.conflict import ConflictResolver
from contextseek.evolution.distiller import HeuristicDistillRule, SkillDistiller
from contextseek.evolution.extractor import Extractor, HeuristicExtractor
from contextseek.evolution.merger import ConvergenceMerger
from contextseek.evolution.rules import DEFAULT_RULES, EvolutionRule


def _skill_fingerprint(item: ContextItem) -> str | None:
    """Read a skill item's ``source_fingerprint`` (the distillation upsert key)."""
    return SkillIR.from_content(item.content).source_fingerprint


class EvolutionEngine:
    """Drives the evolution pipeline for a set of ContextItems.

    Usage::
        engine = EvolutionEngine()
        new_items, archived_items, report = engine.evolve(existing_items)
    """

    def __init__(
        self,
        *,
        rules: list[EvolutionRule] | None = None,
        extractor: Extractor | None = None,
        merger: ConvergenceMerger | None = None,
        distiller: SkillDistiller | None = None,
        strategy: Any | None = None,
        merge_synthesize_fn: Callable[[list[str]], str] | None = None,
        distill_decide_fn: Callable[[ContextItem], bool] | None = None,
        distill_render_fn: Callable[[ContextItem], dict[str, str]] | None = None,
        summarizer: Any | None = None,
        conflict_resolver: ConflictResolver | None = None,
        enable_conflict_resolution: bool = True,
        promote_decide_fn: Callable[[ContextItem], bool] | None = None,
    ):
        self._rules = rules or DEFAULT_RULES

        # Resolve strategy fields — fall back to hardcoded defaults when absent
        ephemeral_ttl = 3600.0
        merger_threshold = 0.72
        merger_min_cluster = 3
        merger_half_life = 7.0
        distiller_min_use = 10
        distiller_min_boost = 1.2
        if strategy is not None:
            ephemeral_ttl = getattr(strategy, "ephemeral_ttl_seconds", ephemeral_ttl)
            merger_threshold = getattr(
                strategy, "semantic_merge_threshold", merger_threshold
            )
            merger_min_cluster = getattr(
                strategy, "min_cluster_size", merger_min_cluster
            )
            merger_half_life = getattr(
                strategy, "decay_half_life_days", merger_half_life
            )
            distiller_min_use = getattr(
                strategy, "distill_min_use_count", distiller_min_use
            )
            distiller_min_boost = getattr(
                strategy, "distill_min_relevance_boost", distiller_min_boost
            )

        text_extract_min_access = 3
        heuristic_distill_min_use = 5
        heuristic_distill_min_age_days = 3.0
        heuristic_distill_min_boost = 1.1
        if strategy is not None:
            text_extract_min_access = getattr(
                strategy, "text_extract_min_access", text_extract_min_access
            )
            heuristic_distill_min_use = getattr(
                strategy, "heuristic_distill_min_use", heuristic_distill_min_use
            )
            heuristic_distill_min_age_days = getattr(
                strategy,
                "heuristic_distill_min_age_days",
                heuristic_distill_min_age_days,
            )
            heuristic_distill_min_boost = getattr(
                strategy, "heuristic_distill_min_boost", heuristic_distill_min_boost
            )

        # Evolution-deepening P0 fields (multi-path promotion, age fallback,
        # quality gate). All read via getattr so a bare/legacy strategy still works.
        text_extract_max_age_days = 7.0
        solo_promote_enabled = True
        solo_promote_min_lineage_access = 3
        solo_promote_min_boost = 1.1
        solo_promote_min_age_days = 1.0
        small_cluster_size = 2
        small_cluster_similarity = 0.85
        heuristic_distill_allow_raw = False
        knowledge_quality_min_len = 20
        if strategy is not None:
            text_extract_max_age_days = getattr(
                strategy, "text_extract_max_age_days", text_extract_max_age_days
            )
            solo_promote_enabled = getattr(
                strategy, "solo_promote_enabled", solo_promote_enabled
            )
            solo_promote_min_lineage_access = getattr(
                strategy,
                "solo_promote_min_lineage_access",
                solo_promote_min_lineage_access,
            )
            solo_promote_min_boost = getattr(
                strategy, "solo_promote_min_boost", solo_promote_min_boost
            )
            solo_promote_min_age_days = getattr(
                strategy, "solo_promote_min_age_days", solo_promote_min_age_days
            )
            small_cluster_size = getattr(
                strategy, "small_cluster_size", small_cluster_size
            )
            small_cluster_similarity = getattr(
                strategy, "small_cluster_similarity", small_cluster_similarity
            )
            heuristic_distill_allow_raw = getattr(
                strategy, "heuristic_distill_allow_raw", heuristic_distill_allow_raw
            )
            knowledge_quality_min_len = getattr(
                strategy, "knowledge_quality_min_len", knowledge_quality_min_len
            )

        self._text_extract_min_access = text_extract_min_access
        self._text_extract_max_age_days = text_extract_max_age_days
        self._solo_promote_enabled = solo_promote_enabled
        self._solo_min_lineage = solo_promote_min_lineage_access
        self._solo_min_boost = solo_promote_min_boost
        self._solo_min_age_days = solo_promote_min_age_days
        self._heuristic_allow_raw = heuristic_distill_allow_raw
        self._knowledge_quality_min_len = knowledge_quality_min_len
        self._promote_decide_fn = promote_decide_fn
        self._ephemeral_ttl = ephemeral_ttl
        self._extractor = extractor or HeuristicExtractor()
        self._merger = merger or ConvergenceMerger(
            similarity_threshold=merger_threshold,
            min_cluster_size=merger_min_cluster,
            half_life_days=merger_half_life,
            synthesize_fn=merge_synthesize_fn,
            small_cluster_size=small_cluster_size,
            small_cluster_similarity=small_cluster_similarity,
        )
        default_heuristic_rule = HeuristicDistillRule(
            min_access_count=heuristic_distill_min_use,
            min_age_days=heuristic_distill_min_age_days,
            min_relevance_boost=heuristic_distill_min_boost,
        )
        self._distiller = distiller or SkillDistiller(
            min_use_count=distiller_min_use,
            min_relevance_boost=distiller_min_boost,
            llm_decide_fn=distill_decide_fn,
            llm_distill_fn=distill_render_fn,
            heuristic_rule=default_heuristic_rule,
        )
        self._summarizer = summarizer

        conflict_threshold = 0.82
        enable_conflict = enable_conflict_resolution
        if strategy is not None:
            conflict_threshold = getattr(
                strategy, "conflict_sim_threshold", conflict_threshold
            )
            enable_conflict = getattr(
                strategy, "conflict_resolution_enabled", enable_conflict
            )
        self._enable_conflict = enable_conflict
        self._conflict_resolver = conflict_resolver or ConflictResolver(
            similarity_threshold=conflict_threshold,
        )

    def evolve(
        self, items: list[ContextItem]
    ) -> tuple[list[ContextItem], list[ContextItem], CompactReport]:
        """Run the full evolution pipeline.

        Returns:
            (new_items, archived_items, report):
            - new_items: newly created items (extracted/knowledge/skill)
            - archived_items: items that were superseded
            - report: summary of what happened
        """
        new_items: list[ContextItem] = []
        archived_items: list[ContextItem] = []
        report = CompactReport()
        events = report.events

        def emit(event: str, item: ContextItem, **fields: Any) -> None:
            events.append(
                EvolutionEvent(
                    event=event,
                    item_id=item.id,
                    ts=datetime.now(timezone.utc).isoformat(),
                    **fields,
                )
            )

        def record_hop(
            hop: str, *, attempted: int, succeeded: int, rejected: int
        ) -> None:
            report.conversion[hop] = {
                "attempted": attempted,
                "succeeded": succeeded,
                "rejected": rejected,
            }

        # Phase 0: conflict resolution (update vs drift). Runs first so retired
        # facts and quarantined drift don't feed downstream extraction/merge.
        if self._enable_conflict:
            resolution = self._conflict_resolver.resolve(items)
            archived_items.extend(resolution.touched)
            report.conflict_updated_count = len(resolution.updated)
            report.conflict_drift_count = len(resolution.quarantined)

        # Phase 1: raw → extracted (trace extraction)
        raw_traces = [
            it
            for it in items
            if it.stage == Stage.raw
            and not it.is_deleted
            and it.is_valid_at()
            and self._eligible_for_extraction(it)
        ]
        extract_succeeded = 0
        for item in raw_traces:
            emit(
                "promotion_attempted",
                item,
                from_stage="raw",
                to_stage="extracted",
                promotion_path="extract",
            )
            extracted = self._extractor.extract(item)
            if extracted:
                extract_succeeded += 1
                for e in extracted:
                    if e.promotion_path is None:
                        e.promotion_path = "extract"
                    emit(
                        "promotion_succeeded",
                        e,
                        from_stage="raw",
                        to_stage="extracted",
                        promotion_path="extract",
                        lineage_access_count=e.lineage_access_count,
                    )
                new_items.extend(extracted)
                item.searchable = False
                item.superseded_by = extracted[0].id
                item.updated_at = datetime.now(timezone.utc)
                archived_items.append(item)
            else:
                emit(
                    "promotion_rejected",
                    item,
                    from_stage="raw",
                    to_stage="extracted",
                    reject_reason="extractor_empty",
                )
        if raw_traces:
            record_hop(
                "raw->extracted",
                attempted=len(raw_traces),
                succeeded=extract_succeeded,
                rejected=len(raw_traces) - extract_succeeded,
            )
        report.evolved_count += len(new_items)

        # Phase 2: extracted → knowledge (convergence merge). Exclude items
        # already superseded by a prior merge: the merger and solo path both skip
        # them anyway, and counting them as candidates would report a permanently
        # depressed conversion rate at this boundary on every repeat compact.
        extracted_items = [
            it
            for it in items
            if it.stage == Stage.extracted
            and not it.is_deleted
            and it.is_valid_at()
            and not it.superseded_by
        ]
        # Include newly extracted items
        all_extracted = extracted_items + [
            it for it in new_items if it.stage == Stage.extracted
        ]
        if all_extracted:
            kept, archived = self._merger.merge(all_extracted)
            # Find new knowledge items (those not in original list)
            original_ids = {it.id for it in all_extracted}
            merge_knowledge = [it for it in kept if it.id not in original_ids]
            new_items.extend(merge_knowledge)
            archived_items.extend(archived)
            report.merged_count += len(archived)
            report.evolved_count += len(merge_knowledge)

            if self._summarizer is not None:
                for it in merge_knowledge:
                    if it.abstract is None:
                        it.abstract = self._summarizer.abstract(it.content_text)
                        it.summary = self._summarizer.summary(it.content_text)
            else:
                # When synthesize_fn has already written content as a natural
                # language string, use it directly as abstract/summary to ensure
                # middleware injection and semantic retrieval can match this
                # knowledge entry.
                for it in merge_knowledge:
                    if it.abstract is None and isinstance(it.content, str):
                        it.abstract = it.content
                        it.summary = it.content

            # Solo promotion path: isolated high-value extracted items that could
            # not form a cluster still reach knowledge when their lineage usage
            # and feedback clear the bar (fixes the "isolated insight dead-ends"
            # gap). Operates on items the merge step did not consume.
            consumed_ids = {it.id for it in archived}
            solo_candidates = [
                it
                for it in all_extracted
                if it.id not in consumed_ids and not it.superseded_by
            ]
            solo_knowledge, solo_archived, solo_rejections = (
                self._promote_solo_extracted(solo_candidates)
            )
            new_items.extend(solo_knowledge)
            archived_items.extend(solo_archived)
            report.evolved_count += len(solo_knowledge)

            # Quality gate: every new knowledge item is scored before it lands;
            # under-spec items are tagged needs_review with a reduced confidence.
            new_knowledge = merge_knowledge + solo_knowledge
            for it in new_knowledge:
                self._apply_knowledge_quality_gate(it)
                emit(
                    "promotion_succeeded",
                    it,
                    from_stage="extracted",
                    to_stage="knowledge",
                    promotion_path=it.promotion_path or "converge",
                    quality_score=it.quality_score,
                    lineage_access_count=it.lineage_access_count,
                )
            for src, reason in solo_rejections:
                emit(
                    "promotion_rejected",
                    src,
                    from_stage="extracted",
                    to_stage="knowledge",
                    reject_reason=reason,
                )
            record_hop(
                "extracted->knowledge",
                attempted=len(all_extracted),
                succeeded=len(new_knowledge),
                rejected=len(solo_rejections),
            )

        # Phase 3: knowledge → skill (distillation)
        knowledge_items = [
            it
            for it in items
            if it.stage == Stage.knowledge and not it.is_deleted and it.is_valid_at()
        ]
        candidates = self._distiller.identify_candidates(knowledge_items)
        # Publish idempotency: a skill's source_fingerprint is its upsert key.
        # Re-distilling the same knowledge yields the same fingerprint, so we
        # skip any candidate whose skill already exists (in the scope or earlier
        # this cycle) instead of multiplying near-duplicate skills.
        seen_fingerprints = {
            fp
            for it in items
            if it.stage == Stage.skill
            for fp in (_skill_fingerprint(it),)
            if fp
        }
        candidate_ids = {it.id for it in candidates}
        distilled_count = 0
        for candidate in candidates:
            emit(
                "promotion_attempted",
                candidate,
                from_stage="knowledge",
                to_stage="skill",
                promotion_path=candidate.promotion_path or "distill",
            )
            skill_item = self._distiller.distill(candidate)
            fp = _skill_fingerprint(skill_item)
            if fp and fp in seen_fingerprints:
                emit(
                    "promotion_rejected",
                    skill_item,
                    from_stage="knowledge",
                    to_stage="skill",
                    reject_reason="duplicate_fingerprint",
                )
                continue
            if fp:
                seen_fingerprints.add(fp)
            new_items.append(skill_item)
            report.evolved_count += 1
            distilled_count += 1
            emit(
                "promotion_succeeded",
                skill_item,
                from_stage="knowledge",
                to_stage="skill",
                promotion_path=skill_item.promotion_path or "distill",
                quality_score=skill_item.quality_score,
                lineage_access_count=skill_item.lineage_access_count,
            )
        for it in knowledge_items:
            if it.id not in candidate_ids:
                emit(
                    "promotion_rejected",
                    it,
                    from_stage="knowledge",
                    to_stage="skill",
                    reject_reason="not_distill_candidate",
                )
        if knowledge_items:
            record_hop(
                "knowledge->skill",
                attempted=len(knowledge_items),
                succeeded=distilled_count,
                rejected=len(knowledge_items) - distilled_count,
            )

        # Phase 3.5: Heuristic distillation for plain text items (no LLM required).
        # Scope-limited to extracted/knowledge so raw cannot jump straight to a
        # skill — raw must first pass module 1 extraction. This keeps the
        # LLM-free distillation ability while killing low-quality "truncated
        # string skills" produced directly from raw. Newly-extracted items from
        # this same cycle are included so the chain can flow within one compact.
        distilled_ids = {it.id for it in new_items if it.stage == Stage.skill}
        allowed_stages = (
            (Stage.raw, Stage.extracted, Stage.knowledge)
            if self._heuristic_allow_raw
            else (Stage.extracted, Stage.knowledge)
        )
        all_items_for_heuristic = [
            it
            for it in (items + new_items)
            if not it.is_deleted
            and it.is_valid_at()
            and it.stage in allowed_stages
            and it.id not in distilled_ids
        ]
        heuristic_candidates = self._distiller.identify_heuristic_candidates(
            all_items_for_heuristic
        )
        heuristic_count = 0
        for candidate in heuristic_candidates:
            emit(
                "promotion_attempted",
                candidate,
                from_stage=candidate.stage.value,
                to_stage="skill",
                promotion_path="heuristic",
            )
            heuristic_skill = self._distiller.distill_heuristic(candidate)
            fp = _skill_fingerprint(heuristic_skill)
            if fp and fp in seen_fingerprints:
                emit(
                    "promotion_rejected",
                    heuristic_skill,
                    from_stage=candidate.stage.value,
                    to_stage="skill",
                    reject_reason="duplicate_fingerprint",
                )
                continue
            if fp:
                seen_fingerprints.add(fp)
            new_items.append(heuristic_skill)
            report.evolved_count += 1
            heuristic_count += 1
            emit(
                "promotion_succeeded",
                heuristic_skill,
                from_stage=candidate.stage.value,
                to_stage="skill",
                promotion_path="heuristic",
                quality_score=heuristic_skill.quality_score,
                lineage_access_count=heuristic_skill.lineage_access_count,
            )
        if all_items_for_heuristic:
            record_hop(
                "heuristic->skill",
                attempted=len(all_items_for_heuristic),
                succeeded=heuristic_count,
                rejected=len(all_items_for_heuristic) - heuristic_count,
            )

        # Phase 4: Archive expired items (stability=ephemeral past TTL)
        for item in items:
            if not item.is_deleted and self._should_archive(item):
                item.searchable = False
                item.deleted_at = datetime.now(timezone.utc)
                item.deleted_reason = "auto_archived_by_evolution"
                archived_items.append(item)
                report.archived_count += 1

        # Observability summaries: path mix, mean quality, and the end-of-cycle
        # stage inventory (the funnel snapshot the dashboard reads).
        for it in new_items:
            if it.promotion_path:
                report.path_distribution[it.promotion_path] = (
                    report.path_distribution.get(it.promotion_path, 0) + 1
                )
        scores = [it.quality_score for it in new_items if it.quality_score is not None]
        if scores:
            report.avg_quality_score = round(sum(scores) / len(scores), 3)
        report.stage_distribution = self._stage_inventory(
            items, new_items, archived_items
        )

        return new_items, archived_items, report

    @staticmethod
    def _stage_inventory(
        items: list[ContextItem],
        new_items: list[ContextItem],
        archived_items: list[ContextItem],
    ) -> dict[str, int]:
        """Count searchable items per stage after the cycle (滞留量 snapshot).

        Inputs that were superseded/archived this cycle are excluded so the
        distribution reflects the live funnel, not the transient mid-pipeline
        state.
        """
        archived_ids = {it.id for it in archived_items}
        dist: dict[str, int] = {}
        for it in items:
            if it.id in archived_ids or it.is_deleted or not it.searchable:
                continue
            dist[it.stage.value] = dist.get(it.stage.value, 0) + 1
        for it in new_items:
            if it.is_deleted or not it.searchable:
                continue
            dist[it.stage.value] = dist.get(it.stage.value, 0) + 1
        return dist

    def _eligible_for_extraction(self, item: ContextItem) -> bool:
        """Check if a raw item is eligible for extraction."""
        # Trace structure path: existing behavior unchanged
        if isinstance(item.content, dict) and _is_trace_structure(item.content):
            extraction_rule = next(
                (r for r in self._rules if r.name == "extract_from_trace"), None
            )
            if extraction_rule and extraction_rule.min_age_seconds > 0:
                age = (datetime.now(timezone.utc) - item.created_at).total_seconds()
                if age < extraction_rule.min_age_seconds:
                    return False
            return True

        # Plain text path: three-choice trigger so write-once text never stalls.
        if isinstance(item.content, str) and len(item.content.strip()) > 20:
            # Usage path: enough accesses (fuel supplied by module 0 attribution).
            if item.access_count >= self._text_extract_min_access:
                return True
            # Age fallback: even a never-retrieved text raw is extracted once it
            # is older than the max age, so it can at least enter the extracted
            # pool instead of being stuck at raw forever.
            age_days = (
                datetime.now(timezone.utc) - item.created_at
            ).total_seconds() / 86400.0
            if age_days >= self._text_extract_max_age_days:
                return True
            return False

        return False

    def _promote_solo_extracted(
        self, candidates: list[ContextItem]
    ) -> tuple[list[ContextItem], list[ContextItem], list[tuple[ContextItem, str]]]:
        """Promote isolated high-value extracted items to knowledge.

        An extracted item that never joined a cluster is promoted when its
        blood-line usage, feedback boost and age all clear the configured bars
        (the ``solo`` path), or when an optional LLM decider judges it a stable
        knowledge (the ``llm`` path). The source extracted item is linked and
        marked superseded but stays searchable (mirrors the merger).

        Returns ``(new_knowledge, archived, rejections)`` where ``rejections``
        pairs each non-promoted candidate with a reason string, so the caller
        can emit ``promotion_rejected`` events that pinpoint over-strict gates.
        """
        new_knowledge: list[ContextItem] = []
        archived: list[ContextItem] = []
        rejections: list[tuple[ContextItem, str]] = []
        now = datetime.now(timezone.utc)

        for item in candidates:
            if (
                item.stage != Stage.extracted
                or item.is_deleted
                or not item.searchable
                or item.superseded_by
            ):
                continue

            path: str | None = None
            reasons: list[str] = []
            if self._solo_promote_enabled:
                age_days = (now - item.created_at).total_seconds() / 86400.0
                if (
                    item.lineage_access_count >= self._solo_min_lineage
                    and item.relevance_boost >= self._solo_min_boost
                    and age_days >= self._solo_min_age_days
                ):
                    path = "solo"
                else:
                    if item.lineage_access_count < self._solo_min_lineage:
                        reasons.append("low_lineage")
                    if item.relevance_boost < self._solo_min_boost:
                        reasons.append("low_boost")
                    if age_days < self._solo_min_age_days:
                        reasons.append("young")
            if path is None and self._promote_decide_fn is not None:
                try:
                    if self._promote_decide_fn(item):
                        path = "llm"
                except Exception:
                    path = None
            if path is None:
                rejections.append((item, ",".join(reasons) or "llm_declined"))
                continue

            knowledge = ContextItem(
                content=item.content,
                scope=item.scope,
                provenance=Provenance(
                    source_type=SourceType.merge_result,
                    source_id=item.id,
                    # Solo products are slightly less trusted than merged ones,
                    # which aggregate corroborating evidence from a cluster.
                    confidence=min(0.85, item.provenance.confidence + 0.1),
                    context=f"Promoted from extracted via {path} path",
                ),
                stage=Stage.knowledge,
                stability=Stability.stable,
                tags=list(dict.fromkeys([*item.tags, "solo_promoted"])),
                links=[Link(target_id=item.id, relation=LinkType.derived_from)],
                created_at=_utc_now(),
                importance=item.importance,
                access_count=item.access_count,
                lineage_access_count=item.lineage_access_count,
                relevance_boost=item.relevance_boost,
                abstract=item.abstract,
                summary=item.summary,
                promotion_path=path,
            )
            new_knowledge.append(knowledge)
            item.superseded_by = knowledge.id
            item.updated_at = _utc_now()
            archived.append(item)

        return new_knowledge, archived, rejections

    def _apply_knowledge_quality_gate(self, item: ContextItem) -> None:
        """Score a knowledge item and flag under-spec products for review.

        Score (0..1): half for a present abstract+summary surface, half for a
        body of reasonable length. Below 0.6 the item is tagged ``needs_review``
        and its effective confidence is dampened so retrieval ranks it lower
        until a human or a later LLM pass improves it. The gate only tags and
        dampens — it never deletes data.
        """
        has_surface = bool(item.abstract) and bool(item.summary)
        long_enough = len(item.content_text.strip()) >= self._knowledge_quality_min_len
        score = (0.5 if has_surface else 0.0) + (0.5 if long_enough else 0.0)
        item.quality_score = round(score, 3)
        if score < 0.6:
            if "needs_review" not in item.tags:
                item.tags.append("needs_review")
            base_conf = (
                item.effective_confidence
                if item.effective_confidence is not None
                else item.provenance.confidence
            )
            item.effective_confidence = min(base_conf, 0.5)

    def _should_archive(self, item: ContextItem) -> bool:
        """Check if item should be auto-archived based on stability."""
        from contextseek.domain.stages import Stability

        if item.stability != Stability.ephemeral:
            return False
        age = (datetime.now(timezone.utc) - item.created_at).total_seconds()
        return age > self._ephemeral_ttl
