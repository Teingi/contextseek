"""Export trace data as training-ready datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from contextseek.client.contextseek import ContextSeek


@dataclass
class TraceExportRecord:
    """One training sample derived from a trace."""

    item_id: str
    task_id: str
    input: str
    output: str
    tool_calls: list[dict[str, Any]]
    feedback: str | None
    status: str
    metadata: dict[str, Any]

    def to_chat_format(self) -> dict[str, Any]:
        """Convert to OpenAI-style chat training format."""
        messages: list[dict[str, str]] = []
        messages.append({"role": "user", "content": self.input})
        if self.tool_calls:
            for tc in self.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": f"[tool_call] {json.dumps(tc, ensure_ascii=False)}",
                    }
                )
        messages.append({"role": "assistant", "content": self.output})
        return {"messages": messages, "metadata": self.metadata}

    def to_preference_pair(self) -> dict[str, Any] | None:
        """Convert to preference pair if feedback is available."""
        if not self.feedback:
            return None
        return {
            "prompt": self.input,
            "chosen": self.output,
            "feedback": self.feedback,
            "metadata": self.metadata,
        }


@dataclass
class TraceExporter:
    """Export traces from ContextSeek as training data.

    Usage::

        exporter = TraceExporter(client=ctx)
        records = exporter.export_scope("acme/proj/user1")
        jsonl = exporter.to_jsonl(records)
    """

    client: "ContextSeek"
    include_failed: bool = False
    min_output_length: int = 10

    def export_scope(
        self,
        scope: str,
        *,
        limit: int | None = None,
    ) -> list[TraceExportRecord]:
        """Export all traces in a scope as training records."""
        from contextseek.domain.stages import Stage

        # Search for raw trace items in the scope; need full L0 to access content dict
        response = self.client.retrieve(
            "trace",
            scope=scope,
            k=limit or 100,
            full=True,
            filters={"stage": Stage.raw.value, "tags": ["trace"]},
        )
        records: list[TraceExportRecord] = []
        for hit in response:
            item = hit.item
            if limit is not None and len(records) >= limit:
                break
            if item.is_deleted:
                continue
            content = item.content if isinstance(item.content, dict) else {}
            status = str(content.get("status", "success"))
            if not self.include_failed and status != "success":
                continue
            output = str(content.get("output", ""))
            if len(output) < self.min_output_length:
                continue
            record = TraceExportRecord(
                item_id=item.id,
                task_id=str(content.get("task_id", "")),
                input=str(content.get("input", "")),
                output=output,
                tool_calls=list(content.get("tool_calls", [])),
                feedback=content.get("feedback"),
                status=status,
                metadata={
                    "scope": scope,
                    "item_id": item.id,
                    "duration_ms": content.get("duration_ms", 0),
                },
            )
            records.append(record)
        return records

    def to_jsonl(
        self,
        records: list[TraceExportRecord],
        *,
        format: str = "chat",
    ) -> str:
        """Serialize records to JSONL format."""
        lines: list[str] = []
        for record in records:
            if format == "preference":
                entry = record.to_preference_pair()
                if entry is None:
                    continue
            else:
                entry = record.to_chat_format()
            lines.append(json.dumps(entry, ensure_ascii=False))
        return "\n".join(lines) + ("\n" if lines else "")


__all__ = ["TraceExporter", "TraceExportRecord"]
