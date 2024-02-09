# Copyright 2023-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
import os
import platform
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
        exc = build / "Scripts" / "pip3.exe"
    else:
        exc = build / "bin" / "pip3"
    yield exc


@pytest.fixture
def pyexec(build):
    if sys.platform == "win32":
        exc = build / "Scripts" / "python.exe"
    else:
        exc = build / "bin" / "python3"
    yield exc
