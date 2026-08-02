"""Release metadata must stay consistent across packages and images."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from src.app.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SOURCE = "https://github.com/Peter-McCann-Strain/Personal_Execution_OS"


def test_package_versions_and_changelog_match_runtime() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_json = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == APP_VERSION
    assert package_json["version"] == APP_VERSION
    assert package_lock["version"] == APP_VERSION
    assert package_lock["packages"][""]["version"] == APP_VERSION
    assert f"## {APP_VERSION} -" in changelog


def test_python_package_has_public_license_and_source_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["license"] == "Apache-2.0"
    assert {"LICENSE", "NOTICE"}.issubset(project["license-files"])
    assert project["urls"]["Repository"] == CANONICAL_SOURCE
    assert project["urls"]["Issues"] == f"{CANONICAL_SOURCE}/issues"


def test_application_images_override_base_image_oci_metadata() -> None:
    for relative_path in ("docker/Dockerfile", "docker/Dockerfile.web"):
        dockerfile = (ROOT / relative_path).read_text(encoding="utf-8")

        assert f"ARG APP_VERSION={APP_VERSION}" in dockerfile
        assert f"ARG SOURCE_REPOSITORY_URL={CANONICAL_SOURCE}" in dockerfile
        assert 'org.opencontainers.image.version="${APP_VERSION}"' in dockerfile
        assert 'org.opencontainers.image.source="${SOURCE_REPOSITORY_URL}"' in dockerfile
        assert 'org.opencontainers.image.revision="${SOURCE_REVISION}"' in dockerfile
        assert 'org.opencontainers.image.licenses="Apache-2.0"' in dockerfile


def test_compose_supplies_version_and_revision_build_arguments() -> None:
    compose = (ROOT / "compose.yml").read_text(encoding="utf-8")

    assert f"APP_VERSION: ${{APP_VERSION:-{APP_VERSION}}}" in compose
    assert "SOURCE_REVISION: ${SOURCE_REVISION:-local}" in compose
    source_argument_lines = [
        line for line in compose.splitlines() if line.strip().startswith("SOURCE_REPOSITORY_URL:")
    ]
    assert len(source_argument_lines) == 2
