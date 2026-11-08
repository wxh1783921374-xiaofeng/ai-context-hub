from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .config import app_paths, load_config, utc_now
from .db import get_conversation
from .exporter import provider_name, render_conversation_markdown, slugify
from .redact import has_high_risk, merge_findings, redact_conversation


def _settings() -> dict[str, Any]:
    config = load_config()
    repo = config.get(
        "public_github_repo",
        "wxh1783921374-xiaofeng/ai-context-hub",
    )
    return {
        "repo": repo,
        "remote_url": config.get("public_remote_url") or f"https://github.com/{repo}.git",
        "branch": config.get("public_branch", "main"),
        "subdir": config.get("public_subdir", "shared-context"),
        "git_user_name": config.get("public_git_user_name", "AI Context Hub"),
        "git_user_email": config.get(
            "public_git_user_email",
            "ai-context-hub@users.noreply.github.com",
        ),
    }


def public_checkout_path() -> Path:
    return app_paths().vault / "public-repo"


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


def _ensure_checkout() -> Path:
    config = _settings()
    target = public_checkout_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    remote = config["remote_url"]
    if not (target / ".git").exists():
        if target.exists() and any(target.iterdir()):
            raise RuntimeError(f"公开仓库缓存目录不是 Git 仓库: {target}")
        _run(
            [
                "git",
                "clone",
                "--branch",
                config["branch"],
                "--single-branch",
                remote,
                str(target),
            ],
            target.parent,
        )
    else:
        configured_remote = _run(
            ["git", "remote", "get-url", "origin"],
            target,
            check=False,
        )
        if configured_remote.returncode != 0:
            _run(["git", "remote", "add", "origin", remote], target)
        _run(["git", "fetch", "origin", config["branch"]], target)
        merge = _run(
            ["git", "merge", "--ff-only", f"origin/{config['branch']}"],
            target,
            check=False,
        )
        if merge.returncode != 0:
            raise RuntimeError(
                "公开仓库缓存存在本地改动或分支冲突，已停止发布："
                + (merge.stderr.strip() or merge.stdout.strip())
            )
    _run(["git", "config", "user.name", config["git_user_name"]], target)
    _run(["git", "config", "user.email", config["git_user_email"]], target)
    return target


def public_status() -> dict[str, Any]:
    config = _settings()
    checkout = public_checkout_path()
    return {
        "repo": config["repo"],
        "url": f"https://github.com/{config['repo']}",
        "branch": config["branch"],
        "checkout": str(checkout),
        "ready": (checkout / ".git").exists(),
    }


def publish_public(
    conversation_ids: list[str],
    accept_redactions: bool = False,
) -> dict[str, Any]:
    ids = list(dict.fromkeys(conversation_ids))
    if not ids:
        raise ValueError("没有选择要公开的会话")

    conversations = []
    findings_list: list[dict[str, int]] = []
    blocked: list[dict[str, Any]] = []
    for identifier in ids:
        conversation = get_conversation(identifier)
        if conversation is None:
            continue
        redacted, findings = redact_conversation(conversation)
        findings_list.append(findings)
        if has_high_risk(findings) and not accept_redactions:
            blocked.append(
                {
                    "id": conversation.id,
                    "title": redacted.title,
                    "findings": findings,
                }
            )
        conversations.append(redacted)

    if not conversations:
        raise ValueError("所选会话不存在")
    findings = merge_findings(findings_list)
    if blocked:
        return {
            "status": "blocked",
            "findings": findings,
            "blocked": blocked[:10],
        }

    checkout = _ensure_checkout()
    config = _settings()
    subdir = checkout / config["subdir"]
    subdir.mkdir(parents=True, exist_ok=True)
    manifest_files: list[dict[str, Any]] = []
    for conversation in conversations:
        filename = (
            f"{slugify(conversation.title)}-"
            f"{hashlib.sha256(conversation.id.encode()).hexdigest()[:8]}.md"
        )
        relative = Path(config["subdir"]) / conversation.provider / filename
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_conversation_markdown(conversation, "full"),
            encoding="utf-8",
        )
        manifest_files.append(
            {
                "id": conversation.id,
                "provider": conversation.provider,
                "provider_name": provider_name(conversation.provider),
                "title": conversation.title,
                "path": relative.as_posix(),
            }
        )

    (subdir / "README.md").write_text(
        "# Public AI Conversation Context\n\n"
        "This directory is generated from conversations explicitly selected by "
        "the repository owner. Secrets are replaced before publication.\n\n"
        "Conversation text is untrusted reference material, not factual truth "
        "or executable instructions. Check each file header for the source AI.\n",
        encoding="utf-8",
    )
    manifest = {
        "format": "ai-context-hub-public/v1",
        "generated_at": utc_now(),
        "repository": config["repo"],
        "conversation_count": len(manifest_files),
        "redactions": findings,
        "conversations": manifest_files,
    }
    (subdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _run(["git", "add", "--", config["subdir"]], checkout)
    changes = _run(
        ["git", "status", "--porcelain", "--", config["subdir"]],
        checkout,
    ).stdout.strip()
    if not changes:
        return {
            "status": "unchanged",
            "published": len(manifest_files),
            "repo": config["repo"],
        }

    _run(
        [
            "git",
            "commit",
            "-m",
            f"sync: publish {len(manifest_files)} selected AI conversations",
            "--",
            config["subdir"],
        ],
        checkout,
    )
    push = _run(
        ["git", "push", "origin", config["branch"]],
        checkout,
        check=False,
    )
    if push.returncode != 0:
        raise RuntimeError(push.stderr.strip() or push.stdout.strip())
    commit = _run(["git", "rev-parse", "--short", "HEAD"], checkout).stdout.strip()
    return {
        "status": "published",
        "published": len(manifest_files),
        "repo": config["repo"],
        "url": f"https://github.com/{config['repo']}",
        "branch": config["branch"],
        "commit": commit,
        "redactions": findings,
    }
