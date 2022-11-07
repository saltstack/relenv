# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2
import pathlib
import platform
import sys
import tarfile
from unittest.mock import Mock, patch

import pytest

import relenv.common as common


def test_get_triplet_linux():
    assert common.get_triplet("aarch64", "linux") == "aarch64-linux-gnu"


def test_get_triplet_darwin():
    assert common.get_triplet("x86_64", "darwin") == "x86_64-macos"


def test_get_triplet_windows():
    assert common.get_triplet("amd64", "win32") == "amd64-win"


def test_get_triplet_default():
    machine = platform.machine().lower()
    plat = sys.platform
    if plat == "win32":
        assert common.get_triplet() == f"{machine}-win"
    elif plat == "darwin":
        assert common.get_triplet() == f"{machine}-macos"
    elif plat == "linux":
        assert common.get_triplet() == f"{machine}-linux-gnu"
    else:
        pytest.fail("Do not know how to test for '{}' platform".format(plat))


def test_get_triplet_unknown():
    with pytest.raises(common.RelenvException):
        common.get_triplet("aarch64", "oijfsdf")


def test_archived_build():
    dirs = common.work_dirs()
    build = common.archived_build()
    try:
        _ = build.relative_to(dirs.build)
    except ValueError:
        pytest.fail("Archived build value not relative to build dir")


def test_work_root_when_passed_relative_path():
    name = "foo"
    assert common.work_root(name) == pathlib.Path(name).resolve()


def test_work_root_when_passed_full_path():
    name = "/foo/bar"
    if sys.platform == "win32":
        name = "D:/foo/bar"
    assert common.work_root(name) == pathlib.Path(name)


def test_work_root_when_nothing_passed():
    assert common.work_root() == common.MODULE_DIR


def test_work_dirs_attributes():
    dirs = common.work_dirs()
    checkfor = [
        "root",
        "toolchain",
        "build",
        "src",
        "logs",
        "download",
    ]
    for attr in checkfor:
        assert hasattr(dirs, attr)


def test_runcmd_success():
    with patch("subprocess.run") as moc:
        ret = Mock()
        ret.returncode = 0
        moc.side_effect = [ret]
        _ = common.runcmd(["echo", "foo"])
        assert moc.called_with(["echo", "foo"])
        assert _ == ret


def test_runcmd_fail():
    with patch("subprocess.run") as moc:
        ret = Mock()
        ret.returncode = 1
        moc.side_effect = [ret]
        with pytest.raises(common.RelenvException):
            _ = common.runcmd(["echo", "foo"])


def test_verify_checksum():
    with patch("subprocess.run") as moc:
        ret = Mock()
        ret.returncode = 1
        moc.side_effect = [ret]
        with pytest.raises(common.RelenvException):
            _ = common.runcmd(["echo", "foo"])


def test_work_dir_with_root_module_dir():
    ret = common.work_dir("fakedir")
    assert ret == common.MODULE_DIR / "_fakedir"


def test_work_dir_with_root_given(tmp_path):
    ret = common.work_dir("fakedir", root=tmp_path)
    assert ret == tmp_path / "fakedir"


def test_get_toolchain(tmp_path):
    data_dir = tmp_path / "data"
    with patch.object(common, "DATA_DIR", data_dir):
        ret = common.get_toolchain(arch="aarch64")
        assert ret == data_dir / "toolchain" / "aarch64-linux-gnu"


def test_get_toolchain_no_arch(tmp_path):
    data_dir = tmp_path / "data"
    with patch.object(common, "DATA_DIR", data_dir):
        ret = common.get_toolchain()
        assert ret == data_dir / "toolchain"


@pytest.mark.parametrize("open_arg", (":gz", ":xz", ":bz2", ""))
def test_extract_archive(tmp_path, open_arg):
    to_be_archived = tmp_path / "to_be_archived"
    to_be_archived.mkdir()
    test_file = to_be_archived / "testfile"
    test_file.touch()
    tar_file = tmp_path / "fake_archive"
    to_dir = tmp_path / "extracted"
    with tarfile.open(str(tar_file), "w{}".format(open_arg)) as tar:
        tar.add(str(to_be_archived), to_be_archived.name)
    common.extract_archive(str(to_dir), str(tar_file))
    assert to_dir.exists()
    assert (to_dir / to_be_archived.name / test_file.name) in to_dir.glob("**/*")
