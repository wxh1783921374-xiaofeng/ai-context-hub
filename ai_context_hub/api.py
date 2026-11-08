from __future__ import annotations

import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import app_paths, local_token, utc_now
from .db import (
    count_conversations,
    get_conversation,
    init_db,
    list_conversations,
    recent_sync_runs,
    record_sync_run,
    search_conversations,
)
from .exporter import export_all
from .github_sync import git_status, publish_exports
from .ingest import (
    ingest_browser_capture,
    ingest_chatgpt,
    ingest_codex,
    ingest_deepseek_harness,
    ingest_generic,
)
from .models import BrowserCapture
from .packs import build_pack


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Context Hub",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class SyncRequest(BaseModel):
    include_codex: bool = True
    include_deepseek_harness: bool = True
    publish: bool = False
    accept_redactions: bool = False


class PackRequest(BaseModel):
    conversation_ids: list[str] = Field(default_factory=list)
    query: str | None = None
    budget: int = 32000
    mode: Literal["brief", "working", "full"] = "working"
    accept_redactions: bool = False


class ImportRequest(BaseModel):
    kind: Literal["chatgpt", "generic"]
    path: str


def require_capture_token(
    x_ai_context_token: str | None = Header(default=None),
) -> None:
    expected = local_token()
    if not x_ai_context_token or not secrets.compare_digest(
        x_ai_context_token,
        expected,
    ):
        raise HTTPException(status_code=401, detail="本地扩展令牌无效")


@app.get("/api/v1/status")
def status() -> dict[str, Any]:
    config = git_status()
    return {
        "ok": True,
        "counts": count_conversations(),
        "git": config,
        "recent_syncs": recent_sync_runs(5),
        "server_time": utc_now(),
    }


@app.get("/api/v1/conversations")
def conversations(
    q: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    items = search_conversations(q, limit=limit) if q else list_conversations(provider, limit)
    if q and provider:
        items = [item for item in items if item["provider"] == provider]
    return {"items": items, "count": len(items)}


@app.get("/api/v1/conversations/{conversation_id:path}")
def conversation(conversation_id: str) -> dict[str, Any]:
    item = get_conversation(conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return item.model_dump(mode="json")


@app.post("/api/v1/capture")
def capture(
    payload: BrowserCapture,
    _: None = Depends(require_capture_token),
) -> dict[str, Any]:
    try:
        return ingest_browser_capture(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/sync/preview")
def sync_preview(request: SyncRequest) -> dict[str, Any]:
    codex_summary: dict[str, Any] | None = None
    if request.include_codex:
        codex_summary = ingest_codex(commit=False)
    dsh_summary = (
        ingest_deepseek_harness(commit=False)
        if request.include_deepseek_harness
        else None
    )
    export_summary = export_all(
        accept_redactions=request.accept_redactions,
        dry_run=True,
    )
    git = git_status()
    blocked = export_summary.get("status") == "blocked"
    return {
        "status": "blocked" if blocked else "ready",
        "codex": codex_summary,
        "deepseek_harness": dsh_summary,
        "export": export_summary,
        "git": git,
        "requires_redaction_ack": blocked,
    }


@app.post("/api/v1/sync/commit")
def sync_commit(request: SyncRequest) -> dict[str, Any]:
    started = utc_now()
    summary: dict[str, Any] = {}
    try:
        summary["codex"] = ingest_codex(commit=True) if request.include_codex else None
        summary["deepseek_harness"] = (
            ingest_deepseek_harness(commit=True)
            if request.include_deepseek_harness
            else None
        )
        exported = export_all(accept_redactions=request.accept_redactions)
        summary["export"] = exported
        if exported.get("status") == "blocked":
            record_sync_run(started, "blocked", summary)
            return summary
        if request.publish:
            summary["publish"] = publish_exports()
        record_sync_run(started, "ok", summary)
        return summary
    except Exception as exc:
        record_sync_run(started, "failed", summary, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/v1/imports")
def import_file(request: ImportRequest) -> dict[str, Any]:
    path = Path(request.path).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail="导入文件不存在")
    try:
        if request.kind == "chatgpt":
            return ingest_chatgpt(path)
        return ingest_generic(path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/packs")
def create_pack(request: PackRequest) -> dict[str, Any]:
    try:
        return build_pack(
            conversation_ids=request.conversation_ids,
            query=request.query,
            budget=request.budget,
            mode=request.mode,
            accept_redactions=request.accept_redactions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/packs/{filename}")
def download_pack(filename: str) -> FileResponse:
    if not re.fullmatch(r"[\w.\-\u4e00-\u9fff]+", filename):
        raise HTTPException(status_code=400, detail="非法文件名")
    path = app_paths().exports / "packs" / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name, media_type="text/markdown")


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
