"""Unit-test fixtures: isolate env from the project .env so default-settings
tests don't pick up STORAGE_BACKEND=oceanbase / LLM_PROVIDER=langchain.

pydantic-settings merges dict fields across sources (DotEnvSettingsSource +
EnvSettingsSource), so monkeypatching individual env vars doesn't cleanly
suppress dict values (e.g. EMBEDDING_KWARGS) read from the .env file.  The
reliable fix is to patch _read_env_files to return {} so the .env file is
never consulted, then set the scalar defaults that unit tests rely on.
"""

from __future__ import annotations

import pytest

_UNIT_ENV_OVERRIDES = {
    "STORAGE_BACKEND": "memory",
    "LLM_PROVIDER": "none",
    "EMBEDDING_PROVIDER": "none",
}


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable .env file loading and reset scalar defaults for unit tests."""
    monkeypatch.setattr(
        "pydantic_settings.sources.providers.dotenv.DotEnvSettingsSource._read_env_files",
        lambda self: {},
    )
    for key, value in _UNIT_ENV_OVERRIDES.items():
        monkeypatch.setenv(key, value)
