"""Static invariants for the one-command self-hosted stack."""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yml"


def test_root_compose_has_hardened_core_services() -> None:
    content = COMPOSE.read_text(encoding="utf-8")

    for service in ["postgres:", "redis:", "migrate:", "api:", "worker:", "web:"]:
        assert service in content
    assert content.count("env_file:") == 2
    assert "supabase" not in content.casefold()
    assert "image: ollama" not in content.casefold()
    assert "OLLAMA_HOST: ${OLLAMA_HOST:-}" in content
    assert "LLM_PROVIDER: ${LLM_PROVIDER:-disabled}" in content
    assert "127.0.0.1:${APP_PORT:-8080}:8080" in content
    assert "${POSTGRES_PASSWORD:?Run ./scripts/start.sh first}" in content
    assert "${POSTGRES_ADMIN_PASSWORD:?Run ./scripts/start.sh first}" in content
    assert "${POSTGRES_MIGRATOR_PASSWORD:?Run ./scripts/start.sh first}" in content
    assert "assistant_runtime" in content
    assert "assistant_migrator" in content
    assert "local-only-change-me" not in content
    assert "AUTH_COOKIE_SECURE: ${AUTH_COOKIE_SECURE:-false}" in content
    assert "AUTH_TRUSTED_ORIGINS: ${AUTH_TRUSTED_ORIGINS:-}" in content
    assert content.count("./config/IDENTITY.local.md:/app/config/IDENTITY.local.md:ro") == 2
    web_block = content.split("  web:", maxsplit=1)[1]
    assert "env_file:" not in web_block
    assert "worker-egress" in content
    assert "internal: true" in content

    for service in ["migrate", "api", "worker", "web"]:
        block = content.split(f"  {service}:", maxsplit=1)[1]
        next_service = re.search(r"\n  [a-z][a-z0-9-]*:\n", block)
        if next_service:
            block = block[: next_service.start()]
        assert "read_only: true" in block
        assert "cap_drop:\n      - ALL" in block
        assert "no-new-privileges:true" in block
        assert "pids_limit:" in block
        assert "/tmp:" in block


def test_private_local_identity_files_never_enter_docker_build_context() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    patterns = set(dockerignore.splitlines())

    assert {
        "config/*.local.md",
        "config/*.local.yaml",
        "config/*.local.yml",
        "**/*.local.md",
        "**/*.local.yaml",
        "**/*.local.yml",
    }.issubset(patterns)
    assert "COPY config/ config/" in (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")


def test_backend_image_prepares_writable_app_data_volume_mountpoint() -> None:
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "mkdir -p /var/lib/personal-execution-os" in dockerfile
    assert "chown appuser:appuser /var/lib/personal-execution-os" in dockerfile
    assert "adduser -S -D -H -G appuser appuser" in dockerfile
    assert dockerfile.index(
        "chown appuser:appuser /var/lib/personal-execution-os"
    ) < dockerfile.index("USER appuser")

    compose = COMPOSE.read_text(encoding="utf-8")
    assert "app-data:/var/lib/personal-execution-os" in compose
    assert "SPOTCHECK_DIR: /var/lib/personal-execution-os/evaluation/spotcheck" in compose
    assert (
        "DATASET_PROPOSALS_DIR: /var/lib/personal-execution-os/evaluation/datasets/proposals"
        in compose
    )


def test_compose_orders_migrations_before_runtime() -> None:
    content = COMPOSE.read_text(encoding="utf-8")

    assert content.count("condition: service_completed_successfully") == 2
    assert "condition: service_healthy" in content
    assert "alembic upgrade head && python -m scripts.grant_runtime_role" in content
    worker_block = content.split("  worker:", maxsplit=1)[1].split(
        "  web:",
        maxsplit=1,
    )[0]
    assert "healthcheck:" in worker_block
    assert "--check" in worker_block


def test_redis_queue_data_cannot_be_evicted() -> None:
    content = COMPOSE.read_text(encoding="utf-8")
    assert "--maxmemory-policy" in content
    assert "noeviction" in content


def test_web_proxy_does_not_trust_client_forwarded_for_headers() -> None:
    nginx = (ROOT / "docker" / "nginx-site.conf.template").read_text(encoding="utf-8")

    assert "$proxy_add_x_forwarded_for" not in nginx
    assert nginx.count("proxy_set_header X-Forwarded-For $remote_addr;") == 5


def test_web_proxy_rejects_unknown_host_headers() -> None:
    main = (ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
    site = (ROOT / "docker" / "nginx-site.conf.template").read_text(encoding="utf-8")
    entrypoint = (ROOT / "docker" / "web-entrypoint.sh").read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "include /tmp/nginx-conf.d/*.conf;" in main
    assert "listen 8080 default_server;" in site
    assert "listen [::]:8080 default_server;" in site
    assert 'server_name "";' in site
    assert "return 421;" in site
    assert 'server_name localhost 127.0.0.1 "[::1]" ${PUBLIC_HOSTNAME};' in site
    assert "PUBLIC_HOSTNAME: ${PUBLIC_HOSTNAME:-}" in compose
    assert "*[!A-Za-z0-9.-]* | .* | *. | *..*)" in entrypoint
    assert "envsubst '${PUBLIC_HOSTNAME}'" in entrypoint


@pytest.mark.parametrize(
    "configured_host",
    [
        "https://assistant.example.com",
        "assistant.example.com:443",
        "*.example.com",
        "one.example.com,two.example.com",
        "[2001:db8::1]",
        "2001:db8::1",
    ],
)
def test_web_proxy_rejects_unsafe_public_hostname_values(
    configured_host: str,
) -> None:
    entrypoint = ROOT / "docker" / "web-entrypoint.sh"
    env = os.environ.copy()
    env["PUBLIC_HOSTNAME"] = configured_host

    completed = subprocess.run(
        ["sh", str(entrypoint)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert completed.returncode == 1
    assert "one exact DNS hostname or IPv4 address" in completed.stderr
