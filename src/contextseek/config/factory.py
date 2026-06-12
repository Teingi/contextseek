"""Lazy model factory for ContextSeek.

Builds embedder and LLM instances from Settings using dynamic imports.
LangChain is imported only when a provider is actually configured,
so users without LangChain installed incur no import cost.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

from contextseek.config.settings import (
    EmbeddingSettings,
    LLMSettings,
    SummarizerSettings,
)

_EMBEDDING_PROVIDERS: dict[str, tuple[str, int]] = {
    "openai": ("langchain_openai.OpenAIEmbeddings", 1536),
    "dashscope": ("langchain_community.embeddings.DashScopeEmbeddings", 1024),
    "ollama": ("langchain_ollama.OllamaEmbeddings", 768),
    "huggingface": ("langchain_huggingface.HuggingFaceEmbeddings", 512),
}

_LLM_PROVIDERS: dict[str, str] = {
    "openai": "langchain_openai.ChatOpenAI",
    "dashscope": "langchain_community.chat_models.ChatTongyi",
    "ollama": "langchain_ollama.ChatOllama",
}


def _import_class(class_path: str) -> type:
    """Dynamically import a class from a dotted path.

    Example::

        cls = _import_class("langchain_openai.OpenAIEmbeddings")
    """
    module_path, _, class_name = class_path.rpartition(".")
    if not module_path:
        raise ImportError(
            f"Invalid class_path '{class_path}': expected 'module.ClassName'"
        )
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _normalize_legacy_openai_kwargs(init_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy OpenAI kwarg names to aliases expected by some versions."""
    normalized = {**init_kwargs}
    if "openai_api_base" in normalized and "base_url" not in normalized:
        normalized["base_url"] = normalized.pop("openai_api_base")
    else:
        normalized.pop("openai_api_base", None)

    if "openai_api_key" in normalized and "api_key" not in normalized:
        normalized["api_key"] = normalized.pop("openai_api_key")
    else:
        normalized.pop("openai_api_key", None)
    return normalized


def _normalize_provider(provider: str) -> str:
    return provider.strip().lower()


def _default_embedding_dims(provider: str, class_path: str = "") -> int:
    if provider in _EMBEDDING_PROVIDERS:
        return _EMBEDDING_PROVIDERS[provider][1]
    for known_class_path, dims in _EMBEDDING_PROVIDERS.values():
        if class_path == known_class_path:
            return dims
    return 1536


def _resolve_embedding_provider(settings: EmbeddingSettings) -> tuple[str, int] | None:
    provider = _normalize_provider(settings.provider)
    if provider in {"", "none"}:
        return None
    if settings.class_path:
        return settings.class_path, settings.dims or _default_embedding_dims(
            provider, settings.class_path
        )
    if provider == "langchain":
        return None
    if provider not in _EMBEDDING_PROVIDERS:
        supported = ", ".join(["none", "langchain", *_EMBEDDING_PROVIDERS])
        raise ValueError(
            f"Unknown embedding provider '{settings.provider}'. "
            f"Supported providers: {supported}."
        )
    class_path, default_dims = _EMBEDDING_PROVIDERS[provider]
    return class_path, settings.dims or default_dims


def _resolve_llm_provider(settings: LLMSettings) -> str | None:
    provider = _normalize_provider(settings.provider)
    if provider in {"", "none"}:
        return None
    if settings.class_path:
        return settings.class_path
    if provider == "langchain":
        return None
    if provider not in _LLM_PROVIDERS:
        supported = ", ".join(["none", "langchain", *_LLM_PROVIDERS])
        raise ValueError(
            f"Unknown LLM provider '{settings.provider}'. "
            f"Supported providers: {supported}."
        )
    return _LLM_PROVIDERS[provider]


def resolve_embedding_dims(settings: EmbeddingSettings) -> int:
    """Return the vector dimensions that will be used for embedding settings."""
    resolved = _resolve_embedding_provider(settings)
    if resolved is None:
        return 0
    _, dims = resolved
    return dims


def build_embedder(settings: EmbeddingSettings) -> Callable[[str], list[float]] | None:
    """Build an embedder callable from settings.

    Returns None when provider is "none" (default).
    """
    resolved = _resolve_embedding_provider(settings)
    if resolved is None:
        return None
    class_path, dims = resolved

    import contextseek.embedders.langchain_embedder as _lc_mod

    LangChainEmbedder = _lc_mod.LangChainEmbedder

    cls = _import_class(class_path)
    init_kwargs: dict[str, Any] = {**settings.kwargs}
    init_kwargs = _normalize_legacy_openai_kwargs(init_kwargs)
    if settings.model:
        init_kwargs.setdefault("model", settings.model)
    if settings.base_url:
        init_kwargs.setdefault("base_url", settings.base_url)

    embeddings_instance = cls(**init_kwargs)
    return LangChainEmbedder(embeddings_instance, dims=dims)


def build_llm(settings: LLMSettings) -> Any | None:
    """Build an LLM instance from settings.

    Returns None when provider is "none" (default).
    The returned object is a LangChain BaseChatModel that can be
    wrapped into score_fn / summarize_fn by callers.
    """
    class_path = _resolve_llm_provider(settings)
    if class_path is None:
        return None

    cls = _import_class(class_path)
    init_kwargs: dict[str, Any] = {**settings.kwargs}
    init_kwargs = _normalize_legacy_openai_kwargs(init_kwargs)
    if settings.model:
        init_kwargs.setdefault("model", settings.model)
    if settings.base_url:
        init_kwargs.setdefault("base_url", settings.base_url)

    return cls(**init_kwargs)


def build_summarizer(
    settings: SummarizerSettings,
    *,
    llm: Any | None = None,
    prompt_templates: Any | None = None,
) -> Any | None:
    """Build a Summarizer instance from settings.

    Args:
        settings: ``SummarizerSettings`` controlling provider + token budgets.
        llm: Optional pre-built LangChain chat model. When supplied and
            ``provider == "llm"``, this instance is reused instead of
            re-constructing a separate LLM (avoids duplicate instances when
            both Summarizer and other components need the same model).

    Returns:
        ``None`` when ``provider == "none"`` or when ``provider == "llm"``
        but no usable LLM is configured (graceful fallback to flat L0-only).
        :class:`~contextseek.bridges.summarizer.LLMSummarizer` when
        ``provider == "llm"`` and an LLM is available (uses ``llm`` if
        provided, otherwise builds one from the global ``LLM_*`` env vars).
    """
    if settings.provider == "none":
        return None

    if settings.provider == "llm":
        from contextseek.bridges.summarizer import LLMSummarizer
        import warnings

        try:
            effective_llm = llm if llm is not None else build_llm(LLMSettings())
        except Exception as exc:
            warnings.warn(
                f"build_summarizer: LLM init failed ({exc}); falling back to L0-only.",
                RuntimeWarning,
                stacklevel=2,
            )
            return None
        if effective_llm is None:
            return None
        return LLMSummarizer(
            effective_llm,
            l2_max_chars=settings.l2_max_chars,
            l1_max_chars=settings.l1_max_chars,
            prompts=prompt_templates,
        )
    return None


__all__ = [
    "build_embedder",
    "build_llm",
    "build_summarizer",
    "resolve_embedding_dims",
]
