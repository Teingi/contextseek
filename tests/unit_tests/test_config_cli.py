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
