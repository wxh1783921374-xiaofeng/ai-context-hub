from __future__ import annotations

import subprocess
from pathlib import Path

from ai_context_hub.github_sync import publish_exports


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def test_publish_exports_to_temporary_bare_remote(hub_home) -> None:
    root = Path(hub_home)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("test\n", encoding="utf-8")
    (root / ".gitignore").write_text("local-vault/\n", encoding="utf-8")
    _git(root, "add", "README.md", ".gitignore")
    _git(root, "commit", "-m", "initial")

    remote = root.parent / "origin.git"
    _git(root.parent, "init", "--bare", str(remote))
    _git(root, "remote", "add", "origin", str(remote))

    export = root / "exports" / "conversations" / "codex" / "test.md"
    export.parent.mkdir(parents=True)
    export.write_text("# test\n", encoding="utf-8")

    result = publish_exports("test export")

    assert result["status"] == "pushed"
    assert result["branch"] == "main"
    assert _git(remote, "rev-parse", "main")
    assert not (root / "local-vault" / "secret.txt").exists()
