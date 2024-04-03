# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tarfile
from unittest.mock import patch

import pytest

from relenv.common import (
    MODULE_DIR,
    SHEBANG_TPL_LINUX,
    SHEBANG_TPL_MACOS,
    RelenvException,
    archived_build,
    extract_archive,
    format_shebang,
    get_download_location,
    get_toolchain,
    get_triplet,
    relative_interpreter,
    runcmd,
    sanitize_sys_path,
    work_dir,
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
        pytest.fail(f"Do not know how to test for '{plat}' platform")


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
    ret = runcmd(["echo", "foo"])
    assert ret.returncode == 0


def test_runcmd_fail():
    with pytest.raises(RelenvException):
        runcmd([sys.executable, "-c", "import sys;sys.exit(1)"])


def test_work_dir_with_root_module_dir():
    ret = work_dir("fakedir")
    assert ret == MODULE_DIR / "_fakedir"


def test_work_dir_with_root_given(tmp_path):
    ret = work_dir("fakedir", root=tmp_path)
    assert ret == tmp_path / "fakedir"


def test_get_toolchain(tmp_path):
    data_dir = tmp_path / "data"
    with patch("relenv.common.DATA_DIR", data_dir):
        ret = get_toolchain(arch="aarch64")
        assert ret == data_dir / "toolchain" / "aarch64-linux-gnu"


def test_get_toolchain_no_arch(tmp_path):
    data_dir = tmp_path / "data"
    with patch("relenv.common.DATA_DIR", data_dir):
        ret = get_toolchain()
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
    extract_archive(str(to_dir), str(tar_file))
    assert to_dir.exists()
    assert (to_dir / to_be_archived.name / test_file.name) in to_dir.glob("**/*")


def test_get_download_location(tmp_path):
    url = "https://test.com/1.0.0/test-1.0.0.tar.xz"
    loc = get_download_location(url, str(tmp_path))
    assert loc == str(tmp_path / "test-1.0.0.tar.xz")


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="Test needs shellcheck")
def test_shebang_tpl_linux():
    sh = format_shebang("python3", SHEBANG_TPL_LINUX).split("'''")[1].strip("'")
    proc = subprocess.Popen(["shellcheck", "-s", "sh", "-"], stdin=subprocess.PIPE)
    proc.stdin.write(sh.encode())
    proc.communicate()
    assert proc.returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="Test needs shellcheck")
def test_shebang_tpl_macos():
    sh = format_shebang("python3", SHEBANG_TPL_MACOS).split("'''")[1].strip("'")
    proc = subprocess.Popen(["shellcheck", "-s", "sh", "-"], stdin=subprocess.PIPE)
    proc.stdin.write(sh.encode())
    proc.communicate()
    assert proc.returncode == 0


def test_relative_interpreter_default_location():
    assert relative_interpreter(
        "/tmp/relenv", "/tmp/relenv/bin", "/tmp/relenv/bin/python3"
    ) == pathlib.Path("..", "bin", "python3")


def test_relative_interpreter_pip_dir_location():
    assert relative_interpreter(
        "/tmp/relenv", "/tmp/relenv", "/tmp/relenv/bin/python3"
    ) == pathlib.Path("bin", "python3")


def test_relative_interpreter_alternate_location():
    assert relative_interpreter(
        "/tmp/relenv", "/tmp/relenv/bar/bin", "/tmp/relenv/bin/python3"
    ) == pathlib.Path("..", "..", "bin", "python3")


def test_relative_interpreter_interpreter_not_relative_to_root():
    with pytest.raises(ValueError):
        relative_interpreter("/tmp/relenv", "/tmp/relenv/bar/bin", "/tmp/bin/python3")


def test_relative_interpreter_scripts_not_relative_to_root():
    with pytest.raises(ValueError):
        relative_interpreter("/tmp/relenv", "/tmp/bar/bin", "/tmp/relenv/bin/python3")


def test_sanitize_sys_path():
    if sys.platform.startswith("win"):
        path_prefix = "C:\\"
        separator = "\\"
    else:
        path_prefix = "/"
        separator = "/"
    python_path_entries = [
        f"{path_prefix}blah{separator}blah",
        f"{path_prefix}yada{separator}yada",
    ]
    expected = [
        f"{path_prefix}foo{separator}1",
        f"{path_prefix}bar{separator}2",
    ] + python_path_entries
    sys_path = [
        f"{path_prefix}foo{separator}1",
        f"{path_prefix}bar{separator}2",
        f"{path_prefix}lib{separator}3",
    ]
    with patch.object(sys, "prefix", f"{path_prefix}foo"), patch.object(
        sys, "base_prefix", f"{path_prefix}bar"
    ), patch.dict(os.environ, PYTHONPATH=os.pathsep.join(python_path_entries)):
        new_sys_path = sanitize_sys_path(sys_path)
        assert new_sys_path != sys_path
        assert new_sys_path == expected
