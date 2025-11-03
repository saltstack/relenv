# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
A script to ensure the proper rpaths are in place for the relenv environment.
"""

from __future__ import annotations

import logging
import os as _os
import pathlib
import shutil as _shutil
import subprocess as _subprocess
from typing import Optional

log = logging.getLogger(__name__)

os = _os
shutil = _shutil
subprocess = _subprocess

__all__ = [
    "is_macho",
    "is_elf",
    "parse_otool_l",
    "parse_readelf_d",
    "parse_macho",
    "parse_rpath",
    "handle_macho",
    "is_in_dir",
    "handle_elf",
    "patch_rpath",
    "main",
    "os",
    "shutil",
    "subprocess",
]


LIBCLIBS = [
    "linux-vdso.so.1",
    "libc.so.6",
    "librt.so.1",
    "libm.so.6",
    "libmd.so.0",
    "libpthread.so.0",
    # Adjust rpath of libcrypt because we include libxcrypt
    # "libcrypt.so.1",
    "libdl.so.2",
    "libmemusage.so",
    "libnsl.so.1",
    "libnss_compat.so.2",
    "libnss_db.so.2",
    "libnss_dns.so.2",
    "libnss_files.so.2",
    "libnss_hesiod.so.2",
    "libpcprofile.so.2",
    "libresolv.so.2",
    "librt.so.1",
    "libthread_db.so.1",
    "libutil.so.1",
    "libutil.so.2",
    # libgcc is not technically glibc but shares the same kind of backwards
    # compatablity guarantees.
    "libgcc_s.so.2",
    "libgcc_s.so.1",
]

LC_ID_DYLIB = "LC_ID_DYLIB"
LC_LOAD_DYLIB = "LC_LOAD_DYLIB"
LC_RPATH = "LC_RPATH"


def is_macho(path: str | os.PathLike[str]) -> bool:
    """
    Determines whether the given file is a macho file.

    :param path: The path to the file to check
    :type path: str

    :return: Whether the file is a macho file
    :rtype: bool
    """
    with open(path, "rb") as fp:
        magic = fp.read(4)
    # XXX: Handle 64bit, 32bit, ppc, arm
    return magic in [b"\xcf\xfa\xed\xfe"]


def is_elf(path: str | os.PathLike[str]) -> bool:
    """
    Determines whether the given file is an ELF file.

    :param path: The path to the file to check
    :type path: str

    :return: Whether the file is an ELF file
    :rtype: bool
    """
    with open(path, "rb") as fp:
        magic = fp.read(4)
    return magic == b"\x7f\x45\x4c\x46"


def parse_otool_l(stdout: str) -> dict[str, list[str]]:
    """
    Parse the output of ``otool -l <path>``.

    :param stdout: The output of the ``otool -l <path>`` command
    :type stdout: str

    :return: The parsed relevant output with command keys and path values
    :rtype: dict
    """
    in_cmd = False
    cmd: Optional[str] = None
    name: Optional[str] = None
    data: dict[str, list[str]] = {}
    for line in [x.strip() for x in stdout.split("\n")]:

        if not line:
            continue

        if line.split()[0] == "cmd":
            in_cmd = False
            if cmd is not None and name is not None:
                data.setdefault(cmd, []).append(name)
                cmd = None
                name = None
            command = line.split()[-1]
            if command in (LC_ID_DYLIB, LC_LOAD_DYLIB, "LC_RPATH"):
                cmd = command
                in_cmd = True

        if in_cmd:
            parts = line.split()
            if parts[0] == "name" and len(parts) > 1:
                name = parts[1]
            if parts[0] == "path" and len(parts) > 1:
                name = parts[1]

    if in_cmd and cmd is not None and name is not None:
        data.setdefault(cmd, []).append(name)

    return data


def parse_readelf_d(stdout: str) -> list[str]:
    """
    Parse the output of ``readelf -d <path>``.

    :param stdout: The output of the ``readelf -d <path>`` command
    :type stdout: str

    :return: The RPATH values
    :rtype: list
    """
    for line in stdout.splitlines():
        # Find either RPATH or READPATH
        if line.find("PATH") == -1:
            continue
        return line.split(":", 1)[-1].strip().strip("[").strip("]").split(":")
    return []


def parse_macho(path: str | os.PathLike[str]) -> dict[str, list[str]] | None:
    """
    Run ``otool -l <path>`` and return its parsed output.

    :param path: The path to the file
    :type path: str

    :return: The parsed relevant RPATH content, or None if it isn't an object file
    :rtype: dict or None
    """
    proc = subprocess.run(
        ["otool", "-l", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE
    )
    stdout = proc.stdout.decode()
    if stdout.find("is not an object file") != -1:
        return None
    return parse_otool_l(stdout)


def parse_rpath(path: str | os.PathLike[str]) -> list[str]:
    """
    Run ``readelf -d <path>`` and return its parsed output.

    :param path: The path to the file
    :type path: str

    :return: The RPATH's found.
    :rtype: list
    """
    proc = subprocess.run(
        ["readelf", "-d", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return parse_readelf_d(proc.stdout.decode())


def handle_macho(
    path: str | os.PathLike[str],
    root_dir: str | os.PathLike[str],
    rpath_only: bool,
) -> dict[str, list[str]] | None:
    """
    Ensure the given macho file has the correct rpath and is in th correct location.

    :param path: The path to a macho file
    :type path: str
    :param root_dir: The directory the file needs to reside under
    :type root_dir: str
    :param rpath_only: If true, only ensure the correct rpaths are present and don't copy the file
    :type rpath_only: bool

    :return: The information from ``parse_macho`` on the macho file.
    """
    path_obj = pathlib.Path(path)
    obj = parse_macho(path_obj)
    path_str = str(path_obj)
    log.info("Processing file %s %r", path_str, obj)
    if not obj:
        return None
    if LC_LOAD_DYLIB in obj:
        for x in obj[LC_LOAD_DYLIB]:
            if x.startswith("@"):
                log.info("Skipping dynamic load: %s", x)
                continue
            if os.path.exists(x):
                target_dir = pathlib.Path(root_dir).resolve()
                y = target_dir / os.path.basename(x)
                if not os.path.exists(y):
                    if rpath_only:
                        log.warning("In `rpath_only mode` but %s is not in %s", x, y)
                        continue
                    else:
                        shutil.copy(x, y)
                        shutil.copymode(x, y)
                        log.info("Copied %s to %s", x, y)
                log.info("Use %s to %s", y, path_str)
                z = pathlib.Path("@loader_path") / os.path.relpath(
                    y, path_obj.resolve().parent
                )
                cmd = ["install_name_tool", "-change", x, str(z), path_str]
                subprocess.run(cmd)
                log.info("Changed %s to %s in %s", x, z, path_str)
    return obj


def is_in_dir(
    filepath: str | os.PathLike[str], directory: str | os.PathLike[str]
) -> bool:
    """
    Determines whether a file is contained within a directory.

    :param filepath: The path to the file to check
    :type filepath: str
    :param directory: The directory to check within
    :type directory: str

    :return: Whether the file is contained within the given directory
    :rtype: bool
    """
    return os.path.realpath(filepath).startswith(os.path.realpath(directory) + os.sep)


def patch_rpath(
    path: str | os.PathLike[str],
    new_rpath: str,
    only_relative: bool = True,
) -> str | bool:
    """
    Patch the rpath of a given ELF file.

    :param path: The path to an ELF file
    :type path: str
    :param new_rpath: The new rpath to add
    :type new_rpath: str
    :param only_relative: Whether or not to remove non-relative rpaths, defaults to True
    :type only_relative: bool, optional

    :return: The new rpath, or False if patching failed
    :rtype: str or bool
    """
    old_rpath = parse_rpath(path)

    # Remove non-relative rpaths if needed
    if only_relative:
        old_rpath = [rpath for rpath in old_rpath if rpath.startswith("$ORIGIN")]

    if new_rpath not in old_rpath:
        patched_rpath = ":".join([new_rpath] + old_rpath)
        log.info("Set RPATH=%s %s", patched_rpath, path)
        proc = subprocess.run(
            ["patchelf", "--force-rpath", "--set-rpath", patched_rpath, path],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        if proc.returncode:
            return False
        return patched_rpath
    return ":".join(old_rpath)


def handle_elf(
    path: str | os.PathLike[str],
    libs: str | os.PathLike[str],
    rpath_only: bool,
    root: str | os.PathLike[str] | None = None,
) -> None:
    """
    Handle the parsing and pathcing of an ELF file.

    :param path: The path of the ELF file
    :type path: str
    :param libs: The libs directory
    :type libs: str
    :param rpath_only: If true, only ensure the correct rpaths are present and don't copy the file
    :type rpath_only: bool
    :param root: The directory to ensure the file is under, defaults to None
    :type root: str, optional
    """
    if root is None:
        root = libs
    proc = subprocess.run(["ldd", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    needs_rpath = False
    for line in proc.stdout.decode().splitlines():
        if line.find("=>") == -1:
            log.debug("Skip ldd output line: %s", line)
            continue

        lib_name, location_info = [_.strip() for _ in line.split("=>", 1)]
        if location_info == "not found":
            # It is likely that something was not compiled correctly
            log.warning("Unable to find library %s linked from %s", lib_name, path)
            continue

        linked_lib = location_info.rsplit(" ", 1)[0].strip()
        lib_basename = os.path.basename(linked_lib)

        if lib_name in LIBCLIBS:
            log.debug("Skipping glibc lib %s", lib_name)
            continue

        if is_in_dir(linked_lib, root):
            needs_rpath = True
            log.info("File already within root directory: %s", linked_lib)
            continue

        relocated_path = os.path.join(libs, lib_basename)

        if os.path.exists(relocated_path):
            log.debug("Relocated library exists: %s", relocated_path)
        elif rpath_only:
            log.warning("In `rpath_only mode` but %s is not in %s", linked_lib, root)
        else:
            # If we aren't in `rpath_only` mode, we can copy
            log.info("Copy %s to %s", linked_lib, relocated_path)
            shutil.copy(linked_lib, relocated_path)
            shutil.copymode(linked_lib, relocated_path)
            needs_rpath = True

    if needs_rpath:
        relpart = os.path.relpath(libs, os.path.dirname(path))
        if relpart == ".":
            relpath = "$ORIGIN"
        else:
            relpath = str(pathlib.Path("$ORIGIN") / relpart)

        log.info("Adjust rpath of %s to %s", path, relpath)
        patch_rpath(path, relpath)
    else:
        log.info("Do not adjust rpath of %s", path)


def main(
    root: str | os.PathLike[str],
    libs_dir: str | os.PathLike[str] | None = None,
    rpath_only: bool = True,
    log_level: str = "DEBUG",
    log_file_name: str = "<stdout>",
) -> None:
    """
    The entrypoint into the relocate script.

    :param root: The root directory to operate traverse for files to be patched
    :type root: str
    :param libs_dir: The directory to place the libraries in, defaults to None
    :type libs_dir: str, optional
    :param rpath_only: If true, only ensure the correct rpaths are present and don't copy the file, defaults to True
    :type rpath_only: bool, optional
    :param log_level: The level to log at, defaults to "INFO"
    :type log_level: str, optional
    """
    level = logging.getLevelName(log_level.upper())
    if log_file_name != "<stdout>":
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(message)s",
            filename=log_file_name,
            filemode="w",
        )
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(message)s",
        )
    root_dir = str(pathlib.Path(root).resolve())
    if libs_dir is None:
        libs_dir = pathlib.Path(root_dir, "lib")
    libs_dir = str(pathlib.Path(libs_dir).resolve())
    processed: dict[str, dict[str, list[str]] | None] = {}
    found = True
    while found:
        found = False
        for root, dirs, files in os.walk(root_dir):
            for file in files:
                path = os.path.join(root, file)
                if path in processed:
                    continue
                log.debug("Checking %s", path)
                if is_macho(path):
                    log.info("Found Mach-O %s", path)
                    _ = handle_macho(path, libs_dir, rpath_only)
                    if _ is not None:
                        processed[path] = _
                        found = True
                elif is_elf(path):
                    log.info("Found ELF %s", path)
                    handle_elf(path, libs_dir, rpath_only, root_dir)


if __name__ == "__main__":
    import sys

    if not hasattr(sys, "RELENV"):
        raise RuntimeError("Not in a relenv environment")
    main(sys.RELENV)
