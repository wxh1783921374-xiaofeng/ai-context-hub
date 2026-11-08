from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .config import app_paths


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def git_status(root: Path | None = None) -> dict[str, Any]:
    paths = app_paths()
    root = root or paths.root
    if not (root / ".git").exists():
        return {"initialized": False, "remote": None, "changes": []}
    branch = _run(["git", "branch", "--show-current"], root, check=False).stdout.strip()
    remote = _run(["git", "remote", "get-url", "origin"], root, check=False)
    status = _run(["git", "status", "--porcelain", "--", "exports"], root, check=False)
    changes = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "initialized": True,
        "branch": branch,
        "remote": remote.stdout.strip() if remote.returncode == 0 else None,
        "changes": changes,
        "change_count": len(changes),
    }


def publish_exports(message: str | None = None) -> dict[str, Any]:
    paths = app_paths()
    root = paths.root
    status = git_status(root)
    if not status["initialized"]:
        return {"status": "skipped", "reason": "not_a_git_repository"}
    if not status["remote"]:
        return {"status": "skipped", "reason": "no_origin_remote"}
    if not status["changes"]:
        return {"status": "unchanged", "reason": "no_export_changes"}

    branch = status.get("branch") or "main"
    _run(["git", "add", "--", "exports"], root)
    commit_message = message or "sync: export sanitized AI conversations"
    _run(["git", "commit", "-m", commit_message, "--", "exports"], root)
    push = _run(["git", "push", "-u", "origin", branch], root, check=False)
    if push.returncode != 0:
        return {
            "status": "failed",
            "reason": "push_failed",
            "error": push.stderr.strip() or push.stdout.strip(),
        }
    commit = _run(["git", "rev-parse", "--short", "HEAD"], root, check=False).stdout.strip()
    return {"status": "pushed", "commit": commit, "branch": branch}


def ensure_private_repository(repo: str, root: Path | None = None) -> dict[str, Any]:
    paths = app_paths()
    root = root or paths.root
    auth = _run(["gh", "auth", "status"], root, check=False)
    if auth.returncode != 0:
        raise RuntimeError("GitHub CLI 尚未登录，请先运行 gh auth login")

    existing = _run(["gh", "repo", "view", repo, "--json", "visibility,url"], root, check=False)
    if existing.returncode == 0:
        remote = _run(["git", "remote", "get-url", "origin"], root, check=False)
        if remote.returncode != 0:
            _run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], root)
        return {"status": "existing", "repo": repo}

    result = _run(
        [
            "gh",
            "repo",
            "create",
            repo,
            "--private",
            "--source",
            str(root),
            "--remote",
            "origin",
            "--push",
        ],
        root,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return {"status": "created", "repo": repo}
