"""Summarizer — generate L2 abstract and L1 summary for ContextItems.

The API layer (``ContextSeek``) is the only place that calls a Summarizer.
:class:`LLMSummarizer` wraps any LangChain ``BaseChatModel`` to produce
controlled-length summaries.

When no LLM is available ContextSeek falls back to flat L0-only mode
(no summarization, embeddings run on full content).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from contextseek.llm.client import invoke_text
from contextseek.llm.prompts import (
    LLMPromptTemplates,
    summarizer_abstract_prompt,
    summarizer_summary_prompt,
)


@runtime_checkable
class Summarizer(Protocol):
    """Protocol that produces L2 (abstract) and L1 (summary) summaries."""

    def abstract(self, content: str) -> str:
        """Produce the ~100-token L2 abstract."""

    def summary(self, content: str) -> str:
        """Produce the ~2k-token L1 summary."""


class LLMSummarizer:
    """Summarizer backed by a LangChain ``BaseChatModel``.

    The chat model is constructed externally (e.g. via
    :func:`contextseek.config.factory.build_llm`) and injected. Both prompts
    are run synchronously through ``llm.invoke``.
    """

    def __init__(
        self,
        llm: Any,
        *,
        l2_max_chars: int = 100,
        l1_max_chars: int = 2000,
        prompts: LLMPromptTemplates | None = None,
    ) -> None:
        self._llm = llm
        self._l2_max_chars = int(l2_max_chars)
        self._l1_max_chars = int(l1_max_chars)
        self._prompts = prompts

    def abstract(self, content: str) -> str:
        prompt = summarizer_abstract_prompt(
            char_budget=self._l2_max_chars,
            content=content,
            templates=self._prompts,
        )
        return invoke_text(self._llm, prompt)

    def summary(self, content: str) -> str:
        prompt = summarizer_summary_prompt(
            char_budget=self._l1_max_chars,
            content=content,
            templates=self._prompts,
        )
        return invoke_text(self._llm, prompt)


__all__ = ["LLMSummarizer", "Summarizer"]
