"""Tests for Docker context setup used by the real-database integration suite."""

from __future__ import annotations

from pathlib import Path

from tests.integration.docker_runtime import (
    _DockerContext,
    configure_testcontainers_runtime,
)

COLIMA_HOST = "unix:///workspace/.colima/default/docker.sock"


def test_active_colima_context_configures_docker_and_ryuk_sockets() -> None:
    environ: dict[str, str] = {}

    configure_testcontainers_runtime(
        environ,
        context_inspector=lambda: _DockerContext(name="colima", host=COLIMA_HOST),
        socket_exists=lambda path: path == Path("/workspace/.colima/default/docker.sock"),
    )

    assert environ == {
        "DOCKER_HOST": COLIMA_HOST,
        "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE": "/var/run/docker.sock",
    }


def test_explicit_colima_host_adds_only_missing_ryuk_override() -> None:
    environ = {"DOCKER_HOST": COLIMA_HOST}

    configure_testcontainers_runtime(
        environ,
        context_inspector=lambda: (_ for _ in ()).throw(AssertionError("must not inspect")),
    )

    assert environ == {
        "DOCKER_HOST": COLIMA_HOST,
        "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE": "/var/run/docker.sock",
    }


def test_explicit_testcontainers_override_is_preserved() -> None:
    environ = {
        "DOCKER_HOST": COLIMA_HOST,
        "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE": "/custom/docker.sock",
    }

    configure_testcontainers_runtime(environ)

    assert environ["TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE"] == "/custom/docker.sock"


def test_non_colima_context_does_not_change_environment() -> None:
    environ: dict[str, str] = {}

    configure_testcontainers_runtime(
        environ,
        context_inspector=lambda: _DockerContext(
            name="desktop-linux",
            host="unix:///workspace/.docker/run/docker.sock",
        ),
    )

    assert environ == {}


def test_missing_colima_socket_does_not_select_stale_context() -> None:
    environ: dict[str, str] = {}

    configure_testcontainers_runtime(
        environ,
        context_inspector=lambda: _DockerContext(name="colima", host=COLIMA_HOST),
        socket_exists=lambda _path: False,
    )

    assert environ == {}
