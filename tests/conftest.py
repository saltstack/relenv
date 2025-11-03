# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
import logging
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Iterator, Optional

import pytest
from _pytest.config import Config

from relenv.common import list_archived_builds, plat_from_triplet
from relenv.create import create
from tests._pytest_typing import fixture

# mypy: ignore-errors


log = logging.getLogger(__name__)


def get_build_version() -> Optional[str]:
    if "RELENV_PY_VERSION" in os.environ:
        return os.environ["RELENV_PY_VERSION"]
    builds = list(list_archived_builds())
    versions: list[str] = []
    for version, arch, plat in builds:
        sysplat = plat_from_triplet(plat)
        if sysplat == sys.platform and arch == platform.machine().lower():
            versions.append(version)
    if versions:
        version = versions[0]
        log.warning(
            "Environment RELENV_PY_VERSION not set, detected version %s", version
        )
        return version
    return None


def pytest_report_header(config: Config) -> str:
    return f"relenv python version: {get_build_version()}"


@fixture(scope="module")
def build_version() -> Iterator[str]:
    version = get_build_version()
    if version is None:
        pytest.skip("No relenv build version available for current platform")
    assert version is not None
    yield version


@fixture(scope="module")
def minor_version(build_version: str) -> Iterator[str]:
    yield build_version.rsplit(".", 1)[0]


@fixture
def build(tmp_path: Path, build_version: str) -> Iterator[Path]:
    create("test", tmp_path, version=build_version)
    build_path = tmp_path / "test"
    original_cwd = Path.cwd()
    os.chdir(build_path)
    try:
        yield build_path
    finally:
        os.chdir(original_cwd)
        shutil.rmtree(tmp_path, ignore_errors=True)


@fixture
def pipexec(build: Path) -> Iterator[str]:
    path = build / ("Scripts" if sys.platform == "win32" else "bin")
    exe = shutil.which("pip3", path=str(path))
    if exe is None:
        exe = shutil.which("pip", path=str(path))
    if exe is None:
        pytest.fail(f"Failed to find 'pip3' and 'pip' in '{path}'")
    assert exe is not None
    yield exe


@fixture
def pyexec(build: Path) -> Iterator[str]:
    path = build / ("Scripts" if sys.platform == "win32" else "bin")
    exe = shutil.which("python3", path=str(path))
    if exe is None:
        exe = shutil.which("python", path=str(path))
    if exe is None:
        pytest.fail(f"Failed to find 'python3' and 'python' in '{path}'")
    assert exe is not None
    yield exe
