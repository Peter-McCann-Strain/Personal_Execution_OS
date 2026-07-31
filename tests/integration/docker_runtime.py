"""Configure Docker runtime details needed by integration-test containers.

The Docker CLI understands contexts, but docker-py (and therefore
testcontainers-python) does not automatically use the active CLI context.
Colima also needs a different socket path inside the Ryuk container than the
socket path exposed to the macOS host.

This module intentionally has no testcontainers imports. Call
``configure_testcontainers_runtime`` before importing testcontainers so its
module-level configuration sees the resolved environment.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

_RYUK_SOCKET_IN_COLIMA_VM = "/var/run/docker.sock"


@dataclass(frozen=True, slots=True)
class _DockerContext:
    name: str
    host: str


def configure_testcontainers_runtime(
    environ: MutableMapping[str, str] | None = None,
    *,
    context_inspector: Callable[[], _DockerContext | None] | None = None,
    socket_exists: Callable[[Path], bool] | None = None,
) -> None:
    """Populate the missing Testcontainers settings for an active Colima context.

    Explicit environment values always win. Detection is deliberately narrow:
    it only applies when ``DOCKER_HOST`` points to a Colima Unix socket, or when
    the active Docker CLI context resolves to one.

    The injectable callables are test seams; normal callers should not pass
    them.
    """
    target_environ = os.environ if environ is None else environ
    inspect_context = context_inspector or _inspect_active_docker_context
    path_is_available = socket_exists or Path.is_socket

    docker_host = target_environ.get("DOCKER_HOST")
    if docker_host:
        if _is_colima_socket(docker_host):
            target_environ.setdefault(
                "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE",
                _RYUK_SOCKET_IN_COLIMA_VM,
            )
        return

    context = inspect_context()
    if context is None or not _is_colima_context(context):
        return

    socket_path = _unix_socket_path(context.host)
    if socket_path is None or not path_is_available(socket_path):
        return

    target_environ["DOCKER_HOST"] = context.host
    target_environ.setdefault(
        "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE",
        _RYUK_SOCKET_IN_COLIMA_VM,
    )


def _inspect_active_docker_context() -> _DockerContext | None:
    """Return the active Docker CLI context without importing docker-py."""
    try:
        completed = subprocess.run(
            ["docker", "context", "inspect"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0:
        return None

    try:
        contexts: Any = json.loads(completed.stdout)
        context = contexts[0]
        name = context["Name"]
        host = context["Endpoints"]["docker"]["Host"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        return None

    if not isinstance(name, str) or not isinstance(host, str):
        return None
    return _DockerContext(name=name, host=host)


def _is_colima_context(context: _DockerContext) -> bool:
    return context.name.casefold().startswith("colima") or _is_colima_socket(context.host)


def _is_colima_socket(host: str) -> bool:
    socket_path = _unix_socket_path(host)
    return socket_path is not None and ".colima" in socket_path.parts


def _unix_socket_path(host: str) -> Path | None:
    parsed = urlparse(host)
    if parsed.scheme != "unix" or not parsed.path:
        return None
    return Path(unquote(parsed.path))
