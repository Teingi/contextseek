"""Persistent per-scope dream cooldown state.

The dream cooldown must survive process restarts and be tracked per scope —
each lifecycle cycle constructs a fresh :class:`DreamEngine`, so an in-memory
``_last_dream_time`` never throttles anything across calls. This store keeps a
small JSON map of ``{scope: last_dream_iso}`` on disk.
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone


class DreamStateStore:
    """Reads/writes ``{scope: last_dream_time}`` from a JSON file.

    All timestamps are stored as UTC ISO-8601 strings. A corrupt or missing
    file is treated as empty state (best-effort, never raises on read).
    """

    def __init__(self, path: str | pathlib.Path) -> None:
        self._path = pathlib.Path(path).expanduser()

    def _load(self) -> dict[str, str]:
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def get(self, scope: str) -> datetime | None:
        """Return the last dream time for *scope*, or None if unknown/corrupt."""
        raw = self._load().get(scope)
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def set(self, scope: str, ts: datetime) -> None:
        """Persist *ts* as the last dream time for *scope* (atomic write)."""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        state = self._load()
        state[scope] = ts.astimezone(timezone.utc).isoformat()

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)


__all__ = ["DreamStateStore"]
