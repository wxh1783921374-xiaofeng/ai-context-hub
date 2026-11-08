from __future__ import annotations

from pathlib import Path

import pytest

from ai_context_hub.config import app_paths, ensure_paths, save_config
from ai_context_hub.db import init_db


@pytest.fixture
def hub_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "hub"
    root.mkdir()
    monkeypatch.setenv("AI_CONTEXT_HOME", str(root))
    paths = app_paths()
    ensure_paths(paths)
    init_db()
    empty_codex = tmp_path / "empty-codex"
    empty_codex.mkdir()
    save_config(
        {
            "host": "127.0.0.1",
            "port": 8765,
            "codex_home": str(empty_codex),
            "github_enabled": True,
            "github_repo": "example/ai-context-hub",
            "accept_redactions": False,
        }
    )
    return root
