# Copyright 2022-2025 Broadcom.
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
