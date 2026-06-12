"""URL connector (manual pull + conditional refresh)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib import request

from contextseek.ingestion.connectors.base import BaseConnector, PullResult
from contextseek.ingestion.models import SyncCheckpoint


class _SimpleHTMLText(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self.meta_description = ""
        self._inside_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag_name == "title":
            self._inside_title = True
            return
        if tag_name != "meta":
            return
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        name = attr_map.get("name", "").lower()
        prop = attr_map.get("property", "").lower()
        content = " ".join(attr_map.get("content", "").split()).strip()
        if not content:
            return
        if name == "description" and not self.meta_description:
            self.meta_description = content
        elif prop == "og:description" and not self.meta_description:
            self.meta_description = content

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag_name == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = " ".join(data.split()).strip()
        if not text:
            return
        if self._inside_title and not self.title:
            self.title = text
        self.parts.append(text)


class _LinkExtractor(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        href = attr_map.get("href", "").strip()
        if not href:
            return
        absolute = urljoin(self.base_url, href).strip()
        if not absolute:
            return
        self.links.append(absolute.split("#", 1)[0])


class UrlConnector(BaseConnector):
    def _seed_urls(self) -> list[str]:
        urls = self.config.config.get("urls", [])
        if isinstance(urls, list) and urls:
            return [str(u).strip() for u in urls if str(u).strip()]
        url = str(self.config.config.get("url", "")).strip()
        return [url] if url else []

    @staticmethod
    def _is_http_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _normalize_url(value: str) -> str:
        return value.strip().split("#", 1)[0]

    @staticmethod
    def _same_host(url_a: str, url_b: str) -> bool:
        return urlparse(url_a).netloc == urlparse(url_b).netloc

    @staticmethod
    def _within_seed_path_prefix(seed: str, candidate: str) -> bool:
        seed_path = urlparse(seed).path.rstrip("/")
        candidate_path = urlparse(candidate).path
        if not seed_path or seed_path == "/":
            return True
        return candidate_path.startswith(seed_path)

    @staticmethod
    def _fetch_text_response(
        url: str, *, timeout_seconds: int = 10, headers: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        req = request.Request(url, headers=headers or {})
        with request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            response_headers = {
                "etag": str(resp.headers.get("ETag", "")).strip(),
                "last_modified": str(resp.headers.get("Last-Modified", "")).strip(),
                "rendered_js": "false",
            }
            return body, response_headers

    @staticmethod
    def _fetch_rendered_html(url: str, *, timeout_ms: int = 20000) -> str | None:
        try:
            from playwright.sync_api import (  # pyright: ignore[reportMissingImports]
                sync_playwright,
            )
        except Exception:
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    return page.content()
                finally:
                    browser.close()
        except Exception:
            return None

    def _fetch_url(
        self,
        url: str,
        *,
        timeout_seconds: int,
        headers: dict[str, str] | None = None,
        for_discovery: bool = False,
    ) -> tuple[str, dict[str, str]]:
        render_js = bool(self.config.config.get("render_js", True))
        if render_js:
            rendered = self._fetch_rendered_html(url)
            if rendered:
                return rendered, {
                    "etag": "",
                    "last_modified": "",
                    "rendered_js": "true",
                }
        return self._fetch_text_response(
            url,
            timeout_seconds=timeout_seconds,
            headers=headers if not for_discovery else None,
        )

    def discover(self) -> list[str]:
        seeds = [
            self._normalize_url(seed)
            for seed in self._seed_urls()
            if self._is_http_url(seed)
        ]
        if not seeds:
            return []

        crawl = bool(self.config.config.get("crawl", True))
        if not crawl:
            return seeds

        max_pages = int(self.config.config.get("max_pages", 8))
        max_pages = max(1, min(max_pages, 50))
        same_host_only = bool(self.config.config.get("same_host_only", True))
        restrict_to_seed_path = bool(self.config.config.get("restrict_to_seed_path", True))

        queued: deque[str] = deque(seeds)
        seen: set[str] = set()
        discovered: list[str] = []

        while queued and len(discovered) < max_pages:
            current = queued.popleft()
            if current in seen:
                continue
            seen.add(current)
            discovered.append(current)
            try:
                body, _ = self._fetch_url(
                    current, timeout_seconds=8, for_discovery=True
                )
            except Exception:
                continue
            parser = _LinkExtractor(base_url=current)
            parser.feed(body)
            for link in parser.links:
                normalized = self._normalize_url(link)
                if normalized in seen:
                    continue
                if not self._is_http_url(normalized):
                    continue
                if same_host_only and not any(
                    self._same_host(seed, normalized) for seed in seeds
                ):
                    continue
                if restrict_to_seed_path and not any(
                    self._within_seed_path_prefix(seed, normalized) for seed in seeds
                ):
                    continue
                if len(discovered) + len(queued) >= max_pages:
                    break
                queued.append(normalized)
        return discovered

    def pull(self, partition: str, checkpoint: SyncCheckpoint | None) -> PullResult:
        headers: dict[str, str] = {}
        if checkpoint and checkpoint.cursor:
            if checkpoint.cursor.startswith("rendered:js"):
                headers = {}
            for piece in checkpoint.cursor.split("|"):
                if piece.startswith("etag:"):
                    headers["If-None-Match"] = piece.split(":", 1)[1]
                elif piece.startswith("last_modified:"):
                    headers["If-Modified-Since"] = piece.split(":", 1)[1]

        try:
            body, response_headers = self._fetch_url(
                partition, headers=headers, timeout_seconds=10
            )
            etag = response_headers.get("etag", "")
            last_modified = response_headers.get("last_modified", "")
            rendered_js = response_headers.get("rendered_js", "false") == "true"
        except Exception:
            return PullResult(
                payloads=[], next_cursor=checkpoint.cursor if checkpoint else ""
            )

        parser = _SimpleHTMLText()
        parser.feed(body)
        content = "\n".join(parser.parts).strip()
        if parser.meta_description and parser.meta_description not in content:
            content = (
                f"{content}\n{parser.meta_description}".strip()
                if content
                else parser.meta_description
            )
        if not content:
            fallback_parts = [parser.title, parser.meta_description]
            content = "\n".join(part for part in fallback_parts if part).strip()
        if not content:
            return PullResult(
                payloads=[], next_cursor=checkpoint.cursor if checkpoint else ""
            )

        updated_at = datetime.now(timezone.utc).timestamp()
        cursor_parts = []
        if rendered_js:
            cursor_parts.append("rendered:js")
        if etag:
            cursor_parts.append(f"etag:{etag}")
        if last_modified:
            cursor_parts.append(f"last_modified:{last_modified}")
        next_cursor = "|".join(cursor_parts)
        payload: dict[str, Any] = {
            "source_id": partition,
            "title": parser.title or partition,
            "content": content,
            "updated_at": updated_at,
            "acl_principals": self.config.config.get("acl_principals", []),
            "metadata": {
                "raw_type": "url_doc",
                "canonical_url": partition,
                "etag": etag,
                "last_modified": last_modified,
                "rendered_js": rendered_js,
                "connector_kind": self.config.kind.value,
            },
        }
        return PullResult(payloads=[payload], next_cursor=next_cursor, has_more=False)
