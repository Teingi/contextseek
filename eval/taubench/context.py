"""ContextSeek client for tau-bench evaluation.

Adapted from eval/appworld/context.py with tau-bench specific enhancements:
- Domain-prefix augmented retrieval
- Policy document import
- Policy violation specific error retrieval
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from contextseek import ContextSeek, SourceType, Stage


@dataclass
class RetrievalPayload:
    """Prompt-ready ContextSeek retrieval output."""

    text: str = ""
    count: int = 0
    item_ids: list[str] = field(default_factory=list)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(_jsonable(content), ensure_ascii=False)


def _hit_text(hit: Any) -> str:
    item = hit.item
    if item.summary:
        return item.summary
    if item.content is not None:
        return _content_to_text(item.content)
    return item.abstract or ""


def _response_to_payload(response: Any, *, max_tokens: int) -> RetrievalPayload:
    char_budget = max(0, max_tokens * 4)
    lines: list[str] = []
    item_ids: list[str] = []
    used = 0
    for idx, hit in enumerate(response, 1):
        text = _hit_text(hit).strip()
        if not text:
            continue
        header = f"[Retrieved context {idx}] id={hit.item.id} score={hit.score:.4f}"
        block = f"{header}\n{text}"
        if char_budget and used + len(block) > char_budget:
            remaining = char_budget - used - len(header) - 1
            if remaining <= 0:
                break
            block = f"{header}\n{text[:remaining].rstrip()}"
        lines.append(block)
        item_ids.append(hit.item.id)
        used += len(block) + 2
        if char_budget and used >= char_budget:
            break
    return RetrievalPayload(text="\n\n".join(lines), count=len(item_ids), item_ids=item_ids)


def _jsonable(value: Any) -> Any:
    """Convert tau2/Pydantic objects into JSON-serializable structures."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _jsonable(value.dict())
    return str(value)


class TauBenchContextSeekClient:
    """ContextSeek client tailored for tau-bench airline/retail domains."""

    def __init__(
        self,
        ctx: ContextSeek | None = None,
        *,
        scope: str,
        domain: str = "airline",
    ) -> None:
        self.scope = scope
        self.domain = domain
        self.ctx = ctx or ContextSeek()

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve_for_task(
        self,
        user_message: str,
        *,
        user_id: str = "",
        max_tokens: int = 1200,
    ) -> RetrievalPayload:
        """Retrieve background context at the start of a dialogue.

        Augments the query with the domain name to improve retrieval precision,
        and injects results via INJECTION kind for clean prompt embedding.
        """
        # Domain-prefixed query for better recall precision
        query = f"{self.domain} task: {user_message[:500]}"
        response = self.ctx.retrieve(
            query,
            scope=self.scope,
            k=8,
        )
        return _response_to_payload(response, max_tokens=max_tokens)

    def retrieve_for_error(
        self,
        observation: str,
        *,
        limit: int = 3,
    ) -> RetrievalPayload:
        """Retrieve prior context when a policy violation or tool error occurs.

        Tries policy-violation-tagged items first, falls back to generic error retrieval.
        """
        # First attempt: exact policy violation match
        hits = self.ctx.retrieve(
            observation[:500],
            scope=self.scope,
            k=limit,
            filters={"tags": ["policy_violation", self.domain]},
        )
        # Fallback: generic failure items
        if not hits:
            hits = self.ctx.retrieve(
                observation[:500],
                scope=self.scope,
                k=limit,
                filters={"tags": ["failure"]},
            )
        # Second fallback: any relevant item
        if not hits:
            hits = self.ctx.retrieve(
                observation[:500],
                scope=self.scope,
                k=limit,
            )

        lines: list[str] = []
        item_ids: list[str] = []
        for idx, hit in enumerate(hits, 1):
            item_ids.append(hit.item.id)
            lines.append(
                f"[Prior error context {idx}] id={hit.item.id} score={hit.score:.4f}\n"
                f"{_hit_text(hit)}"
            )
        return RetrievalPayload(
            text="\n\n".join(lines), count=len(hits), item_ids=item_ids
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def store_trajectory(
        self,
        *,
        task_id: int,
        user_id: str,
        instruction: str,
        messages: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        success: bool,
    ) -> str:
        """Store a raw task trajectory for later distillation."""
        item = self.ctx.add(
            {
                "kind": "taubench_trajectory",
                "domain": self.domain,
                "task_id": task_id,
                "user_id": user_id,
                "instruction": instruction,
                "success": success,
                "tool_calls": _jsonable(tool_calls),
                "messages": _jsonable(messages),
            },
            scope=self.scope,
            source=f"taubench:{self.domain}:{task_id}",
            source_type=SourceType.external_api,
            tags=[
                "taubench",
                self.domain,
                "trajectory",
                "success" if success else "failure",
                f"user:{user_id}",
            ],
            stage=Stage.raw,
            confidence=0.8 if success else 0.5,
        )
        return item.id

    def store_experience(
        self,
        *,
        title: str,
        content: str | dict[str, Any],
        source: str,
        tags: list[str] | None = None,
        stage: Stage = Stage.knowledge,
        confidence: float = 0.75,
    ) -> str:
        """Store distilled reusable knowledge for the domain."""
        normalized_tags = [
            "taubench",
            self.domain,
            "experience",
            *(tags or []),
        ]
        item = self.ctx.add(
            {"title": title, "body": _content_to_text(content)},
            scope=self.scope,
            source=source,
            source_type=SourceType.distillation,
            tags=list(dict.fromkeys(normalized_tags)),
            stage=stage,
            confidence=confidence,
        )
        return item.id

    def apply_success_feedback(self, item_ids: list[str]) -> int:
        """Boost retrieved items that were used during a successful task."""
        updated = 0
        for item_id in dict.fromkeys(item_ids):
            try:
                ref = self.ctx.resolver.ref_for(self.scope, item_id)
                self.ctx.feedback(
                    ref,
                    scope=self.scope,
                    score=0.2,
                    reason="retrieved_context_on_successful_taubench_task",
                )
                updated += 1
            except Exception:
                continue
        return updated

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def compact(self) -> dict[str, Any]:
        """Run ContextSeek compaction/evolution for the configured scope."""
        report = self.ctx.compact(scope=self.scope)
        return {
            "merged_count": report.merged_count,
            "archived_count": report.archived_count,
            "evolved_count": report.evolved_count,
            "details": report.details,
        }

    def overview(self) -> dict[str, Any]:
        """Return a serializable stage overview for reporting/debugging."""
        report = self.ctx.overview(scope=self.scope)
        return {
            "total_items": report.total_items,
            "stage_distribution": report.stage_distribution,
            "pending_extraction": report.pending_extraction,
            "pending_convergence": report.pending_convergence,
            "distill_candidates": report.distill_candidates,
        }

    def import_policy_document(self, wiki_text: str) -> int:
        """Import the domain wiki.md policy document as knowledge items.

        Splits on double-newlines to create individual knowledge entries.
        Returns the number of items created.
        """
        sections = [s.strip() for s in wiki_text.split("\n\n") if s.strip()]
        if not sections:
            return 0

        # First section is usually overview — store as one item
        count = 0
        for i, section in enumerate(sections):
            if len(section) < 50:
                continue
            kind = "overview" if i == 0 else "policy_rule"
            self.ctx.add(
                {"title": f"{self.domain} {kind}", "body": section},
                scope=self.scope,
                source=f"taubench:{self.domain}:wiki.md",
                source_type=SourceType.document,
                tags=["taubench", self.domain, "policy_doc", kind],
                stage=Stage.knowledge,
                confidence=0.9,
            )
            count += 1
        return count
