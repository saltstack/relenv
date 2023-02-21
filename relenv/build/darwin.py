# Copyright 2022-2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The darwin build process.
"""
import io

from ..common import arches, DARWIN
from .common import runcmd, finalize, build_openssl, build_sqlite, builds

ARCHES = arches[DARWIN]


def populate_env(env, dirs):
    """
    Make sure we have the correct environment variables set.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    """
    env["CC"] = "clang"
    ldflags = [
        "-Wl,-rpath,{prefix}/lib",
        "-L{prefix}/lib",
    ]
    env["LDFLAGS"] = " ".join(ldflags).format(prefix=dirs.prefix)
    env["MACOSX_DEPLOYMENT_TARGET"] = "10.15"
    cflags = [
        "-L{prefix}/lib",
        "-I{prefix}/include",
        "-I{prefix}/include/readline",
    ]
    env["CFLAGS"] = " ".join(cflags).format(prefix=dirs.prefix)


def build_python(env, dirs, logfp):
    """
    Run the commands to build Python.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    env["LDFLAGS"] = "-Wl,-rpath,{prefix}/lib {ldflags}".format(
        prefix=dirs.prefix, ldflags=env["LDFLAGS"]
    )
    runcmd(
        [
            "./configure",
            "-v",
            "--prefix={}".format(dirs.prefix),
            "--with-openssl={}".format(dirs.prefix),
            "--enable-optimizations",
            "--disable-test-modules",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    with io.open("Modules/Setup", "a+") as fp:
        fp.seek(0, io.SEEK_END)
        fp.write("*disabled*\n" "_tkinter\n" "nsl\n" "ncurses\n" "nis\n")
    runcmd(
        ["sed", "s/#zlib/zlib/g", "Modules/Setup"], env=env, stderr=logfp, stdout=logfp
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


build = builds.add("darwin", populate_env=populate_env, version="3.10.10")

build.add(
    "OpenSSL",
    build_func=build_openssl,
    download={
        "url": "https://www.openssl.org/source/openssl-{version}.tar.gz",
        "version": "1.1.1t",
        "md5sum": "1cfee919e0eac6be62c88c5ae8bcd91e",
    },
)

build.add(
    "XZ",
    download={
        "url": "http://tukaani.org/xz/xz-{version}.tar.gz",
        "version": "5.4.1",
        "md5sum": "7e7454778b4cfae238a7660521b29b38",
    },
)

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": "https://sqlite.org/2022/sqlite-autoconf-{version}.tar.gz",
        "version": "3400100",
        "md5sum": "42175b1a1d23529cb133bbd2b5900afd",
    },
)

build.add(
    "python",
    build_func=build_python,
    wait_on=[
        "OpenSSL",
        "XZ",
        "SQLite",
    ],
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "version": build.version,
    },
)


build.add(
    "relenv-finalize",
    build_func=finalize,
    wait_on=[
        "python",
    ],
)

build = build.copy(version="3.11.2")
builds.add("darwin", builder=build)
