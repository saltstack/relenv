# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
import hashlib
import pathlib

import pytest

from relenv.build.common import Builder, verify_checksum
from relenv.common import DATA_DIR, RelenvException, toolchain_root_dir

# mypy: ignore-errors


@pytest.fixture
def fake_download(tmp_path: pathlib.Path) -> pathlib.Path:
    download = tmp_path / "fake_download"
    download.write_text("This is some file contents")
    return download


@pytest.fixture
def fake_download_md5(fake_download: pathlib.Path) -> str:
    return hashlib.sha1(fake_download.read_bytes()).hexdigest()


@pytest.mark.skip_unless_on_linux
def test_builder_defaults_linux() -> None:
    builder = Builder(version="3.10.10")
    assert builder.arch == "x86_64"
    assert builder.arch == "x86_64"
    assert builder.triplet == "x86_64-linux-gnu"
    assert builder.prefix == DATA_DIR / "build" / "3.10.10-x86_64-linux-gnu"
    assert builder.sources == DATA_DIR / "src"
    assert builder.downloads == DATA_DIR / "download"
    assert builder.toolchain == toolchain_root_dir() / builder.triplet
    assert callable(builder.build_default)
    assert callable(builder.populate_env)
    assert builder.recipies == {}


def test_verify_checksum(fake_download: pathlib.Path, fake_download_md5: str) -> None:
    assert verify_checksum(fake_download, fake_download_md5) is True


def test_verify_checksum_failed(fake_download: pathlib.Path) -> None:
    pytest.raises(RelenvException, verify_checksum, fake_download, "no")
