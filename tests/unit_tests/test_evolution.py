"""Tests for the evolution pipeline (extractor, merger, distiller, engine)."""

from datetime import datetime, timezone, timedelta

from contextseek.domain.context_item import ContextItem, _generate_id, _utc_now
from contextseek.domain.geo import GeoMetadata
from contextseek.domain.provenance import Provenance, SourceType
from contextseek.domain.skill_ir import SkillIR
from contextseek.domain.stages import Stage, Stability
from contextseek.evolution.distiller import SkillDistiller
from contextseek.evolution.engine import EvolutionEngine
from contextseek.evolution.extractor import GeoExtractor, HeuristicExtractor
from contextseek.evolution.merger import (
    ConvergenceMerger,
    semantic_similarity,
    decay_score,
)


def _make_item(content="test", stage=Stage.raw, scope="t/p/s", **kwargs):
    defaults = {
        "id": _generate_id(),
        "content": content,
        "scope": scope,
        "provenance": Provenance(
            source_type=SourceType.trace_extraction,
            source_id="test",
            confidence=0.6,
        ),
        "stage": stage,
        "tags": [],
        "links": [],
        "created_at": _utc_now(),
    }
    defaults.update(kwargs)
    return ContextItem(**defaults)


class TestHeuristicExtractor:
    def test_extract_trace(self):
        extractor = HeuristicExtractor()
        item = _make_item(
            content={
                "input": "write a function",
                "output": "here is the code",
                "tool_calls": [{"tool": "editor", "result": "file saved"}],
            }
        )
        results = extractor.extract(item)
        assert len(results) >= 2  # input + tool + output
        assert all(r.stage == Stage.extracted for r in results)

    def test_extract_plain_text_returns_extracted_item(self):
        extractor = HeuristicExtractor()
        item = _make_item(content="plain text that is long enough to extract")
        results = extractor.extract(item)
        assert len(results) == 1
        assert results[0].stage == Stage.extracted
        assert "text_extracted" in (results[0].tags or [])

    def test_extract_empty_text_returns_empty(self):
        extractor = HeuristicExtractor()
        item = _make_item(content="")
        results = extractor.extract(item)
        assert results == []


class TestGeoExtractor:
    def test_structured_mode_promotes_geo_field(self):
        extractor = GeoExtractor(
            geo_field="destination_geo",
            geo_type="frequent_location",
            label="工作日目的地",
            location_type="workplace",
            extra_tags=["commute_destination"],
        )
        item = _make_item(
            content={
                "input": "工作日早上出发导航",
                "output": "已到达目的地",
                "destination_geo": {"lat": 31.2285, "lon": 121.4762},
            }
        )
        results = extractor.extract(item)
        assert len(results) == 1
        out = results[0]
        assert out.stage == Stage.extracted
        # coordinates promoted under canonical content["geo"]
        assert out.content["geo"]["lat"] == 31.2285
        assert out.content["geo"]["geo_type"] == "frequent_location"
        assert out.content["label"] == "工作日目的地"
        assert out.content["location_type"] == "workplace"
        assert "commute_destination" in out.tags
        assert GeoMetadata.from_content(out.content) is not None

    def test_structured_mode_skips_when_geo_field_missing(self):
        extractor = GeoExtractor(
            geo_field="destination_geo", geo_type="frequent_location", label="x"
        )
        item = _make_item(content={"input": "no geo here", "output": "done"})
        assert extractor.extract(item) == []

    def test_structured_mode_carries_through_business_fields(self):
        """structured mode must pass through non-location/control fields from
        raw.content to extracted.content; otherwise the downstream merger's
        LLM won't see the original semantics (e.g. dwell time, wait behavior),
        and will only produce geo-only knowledge.
        """
        extractor = GeoExtractor(
            geo_field="destination_geo",
            geo_type="frequent_location",
            label="周末课外班",
            location_type="kids_class",
        )
        item = _make_item(
            content={
                "input": "周末早上送孩子去课外班",
                "output": "已到达课外班，等待约 2 小时",
                "destination_geo": {"lat": 31.2185, "lon": 121.4815},
                "trip_phase": "weekend_morning",
                "weekday": False,
                "dwell_hours": 2.0,
                "wait_behavior": "nearby_parking",
            }
        )
        out = extractor.extract(item)[0]
        # Location / control fields: still handled by structured backbone;
        # destination_geo is not retained separately.
        assert "destination_geo" not in out.content
        assert out.content["geo"]["lat"] == 31.2185
        assert out.content["label"] == "周末课外班"
        assert out.content["location_type"] == "kids_class"
        # Business fields: must be passed through so merger's content_text
        # includes the intent semantics.
        assert out.content["input"] == "周末早上送孩子去课外班"
        assert out.content["output"] == "已到达课外班，等待约 2 小时"
        assert out.content["trip_phase"] == "weekend_morning"
        assert out.content["weekday"] is False
        assert out.content["dwell_hours"] == 2.0
        assert out.content["wait_behavior"] == "nearby_parking"

    def test_structured_mode_does_not_override_label_with_raw(self):
        """If raw.content coincidentally carries label/location_type or other
        structured backbone fields, the structured backbone values take
        precedence (to prevent business data from overriding control fields)."""
        extractor = GeoExtractor(
            geo_field="destination_geo",
            geo_type="frequent_location",
            label="周末课外班",
            location_type="kids_class",
        )
        item = _make_item(
            content={
                "destination_geo": {"lat": 1.0, "lon": 2.0},
                "label": "raw 自带的脏 label",
                "location_type": "raw_should_be_ignored",
                "dwell_hours": 1.5,
            }
        )
        out = extractor.extract(item)[0]
        assert out.content["label"] == "周末课外班"
        assert out.content["location_type"] == "kids_class"
        assert out.content["dwell_hours"] == 1.5

    def test_decorator_mode_enriches_inner_output(self):
        extractor = GeoExtractor(
            geo_field="destination_geo",
            geo_type="frequent_location",
            extra_tags=["pickup"],
        )
        item = _make_item(
            content={
                "input": "go somewhere",
                "output": "arrived",
                "destination_geo": {"lat": 1.0, "lon": 2.0},
            }
        )
        results = extractor.extract(item)
        assert len(results) >= 2  # delegates to HeuristicExtractor (input + output)
        assert all(r.content["geo"]["lat"] == 1.0 for r in results)
        assert all("geo_extracted" in r.tags and "pickup" in r.tags for r in results)

    def test_decorator_mode_degrades_without_geo(self):
        extractor = GeoExtractor(
            geo_field="destination_geo", geo_type="frequent_location"
        )
        item = _make_item(content={"input": "go", "output": "done"})
        results = extractor.extract(item)
        # falls back to pure inner behaviour: content stays plain string slices
        assert len(results) >= 2
        assert all(isinstance(r.content, str) for r in results)


class TestConvergenceMerger:
    def test_no_merge_below_threshold(self):
        merger = ConvergenceMerger(min_cluster_size=3)
        items = [
            _make_item(content=f"unique content {i}", stage=Stage.extracted)
            for i in range(5)
        ]
        kept, archived = merger.merge(items)
        assert len(archived) == 0

    def test_merge_similar_items(self):
        merger = ConvergenceMerger(similarity_threshold=0.5, min_cluster_size=2)
        items = [
            _make_item(
                content="the quick brown fox jumps over the lazy dog",
                stage=Stage.extracted,
            ),
            _make_item(
                content="the quick brown fox jumps over the lazy cat",
                stage=Stage.extracted,
            ),
            _make_item(
                content="the quick brown fox jumps over the lazy bird",
                stage=Stage.extracted,
            ),
        ]
        kept, archived = merger.merge(items)
        assert len(archived) >= 2
        knowledge_items = [it for it in kept if it.stage == Stage.knowledge]
        assert len(knowledge_items) >= 1

    def test_merged_sources_remain_searchable(self):
        """Convergence merge must NOT hide the source extracted items from
        retrieval. They are still independently useful mid-grained memories;
        only ``superseded_by`` is recorded as merge provenance.
        Pairs with ``RetrievalOrchestrator._keep()`` which filters on
        ``searchable=False`` — extracted items absorbed into a knowledge
        synthesis stay searchable so multi-granularity recall keeps working.
        """
        merger = ConvergenceMerger(similarity_threshold=0.5, min_cluster_size=2)
        items = [
            _make_item(
                content="the quick brown fox jumps over the lazy dog",
                stage=Stage.extracted,
            ),
            _make_item(
                content="the quick brown fox jumps over the lazy cat",
                stage=Stage.extracted,
            ),
        ]
        kept, archived = merger.merge(items)
        knowledge = [it for it in kept if it.stage == Stage.knowledge]
        assert knowledge, "merge should produce at least one knowledge item"
        merged_id = knowledge[0].id
        for src in archived:
            assert src.searchable is True, (
                "merged source extracted items must remain searchable"
            )
            assert src.superseded_by == merged_id, (
                "merged source must record superseded_by as merge provenance"
            )

    def test_semantic_similarity(self):
        assert semantic_similarity("hello world", "hello world") == 1.0
        assert semantic_similarity("hello world", "goodbye moon") == 0.0
        assert 0.0 < semantic_similarity("hello world foo", "hello world bar") < 1.0


class TestSkillDistiller:
    def test_identify_candidates(self):
        distiller = SkillDistiller(min_use_count=5, min_relevance_boost=1.0)
        eligible = _make_item(
            content={"body": "do something", "name": "test_skill"},
            stage=Stage.knowledge,
            tags=["procedure"],
            access_count=10,
            relevance_boost=1.5,
        )
        not_eligible = _make_item(
            content="plain text",
            stage=Stage.knowledge,
            access_count=1,
        )
        candidates = distiller.identify_candidates([eligible, not_eligible])
        assert len(candidates) == 1
        assert candidates[0].id == eligible.id

    def test_distill(self):
        distiller = SkillDistiller()
        item = _make_item(
            content={
                "body": "run tests",
                "name": "run_tests",
                "description": "Run test suite",
            },
            stage=Stage.knowledge,
            tags=["procedure"],
            access_count=20,
            relevance_boost=1.5,
        )
        skill = distiller.distill(item)
        assert skill.stage == Stage.skill
        assert skill.stability == Stability.permanent
        assert "auto_distilled" in skill.tags


class TestEvolutionEngine:
    def test_evolve_empty(self):
        engine = EvolutionEngine()
        new_items, archived, report = engine.evolve([])
        assert new_items == []
        assert archived == []

    def test_evolve_raw_traces(self):
        engine = EvolutionEngine()
        item = _make_item(
            content={"input": "hello", "output": "world", "tool_calls": []},
            stage=Stage.raw,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        new_items, archived, report = engine.evolve([item])
        assert report.evolved_count > 0
        assert all(
            it.stage == Stage.extracted
            for it in new_items
            if it.stage == Stage.extracted
        )


class TestDecayScore:
    def test_recent_items_score_higher(self):
        recent = _make_item(created_at=_utc_now())
        old = _make_item(created_at=datetime.now(timezone.utc) - timedelta(days=30))
        assert decay_score(recent) > decay_score(old)


# ════════════════════════════════════════════════════════════════════════════
# Evolution-deepening P0: signal conservation, multi-path promotion, quality gate
# ════════════════════════════════════════════════════════════════════════════


class TestSignalConservation:
    def test_touch_advances_lineage_and_access(self):
        item = _make_item()
        item.touch()
        item.touch()
        assert item.access_count == 2
        assert item.lineage_access_count == 2

    def test_merge_aggregates_usage_signals(self):
        merger = ConvergenceMerger(similarity_threshold=0.5, min_cluster_size=2)
        a = _make_item(
            content="alpha beta gamma delta",
            stage=Stage.extracted,
            access_count=3,
            lineage_access_count=4,
            relevance_boost=1.2,
        )
        b = _make_item(
            content="alpha beta gamma delta",
            stage=Stage.extracted,
            access_count=5,
            lineage_access_count=6,
            relevance_boost=1.4,
        )
        kept, archived = merger.merge([a, b])
        merged = [it for it in kept if it.stage == Stage.knowledge]
        assert len(merged) == 1
        m = merged[0]
        assert m.access_count == 8  # 3 + 5, never reset to zero
        assert m.lineage_access_count == 10  # 4 + 6
        # access-weighted boost: (1.2*3 + 1.4*5) / 8 == 1.325
        assert abs(m.relevance_boost - 1.325) < 1e-9
        assert m.promotion_path == "converge"

    def test_extractor_inherits_raw_usage_and_boost(self):
        # raw→extracted is the first hop; usage/boost accrued on the raw must
        # not be zeroed here or the downstream gates never wake.
        extractor = HeuristicExtractor()
        raw = _make_item(
            content="a fueled write-once note worth extracting into an insight",
            stage=Stage.raw,
            access_count=4,
            lineage_access_count=5,
            relevance_boost=1.3,
        )
        extracted = extractor.extract(raw)
        assert extracted
        assert extracted[0].lineage_access_count == 5  # conserved, not reset
        assert extracted[0].relevance_boost == 1.3  # boost carried forward

    def test_merge_skips_already_superseded_sources(self):
        # A source kept searchable but already merged (superseded_by set) must
        # not be re-merged, or each compact would mint a fresh knowledge id.
        merger = ConvergenceMerger(similarity_threshold=0.5, min_cluster_size=2)
        a = _make_item(
            content="alpha beta gamma delta",
            stage=Stage.extracted,
            superseded_by="k_existing",
        )
        b = _make_item(
            content="alpha beta gamma delta",
            stage=Stage.extracted,
            superseded_by="k_existing",
        )
        kept, archived = merger.merge([a, b])
        assert [it for it in kept if it.stage == Stage.knowledge] == []
        assert archived == []

    def test_repeated_evolve_does_not_re_merge(self):
        engine = EvolutionEngine()
        a = _make_item(
            content="deploy needs migration checks first", stage=Stage.extracted
        )
        b = _make_item(
            content="deploy needs migration checks first", stage=Stage.extracted
        )
        new_items, archived, _ = engine.evolve([a, b])
        knowledge = [it for it in new_items if it.stage == Stage.knowledge]
        assert len(knowledge) == 1
        # Second compact over the persisted state (superseded sources + knowledge)
        # must not produce another merged knowledge.
        persisted = [a, b] + knowledge
        new2, _archived2, report2 = engine.evolve(persisted)
        assert [
            it
            for it in new2
            if it.stage == Stage.knowledge and it.promotion_path == "converge"
        ] == []
        # Funnel honesty: superseded sources are not counted as live candidates,
        # so the boundary does not report a phantom 0%-conversion attempt.
        assert (
            report2.conversion.get("extracted->knowledge", {}).get("attempted", 0) == 0
        )

    def test_distill_inherits_lineage_signals(self):
        distiller = SkillDistiller(min_use_count=5, min_relevance_boost=1.0)
        item = _make_item(
            content={"body": "run tests", "name": "run_tests", "description": "Run"},
            stage=Stage.knowledge,
            tags=["procedure"],
            access_count=12,
            lineage_access_count=20,
            relevance_boost=1.5,
        )
        skill = distiller.distill(item)
        assert skill.access_count == 12
        assert skill.lineage_access_count == 20
        assert skill.relevance_boost == 1.5


class TestAgeFallbackExtraction:
    def test_old_unread_text_is_extractable(self):
        engine = EvolutionEngine()
        item = _make_item(
            content="a write-once note that was never retrieved but matters",
            stage=Stage.raw,
            access_count=0,
            created_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
        assert engine._eligible_for_extraction(item) is True

    def test_fresh_unread_text_is_not_extractable(self):
        engine = EvolutionEngine()
        item = _make_item(
            content="a fresh note that was never retrieved",
            stage=Stage.raw,
            access_count=0,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert engine._eligible_for_extraction(item) is False


class TestSoloPromotion:
    def test_isolated_high_value_extracted_promotes_to_knowledge(self):
        engine = EvolutionEngine()
        item = _make_item(
            content="an isolated high-value insight worth keeping around",
            stage=Stage.extracted,
            access_count=0,
            lineage_access_count=5,  # >= solo_promote_min_lineage_access (3)
            relevance_boost=1.3,  # >= solo_promote_min_boost (1.1)
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        new_items, archived, report = engine.evolve([item])
        knowledge = [it for it in new_items if it.stage == Stage.knowledge]
        assert len(knowledge) == 1
        assert knowledge[0].promotion_path == "solo"
        assert "solo_promoted" in knowledge[0].tags
        # source extracted is superseded but the knowledge inherits its lineage
        assert item.superseded_by == knowledge[0].id
        assert knowledge[0].lineage_access_count == 5

    def test_low_signal_extracted_does_not_promote(self):
        engine = EvolutionEngine()
        item = _make_item(
            content="a low-signal extracted item nobody used",
            stage=Stage.extracted,
            lineage_access_count=1,
            relevance_boost=1.0,
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        new_items, archived, report = engine.evolve([item])
        assert [it for it in new_items if it.stage == Stage.knowledge] == []


class TestKnowledgeQualityGate:
    def test_thin_knowledge_flagged_needs_review(self):
        engine = EvolutionEngine()
        item = _make_item(
            content="tiny",  # below knowledge_quality_min_len, no abstract/summary
            stage=Stage.extracted,
            lineage_access_count=5,
            relevance_boost=1.3,
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        new_items, archived, report = engine.evolve([item])
        knowledge = [it for it in new_items if it.stage == Stage.knowledge]
        assert len(knowledge) == 1
        assert "needs_review" in knowledge[0].tags
        assert knowledge[0].quality_score is not None
        assert knowledge[0].quality_score < 0.6


class TestDistillerDecoupling:
    def test_no_llm_usage_path_accepts_non_procedure_knowledge(self):
        distiller = SkillDistiller(min_use_count=5, min_relevance_boost=1.1)
        # No procedure tag, plain text — old path would have excluded this.
        item = _make_item(
            content="a repeatedly used non-procedure insight",
            stage=Stage.knowledge,
            access_count=0,
            lineage_access_count=10,
            relevance_boost=1.3,
        )
        candidates = distiller.identify_candidates([item])
        assert len(candidates) == 1
        assert candidates[0].id == item.id

    def test_llm_decider_not_pre_gated_by_procedure(self):
        seen: list[str] = []

        def decide(it):
            seen.append(it.id)
            return True

        distiller = SkillDistiller(
            min_use_count=5, min_relevance_boost=1.1, llm_decide_fn=decide
        )
        item = _make_item(
            content="non-procedure but used a lot",
            stage=Stage.knowledge,
            access_count=8,
            relevance_boost=1.2,
        )
        candidates = distiller.identify_candidates([item])
        assert seen == [item.id]  # LLM saw it despite no procedure tag
        assert len(candidates) == 1


class TestHeuristicScopeAndQuality:
    def test_raw_does_not_jump_straight_to_skill(self):
        engine = EvolutionEngine()
        raw = _make_item(
            content="a raw note used a lot but still raw and unstructured",
            stage=Stage.raw,
            access_count=10,
            relevance_boost=1.3,
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        new_items, archived, report = engine.evolve([raw])
        skills = [it for it in new_items if it.stage == Stage.skill]
        # raw must first extract; no skill should be produced directly from raw
        assert all(s.provenance.source_id != raw.id for s in skills)

    def test_knowledge_heuristic_distills_to_skill(self):
        engine = EvolutionEngine()
        knowledge = _make_item(
            content="a well-used knowledge note worth turning into a skill body",
            stage=Stage.knowledge,
            access_count=10,
            relevance_boost=1.3,
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        new_items, archived, report = engine.evolve([knowledge])
        skills = [it for it in new_items if it.stage == Stage.skill]
        assert any(s.provenance.source_id == knowledge.id for s in skills)

    def test_heuristic_skill_quality_gate_flags_thin_body(self):
        distiller = SkillDistiller()
        item = _make_item(
            content="just a short truncated note without real structure here",
            stage=Stage.knowledge,
            access_count=10,
            relevance_boost=1.3,
        )
        skill = distiller.distill_heuristic(item)
        assert "needs_review" in skill.tags
        assert skill.quality_score is not None and skill.quality_score < 0.6
        assert skill.promotion_path == "heuristic"


class TestFactoryConsistency:
    def test_from_config_assembles_strategy_driven_engine(self, tmp_path):
        import json

        from contextseek.client.contextseek import ContextSeek
        from contextseek.evolution.extractor import HeuristicExtractor

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {"adapter": {"type": "in_memory"}, "evolution": {"enabled": True}}
            ),
            encoding="utf-8",
        )
        ctx = ContextSeek.from_runtime_config(str(config_path))
        engine = ctx.evolution_engine
        # G6: config-dict users get the same strategy-driven defaults as
        # from_settings, not a bare EvolutionEngine() on hardcoded weak defaults.
        assert engine is not None
        assert isinstance(engine._extractor, HeuristicExtractor)
        assert engine._solo_promote_enabled is True
        assert engine._text_extract_max_age_days == 7.0

    def test_from_config_honors_evolution_switches(self, tmp_path):
        # G6: switches in the config dict must actually drive the engine, not be
        # silently replaced by defaults.
        import json

        from contextseek.client.contextseek import ContextSeek

        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "adapter": {"type": "in_memory"},
                    "evolution": {
                        "enabled": True,
                        "solo_promote_enabled": False,
                        "text_extract_max_age_days": 2.0,
                        "solo_promote_min_lineage_access": 9,
                    },
                }
            ),
            encoding="utf-8",
        )
        engine = ContextSeek.from_runtime_config(str(config_path)).evolution_engine
        assert engine._solo_promote_enabled is False
        assert engine._text_extract_max_age_days == 2.0
        assert engine._solo_min_lineage == 9

    def test_from_config_reads_runtimeconfig_schema(self, tmp_path):
        # The exported config/runtime.py schema (backend/storage_path/strategy.*)
        # must be honored too, not only the legacy adapter/evolution/audit form.
        import json

        from contextseek.client.contextseek import ContextSeek

        config_path = tmp_path / "runtime.json"
        config_path.write_text(
            json.dumps(
                {
                    "backend": "memory",
                    "storage_path": str(tmp_path / "store"),
                    "strategy": {
                        "evolution": {
                            "solo_promote_enabled": False,
                            "solo_promote_min_lineage_access": 7,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        ctx = ContextSeek.from_runtime_config(str(config_path))
        engine = ctx.evolution_engine
        # strategy.evolution present → engine built and its switches honored.
        assert engine is not None
        assert engine._solo_promote_enabled is False
        assert engine._solo_min_lineage == 7

    def test_none_path_delegates_to_from_settings(self, monkeypatch):
        # No config file must still honor the environment via from_settings,
        # not bypass it with a bare cls().
        from contextseek.client.contextseek import ContextSeek

        called = {}

        def fake_from_settings(settings=None):
            called["hit"] = True
            return ContextSeek()

        monkeypatch.setattr(
            ContextSeek,
            "from_settings",
            classmethod(lambda cls, settings=None: fake_from_settings(settings)),
        )
        ContextSeek.from_runtime_config(None)
        assert called.get("hit") is True

    def test_runtimeconfig_maps_ob_vector_dims_to_embedding(self, tmp_path):
        # ob_vector_dims in the RuntimeConfig schema must reach embedding.dims so
        # an OceanBase runtime JSON does not still require EMBEDDING_DIMS.
        import json

        from contextseek.config.settings import EmbeddingSettings, StorageSettings

        captured = {}

        from contextseek.client.contextseek import ContextSeek

        def capture(cls, settings=None):
            captured["settings"] = settings
            return ContextSeek()

        config_path = tmp_path / "ob.json"
        config_path.write_text(
            json.dumps(
                {
                    "backend": "oceanbase",
                    "ob_host": "10.0.0.1",
                    "ob_vector_dims": 1024,
                }
            ),
            encoding="utf-8",
        )
        import unittest.mock as mock

        with mock.patch.object(ContextSeek, "from_settings", classmethod(capture)):
            ContextSeek.from_runtime_config(str(config_path))

        settings = captured["settings"]
        assert isinstance(settings.storage, StorageSettings)
        assert settings.storage.backend == "oceanbase"
        assert settings.ob.host == "10.0.0.1"
        assert isinstance(settings.embedding, EmbeddingSettings)
        assert settings.embedding.dims == 1024

    def test_assemble_helper_passes_promote_decide_fn(self):
        from contextseek.client.contextseek import ContextSeek
        from contextseek.config.strategies import default_strategy_config
        from contextseek.evolution.extractor import HeuristicExtractor

        def decide(_it):
            return True

        engine = ContextSeek._assemble_evolution_engine(
            default_strategy_config().evolution,
            extractor=HeuristicExtractor(),
            promote_decide_fn=decide,
        )
        assert engine._promote_decide_fn is decide


# ════════════════════════════════════════════════════════════════════════════
# Module 5: evolution observability (stage inventory, conversion, events)
# ════════════════════════════════════════════════════════════════════════════


class TestEvolutionObservability:
    def test_extract_emits_succeeded_event_and_inventory(self):
        engine = EvolutionEngine()
        raw = _make_item(
            content="a write-once operational note worth extracting into a summary",
            stage=Stage.raw,
            access_count=5,  # >= text_extract_min_access
        )
        new_items, archived, report = engine.evolve([raw])

        succeeded = [
            e
            for e in report.events
            if e.event == "promotion_succeeded" and e.to_stage == "extracted"
        ]
        assert succeeded and succeeded[0].promotion_path == "extract"
        # Funnel snapshot: the raw was archived, the extracted now occupies it.
        assert report.stage_distribution.get("extracted", 0) >= 1
        assert "raw" not in report.stage_distribution
        assert report.conversion["raw->extracted"]["attempted"] == 1
        assert report.conversion["raw->extracted"]["succeeded"] == 1

    def test_solo_rejection_emits_reason(self):
        engine = EvolutionEngine()
        weak = _make_item(
            content="a low-signal extracted item nobody used much at all here",
            stage=Stage.extracted,
            lineage_access_count=1,  # below solo_promote_min_lineage_access (3)
            relevance_boost=1.0,  # below solo_promote_min_boost (1.1)
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        new_items, archived, report = engine.evolve([weak])

        rejected = [e for e in report.events if e.event == "promotion_rejected"]
        assert rejected
        reason = rejected[0].reject_reason
        assert "low_lineage" in reason and "low_boost" in reason
        assert report.conversion["extracted->knowledge"]["rejected"] >= 1

    def test_path_distribution_and_avg_quality_populated(self):
        engine = EvolutionEngine()
        item = _make_item(
            content="an isolated high-value insight worth promoting on its own",
            stage=Stage.extracted,
            lineage_access_count=5,
            relevance_boost=1.3,
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        new_items, archived, report = engine.evolve([item])
        assert report.path_distribution.get("solo", 0) == 1
        assert report.avg_quality_score is not None

    def test_event_to_dict_is_compact(self):
        from contextseek.domain.results import EvolutionEvent

        e = EvolutionEvent(
            event="promotion_succeeded",
            item_id="abc",
            from_stage="extracted",
            to_stage="knowledge",
            promotion_path="solo",
            lineage_access_count=5,
            ts="2026-06-23T00:00:00+00:00",
        )
        d = e.to_dict()
        assert d["event"] == "promotion_succeeded"
        assert d["promotion_path"] == "solo"
        assert d["lineage_access_count"] == 5
        # Unset fields (quality_score, reject_reason) are omitted.
        assert "quality_score" not in d
        assert "reject_reason" not in d


# ════════════════════════════════════════════════════════════════════════════
# Module 6 slice-A: Skill IR distillation + publish idempotency
# ════════════════════════════════════════════════════════════════════════════


class TestSkillIRDistillation:
    def test_distill_populates_ir_identity(self):
        distiller = SkillDistiller(min_use_count=5, min_relevance_boost=1.0)
        item = _make_item(
            content={"body": "run tests", "name": "run_tests", "description": "Run"},
            stage=Stage.knowledge,
            tags=["procedure"],
            access_count=12,
            relevance_boost=1.5,
        )
        skill = distiller.distill(item)
        assert isinstance(skill.content, dict)
        assert skill.content["skill_id"].startswith("sk_")
        assert skill.content["source_fingerprint"]
        assert skill.content["publish_status"] == "drafted"
        assert skill.content["kind"] == "prompt"

    def test_distill_skill_id_stable_across_runs(self):
        distiller = SkillDistiller(min_use_count=5, min_relevance_boost=1.0)
        item = _make_item(
            content={"body": "run tests", "name": "run_tests", "description": "Run"},
            stage=Stage.knowledge,
            tags=["procedure"],
            access_count=12,
            relevance_boost=1.5,
        )
        a = distiller.distill(item)
        b = distiller.distill(item)
        # Same source + body → same fingerprint-derived skill_id (item ids differ).
        assert a.content["skill_id"] == b.content["skill_id"]
        assert a.id != b.id


class TestDistillIdempotency:
    def _knowledge(self):
        return _make_item(
            content={
                "body": "deploy steps here",
                "name": "deploy",
                "description": "Deploy",
            },
            stage=Stage.knowledge,
            tags=["procedure"],
            access_count=10,
            relevance_boost=1.3,
        )

    def test_second_compact_does_not_duplicate_skill(self):
        engine = EvolutionEngine()
        knowledge = self._knowledge()

        new1, _, report1 = engine.evolve([knowledge])
        skills1 = [it for it in new1 if it.stage == Stage.skill]
        assert len(skills1) == 1
        skill_id = skills1[0].content["skill_id"]

        # Feed the produced skill back alongside the source (simulating a second
        # compact over the same scope): no new skill should be created.
        new2, _, report2 = engine.evolve([knowledge, skills1[0]])
        skills2 = [it for it in new2 if it.stage == Stage.skill]
        assert skills2 == []
        dup_events = [
            e
            for e in report2.events
            if e.event == "promotion_rejected"
            and e.reject_reason == "duplicate_fingerprint"
        ]
        assert dup_events
        # Stable identity preserved across the boundary.
        assert SkillIR.from_content(skills1[0].content).skill_id == skill_id
