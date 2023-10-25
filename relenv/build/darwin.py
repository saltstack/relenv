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


build = builds.add("darwin", populate_env=populate_env, version="3.10.13")

build.add(
    "openssl",
    build_func=build_openssl,
    download={
        "url": "https://www.openssl.org/source/openssl-{version}.tar.gz",
        "version": "3.1.3",
        "md5sum": "ece430df6d3158913df0950cc70ea2b2",
    },
)

build.add(
    "XZ",
    download={
        "url": "http://tukaani.org/xz/xz-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/xz-{version}.tar.gz",
        "version": "5.4.4",
        "md5sum": "b9c34fed669c3e84aa1fa1246a99943b",
    },
)

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": "https://sqlite.org/2023/sqlite-autoconf-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/sqlite-autoconf-{version}.tar.gz",
        "version": "3430100",
        "md5sum": "77e61befe9c3298da0504f87772a24b0",
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
        "md5sum": "8847dc6458d1431d0ae0f55942deeb89",
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

build = build.copy(version="3.11.6", md5sum="d0c5a1a31efe879723e51addf56dd206")
builds.add("darwin", builder=build)
build = build.copy(version="3.9.18", md5sum="765576c3af57deb046819ecd57804bbb")
builds.add("darwin", builder=build)
