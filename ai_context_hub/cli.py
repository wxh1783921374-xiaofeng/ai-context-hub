from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import (
    app_paths,
    ensure_paths,
    load_config,
    local_token,
    utc_now,
    write_extension_config,
)
from .db import (
    count_conversations,
    init_db,
    list_conversations,
    recent_sync_runs,
    record_sync_run,
    search_conversations,
)
from .exporter import export_all
from .github_sync import ensure_private_repository, git_status, publish_exports
from .ingest import ingest_chatgpt, ingest_codex, ingest_deepseek_harness, ingest_generic
from .packs import build_pack


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-context",
        description="Local AI conversation hub.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize local storage.")
    subparsers.add_parser("token", help="Print the local extension pairing token.")
    subparsers.add_parser(
        "pair-extension",
        help="Write the ignored local extension config with the current token.",
    )
    subparsers.add_parser("status", help="Show index and Git status.")

    serve = subparsers.add_parser("serve", help="Run the local dashboard and API.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--no-open", action="store_true")

    sync = subparsers.add_parser("sync", help="Import Codex and publish sanitized exports.")
    sync.add_argument("--codex", action="store_true")
    sync.add_argument("--deepseek-harness", action="store_true")
    sync.add_argument("--chatgpt", type=Path)
    sync.add_argument("--browser", action="store_true")
    sync.add_argument("--publish", action="store_true")
    sync.add_argument("--accept-redactions", action="store_true")

    search = subparsers.add_parser("search", help="Search conversations.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=30)

    pack = subparsers.add_parser("pack", help="Build an AI context pack.")
    group = pack.add_mutually_exclusive_group(required=True)
    group.add_argument("--threads", nargs="+")
    group.add_argument("--query")
    pack.add_argument("--budget", type=int, default=32000)
    pack.add_argument("--mode", choices=["brief", "working", "full"], default="working")
    pack.add_argument("--accept-redactions", action="store_true")

    import_parser = subparsers.add_parser("import", help="Import a local file.")
    import_parser.add_argument("path", type=Path)
    import_parser.add_argument(
        "--kind",
        choices=["auto", "chatgpt", "generic"],
        default="auto",
    )

    repo = subparsers.add_parser("ensure-repo", help="Create or connect the private repo.")
    repo.add_argument("--repo", default=None)
    return parser


def command_init() -> None:
    paths = app_paths()
    ensure_paths(paths)
    init_db()
    _print(
        {
            "status": "initialized",
            "root": str(paths.root),
            "database": str(paths.database),
            "token_file": str(paths.token_file),
        }
    )


def command_status() -> None:
    init_db()
    _print(
        {
            "root": str(app_paths().root),
            "counts": count_conversations(),
            "git": git_status(),
            "recent_syncs": recent_sync_runs(5),
        }
    )


def command_sync(args: argparse.Namespace) -> None:
    init_db()
    started = utc_now()
    summary: dict[str, Any] = {}
    if args.codex or not args.chatgpt:
        summary["codex"] = ingest_codex()
    if args.deepseek_harness:
        summary["deepseek_harness"] = ingest_deepseek_harness()
    if args.chatgpt:
        summary["chatgpt"] = ingest_chatgpt(args.chatgpt)
    if args.browser:
        summary["browser"] = {"status": "already_received", "source": "browser_extension"}
    summary["export"] = export_all(accept_redactions=args.accept_redactions)
    if summary["export"].get("status") == "blocked":
        record_sync_run(started, "blocked", summary)
        _print(summary)
        raise SystemExit(2)
    if args.publish:
        summary["publish"] = publish_exports()
    record_sync_run(started, "ok", summary)
    _print(summary)


def command_import(args: argparse.Namespace) -> None:
    path = args.path.expanduser()
    if not path.exists():
        raise SystemExit(f"文件不存在: {path}")
    kind = args.kind
    if kind == "auto":
        kind = "chatgpt" if path.suffix.lower() in {".zip"} else "generic"
    summary = ingest_chatgpt(path) if kind == "chatgpt" else ingest_generic(path)
    _print({"kind": kind, **summary})


def command_serve(args: argparse.Namespace) -> None:
    import uvicorn

    init_db()
    config = load_config()
    host = args.host or config.get("host", "127.0.0.1")
    port = args.port or int(config.get("port", 8765))
    if not args.no_open:
        import threading
        import time
        import webbrowser

        def open_browser() -> None:
            time.sleep(1.2)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("ai_context_hub.api:app", host=host, port=port, log_level="info")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        command_init()
    elif args.command == "token":
        init_db()
        print(local_token())
    elif args.command == "pair-extension":
        init_db()
        target = write_extension_config()
        _print({"status": "paired", "config": str(target)})
    elif args.command == "status":
        command_status()
    elif args.command == "serve":
        command_serve(args)
    elif args.command == "sync":
        command_sync(args)
    elif args.command == "search":
        init_db()
        _print(search_conversations(args.query, args.limit))
    elif args.command == "pack":
        _print(
            build_pack(
                conversation_ids=args.threads,
                query=args.query,
                budget=args.budget,
                mode=args.mode,
                accept_redactions=args.accept_redactions,
            )
        )
    elif args.command == "import":
        command_import(args)
    elif args.command == "ensure-repo":
        config = load_config()
        repo = args.repo or config["github_repo"]
        _print(ensure_private_repository(repo))
    else:
        raise SystemExit(f"未知命令: {args.command}")


if __name__ == "__main__":
    main(sys.argv[1:])
