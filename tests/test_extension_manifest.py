from __future__ import annotations

import json
from pathlib import Path


def test_extension_manifest_is_mv3_and_scoped() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "extension" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    hosts = set(manifest["host_permissions"])
    assert "https://chat.deepseek.com/*" in hosts
    assert "https://www.doubao.com/*" in hosts
    assert "https://gemini.google.com/*" in hosts
    assert "https://chatgpt.com/*" in hosts
    assert "cookies" not in manifest["permissions"]
    for size in ("16", "32", "48", "128"):
        assert (root / "extension" / manifest["icons"][size]).exists()
