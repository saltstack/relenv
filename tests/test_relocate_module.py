# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
from typing import Dict, List, Tuple

import pytest

from relenv import relocate


def test_is_elf_on_text_file(tmp_path: pathlib.Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("not an ELF binary\n")
    assert relocate.is_elf(sample) is False


def test_is_macho_on_text_file(tmp_path: pathlib.Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("plain text\n")
    assert relocate.is_macho(sample) is False


def test_parse_readelf_output() -> None:
    output = """
 0x000000000000000f (NEEDED)             Shared library: [libc.so.6]
 0x000000000000001d (RUNPATH)            Library runpath: [/usr/lib:/opt/lib]
"""
    result = relocate.parse_readelf_d(output)
    assert result == ["/usr/lib", "/opt/lib"]


def test_parse_otool_output_extracts_rpaths() -> None:
    sample_output = """
Load command 0
      cmd LC_LOAD_DYLIB
  cmdsize 56
     name /usr/lib/libSystem.B.dylib (offset 24)
Load command 1
      cmd LC_RPATH
  cmdsize 32
     path @loader_path/../lib (offset 12)
"""
    parsed = relocate.parse_otool_l(sample_output)
    assert parsed[relocate.LC_LOAD_DYLIB] == ["/usr/lib/libSystem.B.dylib"]
    assert parsed[relocate.LC_RPATH] == ["@loader_path/../lib"]


def test_patch_rpath_adds_new_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    binary = tmp_path / "prog"
    binary.write_text("dummy")

    monkeypatch.setattr(
        relocate,
        "parse_rpath",
        lambda path: ["$ORIGIN/lib", "/abs/lib"],
    )

    recorded: Dict[str, List[str]] = {}

    def fake_run(
        cmd: List[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        recorded.setdefault("cmd", []).extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(relocate.subprocess, "run", fake_run)

    result = relocate.patch_rpath(binary, "$ORIGIN/../lib")
    assert result == "$ORIGIN/../lib:$ORIGIN/lib"
    assert pathlib.Path(recorded["cmd"][-1]) == binary


def test_patch_rpath_skips_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    binary = tmp_path / "prog"
    binary.write_text("dummy")

    monkeypatch.setattr(relocate, "parse_rpath", lambda path: ["$ORIGIN/lib"])

    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("patchelf should not be invoked")

    monkeypatch.setattr(relocate.subprocess, "run", fail_run)

    result = relocate.patch_rpath(binary, "$ORIGIN/lib")
    assert result == "$ORIGIN/lib"


def test_handle_elf_sets_rpath(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    bin_dir = tmp_path / "bin"
    lib_dir = tmp_path / "lib"
    bin_dir.mkdir()
    lib_dir.mkdir()

    binary = bin_dir / "prog"
    binary.write_text("binary")
    resident = lib_dir / "libfoo.so"
    resident.write_text("library")

    def fake_run(
        cmd: List[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if cmd[0] == "ldd":
            stdout = f"libfoo.so => {resident} (0x00007)\nlibc.so.6 => /lib/libc.so.6 (0x00007)\n"
            return subprocess.CompletedProcess(
                cmd, 0, stdout=stdout.encode(), stderr=b""
            )
        raise AssertionError(f"Unexpected command {cmd}")

    monkeypatch.setattr(relocate.subprocess, "run", fake_run)

    captured: Dict[str, str] = {}

    def fake_patch_rpath(path: str, relpath: str) -> str:
        captured["path"] = path
        captured["relpath"] = relpath
        return relpath

    monkeypatch.setattr(relocate, "patch_rpath", fake_patch_rpath)

    relocate.handle_elf(binary, lib_dir, rpath_only=False, root=lib_dir)

    assert pathlib.Path(captured["path"]) == binary
    expected_rel = os.path.relpath(lib_dir, bin_dir)
    if expected_rel == ".":
        expected_rpath = "$ORIGIN"
    else:
        expected_rpath = str(pathlib.Path("$ORIGIN") / expected_rel)
    assert captured["relpath"] == expected_rpath


def test_patch_rpath_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    binary = tmp_path / "prog"
    binary.write_text("dummy")

    monkeypatch.setattr(relocate, "parse_rpath", lambda path: [])

    def fake_run(
        cmd: List[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"err")

    monkeypatch.setattr(relocate.subprocess, "run", fake_run)

    assert relocate.patch_rpath(binary, "$ORIGIN/lib") is False


def test_parse_macho_non_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    output = "foo: is not an object file\n"
    monkeypatch.setattr(
        relocate.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 0, stdout=output.encode(), stderr=b""
        ),
    )
    assert relocate.parse_macho(tmp_path / "lib.dylib") is None


def test_handle_macho_copies_when_needed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    binary = tmp_path / "bin" / "prog"
    binary.parent.mkdir()
    binary.write_text("exe")
    source_lib = tmp_path / "src" / "libfoo.dylib"
    source_lib.parent.mkdir()
    source_lib.write_text("binary")
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    monkeypatch.setattr(
        relocate,
        "parse_macho",
        lambda path: {relocate.LC_LOAD_DYLIB: [str(source_lib)]},
    )

    monkeypatch.setattr(os.path, "exists", lambda path: path == str(source_lib))

    copied: Dict[str, Tuple[str, str]] = {}

    monkeypatch.setattr(
        shutil, "copy", lambda src, dst: copied.setdefault("copy", (src, dst))
    )
    monkeypatch.setattr(
        shutil, "copymode", lambda src, dst: copied.setdefault("copymode", (src, dst))
    )

    recorded: Dict[str, List[str]] = {}

    def fake_run(
        cmd: List[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        recorded.setdefault("cmd", []).extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(relocate.subprocess, "run", fake_run)

    relocate.handle_macho(str(binary), str(root_dir), rpath_only=False)

    assert copied["copy"][0] == str(source_lib)
    assert pathlib.Path(copied["copy"][1]).name == source_lib.name
    assert recorded["cmd"][0] == "install_name_tool"


def test_handle_macho_rpath_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    binary = tmp_path / "bin" / "prog"
    binary.parent.mkdir()
    binary.write_text("exe")
    source_lib = tmp_path / "src" / "libfoo.dylib"
    source_lib.parent.mkdir()
    source_lib.write_text("binary")
    root_dir = tmp_path / "root"
    root_dir.mkdir()

    monkeypatch.setattr(
        relocate,
        "parse_macho",
        lambda path: {relocate.LC_LOAD_DYLIB: [str(source_lib)]},
    )

    monkeypatch.setattr(
        os.path,
        "exists",
        lambda path: path == str(source_lib),
    )

    monkeypatch.setattr(shutil, "copy", lambda *_args, **_kw: (_args, _kw))
    monkeypatch.setattr(shutil, "copymode", lambda *_args, **_kw: (_args, _kw))

    def fake_run(
        cmd: List[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if cmd[0] == "install_name_tool":
            raise AssertionError("install_name_tool should not run in rpath_only mode")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(relocate.subprocess, "run", fake_run)

    relocate.handle_macho(str(binary), str(root_dir), rpath_only=True)
