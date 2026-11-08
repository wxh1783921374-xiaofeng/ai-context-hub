from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import app_paths, ensure_paths, utc_now
from .models import Conversation, Message


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT,
    title TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    source_ref TEXT,
    source_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_provider
ON conversations(provider);

CREATE INDEX IF NOT EXISTS idx_conversations_updated
ON conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    timestamp TEXT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(conversation_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
ON messages(conversation_id, seq);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    paths = app_paths()
    ensure_paths(paths)
    conn = sqlite3.connect(db_path or paths.database, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_search
                USING fts5(
                    conversation_id UNINDEXED,
                    title,
                    body,
                    tokenize='trigram'
                )
                """
            )
        except sqlite3.OperationalError:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_search
                USING fts5(
                    conversation_id UNINDEXED,
                    title,
                    body,
                    tokenize='unicode61'
                )
                """
            )
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES ('schema_version', '1')"
        )
        conn.commit()


def conversation_status(conversation: Conversation) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT content_hash FROM conversations WHERE id = ?",
            (conversation.id,),
        ).fetchone()
    if row is None:
        return "new"
    if row["content_hash"] == conversation.content_hash():
        return "unchanged"
    return "updated"


def upsert_conversation(conversation: Conversation) -> str:
    conversation.ordered()
    content_hash = conversation.content_hash()
    status = conversation_status(conversation)
    if status == "unchanged":
        return status

    body = "\n".join(message.text for message in conversation.messages)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO conversations (
                id, provider, model, title, created_at, updated_at,
                source_ref, source_type, content_hash, message_count, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                provider=excluded.provider,
                model=excluded.model,
                title=excluded.title,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                source_ref=excluded.source_ref,
                source_type=excluded.source_type,
                content_hash=excluded.content_hash,
                message_count=excluded.message_count,
                imported_at=excluded.imported_at
            """,
            (
                conversation.id,
                conversation.provider,
                conversation.model,
                conversation.title,
                conversation.created_at,
                conversation.updated_at,
                conversation.source_ref,
                conversation.source_type,
                content_hash,
                len(conversation.messages),
                utc_now(),
            ),
        )
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation.id,),
        )
        conn.executemany(
            """
            INSERT INTO messages (
                conversation_id, seq, role, timestamp, kind, text, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    conversation.id,
                    message.seq,
                    message.role,
                    message.timestamp,
                    message.kind,
                    message.text,
                    json.dumps(message.metadata, ensure_ascii=False, sort_keys=True),
                )
                for message in conversation.messages
            ],
        )
        conn.execute(
            "DELETE FROM conversation_search WHERE conversation_id = ?",
            (conversation.id,),
        )
        conn.execute(
            """
            INSERT INTO conversation_search(conversation_id, title, body)
            VALUES (?, ?, ?)
            """,
            (conversation.id, conversation.title, body),
        )
        conn.commit()
    return status


def get_conversation(conversation_id: str) -> Conversation | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        messages = conn.execute(
            """
            SELECT seq, role, timestamp, kind, text, metadata_json
            FROM messages
            WHERE conversation_id = ?
            ORDER BY seq
            """,
            (conversation_id,),
        ).fetchall()
    return Conversation(
        id=row["id"],
        provider=row["provider"],
        model=row["model"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        source_ref=row["source_ref"],
        source_type=row["source_type"],
        messages=[
            Message(
                seq=item["seq"],
                role=item["role"],
                timestamp=item["timestamp"],
                kind=item["kind"],
                text=item["text"],
                metadata=json.loads(item["metadata_json"]),
            )
            for item in messages
        ],
    )


def list_conversations(
    provider: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, provider, model, title, created_at, updated_at,
               source_ref, source_type, message_count, imported_at
        FROM conversations
    """
    params: list[Any] = []
    if provider:
        sql += " WHERE provider = ?"
        params.append(provider)
    sql += " ORDER BY COALESCE(updated_at, imported_at) DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def count_conversations() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT provider, COUNT(*) AS count FROM conversations GROUP BY provider"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    result = {row["provider"]: row["count"] for row in rows}
    result["all"] = total
    return result


def search_conversations(query: str, limit: int = 100) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return list_conversations(limit=limit)
    with connect() as conn:
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.provider, c.model, c.title, c.created_at,
                       c.updated_at, c.source_ref, c.source_type,
                       c.message_count, c.imported_at,
                       snippet(conversation_search, 2, '', '', '…', 24) AS snippet
                FROM conversation_search
                JOIN conversations c
                  ON c.id = conversation_search.conversation_id
                WHERE conversation_search MATCH ?
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            pattern = f"%{query}%"
            rows = conn.execute(
                """
                SELECT c.id, c.provider, c.model, c.title, c.created_at,
                       c.updated_at, c.source_ref, c.source_type,
                       c.message_count, c.imported_at, c.title AS snippet
                FROM conversations c
                WHERE c.title LIKE ? OR EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.conversation_id = c.id AND m.text LIKE ?
                )
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def all_conversations_for_export() -> Iterable[Conversation]:
    for item in list_conversations(limit=100000):
        conversation = get_conversation(item["id"])
        if conversation:
            yield conversation


def record_sync_run(
    started_at: str,
    status: str,
    summary: dict[str, Any],
    error: str | None = None,
) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO sync_runs(started_at, finished_at, status, summary_json, error)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                started_at,
                utc_now(),
                status,
                json.dumps(summary, ensure_ascii=False),
                error,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def recent_sync_runs(limit: int = 10) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, started_at, finished_at, status, summary_json, error
            FROM sync_runs ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            **dict(row),
            "summary": json.loads(row["summary_json"]),
        }
        for row in rows
    ]


def get_meta(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def delete_all_for_tests() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM conversation_search")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM sync_runs")
        conn.commit()
