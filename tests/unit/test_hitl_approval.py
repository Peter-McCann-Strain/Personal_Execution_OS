"""Phase 5.8 — tests for the HITL tool approval gate.

These tests never talk to real Telegram or Google APIs. LangGraph's real
``interrupt()`` is replaced by a synchronous stand-in that simulates each
resume path: approve, edit, cancel, timeout. Trusted-destination auto-approve
skips the stand-in entirely.

Invariants verified here:
- ``interrupt()`` is NEVER wrapped in try/except by the gate.
- Code above ``interrupt()`` inside ``approval_gate`` is side-effect free.
- Secrets are stripped from preview payloads.
- Approval records are emitted as ``span_kind='approval'`` trace spans.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.app.core.hitl import (
    ApprovalResult,
    SyntheticCancelledResult,
    approval_gate,
    build_approval_span,
    build_interrupt_payload,
    extract_destinations,
    format_preview,
    is_auto_approved,
    mask_secrets,
    parse_resume_value,
    requires_approval,
)

# ---------------------------------------------------------------------------
# Settings fixture — isolates tests from real env.
# ---------------------------------------------------------------------------


def _mock_settings(
    *,
    hitl_enabled: bool = True,
    trusted: list[str] | None = None,
    timeout_seconds: int = 300,
) -> MagicMock:
    s = MagicMock()
    s.hitl_enabled = hitl_enabled
    s.hitl_timeout_seconds = timeout_seconds
    s.hitl_auto_approve_destinations = list(trusted or [])
    return s


@pytest.fixture(autouse=True)
def _patch_default_settings():
    """Default settings for every test; individual tests override with `settings=`."""
    with patch("src.app.core.hitl.get_settings", return_value=_mock_settings()):
        yield


# ---------------------------------------------------------------------------
# Pure-function checks.
# ---------------------------------------------------------------------------


class TestRequiresApproval:
    def test_gates_on_send(self):
        assert (
            requires_approval(
                mutation_class="send", requires_confirmation=False, settings=_mock_settings()
            )
            is True
        )

    def test_gates_on_create_update_delete(self):
        for cls in ("create", "update", "delete", "mutating"):
            assert (
                requires_approval(
                    mutation_class=cls,
                    requires_confirmation=False,
                    settings=_mock_settings(),
                )
                is True
            ), f"should gate {cls}"

    def test_passes_through_read_only(self):
        assert (
            requires_approval(
                mutation_class="read_only",
                requires_confirmation=False,
                settings=_mock_settings(),
            )
            is False
        )

    def test_requires_confirmation_overrides_mutation_class(self):
        assert (
            requires_approval(
                mutation_class="read_only",
                requires_confirmation=True,
                settings=_mock_settings(),
            )
            is True
        )

    def test_disabled_globally(self):
        assert (
            requires_approval(
                mutation_class="send",
                requires_confirmation=True,
                settings=_mock_settings(hitl_enabled=False),
            )
            is False
        )


class TestMaskSecrets:
    def test_masks_common_secret_keys(self):
        args = {
            "to": "recipient@example.com",
            "api_key": "sk-secret",
            "oauth_token": "abc",
            "auth_header": "Bearer xyz",
            "password": "hunter2",
        }
        masked = mask_secrets(args)
        assert masked["to"] == "recipient@example.com"
        assert masked["api_key"] == "***"
        assert masked["oauth_token"] == "***"
        assert masked["auth_header"] == "***"
        assert masked["password"] == "***"

    def test_masks_nested(self):
        args = {"headers": {"Authorization": "Bearer abc", "X-Req-Id": "ok"}}
        masked = mask_secrets(args)
        assert masked["headers"]["Authorization"] == "***"
        assert masked["headers"]["X-Req-Id"] == "ok"

    def test_masks_inside_lists(self):
        args = {"attachments": [{"secret_key": "s", "name": "report.pdf"}]}
        masked = mask_secrets(args)
        assert masked["attachments"][0]["secret_key"] == "***"
        assert masked["attachments"][0]["name"] == "report.pdf"


class TestFormatPreview:
    def test_email_send_preview(self):
        preview = format_preview(
            "google-gmail__send_message",
            {"to": "priya@example.com", "subject": "Project update", "body": "Hi" * 500},
        )
        assert "Send this email?" in preview
        assert "priya@example.com" in preview
        assert "Project update" in preview
        # Body truncated — must not exceed the advertised 200-char limit + ellipsis.
        assert "first 200 chars" in preview

    def test_calendar_create_preview(self):
        preview = format_preview(
            "google-calendar__create_event",
            {
                "summary": "Team standup",
                "start": "2026-04-19T09:00:00Z",
                "end": "2026-04-19T09:30:00Z",
                "attendees": ["alice@example.com", "bob@example.com"],
            },
        )
        assert "Create this calendar event?" in preview
        assert "Team standup" in preview
        assert "alice@example.com" in preview

    def test_github_issue_preview(self):
        preview = format_preview(
            "github__create_issue",
            {"repo": "foo/bar", "title": "Crash on startup", "body": "..."},
        )
        assert "Create this GitHub issue?" in preview
        assert "foo/bar" in preview

    def test_generic_preview_falls_back(self):
        preview = format_preview("mystery__do_thing", {"x": 1, "y": "z"})
        assert "mystery__do_thing" in preview
        assert "x:" in preview

    def test_preview_never_contains_secret_value(self):
        preview = format_preview(
            "google-gmail__send_message",
            {
                "to": "recipient@example.com",
                "subject": "s",
                "body": "b",
                "api_key": "SECRET_VALUE",
            },
        )
        assert "SECRET_VALUE" not in preview


class TestExtractDestinations:
    def test_gathers_to_cc_bcc(self):
        got = extract_destinations(
            "google-gmail__send_message",
            {
                "to": "alice@example.com",
                "cc": ["bob@example.com", "carol@example.com"],
                "bcc": "dave@example.com",
            },
        )
        assert set(got) == {
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
            "dave@example.com",
        }

    def test_parses_calendar_attendees(self):
        got = extract_destinations(
            "google-calendar__create_event",
            {"attendees": [{"email": "recipient@example.com"}, "zara@example.com"]},
        )
        assert set(got) == {"recipient@example.com", "zara@example.com"}

    def test_splits_comma_separated_strings(self):
        got = extract_destinations(
            "google-gmail__send_message",
            {"to": "alice@example.com, bob@example.com; carol@example.com"},
        )
        assert set(got) == {"alice@example.com", "bob@example.com", "carol@example.com"}


class TestIsAutoApproved:
    def test_all_destinations_trusted(self):
        settings = _mock_settings(trusted=["owner@example.com"])
        assert (
            is_auto_approved(
                tool_name="google-gmail__send_message",
                args={"to": "owner@example.com", "subject": "x", "body": "y"},
                settings=settings,
            )
            is True
        )

    def test_one_untrusted_breaks_auto_approve(self):
        settings = _mock_settings(trusted=["owner@example.com"])
        assert (
            is_auto_approved(
                tool_name="google-gmail__send_message",
                args={
                    "to": ["owner@example.com", "stranger@example.com"],
                    "subject": "x",
                    "body": "y",
                },
                settings=settings,
            )
            is False
        )

    def test_empty_trusted_list_never_auto_approves(self):
        assert (
            is_auto_approved(
                tool_name="google-gmail__send_message",
                args={"to": "recipient@example.com"},
                settings=_mock_settings(trusted=[]),
            )
            is False
        )

    def test_tool_with_no_destinations_not_auto_approved(self):
        # A GitHub issue has no email/attendee — trust lists don't apply.
        assert (
            is_auto_approved(
                tool_name="github__create_issue",
                args={"repo": "r", "title": "t", "body": "b"},
                settings=_mock_settings(trusted=["owner@example.com"]),
            )
            is False
        )


class TestParseResumeValue:
    def test_string_approve(self):
        decision, args, reason = parse_resume_value("approve", original_args={"x": 1})
        assert decision == ApprovalResult.APPROVE
        assert args == {"x": 1}
        assert reason is None

    def test_string_cancel(self):
        decision, _, _ = parse_resume_value("cancel", original_args={})
        assert decision == ApprovalResult.CANCEL

    def test_dict_edit(self):
        decision, args, _ = parse_resume_value(
            {"edit": {"subject": "new"}}, original_args={"subject": "old"}
        )
        assert decision == ApprovalResult.EDIT
        assert args == {"subject": "new"}

    def test_dict_decision_edit_with_args(self):
        decision, args, _ = parse_resume_value(
            {"decision": "edit", "args": {"subject": "new"}},
            original_args={"subject": "old"},
        )
        assert decision == ApprovalResult.EDIT
        assert args == {"subject": "new"}

    def test_none_becomes_cancel(self):
        decision, _, reason = parse_resume_value(None, original_args={})
        assert decision == ApprovalResult.CANCEL
        assert reason == "no_reply"

    def test_unrecognised_string_becomes_cancel(self):
        decision, _, reason = parse_resume_value("maybe", original_args={})
        assert decision == ApprovalResult.CANCEL
        assert reason is not None
        assert "unrecognised_reply" in reason

    def test_timeout_string(self):
        decision, _, _ = parse_resume_value("timeout", original_args={})
        assert decision == ApprovalResult.TIMEOUT


# ---------------------------------------------------------------------------
# End-to-end gate flows — the critical correctness tests.
# ---------------------------------------------------------------------------


class TestApprovalGateFlows:
    """Each flow uses a fake `interrupt_fn` that returns a scripted reply."""

    def test_approve_path_runs_tool_with_original_args(self):
        settings = _mock_settings()
        called_with: list[dict] = []

        def fake_interrupt(payload: dict):
            called_with.append(payload)
            return "approve"

        result = approval_gate(
            tool_name="google-gmail__send_message",
            args={"to": "owner@example.com", "subject": "s", "body": "b"},
            mutation_class="send",
            settings=settings,
            interrupt_fn=fake_interrupt,
        )
        assert result.decision == ApprovalResult.APPROVE
        assert result.should_run is True
        assert result.args == {"to": "owner@example.com", "subject": "s", "body": "b"}
        # Preview was formatted and the payload was JSON-safe.
        assert called_with[0]["kind"] == "tool_approval"
        assert "Send this email?" in called_with[0]["preview"]

    def test_edit_path_runs_tool_with_edited_args(self):
        settings = _mock_settings()

        def fake_interrupt(_payload: dict):
            return {
                "edit": {
                    "to": "owner@example.com",
                    "subject": "NEW",
                    "body": "edited body",
                }
            }

        result = approval_gate(
            tool_name="google-gmail__send_message",
            args={"to": "owner@example.com", "subject": "old", "body": "b"},
            mutation_class="send",
            settings=settings,
            interrupt_fn=fake_interrupt,
        )
        assert result.decision == ApprovalResult.EDIT
        assert result.should_run is True
        assert result.args["subject"] == "NEW"
        assert result.args["body"] == "edited body"

    def test_cancel_path_does_not_run_tool(self):
        settings = _mock_settings()

        def fake_interrupt(_payload: dict):
            return "cancel"

        result = approval_gate(
            tool_name="google-gmail__send_message",
            args={"to": "owner@example.com", "subject": "s", "body": "b"},
            mutation_class="send",
            settings=settings,
            interrupt_fn=fake_interrupt,
        )
        assert result.decision == ApprovalResult.CANCEL
        assert result.should_run is False
        assert result.cancelled is True

        # Synthetic result the specialist receives.
        synthetic = SyntheticCancelledResult(
            tool_name="google-gmail__send_message",
            reason=result.reason or "user_cancelled",
            interrupt_id=result.interrupt_id,
        )
        tr = synthetic.to_tool_result()
        assert tr["cancelled"] is True
        assert tr["is_error"] is False

    def test_timeout_path_defaults_to_cancel(self):
        settings = _mock_settings(timeout_seconds=300)

        def fake_interrupt(_payload: dict):
            # The transport layer simulates a timeout by sending this string.
            return "timeout"

        result = approval_gate(
            tool_name="google-gmail__send_message",
            args={"to": "owner@example.com", "subject": "s", "body": "b"},
            mutation_class="send",
            settings=settings,
            interrupt_fn=fake_interrupt,
        )
        assert result.decision == ApprovalResult.TIMEOUT
        assert result.cancelled is True
        assert result.should_run is False

    def test_no_reply_path_defaults_to_cancel(self):
        """An empty/None resume value also counts as a cancel (fail-safe)."""
        settings = _mock_settings()

        def fake_interrupt(_payload: dict):
            return None

        result = approval_gate(
            tool_name="google-gmail__send_message",
            args={"to": "owner@example.com", "subject": "s", "body": "b"},
            mutation_class="send",
            settings=settings,
            interrupt_fn=fake_interrupt,
        )
        assert result.decision == ApprovalResult.CANCEL
        assert result.reason == "no_reply"

    def test_auto_approve_for_trusted_destination_skips_gate(self):
        settings = _mock_settings(trusted=["owner@example.com"])
        interrupt_called = {"n": 0}

        def fake_interrupt(_payload: dict):
            interrupt_called["n"] += 1
            return "approve"

        result = approval_gate(
            tool_name="google-gmail__send_message",
            args={"to": "owner@example.com", "subject": "s", "body": "b"},
            mutation_class="send",
            settings=settings,
            interrupt_fn=fake_interrupt,
        )
        assert result.decision == ApprovalResult.AUTO_APPROVE
        assert result.should_run is True
        assert interrupt_called["n"] == 0, "gate must not prompt for trusted destinations"

    def test_read_only_tool_passes_through(self):
        settings = _mock_settings()
        interrupt_called = {"n": 0}

        def fake_interrupt(_payload: dict):
            interrupt_called["n"] += 1
            return "approve"

        result = approval_gate(
            tool_name="google-gmail__list_messages",
            args={"query": "from:owner@example.com"},
            mutation_class="read_only",
            settings=settings,
            interrupt_fn=fake_interrupt,
        )
        assert result.decision == ApprovalResult.APPROVE
        assert result.reason == "not_gated"
        assert interrupt_called["n"] == 0


# ---------------------------------------------------------------------------
# Invariants — these are required and enforced structurally.
# ---------------------------------------------------------------------------


class TestInvariants:
    def test_interrupt_is_not_wrapped_in_try_except(self):
        """Static check: no try/except block in hitl.py encloses `interrupt(`.

        Wrapping the interrupt would swallow GraphInterrupt and break the
        LangGraph pause contract. The check parses the AST so new code can't
        silently regress.
        """
        path = Path(__file__).resolve().parents[2] / "src" / "app" / "core" / "hitl.py"
        tree = ast.parse(path.read_text())

        class InterruptInTryFinder(ast.NodeVisitor):
            def __init__(self) -> None:
                super().__init__()
                self.offences: list[int] = []

            def visit_Try(self, node: ast.Try) -> None:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        fn = sub.func
                        name = None
                        if isinstance(fn, ast.Name):
                            name = fn.id
                        elif isinstance(fn, ast.Attribute):
                            name = fn.attr
                        if name in ("interrupt", "effective_interrupt"):
                            self.offences.append(node.lineno)
                # Still recurse into nested nodes for completeness.
                self.generic_visit(node)

        finder = InterruptInTryFinder()
        finder.visit(tree)
        assert finder.offences == [], (
            f"interrupt() must not be wrapped in try/except; found at lines {finder.offences}"
        )

    def test_graph_interrupt_propagates_from_gate(self):
        """Runtime check: if `interrupt_fn` raises, the gate does NOT catch it."""

        class FakeGraphInterrupt(BaseException):
            pass

        def raising_interrupt(_payload: dict):
            raise FakeGraphInterrupt("pause")

        with pytest.raises(FakeGraphInterrupt):
            approval_gate(
                tool_name="google-gmail__send_message",
                args={"to": "recipient@example.com", "subject": "s", "body": "b"},
                mutation_class="send",
                settings=_mock_settings(),
                interrupt_fn=raising_interrupt,
            )

    def test_pre_interrupt_code_is_replay_safe(self):
        """Calling the gate twice with the same approve-path yields identical
        outcomes and no accumulating side effects (the module itself has none
        — this test guards against future accidental additions)."""
        settings = _mock_settings()

        def always_approve(_payload):
            return "approve"

        args = {"to": "recipient@example.com", "subject": "s", "body": "b"}
        r1 = approval_gate(
            tool_name="google-gmail__send_message",
            args=args,
            mutation_class="send",
            settings=settings,
            interrupt_fn=always_approve,
        )
        r2 = approval_gate(
            tool_name="google-gmail__send_message",
            args=args,
            mutation_class="send",
            settings=settings,
            interrupt_fn=always_approve,
        )
        # Each call allocates a fresh interrupt_id, but every other value
        # must match — i.e. re-execution is deterministic from inputs alone.
        assert r1.decision == r2.decision
        assert r1.args == r2.args
        assert r1.should_run == r2.should_run
        assert r1.interrupt_id != r2.interrupt_id

    def test_preview_payload_is_json_safe(self):
        """The dict handed to `interrupt()` must be JSON-serialisable."""
        import json

        payload = build_interrupt_payload(
            tool_name="google-gmail__send_message",
            args={
                "to": "recipient@example.com",
                "subject": "s",
                "body": "b",
                "api_key": "TOP_SECRET_KEY_12345",
                "nested": {"token": "NESTED_SECRET_VAL", "ok": True, "count": 1},
            },
            interrupt_id="tool_approval:01",
            timeout_seconds=300,
        )
        serialised = json.dumps(payload)  # must not raise
        # Both top-level and nested secret values are masked out.
        assert "TOP_SECRET_KEY_12345" not in serialised
        assert "NESTED_SECRET_VAL" not in serialised
        # The masking sentinel IS present in place of each secret.
        assert payload["args"]["api_key"] == "***"
        assert payload["args"]["nested"]["token"] == "***"
        # The payload retains its structural hallmarks.
        assert "tool_approval" in serialised
        assert payload["buttons"][0]["value"] == "approve"


# ---------------------------------------------------------------------------
# Trace-span emission.
# ---------------------------------------------------------------------------


class TestApprovalTraceSpan:
    def test_approve_span_shape(self):
        result = ApprovalResult(
            decision=ApprovalResult.APPROVE,
            args={"to": "recipient@example.com"},
            interrupt_id="tool_approval:1",
        )
        span = build_approval_span(
            result=result,
            tool_name="google-gmail__send_message",
            trace_id="trace-abc",
            specialist="communications",
        )
        assert span["span_kind"] == "approval"
        assert span["status"] == "ok"
        assert span["tool_name"] == "google-gmail__send_message"
        assert span["details"]["decision"] == "approve"
        assert span["details"]["args_edited"] is False

    def test_cancel_span_status(self):
        result = ApprovalResult(
            decision=ApprovalResult.CANCEL,
            args={"to": "recipient@example.com"},
            interrupt_id="tool_approval:1",
            reason="user_cancelled",
        )
        span = build_approval_span(
            result=result,
            tool_name="google-gmail__send_message",
            trace_id="trace-abc",
        )
        assert span["status"] == "cancelled"
        assert span["details"]["reason"] == "user_cancelled"

    def test_span_masks_secrets(self):
        result = ApprovalResult(
            decision=ApprovalResult.APPROVE,
            args={"to": "recipient@example.com", "api_key": "SECRET"},
            interrupt_id="tool_approval:1",
        )
        span = build_approval_span(
            result=result,
            tool_name="google-gmail__send_message",
            trace_id="trace-abc",
        )
        assert span["details"]["args_preview"]["api_key"] == "***"
        assert span["details"]["args_preview"]["to"] == "recipient@example.com"

    def test_edit_span_flags_edited(self):
        result = ApprovalResult(
            decision=ApprovalResult.EDIT,
            args={"to": "recipient@example.com", "subject": "new"},
            interrupt_id="tool_approval:1",
        )
        span = build_approval_span(
            result=result,
            tool_name="google-gmail__send_message",
            trace_id="trace-abc",
            original_args={"to": "recipient@example.com", "subject": "old"},
        )
        assert span["details"]["args_edited"] is True
