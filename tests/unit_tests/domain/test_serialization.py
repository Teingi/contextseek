"""Tests for ContextItem serialization/deserialization."""

from contextseek.domain.context_item import ContextItem, _generate_id, _utc_now
from contextseek.domain.links import Link, LinkType
from contextseek.domain.provenance import Provenance, SourceType
from contextseek.domain.serialization import (
    deserialize_context_item,
    serialize_context_item,
)
from contextseek.domain.stages import Stage


def _make_item(**kwargs):
    defaults = {
        "id": _generate_id(),
        "content": "serialization test",
        "scope": "acme/proj/user1",
        "provenance": Provenance(
            source_type=SourceType.human_input,
            source_id="src1",
            confidence=0.9,
        ),
        "stage": Stage.knowledge,
        "tags": ["tag1", "tag2"],
        "links": [Link(target_id="linked-id", relation=LinkType.related_to)],
        "created_at": _utc_now(),
    }
    defaults.update(kwargs)
    return ContextItem(**defaults)


class TestSerialization:
    def test_roundtrip(self):
        item = _make_item()
        payload = serialize_context_item(item)
        restored = deserialize_context_item(payload)
        assert restored.id == item.id
        assert restored.content == item.content
        assert restored.scope == item.scope
        assert restored.stage == item.stage
        assert restored.provenance.source_type == item.provenance.source_type
        assert restored.provenance.confidence == item.provenance.confidence
        assert len(restored.links) == len(item.links)
        assert restored.tags == item.tags

    def test_serialize_produces_dict(self):
        item = _make_item()
        payload = serialize_context_item(item)
        assert isinstance(payload, dict)
        assert payload["id"] == item.id
        assert payload["stage"] == "knowledge"
        assert payload["scope"] == item.scope

    def test_deserialize_minimal(self):
        payload = {
            "id": "test-id",
            "content": "hello",
            "scope": "t/p/s",
            "provenance": {
                "source_type": "human_input",
                "source_id": "x",
                "confidence": 1.0,
            },
            "stage": "raw",
            "tags": [],
            "links": [],
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        item = deserialize_context_item(payload)
        assert item.id == "test-id"
        assert item.stage == Stage.raw
        # New evolution-deepening fields default for legacy payloads.
        assert item.lineage_access_count == 0
        assert item.quality_score is None
        assert item.promotion_path is None

    def test_roundtrip_evolution_fields(self):
        item = _make_item(
            lineage_access_count=7,
            quality_score=0.42,
            promotion_path="solo",
        )
        payload = serialize_context_item(item)
        assert payload["lineage_access_count"] == 7
        assert payload["quality_score"] == 0.42
        assert payload["promotion_path"] == "solo"
        restored = deserialize_context_item(payload)
        assert restored.lineage_access_count == 7
        assert restored.quality_score == 0.42
        assert restored.promotion_path == "solo"
