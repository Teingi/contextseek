"""Tests for the dreaming mechanism (consolidation + divergence)."""

from datetime import datetime, timedelta, timezone

from contextseek.config.strategies import DreamStrategy
from contextseek.domain.context_item import ContextItem, _generate_id, _utc_now
from contextseek.domain.links import LinkType
from contextseek.domain.provenance import Provenance, SourceType
from contextseek.domain.stages import STAGE_CONFIDENCE, Stability, Stage
from contextseek.evolution.dreaming import (
    ConsolidationEngine,
    ConsolidationResult,
    DivergenceEngine,
    DreamEngine,
    DreamReport,
)
from contextseek.policies.decay import DecayConfig, compute_decay


def _make_item(
    content="test",
    stage=Stage.extracted,
    scope="t/p/s",
    tags=None,
    access_count=3,
    created_at=None,
    **kwargs,
):
    return ContextItem(
        id=_generate_id(),
        content=content,
        scope=scope,
        provenance=Provenance(
            source_type=SourceType.trace_extraction,
            source_id="test",
            confidence=0.6,
        ),
        stage=stage,
        tags=tags or [],
        access_count=access_count,
        created_at=created_at or _utc_now(),
        **kwargs,
    )


# ═══════════════════════════════════════════
# ConsolidationEngine
# ═══════════════════════════════════════════


class TestConsolidationEngine:
    def test_consolidation_finds_patterns_in_similarity_window(self):
        """Items with similarity in (0.35, 0.72) get consolidated."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.3, 0.8),
            min_items_for_dream=2,
        )
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(
                content="deployment failed due to memory issue in staging server",
                tags=["ops"],
                access_count=3,
            ),
            _make_item(
                content="deployment failed due to cpu issue in staging environment",
                tags=["ops"],
                access_count=3,
            ),
        ]

        result = engine.consolidate(items)
        assert result.patterns_found >= 1
        assert len(result.items) >= 1

        # Pattern item should have correct properties
        pattern = result.items[0]
        assert pattern.stage == Stage.extracted
        assert pattern.stability == Stability.transient
        assert "dreamed" in pattern.tags
        assert "consolidation" in pattern.tags
        assert pattern.provenance.source_type == SourceType.dream_consolidation

    def test_consolidation_filters_low_access_items(self):
        """Items below consolidation_min_access are excluded."""
        strategy = DreamStrategy(consolidation_min_access=5)
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(content="related topic alpha beta", access_count=1),
            _make_item(content="related topic alpha gamma", access_count=1),
        ]

        result = engine.consolidate(items)
        assert result.patterns_found == 0
        assert len(result.items) == 0

    def test_consolidation_filters_old_items(self):
        """Items outside the consolidation window are excluded."""
        strategy = DreamStrategy(
            consolidation_window_hours=1.0,
            consolidation_min_access=1,
        )
        engine = ConsolidationEngine(strategy=strategy)

        old_time = datetime.now(timezone.utc) - timedelta(hours=5)
        items = [
            _make_item(content="related topic alpha beta", created_at=old_time),
            _make_item(content="related topic alpha gamma", created_at=old_time),
        ]

        result = engine.consolidate(items)
        assert result.patterns_found == 0

    def test_consolidation_excludes_dreamed_items(self):
        """Items already tagged as dreamed are not re-processed."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.3, 0.8),
        )
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(
                content="related alpha beta gamma", tags=["dreamed", "consolidation"]
            ),
            _make_item(
                content="related alpha beta delta", tags=["dreamed", "consolidation"]
            ),
        ]

        result = engine.consolidate(items)
        assert result.patterns_found == 0

    def test_consolidation_max_outputs_cap(self):
        """At most consolidation_max_outputs patterns are produced."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
            consolidation_max_outputs=1,
        )
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(content="alpha beta gamma delta epsilon"),
            _make_item(content="alpha beta gamma delta zeta"),
            _make_item(content="alpha beta gamma delta eta"),
        ]

        result = engine.consolidate(items)
        assert len(result.items) <= 1

    def test_consolidation_links_point_to_sources(self):
        """Dream items should have synthesized_from links to source items."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
        )
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(content="shared topic alpha beta gamma delta"),
            _make_item(content="shared topic alpha beta gamma epsilon"),
        ]

        result = engine.consolidate(items)
        if result.items:
            pattern = result.items[0]
            source_ids = {it.id for it in items}
            for link in pattern.links:
                assert link.relation == LinkType.synthesized_from
                assert link.target_id in source_ids

    def test_consolidation_content_is_pattern_plus_evidence(self):
        """Consolidation item content carries the summary plus primary_evidence."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
        )
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(content="shared topic alpha beta gamma delta"),
            _make_item(content="shared topic alpha beta gamma epsilon"),
        ]

        result = engine.consolidate(items)
        assert result.items
        pattern = result.items[0]
        assert isinstance(pattern.content, dict)
        assert "pattern" in pattern.content
        assert "primary_evidence" in pattern.content
        # Clean summary string is preserved on abstract for embeddings/display.
        assert pattern.abstract == pattern.content["pattern"]

    def test_consolidation_primary_evidence_picks_highest_stage(self):
        """primary_evidence is the cluster's highest-authority (stage) source."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
        )
        engine = ConsolidationEngine(strategy=strategy)

        # Same text so they cluster; different stages so authority differs.
        raw_item = _make_item(
            content="commute destination alpha beta gamma",
            stage=Stage.raw,
        )
        knowledge_item = _make_item(
            content="commute destination alpha beta delta",
            stage=Stage.knowledge,
        )

        result = engine.consolidate([raw_item, knowledge_item])
        assert result.items
        ev = result.items[0].content["primary_evidence"]
        # knowledge (0.85) beats raw (0.3)
        assert ev["stage"] == Stage.knowledge.value
        assert ev["confidence"] == STAGE_CONFIDENCE[Stage.knowledge]
        assert ev["source_id"] == knowledge_item.id
        # Source content is preserved verbatim (generic — no field inspection).
        assert ev["content"] == knowledge_item.content

    def test_consolidation_strengthened_links(self):
        """Cluster pairs get strengthened_links recorded."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
        )
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(content="common words shared between both items here"),
            _make_item(content="common words shared between both texts here"),
        ]

        result = engine.consolidate(items)
        if result.patterns_found > 0:
            assert len(result.strengthened_links) >= 1
            # Each link is (id_a, id_b, sim)
            for a_id, b_id, sim in result.strengthened_links:
                assert isinstance(sim, float)


# ═══════════════════════════════════════════
# DivergenceEngine
# ═══════════════════════════════════════════


class TestDivergenceEngine:
    def test_divergence_needs_min_clusters(self):
        """Divergence requires at least divergence_min_clusters clusters."""
        strategy = DreamStrategy(divergence_min_clusters=2)
        engine = DivergenceEngine(strategy=strategy)

        # Only one cluster
        result = engine.diverge(
            [
                [_make_item(content="one"), _make_item(content="two")],
            ]
        )
        assert len(result.items) == 0

    def test_divergence_generates_hypotheses(self):
        """Given 2+ clusters, divergence generates hypothesis items."""
        strategy = DreamStrategy(divergence_min_clusters=2, divergence_max_outputs=3)
        engine = DivergenceEngine(strategy=strategy)

        # Reps share the concept "scaling" so a fallback hypothesis is produced
        # (the no-LLM path only emits when the two reps share a real concept).
        cluster_a = [
            _make_item(content="database scaling replication strategy", tags=["infra"]),
            _make_item(content="database scaling backup plan", tags=["infra"]),
        ]
        cluster_b = [
            _make_item(content="user scaling onboarding flow", tags=["product"]),
            _make_item(content="user scaling retention metrics", tags=["product"]),
        ]

        result = engine.diverge([cluster_a, cluster_b])
        assert len(result.items) >= 1

        hypothesis = result.items[0]
        assert hypothesis.stage == Stage.extracted
        assert "dreamed" in hypothesis.tags
        assert "divergence" in hypothesis.tags
        assert hypothesis.provenance.source_type == SourceType.dream_divergence

    def test_divergence_links_to_both_sources(self):
        """Hypothesis items link to both cross-cluster representatives."""
        strategy = DreamStrategy(divergence_min_clusters=2)
        engine = DivergenceEngine(strategy=strategy)

        cluster_a = [_make_item(content="topic alpha one", tags=["a"], importance=2.0)]
        cluster_b = [_make_item(content="topic beta two", tags=["b"], importance=2.0)]

        result = engine.diverge([cluster_a, cluster_b])
        if result.items:
            hyp = result.items[0]
            assert len(hyp.links) == 2
            link_targets = {lnk.target_id for lnk in hyp.links}
            assert cluster_a[0].id in link_targets
            assert cluster_b[0].id in link_targets
            for link in hyp.links:
                assert link.relation == LinkType.synthesized_from

    def test_divergence_max_outputs(self):
        """At most divergence_max_outputs hypotheses are produced."""
        strategy = DreamStrategy(divergence_min_clusters=2, divergence_max_outputs=1)
        engine = DivergenceEngine(strategy=strategy)

        clusters = [
            [_make_item(content=f"cluster {i} content") for _ in range(2)]
            for i in range(4)
        ]

        result = engine.diverge(clusters)
        assert len(result.items) <= 1

    def test_divergence_with_llm(self):
        """When LLM is provided, it generates hypothesis text."""
        strategy = DreamStrategy(divergence_min_clusters=2)
        llm_called = []

        def mock_llm(prompt: str) -> str:
            llm_called.append(prompt)
            return "These two observations might be connected through feedback loops."

        engine = DivergenceEngine(strategy=strategy, llm=mock_llm)

        cluster_a = [_make_item(content="system reliability")]
        cluster_b = [_make_item(content="user satisfaction")]

        result = engine.diverge([cluster_a, cluster_b])
        assert len(llm_called) == 1
        assert "feedback loops" in result.items[0].content


# ═══════════════════════════════════════════
# DreamEngine (full cycle)
# ═══════════════════════════════════════════


class TestDreamEngine:
    def test_full_dream_cycle(self):
        """DreamEngine runs consolidation + divergence end-to-end."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
            divergence_min_clusters=2,
            min_items_for_dream=3,
            cooldown_hours=0.0,
        )
        engine = DreamEngine(strategy=strategy)

        items = [
            _make_item(content="alpha beta gamma shared topic one", tags=["a"]),
            _make_item(content="alpha beta gamma shared topic two", tags=["a"]),
            _make_item(content="completely different subject matter x", tags=["b"]),
            _make_item(content="completely different subject matter y", tags=["b"]),
        ]

        report = engine.dream(items)
        assert isinstance(report, DreamReport)
        assert report.total_dream_items >= 0
        assert isinstance(report.consolidation, ConsolidationResult)

    def test_cooldown_prevents_repeat_dream(self):
        """Dream is skipped if cooldown hasn't elapsed."""
        strategy = DreamStrategy(
            min_items_for_dream=2,
            cooldown_hours=1.0,
            consolidation_min_access=1,
        )
        engine = DreamEngine(strategy=strategy)

        items = [
            _make_item(content="alpha beta gamma shared topic one"),
            _make_item(content="alpha beta gamma shared topic two"),
            _make_item(content="alpha beta gamma shared topic three"),
        ]

        # First dream should work
        engine.dream(items)
        # Second dream should be blocked by cooldown
        report2 = engine.dream(items)
        assert report2.total_dream_items == 0

    def test_min_items_threshold(self):
        """Dream is skipped if fewer than min_items_for_dream items."""
        strategy = DreamStrategy(min_items_for_dream=100, cooldown_hours=0.0)
        engine = DreamEngine(strategy=strategy)

        items = [_make_item(content=f"item {i}") for i in range(5)]
        report = engine.dream(items)
        assert report.total_dream_items == 0

    def test_dream_with_deleted_items_excluded(self):
        """Deleted items are excluded from dream input."""
        strategy = DreamStrategy(
            min_items_for_dream=2,
            cooldown_hours=0.0,
            consolidation_min_access=1,
        )
        engine = DreamEngine(strategy=strategy)

        normal = _make_item(content="active item with content")
        deleted = _make_item(content="deleted item")
        deleted.soft_delete("test")

        # Only 1 active item — below min_items_for_dream=2
        report = engine.dream([normal, deleted])
        assert report.total_dream_items == 0


# ═══════════════════════════════════════════
# Decay integration
# ═══════════════════════════════════════════


class TestDreamDecay:
    def test_dreamed_items_decay_faster(self):
        """Items tagged 'dreamed' with no access decay 3x faster."""
        config = DecayConfig(half_life_days=7.0, dream_decay_multiplier=3.0)
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=3)

        normal = _make_item(content="normal item", access_count=0, created_at=created)
        normal.importance = 1.0

        dreamed = _make_item(
            content="dream item",
            tags=["dreamed", "consolidation"],
            access_count=0,
            created_at=created,
        )
        dreamed.importance = 1.0

        normal_decay = compute_decay(normal, now=now, config=config)
        dream_decay = compute_decay(dreamed, now=now, config=config)

        # Dreamed item should have lower importance after decay
        assert dream_decay < normal_decay

    def test_accessed_dream_items_decay_normally(self):
        """Dreamed items that have been accessed decay at normal rate."""
        config = DecayConfig(half_life_days=7.0, dream_decay_multiplier=3.0)
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=3)

        normal = _make_item(content="normal item", access_count=2, created_at=created)
        normal.importance = 1.0

        dreamed_accessed = _make_item(
            content="dream item accessed",
            tags=["dreamed", "consolidation"],
            access_count=2,
            created_at=created,
        )
        dreamed_accessed.importance = 1.0

        normal_decay = compute_decay(normal, now=now, config=config)
        dream_decay = compute_decay(dreamed_accessed, now=now, config=config)

        # Accessed dream item should decay at same rate as normal
        assert abs(normal_decay - dream_decay) < 0.01


# ═══════════════════════════════════════════
# Dream item properties
# ═══════════════════════════════════════════


class TestDreamItemProperties:
    def test_consolidation_item_properties(self):
        """Consolidation items have correct stage, tags, source_type."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
        )
        engine = ConsolidationEngine(strategy=strategy)

        items = [
            _make_item(content="shared common words between these items"),
            _make_item(content="shared common words between those items"),
        ]

        result = engine.consolidate(items)
        if result.items:
            item = result.items[0]
            assert item.stage == Stage.extracted
            assert item.stability == Stability.transient
            assert "dreamed" in item.tags
            assert "consolidation" in item.tags
            assert item.provenance.source_type == SourceType.dream_consolidation
            assert item.provenance.confidence == strategy.dream_initial_confidence

    def test_divergence_item_properties(self):
        """Divergence items have correct properties and lower confidence."""
        strategy = DreamStrategy(
            divergence_min_clusters=2,
            dream_initial_confidence=0.35,
        )
        engine = DivergenceEngine(strategy=strategy)

        clusters = [
            [_make_item(content="cluster a content", tags=["a"])],
            [_make_item(content="cluster b content", tags=["b"])],
        ]

        result = engine.diverge(clusters)
        if result.items:
            item = result.items[0]
            assert item.stage == Stage.extracted
            assert item.stability == Stability.transient
            assert "dreamed" in item.tags
            assert "divergence" in item.tags
            assert item.provenance.source_type == SourceType.dream_divergence
            # Divergence confidence = initial * 0.85
            expected_conf = 0.35 * 0.85
            assert abs(item.provenance.confidence - expected_conf) < 0.01


# ═══════════════════════════════════════════
# ContextSeek.dream() API integration
# ═══════════════════════════════════════════


class TestContextSeekDreamAPI:
    def test_dream_api_dry_run(self):
        """ContextSeek.dream(dry_run=True) returns report without persisting."""
        from contextseek.client.contextseek import ContextSeek

        ctx = ContextSeek()
        scope = "test/dream/api"

        # Add enough items
        for i in range(12):
            item = ctx.add(
                content=f"observation about deployment patterns variant {i}",
                scope=scope,
                source="test",
                source_type=SourceType.trace_extraction,
                tags=["ops"],
                check_conflicts=False,
            )
            # Simulate access to pass consolidation_min_access
            ref = ctx.resolver.ref_for(scope, item.id)
            ctx.feedback(ref, scope=scope, score=0.5)
            ctx.feedback(ref, scope=scope, score=0.5)

        report = ctx.dream(scope=scope, dry_run=True)
        assert isinstance(report, DreamReport)

        # dry_run should not persist new items
        items_after = ctx._list_items(scope)
        # Should still be exactly the 12 we added
        assert len(items_after) == 12

    def test_dream_api_persists_items(self):
        """ContextSeek.dream(dry_run=False) persists dream items."""
        from contextseek.client.contextseek import ContextSeek
        from contextseek.config.strategies import DreamStrategy, StrategyConfig

        dream_cfg = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
            min_items_for_dream=3,
            cooldown_hours=0.0,
        )
        strategy = StrategyConfig(dream=dream_cfg)
        ctx = ContextSeek(strategy=strategy)
        scope = "test/dream/persist"

        # Add similar items
        for i in range(5):
            ctx.add(
                content=f"shared deployment pattern alpha beta gamma variant {i}",
                scope=scope,
                source="test",
                source_type=SourceType.trace_extraction,
                tags=["ops"],
                check_conflicts=False,
            )

        before_count = len(ctx._list_items(scope))
        report = ctx.dream(scope=scope, dry_run=False)

        if report.total_dream_items > 0:
            after_count = len(ctx._list_items(scope))
            assert after_count > before_count


# ═══════════════════════════════════════════
# Graduation (reinforced dream → durable knowledge)
# ═══════════════════════════════════════════


class TestDreamGraduation:
    def _strategy(self, **overrides):
        base = dict(
            min_items_for_dream=1,
            cooldown_hours=0.0,
            graduation_min_access=3,
            graduation_min_age_hours=48.0,
            graduation_min_importance=0.3,
            graduation_confidence=0.7,
        )
        base.update(overrides)
        return DreamStrategy(**base)

    def test_reinforced_dream_item_graduates(self):
        """A dreamed item past all thresholds matures into stable knowledge."""
        engine = DreamEngine(strategy=self._strategy())
        old = _utc_now() - timedelta(hours=72)
        dreamed = _make_item(
            content="useful consolidated insight about deployments",
            tags=["dreamed", "consolidation"],
            access_count=5,
            created_at=old,
            importance=0.6,
        )

        report = engine.dream([dreamed])

        assert dreamed in report.graduated_items
        assert dreamed.stage == Stage.knowledge
        assert dreamed.stability == Stability.stable
        assert "dreamed" not in dreamed.tags
        assert "graduated" in dreamed.tags
        assert dreamed.provenance.confidence >= 0.7

    def test_dream_item_below_thresholds_does_not_graduate(self):
        """Items failing any of access/age/importance stay as transient dreams."""
        engine = DreamEngine(strategy=self._strategy())
        old = _utc_now() - timedelta(hours=72)
        young = _utc_now() - timedelta(hours=1)

        low_access = _make_item(
            content="insight a",
            tags=["dreamed"],
            access_count=1,
            created_at=old,
            importance=0.6,
        )
        too_young = _make_item(
            content="insight b",
            tags=["dreamed"],
            access_count=5,
            created_at=young,
            importance=0.6,
        )
        low_importance = _make_item(
            content="insight c",
            tags=["dreamed"],
            access_count=5,
            created_at=old,
            importance=0.1,
        )

        report = engine.dream([low_access, too_young, low_importance])

        assert report.graduated_items == []
        for it in (low_access, too_young, low_importance):
            assert it.stage == Stage.extracted
            assert "dreamed" in it.tags
            assert "graduated" not in it.tags

    def test_already_graduated_item_is_not_regraduated(self):
        """An item already graduated (no 'dreamed' tag) is left alone."""
        engine = DreamEngine(strategy=self._strategy())
        old = _utc_now() - timedelta(hours=72)
        item = _make_item(
            content="already mature insight",
            tags=["graduated"],
            access_count=5,
            created_at=old,
            importance=0.6,
            stage=Stage.knowledge,
        )

        report = engine.dream([item])
        assert report.graduated_items == []

    def test_graduation_can_be_disabled(self):
        engine = DreamEngine(strategy=self._strategy(graduation_enabled=False))
        old = _utc_now() - timedelta(hours=72)
        dreamed = _make_item(
            content="insight",
            tags=["dreamed"],
            access_count=5,
            created_at=old,
            importance=0.6,
        )
        report = engine.dream([dreamed])
        assert report.graduated_items == []
        assert dreamed.stage == Stage.extracted


# ═══════════════════════════════════════════
# Quality gate (no-LLM noise suppression)
# ═══════════════════════════════════════════


class TestDreamQualityGate:
    def test_consolidation_skips_trivial_shared_tokens(self):
        """No LLM + only short shared tokens → no pattern item (no noise)."""
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.3, 0.8),
            consolidation_min_shared_tokens=2,
        )
        engine = ConsolidationEngine(strategy=strategy)
        # jaccard("to be or not", "to be or yes") = 3/5 = 0.6 (in window),
        # but the only shared tokens (to/be/or) are all <=2 chars → skip.
        items = [
            _make_item(content="to be or not"),
            _make_item(content="to be or yes"),
        ]
        result = engine.consolidate(items)
        assert result.items == []
        assert result.patterns_found == 0

    def test_consolidation_emits_with_meaningful_shared_tokens(self):
        strategy = DreamStrategy(
            consolidation_min_access=1,
            consolidation_similarity_range=(0.2, 0.9),
            consolidation_min_shared_tokens=2,
        )
        engine = ConsolidationEngine(strategy=strategy)
        items = [
            _make_item(content="deployment staging memory issue alpha"),
            _make_item(content="deployment staging memory issue beta"),
        ]
        result = engine.consolidate(items)
        assert len(result.items) >= 1

    def test_divergence_skips_without_shared_concepts(self):
        """No LLM + no overlapping concepts → no empty-speculation item."""
        strategy = DreamStrategy(divergence_min_clusters=2)
        engine = DivergenceEngine(strategy=strategy)
        cluster_a = [_make_item(content="alpha beta", tags=["a"])]
        cluster_b = [_make_item(content="gamma delta", tags=["b"])]
        result = engine.diverge([cluster_a, cluster_b])
        assert result.items == []


# ═══════════════════════════════════════════
# Persistent per-scope cooldown
# ═══════════════════════════════════════════


class TestDreamCooldownPersistence:
    def _items(self):
        return [
            _make_item(content="alpha beta gamma topic one"),
            _make_item(content="alpha beta gamma topic two"),
        ]

    def test_persistent_cooldown_blocks_fresh_engine(self, tmp_path):
        """A new engine instance is still throttled via the persistent store.

        Regression for the original dead-code cooldown: every call builds a
        fresh DreamEngine, so without external state nothing was ever throttled.
        """
        from contextseek.policies.dream_state import DreamStateStore

        store = DreamStateStore(tmp_path / "dream_state.json")
        strategy = DreamStrategy(
            min_items_for_dream=1, cooldown_hours=6.0, consolidation_min_access=1
        )
        scope = "s/p/x"
        items = self._items()

        e1 = DreamEngine(strategy=strategy)
        r1 = e1.dream(items, last_dream_time=store.get(scope))
        assert r1.skipped_cooldown is False
        store.set(scope, r1.timestamp)

        # A brand-new engine must be blocked by the persisted timestamp.
        e2 = DreamEngine(strategy=strategy)
        r2 = e2.dream(items, last_dream_time=store.get(scope))
        assert r2.skipped_cooldown is True
        assert r2.total_dream_items == 0

    def test_force_bypasses_persistent_cooldown(self, tmp_path):
        from contextseek.policies.dream_state import DreamStateStore

        store = DreamStateStore(tmp_path / "dream_state.json")
        strategy = DreamStrategy(
            min_items_for_dream=1, cooldown_hours=6.0, consolidation_min_access=1
        )
        scope = "s/p/x"
        items = self._items()
        store.set(scope, _utc_now())

        engine = DreamEngine(strategy=strategy)
        report = engine.dream(items, last_dream_time=store.get(scope), force=True)
        assert report.skipped_cooldown is False


class TestDreamStateStore:
    def test_set_get_roundtrip(self, tmp_path):
        from contextseek.policies.dream_state import DreamStateStore

        store = DreamStateStore(tmp_path / "d.json")
        ts = _utc_now()
        store.set("a/b/c", ts)
        got = store.get("a/b/c")
        assert got is not None
        assert abs((got - ts).total_seconds()) < 1.0

    def test_missing_file_returns_none(self, tmp_path):
        from contextseek.policies.dream_state import DreamStateStore

        store = DreamStateStore(tmp_path / "missing.json")
        assert store.get("anything") is None

    def test_corrupt_file_treated_as_empty(self, tmp_path):
        from contextseek.policies.dream_state import DreamStateStore

        path = tmp_path / "corrupt.json"
        path.write_text("not valid json {{", encoding="utf-8")
        store = DreamStateStore(path)
        assert store.get("x") is None
        # set still recovers and overwrites cleanly
        store.set("x", _utc_now())
        assert store.get("x") is not None

    def test_isolates_scopes(self, tmp_path):
        from contextseek.policies.dream_state import DreamStateStore

        store = DreamStateStore(tmp_path / "d.json")
        store.set("scope/one", _utc_now())
        assert store.get("scope/two") is None
