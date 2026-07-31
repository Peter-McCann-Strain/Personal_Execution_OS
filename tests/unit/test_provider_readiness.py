"""Tests for the provider-readiness CLI."""

from __future__ import annotations

import argparse

import pytest

from scripts.provider_readiness import _render_text_report, build_parser


def test_build_parser_accepts_flags():
    parser = build_parser()

    args = parser.parse_args(["--include-runtime-checks", "--json", "--strict"])

    assert isinstance(args, argparse.Namespace)
    assert args.include_runtime_checks is True
    assert args.json is True
    assert args.strict is True


def test_render_text_report_with_provider_details():
    report = {
        "status": "ok",
        "checks": [
            {
                "name": "provider_configuration",
                "details": {
                    "required": {
                        "anthropic": True,
                        "database": True,
                        "redis": True,
                        "chat_api": True,
                    },
                    "optional": {
                        "google_workspace": False,
                        "tavily": True,
                        "telegram": False,
                    },
                    "missing_required": [],
                    "missing_optional": ["google_workspace", "telegram"],
                },
            }
        ],
    }

    output = _render_text_report(report)

    assert "Provider readiness: ok" in output
    assert "- required configured: 4/4" in output
    assert "- missing required: none" in output
    assert "- enabled optional: tavily" in output
    assert "- missing optional: google_workspace, telegram" in output


def test_render_text_report_without_provider_check():
    output = _render_text_report({"status": "warn", "checks": []})

    assert output == "Provider readiness: warn\n- provider configuration: unavailable"


@pytest.mark.asyncio
async def test_main_async_returns_nonzero_on_warn_in_strict_mode(monkeypatch):
    from datetime import UTC, datetime

    from scripts import provider_readiness
    from src.app.core.preflight import PreflightCheck, PreflightReport

    monkeypatch.setattr(provider_readiness, "get_settings", lambda: object())

    async def _fake_preflight_dt(**_kwargs):
        return PreflightReport(
            status="warn",
            generated_at=datetime(2026, 4, 8, tzinfo=UTC),
            checks=[
                PreflightCheck(
                    name="provider_configuration",
                    status="ok",
                    message="ok",
                    details={
                        "required": {"anthropic": True},
                        "optional": {},
                        "missing_required": [],
                        "missing_optional": [],
                    },
                )
            ],
        )

    monkeypatch.setattr(provider_readiness, "run_startup_preflight", _fake_preflight_dt)

    exit_code = await provider_readiness._main_async(
        argparse.Namespace(include_runtime_checks=False, json=False, strict=True)
    )

    assert exit_code == 1
