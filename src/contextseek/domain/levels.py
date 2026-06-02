"""Content levels for progressive layered retrieval (L0/L1/L2)."""

from __future__ import annotations

from enum import Enum


class ContentLevel(str, Enum):
    """Three semantic storage tiers.

    - L0 (full):     full source text; fetch on demand via ``expand()``.
    - L1 (overview): ~2k-token overview; default surface for agents.
    - L2 (abstract): ~100-token gist powering ANN semantic retrieval.
    """

    L0 = "l0"
    L1 = "l1"
    L2 = "l2"


__all__ = ["ContentLevel"]
