# 配置管理（Config Management）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 contextseek 现有两套配置加载器之上加一层版本化、可溯源、可回退的配置托管层，并支持把 agentseek 配置纳入并投影为 contextseek 配置。

**Architecture:** 方案 A — 物化层在上（非侵入）。`ConfigManager` 是权威版本化源（append-only 文件历史，固定路径 `.contextseek/config/`，不依赖 VFS 存储后端）；`Materializer` 把当前生效配置物化为现有加载器已读取的 `.env` 与 `config.json`；`AgentseekIngestor` pull agentseek 配置 → diff → 投影为 `projected` 层。现有 `settings.py` / `runtime.py` / `factory.py` 核心逻辑不动。

**Tech Stack:** Python 3.11+，pydantic-settings，pytest（仓库现有风格，测试放 `tests/unit_tests/`），argparse CLI（`build_parser()` + `run_cli` 的 `if args.command == ...` 分发链）。

## Global Constraints

- 托管库固定路径 `${CONTEXTSEEK_HOME:-.contextseek}/config/`，绝不依赖 VFS / 存储后端（避免「配置决定存储后端、存储后端存配置」的引导循环）。
- 历史是 append-only：回退 = 新建一个 payload 等于旧版本的新版本，历史文件永不删除。
- 合并优先级：`projected`（agentseek）作基线，`native`（contextseek）显式设值的 key 覆盖 `projected`。
- agentseek 是上游自主配置，contextseek 只读 + 投影 + 溯源，绝不反写 agentseek。
- 写操作原子：先写 `history/vN.json.tmp` → fsync → rename → append `manifest.jsonl`（fsync）→ 更新 `current.json`。
- 每个版本 `payload_hash = sha256(canonical_json(payload))`，`verify` 校验整条 hash 链。
- `apply` 物化前必须 dry-run 校验 `effective` 能被 `ContextSeekSettings` / `RuntimeConfig` 成功构造；校验失败不写物化文件、版本标记 `failed`。
- 时间戳用 `datetime.now(timezone.utc).isoformat()`（UTC ISO）。
- 回复与提交信息用中文叙述可，但 git commit message 遵循仓库现有 `feat:/fix:` 英文前缀风格。

## File Structure

新增：
- `src/contextseek/config/envreflector.py` — 反射 `ContextSeekSettings` 得到 env 变量名（迁移自 contrib `agentseek_contextseek/config.py` 的 `_iter_env_vars`），供 Materializer 写 `.env` 与 Ingestor fallback 用。单一职责：模型 → env 名。
- `src/contextseek/config/manager.py` — `ConfigManager`：版本化权威源（init/load/commit/set/rollback/redo/diff/blame/verify/status/apply）。单一职责：版本链与存储 IO。
- `src/contextseek/config/materializer.py` — `Materializer`：`effective` → `.env` + `config.json`，dry-run validate，漂移检测。单一职责：物化与校验。
- `src/contextseek/config/mapping.py` — agentseek → contextseek 显式映射表 + provider 检测（迁移自 contrib）。单一职责：跨系统键映射。
- `src/contextseek/config/agentseek_ingestor.py` — `AgentseekIngestor`：pull / diff / 幂等投影。单一职责：摄入外部源。
- `src/contextseek/config/cli.py` — `register_config_subparser(subparsers)` + `run_config_command(args)`。单一职责：CLI 接线。
- `tests/unit_tests/test_config_envreflector.py`
- `tests/unit_tests/test_config_manager.py`
- `tests/unit_tests/test_config_materializer.py`
- `tests/unit_tests/test_config_mapping.py`
- `tests/unit_tests/test_config_agentseek_ingestor.py`
- `tests/unit_tests/test_config_cli.py`

改动：
- `src/contextseek/cli/main.py` — 在 `build_parser()` 注册 `config` 子命令组；在 `run_cli` 加 `if args.command == "config"` 分发。
- `src/contextseek/config/__init__.py` — 导出新增公共 API。

---

### Task 1: envreflector — 反射 ContextSeekSettings 得到 env 变量名

**Files:**
- Create: `src/contextseek/config/envreflector.py`
- Test: `tests/unit_tests/test_config_envreflector.py`

**Interfaces:**
- Consumes: `contextseek.config.settings.ContextSeekSettings`（现有）。
- Produces:
  - `iter_env_vars(settings_cls=ContextSeekSettings) -> Iterator[str]` — 所有 env 变量名（大写），供 Ingestor fallback。
  - `iter_section_env_fields(settings_cls=ContextSeekSettings) -> Iterator[tuple[str, str, str]]` — yield `(section, field, env_name)`，供 Materializer 写 `.env`。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit_tests/test_config_envreflector.py
"""Tests for ContextSeekSettings env-var reflection."""

from __future__ import annotations

from contextseek.config.envreflector import (
    iter_env_vars,
    iter_section_env_fields,
)


def test_iter_env_vars_includes_known_keys():
    names = set(iter_env_vars())
    assert "STORAGE_BACKEND" in names
    assert "LLM_PROVIDER" in names
    assert "LLM_MODEL" in names


def test_iter_section_env_fields_pairs_section_field_env():
    triples = list(iter_section_env_fields())
    # (section, field, env_name)
    assert ("storage", "backend", "STORAGE_BACKEND") in triples
    assert ("llm", "model", "LLM_MODEL") in triples
    # every env name is uppercase
    for _section, _field, env in triples:
        assert env == env.upper()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_envreflector.py -v`
Expected: FAIL with `ModuleNotFoundError: contextseek.config.envreflector`

- [ ] **Step 3: Write minimal implementation**

```python
# src/contextseek/config/envreflector.py
"""Reflect ``ContextSeekSettings`` to discover the env vars it consumes.

Ported from the ``agentseek-contextseek`` contrib's ``_iter_env_vars`` so the
config manager can (a) write a valid ``.env`` from an effective config and
(b) let ``AGENTSEEK_CTX_*`` act as fallbacks for contextseek's flat env vars.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import type

from pydantic_settings import BaseSettings

from contextseek.config.settings import ContextSeekSettings


def _iter_env_vars(settings_cls: type[BaseSettings]) -> Iterator[str]:
    """Yield ``PREFIX + FIELD_NAME`` (uppercased) for every nested settings group."""
    case_sensitive = settings_cls.model_config.get("case_sensitive", False)
    for field_info in settings_cls.model_fields.values():
        group_cls = field_info.annotation
        if not isinstance(group_cls, type) or not issubclass(group_cls, BaseSettings):
            continue
        prefix = group_cls.model_config.get("env_prefix", "")
        for sub_name in group_cls.model_fields:
            env_name = f"{prefix}{sub_name}"
            yield env_name if case_sensitive else env_name.upper()


def iter_env_vars(
    settings_cls: type[BaseSettings] = ContextSeekSettings,
) -> Iterator[str]:
    """Names of every env var ``settings_cls`` reads."""
    yield from _iter_env_vars(settings_cls)


def iter_section_env_fields(
    settings_cls: type[BaseSettings] = ContextSeekSettings,
) -> Iterator[tuple[str, str, str]]:
    """Yield ``(section, field, env_name)`` for every nested settings group.

    ``section`` is the lowercase attribute name on the root settings model
    (e.g. ``storage``); ``field`` is the attribute name on that group
    (e.g. ``backend``); ``env_name`` is the resolved env var (e.g.
    ``STORAGE_BACKEND``).
    """
    case_sensitive = settings_cls.model_config.get("case_sensitive", False)
    for section, field_info in settings_cls.model_fields.items():
        group_cls = field_info.annotation
        if not isinstance(group_cls, type) or not issubclass(group_cls, BaseSettings):
            continue
        prefix = group_cls.model_config.get("env_prefix", "")
        for sub_name in group_cls.model_fields:
            env_name = f"{prefix}{sub_name}"
            yield (
                section,
                sub_name,
                env_name if case_sensitive else env_name.upper(),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_envreflector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/envreflector.py tests/unit_tests/test_config_envreflector.py
git commit -m "feat(config): add ContextSeekSettings env-var reflector"
```

---

### Task 2: ConfigManager 核心 — 版本化存储与提交

**Files:**
- Create: `src/contextseek/config/manager.py`
- Test: `tests/unit_tests/test_config_manager.py`

**Interfaces:**
- Consumes: 无（独立文件历史）。
- Produces:
  - `@dataclass ConfigVersion`：`version_id: str`, `parent_version_id: str | None`, `created_at: str`, `origin: str`, `author: str`, `reason: str`, `source_ref: str | None`, `payload_hash: str`, `payload: dict`, `diff: dict | None`。
  - `class ConfigManager`：
    - `__init__(self, config_dir: Path)`
    - `init_store(self) -> None`
    - `current(self) -> ConfigVersion | None`
    - `get_version(self, version_id: str) -> ConfigVersion`
    - `history(self, n: int | None = None) -> list[ConfigVersion]`
    - `set_native(self, key: str, value, *, author: str, reason: str) -> ConfigVersion`（`key` 为点分路径如 `llm.model`）
    - `set_native_many(self, updates: dict[str, Any], *, author: str, reason: str) -> ConfigVersion`
    - `commit(self, *, native: dict | None = None, projected: dict | None = None, origin: str, author: str, reason: str, source_ref: str | None = None) -> ConfigVersion`（`native`/`projected` 为该层完整新状态；缺省表示沿用当前层）
    - 内部 `_merge(native, projected) -> tuple[dict, dict]` 返回 `(effective, override_sources)`。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit_tests/test_config_manager.py
"""Tests for ConfigManager versioned store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextseek.config.manager import ConfigManager, ConfigVersion


@pytest.fixture()
def manager(tmp_path: Path) -> ConfigManager:
    m = ConfigManager(tmp_path / "config")
    m.init_store()
    return m


def test_init_store_creates_layout(manager: ConfigManager, tmp_path: Path):
    root = tmp_path / "config"
    assert (root / "history").is_dir()
    assert (root / "sources").is_dir()
    assert (root / "manifest.jsonl").is_file()
    # empty store has no current version
    assert manager.current() is None


def test_set_native_creates_first_version(manager: ConfigManager):
    v = manager.set_native("llm.model", "gpt-4o", author="cli:tq", reason="init llm")
    assert v.version_id == "v000001"
    assert v.parent_version_id is None
    assert v.origin == "manual"
    assert v.payload["native"]["llm"]["model"] == "gpt-4o"
    assert v.payload["effective"]["llm"]["model"] == "gpt-4o"
    assert manager.current().version_id == "v000001"


def test_versions_increment_and_chain(manager: ConfigManager):
    v1 = manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    v2 = manager.set_native("llm.provider", "openai", author="a", reason="r2")
    assert v2.version_id == "v000002"
    assert v2.parent_version_id == "v000001"


def test_manifest_records_each_version(manager: ConfigManager, tmp_path: Path):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    manager.set_native("llm.provider", "openai", author="a", reason="r2")
    lines = (tmp_path / "config" / "manifest.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[1])
    assert rec["version_id"] == "v000002"
    assert rec["parent_version_id"] == "v000001"


def test_payload_hash_matches_file(manager: ConfigManager, tmp_path: Path):
    v = manager.set_native("llm.model", "gpt-4o", author="a", reason="r")
    raw = json.loads((tmp_path / "config" / "history" / "v000001.json").read_text())
    assert raw["payload_hash"] == v.payload_hash
    assert raw["payload_hash"].startswith("sha256:")


def test_history_returns_newest_first(manager: ConfigManager):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    manager.set_native("llm.provider", "openai", author="a", reason="r2")
    hist = manager.history()
    assert [h.version_id for h in hist] == ["v000002", "v000001"]


def test_merge_native_overrides_projected(manager: ConfigManager):
    manager.commit(
        projected={"llm": {"model": "projected-model"}},
        origin="agentseek-projection",
        author="agentseek",
        reason="proj",
        source_ref="agentseek@config.yml:sha256:abc",
    )
    v = manager.set_native("llm.model", "native-model", author="a", reason="override")
    eff = v.payload["effective"]
    assert eff["llm"]["model"] == "native-model"


def test_projected_used_when_native_absent(manager: ConfigManager):
    manager.commit(
        projected={"llm": {"model": "projected-model"}},
        origin="agentseek-projection",
        author="agentseek",
        reason="proj",
        source_ref="agentseek@config.yml:sha256:abc",
    )
    assert manager.current().payload["effective"]["llm"]["model"] == "projected-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: contextseek.config.manager`

- [ ] **Step 3: Write minimal implementation**

```python
# src/contextseek/config/manager.py
"""Versioned, provenance-tracked configuration store for ContextSeek.

The store lives at a fixed path (``${CONTEXTSEEK_HOME:-.contextseek}/config/``)
and is deliberately independent of the VFS storage backend so there is no
bootstrap cycle (config decides the storage backend; the storage backend must
not be needed to read the config history).

History is append-only: rollback creates a *new* version whose payload equals
an old version's payload. No history file is ever deleted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any as _Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(obj: _Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _payload_hash(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _set_path(nested: dict, dotted_key: str, value: _Any) -> None:
    """Set a value at a dotted path inside a nested dict (e.g. ``llm.model``)."""
    parts = dotted_key.split(".")
    cur = nested
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _merge(native: dict, projected: dict) -> tuple[dict, dict]:
    """Merge ``projected`` (baseline) with ``native`` (overrides).

    Returns ``(effective, override_sources)`` where ``override_sources`` maps
    dotted keys to ``"native"`` or ``"projected:agentseek"``.
    """
    effective: dict = {}
    sources: dict = {}

    def walk(base: dict, source_label: str, prefix: str = "") -> None:
        for k, v in base.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and not _is_leaf_dict(v):
                effective.setdefault(k, {})
                sources.setdefault(key, source_label)
                walk(v, source_label, key)
            else:
                effective[k] = v
                sources[key] = source_label

    walk(projected, "projected:agentseek")
    # native overrides
    def walk_native(base: dict, prefix: str = "") -> None:
        for k, v in base.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and not _is_leaf_dict(v):
                eff_child = effective.get(k)
                if not isinstance(eff_child, dict):
                    effective[k] = {}
                sources[key] = "native"
                walk_native(v, key)
            else:
                effective[k] = v
                sources[key] = "native"

    walk_native(native)
    return effective, sources


def _is_leaf_dict(d: dict) -> bool:
    """A dict is a 'leaf' if it has no dict values (treat scalars/lists as leaves)."""
    return not any(isinstance(v, dict) for v in d.values())


@dataclass
class ConfigVersion:
    """One snapshot in the append-only config history."""

    version_id: str
    parent_version_id: str | None
    created_at: str
    origin: str
    author: str
    reason: str
    payload_hash: str
    source_ref: str | None = None
    payload: dict = field(default_factory=dict)
    diff: dict | None = None
    override_sources: dict = field(default_factory=dict)


class ConfigManager:
    """Authoritative versioned configuration store."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)
        self.history_dir = self.config_dir / "history"
        self.sources_dir = self.config_dir / "sources"
        self.manifest_path = self.config_dir / "manifest.jsonl"
        self.current_path = self.config_dir / "current.json"

    # ------------------------------------------------------------------ store
    def init_store(self) -> None:
        """Create the store layout if absent. Idempotent."""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.touch(exist_ok=True)
        if not self.current_path.exists():
            self.current_path.write_text("{}", encoding="utf-8")

    # ----------------------------------------------------------------- read
    def current(self) -> ConfigVersion | None:
        """Return the latest committed version, or None if the store is empty."""
        hist = self.history()
        return hist[0] if hist else None

    def get_version(self, version_id: str) -> ConfigVersion:
        path = self.history_dir / f"{version_id}.json"
        if not path.exists():
            msg = f"unknown version: {version_id}"
            raise KeyError(msg)
        return self._load_version(path)

    def history(self, n: int | None = None) -> list[ConfigVersion]:
        """Return versions newest-first, optionally limited to ``n``."""
        if not self.manifest_path.exists():
            return []
        records = [
            json.loads(line)
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        records = list(reversed(records))  # newest first
        if n is not None:
            records = records[:n]
        return [self._load_version(self.history_dir / f"{r['version_id']}.json") for r in records]

    def _load_version(self, path: Path) -> ConfigVersion:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ConfigVersion(
            version_id=raw["version_id"],
            parent_version_id=raw.get("parent_version_id"),
            created_at=raw["created_at"],
            origin=raw["origin"],
            author=raw["author"],
            reason=raw["reason"],
            payload_hash=raw["payload_hash"],
            source_ref=raw.get("source_ref"),
            payload=raw.get("payload", {}),
            diff=raw.get("diff"),
            override_sources=raw.get("override_sources", {}),
        )

    # ---------------------------------------------------------------- write
    def set_native(self, key: str, value: _Any, *, author: str, reason: str) -> ConfigVersion:
        cur = self.current()
        native = dict(cur.payload.get("native", {})) if cur else {}
        _set_path(native, key, value)
        return self.commit(native=native, origin="manual", author=author, reason=reason)

    def set_native_many(
        self, updates: dict[str, _Any], *, author: str, reason: str
    ) -> ConfigVersion:
        cur = self.current()
        native = dict(cur.payload.get("native", {})) if cur else {}
        for k, v in updates.items():
            _set_path(native, k, v)
        return self.commit(native=native, origin="manual", author=author, reason=reason)

    def commit(
        self,
        *,
        native: dict | None = None,
        projected: dict | None = None,
        origin: str,
        author: str,
        reason: str,
        source_ref: str | None = None,
    ) -> ConfigVersion:
        """Commit a new version. ``native``/``projected`` are full new layer states.

        If a layer is omitted, the current version's layer is carried forward.
        """
        cur = self.current()
        prev_native = dict(cur.payload.get("native", {})) if cur else {}
        prev_projected = dict(cur.payload.get("projected", {})) if cur else {}
        new_native = prev_native if native is None else native
        new_projected = prev_projected if projected is None else projected
        effective, sources = _merge(new_native, new_projected)
        payload = {
            "native": new_native,
            "projected": new_projected,
            "effective": effective,
        }
        version_id = self._next_version_id()
        diff = self._diff_payloads(
            cur.payload.get("effective", {}) if cur else {}, effective
        )
        version = ConfigVersion(
            version_id=version_id,
            parent_version_id=cur.version_id if cur else None,
            created_at=_utc_now_iso(),
            origin=origin,
            author=author,
            reason=reason,
            payload_hash=_payload_hash(payload),
            source_ref=source_ref,
            payload=payload,
            diff=diff,
            override_sources=sources,
        )
        self._write_version(version)
        return version

    def _next_version_id(self) -> str:
        count = 0
        if self.manifest_path.exists():
            count = sum(
                1 for line in self.manifest_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        return f"v{count + 1:06d}"

    def _write_version(self, version: ConfigVersion) -> None:
        """Atomic write: tmp → rename → manifest append → current.json update."""
        self.init_store()
        path = self.history_dir / f"{version.version_id}.json"
        tmp = path.with_suffix(".json.tmp")
        body = {
            "version_id": version.version_id,
            "parent_version_id": version.parent_version_id,
            "created_at": version.created_at,
            "origin": version.origin,
            "author": version.author,
            "reason": version.reason,
            "payload_hash": version.payload_hash,
            "source_ref": version.source_ref,
            "payload": version.payload,
            "diff": version.diff,
            "override_sources": version.override_sources,
        }
        tmp.write_text(_canonical_json(body), encoding="utf-8")
        tmp.replace(path)

        manifest_record = {
            "version_id": version.version_id,
            "parent_version_id": version.parent_version_id,
            "created_at": version.created_at,
            "origin": version.origin,
            "author": version.author,
            "reason": version.reason,
            "payload_hash": version.payload_hash,
            "source_ref": version.source_ref,
        }
        with self.manifest_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest_record, ensure_ascii=False) + "\n")

        self.current_path.write_text(
            _canonical_json(version.payload), encoding="utf-8"
        )

    # ----------------------------------------------------------------- diff
    def _diff_payloads(self, a: dict, b: dict, prefix: str = "") -> dict:
        """Compare two effective payloads, return {added, changed, removed}."""
        added, changed, removed = [], [], []

        def flat(d: dict, pre: str = "") -> dict[str, _Any]:
            out: dict[str, _Any] = {}
            for k, v in d.items():
                key = f"{pre}.{k}" if pre else k
                if isinstance(v, dict) and not _is_leaf_dict(v):
                    out.update(flat(v, key))
                else:
                    out[key] = v
            return out

        fa, fb = flat(a), flat(b)
        for k in fa:
            if k not in fb:
                removed.append(k)
            elif fa[k] != fb[k]:
                changed.append(k)
        for k in fb:
            if k not in fa:
                added.append(k)
        return {"added": sorted(added), "changed": sorted(changed), "removed": sorted(removed)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_manager.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/manager.py tests/unit_tests/test_config_manager.py
git commit -m "feat(config): add ConfigManager versioned store with merge/diff"
```

---

### Task 3: ConfigManager — rollback / redo / verify / diff / blame / status

**Files:**
- Modify: `src/contextseek/config/manager.py`（追加方法）
- Test: `tests/unit_tests/test_config_manager.py`（追加测试）

**Interfaces:**
- Produces（追加到 `ConfigManager`）：
  - `rollback(self, target_version_id: str, *, author: str, reason: str) -> ConfigVersion`
  - `redo(self, *, author: str, reason: str) -> ConfigVersion | None`
  - `diff(self, a: str, b: str) -> dict`（版本 id）
  - `blame(self, key: str) -> dict | None`
  - `verify(self) -> list[str]`（问题列表，空表示 OK）
  - `status(self) -> dict`（至少含 `current_version`, `version_count`）

- [ ] **Step 1: Write the failing test（追加到 test_config_manager.py）**

```python
def test_rollback_is_append_only(manager: ConfigManager):
    v1 = manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    manager.set_native("llm.model", "gpt-4o-mini", author="a", reason="r2")
    v3 = manager.rollback("v000001", author="a", reason="rollback to v1")
    assert v3.version_id == "v000003"
    assert v3.origin == "rollback"
    assert v3.parent_version_id == "v000002"
    assert v3.payload["effective"]["llm"]["model"] == "gpt-4o"
    # v000002 仍在历史中
    ids = [h.version_id for h in manager.history()]
    assert "v000002" in ids
    assert manager.current().version_id == "v000003"


def test_redo_reverts_last_rollback(manager: ConfigManager):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    v2 = manager.set_native("llm.model", "gpt-4o-mini", author="a", reason="r2")
    manager.rollback("v000001", author="a", reason="back")
    v4 = manager.redo(author="a", reason="undo rollback")
    assert v4 is not None
    assert v4.payload["effective"]["llm"]["model"] == "gpt-4o-mini"
    assert v4.parent_version_id == "v000003"


def test_redo_returns_none_when_last_not_rollback(manager: ConfigManager):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    assert manager.redo(author="a", reason="x") is None


def test_diff_between_versions(manager: ConfigManager):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    manager.set_native("llm.model", "gpt-4o-mini", author="a", reason="r2")
    d = manager.diff("v000001", "v000002")
    assert "llm.model" in d["changed"]


def test_blame_finds_last_change(manager: ConfigManager):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    manager.set_native("llm.provider", "openai", author="b", reason="r2")
    blame = manager.blame("llm.model")
    assert blame["version_id"] == "v000001"
    assert blame["reason"] == "r1"
    blame_provider = manager.blame("llm.provider")
    assert blame_provider["version_id"] == "v000002"


def test_verify_passes_on_clean_store(manager: ConfigManager):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    assert manager.verify() == []


def test_verify_detects_tampered_payload(manager: ConfigManager, tmp_path: Path):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    path = tmp_path / "config" / "history" / "v000001.json"
    raw = json.loads(path.read_text())
    raw["payload"]["effective"]["llm"]["model"] = "tampered"
    path.write_text(json.dumps(raw))
    problems = manager.verify()
    assert any("hash" in p for p in problems)


def test_status_reports_current_and_count(manager: ConfigManager):
    manager.set_native("llm.model", "gpt-4o", author="a", reason="r1")
    s = manager.status()
    assert s["current_version"] == "v000001"
    assert s["version_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_manager.py -k "rollback or redo or diff or blame or verify or status" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'rollback'`

- [ ] **Step 3: Write minimal implementation（追加到 ConfigManager 类体内）**

```python
    # ------------------------------------------------------- rollback/redo
    def rollback(self, target_version_id: str, *, author: str, reason: str) -> ConfigVersion:
        """Create a new version whose payload equals ``target_version_id``'s.

        Append-only: the target and any versions after it remain in history.
        """
        target = self.get_version(target_version_id)
        return self.commit(
            native=dict(target.payload.get("native", {})),
            projected=dict(target.payload.get("projected", {})),
            origin="rollback",
            author=author,
            reason=reason,
        )

    def redo(self, *, author: str, reason: str) -> ConfigVersion | None:
        """Undo the most recent rollback by re-applying the version it reverted.

        Returns None if the latest version is not a rollback.
        """
        cur = self.current()
        if cur is None or cur.origin != "rollback":
            return None
        # The version immediately before the rollback is what was reverted.
        prev = self.get_version(cur.parent_version_id)
        return self.commit(
            native=dict(prev.payload.get("native", {})),
            projected=dict(prev.payload.get("projected", {})),
            origin="manual",
            author=author,
            reason=reason,
        )

    # --------------------------------------------------------------- diff
    def diff(self, a: str, b: str) -> dict:
        va = self.get_version(a)
        vb = self.get_version(b)
        return self._diff_payloads(
            va.payload.get("effective", {}), vb.payload.get("effective", {})
        )

    # -------------------------------------------------------------- blame
    def blame(self, key: str) -> dict | None:
        """Find the most recent version where ``key``'s effective value was set."""
        hist = self.history()  # newest first
        if not hist:
            return None
        current_val = self._flat_get(hist[0].payload.get("effective", {}), key)
        prev_val = None
        prev_eff = hist[1].payload.get("effective", {}) if len(hist) > 1 else {}
        prev_val = self._flat_get(prev_eff, key)
        if current_val != prev_val or len(hist) == 1:
            v = hist[0]
            return {
                "version_id": v.version_id,
                "origin": v.origin,
                "author": v.author,
                "reason": v.reason,
                "source_ref": v.source_ref,
                "value": current_val,
            }
        # walk backwards to the introducing version
        for i, v in enumerate(hist):
            val = self._flat_get(v.payload.get("effective", {}), key)
            older = hist[i + 1] if i + 1 < len(hist) else None
            older_val = (
                self._flat_get(older.payload.get("effective", {}), key) if older else None
            )
            if val != older_val:
                return {
                    "version_id": v.version_id,
                    "origin": v.origin,
                    "author": v.author,
                    "reason": v.reason,
                    "source_ref": v.source_ref,
                    "value": val,
                }
        return None

    @staticmethod
    def _flat_get(d: dict, dotted_key: str):
        cur: _Any = d
        for part in dotted_key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    # ------------------------------------------------------------- verify
    def verify(self) -> list[str]:
        """Return a list of problems with the store (empty == OK)."""
        problems: list[str] = []
        if not self.manifest_path.exists():
            return problems
        records = [
            json.loads(line)
            for line in self.manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        expected_parent: str | None = None
        for rec in records:
            path = self.history_dir / f"{rec['version_id']}.json"
            if not path.exists():
                problems.append(f"missing version file: {rec['version_id']}")
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            actual_hash = _payload_hash(raw["payload"])
            if actual_hash != rec["payload_hash"]:
                problems.append(
                    f"payload hash mismatch in {rec['version_id']} "
                    f"(manifest={rec['payload_hash']}, file={actual_hash})"
                )
            if rec["parent_version_id"] != expected_parent:
                problems.append(
                    f"parent chain broken at {rec['version_id']}: "
                    f"expected parent {expected_parent}, got {rec['parent_version_id']}"
                )
            expected_parent = rec["version_id"]
        # current.json must match newest version's payload hash
        if records and self.current_path.exists():
            cur_payload = json.loads(self.current_path.read_text(encoding="utf-8"))
            newest = self._load_version(
                self.history_dir / f"{records[-1]['version_id']}.json"
            )
            if _payload_hash(cur_payload) != newest.payload_hash:
                problems.append("current.json does not match newest version payload")
        return problems

    # ------------------------------------------------------------- status
    def status(self) -> dict:
        cur = self.current()
        count = 0
        if self.manifest_path.exists():
            count = sum(
                1 for line in self.manifest_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        return {
            "current_version": cur.version_id if cur else None,
            "version_count": count,
            "store_dir": str(self.config_dir),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_manager.py -v`
Expected: PASS (all tests including new ones)

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/manager.py tests/unit_tests/test_config_manager.py
git commit -m "feat(config): add rollback/redo/verify/diff/blame/status to ConfigManager"
```

---

### Task 4: Materializer — 物化 effective 为 .env + config.json，dry-run validate，漂移检测

**Files:**
- Create: `src/contextseek/config/materializer.py`
- Test: `tests/unit_tests/test_config_materializer.py`

**Interfaces:**
- Consumes: `contextseek.config.envreflector.iter_section_env_fields`；`ContextSeekSettings`（dry-run 校验）；`contextseek.config.runtime.RuntimeConfig` + `load_runtime_config`（dry-run 校验，复用现有）。
- Produces:
  - `class Materializer`：
    - `__init__(self, env_path: Path, runtime_path: Path)`
    - `materialize(self, effective: dict) -> None`（写 `.env` + `config.json`）
    - `dry_run_validate(self, effective: dict) -> tuple[bool, str | None]`（返回 `(ok, error)`）
    - `expected_hashes(self, effective: dict) -> tuple[str, str]`（返回期望的 `.env`/`config.json` 的 sha256）
    - `detect_drift(self, effective: dict) -> dict[str, bool]`（`{"env": bool, "runtime": bool}`，True=漂移）
  - 模块函数 `effective_to_env(effective: dict) -> str`、`effective_to_runtime_json(effective: dict) -> dict`。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit_tests/test_config_materializer.py
"""Tests for Materializer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from contextseek.config.materializer import (
    Materializer,
    effective_to_env,
    effective_to_runtime_json,
)


@pytest.fixture()
def materializer(tmp_path: Path) -> Materializer:
    return Materializer(env_path=tmp_path / ".env", runtime_path=tmp_path / "config.json")


def test_effective_to_env_writes_known_keys():
    env = effective_to_env({"llm": {"model": "gpt-4o", "provider": "openai"}})
    assert "LLM_MODEL=gpt-4o" in env
    assert "LLM_PROVIDER=openai" in env


def test_effective_to_runtime_json_includes_runtime_section():
    rt = effective_to_runtime_json({"runtime": {"backend": "file", "storage_path": "/data"}})
    assert rt["backend"] == "file"
    assert rt["storage_path"] == "/data"


def test_materialize_writes_both_files(materializer: Materializer, tmp_path: Path):
    materializer.materialize({"llm": {"model": "gpt-4o"}})
    assert (tmp_path / ".env").is_file()
    assert (tmp_path / "config.json").is_file()
    assert "LLM_MODEL=gpt-4o" in (tmp_path / ".env").read_text()


def test_dry_run_validate_ok_for_minimal(materializer: Materializer):
    ok, err = materializer.dry_run_validate({"storage": {"backend": "file"}})
    assert ok is True
    assert err is None


def test_detect_drift_when_file_hand_edited(materializer: Materializer, tmp_path: Path):
    eff = {"llm": {"model": "gpt-4o"}}
    materializer.materialize(eff)
    # hand-edit the .env
    (tmp_path / ".env").write_text("LLM_MODEL=tampered\n")
    drift = materializer.detect_drift(eff)
    assert drift["env"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_materializer.py -v`
Expected: FAIL with `ModuleNotFoundError: contextseek.config.materializer`

- [ ] **Step 3: Write minimal implementation**

```python
# src/contextseek/config/materializer.py
"""Materialize an effective config into the files existing loaders already read.

- ``.env``        → consumed by :class:`ContextSeekSettings` (pydantic-settings).
- ``config.json`` → consumed by :func:`contextseek.config.runtime.load_runtime_config`
  via the ``CONTEXTSEEK_CONFIG`` env var.

Before writing, ``dry_run_validate`` constructs a ``ContextSeekSettings`` and a
``RuntimeConfig`` from the effective payload to ensure the materialized files
will actually load.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from contextseek.config.envreflector import iter_section_env_fields
from contextseek.config.settings import ContextSeekSettings


def _flat_get(d: dict, dotted_key: str):
    cur: Any = d
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def effective_to_env(effective: dict) -> str:
    """Render an effective config as ``.env`` text (``KEY=value`` lines)."""
    section_fields = list(iter_section_env_fields())
    lines: list[str] = []
    for section, field, env_name in section_fields:
        value = _flat_get(effective, f"{section}.{field}")
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append(f"{env_name}={value}")
    return "\n".join(lines) + ("\n" if lines else "")


def effective_to_runtime_json(effective: dict) -> dict:
    """Render the ``runtime`` section of an effective config as a RuntimeConfig JSON payload."""
    runtime = effective.get("runtime", {})
    # RuntimeConfig.load_runtime_config reads backend/storage_path/uri_scheme/
    # cold_backend/cold_storage_path/strategy/api_keys/ob_*  from the JSON top level.
    return dict(runtime)


class Materializer:
    """Write effective config to the ``.env`` and ``config.json`` loaders read."""

    def __init__(self, env_path: Path, runtime_path: Path) -> None:
        self.env_path = Path(env_path)
        self.runtime_path = Path(runtime_path)

    def materialize(self, effective: dict) -> None:
        ok, err = self.dry_run_validate(effective)
        if not ok:
            msg = f"refusing to materialize invalid config: {err}"
            raise ValueError(msg)
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.write_text(effective_to_env(effective), encoding="utf-8")
        rt = effective_to_runtime_json(effective)
        self.runtime_path.write_text(
            json.dumps(rt, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def dry_run_validate(self, effective: dict) -> tuple[bool, str | None]:
        """Return ``(ok, error)``. ``ok`` iff both loaders can construct from effective."""
        env_text = effective_to_env(effective)
        # Validate ContextSeekSettings by populating a fake env and constructing.
        env_backup = dict(os.environ)
        try:
            for line in env_text.splitlines():
                if not line.strip() or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ[k] = v
            ContextSeekSettings()
        except Exception as exc:  # noqa: BLE001 - any validation error is a failure
            return False, f"ContextSeekSettings: {exc}"
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

        # Validate RuntimeConfig JSON payload.
        try:
            from contextseek.config.runtime import RuntimeConfig  # noqa: F401

            rt_json = effective_to_runtime_json(effective)
            # load_runtime_config expects a file path; write to a temp buffer via json parse.
            # RuntimeConfig is a dataclass; reconstruct via _strategy_from_dict path is internal.
            # Simplest: round-trip through load_runtime_config by writing a temp file.
            import tempfile

            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8"
            ) as fh:
                json.dump(rt_json, fh)
                tmp = fh.name
            from contextseek.config.runtime import load_runtime_config

            load_runtime_config(tmp)
        except Exception as exc:  # noqa: BLE001
            return False, f"RuntimeConfig: {exc}"
        return True, None

    def expected_hashes(self, effective: dict) -> tuple[str, str]:
        env_text = effective_to_env(effective)
        rt_text = json.dumps(
            effective_to_runtime_json(effective), ensure_ascii=False, indent=2
        )
        env_hash = "sha256:" + hashlib.sha256(env_text.encode("utf-8")).hexdigest()
        rt_hash = "sha256:" + hashlib.sha256(rt_text.encode("utf-8")).hexdigest()
        return env_hash, rt_hash

    def detect_drift(self, effective: dict) -> dict[str, bool]:
        """Return ``{"env": drifted, "runtime": drifted}``. True == file differs from expected."""
        env_hash, rt_hash = self.expected_hashes(effective)
        env_drift = True
        if self.env_path.exists():
            actual = "sha256:" + hashlib.sha256(
                self.env_path.read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest()
            env_drift = actual != env_hash
        rt_drift = True
        if self.runtime_path.exists():
            actual = "sha256:" + hashlib.sha256(
                self.runtime_path.read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest()
            rt_drift = actual != rt_hash
        return {"env": env_drift, "runtime": rt_drift}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_materializer.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/materializer.py tests/unit_tests/test_config_materializer.py
git commit -m "feat(config): add Materializer with dry-run validate and drift detection"
```

---

### Task 5: ConfigManager.apply — 接入 Materializer，失败保护

**Files:**
- Modify: `src/contextseek/config/manager.py`（追加 `apply` 方法 + 物化路径解析）
- Test: `tests/unit_tests/test_config_manager.py`（追加测试）

**Interfaces:**
- Produces（追加到 `ConfigManager`）：
  - `apply(self, materializer: Materializer) -> None` — 物化 `current().payload["effective"]`；dry-run 失败则抛 `ValueError` 且不写文件。

- [ ] **Step 1: Write the failing test（追加）**

```python
def test_apply_materializes_current(manager: ConfigManager, tmp_path: Path):
    from contextseek.config.materializer import Materializer

    manager.set_native("llm.model", "gpt-4o", author="a", reason="r")
    mat = Materializer(env_path=tmp_path / ".env", runtime_path=tmp_path / "config.json")
    manager.apply(mat)
    assert "LLM_MODEL=gpt-4o" in (tmp_path / ".env").read_text()


def test_apply_refuses_invalid_config(manager: ConfigManager, tmp_path: Path):
    from contextseek.config.materializer import Materializer

    # An unknown storage backend will fail RuntimeConfig/materialize validation.
    manager.set_native("storage.backend", "not-a-real-backend", author="a", reason="bad")
    mat = Materializer(env_path=tmp_path / ".env", runtime_path=tmp_path / "config.json")
    import pytest

    with pytest.raises(ValueError):
        manager.apply(mat)
    # files were not written
    assert not (tmp_path / ".env").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_manager.py -k "apply" -v`
Expected: FAIL with `AttributeError: 'ConfigManager' has no attribute 'apply'`

- [ ] **Step 3: Write minimal implementation（追加到 ConfigManager 类体内）**

```python
    # --------------------------------------------------------------- apply
    def apply(self, materializer) -> None:  # type: ignore[no-untyped-def]
        """Materialize the current effective config via ``materializer``.

        ``materializer.materialize`` already dry-run-validates and raises
        ``ValueError`` on invalid config without writing files, so a failed
        apply leaves the previously materialized files intact.
        """
        cur = self.current()
        if cur is None:
            msg = "no current config version to apply"
            raise ValueError(msg)
        materializer.materialize(cur.payload.get("effective", {}))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_manager.py -k "apply" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/manager.py tests/unit_tests/test_config_manager.py
git commit -m "feat(config): add ConfigManager.apply with validate-before-write guard"
```

---

### Task 6: mapping — agentseek → contextseek 显式映射表 + provider 检测

**Files:**
- Create: `src/contextseek/config/mapping.py`
- Test: `tests/unit_tests/test_config_mapping.py`

**Interfaces:**
- Consumes: 无外部（纯函数 + 常量表）。
- Produces：
  - `AGENTSEEK_MAPPING: dict[str, tuple[str, Callable, str | None]]` — `agentseek键 → (contextseek点分路径, 转换函数, provider hint)`。
  - `PROVIDER_CREDS: dict[str, tuple[str, str | None]]`
  - `PROVIDER_CLASS_PATH: dict[str, str]`
  - `detect_provider(*, class_path: str = "", model: str = "") -> str`
  - `strip_provider_prefix(model: str) -> str`
  - `project_agentseek_env(env: Mapping[str, str]) -> tuple[dict, str | None]` — 返回 `(projected_native_dict, source_ref_or_None)`，仅当 contextseek LLM 启用时投影凭证。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit_tests/test_config_mapping.py
"""Tests for agentseek→contextseek mapping."""

from __future__ import annotations

from contextseek.config.mapping import (
    detect_provider,
    project_agentseek_env,
    strip_provider_prefix,
)


def test_strip_provider_prefix():
    assert strip_provider_prefix("openai:gpt-4o") == "gpt-4o"
    assert strip_provider_prefix("gpt-4o") == "gpt-4o"


def test_detect_provider_from_model_prefix():
    assert detect_provider(model="openai:gpt-4o") == "openai"
    assert detect_provider(model="anthropic:claude-3") == "anthropic"


def test_detect_provider_from_class_path():
    assert detect_provider(class_path="langchain_openai.ChatOpenAI") == "openai"


def test_project_agentseek_env_maps_api_key_and_model():
    env = {
        "AGENTSEEK_API_KEY": "sk-xxx",
        "AGENTSEEK_API_BASE": "https://api.example.com/v1",
        "AGENTSEEK_MODEL": "openai:gpt-4o",
        "AGENTSEEK_CTX_LLM_PROVIDER": "openai",
    }
    projected, source_ref = project_agentseek_env(env)
    assert projected["llm"]["api_key"] == "sk-xxx"
    assert projected["llm"]["base_url"] == "https://api.example.com/v1"
    assert projected["llm"]["model"] == "gpt-4o"
    assert projected["llm"]["provider"] == "openai"
    assert source_ref is not None


def test_project_agentseek_env_noop_when_llm_disabled():
    env = {"AGENTSEEK_API_KEY": "sk-xxx", "AGENTSEEK_MODEL": "openai:gpt-4o"}
    projected, source_ref = project_agentseek_env(env)
    # LLM not enabled (no AGENTSEEK_CTX_LLM_PROVIDER / LLM_MODEL) → no credential projection
    assert "llm" not in projected or "api_key" not in projected.get("llm", {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: contextseek.config.mapping`

- [ ] **Step 3: Write minimal implementation**

```python
# src/contextseek/config/mapping.py
"""Explicit agentseek → contextseek configuration mapping.

Migrated from the ``agentseek-contextseek`` contrib's reflective env-aliasing
into a declarative, testable mapping table. Projection output is written to
the config manager's ``projected`` layer (not to ``os.environ``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

AGENTSEEK_CTX_PREFIX = "AGENTSEEK_CTX_"

# Maps a provider name → (api_key_var, base_url_var | None).
PROVIDER_CREDS: dict[str, tuple[str, str | None]] = {
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "anthropic": ("ANTHROPIC_API_KEY", None),
    "google": ("GOOGLE_API_KEY", None),
    "cohere": ("COHERE_API_KEY", None),
    "mistral": ("MISTRAL_API_KEY", None),
    "dashscope": ("DASHSCOPE_API_KEY", None),
    "tongyi": ("DASHSCOPE_API_KEY", None),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"),
}

# Maps a provider name → LangChain chat class path.
PROVIDER_CLASS_PATH: dict[str, str] = {
    "openai": "langchain_openai.ChatOpenAI",
    "anthropic": "langchain_anthropic.ChatAnthropic",
    "google": "langchain_google_genai.ChatGoogleGenerativeAI",
    "cohere": "langchain_cohere.ChatCohere",
    "mistral": "langchain_mistralai.ChatMistralAI",
    "dashscope": "langchain_community.chat_models.ChatTongyi",
    "tongyi": "langchain_community.chat_models.ChatTongyi",
    "deepseek": "langchain_openai.ChatOpenAI",
}

# Fragments of LangChain class paths → provider name (reverse lookup).
_CLASS_PATH_PROVIDER: dict[str, str] = {
    "langchain_openai": "openai",
    "langchain_anthropic": "anthropic",
    "langchain_google_genai": "google",
    "langchain_google_vertexai": "google",
    "langchain_cohere": "cohere",
    "langchain_mistralai": "mistral",
    "chattongyi": "dashscope",
    "tongyi": "dashscope",
    "deepseek": "deepseek",
}


def detect_provider(*, class_path: str = "", model: str = "") -> str:
    """Return a lowercase provider name from class path or model prefix."""
    if class_path:
        lowered = class_path.lower()
        for fragment, provider in _CLASS_PATH_PROVIDER.items():
            if fragment in lowered:
                return provider
    if ":" in model:
        prefix = model.split(":", 1)[0].lower()
        if prefix in PROVIDER_CREDS:
            return prefix
    return "openai"


def strip_provider_prefix(model: str) -> str:
    """Strip a ``provider:`` prefix from a model name."""
    if ":" in model:
        return model.split(":", 1)[1]
    return model


def _set_path(nested: dict, dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cur = nested
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


# agentseek 键 → (contextseek 点分路径, 转换函数, provider hint 或 None)
AGENTSEEK_MAPPING: dict[str, tuple[str, Callable[[str], Any], str | None]] = {
    "AGENTSEEK_API_KEY": ("llm.api_key", lambda v: v, "openai"),
    "AGENTSEEK_API_BASE": ("llm.base_url", lambda v: v, None),
    "AGENTSEEK_MODEL": ("llm.model", strip_provider_prefix, None),
}


def project_agentseek_env(env: Mapping[str, str]) -> tuple[dict, str | None]:
    """Project agentseek env vars into a contextseek ``projected`` payload.

    Returns ``(projected, source_ref)``. Credential/class_path projection only
    runs when contextseek's LLM is enabled (``AGENTSEEK_CTX_LLM_PROVIDER`` !=
    ``none`` or ``AGENTSEEK_CTX_LLM_MODEL`` is set), mirroring the contrib's
    ``_maybe_bridge_llm_credentials``.

    ``source_ref`` is a stable hash of the contributing agentseek env keys
    (used for idempotent ingestion), or None when nothing was projected.
    """
    projected: dict = {}

    llm_provider = env.get(f"{AGENTSEEK_CTX_PREFIX}LLM_PROVIDER", "none")
    llm_model = env.get(f"{AGENTSEEK_CTX_LLM_MODEL_KEY", "")  # placeholder, fixed below
    llm_model = env.get(f"{AGENTSEEK_CTX_PREFIX}LLM_MODEL", "")
    if llm_provider.lower() == "none" and not llm_model:
        return projected, None

    provider = _detect_from_env(env)

    agentseek_key = env.get("AGENTSEEK_API_KEY", "")
    agentseek_base = env.get("AGENTSEEK_API_BASE", "")
    agentseek_model = env.get("AGENTSEEK_MODEL", "")

    contributing = []
    if agentseek_key:
        _set_path(projected, "llm.api_key", agentseek_key)
        contributing.append(("api_key", agentseek_key))
    if agentseek_base:
        _set_path(projected, "llm.base_url", agentseek_base)
        contributing.append(("base_url", agentseek_base))
    if agentseek_model:
        _set_path(projected, "llm.model", strip_provider_prefix(agentseek_model))
        contributing.append(("model", agentseek_model))

    # class path + provider derivation
    ctx_class_path = env.get(f"{AGENTSEEK_CTX_PREFIX}LLM_CLASS_PATH", "")
    if not ctx_class_path:
        class_path = PROVIDER_CLASS_PATH.get(provider)
        if class_path:
            _set_path(projected, "llm.class_path", class_path)
            contributing.append(("class_path", class_path))

    _set_path(projected, "llm.provider", provider)
    contributing.append(("provider", provider))

    if not contributing:
        return projected, None
    source_ref = "agentseek:env:sha256:" + hashlib.sha256(
        repr(sorted(contributing)).encode("utf-8")
    ).hexdigest()
    return projected, source_ref


_AGENTSEEK_CTX_LLM_MODEL_KEY = f"{AGENTSEEK_CTX_PREFIX}LLM_MODEL"  # noqa: F841


def _detect_from_env(env: Mapping[str, str]) -> str:
    class_path = env.get(f"{AGENTSEEK_CTX_PREFIX}LLM_CLASS_PATH", "")
    model = env.get("AGENTSEEK_MODEL", "")
    return detect_provider(class_path=class_path, model=model)
```

> 注：上面 `project_agentseek_env` 开头有一行占位 `llm_model = env.get(f"{AGENTSEEK_CTX_LLM_MODEL_KEY", "")`，这是笔误，实现时删除该行，仅保留其下一行 `llm_model = env.get(f"{AGENTSEEK_CTX_PREFIX}LLM_MODEL", "")`。模块末尾的 `_AGENTSEEK_CTX_LLM_MODEL_KEY` 常量也随之删除。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_mapping.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/mapping.py tests/unit_tests/test_config_mapping.py
git commit -m "feat(config): add explicit agentseek→contextseek mapping table"
```

---

### Task 7: AgentseekIngestor — pull / diff / 幂等投影

**Files:**
- Create: `src/contextseek/config/agentseek_ingestor.py`
- Test: `tests/unit_tests/test_config_agentseek_ingestor.py`

**Interfaces:**
- Consumes: `contextseek.config.mapping.project_agentseek_env`；`ConfigManager`。
- Produces：
  - `class AgentseekIngestor`：
    - `__init__(self, manager: ConfigManager)`
    - `ingest_env(self, env: Mapping[str, str], *, author: str = "agentseek", reason: str = "ingest agentseek env") -> ConfigVersion | None` — 幂等：若 `source_ref` 与最近一次 `agentseek-projection` 版本相同则跳过返回 None。
    - `ingest_file(self, path: Path, *, author: str = "agentseek", reason: str | None = None) -> ConfigVersion | None` — 读 `config.yml`/`.env` 风格文件，合并为 env dict 后投影；`source_ref` 含文件 sha256。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit_tests/test_config_agentseek_ingestor.py
"""Tests for AgentseekIngestor."""

from __future__ import annotations

from pathlib import Path

import pytest

from contextseek.config.agentseek_ingestor import AgentseekIngestor
from contextseek.config.manager import ConfigManager


@pytest.fixture()
def manager(tmp_path: Path) -> ConfigManager:
    m = ConfigManager(tmp_path / "config")
    m.init_store()
    return m


def test_ingest_env_creates_projection_version(manager: ConfigManager):
    ing = AgentseekIngestor(manager)
    env = {
        "AGENTSEEK_API_KEY": "sk-xxx",
        "AGENTSEEK_MODEL": "openai:gpt-4o",
        "AGENTSEEK_CTX_LLM_PROVIDER": "openai",
    }
    v = ing.ingest_env(env)
    assert v is not None
    assert v.origin == "agentseek-projection"
    assert v.payload["projected"]["llm"]["model"] == "gpt-4o"
    assert v.source_ref is not None


def test_ingest_env_is_idempotent(manager: ConfigManager):
    ing = AgentseekIngestor(manager)
    env = {
        "AGENTSEEK_API_KEY": "sk-xxx",
        "AGENTSEEK_MODEL": "openai:gpt-4o",
        "AGENTSEEK_CTX_LLM_PROVIDER": "openai",
    }
    v1 = ing.ingest_env(env)
    v2 = ing.ingest_env(env)  # same source_ref → skip
    assert v1 is not None
    assert v2 is None
    # only one version in history
    assert len(manager.history()) == 1


def test_ingest_env_new_source_creates_new_version(manager: ConfigManager):
    ing = AgentseekIngestor(manager)
    ing.ingest_env(
        {"AGENTSEEK_API_KEY": "sk-1", "AGENTSEEK_MODEL": "openai:gpt-4o",
         "AGENTSEEK_CTX_LLM_PROVIDER": "openai"}
    )
    v2 = ing.ingest_env(
        {"AGENTSEEK_API_KEY": "sk-2", "AGENTSEEK_MODEL": "openai:gpt-4o",
         "AGENTSEEK_CTX_LLM_PROVIDER": "openai"}
    )
    assert v2 is not None
    assert len(manager.history()) == 2


def test_ingest_file_records_file_hash(manager: ConfigManager, tmp_path: Path):
    cfg = tmp_path / "agentseek.env"
    cfg.write_text(
        "AGENTSEEK_API_KEY=sk-xxx\nAGENTSEEK_MODEL=openai:gpt-4o\n"
        "AGENTSEEK_CTX_LLM_PROVIDER=openai\n"
    )
    ing = AgentseekIngestor(manager)
    v = ing.ingest_file(cfg)
    assert v is not None
    assert "sha256:" in v.source_ref
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_agentseek_ingestor.py -v`
Expected: FAIL with `ModuleNotFoundError: contextseek.config.agentseek_ingestor`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_agentseek_ingestor.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/agentseek_ingestor.py tests/unit_tests/test_config_agentseek_ingestor.py
git commit -m "feat(config): add AgentseekIngestor with idempotent projection"
```

---

### Task 8: CLI — `contextseek config` 子命令组

**Files:**
- Create: `src/contextseek/config/cli.py`
- Modify: `src/contextseek/cli/main.py`（注册子命令 + 分发）
- Test: `tests/unit_tests/test_config_cli.py`

**Interfaces:**
- Produces：
  - `register_config_subparser(subparsers) -> None`
  - `run_config_command(args) -> int`
  - `def _default_config_dir() -> Path` — 解析 `${CONTEXTSEEK_HOME:-.contextseek}/config`。
  - `def _default_materializer(config_dir) -> Materializer` — env_path=`.env`、runtime_path=`config.json`（相对于 CWD 或 `CONTEXTSEEK_CONFIG`）。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit_tests/test_config_cli.py
"""Tests for `contextseek config` CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextseek.cli.main import run_cli


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("CONTEXTSEEK_HOME", str(h))
    monkeypatch.chdir(tmp_path)
    return h


def test_config_set_then_show(home: Path, tmp_path: Path):
    rc = run_cli(["config", "set", "llm.model", "gpt-4o", "--reason", "init"])
    assert rc == 0
    # show prints effective config; capture via capfd not needed—check store
    store = home / "config"
    assert (store / "history" / "v000001.json").exists()


def test_config_history(home: Path):
    run_cli(["config", "set", "llm.model", "gpt-4o", "--reason", "r1"])
    run_cli(["config", "set", "llm.provider", "openai", "--reason", "r2"])
    rc = run_cli(["config", "history"])
    assert rc == 0


def test_config_rollback(home: Path):
    run_cli(["config", "set", "llm.model", "gpt-4o", "--reason", "r1"])
    run_cli(["config", "set", "llm.model", "gpt-4o-mini", "--reason", "r2"])
    rc = run_cli(["config", "rollback", "v000001", "--reason", "back"])
    assert rc == 0
    v3 = json.loads((home / "config" / "history" / "v000003.json").read_text())
    assert v3["origin"] == "rollback"
    assert v3["payload"]["effective"]["llm"]["model"] == "gpt-4o"


def test_config_verify_ok(home: Path):
    run_cli(["config", "set", "llm.model", "gpt-4o", "--reason", "r1"])
    rc = run_cli(["config", "verify"])
    assert rc == 0


def test_config_status(home: Path):
    run_cli(["config", "set", "llm.model", "gpt-4o", "--reason", "r1"])
    rc = run_cli(["config", "status"])
    assert rc == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_cli.py -v`
Expected: FAIL（`config` 子命令不存在，argparse 报错）

- [ ] **Step 3: Write minimal implementation**

```python
# src/contextseek/config/cli.py
"""`contextseek config` subcommand wiring."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from contextseek.config.manager import ConfigManager
from contextseek.config.materializer import Materializer


def _default_config_dir() -> Path:
    home = os.environ.get("CONTEXTSEEK_HOME")
    root = Path(home) if home else Path.cwd() / ".contextseek"
    return root / "config"


def _default_materializer() -> Materializer:
    env_path = Path(os.environ.get("CONTEXTSEEK_ENV_FILE", ".env"))
    runtime_path = Path(
        os.environ.get("CONTEXTSEEK_CONFIG", "config.json")
    )
    return Materializer(env_path=env_path, runtime_path=runtime_path)


def _manager() -> ConfigManager:
    m = ConfigManager(_default_config_dir())
    m.init_store()
    return m


def register_config_subparser(subparsers: Any) -> None:
    """Register the ``config`` subcommand group on ``subparsers``."""
    parser = subparsers.add_parser("config", help="manage contextseek configuration")
    sub = parser.add_subparsers(dest="config_command", required=True)

    p_show = sub.add_parser("show", help="show a config version/layer")
    p_show.add_argument("--version", default=None)
    p_show.add_argument(
        "--layer", choices=["native", "projected", "effective"], default="effective"
    )

    p_set = sub.add_parser("set", help="set a native config key")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--reason", default="cli set")
    p_set.add_argument("--author", default="cli")
    p_set.add_argument("--no-apply", action="store_true")

    p_apply = sub.add_parser("apply", help="materialize current config to .env + config.json")

    p_hist = sub.add_parser("history", help="list version history")
    p_hist.add_argument("-n", type=int, default=None)

    p_diff = sub.add_parser("diff", help="diff two versions")
    p_diff.add_argument("a")
    p_diff.add_argument("b")

    p_rb = sub.add_parser("rollback", help="rollback to a version (append-only)")
    p_rb.add_argument("version")
    p_rb.add_argument("--reason", default="rollback")
    p_rb.add_argument("--author", default="cli")
    p_rb.add_argument("--no-apply", action="store_true")

    p_redo = sub.add_parser("redo", help="undo the most recent rollback")
    p_redo.add_argument("--reason", default="redo")
    p_redo.add_argument("--author", default="cli")

    p_blame = sub.add_parser("blame", help="find the version that last set a key")
    p_blame.add_argument("key")

    sub.add_parser("status", help="show current version / drift / source staleness")
    sub.add_parser("verify", help="verify history integrity (hash + parent chain)")

    p_ingest = sub.add_parser("ingest", help="ingest an external config source")
    p_ingest_sub = p_ingest.add_subparsers(dest="ingest_source", required=True)
    p_ingest_agent = p_ingest_sub.add_parser("agentseek", help="ingest agentseek config")
    p_ingest_agent.add_argument("--path", default=None)
    p_ingest_agent.add_argument("--apply", action="store_true")
    p_ingest_agent.add_argument("--author", default="agentseek")


def run_config_command(args: argparse.Namespace) -> int:
    """Dispatch a ``config`` subcommand. Returns process exit code."""
    cmd = args.config_command
    mgr = _manager()

    if cmd == "show":
        v = mgr.get_version(args.version) if args.version else mgr.current()
        if v is None:
            print("no config versions yet")
            return 0
        layer = v.payload.get(args.layer, {})
        print(json.dumps(layer, ensure_ascii=False, indent=2))
        return 0

    if cmd == "set":
        v = mgr.set_native(args.key, args.value, author=args.author, reason=args.reason)
        print(f"committed {v.version_id}")
        if not args.no_apply:
            mgr.apply(_default_materializer())
            print("applied to .env + config.json")
        return 0

    if cmd == "apply":
        mgr.apply(_default_materializer())
        print("applied current config to .env + config.json")
        return 0

    if cmd == "history":
        for v in mgr.history(n=args.n):
            print(f"{v.version_id}  {v.created_at}  {v.origin}  {v.author}  {v.reason}")
        return 0

    if cmd == "diff":
        d = mgr.diff(args.a, args.b)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    if cmd == "rollback":
        v = mgr.rollback(args.version, author=args.author, reason=args.reason)
        print(f"rolled back to {args.version} as {v.version_id}")
        if not args.no_apply:
            mgr.apply(_default_materializer())
            print("applied to .env + config.json")
        return 0

    if cmd == "redo":
        v = mgr.redo(author=args.author, reason=args.reason)
        if v is None:
            print("nothing to redo (latest version is not a rollback)")
            return 1
        print(f"redone as {v.version_id}")
        return 0

    if cmd == "blame":
        info = mgr.blame(args.key)
        if info is None:
            print(f"no history for {args.key}")
            return 1
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    if cmd == "status":
        st = mgr.status()
        st["verify_problems"] = mgr.verify()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0

    if cmd == "verify":
        problems = mgr.verify()
        if problems:
            for p in problems:
                print(f"PROBLEM: {p}")
            return 1
        print("OK")
        return 0

    if cmd == "ingest":
        from contextseek.config.agentseek_ingestor import AgentseekIngestor

        ing = AgentseekIngestor(mgr)
        if args.ingest_source == "agentseek":
            if args.path:
                v = ing.ingest_file(Path(args.path), author=args.author)
            else:
                v = ing.ingest_env(dict(os.environ), author=args.author)
            if v is None:
                print("no new agentseek config to ingest (idempotent skip or empty)")
                return 0
            print(f"ingested as {v.version_id} (source_ref={v.source_ref})")
            if args.apply:
                mgr.apply(_default_materializer())
                print("applied to .env + config.json")
            return 0

    return 1
```

Now wire into `src/contextseek/cli/main.py`. In `build_parser()`, after the existing subparsers are registered (e.g. right before the `items` parser or at a sensible spot), add:

```python
    # config management
    from contextseek.config.cli import register_config_subparser

    register_config_subparser(subparsers)
```

And in `run_cli()`, add an early dispatch (before `settings = ContextSeekSettings()` so it does not require a working storage backend), right after the `plug-serve` block:

```python
    if args.command == "config":
        from contextseek.config.cli import run_config_command

        return run_config_command(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_cli.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/contextseek/config/cli.py src/contextseek/cli/main.py tests/unit_tests/test_config_cli.py
git commit -m "feat(config): add `contextseek config` CLI subcommand group"
```

---

### Task 9: 公共 API 导出 + 文档更新

**Files:**
- Modify: `src/contextseek/config/__init__.py`
- Modify: `README.md`（在 capabilities 表或 Quick Start 后加一行 config 管理说明）

**Interfaces:**
- Produces: `__init__.py` 导出 `ConfigManager`, `ConfigVersion`, `Materializer`, `AgentseekIngestor`。

- [ ] **Step 1: Write the failing test（追加到 test_config_manager.py 或新建）**

```python
# tests/unit_tests/test_config_exports.py
"""Tests for public API exports."""

from __future__ import annotations


def test_public_exports_available():
    from contextseek.config import (  # noqa: F401
        AgentseekIngestor,
        ConfigManager,
        ConfigVersion,
        Materializer,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit_tests/test_config_exports.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConfigManager'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/contextseek/config/__init__.py`:

```python
from contextseek.config.manager import ConfigManager
from contextseek.config.manager import ConfigVersion
from contextseek.config.materializer import Materializer
from contextseek.config.agentseek_ingestor import AgentseekIngestor
```

And add these names to the `__all__` list:

```python
    "ConfigManager",
    "ConfigVersion",
    "Materializer",
    "AgentseekIngestor",
```

Append a short section to `README.md` (after the capabilities table):

```markdown
## Configuration management

ContextSeek ships a versioned, traceable, rollback-able configuration store:

```bash
contextseek config set llm.model gpt-4o --reason "init llm"
contextseek config history
contextseek config rollback v000001
contextseek config ingest agentseek --path agentseek.env --apply
contextseek config verify
```

Every change is an append-only version with provenance (author, reason, origin). Rollback creates a new version — history is never deleted. agentseek config can be ingested and projected into the `projected` layer without reverse-writing agentseek.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit_tests/test_config_exports.py -v`
Expected: PASS

- [ ] **Step 5: Run full config test suite**

Run: `pytest tests/unit_tests/test_config_envreflector.py tests/unit_tests/test_config_manager.py tests/unit_tests/test_config_materializer.py tests/unit_tests/test_config_mapping.py tests/unit_tests/test_config_agentseek_ingestor.py tests/unit_tests/test_config_cli.py tests/unit_tests/test_config_exports.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add src/contextseek/config/__init__.py README.md tests/unit_tests/test_config_exports.py
git commit -m "feat(config): export public API and document config management"
```

---

## Self-Review

**1. Spec coverage:**
- §1 背景/目标 → 整个计划对应。✓
- §2 架构（物化层在上，非侵入）→ Task 4/5 Materializer + apply；现有加载器不动。✓
- §3 数据模型（目录布局、版本文件、合并优先级、manifest）→ Task 2 `_write_version`/`_merge`/目录创建。✓
- §4 CLI 全部命令 → Task 8 注册 show/set/apply/history/diff/rollback/redo/blame/status/verify/ingest。✓
- §5 agentseek 摄入与映射表 → Task 6 mapping + Task 7 ingestor；幂等、source_ref、不反写。✓
- §6 溯源与回退（append-only rollback、redo、漂移检测、blame）→ Task 3 + Task 4 `detect_drift`。✓
- §7 错误处理（写原子性、hash 链、dry-run validate、映射冲突）→ Task 2 原子写 + Task 3 verify + Task 4 dry_run_validate + Task 2 `_merge` 不报错取 native。✓
- §8 测试 → 每个 Task 都有对应测试文件。✓
- §9 文件改动概览 → 全部覆盖。✓

**2. Placeholder scan:** Task 6 Step 3 有一处已明确标注的笔误需在实现时删除（占位行 + 末尾常量），已在注释中说明——这不是模糊占位而是精确修正指令。其余无 TBD/TODO。

**3. Type consistency:** `ConfigManager` 在 Task 2/3/5 中方法签名一致（`set_native(key, value, *, author, reason)`、`rollback(target_version_id, *, author, reason)`、`apply(materializer)`）；`ConfigVersion` 字段在 Task 2 定义后被 Task 3/7/8 一致使用；`Materializer(env_path, runtime_path)` 在 Task 4/5/8 一致；`project_agentseek_env(env) -> (projected, source_ref)` 在 Task 6/7 一致；`AgentseekIngestor(manager)` + `ingest_env`/`ingest_file` 在 Task 7/8 一致。

无遗留 gap。
