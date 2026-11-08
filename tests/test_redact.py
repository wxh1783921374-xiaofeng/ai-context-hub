from __future__ import annotations

from ai_context_hub.redact import has_high_risk, redact_text


def test_redacts_common_secret_shapes() -> None:
    source = "\n".join(
        [
            "Authorization: Bearer abcdefghijklmnop",
            "OPENAI_TOKEN=abcdefghijklmnop",
            "token=abcdefghijklmnop",
            r"cwd=C:\Users\someone\project\file.py",
            "mail me at user@example.com or 13800138000",
        ]
    )

    result = redact_text(source)

    assert "abcdefghijklmnop" not in result.text
    assert "user@example.com" not in result.text
    assert "13800138000" not in result.text
    assert r"C:\Users\someone" not in result.text
    assert has_high_risk(result.findings)


def test_redacts_private_key_and_github_token() -> None:
    private_key = (
        "-----BEGIN " + "PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
        "-----END " + "PRIVATE KEY-----"
    )
    github_token = "ghp_" + ("a" * 32)
    source = f"{private_key}\n{github_token}"

    result = redact_text(source)

    assert "BEGIN PRIVATE KEY" not in result.text
    assert "ghp_" not in result.text
    assert result.findings["private_key"] == 1
    assert result.findings["github_token"] == 1


def test_redaction_placeholders_are_idempotent() -> None:
    first = redact_text("token=abcdefghijklmnop\nAPI_KEY=abcdefghijklmnop\n\0")
    second = redact_text(first.text)

    assert first.text == second.text
    assert first.findings == {"secret_assignment": 2}
    assert second.findings == {}


def test_redacts_token_embedded_in_source_escape() -> None:
    token = "ghp_" + ("a" * 32)
    result = redact_text(f'source = "line\\n{token}"')

    assert token not in result.text
    assert result.findings["github_token"] == 1


def test_redacted_headers_are_idempotent() -> None:
    first = redact_text("Authorization: Bearer abcdefghijklmnop\nCookie: session=secretvalue")
    second = redact_text(first.text)

    assert first.findings == {"authorization": 1, "cookie": 1}
    assert second.findings == {}
