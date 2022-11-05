# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2
# Toying around with what sanity checks we might run during a build
import logging
import os
import subprocess

log = logging.getLogger(__name__)


def is_elf(path):
    with open(path, "rb") as fp:
        magic = fp.read(4)
    return magic == b"\x7f\x45\x4c\x46"


def get_rpath(path):
    proc = subprocess.run(
        ["readelf", "-d", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return parse_rpath(proc.stdout.decode())


def parse_rpath(stdout):
    for line in stdout.splitlines():
        # Find either RPATH or READPATH
        if line.find("PATH") == -1:
            continue
        return [_.strip() for _ in line.split("[", 1)[1].split("]")[0].split(":")]
    return []


def get_libs(path):
    proc = subprocess.run(["ldd", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return parse_libs(proc.stdout.decode())


def parse_libs(stdout):
    parsed = []
    for _ in stdout.splitlines():
        lib, addr = _.rsplit("(", 1)
        try:
            name, loc = [_.strip() for _ in lib.split("=>")]
        except:
            name, loc = lib.strip(), None
        parsed.append((name, loc))
    return parsed


def is_in_dir(filepath, directory):
    return os.path.realpath(filepath).startswith(os.path.realpath(directory) + os.sep)


def handle_elf(path):
    print("> {}".format(path))
    print(get_rpath(path))
    rootdir = "/home/dan/src/Relenv/build"
    glibcdir = "/home/dan/src/Relenv/build/glibc"
    errors = []
    for name, loc in get_libs(path):
        if loc is None:
            print("- {}".format(name))
            if name not in ("/lib64/ld-linux-x86-64.so.2", "linux-vdso.so.1"):
                errors.append(
                    "Unknown library referenced by name only: {}".format(name)
                )
        else:
            if not is_in_dir(loc, rootdir):
                # Only glibc libraries should be linked outside of root
                libname = os.path.basename(loc)
                if not os.path.exists(os.path.join(glibcdir, "lib", libname)):
                    errors.append("Not a glibc lib: {}".format(libname))
                    print("+ {} => {}".format(name, loc))
    return errors


def main():
    root_dir = "build/bin"
    # root_dir = '/tmp/cross'
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            path = os.path.join(root, file)
            # if path in processed:
            #    continue
            log.debug("Checking %s", path)
            # if is_macho(path):
            #    log.info("Found Mach-O %s", path)
            #    _ = handle_macho(path, libs_dir)
            #    if _ is not None:
            #        processed[path] = _
            #        found = True
            if is_elf(path):
                log.info("Found ELF %s", path)
                handle_elf(path)  # , libs_dir, root_dir)


if __name__ == "__main__":
    main()
