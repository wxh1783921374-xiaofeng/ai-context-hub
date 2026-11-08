from __future__ import annotations

import subprocess
from pathlib import Path

from ai_context_hub.config import load_config, save_config
from ai_context_hub.db import upsert_conversation
from ai_context_hub.models import Conversation, Message
from ai_context_hub.public_sync import publish_public


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def test_publish_selected_conversation_to_public_remote(hub_home, tmp_path: Path) -> None:
    source = tmp_path / "public-source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Test User")
    _git(source, "config", "user.email", "test@example.invalid")
    (source / "README.md").write_text("public\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "initial")

    remote = tmp_path / "public-origin.git"
    _git(tmp_path, "clone", "--bare", str(source), str(remote))
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")

    config = load_config()
    config["public_remote_url"] = remote.as_uri()
    save_config(config)

    upsert_conversation(
        Conversation(
            id="chatgpt:public-one",
            provider="chatgpt",
            title="公开测试",
            model="gpt-test",
            source_type="browser_snapshot",
            messages=[
                Message(role="user", text="公开内容"),
                Message(role="assistant", text="公开回答"),
            ],
        )
    )

    result = publish_public(["chatgpt:public-one"])

    assert result["status"] == "published"
    assert result["published"] == 1
    assert _git(remote, "rev-parse", "main")
