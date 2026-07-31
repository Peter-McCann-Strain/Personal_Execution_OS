"""Tests for generated OpenAPI contract helpers."""

from scripts.export_openapi import build_routes_ts, path_to_key


def test_path_to_key_handles_plain_paths():
    assert path_to_key("/api/chat/stream") == "apiChatStream"
    assert path_to_key("/health/preflight") == "healthPreflight"


def test_path_to_key_handles_path_parameters():
    assert path_to_key("/api/notes/{note_id}/links") == "apiNotesByNoteIdLinks"


def test_build_routes_ts_contains_paths():
    content = build_routes_ts(
        {
            "paths": {
                "/health": {},
                "/api/chat/stream": {},
            }
        }
    )
    assert 'health: "/health"' in content
    assert 'apiChatStream: "/api/chat/stream"' in content
