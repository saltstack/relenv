# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
The darwin build process.
"""
from __future__ import annotations

import io
from typing import IO, MutableMapping

from ..common import DARWIN, MACOS_DEVELOPMENT_TARGET, arches
from .common import Dirs, build_openssl, build_sqlite, builds, finalize, runcmd

ARCHES = arches[DARWIN]


def populate_env(env: MutableMapping[str, str], dirs: Dirs) -> None:
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
    env["MACOSX_DEPLOYMENT_TARGET"] = MACOS_DEVELOPMENT_TARGET
    cflags = [
        "-I{prefix}/include",
        "-I{prefix}/include/readline",
    ]
    env["CFLAGS"] = " ".join(cflags).format(prefix=dirs.prefix)


def build_python(env: MutableMapping[str, str], dirs: Dirs, logfp: IO[str]) -> None:
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


build = builds.add("darwin", populate_env=populate_env)

build.add(
    "openssl",
    build_func=build_openssl,
    download={
        "url": "https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz",
        "version": "3.5.4",
        "checksum": "b75daac8e10f189abe28a076ba5905d363e4801f",
    },
)

build.add(
    "XZ",
    download={
        "url": "http://tukaani.org/xz/xz-{version}.tar.gz",
        "version": "5.8.1",
        "checksum": "ed4d5589c4cfe84e1697bd02a9954b76af336931",
    },
)

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": "https://sqlite.org/2025/sqlite-autoconf-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/sqlite-autoconf-{version}.tar.gz",
        "version": "3500400",
        "checksum": "145048005c777796dd8494aa1cfed304e8c34283",
    },
)

build.add(
    "python",
    build_func=build_python,
    wait_on=[
        "openssl",
        "XZ",
        "SQLite",
    ],
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "fallback_url": "https://woz.io/relenv/dependencies/Python-{version}.tar.gz",
        "version": build.version,
        "checksum": "d31d548cd2c5ca2ae713bebe346ba15e8406633a",
    },
)


build.add(
    "relenv-finalize",
    build_func=finalize,
    wait_on=[
        "python",
    ],
)
