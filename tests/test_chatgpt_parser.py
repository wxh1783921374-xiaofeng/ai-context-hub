from __future__ import annotations

import json
import zipfile
from pathlib import Path

from ai_context_hub.parsers.chatgpt import import_chatgpt_export


def test_chatgpt_export_uses_current_branch(tmp_path: Path) -> None:
    data = [
        {
            "id": "conv-1",
            "title": "分支测试",
            "create_time": 1700000000,
            "update_time": 1700000100,
            "current_node": "assistant-current",
            "mapping": {
                "root": {"id": "root", "parent": None, "message": None},
                "system": {
                    "id": "system",
                    "parent": "root",
                    "message": {
                        "author": {"role": "system"},
                        "content": {"content_type": "text", "parts": ["系统提示"]},
                        "create_time": 1700000001,
                    },
                },
                "user": {
                    "id": "user",
                    "parent": "system",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["主分支问题"]},
                        "create_time": 1700000002,
                    },
                },
                "assistant-old": {
                    "id": "assistant-old",
                    "parent": "user",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": ["旧分支回答"]},
                        "create_time": 1700000003,
                    },
                },
                "assistant-current": {
                    "id": "assistant-current",
                    "parent": "user",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": ["当前分支回答"]},
                        "create_time": 1700000004,
                        "metadata": {"model_slug": "gpt-test"},
                    },
                },
            },
        }
    ]
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(data, ensure_ascii=False))

    conversations = list(import_chatgpt_export(zip_path, tmp_path / "raw"))

    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation.id == "chatgpt:conv-1"
    assert conversation.model == "gpt-test"
    assert [item.text for item in conversation.messages] == ["主分支问题", "当前分支回答"]
    assert list((tmp_path / "raw").glob("chatgpt-*.zip"))
