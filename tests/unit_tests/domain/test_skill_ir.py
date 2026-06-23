"""Tests for Skill IR v1 — canonical skill representation + identity/fingerprint."""

from __future__ import annotations

from contextseek.domain.skill_ir import (
    DESCRIPTION_MAX,
    SkillIR,
    can_transition,
    compute_fingerprint,
    derive_skill_id,
)


class TestFingerprintAndIdentity:
    def test_fingerprint_stable_for_same_inputs(self):
        a = compute_fingerprint("src1", "body text", {"type": "object"}, "prompt")
        b = compute_fingerprint("src1", "body text", {"type": "object"}, "prompt")
        assert a == b

    def test_fingerprint_changes_with_body(self):
        a = compute_fingerprint("src1", "body one")
        b = compute_fingerprint("src1", "body two")
        assert a != b

    def test_fingerprint_changes_with_source(self):
        a = compute_fingerprint("src1", "same body")
        b = compute_fingerprint("src2", "same body")
        assert a != b

    def test_derive_skill_id_deterministic(self):
        fp = compute_fingerprint("src1", "body")
        assert derive_skill_id(fp) == derive_skill_id(fp)
        assert derive_skill_id(fp).startswith("sk_")

    def test_assign_identity_sets_fingerprint_and_id(self):
        ir = SkillIR(name="Deploy", description="d", body="steps").assign_identity("k1")
        assert ir.source_fingerprint
        assert ir.skill_id == derive_skill_id(ir.source_fingerprint)


class TestContentRoundtrip:
    def test_legacy_dict_parses(self):
        legacy = {
            "skill_type": "prompt",
            "name": "Deploy",
            "description": "Deploy the service",
            "version": "1.0.0",
            "tags": ["ops"],
            "body": "## Overview\n\nsteps",
        }
        ir = SkillIR.from_content(legacy)
        assert ir.kind == "prompt"
        assert ir.name == "Deploy"
        assert ir.tags == ["ops"]
        # No identity fields in legacy content → None, not crash.
        assert ir.skill_id is None
        assert ir.publish_status == "drafted"

    def test_mcp_inputschema_maps_to_parameters(self):
        legacy = {
            "skill_type": "mcp",
            "name": "search",
            "description": "search docs",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
        ir = SkillIR.from_content(legacy)
        assert ir.kind == "mcp"
        assert ir.parameters["properties"]["q"]["type"] == "string"

    def test_roundtrip_preserves_identity_and_mirrors_skill_type(self):
        ir = SkillIR(
            name="Deploy",
            description="d",
            body="b",
            kind="tool",
            tags=["ops"],
            parameters={"type": "object", "properties": {}},
        ).assign_identity("k1")
        content = ir.to_content()
        # skill_type mirrors kind for existing exporter/filter compatibility.
        assert content["skill_type"] == "tool"
        assert content["skill_id"] == ir.skill_id
        assert content["source_fingerprint"] == ir.source_fingerprint
        back = SkillIR.from_content(content)
        assert back.skill_id == ir.skill_id
        assert back.kind == "tool"

    def test_string_content_becomes_prompt(self):
        ir = SkillIR.from_content("just a plain instruction string")
        assert ir.kind == "prompt"
        assert ir.body == "just a plain instruction string"

    def test_description_capped(self):
        ir = SkillIR(name="x", description="a" * (DESCRIPTION_MAX + 50))
        assert len(ir.description) == DESCRIPTION_MAX


class TestPublishStateMachine:
    def test_valid_transitions(self):
        assert can_transition("drafted", "validated")
        assert can_transition("validated", "published")
        assert can_transition("published", "deprecated")

    def test_invalid_transitions(self):
        assert not can_transition("drafted", "published")
        assert not can_transition("deprecated", "published")
