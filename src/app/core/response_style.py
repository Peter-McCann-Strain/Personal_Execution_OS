"""Shared response-style instructions and channel-specific output normalization.

Telegram delivery uses HTML parse mode. The LLM is instructed to emit
**bold** / *italic* / `code` markers; this module converts them to Telegram
HTML tags (<b>, <i>, <code>) and safely escapes any literal HTML characters
so the API never receives malformed markup.
"""

from __future__ import annotations

import re

from src.app.domain.models import ChatResponse, Intent, MessageInput

_RESPONSE_STYLE_PROMPT = """\
Respond like a world-class human personal assistant — sharp, warm, and decisive.

Rules for all user-facing replies:
- Lead with the answer or the confirmed action. Never make the user read past the
  first line to find out what you did.
- For saves, captures, and task additions: ALWAYS open with a confirmation line
  that names exactly what was saved and where. Example: "Saved to Notes: Investigate
  Marp — presentation tooling." Then add any useful context below.
- Use **bold** for section headers and key terms when returning structured data.
- Use bullet lists (- item) for any list of three or more items.
- Use emoji prefixes to signal action type: ✅ saved/done, 📝 notes/capture,
  🔍 memory/search result, ⚠️ warning/issue, ❌ failed, 📅 calendar/schedule.
- Keep conversational replies to three short paragraphs maximum. No walls of text.
- Dates are always human-readable: "Thursday", "in 3 days", "yesterday at 4pm".
  Never output raw ISO timestamps.
- Do not use canned AI phrasing, disclaimers, or filler.
- Do not expose internal labels like classification, routing, confidence,
  or metadata unless the user explicitly asked for them.
"""

# Only strip genuine filler openers — NOT confirmation words.
# "saved", "captured", "logged", "noted" are essential confirmation signals
# and must NEVER be stripped from responses.
_FORBIDDEN_OPENERS = (
    "got it",
    "understood",
    "certainly",
    "of course",
    "sure thing",
    "absolutely",
)

_TRIAGE_KEYWORDS = ("classify", "triage", "category", "label", "urgent", "fyi", "archive")
_INTERNAL_ERROR_INLINE_PATTERNS = (
    re.compile(r"(?is)failed to parse [^:\n]+ response:\s*"),
    re.compile(r"(?is)failed to parse [^:\n]+:\s*"),
)
_INTERNAL_ERROR_LINE_PATTERNS = (
    re.compile(r"(?i)^failed to parse [^:\n]+ response:"),
    re.compile(r"(?i)^traceback \(most recent call last\):"),
    re.compile(r"(?i)^internal error while generating the response"),
)

# Convert Markdown inline markers to Telegram HTML tags.
# Order matters: bold before italic so **text** is not partially matched by *text*.
_MARKDOWN_TO_HTML_PATTERNS = (
    (re.compile(r"\*\*(.*?)\*\*", re.DOTALL), r"<b>\1</b>"),
    (re.compile(r"__(.*?)__", re.DOTALL), r"<b>\1</b>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*(.*?)\*", re.DOTALL), r"<i>\1</i>"),
    # Underscore italic only when surrounded by word boundaries to avoid mangling
    # snake_case identifiers.
    (re.compile(r"(?<!\w)_([^_]+)_(?!\w)", re.DOTALL), r"<i>\1</i>"),
)

# Characters that must be escaped in Telegram HTML mode.
# Only three: &, <, >. The LLM output is escaped BEFORE the Markdown→HTML
# conversion so that literal < or > in the text become &lt;/&gt; while the
# tags we insert ourselves are left intact.
_HTML_ESCAPE = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})


def _escape_html(text: str) -> str:
    """Escape literal HTML characters in raw LLM output."""
    return text.translate(_HTML_ESCAPE)


def get_response_style_prefix() -> str:
    """Get the shared response-style prompt prefix."""
    return f"<response_style>\n{_RESPONSE_STYLE_PROMPT}\n</response_style>\n\n"


def normalize_response(
    response: ChatResponse,
    *,
    message: MessageInput,
    intent: Intent,
) -> ChatResponse:
    """Return a copy of the response with normalized user-facing text."""
    normalized = normalize_response_text(
        response.content,
        source=message.source,
        specialist=str(intent.specialist),
        message_content=message.content,
        metadata=response.metadata,
    )
    if normalized == response.content:
        return response
    return response.model_copy(update={"content": normalized})


def normalize_response_text(
    text: str,
    *,
    source: str,
    specialist: str,
    message_content: str,
    metadata: dict | None = None,
) -> str:
    """Normalize user-facing text for the current channel."""
    metadata = metadata or {}
    cleaned = text.strip()
    if not cleaned:
        return cleaned

    cleaned = _strip_canned_openers(cleaned)
    cleaned = _strip_code_fences(cleaned)
    cleaned = _strip_internal_error_leakage(cleaned)
    cleaned = _dedupe_repeated_lines(cleaned)

    if specialist == "communications":
        cleaned = _normalize_communications_text(
            cleaned,
            message_content=message_content,
            metadata=metadata,
        )

    # Channel-specific rendering (Markdown → HTML) is applied exclusively in
    # render_response_envelope() to prevent double-escaping when this function
    # is called at both the normalize and render stages of the pipeline.
    if source != "telegram":
        cleaned = _strip_markdown_headings(cleaned)

    return cleaned.strip()


def format_telegram_text(text: str) -> str:
    """Convert LLM Markdown output to Telegram HTML for structured delivery.

    Pipeline:
    1. Escape literal & < > in the raw text so they render as characters.
    2. Strip bare Markdown headings (### Foo → Foo, rendered as plain text
       since Telegram HTML has no heading tag).
    3. Convert inline Markdown markers to HTML tags.
    4. Normalise bullet characters to the Unicode bullet (•) for readability.
    5. Collapse excess blank lines.
    """
    text = text.replace("\r\n", "\n")

    # Step 1 — escape literal HTML chars BEFORE inserting our own tags.
    text = _escape_html(text)

    # Step 2 — strip Markdown headings (### Foo → Foo in bold).
    text = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"<b>\1</b>", text)

    # Step 3 — convert inline Markdown to HTML.
    for pattern, replacement in _MARKDOWN_TO_HTML_PATTERNS:
        text = pattern.sub(replacement, text)

    # Step 4 — normalise bullet characters.
    lines: list[str] = []
    previous_blank = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue

        previous_blank = False
        if line.startswith(("* ", "- ")):
            line = f"• {line[2:].strip()}"
        lines.append(line)

    # Step 5 — collapse excess blank lines.
    formatted = "\n".join(lines)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)
    return formatted.strip()


def _strip_canned_openers(text: str) -> str:
    lower = text.lower()
    for opener in _FORBIDDEN_OPENERS:
        if lower.startswith(opener):
            for separator in (":", ",", "-", "—", "!"):
                prefix = f"{opener}{separator}"
                if lower.startswith(prefix):
                    return text[len(prefix) :].strip()
    return text


def _strip_code_fences(text: str) -> str:
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return text


def _strip_markdown_headings(text: str) -> str:
    return re.sub(r"(?m)^#{1,6}\s+", "", text).strip()


def _strip_internal_error_leakage(text: str) -> str:
    stripped = text.strip()
    for pattern in _INTERNAL_ERROR_INLINE_PATTERNS:
        stripped = pattern.sub("", stripped).strip()

    cleaned_lines: list[str] = []
    for line in stripped.splitlines():
        if any(pattern.match(line.strip()) for pattern in _INTERNAL_ERROR_LINE_PATTERNS):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    if cleaned:
        return cleaned
    return "I ran into a formatting issue on my side. Ask again and I'll answer directly."


def _dedupe_repeated_lines(text: str) -> str:
    """Collapse immediate duplicate lines from malformed model output."""
    deduped: list[str] = []
    previous: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if previous is not None and line and line == previous:
            continue
        deduped.append(raw_line)
        previous = line or previous
    return "\n".join(deduped)


def _normalize_communications_text(
    text: str,
    *,
    message_content: str,
    metadata: dict,
) -> str:
    if metadata.get("subject"):
        return text

    wants_triage_labels = _wants_explicit_triage(message_content)
    user_reply = (metadata.get("user_reply") or "").strip()
    action = (metadata.get("suggested_action") or "").strip()
    urgency = (metadata.get("urgency_reason") or "").strip()
    deadline = (metadata.get("response_deadline") or "").strip()
    classification = (metadata.get("classification") or "").strip()

    if _looks_mechanical(text) and user_reply:
        text = user_reply
    elif _looks_mechanical(text):
        text = _build_natural_triage_reply(metadata)

    if wants_triage_labels:
        details: list[str] = []
        if classification:
            details.append(f"Category: {classification}.")
        if action:
            details.append(f"Next step: {action}.")
        if deadline:
            details.append(f"Deadline: {deadline}.")
        elif urgency:
            details.append(f"Why it matters: {urgency}.")
        if details:
            text = "\n\n".join([text, " ".join(details)])

    return text.strip()


def _build_natural_triage_reply(metadata: dict) -> str:
    sender = (metadata.get("sender") or "This email").strip()
    subject = (metadata.get("subject_summary") or "").strip()
    action = (metadata.get("suggested_action") or "").strip()
    urgency = (metadata.get("urgency_reason") or "").strip()
    deadline = (metadata.get("response_deadline") or "").strip()

    first_sentence = sender if sender.lower().startswith("this email") else f"{sender}"
    if subject:
        first_sentence = f"{first_sentence} is about {subject}."
    else:
        first_sentence = f"{first_sentence} needs attention."

    follow_up: list[str] = []
    if urgency:
        follow_up.append(urgency.rstrip(".") + ".")
    if action:
        follow_up.append(f"Next step: {action}.")
    elif deadline:
        follow_up.append(f"Deadline: {deadline}.")

    return " ".join([first_sentence, *follow_up]).strip()


def _looks_mechanical(text: str) -> bool:
    stripped = text.strip()
    lower = stripped.lower()
    return lower.startswith(("classification:", "{", "[")) or bool(
        re.match(r"^[A-Z_]+ from .+:", stripped)
    )


def _wants_explicit_triage(message_content: str) -> bool:
    lower = message_content.lower()
    return any(keyword in lower for keyword in _TRIAGE_KEYWORDS)
