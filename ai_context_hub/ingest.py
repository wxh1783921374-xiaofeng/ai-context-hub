from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .config import app_paths, load_config, utc_now
from .db import (
    conversation_status,
    get_conversation,
    get_meta,
    init_db,
    set_meta,
    upsert_conversation,
)
from .models import BrowserCapture, Conversation, Message
from .parsers.chatgpt import import_chatgpt_export
from .parsers.codex import (
    discover_session_files,
    load_thread_names,
    parse_session_file,
)
from .parsers.codex_db import discover_thread_conversations
from .parsers.deepseek_harness import (
    discover_conversations as discover_deepseek_harness_conversations,
)
from .parsers.generic import import_generic


def _apply_conversations(
    conversations: Iterable[Conversation],
    commit: bool,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    for conversation in conversations:
        try:
            status = conversation_status(conversation)
            counts[status] += 1
            if commit and status != "unchanged":
                upsert_conversation(conversation)
        except Exception as exc:  # Keep one malformed source from blocking the batch.
            counts["failed"] += 1
            errors.append({"id": conversation.id, "error": str(exc)})
    return {**dict(counts), "errors": errors}


def ingest_codex(commit: bool = True) -> dict[str, Any]:
    init_db()
    config = load_config()
    codex_root = Path(config.get("codex_home") or app_paths().root).expanduser()
    database_conversations = list(discover_thread_conversations(codex_root))
    if database_conversations:
        return _apply_conversations(database_conversations, commit)
    tool_call_limit = int(config.get("transcript_tool_call_limit", 50000))
    tool_result_limit = int(config.get("transcript_tool_result_limit", 100000))
    title_map = load_thread_names(codex_root)
    cache_value = get_meta("codex_file_cache", "{}") or "{}"
    try:
        file_cache = json.loads(cache_value)
    except json.JSONDecodeError:
        file_cache = {}
    updated_cache = dict(file_cache)
    counts: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    seen_conversations: dict[str, Conversation] = {}

    for path in discover_session_files(codex_root):
        path_key = str(path.resolve())
        try:
            stat = path.stat()
        except OSError as exc:
            counts["failed"] += 1
            errors.append({"id": path_key, "error": str(exc)})
            continue
        signature = f"{stat.st_mtime_ns}:{stat.st_size}"
        cached_entry = file_cache.get(path_key) or {}
        conversation: Conversation | None = None
        if (
            cached_entry.get("signature") == signature
            and cached_entry.get("conversation_id")
        ):
            conversation = get_conversation(cached_entry["conversation_id"])
            if conversation:
                session_id = conversation.id.removeprefix("codex:")
                desired_title = title_map.get(session_id)
                if desired_title and conversation.title != desired_title:
                    conversation.title = desired_title
        if conversation is None:
            conversation = parse_session_file(
                path,
                title_map,
                tool_call_limit=tool_call_limit,
                tool_result_limit=tool_result_limit,
            )
        if conversation is None:
            continue
        previous = seen_conversations.get(conversation.id)
        if previous is None or (conversation.updated_at or "") >= (previous.updated_at or ""):
            seen_conversations[conversation.id] = conversation
        updated_cache[path_key] = {
            "signature": signature,
            "conversation_id": conversation.id,
        }

    for conversation in seen_conversations.values():
        try:
            status = conversation_status(conversation)
            counts[status] += 1
            if commit and status != "unchanged":
                upsert_conversation(conversation)
        except Exception as exc:
            counts["failed"] += 1
            errors.append({"id": conversation.id, "error": str(exc)})
    if commit:
        set_meta(
            "codex_file_cache",
            json.dumps(updated_cache, ensure_ascii=False, sort_keys=True),
        )
    return {**dict(counts), "errors": errors}


def ingest_deepseek_harness(commit: bool = True) -> dict[str, Any]:
    init_db()
    config = load_config()
    dsh_root = Path(config.get("dsh_home") or (Path.home() / ".dsh")).expanduser()
    return _apply_conversations(
        discover_deepseek_harness_conversations(dsh_root),
        commit,
    )


def ingest_chatgpt(path: Path, commit: bool = True) -> dict[str, Any]:
    init_db()
    paths = app_paths()
    raw_dir = paths.raw / "chatgpt"
    return _apply_conversations(import_chatgpt_export(path, raw_dir), commit)


def ingest_generic(path: Path, commit: bool = True) -> dict[str, Any]:
    init_db()
    return _apply_conversations(import_generic(path), commit)


def _message_key(message: Message) -> tuple[str, str]:
    return (message.role, " ".join(message.text.split()))


def merge_snapshots(
    existing: list[Message],
    incoming: list[Message],
    complete: bool,
) -> list[Message]:
    incoming = [message.model_copy(deep=True) for message in incoming]
    if complete or not existing:
        return incoming

    incoming_keys = [_message_key(item) for item in incoming]
    existing_keys = [_message_key(item) for item in existing]
    if len(incoming_keys) >= len(existing_keys):
        return incoming

    if incoming_keys == existing_keys[: len(incoming_keys)]:
        return [
            *(message.model_copy(deep=True) for message in incoming),
            *(message.model_copy(deep=True) for message in existing[len(incoming) :]),
        ]

    merged = [message.model_copy(deep=True) for message in existing]
    present = set(existing_keys)
    for message, key in zip(incoming, incoming_keys, strict=False):
        if key not in present:
            merged.append(message.model_copy(deep=True))
            present.add(key)
    return merged


def ingest_browser_capture(payload: BrowserCapture) -> dict[str, Any]:
    init_db()
    paths = app_paths()
    provider = payload.provider
    identifier = payload.conversation_id.strip()
    if not identifier:
        raise ValueError("conversation_id 不能为空")
    conversation_id = f"{provider}:{identifier}"
    received = payload.model_dump(mode="json")
    canonical = json.dumps(received, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    raw_dir = paths.raw / "browser" / provider
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{digest[:16]}.json"
    if not raw_path.exists():
        raw_path.write_text(
            json.dumps(received, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    existing = get_conversation(conversation_id)
    messages = merge_snapshots(
        existing.messages if existing else [],
        payload.messages,
        payload.complete,
    )
    conversation = Conversation(
        id=conversation_id,
        provider=provider,
        model=payload.model,
        title=payload.title or (existing.title if existing else "未命名会话"),
        created_at=existing.created_at if existing else payload.captured_at,
        updated_at=payload.captured_at or utc_now(),
        source_ref=payload.url,
        source_type="browser_snapshot",
        messages=messages,
    ).ordered()
    status = upsert_conversation(conversation)
    return {
        "status": status,
        "conversation_id": conversation.id,
        "message_count": len(conversation.messages),
        "raw_path": str(raw_path),
    }
