from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    LOCAL_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def iso_from_epoch(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def local_time(value: str | None) -> str:
    if not value:
        return "未知时间"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


@dataclass(frozen=True)
class AppPaths:
    root: Path
    vault: Path
    raw: Path
    database: Path
    exports: Path
    config_file: Path
    token_file: Path
    logs: Path


def app_paths(root: Path | str | None = None) -> AppPaths:
    configured = root or os.getenv("AI_CONTEXT_HOME") or PROJECT_ROOT
    base = Path(configured).expanduser().resolve()
    vault = base / "local-vault"
    return AppPaths(
        root=base,
        vault=vault,
        raw=vault / "raw",
        database=vault / "hub.sqlite",
        exports=base / "exports",
        config_file=vault / "config.json",
        token_file=vault / "token",
        logs=vault / "logs",
    )


def ensure_paths(paths: AppPaths) -> None:
    for directory in (paths.root, paths.vault, paths.raw, paths.exports, paths.logs):
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.config_file.exists():
        default = {
            "host": os.getenv("AI_CONTEXT_HOST", "127.0.0.1"),
            "port": int(os.getenv("AI_CONTEXT_PORT", "8765")),
            "codex_home": str(codex_home()),
            "dsh_home": str(Path.home() / ".dsh"),
            "github_enabled": True,
            "github_repo": "",
            "accept_redactions": False,
            "transcript_tool_call_limit": 50000,
            "transcript_tool_result_limit": 100000,
        }
        paths.config_file.write_text(
            json.dumps(default, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not paths.token_file.exists():
        paths.token_file.write_text(secrets.token_urlsafe(36), encoding="utf-8")


def load_config(paths: AppPaths | None = None) -> dict[str, Any]:
    paths = paths or app_paths()
    ensure_paths(paths)
    return json.loads(paths.config_file.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any], paths: AppPaths | None = None) -> None:
    paths = paths or app_paths()
    ensure_paths(paths)
    paths.config_file.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def local_token(paths: AppPaths | None = None) -> str:
    paths = paths or app_paths()
    ensure_paths(paths)
    return paths.token_file.read_text(encoding="utf-8").strip()


def write_extension_config(paths: AppPaths | None = None) -> Path:
    paths = paths or app_paths()
    ensure_paths(paths)
    config = load_config(paths)
    target = paths.root / "extension" / "config.local.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    server_url = f"http://{config.get('host', '127.0.0.1')}:{config.get('port', 8765)}"
    content = (
        "globalThis.AI_CONTEXT_LOCAL_CONFIG = Object.freeze({\n"
        f"  serverUrl: {json.dumps(server_url)},\n"
        f"  token: {json.dumps(local_token(paths))},\n"
        "});\n"
    )
    target.write_text(content, encoding="utf-8")
    return target


def codex_home() -> Path:
    configured = os.getenv("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".codex"
