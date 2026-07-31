"""Approval callbacks — HITL Telegram bridge for tool approval gates.

Phase 5.8 (task P5.8 wiring).

The LangGraph-canonical resume payload is ``Command(resume=<value>)`` into a
compiled workflow. The tool-call node in ``handlers/tools.py`` drives the
approval via ``src.app.core.hitl.approval_gate``. This module owns:

- the dispatch callback data prefixes for inline keyboards
- a process-local registry that holds the pending approval future for each
  ``interrupt_id`` so the Telegram callback handler can resolve it
- the helper that builds the inline-keyboard markup the user taps in Telegram
- the Telegram handler that converts a tapped button into the resume value
  and (for the Edit path) collects the follow-up message

The module is transport-aware but LangGraph-agnostic — the actual
``Command(resume=...)`` dispatch happens when the orchestrator compiles its
workflow with a checkpointer. Until then, the registry resolves the pending
future directly (matches the test surface in
``tests/integration/test_hitl_orchestrator.py``).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.app.config import get_settings

logger = structlog.get_logger()

# Callback data prefixes — Telegram callback_data is <= 64 bytes so we keep
# the ids terse. Format: "<prefix><interrupt_id>".
CB_APPROVE = "hitl_ap:"
CB_CANCEL = "hitl_cn:"
CB_EDIT = "hitl_ed:"


class _PendingApproval:
    """One outstanding approval — a future, a deadline, and the original args."""

    __slots__ = ("chat_id", "created_at", "deadline", "future", "original_args", "tool_name")

    def __init__(
        self,
        *,
        future: asyncio.Future[Any],
        tool_name: str,
        original_args: dict[str, Any],
        chat_id: int | None,
        timeout_seconds: int,
    ) -> None:
        self.future = future
        self.tool_name = tool_name
        self.original_args = dict(original_args)
        self.chat_id = chat_id
        self.created_at = time.time()
        self.deadline = self.created_at + timeout_seconds


class ApprovalRegistry:
    """Process-local registry that tracks outstanding HITL approvals.

    Thread-safe for asyncio — one lock guards the mapping. A single entry
    lives for the duration of one ``approval_gate`` call.
    """

    def __init__(self) -> None:
        self._pending: dict[str, _PendingApproval] = {}
        self._edit_awaiting: dict[int, str] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        interrupt_id: str,
        tool_name: str,
        original_args: dict[str, Any],
        chat_id: int | None,
        timeout_seconds: int,
    ) -> asyncio.Future[Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        async with self._lock:
            self._pending[interrupt_id] = _PendingApproval(
                future=future,
                tool_name=tool_name,
                original_args=original_args,
                chat_id=chat_id,
                timeout_seconds=timeout_seconds,
            )
        return future

    async def resolve(self, interrupt_id: str, value: Any) -> bool:
        async with self._lock:
            pending = self._pending.pop(interrupt_id, None)
            # Clear any Telegram "awaiting edit text" state pointing at this id.
            to_drop = [chat for chat, id_ in self._edit_awaiting.items() if id_ == interrupt_id]
            for chat in to_drop:
                self._edit_awaiting.pop(chat, None)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(value)
        return True

    async def cancel_expired(self, now: float | None = None) -> list[str]:
        """Cancel every approval past its deadline. Returns the ids cancelled."""
        current = now if now is not None else time.time()
        expired: list[str] = []
        async with self._lock:
            for interrupt_id, pending in list(self._pending.items()):
                if pending.deadline <= current:
                    if not pending.future.done():
                        pending.future.set_result("timeout")
                    expired.append(interrupt_id)
                    self._pending.pop(interrupt_id, None)
        return expired

    async def mark_edit_awaiting(self, chat_id: int, interrupt_id: str) -> None:
        async with self._lock:
            self._edit_awaiting[chat_id] = interrupt_id

    async def pop_edit_awaiting(self, chat_id: int) -> str | None:
        async with self._lock:
            return self._edit_awaiting.pop(chat_id, None)

    def has_edit_awaiting(self, chat_id: int) -> bool:
        return chat_id in self._edit_awaiting

    def pending_chat(self, interrupt_id: str) -> int | None:
        pending = self._pending.get(interrupt_id)
        return pending.chat_id if pending else None

    def clear(self) -> None:  # pragma: no cover - test hook
        self._pending.clear()
        self._edit_awaiting.clear()


# Module-level registry — tests patch or reset this.
_REGISTRY: ApprovalRegistry = ApprovalRegistry()


def get_registry() -> ApprovalRegistry:
    return _REGISTRY


def build_approval_keyboard(interrupt_id: str) -> InlineKeyboardMarkup:
    """Build the three-button inline keyboard for a HITL approval prompt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Approve",
                    callback_data=f"{CB_APPROVE}{interrupt_id}",
                ),
                InlineKeyboardButton(
                    text="Edit",
                    callback_data=f"{CB_EDIT}{interrupt_id}",
                ),
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data=f"{CB_CANCEL}{interrupt_id}",
                ),
            ]
        ]
    )


async def _answer(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.answer(text)
    except Exception:  # pragma: no cover - degraded aiogram path
        logger.debug("telegram_callback_answer_failed", exc_info=True)


async def _handle_approve(callback: CallbackQuery) -> None:
    if callback.data is None:
        return
    interrupt_id = callback.data.removeprefix(CB_APPROVE)
    registry = get_registry()
    resolved = await registry.resolve(interrupt_id, "approve")
    if resolved:
        await _answer(callback, "Approved — running now.")
    else:
        await _answer(callback, "Approval expired or already handled.")


async def _handle_cancel(callback: CallbackQuery) -> None:
    if callback.data is None:
        return
    interrupt_id = callback.data.removeprefix(CB_CANCEL)
    registry = get_registry()
    resolved = await registry.resolve(interrupt_id, "cancel")
    if resolved:
        await _answer(callback, "Cancelled.")
    else:
        await _answer(callback, "Already handled.")


async def _handle_edit_start(callback: CallbackQuery) -> None:
    if callback.data is None or callback.message is None:
        return
    interrupt_id = callback.data.removeprefix(CB_EDIT)
    registry = get_registry()
    chat_id = callback.message.chat.id
    await registry.mark_edit_awaiting(chat_id, interrupt_id)
    await _answer(callback, "Send edited args as JSON or free text.")
    try:
        await callback.message.answer(
            "Reply with edits (JSON for structured args, or free-form text)."
        )
    except Exception:  # pragma: no cover - degraded path
        logger.debug("telegram_edit_prompt_failed", exc_info=True)


def parse_edit_reply(text: str) -> Any:
    """Parse a free-form or JSON reply into a resume-compatible payload."""
    import json

    trimmed = (text or "").strip()
    if not trimmed:
        return "cancel"
    if trimmed.startswith("{") and trimmed.endswith("}"):
        try:
            parsed = json.loads(trimmed)
        except json.JSONDecodeError:
            return {"edit": {"_freeform": trimmed}}
        if isinstance(parsed, dict):
            if "edit" in parsed and isinstance(parsed["edit"], dict):
                return parsed
            return {"edit": parsed}
    return {"edit": {"_freeform": trimmed}}


def register_approval_handlers(router: Router) -> None:
    """Register HITL approval button + follow-up-text handlers on an aiogram router."""
    router.callback_query.register(_handle_approve, F.data.startswith(CB_APPROVE))
    router.callback_query.register(_handle_cancel, F.data.startswith(CB_CANCEL))
    router.callback_query.register(_handle_edit_start, F.data.startswith(CB_EDIT))


async def maybe_handle_edit_reply(chat_id: int, text: str) -> bool:
    """If a chat has an edit awaiting, resolve that approval and return True."""
    registry = get_registry()
    interrupt_id = await registry.pop_edit_awaiting(chat_id)
    if interrupt_id is None:
        return False
    payload = parse_edit_reply(text)
    await registry.resolve(interrupt_id, payload)
    return True


async def wait_for_approval_decision(
    *,
    interrupt_id: str,
    tool_name: str,
    original_args: dict[str, Any],
    chat_id: int | None = None,
    timeout_seconds: int | None = None,
) -> Any:
    """Coroutine entry point used by the HITL gate to block on a user reply.

    Returns the raw resume value ("approve" / "cancel" / {"edit": {...}}) so
    ``parse_resume_value`` in the gate normalises it. Falls back to "timeout"
    if the user does not reply within ``timeout_seconds``.
    """
    settings = get_settings()
    timeout = int(timeout_seconds if timeout_seconds is not None else settings.hitl_timeout_seconds)
    registry = get_registry()
    future = await registry.register(
        interrupt_id=interrupt_id,
        tool_name=tool_name,
        original_args=original_args,
        chat_id=chat_id,
        timeout_seconds=timeout,
    )
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        await registry.resolve(interrupt_id, "timeout")
        return "timeout"
