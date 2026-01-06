# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Build functions for specific dependencies.
"""
from __future__ import annotations

import pathlib
import shutil
import sys
from typing import IO, MutableMapping, TYPE_CHECKING

from relenv.common import PlatformError, runcmd

if TYPE_CHECKING:
    from .builder import Dirs


def build_default(env: MutableMapping[str, str], dirs: Dirs, logfp: IO[str]) -> None:
    """
    The default build function if none is given during the build process.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    cmd = [
        "./configure",
        "--prefix={}".format(dirs.prefix),
    ]
    if env["RELENV_HOST"].find("linux") > -1:
        cmd += [
            "--build={}".format(env["RELENV_BUILD"]),
            "--host={}".format(env["RELENV_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_openssl_fips(
    env: MutableMapping[str, str], dirs: Dirs, logfp: IO[str]
) -> None:
    """Build OpenSSL with FIPS module."""
    return build_openssl(env, dirs, logfp, fips=True)


def build_openssl(
    env: MutableMapping[str, str],
    dirs: Dirs,
    logfp: IO[str],
    fips: bool = False,
) -> None:
    """
    Build openssl.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    arch = "aarch64"
    if sys.platform == "darwin":
        plat = "darwin64"
        if env["RELENV_HOST_ARCH"] == "x86_64":
            arch = "x86_64-cc"
        elif env["RELENV_HOST_ARCH"] == "arm64":
            arch = "arm64-cc"
        else:
            raise PlatformError(f"Unable to build {env['RELENV_HOST_ARCH']}")
        extended_cmd = []
    else:
        plat = "linux"
        if env["RELENV_HOST_ARCH"] == "x86_64":
            arch = "x86_64"
        elif env["RELENV_HOST_ARCH"] == "aarch64":
            arch = "aarch64"
        else:
            raise PlatformError(f"Unable to build {env['RELENV_HOST_ARCH']}")
        extended_cmd = [
            "-Wl,-z,noexecstack",
        ]
    if fips:
        extended_cmd.append("enable-fips")
    cmd = [
        "./Configure",
        f"{plat}-{arch}",
        f"--prefix={dirs.prefix}",
        "--openssldir=/etc/ssl",
        "--libdir=lib",
        "--api=1.1.1",
        "--shared",
        "--with-rand-seed=os,egd",
        "enable-md2",
        "enable-egd",
        "no-idea",
    ]
    cmd.extend(extended_cmd)
    runcmd(
        cmd,
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    if fips:
        shutil.copy(
            pathlib.Path("providers") / "fips.so",
            pathlib.Path(dirs.prefix) / "lib" / "ossl-modules",
        )
    else:
        runcmd(["make", "install_sw"], env=env, stderr=logfp, stdout=logfp)


def build_sqlite(env: MutableMapping[str, str], dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build sqlite.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    # extra_cflags=('-Os '
    #              '-DSQLITE_ENABLE_FTS5 '
    #              '-DSQLITE_ENABLE_FTS4 '
    #              '-DSQLITE_ENABLE_FTS3_PARENTHESIS '
    #              '-DSQLITE_ENABLE_JSON1 '
    #              '-DSQLITE_ENABLE_RTREE '
    #              '-DSQLITE_TCL=0 '
    #              )
    # configure_pre=[
    #    '--enable-threadsafe',
    #    '--enable-shared=no',
    #    '--enable-static=yes',
    #    '--disable-readline',
    #    '--disable-dependency-tracking',
    # ]
    cmd = [
        "./configure",
        #     "--with-shared",
        #    "--without-static",
        "--enable-threadsafe",
        "--disable-readline",
        "--disable-dependency-tracking",
        "--prefix={}".format(dirs.prefix),
        #    "--enable-add-ons=nptl,ports",
    ]
    if env["RELENV_HOST"].find("linux") > -1:
        cmd += [
            "--build={}".format(env["RELENV_BUILD_ARCH"]),
            "--host={}".format(env["RELENV_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)
