# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
#
import os
import pathlib
import tarfile
from unittest.mock import patch

import pytest

import relenv.create as create


def test_chdir(tmp_path):
    with create.chdir(str(tmp_path)):
        assert pathlib.Path(os.getcwd()) == tmp_path


def test_create(tmp_path):
    to_be_archived = tmp_path / "to_be_archived"
    to_be_archived.mkdir()
    test_file = to_be_archived / "testfile"
    test_file.touch()
    tar_file = tmp_path / "fake_archive"
    with tarfile.open(str(tar_file), "w:xz") as tar:
        tar.add(str(to_be_archived), to_be_archived.name)

    with patch.object(create, "archived_build", return_value=tar_file):
        create.create("foo", dest=tmp_path)

    to_dir = tmp_path / "foo"
    assert (to_dir).exists()
    assert (to_dir / to_be_archived.name / test_file.name) in to_dir.glob("**/*")


def test_create_tar_doesnt_exist(tmp_path):
    tar_file = tmp_path / "fake_archive"
    with patch.object(create, "archived_build", return_value=tar_file):
        with pytest.raises(create.CreateException):
            create.create("foo", dest=tmp_path)


def test_create_directory_exists(tmp_path):
    (tmp_path / "foo").mkdir()
    with pytest.raises(create.CreateException):
        create.create("foo", dest=tmp_path)


def test_create_directory_exists(tmp_path):
    mocked_arches = {key: [] for key in create.arches.keys()}
    with patch.object(create, "arches", mocked_arches):
        with pytest.raises(create.CreateException):
            create.create("foo", dest=tmp_path)
