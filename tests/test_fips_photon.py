# Copyright 2023-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
import os
import pathlib

# mypy: ignore-errors
import subprocess
from typing import Any

import pytest

from tests.test_verify_build import _install_ppbt

from .conftest import get_build_version


def check_test_environment() -> bool:
    path = pathlib.Path("/etc/os-release")
    if path.exists():
        release = path.read_text()
        return "Photon" in release and "4.0" in release
    return False


pytestmark = [
    pytest.mark.skipif(not get_build_version(), reason="Build archive does not exist"),
    pytest.mark.skipif(
        not check_test_environment(), reason="Not running on photon 4 with fips enabled"
    ),
]


def test_fips_mode(pyexec: str, build: Any) -> None:
    _install_ppbt(pyexec)
    env = os.environ.copy()
    proc = subprocess.run(
        [
            pyexec,
            "-c",
            "import hashlib; hashlib.sha256(b'')",
        ],
        check=False,
        env=env,
        capture_output=True,
    )
    assert proc.returncode == 0
    assert b"ValueError" not in proc.stderr
    proc = subprocess.run(
        [
            pyexec,
            "-c",
            "import hashlib; hashlib.md5(b'')",
        ],
        check=False,
        env=env,
        capture_output=True,
    )
    assert b"ValueError" in proc.stderr or b"UnsupportedDigestmodError" in proc.stderr
