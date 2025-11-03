# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
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


@pytest.mark.skip_unless_on_linux
def test_builder_toolchain_lazy_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that toolchain is only fetched when accessed (lazy loading)."""
    import relenv.build.common

    call_count = {"count": 0}

    def mock_get_toolchain(arch=None, root=None):
        call_count["count"] += 1
        # Return a fake path instead of actually extracting
        return pathlib.Path(f"/fake/toolchain/{arch or 'default'}")

    monkeypatch.setattr(relenv.build.common, "get_toolchain", mock_get_toolchain)

    # Create builder - should NOT call get_toolchain yet
    builder = Builder(version="3.10.10", arch="aarch64")
    assert call_count["count"] == 0, "get_toolchain should not be called during init"

    # Access toolchain property - should call get_toolchain once
    toolchain = builder.toolchain
    assert (
        call_count["count"] == 1
    ), "get_toolchain should be called when property is accessed"
    assert toolchain == pathlib.Path("/fake/toolchain/aarch64")

    # Access again - should use cached value, not call again
    toolchain2 = builder.toolchain
    assert call_count["count"] == 1, "get_toolchain should only be called once (cached)"
    assert toolchain == toolchain2

    # Change arch - should reset cache
    builder.set_arch("x86_64")
    assert builder._toolchain is None, "Changing arch should reset toolchain cache"

    # Access after arch change - should call get_toolchain again
    toolchain3 = builder.toolchain
    assert (
        call_count["count"] == 2
    ), "get_toolchain should be called again after arch change"
    assert toolchain3 == pathlib.Path("/fake/toolchain/x86_64")


def test_verify_checksum(fake_download: pathlib.Path, fake_download_md5: str) -> None:
    assert verify_checksum(fake_download, fake_download_md5) is True


def test_verify_checksum_failed(fake_download: pathlib.Path) -> None:
    pytest.raises(RelenvException, verify_checksum, fake_download, "no")
