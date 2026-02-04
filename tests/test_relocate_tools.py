# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0

import pathlib
from typing import Iterator
from unittest.mock import patch

import pytest

from relenv import relocate


@pytest.fixture(autouse=True)  # type: ignore[misc]
def reset_globals() -> Iterator[None]:
    """Reset global caches in relocate module before and after each test."""
    relocate._READELF_BINARY = None
    relocate._PATCHELF_BINARY = None
    yield
    relocate._READELF_BINARY = None
    relocate._PATCHELF_BINARY = None


def test_get_readelf_binary_toolchain_exists(tmp_path: pathlib.Path) -> None:
    """Test that toolchain readelf is used when available."""
    toolchain_root = tmp_path / "toolchain"
    toolchain_root.mkdir()
    triplet = "x86_64-linux-gnu"

    # Create the fake toolchain binary
    bin_dir = toolchain_root / "bin"
    bin_dir.mkdir(parents=True)
    toolchain_readelf = bin_dir / f"{triplet}-readelf"
    toolchain_readelf.touch()

    with patch("relenv.relocate.sys.platform", "linux"):
        # We need to mock relenv.common.get_toolchain and get_triplet
        # Since they are imported inside the function, we can patch the module if it's already imported
        # or use patch.dict(sys.modules)

        # Ensure relenv.common is imported so we can patch it
        import relenv.common  # noqa: F401

        with patch("relenv.common.get_toolchain", return_value=toolchain_root):
            with patch("relenv.common.get_triplet", return_value=triplet):
                readelf = relocate._get_readelf_binary()

                assert readelf == str(toolchain_readelf)
                assert relocate._READELF_BINARY == str(toolchain_readelf)


def test_get_readelf_binary_toolchain_missing(tmp_path: pathlib.Path) -> None:
    """Test that system readelf is used when toolchain binary is missing."""
    toolchain_root = tmp_path / "toolchain"
    toolchain_root.mkdir()
    triplet = "x86_64-linux-gnu"

    # Do NOT create the binary

    with patch("relenv.relocate.sys.platform", "linux"):
        # Ensure relenv.common is imported so we can patch it
        import relenv.common  # noqa: F401

        with patch("relenv.common.get_toolchain", return_value=toolchain_root):
            with patch("relenv.common.get_triplet", return_value=triplet):
                readelf = relocate._get_readelf_binary()

                assert readelf == "readelf"
                assert relocate._READELF_BINARY == "readelf"


def test_get_readelf_binary_no_toolchain() -> None:
    """Test that system readelf is used when get_toolchain returns None."""
    with patch("relenv.relocate.sys.platform", "linux"):
        # Ensure relenv.common is imported so we can patch it
        import relenv.common  # noqa: F401

        with patch("relenv.common.get_toolchain", return_value=None):
            readelf = relocate._get_readelf_binary()

            assert readelf == "readelf"
            assert relocate._READELF_BINARY == "readelf"


def test_get_readelf_binary_not_linux() -> None:
    """Test that system readelf is used on non-Linux platforms."""
    with patch("relenv.relocate.sys.platform", "darwin"):
        readelf = relocate._get_readelf_binary()

        assert readelf == "readelf"
        assert relocate._READELF_BINARY == "readelf"


def test_get_patchelf_binary_toolchain_exists(tmp_path: pathlib.Path) -> None:
    """Test that toolchain patchelf is used when available."""
    toolchain_root = tmp_path / "toolchain"
    toolchain_root.mkdir()

    # Create the fake toolchain binary
    bin_dir = toolchain_root / "bin"
    bin_dir.mkdir(parents=True)
    toolchain_patchelf = bin_dir / "patchelf"
    toolchain_patchelf.touch()

    with patch("relenv.relocate.sys.platform", "linux"):
        # Ensure relenv.common is imported so we can patch it
        import relenv.common  # noqa: F401

        with patch("relenv.common.get_toolchain", return_value=toolchain_root):
            patchelf = relocate._get_patchelf_binary()

            assert patchelf == str(toolchain_patchelf)
            assert relocate._PATCHELF_BINARY == str(toolchain_patchelf)


def test_get_patchelf_binary_toolchain_missing(tmp_path: pathlib.Path) -> None:
    """Test that system patchelf is used when toolchain binary is missing."""
    toolchain_root = tmp_path / "toolchain"
    toolchain_root.mkdir()

    # Do NOT create the binary

    with patch("relenv.relocate.sys.platform", "linux"):
        # Ensure relenv.common is imported so we can patch it
        import relenv.common  # noqa: F401

        with patch("relenv.common.get_toolchain", return_value=toolchain_root):
            patchelf = relocate._get_patchelf_binary()

            assert patchelf == "patchelf"
            assert relocate._PATCHELF_BINARY == "patchelf"


def test_get_patchelf_binary_no_toolchain() -> None:
    """Test that system patchelf is used when get_toolchain returns None."""
    with patch("relenv.relocate.sys.platform", "linux"):
        # Ensure relenv.common is imported so we can patch it
        import relenv.common  # noqa: F401

        with patch("relenv.common.get_toolchain", return_value=None):
            patchelf = relocate._get_patchelf_binary()

            assert patchelf == "patchelf"
            assert relocate._PATCHELF_BINARY == "patchelf"


def test_get_patchelf_binary_not_linux() -> None:
    """Test that system patchelf is used on non-Linux platforms."""
    with patch("relenv.relocate.sys.platform", "darwin"):
        patchelf = relocate._get_patchelf_binary()

        assert patchelf == "patchelf"
        assert relocate._PATCHELF_BINARY == "patchelf"
