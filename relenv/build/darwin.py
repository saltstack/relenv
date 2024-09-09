# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The darwin build process.
"""
import io

from ..common import arches, DARWIN, MACOS_DEVELOPMENT_TARGET
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
    env["MACOSX_DEPLOYMENT_TARGET"] = MACOS_DEVELOPMENT_TARGET
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


build = builds.add("darwin", populate_env=populate_env, version="3.10.14")

build.add(
    "openssl",
    build_func=build_openssl,
    download={
        "url": "https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz",
        "version": "3.2.3",
        "checksum": "1c04294b2493a868ac5f65d166c29625181a31ed",
    },
)

build.add(
    "XZ",
    download={
        "fallback_url": "http://tukaani.org/xz/xz-{version}.tar.gz",
        "url": "https://woz.io/relenv/dependencies/xz-{version}.tar.gz",
        "version": "5.6.2",
        "checksum": "0d6b10e4628fe08e19293c65e8dbcaade084a083",
    },
)

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": "https://sqlite.org/2024/sqlite-autoconf-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/sqlite-autoconf-{version}.tar.gz",
        "version": "3460000",
        "checksum": "cab1c195dbb477f4ab8939ca6c58c62230e5ceea",
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
        "checksum": "05148354ce821ba7369e5b7958435400",
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

build = build.copy(
    version="3.11.9", checksum="926cd6a577b2e8dcbb17671b30eda04019328ada"
)
builds.add("darwin", builder=build)

build = build.copy(
    version="3.12.4", checksum="c221421f3ba734daaf013dbdc7b48aa725cea18e"
)
builds.add("darwin", builder=build)
