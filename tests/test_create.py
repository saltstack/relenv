# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
import os
import pathlib
import tarfile
from unittest.mock import patch

import pytest

from relenv.common import arches
from relenv.create import CreateException, chdir, create


def test_chdir(tmp_path: pathlib.Path) -> None:
    with chdir(str(tmp_path)):
        assert pathlib.Path(os.getcwd()) == tmp_path


def test_create(tmp_path: pathlib.Path) -> None:
    to_be_archived = tmp_path / "to_be_archived"
    to_be_archived.mkdir()
    test_file = to_be_archived / "testfile"
    test_file.touch()
    tar_file = tmp_path / "fake_archive"
    with tarfile.open(str(tar_file), "w:xz") as tar:
        tar.add(str(to_be_archived), to_be_archived.name)

    with patch("relenv.create.archived_build", return_value=tar_file):
        create("foo", dest=tmp_path)

    to_dir = tmp_path / "foo"
    assert (to_dir).exists()
    assert (to_dir / to_be_archived.name / test_file.name) in to_dir.glob("**/*")


def test_create_tar_doesnt_exist(tmp_path: pathlib.Path) -> None:
    tar_file = tmp_path / "fake_archive"
    with patch("relenv.create.archived_build", return_value=tar_file):
        with pytest.raises(CreateException):
            create("foo", dest=tmp_path)


def test_create_directory_exists(tmp_path: pathlib.Path) -> None:
    (tmp_path / "foo").mkdir()
    with pytest.raises(CreateException):
        create("foo", dest=tmp_path)


def test_create_arches_directory_exists(tmp_path: pathlib.Path) -> None:
    mocked_arches: dict[str, list[str]] = {key: [] for key in arches.keys()}
    with patch("relenv.create.arches", mocked_arches):
        with pytest.raises(CreateException):
            create("foo", dest=tmp_path)


def test_create_with_minor_version(tmp_path: pathlib.Path) -> None:
    """Test that minor version (e.g., '3.12') resolves to latest micro version."""
    import argparse
    import sys

    from relenv.create import main
    from relenv.pyversions import Version

    # Mock python_versions to return some test versions
    all_versions = {
        Version("3.11.5"): "aaa111",
        Version("3.12.5"): "abc123",
        Version("3.12.6"): "def456",
        Version("3.12.7"): "ghi789",
        Version("3.13.1"): "zzz999",
    }

    def mock_python_versions(minor: str | None = None) -> dict[Version, str]:
        """Mock that filters versions by minor version like the real function."""
        if minor is None:
            return all_versions
        # Filter versions matching the minor version
        mv = Version(minor)
        return {
            v: h
            for v, h in all_versions.items()
            if v.major == mv.major and v.minor == mv.minor
        }

    # Create a fake archive
    to_be_archived = tmp_path / "to_be_archived"
    to_be_archived.mkdir()
    test_file = to_be_archived / "testfile"
    test_file.touch()
    tar_file = tmp_path / "fake_archive"
    with tarfile.open(str(tar_file), "w:xz") as tar:
        tar.add(str(to_be_archived), to_be_archived.name)

    # Use appropriate architecture for the platform
    test_arch = "amd64" if sys.platform == "win32" else "x86_64"
    args = argparse.Namespace(name="test_env", arch=test_arch, python="3.12")

    with chdir(str(tmp_path)):
        with patch("relenv.create.python_versions", side_effect=mock_python_versions):
            with patch("relenv.create.archived_build", return_value=tar_file):
                with patch("relenv.create.build_arch", return_value=test_arch):
                    main(args)

    to_dir = tmp_path / "test_env"
    assert to_dir.exists()


def test_create_with_full_version(tmp_path: pathlib.Path) -> None:
    """Test that full version (e.g., '3.12.7') still works."""
    import argparse
    import sys

    from relenv.create import main
    from relenv.pyversions import Version

    # Mock python_versions to return some test versions
    all_versions = {
        Version("3.11.5"): "aaa111",
        Version("3.12.5"): "abc123",
        Version("3.12.6"): "def456",
        Version("3.12.7"): "ghi789",
        Version("3.13.1"): "zzz999",
    }

    def mock_python_versions(minor: str | None = None) -> dict[Version, str]:
        """Mock that filters versions by minor version like the real function."""
        if minor is None:
            return all_versions
        # Filter versions matching the minor version
        mv = Version(minor)
        return {
            v: h
            for v, h in all_versions.items()
            if v.major == mv.major and v.minor == mv.minor
        }

    # Create a fake archive
    to_be_archived = tmp_path / "to_be_archived"
    to_be_archived.mkdir()
    test_file = to_be_archived / "testfile"
    test_file.touch()
    tar_file = tmp_path / "fake_archive"
    with tarfile.open(str(tar_file), "w:xz") as tar:
        tar.add(str(to_be_archived), to_be_archived.name)

    # Use appropriate architecture for the platform
    test_arch = "amd64" if sys.platform == "win32" else "x86_64"
    args = argparse.Namespace(name="test_env", arch=test_arch, python="3.12.7")

    with chdir(str(tmp_path)):
        with patch("relenv.create.python_versions", side_effect=mock_python_versions):
            with patch("relenv.create.archived_build", return_value=tar_file):
                with patch("relenv.create.build_arch", return_value=test_arch):
                    main(args)

    to_dir = tmp_path / "test_env"
    assert to_dir.exists()


def test_create_with_unknown_minor_version(tmp_path: pathlib.Path) -> None:
    """Test that unknown minor version produces an error."""
    import argparse
    import sys

    from relenv.create import main
    from relenv.pyversions import Version

    # Mock python_versions to return empty dict for unknown version
    all_versions = {
        Version("3.11.5"): "aaa111",
        Version("3.12.5"): "abc123",
        Version("3.12.6"): "def456",
        Version("3.12.7"): "ghi789",
        Version("3.13.1"): "zzz999",
    }

    # Use appropriate architecture for the platform
    test_arch = "amd64" if sys.platform == "win32" else "x86_64"
    args = argparse.Namespace(name="test_env", arch=test_arch, python="3.99")

    def mock_python_versions(minor: str | None = None) -> dict[Version, str]:
        """Mock that filters versions by minor version like the real function."""
        if minor is None:
            return all_versions
        # Filter versions matching the minor version
        mv = Version(minor)
        return {
            v: h
            for v, h in all_versions.items()
            if v.major == mv.major and v.minor == mv.minor
        }

    with patch("relenv.create.python_versions", side_effect=mock_python_versions):
        with patch("relenv.create.build_arch", return_value=test_arch):
            with pytest.raises(SystemExit):
                main(args)
