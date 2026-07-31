"""Tests for response-style normalization safeguards."""

from src.app.core.response_style import format_telegram_text, normalize_response_text


def test_normalize_response_text_strips_internal_parse_prefix():
    text = (
        "Failed to parse diary agent response: Based on what's captured, "
        "your bottleneck is inconsistent journaling."
    )

    normalized = normalize_response_text(
        text,
        source="telegram",
        specialist="memory",
        message_content="What is my bottleneck?",
    )

    assert "Failed to parse" not in normalized
    assert "inconsistent journaling" in normalized


def test_normalize_response_text_removes_internal_error_line():
    text = (
        "Here's what I found.\n"
        "Failed to parse Memory retrieval response: raw payload...\n"
        "You shipped deployment and fixed webhook retries."
    )

    normalized = normalize_response_text(
        text,
        source="api",
        specialist="memory",
        message_content="What did I do yesterday?",
    )

    assert "Failed to parse" not in normalized
    assert "You shipped deployment" in normalized


def test_normalize_response_text_dedupes_repeated_lines():
    text = "Nothing stored about that yet.\n\nNothing stored about that yet.\n\nTry another angle."

    normalized = normalize_response_text(
        text,
        source="telegram",
        specialist="memory",
        message_content="What happened?",
    )

    assert normalized.count("Nothing stored about that yet.") == 1
    assert "Try another angle." in normalized


def test_normalize_response_text_strips_embedded_parse_wrapper():
    text = (
        "Sources (3): item A, item B. Failed to parse diary agent response: "
        "You shipped deployment and fixed webhook retries."
    )

    normalized = normalize_response_text(
        text,
        source="telegram",
        specialist="memory",
        message_content="What did I do yesterday?",
    )

    assert "Failed to parse" not in normalized
    assert "shipped deployment" in normalized


def test_normalize_response_text_leaves_markdown_for_telegram():
    """normalize_response_text must NOT convert Markdown to HTML for Telegram.

    Channel rendering (Markdown → HTML) happens exclusively in
    render_response_envelope → format_telegram_text. If normalize_response_text
    also converts, the HTML gets double-escaped (&lt;b&gt;) when the render
    stage runs format_telegram_text on already-converted content.
    """
    text = (
        "# Weekly Review: Week of 2026-04-08 to 2026-04-15\n\n**Key Insight:** Something important."
    )

    normalized = normalize_response_text(
        text,
        source="telegram",
        specialist="review",
        message_content="weekly review",
    )

    # Markdown must survive normalize — it should NOT already be HTML
    assert "<b>" not in normalized, "normalize_response_text must not pre-convert Markdown to HTML"
    assert "&lt;" not in normalized, "No HTML entities should appear at this stage"
    assert "# Weekly Review:" in normalized or "Weekly Review:" in normalized

    # But when format_telegram_text is applied once (as render_response_envelope does),
    # we get correct HTML with no double-escaping
    html = format_telegram_text(normalized)
    assert "<b>Weekly Review:" in html
    assert "<b>Key Insight:</b>" in html
    assert "&lt;b&gt;" not in html, (
        "Double-escaped HTML detected — format_telegram_text called twice"
    )
