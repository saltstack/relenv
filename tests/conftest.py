# Copyright 2023-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
import os
import platform
import shutil
import sys

import pytest

from relenv.common import list_archived_builds, plat_from_triplet
from relenv.create import create


def get_build_version():
    if "RELENV_PY_VERSION" in os.environ:
        return os.environ["RELENV_PY_VERSION"]
    builds = list(list_archived_builds())
    versions = []
    for version, arch, plat in builds:
        sysplat = plat_from_triplet(plat)
        if sysplat == sys.platform and arch == platform.machine().lower():
            versions.append(version)
    if versions:
        return versions[0]


def pytest_report_header(config):
    return f"relenv python version: {get_build_version()}"


@pytest.fixture(scope="module")
def build_version():
    return get_build_version()


@pytest.fixture(scope="module")
def minor_version():
    yield get_build_version().rsplit(".", 1)[0]


@pytest.fixture
def build(tmp_path, build_version):
    create("test", tmp_path, version=build_version)
    yield tmp_path / "test"


@pytest.fixture
def pipexec(build):
    if sys.platform == "win32":
        path = build / "Scripts"
    else:
        path = build / "bin"

    exe = shutil.which("pip3", path=path)
    if exe is None:
        exe = shutil.which("pip", path=path)
    if exe is None:
        pytest.fail(f"Failed to find 'pip3' and 'pip' in '{path}'")
    yield exe


@pytest.fixture
def pyexec(build):
    if sys.platform == "win32":
        path = build / "Scripts"
    else:
        path = build / "bin"

    exe = shutil.which("python3", path=path)
    if exe is None:
        exe = shutil.which("python", path=path)
    if exe is None:
        pytest.fail(f"Failed to find 'python3' and 'python' in '{path}'")
    yield exe
