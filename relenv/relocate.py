# Copyright 2022-2026 Broadcom.
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
import sys as _sys

log = logging.getLogger(__name__)

os = _os
shutil = _shutil
subprocess = _subprocess
sys = _sys

__all__ = [
    "is_macho",
    "is_elf",
    "parse_otool_l",
    "parse_readelf_d",
    "parse_readelf_d_needed",
    "parse_macho",
    "parse_rpath",
    "read_needed",
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

# Cache for readelf binary path
_READELF_BINARY: str | None = None

# Cache for patchelf binary path
_PATCHELF_BINARY: str | None = None


def _get_readelf_binary() -> str:
    """
    Get the path to readelf binary, preferring toolchain version.

    Returns the cached value if already computed. On Linux, prefers the
    toolchain's readelf over the system version. Falls back to "readelf"
    from PATH if toolchain is unavailable.

    :return: Path to readelf binary
    :rtype: str
    """
    global _READELF_BINARY
    if _READELF_BINARY is not None:
        return _READELF_BINARY

    # Only Linux has the toolchain with readelf
    if sys.platform == "linux":
        try:
            from relenv.common import get_toolchain, get_triplet

            toolchain = get_toolchain()
            if toolchain:
                triplet = get_triplet()
                toolchain_readelf = toolchain / "bin" / f"{triplet}-readelf"
                if toolchain_readelf.exists():
                    _READELF_BINARY = str(toolchain_readelf)
                    return _READELF_BINARY
        except Exception:
            # Fall through to system readelf
            pass

    # Fall back to system readelf
    _READELF_BINARY = "readelf"
    return _READELF_BINARY


def _get_patchelf_binary() -> str:
    """
    Get the path to patchelf binary, preferring toolchain version.

    Returns the cached value if already computed. On Linux, prefers the
    toolchain's patchelf over the system version. Falls back to "patchelf"
    from PATH if toolchain is unavailable.

    :return: Path to patchelf binary
    :rtype: str
    """
    global _PATCHELF_BINARY
    if _PATCHELF_BINARY is not None:
        return _PATCHELF_BINARY

    # Only Linux has the toolchain with patchelf
    if sys.platform == "linux":
        try:
            from relenv.common import get_toolchain

            toolchain = get_toolchain()
            if toolchain:
                toolchain_patchelf = toolchain / "bin" / "patchelf"
                if toolchain_patchelf.exists():
                    _PATCHELF_BINARY = str(toolchain_patchelf)
                    return _PATCHELF_BINARY
        except Exception:
            # Fall through to system patchelf
            pass

    # Fall back to system patchelf
    _PATCHELF_BINARY = "patchelf"
    return _PATCHELF_BINARY


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
    cmd: str | None = None
    name: str | None = None
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
    proc = subprocess.run(["otool", "-l", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
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
    readelf = _get_readelf_binary()
    proc = subprocess.run([readelf, "-d", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return parse_readelf_d(proc.stdout.decode())


def parse_readelf_d_needed(stdout: str) -> list[str]:
    """
    Parse DT_NEEDED entries from ``readelf -d <path>`` output.

    ``readelf -d`` prints every dynamic-section entry; DT_NEEDED rows look
    like::

        0x0000000000000001 (NEEDED)             Shared library: [libssl.so.3]

    The SONAME is in square brackets.  This is the architecture-agnostic
    equivalent of ``ldd``'s first column, with the critical difference
    that ``readelf`` parses ELF metadata directly and works for
    cross-compiled binaries where the host dynamic linker would error
    out.

    :param stdout: Output of ``readelf -d <path>``.
    :return: List of SONAMEs (strings without brackets) in file order.
    """
    needed: list[str] = []
    for line in stdout.splitlines():
        if "NEEDED" not in line:
            continue
        start = line.find("[")
        end = line.find("]", start)
        if start == -1 or end == -1 or end <= start + 1:
            continue
        needed.append(line[start + 1 : end])
    return needed


def read_needed(path: str | os.PathLike[str]) -> list[str]:
    """
    Run ``readelf -d <path>`` and return the DT_NEEDED SONAMEs.

    Toolchain-aware: :func:`_get_readelf_binary` already prefers the
    target toolchain's ``readelf`` when ``RELENV_BUILDENV`` is set, so this
    works on ELFs of any architecture.

    :param path: The path to the ELF file.
    :return: The SONAMEs the binary depends on, in dynamic-section order.
    """
    readelf = _get_readelf_binary()
    proc = subprocess.run([readelf, "-d", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return parse_readelf_d_needed(proc.stdout.decode())


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
                z = pathlib.Path("@loader_path") / os.path.relpath(y, path_obj.resolve().parent)
                cmd = ["install_name_tool", "-change", x, str(z), path_str]
                subprocess.run(cmd)
                log.info("Changed %s to %s in %s", x, z, path_str)
    return obj


def is_in_dir(filepath: str | os.PathLike[str], directory: str | os.PathLike[str]) -> bool:
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


def remove_rpath(path: str | os.PathLike[str]) -> bool:
    """
    Remove the rpath from a given ELF file.

    :param path: The path to an ELF file
    :type path: str

    :return: True if successful, False otherwise
    :rtype: bool
    """
    old_rpath = parse_rpath(path)
    if not old_rpath:
        # No RPATH to remove
        return True

    log.info("Remove RPATH from %s (was: %s)", path, old_rpath)
    patchelf = _get_patchelf_binary()
    proc = subprocess.run(
        [patchelf, "--remove-rpath", path],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )

    if proc.returncode:
        log.error("Failed to remove RPATH from %s: %s", path, proc.stderr.decode())
        return False
    return True


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
        patchelf = _get_patchelf_binary()
        proc = subprocess.run(
            [patchelf, "--force-rpath", "--set-rpath", patched_rpath, path],
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
    # gh-37: the original implementation shelled out to the host ``ldd``,
    # which fails on cross-compiled ELFs (the host dynamic linker refuses
    # to load a foreign-arch object: either "not a dynamic executable" or
    # a non-zero exit with empty stdout).  The ensuing "needs_rpath stays
    # False -> remove_rpath(path)" silently stripped RPATH from every
    # cross-built binary.  Use ``readelf -d`` instead: it parses the ELF's
    # dynamic section directly, is arch-agnostic, and ``_get_readelf_binary``
    # already prefers the target toolchain's ``readelf`` so even an
    # x86_64 host building aarch64 picks up the right tool.
    #
    # In ``rpath_only`` mode (the default -- what finalize uses) we never
    # needed the host linker's path resolution anyway: all we care about
    # is whether the binary's DT_NEEDED SONAMEs refer to libraries we
    # already laid down under ``libs/``.  That's a filesystem-local check
    # that works identically for native and cross builds.
    needs_rpath = False
    libs_dir = pathlib.Path(libs)
    root_dir = pathlib.Path(root)

    for soname in read_needed(path):
        if soname in LIBCLIBS:
            log.debug("Skipping glibc lib %s", soname)
            continue

        candidate = libs_dir / soname
        if candidate.exists():
            needs_rpath = True
            log.info("File already within libs directory: %s", candidate)
            continue

        # Fall back to a shallow search of root_dir -- covers the case
        # where the needed SONAME lives somewhere under the prefix but
        # not directly in libs (e.g. architecture-specific subdirs).
        try:
            hits = [p for p in root_dir.rglob(soname) if p.is_file()]
        except OSError:
            hits = []
        if hits:
            needs_rpath = True
            log.info("File already within root directory: %s", hits[0])
            continue

        relocated_path = libs_dir / soname
        if relocated_path.exists():
            log.debug("Relocated library exists: %s", relocated_path)
        elif rpath_only:
            log.warning("In `rpath_only mode` but %s is not in %s", soname, root)
        else:
            # Non-rpath_only mode is only used by the ``relenv relocate``
            # CLI on already-installed native onedirs.  Cross builds never
            # exercise this path (finalize is always rpath_only=True), so
            # the host ``ldd`` fallback is retained here for native
            # relocation only.
            ldd_proc = subprocess.run(["ldd", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            linked_lib: str | None = None
            for line in ldd_proc.stdout.decode().splitlines():
                if " => " not in line:
                    continue
                name, info = [p.strip() for p in line.split("=>", 1)]
                if name != soname or info.startswith("not found"):
                    continue
                linked_lib = info.rsplit(" ", 1)[0].strip()
                break
            if not linked_lib or not os.path.exists(linked_lib):
                log.warning(
                    "Could not resolve %s on host for copying (cross build?)",
                    soname,
                )
                continue
            log.info("Copy %s to %s", linked_lib, relocated_path)
            shutil.copy(linked_lib, str(relocated_path))
            shutil.copymode(linked_lib, str(relocated_path))
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
        # No relenv libraries are linked, so RPATH is not needed
        # Remove any existing RPATH to avoid security/correctness issues
        remove_rpath(path)


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
