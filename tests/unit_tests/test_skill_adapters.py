"""Tests for the module-6 slice-A adapters: Agent Skills SKILL.md + LangChain."""

from __future__ import annotations

from contextseek.domain.context_item import ContextItem, _generate_id
from contextseek.domain.provenance import Provenance, SourceType
from contextseek.domain.skill_executor import SkillExporter
from contextseek.domain.skill_ir import SkillIR
from contextseek.domain.stages import Stage
from contextseek.plugs.skills import _parse_skill_md


def _skill(ir: SkillIR) -> ContextItem:
    return ContextItem(
        id=_generate_id(),
        content=ir.to_content(),
        scope="me/work",
        provenance=Provenance(
            source_type=SourceType.distillation, source_id="src", confidence=0.8
        ),
        stage=Stage.skill,
    )


class TestAgentSkillMd:
    def test_strict_frontmatter_keys_only(self):
        item = _skill(
            SkillIR(
                name="Deploy Service",
                description="Deploys the service safely",
                body="## Overview\n\nstep 1",
                tags=["ops"],
            ).assign_identity("k1")
        )
        md = SkillExporter().to_agent_skill_md(item)
        parsed = _parse_skill_md(md)
        # name is slugified; description present; version/tags live under metadata.
        assert parsed["name"] == "deploy-service"
        assert "Deploys the service" in parsed["description"]
        assert "step 1" in parsed["body"]
        # No top-level non-standard keys (version/tags are nested in metadata).
        head = md.split("---")[1]
        assert "\nversion:" not in head
        assert "\ntags:" not in head
        assert "metadata:" in head

    def test_description_single_line_and_capped(self):
        item = _skill(
            SkillIR(name="x", description="line one\nline two   with   spaces")
        )
        md = SkillExporter().to_agent_skill_md(item)
        parsed = _parse_skill_md(md)
        assert "\n" not in parsed["description"]
        assert "line one line two with spaces" == parsed["description"]


class TestLangchainAdapter:
    def test_tool_skill_exposes_parameters(self):
        params = {
            "type": "object",
            "properties": {"env": {"type": "string"}},
            "required": ["env"],
        }
        item = _skill(
            SkillIR(
                name="Deploy Service",
                description="Deploys",
                kind="tool",
                parameters=params,
            ).assign_identity("k1")
        )
        tool = SkillExporter().to_langchain_tool(item)
        assert tool.name == "deploy-service"
        assert tool.args == params["properties"]

    def test_prompt_skill_becomes_noarg_tool_with_body(self):
        item = _skill(SkillIR(name="Guide", description="A guide", body="do X then Y"))
        tool = SkillExporter().to_langchain_tool(item)
        assert tool.name == "guide"
        assert "do X then Y" in tool.description
        assert tool.args == {}

    def test_system_message_for_prompt(self):
        from langchain_core.messages import SystemMessage

        item = _skill(SkillIR(name="Guide", description="A guide", body="body"))
        msg = SkillExporter().to_langchain_system_message(item)
        assert isinstance(msg, SystemMessage)
        assert "body" in msg.content


class TestSliceAAcceptance:
    def test_skill_md_and_langchain_tool_consistent(self):
        """Slice-A acceptance: one skill → SKILL.md + StructuredTool with
        consistent name / description / parameters across both formats."""
        params = {"type": "object", "properties": {"q": {"type": "string"}}}
        item = _skill(
            SkillIR(
                name="Search Docs",
                description="Search the documentation",
                kind="tool",
                parameters=params,
            ).assign_identity("k1")
        )
        exporter = SkillExporter()
        md = exporter.to_agent_skill_md(item)
        tool = exporter.to_langchain_tool(item)
        parsed = _parse_skill_md(md)

        assert parsed["name"] == tool.name == "search-docs"
        assert parsed["description"] == tool.description == "Search the documentation"
        assert tool.args == params["properties"]
