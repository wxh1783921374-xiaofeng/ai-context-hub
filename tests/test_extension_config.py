from __future__ import annotations

from pathlib import Path

from ai_context_hub.config import local_token, write_extension_config


def test_extension_config_uses_local_token(hub_home) -> None:
    (Path(hub_home) / "extension").mkdir()

    target = write_extension_config()
    content = target.read_text(encoding="utf-8")

    assert target.name == "config.local.js"
    assert "http://127.0.0.1:8765" in content
    assert local_token() in content
