# src/contextseek/config/agentseek_ingestor.py
"""Ingest agentseek configuration into the config manager's projected layer.

agentseek remains the upstream owner of its config; contextseek only reads,
projects, and records provenance. Ingestion is idempotent: a source whose
``source_ref`` matches the latest ``agentseek-projection`` version is skipped.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from contextseek.config.manager import ConfigManager, ConfigVersion
from contextseek.config.mapping import project_agentseek_env


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple ``KEY=value`` env file into a dict."""
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


class AgentseekIngestor:
    """Pull agentseek config, project it, and commit a versioned snapshot."""

    def __init__(self, manager: ConfigManager) -> None:
        self.manager = manager

    def ingest_env(
        self,
        env: Mapping[str, str],
        *,
        author: str = "agentseek",
        reason: str = "ingest agentseek env",
    ) -> ConfigVersion | None:
        projected, source_ref = project_agentseek_env(env)
        if source_ref is None:
            return None
        if self._is_duplicate(source_ref):
            return None
        return self.manager.commit(
            projected=projected,
            origin="agentseek-projection",
            author=author,
            reason=reason,
            source_ref=source_ref,
        )

    def ingest_file(
        self,
        path: Path,
        *,
        author: str = "agentseek",
        reason: str | None = None,
    ) -> ConfigVersion | None:
        path = Path(path)
        env = _parse_env_file(path)
        projected, _env_ref = project_agentseek_env(env)
        if not projected:
            return None
        file_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        source_ref = f"agentseek@{path.name}:{file_hash}"
        if self._is_duplicate(source_ref):
            return None
        return self.manager.commit(
            projected=projected,
            origin="agentseek-projection",
            author=author,
            reason=reason or f"ingest agentseek file {path.name}",
            source_ref=source_ref,
        )

    def _is_duplicate(self, source_ref: str) -> bool:
        """True if the latest agentseek-projection version already has this source_ref."""
        for v in self.manager.history():
            if v.origin == "agentseek-projection":
                return v.source_ref == source_ref
            # newest-first: if we hit a non-projection version, no prior projection
            break
        return False
