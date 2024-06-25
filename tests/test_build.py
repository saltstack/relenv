# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
import hashlib

import pytest

from relenv.build.common import Builder, verify_checksum
from relenv.common import DATA_DIR, RelenvException


@pytest.fixture
def fake_download(tmp_path):
    download = tmp_path / "fake_download"
    download.write_text("This is some file contents")
    return download


@pytest.fixture
def fake_download_md5(fake_download):
    return hashlib.sha1(fake_download.read_bytes()).hexdigest()


@pytest.mark.skip_unless_on_linux
def test_builder_defaults_linux():
    builder = Builder(version="3.10.10")
    assert builder.arch == "x86_64"
    assert builder.arch == "x86_64"
    assert builder.triplet == "x86_64-linux-gnu"
    assert builder.prefix == DATA_DIR / "build" / "3.10.10-x86_64-linux-gnu"
    assert builder.sources == DATA_DIR / "src"
    assert builder.downloads == DATA_DIR / "download"
    assert builder.toolchains == DATA_DIR / "toolchain"
    assert builder.toolchain == DATA_DIR / "toolchain" / "x86_64-linux-gnu"
    assert callable(builder.build_default)
    assert callable(builder.populate_env)
    assert builder.force_download is False
    assert builder.recipies == {}


def test_verify_checksum(fake_download, fake_download_md5):
    assert verify_checksum(fake_download, fake_download_md5) is True


def test_verify_checksum_failed(fake_download):
    pytest.raises(RelenvException, verify_checksum, fake_download, "no")
