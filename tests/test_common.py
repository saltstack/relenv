import pathlib
import platform
import sys
from unittest.mock import Mock, patch

import pytest

from relenv.common import (
    MODULE_DIR,
    RelenvException,
    archived_build,
    get_triplet,
    runcmd,
    work_dirs,
    work_root,
)


def test_get_triplet_linux():
    assert get_triplet("aarch64", "linux") == "aarch64-linux-gnu"


def test_get_triplet_darwin():
    assert get_triplet("x86_64", "darwin") == "x86_64-macos"


def test_get_triplet_windows():
    assert get_triplet("amd64", "win32") == "amd64-win"


def test_get_triplet_default():
    machine = platform.machine().lower()
    plat = sys.platform
    if plat == "win32":
        assert get_triplet() == f"{machine}-win"
    elif plat == "darwin":
        assert get_triplet() == f"{machine}-macos"
    elif plat == "linux":
        assert get_triplet() == f"{machine}-linux-gnu"
    else:
        pytest.fail("Do not know how to test for '{}' platform".format(plat))


def test_get_triplet_unknown():
    with pytest.raises(RelenvException):
        get_triplet("aarch64", "oijfsdf")


def test_archived_build():
    dirs = work_dirs()
    build = archived_build()
    try:
        _ = build.relative_to(dirs.build)
    except ValueError:
        pytest.fail("Archived build value not relative to build dir")


def test_work_root_when_passed_relative_path():
    name = "foo"
    assert work_root(name) == pathlib.Path(name).resolve()


def test_work_root_when_passed_full_path():
    name = "/foo/bar"
    if sys.platform == "win32":
        name = "D:/foo/bar"
    assert work_root(name) == pathlib.Path(name)


def test_work_root_when_nothing_passed():
    assert work_root() == MODULE_DIR


def test_work_dirs_attributes():
    dirs = work_dirs()
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
        _ = runcmd(["echo", "foo"])
        assert moc.called_with(["echo", "foo"])
        assert _ == ret


def test_runcmd_fail():
    with patch("subprocess.run") as moc:
        ret = Mock()
        ret.returncode = 1
        moc.side_effect = [ret]
        with pytest.raises(RelenvException):
            _ = runcmd(["echo", "foo"])


def test_verify_checksum():
    with patch("subprocess.run") as moc:
        ret = Mock()
        ret.returncode = 1
        moc.side_effect = [ret]
        with pytest.raises(RelenvException):
            _ = runcmd(["echo", "foo"])
