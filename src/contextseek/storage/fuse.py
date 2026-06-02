"""Optional FUSE mount adapter for ContextSeek (unified ContextItem API).

This module provides a virtual file system layer that exposes ContextSeek
scopes as a directory hierarchy via FUSE.  It requires the ``fusepy``
package (``pip install fusepy``).

Directory structure when mounted::

    <mountpoint>/
    ├── <scope>/
    │   ├── <item_id>.json
    │   └── ...
    └── ...

Each file is a JSON payload representing a ContextItem read via retrieve().
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextseek.client.contextseek import ContextSeek

try:
    import fuse as _fuse  # type: ignore[import-untyped]

    FUSE_AVAILABLE = True
except ImportError:
    _fuse = None
    FUSE_AVAILABLE = False


@dataclass
class ContextSeekFUSEAdapter:
    """Read-only FUSE adapter exposing ContextSeek items as files.

    This is a framework stub. A full implementation would subclass
    ``fuse.Operations`` and implement ``readdir``, ``getattr``, ``read``,
    etc.  The adapter is intentionally minimal so that it can be tested
    without requiring FUSE kernel support.

    Uses scope-based paths (no more namespace enum).

    Usage::

        adapter = ContextSeekFUSEAdapter(client=client, scope="tenant/project/agent")
        adapter.readdir("/")  # → list of item IDs
        adapter.read("/abc123.json")  # → JSON bytes of ContextItem
    """

    client: "ContextSeek"
    scope: str

    def readdir(self, path: str) -> list[str]:
        """List directory entries.

        Root ("/") lists item IDs found via a broad search.
        """
        if path == "/" or path == "":
            # List items by doing a broad search
            response = self.client.retrieve("*", scope=self.scope, k=100)
            return [f"{hit.item.id}.json" for hit in response]
        return []

    def read(self, path: str) -> bytes | None:
        """Read file content as JSON bytes representing a ContextItem."""
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) != 1:
            return None
        filename = parts[0]
        if not filename.endswith(".json"):
            return None
        item_id = filename.removesuffix(".json")
        # Search for the specific item, ask for full L0 since we serialize content
        response = self.client.retrieve(item_id, scope=self.scope, k=5, full=True)
        for hit in response:
            if hit.item.id == item_id:
                payload = {
                    "id": hit.item.id,
                    "content": hit.item.content,
                    "scope": hit.item.scope,
                    "stage": hit.item.stage.value if hit.item.stage else None,
                    "tags": list(hit.item.tags),
                    "created_at": hit.item.created_at.isoformat()
                    if hit.item.created_at
                    else None,
                    "summary": hit.item.summary,
                    "searchable": hit.item.searchable,
                }
                return json.dumps(
                    payload, ensure_ascii=False, indent=2, default=str
                ).encode("utf-8")
        return None

    def getattr(self, path: str) -> dict[str, Any]:
        """Return file attributes (minimal stat-like dict)."""
        if path == "/" or path == "":
            return {"type": "dir", "size": 0}
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) == 1 and parts[0].endswith(".json"):
            content = self.read(path)
            if content is not None:
                return {"type": "file", "size": len(content)}
        return {}

    def mount(self, mountpoint: str) -> None:
        """Mount the FUSE filesystem (requires fusepy and kernel FUSE support)."""
        if not FUSE_AVAILABLE:
            msg = "fusepy is not installed. Install with: pip install fusepy"
            raise RuntimeError(msg)
        raise NotImplementedError(
            "Full FUSE Operations integration is planned but not yet implemented. "
            "Use readdir() / read() for programmatic access."
        )


__all__ = ["ContextSeekFUSEAdapter", "FUSE_AVAILABLE"]
