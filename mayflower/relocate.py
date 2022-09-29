#!/usr/bin/env python3
import argparse
import json
import logging
import os
import pathlib
import shutil
import subprocess

from .common import work_dirs

log = logging.getLogger(__name__)


LIBCLIBS = [
    "linux-vdso.so.1",
    "libc.so.6",
    "librt.so.1",
    "libm.so.6",
    "libmd.so.0",
    "libpthread.so.0",
    "libcrypt.so.1",
    "libdl.so.2",
    "libmemusage.so",
    "libnsl.so.1",
    "libnss_compat.so.2",
    "libnss_db.so.2",
    "libnss_dns.so.2",
    "libnss_files.so.2",
    "libnss_hesiod.so.2",
    "libpcprofile.so.2",
    "libresolve.so.2",
    "librt.so.1",
    "libthread_db.so.1",
    "libutil.so.2",
]

LC_ID_DYLIB = "LC_ID_DYLIB"
LC_LOAD_DYLIB = "LC_LOAD_DYLIB"
LC_RPATH = "LC_RPATH"


def is_macho(path):
    with open(path, "rb") as fp:
        magic = fp.read(4)
    # XXX: Handle 64bit, 32bit, ppc, arm
    return magic in [b"\xcf\xfa\xed\xfe"]


def is_elf(path):
    with open(path, "rb") as fp:
        magic = fp.read(4)
    return magic == b"\x7f\x45\x4c\x46"


def parse_otool_l(stdout):
    in_cmd = False
    cmd = None
    name = None
    data = {}
    for line in [x.strip() for x in stdout.split("\n")]:

        if not line:
            continue

        if line.split()[0] == "cmd":
            in_cmd = False
            if cmd:
                if cmd not in data:
                    data[cmd] = []
                data[cmd].append(name)
                cmd = None
                name = None
            if line.split()[-1] in (LC_ID_DYLIB, LC_LOAD_DYLIB, "LC_RPATH"):
                cmd = line.split()[-1]
                in_cmd = True

        if in_cmd:
            if line.split()[0] == "name":
                name = line.split()[1]
            if line.split()[0] == "path":
                name = line.split()[1]

    if in_cmd:
        if cmd not in data:
            data[cmd] = []
        data[cmd].append(name)

    return data


def parse_readelf_d(stdout):
    for line in stdout.splitlines():
        # Find either RPATH or READPATH
        if line.find("PATH") == -1:
            continue
        return line.split(":", 1)[-1].strip().strip("[").strip("]").split(":")
    return []


def parse_macho(path):
    proc = subprocess.run(
        ["otool", "-l", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE
    )
    stdout = proc.stdout.decode()
    if stdout.find("is not an object file") != -1:
        return
    return parse_otool_l(stdout)


def parse_rpath(path):
    proc = subprocess.run(
        ["readelf", "-d", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return parse_readelf_d(proc.stdout.decode())


def handle_macho(path, root_dir, rpath_only):
    obj = parse_macho(path)
    log.info("Processing file %s %r", path, obj)
    if LC_LOAD_DYLIB in obj:
        for x in obj[LC_LOAD_DYLIB]:
            if path.startswith("@"):
                log.info("Skipping dynamic load: %s", path)
                continue
            if os.path.exists(x):
                y = pathlib.Path(root_dir).resolve() / os.path.basename(x)
                if not os.path.exists(y):
                    if rpath_only:
                        log.warning("In `rpath_only mode` but %s is not in %s", x, y)
                        continue
                    else:
                        shutil.copy(x, y)
                        shutil.copymode(x, y)
                        log.info("Copied %s to %s", x, y)
                log.info("Use %s to %s", y, path)
                z = pathlib.Path("@loader_path") / os.path.relpath(
                    y, pathlib.Path(path).resolve().parent
                )
                cmd = ["install_name_tool", "-change", x, z, path]
                subprocess.run(cmd)
                log.info("Changed %s to %s in %s", x, z, path)
    return obj


def is_in_dir(filepath, directory):
    return os.path.realpath(filepath).startswith(os.path.realpath(directory) + os.sep)


def patch_rpath(path, new_rpath, only_relative=True):
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


def handle_elf(path, libs, rpath_only, root=None):
    if root is None:
        root = libs
    proc = subprocess.run(["ldd", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    needs_rpath = False
    for line in proc.stdout.decode().splitlines():
        if line.find("=>") == -1:
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
            log.warning("File already within root directory: %s", linked_lib)
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

        patch_rpath(path, relpath)


def main(root, libs_dir=None, rpath_only=True, log_level="INFO"):
    dirs = work_dirs()
    logging.basicConfig(
        level=logging.getLevelName(log_level.upper()),
        format="%(asctime)s %(message)s",
        filename=str(dirs.logs / "relocate.py.log"),
        filemode="w",
    )
    root_dir = str(pathlib.Path(root).resolve())
    if libs_dir is None:
        libs_dir = pathlib.Path(root_dir, "lib")
    libs_dir = str(pathlib.Path(libs_dir).resolve())
    rpath_only = rpath_only
    processed = {}
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
    main()
