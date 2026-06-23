"""Skill IR v1 — canonical intermediate representation for distilled skills.

A skill is a ``ContextItem`` with ``stage=skill`` whose ``content`` dict is the
persisted form of this IR (decision Q4: the IR lives in ``ContextItem.content``,
not a separate structure, to keep serialization/back-ends unchanged). One
canonical representation feeds every adapter — Agent Skills ``SKILL.md``,
LangChain tool, OpenAI/Anthropic/MCP — so adding a target product means adding
an adapter, never a new distillation path.

The two identity fields make distillation idempotent:

- ``source_fingerprint`` is a stable hash of (source id, body, parameters, kind,
  schema version). Re-distilling the same knowledge yields the same fingerprint.
- ``skill_id`` is derived deterministically from the fingerprint, so a skill
  keeps one stable identity across adapters/exports/runtime even with no prior
  state to look up.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1"
PUBLISH_STATES = ("drafted", "validated", "published", "deprecated")
VALID_KINDS = ("prompt", "tool", "mcp", "code")
DESCRIPTION_MAX = 1024

# Allowed publish_status transitions. drafted→validated once the quality gate +
# adapter render checks pass; validated→published on export/mount; anything may
# be deprecated; a deprecated/validated skill can drop back to drafted on a
# re-distill that changes its body.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "drafted": {"validated", "deprecated"},
    "validated": {"published", "drafted", "deprecated"},
    "published": {"deprecated", "validated"},
    "deprecated": {"drafted"},
}


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


def compute_fingerprint(
    source_id: str,
    body: str,
    parameters: dict[str, Any] | None = None,
    kind: str = "prompt",
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """Stable upsert key for a distilled skill.

    Derived from the source item id, rendered body, parameter schema, kind and
    IR schema version. Re-distilling the same knowledge produces the same
    fingerprint (→ same ``skill_id``), so repeated compaction upserts a single
    skill instead of multiplying near-duplicates.
    """
    payload = json.dumps(
        {
            "source_id": source_id,
            "body": body,
            "parameters": parameters or {},
            "kind": kind,
            "schema": schema_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_skill_id(fingerprint: str) -> str:
    """Deterministic stable identity: ``sk_<fingerprint[:16]>``."""
    return "sk_" + fingerprint[:16]


def can_transition(frm: str, to: str) -> bool:
    """Whether a ``publish_status`` move from ``frm`` to ``to`` is allowed."""
    return to in _ALLOWED_TRANSITIONS.get(frm, set())


@dataclass
class SkillIR:
    """Canonical skill representation. Persisted via :meth:`to_content`."""

    name: str
    description: str
    body: str = ""
    kind: str = "prompt"
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=_empty_schema)
    allowed_tools: list[str] = field(default_factory=list)
    globs: list[str] = field(default_factory=list)
    always_apply: bool = False
    resources: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    skill_id: str | None = None
    source_fingerprint: str | None = None
    publish_status: str = "drafted"

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            self.kind = "prompt"
        if self.publish_status not in PUBLISH_STATES:
            self.publish_status = "drafted"
        if self.description and len(self.description) > DESCRIPTION_MAX:
            self.description = self.description[:DESCRIPTION_MAX]

    @classmethod
    def from_content(cls, content: Any) -> "SkillIR":
        """Parse a ``ContextItem.content`` (new IR dict, legacy dict, or str).

        Tolerant of legacy shapes: ``skill_type`` maps to ``kind``; an MCP
        ``inputSchema`` is read as ``parameters`` when no explicit parameters
        exist; missing fields fall back to defaults. A plain-string skill body
        becomes a prompt skill.
        """
        if isinstance(content, str):
            return cls(name="", description=content[:DESCRIPTION_MAX], body=content)
        if not isinstance(content, dict):
            return cls(name="", description="")

        kind = content.get("kind") or content.get("skill_type") or "prompt"
        params = content.get("parameters")
        if not isinstance(params, dict):
            schema = content.get("inputSchema")
            params = schema if isinstance(schema, dict) else _empty_schema()

        return cls(
            name=str(content.get("name", "") or ""),
            description=str(content.get("description", "") or ""),
            body=str(content.get("body", "") or ""),
            kind=str(kind),
            version=str(content.get("version", "1.0.0") or "1.0.0"),
            tags=list(content.get("tags", []) or []),
            parameters=params,
            allowed_tools=list(content.get("allowed_tools", []) or []),
            globs=list(content.get("globs", []) or []),
            always_apply=bool(content.get("always_apply", False)),
            resources=list(content.get("resources", []) or []),
            provenance=dict(content.get("provenance", {}) or {}),
            skill_id=content.get("skill_id"),
            source_fingerprint=content.get("source_fingerprint"),
            publish_status=str(content.get("publish_status", "drafted") or "drafted"),
        )

    def to_content(self) -> dict[str, Any]:
        """Serialize to the persisted ``ContextItem.content`` dict.

        ``skill_type`` mirrors ``kind`` so existing ``SkillExporter`` and
        ``ctx.skills(skill_type=...)`` filters keep working unchanged. Optional
        surface fields are emitted only when set, to keep content compact.
        """
        content: dict[str, Any] = {
            "skill_type": self.kind,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": list(self.tags),
            "body": self.body,
            "parameters": self.parameters,
            "skill_id": self.skill_id,
            "source_fingerprint": self.source_fingerprint,
            "publish_status": self.publish_status,
        }
        if self.allowed_tools:
            content["allowed_tools"] = list(self.allowed_tools)
        if self.globs:
            content["globs"] = list(self.globs)
        if self.always_apply:
            content["always_apply"] = True
        if self.resources:
            content["resources"] = list(self.resources)
        if self.provenance:
            content["provenance"] = dict(self.provenance)
        # Keep an inputSchema mirror for the MCP exporter on mcp-kind skills.
        if self.kind == "mcp":
            content["inputSchema"] = self.parameters
        return content

    def assign_identity(self, source_id: str) -> "SkillIR":
        """Compute and set ``source_fingerprint`` + ``skill_id`` from the source.

        Uses the current body/parameters/kind, so identity tracks content: a
        re-distill with an unchanged body keeps the same skill_id; a changed
        body produces a new fingerprint.
        """
        fp = compute_fingerprint(source_id, self.body, self.parameters, self.kind)
        self.source_fingerprint = fp
        self.skill_id = derive_skill_id(fp)
        return self


__all__ = [
    "SCHEMA_VERSION",
    "PUBLISH_STATES",
    "VALID_KINDS",
    "DESCRIPTION_MAX",
    "SkillIR",
    "compute_fingerprint",
    "derive_skill_id",
    "can_transition",
]
