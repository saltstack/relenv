# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
import pathlib
import pickle
import platform
import shutil
import subprocess
import sys
import tarfile
from types import ModuleType
from typing import BinaryIO, Literal
from unittest.mock import patch

import pytest

import relenv.common
from relenv.common import (
    MODULE_DIR,
    SHEBANG_TPL_LINUX,
    SHEBANG_TPL_MACOS,
    RelenvException,
    Version,
    addpackage,
    archived_build,
    download_url,
    extract_archive,
    format_shebang,
    get_download_location,
    get_toolchain,
    get_triplet,
    list_archived_builds,
    makepath,
    relative_interpreter,
    runcmd,
    sanitize_sys_path,
    work_dir,
    work_dirs,
    work_root,
)
from tests._pytest_typing import mark_skipif, parametrize


def _mock_ppbt_module(
    monkeypatch: pytest.MonkeyPatch, triplet: str, archive_path: pathlib.Path
) -> None:
    """
    Provide a lightweight ppbt.common stub so get_toolchain() skips the real extraction.
    """
    stub_package = ModuleType("ppbt")
    stub_common = ModuleType("ppbt.common")
    setattr(stub_package, "common", stub_common)

    # pytest will clean these entries up automatically via monkeypatch
    monkeypatch.setitem(sys.modules, "ppbt", stub_package)
    monkeypatch.setitem(sys.modules, "ppbt.common", stub_common)

    setattr(stub_common, "ARCHIVE", archive_path)

    def fake_extract_archive(dest: str, archive: str) -> None:
        dest_path = pathlib.Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        (dest_path / triplet).mkdir(parents=True, exist_ok=True)

    setattr(stub_common, "extract_archive", fake_extract_archive)


def test_get_triplet_linux() -> None:
    assert get_triplet("aarch64", "linux") == "aarch64-linux-gnu"


def test_get_triplet_darwin() -> None:
    assert get_triplet("x86_64", "darwin") == "x86_64-macos"


def test_get_triplet_windows() -> None:
    assert get_triplet("amd64", "win32") == "amd64-win"


def test_get_triplet_default() -> None:
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


def test_get_triplet_unknown() -> None:
    with pytest.raises(RelenvException):
        get_triplet("aarch64", "oijfsdf")


def test_archived_build() -> None:
    dirs = work_dirs()
    build = archived_build()
    try:
        _ = build.relative_to(dirs.build)
    except ValueError:
        pytest.fail("Archived build value not relative to build dir")


def test_work_root_when_passed_relative_path() -> None:
    name = "foo"
    assert work_root(name) == pathlib.Path(name).resolve()


def test_work_root_when_passed_full_path() -> None:
    name = "/foo/bar"
    if sys.platform == "win32":
        name = "D:/foo/bar"
    assert work_root(name) == pathlib.Path(name)


def test_work_root_when_nothing_passed() -> None:
    assert work_root() == MODULE_DIR


def test_work_dirs_attributes() -> None:
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


def test_runcmd_success() -> None:
    ret = runcmd(["echo", "foo"])
    assert ret.returncode == 0


def test_runcmd_fail() -> None:
    with pytest.raises(RelenvException):
        runcmd([sys.executable, "-c", "import sys;sys.exit(1)"])


def test_work_dir_with_root_module_dir() -> None:
    ret = work_dir("fakedir")
    assert ret == MODULE_DIR / "_fakedir"


def test_work_dir_with_root_given(tmp_path: pathlib.Path) -> None:
    ret = work_dir("fakedir", root=tmp_path)
    assert ret == tmp_path / "fakedir"


def test_get_toolchain(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    triplet = "aarch64-linux-gnu"
    monkeypatch.setattr(relenv.common, "DATA_DIR", data_dir, raising=False)
    monkeypatch.setattr(relenv.common.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        relenv.common, "get_triplet", lambda machine=None, plat=None: triplet
    )
    monkeypatch.setenv("RELENV_TOOLCHAIN_CACHE", str(data_dir / "toolchain"))
    archive_path = tmp_path / "dummy-toolchain.tar.xz"
    archive_path.write_bytes(b"")
    _mock_ppbt_module(monkeypatch, triplet, archive_path)
    ret = get_toolchain(arch="aarch64")
    assert ret == data_dir / "toolchain" / triplet


def test_get_toolchain_linux_existing(tmp_path: pathlib.Path) -> None:
    data_dir = tmp_path / "data"
    triplet = "x86_64-linux-gnu"
    toolchain_path = data_dir / "toolchain" / triplet
    toolchain_path.mkdir(parents=True)
    with patch("relenv.common.DATA_DIR", data_dir), patch(
        "relenv.common.sys.platform", "linux"
    ), patch("relenv.common.get_triplet", return_value=triplet), patch.dict(
        os.environ,
        {"RELENV_TOOLCHAIN_CACHE": str(data_dir / "toolchain")},
    ):
        ret = get_toolchain()
    assert ret == toolchain_path


def test_get_toolchain_no_arch(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    triplet = "x86_64-linux-gnu"
    monkeypatch.setattr(relenv.common, "DATA_DIR", data_dir, raising=False)
    monkeypatch.setattr(relenv.common.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        relenv.common, "get_triplet", lambda machine=None, plat=None: triplet
    )
    monkeypatch.setenv("RELENV_TOOLCHAIN_CACHE", str(data_dir / "toolchain"))
    archive_path = tmp_path / "dummy-toolchain.tar.xz"
    archive_path.write_bytes(b"")
    _mock_ppbt_module(monkeypatch, triplet, archive_path)
    ret = get_toolchain()
    assert ret == data_dir / "toolchain" / triplet


WriteMode = Literal["w:gz", "w:xz", "w:bz2", "w"]


@parametrize(
    ("suffix", "mode"),
    (
        (".tgz", "w:gz"),
        (".tar.gz", "w:gz"),
        (".tar.xz", "w:xz"),
        (".tar.bz2", "w:bz2"),
        (".tar", "w"),
    ),
)
def test_extract_archive(tmp_path: pathlib.Path, suffix: str, mode: WriteMode) -> None:
    to_be_archived = tmp_path / "to_be_archived"
    to_be_archived.mkdir()
    test_file = to_be_archived / "testfile"
    test_file.touch()
    tar_file = tmp_path / f"fake_archive{suffix}"
    to_dir = tmp_path / "extracted"
    with tarfile.open(str(tar_file), mode=mode) as tar:
        tar.add(str(to_be_archived), to_be_archived.name)
    extract_archive(str(to_dir), str(tar_file))
    assert to_dir.exists()
    assert (to_dir / to_be_archived.name / test_file.name) in to_dir.glob("**/*")


def test_get_download_location(tmp_path: pathlib.Path) -> None:
    url = "https://test.com/1.0.0/test-1.0.0.tar.xz"
    loc = get_download_location(url, str(tmp_path))
    assert loc == str(tmp_path / "test-1.0.0.tar.xz")


def test_download_url_writes_file(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "downloads"
    dest.mkdir()
    data = b"payload"

    def fake_fetch(url: str, fp: BinaryIO, backoff: int, timeout: float) -> None:
        fp.write(data)

    with patch("relenv.common.fetch_url", side_effect=fake_fetch):
        path = download_url("https://example.com/a.txt", dest)

    assert pathlib.Path(path).read_bytes() == data


def test_download_url_failure_cleans_up(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "downloads"
    dest.mkdir()
    created = dest / "a.txt"

    def fake_fetch(url: str, fp: BinaryIO, backoff: int, timeout: float) -> None:
        raise RelenvException("fail")

    with patch("relenv.common.get_download_location", return_value=str(created)), patch(
        "relenv.common.fetch_url", side_effect=fake_fetch
    ), patch("relenv.common.log") as log_mock:
        with pytest.raises(RelenvException):
            download_url("https://example.com/a.txt", dest)
        log_mock.error.assert_called()
    assert not created.exists()


def _extract_shell_snippet(tpl: str) -> str:
    rendered = format_shebang("python3", tpl)
    lines = rendered.splitlines()[1:]  # skip #!/bin/sh
    snippet: list[str] = []
    for line in lines:
        if line.startswith("'''"):
            break
        snippet.append(line)
    return "\n".join(snippet)


@mark_skipif(shutil.which("shellcheck") is None, reason="Test needs shellcheck")
def test_shebang_tpl_linux() -> None:
    sh = _extract_shell_snippet(SHEBANG_TPL_LINUX)
    proc = subprocess.Popen(["shellcheck", "-s", "sh", "-"], stdin=subprocess.PIPE)
    assert proc.stdin is not None
    proc.stdin.write(sh.encode())
    proc.communicate()
    assert proc.returncode == 0


@mark_skipif(shutil.which("shellcheck") is None, reason="Test needs shellcheck")
def test_shebang_tpl_macos() -> None:
    sh = _extract_shell_snippet(SHEBANG_TPL_MACOS)
    proc = subprocess.Popen(["shellcheck", "-s", "sh", "-"], stdin=subprocess.PIPE)
    assert proc.stdin is not None
    proc.stdin.write(sh.encode())
    proc.communicate()
    assert proc.returncode == 0


def test_format_shebang_newline() -> None:
    assert format_shebang("python3", SHEBANG_TPL_LINUX).endswith("\n")


def test_relative_interpreter_default_location() -> None:
    assert relative_interpreter(
        "/tmp/relenv", "/tmp/relenv/bin", "/tmp/relenv/bin/python3"
    ) == pathlib.Path("..", "bin", "python3")


def test_relative_interpreter_pip_dir_location() -> None:
    assert relative_interpreter(
        "/tmp/relenv", "/tmp/relenv", "/tmp/relenv/bin/python3"
    ) == pathlib.Path("bin", "python3")


def test_relative_interpreter_alternate_location() -> None:
    assert relative_interpreter(
        "/tmp/relenv", "/tmp/relenv/bar/bin", "/tmp/relenv/bin/python3"
    ) == pathlib.Path("..", "..", "bin", "python3")


def test_relative_interpreter_interpreter_not_relative_to_root() -> None:
    with pytest.raises(ValueError):
        relative_interpreter("/tmp/relenv", "/tmp/relenv/bar/bin", "/tmp/bin/python3")


def test_relative_interpreter_scripts_not_relative_to_root() -> None:
    with pytest.raises(ValueError):
        relative_interpreter("/tmp/relenv", "/tmp/bar/bin", "/tmp/relenv/bin/python3")


def test_sanitize_sys_path() -> None:
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


def test_version_parse_and_str() -> None:
    version = Version("3.10.4")
    assert version.major == 3
    assert version.minor == 10
    assert version.micro == 4
    assert str(version) == "3.10.4"


def test_version_equality_and_hash_handles_missing_parts() -> None:
    left = Version("3.10")
    right = Version("3.10.0")
    assert left == right
    assert isinstance(hash(left), int)
    assert isinstance(hash(right), int)


def test_version_comparisons() -> None:
    assert Version("3.9") < Version("3.10")
    assert Version("3.10.1") > Version("3.10.0")
    assert Version("3.11") >= Version("3.11.0")
    assert Version("3.12.2") <= Version("3.12.2")


def test_version_parse_string_too_many_parts() -> None:
    with pytest.raises(RuntimeError):
        Version.parse_string("1.2.3.4")


def test_work_dirs_pickle_roundtrip(tmp_path: pathlib.Path) -> None:
    data_dir = tmp_path / "data"
    with patch("relenv.common.DATA_DIR", data_dir):
        dirs = work_dirs(tmp_path)
        restored = pickle.loads(pickle.dumps(dirs))
    assert restored.root == dirs.root
    assert restored.toolchain == dirs.toolchain
    assert restored.download == dirs.download


def test_work_dirs_with_data_dir_root(tmp_path: pathlib.Path) -> None:
    data_dir = tmp_path / "data"
    with patch("relenv.common.DATA_DIR", data_dir):
        dirs = work_dirs(data_dir)
    assert dirs.build == data_dir / "build"
    assert dirs.logs == data_dir / "logs"


def test_list_archived_builds(tmp_path: pathlib.Path) -> None:
    data_dir = tmp_path / "data"
    build_dir = data_dir / "build"
    build_dir.mkdir(parents=True)
    archive = build_dir / "3.10.0-x86_64-linux-gnu.tar.xz"
    archive.write_bytes(b"")
    with patch("relenv.common.DATA_DIR", data_dir):
        builds = list_archived_builds()
    assert ("3.10.0", "x86_64", "linux-gnu") in builds


def test_addpackage_reads_paths(tmp_path: pathlib.Path) -> None:
    sitedir = tmp_path
    module_dir = tmp_path / "package"
    module_dir.mkdir()
    pth_file = sitedir / "example.pth"
    pth_file.write_text(f"{module_dir.name}\n")
    result = addpackage(str(sitedir), pth_file.name)
    assert result == [str(module_dir.resolve())]


def test_sanitize_sys_path_with_editable_paths(tmp_path: pathlib.Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    known_path = base / "lib"
    known_path.mkdir()
    editable_file = known_path / "__editable__.demo.pth"
    editable_file.touch()
    extra_path = str(known_path / "extra")
    with patch.object(sys, "prefix", str(base)), patch.object(
        sys, "base_prefix", str(base)
    ), patch.dict(os.environ, {}, clear=True), patch(
        "relenv.common.addpackage", return_value=[extra_path]
    ):
        sanitized = sanitize_sys_path([str(known_path)])
    assert extra_path in sanitized


def test_makepath_oserror() -> None:
    with patch("relenv.common.os.path.abspath", side_effect=OSError):
        result, case = makepath("foo", "Bar")
    expected = os.path.join("foo", "Bar")
    assert result == expected
    assert case == os.path.normcase(expected)


def test_copyright_headers() -> None:
    """Verify all Python source files have the correct copyright header."""
    expected_header = (
        "# Copyright 2022-2025 Broadcom.\n" "# SPDX-License-Identifier: Apache-2.0\n"
    )

    # Find all Python files in relenv/ and tests/
    root = MODULE_DIR.parent
    python_files: list[pathlib.Path] = []
    for directory in ("relenv", "tests"):
        dir_path = root / directory
        if dir_path.exists():
            python_files.extend(dir_path.rglob("*.py"))

    # Skip generated and cache files
    python_files = [
        f
        for f in python_files
        if "__pycache__" not in f.parts
        and ".nox" not in f.parts
        and "build" not in f.parts
    ]

    failures = []
    for py_file in python_files:
        with open(py_file, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith(expected_header):
            # Read first two lines for error message
            lines = content.split("\n", 2)
            actual = "\n".join(lines[:2]) + "\n" if len(lines) >= 2 else content
            failures.append(f"{py_file.relative_to(root)}: {actual!r}")

    if failures:
        pytest.fail("Files with incorrect copyright headers:\n" + "\n".join(failures))
