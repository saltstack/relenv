# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
import hashlib
import logging
import pathlib

import pytest

from relenv.build.common import Dirs, get_dependency_version
from relenv.build.common.builder import Builder
from relenv.build.common.download import Download, verify_checksum
from relenv.build.common.ui import (
    BuildStats,
    LineCountHandler,
    load_build_stats,
    save_build_stats,
    update_build_stats,
)
from relenv.common import DATA_DIR, RelenvException, toolchain_root_dir, work_dirs

# mypy: ignore-errors


@pytest.fixture
def fake_download(tmp_path: pathlib.Path) -> pathlib.Path:
    download = tmp_path / "fake_download"
    download.write_text("This is some file contents")
    return download


@pytest.fixture
def fake_download_md5(fake_download: pathlib.Path) -> str:
    return hashlib.sha1(fake_download.read_bytes()).hexdigest()


@pytest.fixture
def fake_download_sha256(fake_download: pathlib.Path) -> str:
    return hashlib.sha256(fake_download.read_bytes()).hexdigest()


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
    import relenv.common

    call_count = {"count": 0}

    def mock_get_toolchain(arch=None, root=None):
        call_count["count"] += 1
        # Return a fake path instead of actually extracting
        return pathlib.Path(f"/fake/toolchain/{arch or 'default'}")

    # Patch where get_toolchain is actually imported and used (in relenv.common)
    monkeypatch.setattr(relenv.common, "get_toolchain", mock_get_toolchain)

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


def test_verify_checksum_sha256(
    fake_download: pathlib.Path, fake_download_sha256: str
) -> None:
    """Test SHA-256 checksum validation."""
    assert verify_checksum(fake_download, fake_download_sha256) is True


def test_verify_checksum_failed(fake_download: pathlib.Path) -> None:
    pytest.raises(RelenvException, verify_checksum, fake_download, "no")


def test_verify_checksum_none(fake_download: pathlib.Path) -> None:
    """Test that verify_checksum returns False when checksum is None."""
    assert verify_checksum(fake_download, None) is False


def test_verify_checksum_invalid_length(fake_download: pathlib.Path) -> None:
    """Test that invalid checksum length raises error."""
    with pytest.raises(RelenvException, match="Invalid checksum length"):
        verify_checksum(fake_download, "abc123")  # 6 chars, not 40 or 64


def test_get_dependency_version_openssl_linux() -> None:
    """Test getting OpenSSL version for Linux platform."""
    result = get_dependency_version("openssl", "linux")
    assert result is not None
    assert isinstance(result, dict)
    assert "version" in result
    assert "url" in result
    assert "sha256" in result
    assert isinstance(result["version"], str)
    assert "openssl" in result["url"].lower()
    assert "{version}" in result["url"]
    assert isinstance(result["sha256"], str)


def test_get_dependency_version_sqlite_all_platforms() -> None:
    """Test getting SQLite version for various platforms."""
    for platform in ["linux", "darwin", "win32"]:
        result = get_dependency_version("sqlite", platform)
        assert result is not None, f"SQLite should be available for {platform}"
        assert isinstance(result, dict)
        assert "version" in result
        assert "url" in result
        assert "sha256" in result
        assert "sqliteversion" in result, "SQLite should have sqliteversion field"
        assert isinstance(result["version"], str)
        assert "sqlite" in result["url"].lower()
        assert isinstance(result["sha256"], str)


def test_get_dependency_version_xz_all_platforms() -> None:
    """Test getting XZ version for various platforms."""
    # XZ 5.5.0+ removed MSBuild support, so Windows uses a fallback version
    # BUT we now have XZ 5.8.2 in python-versions.json for win32 too
    for platform in ["linux", "darwin", "win32"]:
        result = get_dependency_version("xz", platform)
        assert result is not None, f"XZ should be available for {platform}"
        assert isinstance(result, dict)
        assert "version" in result
        assert "url" in result
        assert "sha256" in result
        assert isinstance(result["version"], str)
        assert "xz" in result["url"].lower()
        assert isinstance(result["sha256"], str)


def test_get_dependency_version_nonexistent() -> None:
    """Test that nonexistent dependency returns None."""
    result = get_dependency_version("nonexistent-dep", "linux")
    assert result is None


def test_get_dependency_version_wrong_platform() -> None:
    """Test that requesting unsupported platform returns None."""
    # Try to get OpenSSL for a platform that doesn't exist
    result = get_dependency_version("openssl", "nonexistent-platform")
    assert result is None


# Build stats tests


def test_build_stats_save_load(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test saving and loading build statistics."""
    monkeypatch.setattr("relenv.build.common.ui.DATA_DIR", tmp_path)

    # Save some stats
    stats = {
        "python": BuildStats(avg_lines=100, samples=1, last_lines=100),
        "openssl": BuildStats(avg_lines=200, samples=2, last_lines=180),
    }
    save_build_stats(stats)

    # Load them back
    loaded = load_build_stats()
    assert loaded["python"]["avg_lines"] == 100
    assert loaded["python"]["samples"] == 1
    assert loaded["python"]["last_lines"] == 100
    assert loaded["openssl"]["avg_lines"] == 200
    assert loaded["openssl"]["samples"] == 2


def test_build_stats_load_nonexistent(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test loading stats when file doesn't exist returns empty dict."""
    monkeypatch.setattr("relenv.build.common.ui.DATA_DIR", tmp_path)
    loaded = load_build_stats()
    assert loaded == {}


def test_build_stats_update_new_step(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test updating stats for a new build step."""
    monkeypatch.setattr("relenv.build.common.ui.DATA_DIR", tmp_path)

    # Update a new step
    update_build_stats("python", 100)

    # Load and verify
    stats = load_build_stats()
    assert stats["python"]["avg_lines"] == 100
    assert stats["python"]["samples"] == 1
    assert stats["python"]["last_lines"] == 100


def test_build_stats_update_existing_step(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test updating stats for an existing step uses exponential moving average."""
    monkeypatch.setattr("relenv.build.common.ui.DATA_DIR", tmp_path)

    # Initial value
    update_build_stats("python", 100)

    # Update with new value
    update_build_stats("python", 200)

    # Load and verify exponential moving average: 0.7 * 200 + 0.3 * 100 = 170
    stats = load_build_stats()
    assert stats["python"]["avg_lines"] == 170
    assert stats["python"]["samples"] == 2
    assert stats["python"]["last_lines"] == 200


# LineCountHandler tests


def test_line_count_handler() -> None:
    """Test LineCountHandler increments shared dict correctly."""
    shared_dict = {}
    handler = LineCountHandler("test", shared_dict)

    # Create a log record
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )

    # Emit first record
    handler.emit(record)
    assert shared_dict["test"] == 1

    # Emit second record
    handler.emit(record)
    assert shared_dict["test"] == 2

    # Emit third record
    handler.emit(record)
    assert shared_dict["test"] == 3


def test_line_count_handler_multiple_steps() -> None:
    """Test LineCountHandler tracks multiple steps independently."""
    shared_dict = {}
    handler1 = LineCountHandler("step1", shared_dict)
    handler2 = LineCountHandler("step2", shared_dict)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )

    handler1.emit(record)
    handler1.emit(record)
    handler2.emit(record)

    assert shared_dict["step1"] == 2
    assert shared_dict["step2"] == 1


# Dirs class tests


@pytest.mark.skip_unless_on_linux
def test_dirs_initialization() -> None:
    """Test Dirs class initialization."""
    dirs = Dirs(work_dirs(), "python", "x86_64", "3.10.0")
    assert dirs.name == "python"
    assert dirs.arch == "x86_64"
    assert dirs.version == "3.10.0"
    assert "python_build" in dirs.tmpbuild


def test_dirs_triplet_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Dirs._triplet property for darwin platform."""
    monkeypatch.setattr("sys.platform", "darwin")
    dirs = Dirs(work_dirs(), "test", "arm64", "3.10.0")
    assert dirs._triplet == "arm64-macos"


def test_dirs_triplet_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Dirs._triplet property for win32 platform."""
    monkeypatch.setattr("sys.platform", "win32")
    dirs = Dirs(work_dirs(), "test", "amd64", "3.10.0")
    assert dirs._triplet == "amd64-win"


@pytest.mark.skip_unless_on_linux
def test_dirs_triplet_linux() -> None:
    """Test Dirs._triplet property for linux platform."""
    dirs = Dirs(work_dirs(), "test", "x86_64", "3.10.0")
    assert dirs._triplet == "x86_64-linux-gnu"


@pytest.mark.skip_unless_on_linux
def test_dirs_prefix() -> None:
    """Test Dirs.prefix property."""
    dirs = Dirs(work_dirs(), "test", "x86_64", "3.10.0")
    assert "3.10.0-x86_64-linux-gnu" in str(dirs.prefix)


@pytest.mark.skip_unless_on_linux
def test_dirs_to_dict() -> None:
    """Test Dirs.to_dict() method."""
    dirs = Dirs(work_dirs(), "test", "x86_64", "3.10.0")
    d = dirs.to_dict()
    assert "root" in d
    assert "prefix" in d
    assert "downloads" in d
    assert "logs" in d
    assert "sources" in d
    assert "build" in d
    assert "toolchain" in d


@pytest.mark.skip_unless_on_linux
def test_dirs_pickle() -> None:
    """Test Dirs serialization/deserialization."""
    dirs = Dirs(work_dirs(), "python", "x86_64", "3.10.0")

    # Get state
    state = dirs.__getstate__()
    assert state["name"] == "python"
    assert state["arch"] == "x86_64"

    # Create new instance and restore state
    dirs2 = Dirs.__new__(Dirs)
    dirs2.__setstate__(state)
    assert dirs2.name == "python"
    assert dirs2.arch == "x86_64"
    assert dirs2.tmpbuild == dirs.tmpbuild


# Download class tests


def test_download_copy() -> None:
    """Test Download.copy() creates independent copy."""
    d1 = Download(
        "test",
        "http://example.com/{version}/test.tar.gz",
        version="1.0.0",
        checksum="abc123",
    )
    d2 = d1.copy()

    # Verify copy has same values
    assert d2.name == d1.name
    assert d2.url_tpl == d1.url_tpl
    assert d2.version == d1.version
    assert d2.checksum == d1.checksum

    # Verify it's a different object
    assert d2 is not d1

    # Verify modifying copy doesn't affect original
    d2.version = "2.0.0"
    assert d1.version == "1.0.0"
    assert d2.version == "2.0.0"


def test_download_fallback_url() -> None:
    """Test Download.fallback_url property."""
    d = Download(
        "test",
        "http://main.com/{version}/test.tar.gz",
        fallback_url="http://backup.com/{version}/test.tar.gz",
        version="1.0.0",
    )
    assert d.fallback_url == "http://backup.com/1.0.0/test.tar.gz"


def test_download_no_fallback() -> None:
    """Test Download.fallback_url returns None when not configured."""
    d = Download("test", "http://example.com/{version}/test.tar.gz", version="1.0.0")
    assert d.fallback_url is None


def test_download_signature_url() -> None:
    """Test Download.signature_url property."""
    d = Download(
        "test",
        "http://example.com/{version}/test.tar.gz",
        signature="http://example.com/{version}/test.tar.gz.asc",
        version="1.0.0",
    )
    assert d.signature_url == "http://example.com/1.0.0/test.tar.gz.asc"


def test_download_signature_url_error() -> None:
    """Test Download.signature_url raises error when not configured."""
    from relenv.common import ConfigurationError

    d = Download("test", "http://example.com/test.tar.gz")
    with pytest.raises(ConfigurationError, match="Signature template not configured"):
        _ = d.signature_url


def test_download_destination_setter() -> None:
    """Test Download.destination setter with None value."""
    d = Download("test", "http://example.com/test.tar.gz")

    # Set to a path
    d.destination = "/tmp/downloads"
    assert d.destination == pathlib.Path("/tmp/downloads")

    # Set to None
    d.destination = None
    assert d.destination == pathlib.Path()
