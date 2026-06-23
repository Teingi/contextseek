"""Skill export — converts skill ContextItems to LLM/agent integration formats.

Skills are ContextItems with stage=skill. ContextSeek's responsibility is
store + retrieve + export. Execution is handled by the external agent runtime.
"""

from __future__ import annotations

import json
import re
from typing import Any

from contextseek.domain.context_item import ContextItem
from contextseek.domain.skill_ir import DESCRIPTION_MAX, SkillIR


def _slug_name(name: str, fallback: str) -> str:
    """Normalize a skill name to a slug valid for both Agent Skills (``name``
    frontmatter, lowercase + hyphens) and LangChain/OpenAI tool names
    (``^[a-zA-Z0-9_-]+$``), capped at 64 chars. Shared by the agent-skill and
    LangChain adapters so a skill keeps one stable invocation name across both.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or fallback)[:64]


def _one_line(text: str, limit: int = DESCRIPTION_MAX) -> str:
    """Collapse whitespace to a single line and cap length (Agent Skills
    ``description`` is a single ≤1024-char line that triggers skill loading)."""
    return " ".join(text.split())[:limit]


def _skill_name(skill: ContextItem) -> str:
    if isinstance(skill.content, dict):
        return skill.content.get("name", skill.summary or skill.id[:8])
    # String-content skill: prefer summary, fall back to ID prefix
    return skill.summary or skill.id[:8]


def _skill_desc(skill: ContextItem) -> str:
    if isinstance(skill.content, dict):
        return skill.content.get("description", skill.summary or "")
    # Use the first 100 chars of string content as description
    text = str(skill.content)
    return text[:100] + ("..." if len(text) > 100 else "")


def _skill_type(skill: ContextItem) -> str:
    if isinstance(skill.content, dict):
        return skill.content.get("skill_type", "prompt")
    return "prompt"


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


def _tool_parameters(skill: ContextItem) -> dict[str, Any]:
    """Extract JSON schema parameters from skill content."""
    if isinstance(skill.content, dict):
        params = skill.content.get("parameters")
        if isinstance(params, dict):
            return params
        # mcp-type: inputSchema is the equivalent
        schema = skill.content.get("inputSchema")
        if isinstance(schema, dict):
            return schema
    return _empty_schema()


class SkillExporter:
    """Converts skill ContextItems to LLM/agent integration formats.

    Supports three skill_type values:
    - "prompt"  — Markdown body; exported as a no-arg function whose description
                  contains the full instruction document (Hermes / SuperAGI style)
    - "tool"    — JSON schema parameters; exported as a standard function tool
    - "mcp"     — MCP inputSchema; exported as an MCP tool definition
    """

    # ── Single-item export ────────────────────────────────────────────────

    def to_openai_function(self, item: ContextItem) -> dict[str, Any]:
        """→ {"type": "function", "function": {name, description, parameters}}"""
        name = _skill_name(item)
        desc = _skill_desc(item)
        stype = _skill_type(item)

        if stype == "prompt":
            body = (
                item.content.get("body", "") if isinstance(item.content, dict) else ""
            )
            description = f"{desc}\n\n{body}".strip() if body else desc
            parameters = _empty_schema()
        else:
            description = desc
            parameters = _tool_parameters(item)

        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    def to_anthropic_tool(self, item: ContextItem) -> dict[str, Any]:
        """→ {"name": ..., "description": ..., "input_schema": {...}}"""
        name = _skill_name(item)
        desc = _skill_desc(item)
        stype = _skill_type(item)

        if stype == "prompt":
            body = (
                item.content.get("body", "") if isinstance(item.content, dict) else ""
            )
            description = f"{desc}\n\n{body}".strip() if body else desc
            input_schema = _empty_schema()
        else:
            description = desc
            input_schema = _tool_parameters(item)

        return {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }

    def to_mcp_tool(self, item: ContextItem) -> dict[str, Any]:
        """→ {"name": ..., "description": ..., "inputSchema": {...}}"""
        name = _skill_name(item)
        desc = _skill_desc(item)
        stype = _skill_type(item)

        if stype == "mcp" and isinstance(item.content, dict):
            schema = item.content.get("inputSchema", _empty_schema())
        else:
            schema = _tool_parameters(item)

        return {
            "name": name,
            "description": desc,
            "inputSchema": schema,
        }

    def to_prompt_block(self, item: ContextItem) -> str:
        """→ Markdown block with name / description / body."""
        name = _skill_name(item)
        desc = _skill_desc(item)
        body = ""
        if isinstance(item.content, dict):
            body = item.content.get("body", "")
        elif isinstance(item.content, str):
            body = item.content

        parts = [f"### {name}"]
        if desc and desc != body:
            parts.append(desc)
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    def to_hermes_skill_md(self, item: ContextItem) -> str:
        """→ Full SKILL.md content (YAML frontmatter + Markdown body)."""
        name = _skill_name(item)
        desc = _skill_desc(item)
        version = "1.0.0"
        tags: list[str] = []
        body = ""

        if isinstance(item.content, dict):
            version = item.content.get("version", version)
            tags = item.content.get("tags", [])
            body = item.content.get("body", "")
        elif isinstance(item.content, str):
            # Plain-text skill: use the full string as the Markdown body
            body = item.content

        tag_str = ", ".join(tags) if tags else ""
        frontmatter = f"---\nname: {name}\ndescription: {desc}\nversion: {version}\n"
        if tag_str:
            frontmatter += f"tags: [{tag_str}]\n"
        frontmatter += "---\n"

        return frontmatter + "\n" + body if body else frontmatter

    def to_agent_skill_md(self, item: ContextItem) -> str:
        """→ Anthropic Agent Skills ``SKILL.md`` (strict official frontmatter).

        Unlike :meth:`to_hermes_skill_md` (which carries non-standard
        ``version``/``tags`` keys), this emits only the official keys —
        ``name`` (slug), ``description`` (≤1024, single line, the load trigger),
        optional ``allowed-tools``, and a ``metadata`` map where version/tags
        live. Values are JSON-encoded so colons/quotes stay YAML-safe.
        """
        ir = SkillIR.from_content(item.content)
        name = _slug_name(ir.name or _skill_name(item), fallback=f"skill-{item.id[:8]}")
        description = _one_line(ir.description or _skill_desc(item))

        lines = ["---", f"name: {name}", f"description: {description}"]
        if ir.allowed_tools:
            lines.append(f"allowed-tools: {', '.join(ir.allowed_tools)}")
        metadata: dict[str, Any] = {"version": ir.version}
        if ir.tags:
            metadata["tags"] = list(ir.tags)
        if ir.skill_id:
            metadata["skill_id"] = ir.skill_id
        lines.append("metadata:")
        for key, value in metadata.items():
            lines.append(f"  {key}: {json.dumps(value)}")
        lines.append("---")

        frontmatter = "\n".join(lines) + "\n"
        return frontmatter + "\n" + ir.body if ir.body else frontmatter

    def to_langchain_tool(self, item: ContextItem) -> Any:
        """→ ``langchain_core.tools.StructuredTool``.

        tool/mcp skills expose their ``parameters`` JSON Schema as the tool's
        args schema; a prompt skill becomes a no-argument tool whose description
        carries the instruction body (mirrors :meth:`to_openai_function`). The
        handler raises ``NotImplementedError`` — ContextSeek skills are
        *definitions*; execution belongs to the agent runtime. The tool ``name``
        matches the Agent Skills slug so both formats share one invocation name.

        Raises ``ImportError`` (lazily) when ``langchain_core`` is not installed.
        """
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ImportError(
                "to_langchain_tool requires langchain_core; install it with "
                "`pip install langchain-core`."
            ) from exc

        ir = SkillIR.from_content(item.content)
        name = _slug_name(ir.name or _skill_name(item), fallback=f"skill-{item.id[:8]}")

        if ir.kind in ("tool", "mcp"):
            description = _one_line(ir.description or _skill_desc(item))
            args_schema = ir.parameters or _empty_schema()
        else:
            desc = ir.description or _skill_desc(item)
            description = f"{desc}\n\n{ir.body}".strip() if ir.body else desc
            args_schema = _empty_schema()

        def _definition_only(**_kwargs: Any) -> Any:
            raise NotImplementedError(
                f"Skill '{name}' is a definition exported by ContextSeek; "
                "execute it via your agent runtime, not here."
            )

        return StructuredTool.from_function(
            func=_definition_only,
            name=name,
            description=description,
            args_schema=args_schema,
        )

    def to_langchain_system_message(self, item: ContextItem) -> Any:
        """→ ``langchain_core.messages.SystemMessage`` for a prompt skill.

        The natural injection form for prompt-type skills inside a LangChain
        graph. Raises ``ImportError`` (lazily) without ``langchain_core``.
        """
        try:
            from langchain_core.messages import SystemMessage
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ImportError(
                "to_langchain_system_message requires langchain_core; install "
                "it with `pip install langchain-core`."
            ) from exc

        return SystemMessage(content=self.to_prompt_block(item))

    def to_system_prompt(self, items: list[ContextItem]) -> str:
        """→ Multi-skill Hermes-style system prompt block.

        Format::
            <available_skills>
            ### skill-name
            description …

            body …

            ### skill-name-2
            …
            </available_skills>
        """
        if not items:
            return ""
        blocks = [self.to_prompt_block(it) for it in items]
        inner = "\n\n---\n\n".join(blocks)
        return f"<available_skills>\n{inner}\n</available_skills>"

    # ── Batch export ──────────────────────────────────────────────────────

    def batch_to_openai(self, items: list[ContextItem]) -> list[dict[str, Any]]:
        """Batch export tool/mcp skills as OpenAI tools list."""
        return [self.to_openai_function(it) for it in items]

    def batch_to_anthropic(self, items: list[ContextItem]) -> list[dict[str, Any]]:
        """Batch export tool/mcp skills as Anthropic tools list."""
        return [self.to_anthropic_tool(it) for it in items]


__all__ = ["SkillExporter"]
