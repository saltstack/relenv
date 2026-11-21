# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
import pathlib
import shutil
from textwrap import dedent
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from relenv.relocate import (
    handle_elf,
    is_elf,
    is_in_dir,
    is_macho,
    main,
    parse_readelf_d,
    parse_readelf_d_needed,
    patch_rpath,
    remove_rpath,
)

pytestmark = [
    pytest.mark.skip_on_windows(reason="Relocate not used on windows"),
]


class BaseProject:
    def __init__(self, root_dir: pathlib.Path) -> None:
        self.root_dir = root_dir
        self.libs_dir = self.root_dir / "lib"

    def make_project(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.libs_dir.mkdir(parents=True, exist_ok=True)

    def destroy_project(self) -> None:
        # Make sure the project is torn down properly
        if self.root_dir.exists():
            shutil.rmtree(self.root_dir, ignore_errors=True)

    def add_file(
        self,
        name: str,
        contents: bytes | str,
        *relpath: str,
        binary: bool = False,
    ) -> pathlib.Path:
        file_path = (self.root_dir / pathlib.Path(*relpath) / name).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            data = contents if isinstance(contents, bytes) else contents.encode()
            file_path.write_bytes(data)
        else:
            text = contents.decode() if isinstance(contents, bytes) else contents
            file_path.write_text(text)
        return file_path

    def __enter__(self) -> "BaseProject":
        self.make_project()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.destroy_project()


class LinuxProject(BaseProject):
    def add_simple_elf(self, name: str, *relpath: str) -> pathlib.Path:
        return self.add_file(name, b"\x7f\x45\x4c\x46", *relpath, binary=True)


def test_is_macho_true(tmp_path: pathlib.Path) -> None:
    lib_path = tmp_path / "test.dylib"
    lib_path.write_bytes(b"\xcf\xfa\xed\xfe")
    assert is_macho(lib_path) is True


def test_is_macho_false(tmp_path: pathlib.Path) -> None:
    lib_path = tmp_path / "test.dylib"
    lib_path.write_bytes(b"\xcf\xfa\xed\xfa")
    assert is_macho(lib_path) is False


def test_is_macho_not_a_file(tmp_path: pathlib.Path) -> None:
    with pytest.raises(IsADirectoryError):
        assert is_macho(tmp_path) is False


def test_is_macho_file_does_not_exist(tmp_path: pathlib.Path) -> None:
    lib_path = tmp_path / "test.dylib"
    with pytest.raises(FileNotFoundError):
        assert is_macho(lib_path) is False


def test_is_elf_true(tmp_path: pathlib.Path) -> None:
    lib_path = tmp_path / "test.so"
    lib_path.write_bytes(b"\x7f\x45\x4c\x46")
    assert is_elf(lib_path) is True


def test_is_elf_false(tmp_path: pathlib.Path) -> None:
    lib_path = tmp_path / "test.so"
    lib_path.write_bytes(b"\xcf\xfa\xed\xfa")
    assert is_elf(lib_path) is False


def test_is_elf_not_a_file(tmp_path: pathlib.Path) -> None:
    with pytest.raises(IsADirectoryError):
        assert is_elf(tmp_path) is False


def test_is_elf_file_does_not_exist(tmp_path: pathlib.Path) -> None:
    lib_path = tmp_path / "test.so"
    with pytest.raises(FileNotFoundError):
        assert is_elf(lib_path) is False


def test_parse_otool_l() -> None:
    pytest.skip("Not implemented")


def test_parse_macho() -> None:
    pytest.skip("Not implemented")


def test_handle_macho() -> None:
    pytest.skip("Not implemented")


def test_parse_readelf_d_no_rpath() -> None:
    section = dedent(
        """
    Dynamic section at offset 0xbdd40 contains 28 entries:
      Tag        Type                         Name/Value
     0x0000000000000001 (NEEDED)             Shared library: [libz.so.1]
     0x0000000000000001 (NEEDED)             Shared library: [libbz2.so.1]
     0x0000000000000001 (NEEDED)             Shared library: [libpng15.so.15]
     0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
     0x000000000000000e (SONAME)             Library soname: [libfreetype.so.6]
    """
    )
    assert parse_readelf_d(section) == []


def test_parse_readelf_d_rpath() -> None:
    section = dedent(
        """
    Dynamic section at offset 0x58000 contains 27 entries:
      Tag        Type                         Name/Value
     0x000000000000000f (RPATH)              Library rpath: [$ORIGIN/../..]
     0x0000000000000001 (NEEDED)             Shared library: [libsqlite3.so.0]
     0x0000000000000001 (NEEDED)             Shared library: [libpthread.so.0]
     0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
     0x000000000000000c (INIT)               0x51f8
     """
    )
    assert parse_readelf_d(section) == ["$ORIGIN/../.."]


def test_parse_readelf_d_needed() -> None:
    """gh-37: DT_NEEDED parsing used to replace host ``ldd`` on cross builds."""
    section = dedent(
        """
    Dynamic section at offset 0xbdd40 contains 28 entries:
      Tag        Type                         Name/Value
     0x0000000000000001 (NEEDED)             Shared library: [libz.so.1]
     0x0000000000000001 (NEEDED)             Shared library: [libbz2.so.1]
     0x0000000000000001 (NEEDED)             Shared library: [libpng15.so.15]
     0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
     0x000000000000000e (SONAME)             Library soname: [libfreetype.so.6]
     0x000000000000000f (RPATH)              Library rpath: [$ORIGIN]
    """
    )
    assert parse_readelf_d_needed(section) == [
        "libz.so.1",
        "libbz2.so.1",
        "libpng15.so.15",
        "libc.so.6",
    ]


def test_parse_readelf_d_needed_empty() -> None:
    section = dedent(
        """
    Dynamic section at offset 0x58000 contains 3 entries:
      Tag        Type                         Name/Value
     0x000000000000000e (SONAME)             Library soname: [libfoo.so.1]
     0x000000000000000c (INIT)               0x51f8
    """
    )
    assert parse_readelf_d_needed(section) == []


def test_parse_readelf_d_needed_malformed() -> None:
    # Lines with "NEEDED" but no bracket pair must not explode.
    section = "0x0000000000000001 (NEEDED)             Shared library: broken\n"
    assert parse_readelf_d_needed(section) == []


def test_is_in_dir(tmp_path: pathlib.Path) -> None:
    parent = tmp_path / "foo"
    child = tmp_path / "foo" / "bar" / "bang"
    assert is_in_dir(child, parent) is True


def test_is_in_dir_false(tmp_path: pathlib.Path) -> None:
    parent = tmp_path / "foo"
    child = tmp_path / "bar" / "bang"
    assert is_in_dir(child, parent) is False


def test_patch_rpath(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "test")
    new_rpath = str(pathlib.Path("$ORIGIN", "..", "..", "lib"))
    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        with patch(
            "relenv.relocate.parse_rpath",
            return_value=[str(tmp_path / "old" / "lib")],
        ):
            assert patch_rpath(path, new_rpath) == new_rpath


def test_patch_rpath_failed(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "test")
    new_rpath = str(pathlib.Path("$ORIGIN", "..", "..", "lib"))
    with patch("subprocess.run", return_value=MagicMock(returncode=1)):
        with patch(
            "relenv.relocate.parse_rpath",
            return_value=[str(tmp_path / "old" / "lib")],
        ):
            assert patch_rpath(path, new_rpath) is False


def test_patch_rpath_no_change(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "test")
    new_rpath = str(pathlib.Path("$ORIGIN", "..", "..", "lib"))
    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        with patch("relenv.relocate.parse_rpath", return_value=[new_rpath]):
            assert patch_rpath(path, new_rpath, only_relative=False) == new_rpath


def test_patch_rpath_remove_non_relative(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "test")
    new_rpath = str(pathlib.Path("$ORIGIN", "..", "..", "lib"))
    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        with patch(
            "relenv.relocate.parse_rpath",
            return_value=[str(tmp_path / "old" / "lib")],
        ):
            assert patch_rpath(path, new_rpath) == new_rpath


def test_main_linux(tmp_path: pathlib.Path) -> None:
    proj = LinuxProject(tmp_path)
    simple = proj.add_simple_elf("simple.so", "foo", "bar")
    simple2 = proj.add_simple_elf("simple2.so", "foo", "bar", "bop")
    proj.add_file("not-an-so", "fake", "foo", "bar", "bop")
    calls = [
        call(str(simple), str(proj.libs_dir), True, str(proj.root_dir)),
        call(str(simple2), str(proj.libs_dir), True, str(proj.root_dir)),
    ]
    with proj:
        with patch("relenv.relocate.handle_elf") as elf_mock:
            main(proj.root_dir, proj.libs_dir)
            assert elf_mock.call_count == 2
            elf_mock.assert_has_calls(calls, any_order=True)


def test_handle_elf(tmp_path: pathlib.Path) -> None:
    proj = LinuxProject(tmp_path / "proj")
    pybin = proj.add_simple_elf("python", "foo")
    libcrypt = tmp_path / "libcrypt.so.2"
    libcrypt.touch()

    needed = ["libcrypt.so.2", "libm.so.6", "libc.so.6"]
    # Non-rpath_only mode falls back to host ``ldd`` to resolve
    # not-yet-bundled SONAMEs for copying.  Provide that resolution via a
    # mocked subprocess.run keyed on argv[0].
    ldd_ret = f"""
    libcrypt.so.2 => {libcrypt} (0x0123456789)
    libm.so.6 => /usr/lib/libm.so.6 (0x0123456789)
    libc.so.6 => /usr/lib/libc.so.6 (0x0123456789)
    """.encode()

    def fake_run(argv: Any, **_kwargs: Any) -> MagicMock:
        if argv and str(argv[0]).endswith("ldd"):
            return MagicMock(stdout=ldd_ret)
        return MagicMock(stdout=b"")

    with proj:
        with patch("relenv.relocate.read_needed", return_value=needed):
            with patch("subprocess.run", side_effect=fake_run):
                with patch("relenv.relocate.patch_rpath") as patch_rpath_mock:
                    handle_elf(str(pybin), str(proj.libs_dir), False, str(proj.root_dir))
                    assert (proj.libs_dir / "libcrypt.so.2").exists()
                    assert not (proj.libs_dir / "libm.so.6").exists()
                    assert not (proj.libs_dir / "libc.so.6").exists()
                    assert patch_rpath_mock.call_count == 1
                    patch_rpath_mock.assert_called_with(str(pybin), "$ORIGIN/../lib")


def test_handle_elf_rpath_only(tmp_path: pathlib.Path) -> None:
    proj = LinuxProject(tmp_path / "proj")
    pybin = proj.add_simple_elf("python", "foo")
    libcrypt = proj.libs_dir / "libcrypt.so.2"

    # rpath_only=True: ``handle_elf`` only cares about DT_NEEDED entries
    # that resolve to files already present under ``libs``.  ``fake.so.2``
    # is in the NEEDED list but not under libs, so it should log a warning
    # and be skipped (no copy, no rpath contribution from it alone).
    needed = ["libcrypt.so.2", "fake.so.2", "libm.so.6", "libc.so.6"]

    with proj:
        libcrypt.touch()
        with patch("relenv.relocate.read_needed", return_value=needed):
            with patch("relenv.relocate.patch_rpath") as patch_rpath_mock:
                handle_elf(str(pybin), str(proj.libs_dir), True, str(proj.root_dir))
                assert not (proj.libs_dir / "fake.so.2").exists()
                assert patch_rpath_mock.call_count == 1
                patch_rpath_mock.assert_called_with(str(pybin), "$ORIGIN/../lib")


def test_remove_rpath_with_existing_rpath(tmp_path: pathlib.Path) -> None:
    """Test that remove_rpath removes an existing RPATH."""
    path = str(tmp_path / "test.so")
    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        with patch(
            "relenv.relocate.parse_rpath",
            return_value=["/some/absolute/path"],
        ):
            assert remove_rpath(path) is True


def test_remove_rpath_no_existing_rpath(tmp_path: pathlib.Path) -> None:
    """Test that remove_rpath succeeds when there's no RPATH to remove."""
    path = str(tmp_path / "test.so")
    with patch("relenv.relocate.parse_rpath", return_value=[]):
        assert remove_rpath(path) is True


def test_remove_rpath_failed(tmp_path: pathlib.Path) -> None:
    """Test that remove_rpath returns False when patchelf fails."""
    path = str(tmp_path / "test.so")
    with patch("subprocess.run", return_value=MagicMock(returncode=1)):
        with patch(
            "relenv.relocate.parse_rpath",
            return_value=["/some/absolute/path"],
        ):
            assert remove_rpath(path) is False


def test_handle_elf_removes_rpath_when_no_relenv_libs(tmp_path: pathlib.Path) -> None:
    """Test that handle_elf removes RPATH for binaries linking only to system libs."""
    proj = LinuxProject(tmp_path / "proj")
    module = proj.add_simple_elf("array.so", "lib", "python3.10", "lib-dynload")

    # DT_NEEDED entries referring only to the LIBCLIBS allow-list (glibc)
    needed = ["libpthread.so.0", "libc.so.6"]

    with proj:
        with patch("relenv.relocate.read_needed", return_value=needed):
            with patch("relenv.relocate.remove_rpath") as remove_rpath_mock:
                with patch("relenv.relocate.patch_rpath") as patch_rpath_mock:
                    handle_elf(str(module), str(proj.libs_dir), True, str(proj.root_dir))
                    # Should remove RPATH, not patch it
                    assert remove_rpath_mock.call_count == 1
                    assert patch_rpath_mock.call_count == 0
                    remove_rpath_mock.assert_called_with(str(module))


def test_handle_elf_sets_rpath_when_relenv_libs_present(tmp_path: pathlib.Path) -> None:
    """Test that handle_elf sets RPATH for binaries linking to relenv libs."""
    proj = LinuxProject(tmp_path / "proj")
    module = proj.add_simple_elf("_ssl.so", "lib", "python3.10", "lib-dynload")
    libssl = proj.libs_dir / "libssl.so.3"
    libssl.touch()

    needed = ["libssl.so.3", "libpthread.so.0", "libc.so.6"]

    with proj:
        with patch("relenv.relocate.read_needed", return_value=needed):
            with patch("relenv.relocate.remove_rpath") as remove_rpath_mock:
                with patch("relenv.relocate.patch_rpath") as patch_rpath_mock:
                    handle_elf(str(module), str(proj.libs_dir), True, str(proj.root_dir))
                    # Should patch RPATH, not remove it
                    assert patch_rpath_mock.call_count == 1
                    assert remove_rpath_mock.call_count == 0
                    patch_rpath_mock.assert_called_with(str(module), "$ORIGIN/../..")


def test_handle_elf_keeps_rpath_on_cross_build(tmp_path: pathlib.Path) -> None:
    """
    gh-37: on a cross-build the host ``ldd`` cannot read a foreign-arch
    ELF and historically emitted empty output -- which drove
    ``handle_elf`` down the "no relenv libs linked -> remove_rpath" path
    for every single cross-built binary.  With the ``readelf -d`` DT_NEEDED
    rewrite, ``handle_elf`` consults ELF metadata directly (arch-agnostic)
    and correctly sees the bundled ``libssl`` dependency, so RPATH is
    preserved instead of stripped.
    """
    proj = LinuxProject(tmp_path / "proj")
    module = proj.add_simple_elf("_ssl.so", "lib", "python3.10", "lib-dynload")
    libssl = proj.libs_dir / "libssl.so.3"
    libssl.touch()

    needed = ["libssl.so.3", "libpthread.so.0", "libc.so.6"]

    # Simulate the exact cross-compile failure mode: host ``ldd`` exits
    # non-zero with empty stdout because the ELF is a foreign arch.  Any
    # subprocess.run call (there shouldn't be one for rpath_only=True,
    # since read_needed is mocked) returns the broken ldd result -- if
    # ``handle_elf`` were still consulting ldd we'd see it fall through to
    # remove_rpath.
    broken_ldd_ret = MagicMock(stdout=b"", returncode=1)

    with proj:
        with patch("relenv.relocate.read_needed", return_value=needed):
            with patch("subprocess.run", return_value=broken_ldd_ret):
                with patch("relenv.relocate.remove_rpath") as remove_rpath_mock:
                    with patch("relenv.relocate.patch_rpath") as patch_rpath_mock:
                        handle_elf(str(module), str(proj.libs_dir), True, str(proj.root_dir))
                        assert patch_rpath_mock.call_count == 1, (
                            "gh-37: cross-built binary with bundled DT_NEEDED "
                            "should get its RPATH patched, not removed."
                        )
                        assert remove_rpath_mock.call_count == 0
                        patch_rpath_mock.assert_called_with(str(module), "$ORIGIN/../..")
