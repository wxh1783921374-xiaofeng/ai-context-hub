from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .config import app_paths, local_time, utc_now
from .db import all_conversations_for_export
from .models import Conversation, Message
from .redact import has_high_risk, merge_findings, redact_conversation


PROVIDER_NAMES = {
    "codex": "Codex",
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
    "deepseek_harness": "DeepSeek Harness",
    "doubao": "豆包",
    "generic": "通用导入",
}


def provider_name(provider: str) -> str:
    return PROVIDER_NAMES.get(provider, provider)


def slugify(value: str, limit: int = 50) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-. ")
    return (cleaned[:limit].strip("-. ") or "conversation")


def render_message(message: Message, mode: str = "full") -> str:
    if message.role == "user":
        label = "用户"
    elif message.role == "assistant":
        label = "助手"
    elif message.role == "tool":
        label = "工具"
    else:
        label = message.role
    timestamp = f" · {local_time(message.timestamp)}" if message.timestamp else ""
    text = message.text.strip()
    if mode == "working" and message.kind == "tool_call":
        text = text[:800]
    elif mode == "working" and message.kind == "tool_result":
        text = text[:2000]
    return f"### {label}{timestamp}\n\n{text}\n"


def render_conversation_markdown(conversation: Conversation, mode: str = "full") -> str:
    lines = [
        f"## {conversation.title}",
        "",
        f"- 来源：{provider_name(conversation.provider)}",
        f"- 模型：{conversation.model or '页面未标注'}",
        f"- 时间：{local_time(conversation.updated_at or conversation.created_at)}",
        f"- 原始会话：{conversation.source_ref or conversation.id}",
        "",
    ]
    for message in conversation.messages:
        if mode != "full" and message.role == "system":
            continue
        lines.append(render_message(message, mode))
    return "\n".join(lines).rstrip() + "\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    last_error: PermissionError | None = None
    for delay in (0, 0.25, 0.75, 1.5):
        if delay:
            time.sleep(delay)
        try:
            temporary.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
    raise last_error or PermissionError(f"无法写入 {path}")


def export_all(
    paths=None,
    accept_redactions: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    paths = paths or app_paths()
    counts: Counter[str] = Counter()
    all_findings: list[dict[str, int]] = []
    blocked_samples: list[dict[str, Any]] = []
    targets: list[tuple[str, Path]] = []

    for conversation in all_conversations_for_export():
        redacted, findings = redact_conversation(conversation)
        all_findings.append(findings)
        counts[conversation.provider] += 1
        if has_high_risk(findings) and not accept_redactions:
            blocked_samples.append(
                {
                    "id": conversation.id,
                    "title": redacted.title,
                    "findings": findings,
                    "preview": render_conversation_markdown(redacted, "brief")[:1200],
                }
            )
            continue
        filename = (
            f"{slugify(conversation.title)}-"
            f"{hashlib.sha256(conversation.id.encode()).hexdigest()[:8]}.md"
        )
        target = paths.exports / "conversations" / conversation.provider / filename
        targets.append((conversation.id, target))

    findings = merge_findings(all_findings)
    blocked = bool(blocked_samples)
    if blocked:
        return {
            "status": "blocked",
            "conversations": sum(counts.values()),
            "providers": dict(counts),
            "findings": findings,
            "redaction_samples": blocked_samples[:3],
            "written": 0,
        }

    if dry_run:
        return {
            "status": "ok",
            "dry_run": True,
            "conversations": len(targets),
            "providers": dict(counts),
            "findings": findings,
            "would_write": len(targets),
        }

    written_paths: list[str] = []
    target_map = dict(targets)
    for conversation in all_conversations_for_export():
        target = target_map.get(conversation.id)
        if target is None:
            continue
        redacted, _ = redact_conversation(conversation)
        content = render_conversation_markdown(redacted, "full")
        del conversation
        _write_atomic(target, content)
        written_paths.append(str(target.relative_to(paths.root)))

    manifest = {
        "format": "ai-context-hub/v1",
        "generated_at": utc_now(),
        "conversation_count": len(written_paths),
        "providers": dict(counts),
        "redactions": findings,
        "files": sorted(written_paths),
    }
    _write_atomic(
        paths.exports / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "status": "ok",
        "conversations": len(written_paths),
        "providers": dict(counts),
        "findings": findings,
        "written": len(written_paths),
    }
