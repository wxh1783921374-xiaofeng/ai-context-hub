from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MessageRole = Literal["user", "assistant", "tool", "system"]


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")

    seq: int = 0
    role: MessageRole
    timestamp: str | None = None
    kind: str = "message"
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    provider: str
    model: str | None = None
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    source_ref: str | None = None
    source_type: str
    messages: list[Message] = Field(default_factory=list)

    def ordered(self) -> "Conversation":
        self.messages.sort(
            key=lambda item: (
                item.timestamp or "",
                item.seq,
            )
        )
        for index, message in enumerate(self.messages):
            message.seq = index
        return self

    def content_hash(self) -> str:
        payload = self.model_dump(exclude={"messages": True})
        payload["messages"] = [
            {
                "role": message.role,
                "kind": message.kind,
                "text": message.text,
                "timestamp": message.timestamp,
                "metadata": message.metadata,
            }
            for message in self.messages
        ]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class BrowserCapture(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: Literal["deepseek", "doubao", "gemini", "chatgpt"]
    conversation_id: str
    title: str
    url: str
    model: str | None = None
    captured_at: str | None = None
    messages: list[Message]
    snapshot_hash: str | None = None
    complete: bool = False
