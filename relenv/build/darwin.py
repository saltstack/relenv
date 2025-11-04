# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2
# mypy: ignore-errors
"""
The darwin build process.
"""
from __future__ import annotations

import glob
import io
import os
import pathlib
import shutil
import tarfile
import time
import urllib.request
from typing import IO, MutableMapping

from ..common import DARWIN, MACOS_DEVELOPMENT_TARGET, arches, runcmd
from .common import (
    Dirs,
    build_openssl,
    build_sqlite,
    builds,
    finalize,
    get_dependency_version,
    update_sbom_checksums,
)

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


def update_expat(dirs: Dirs, env: MutableMapping[str, str]) -> None:
    """
    Update the bundled expat library to the latest version.

    Python ships with an older bundled expat. This function updates it
    to the latest version for security and bug fixes.
    """
    # Get version from JSON
    expat_info = get_dependency_version("expat", "darwin")
    if not expat_info:
        # No update needed, use bundled version
        return

    version = expat_info["version"]
    version_tag = version.replace(".", "_")
    url = f"https://github.com/libexpat/libexpat/releases/download/R_{version_tag}/expat-{version}.tar.xz"

    expat_dir = pathlib.Path(dirs.source) / "Modules" / "expat"
    if not expat_dir.exists():
        # No expat directory, skip
        return

    # Download expat tarball
    tmpbuild = pathlib.Path(dirs.tmpbuild)
    tarball_path = tmpbuild / f"expat-{version}.tar.xz"
    urllib.request.urlretrieve(url, str(tarball_path))

    # Extract tarball
    with tarfile.open(tarball_path) as tar:
        tar.extractall(path=str(tmpbuild))

    # Copy source files to Modules/expat/
    expat_source_dir = tmpbuild / f"expat-{version}" / "lib"
    updated_files = []
    for source_file in ["*.h", "*.c"]:
        for file_path in glob.glob(str(expat_source_dir / source_file)):
            target_file = expat_dir / pathlib.Path(file_path).name
            # Remove old file if it exists
            if target_file.exists():
                target_file.unlink()
            shutil.copy2(file_path, str(expat_dir))
            updated_files.append(target_file)

    # Touch all updated files to ensure make rebuilds them
    # (The tarball may contain files with newer timestamps)
    now = time.time()
    for target_file in updated_files:
        os.utime(target_file, (now, now))

    # Update SBOM with correct checksums for updated expat files
    files_to_update = {}
    for target_file in updated_files:
        # SBOM uses relative paths from Python source root
        relative_path = f"Modules/expat/{target_file.name}"
        files_to_update[relative_path] = target_file

    update_sbom_checksums(dirs.source, files_to_update)


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
    # Update bundled expat to latest version
    update_expat(dirs, env)

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

# Get dependency versions from JSON (with fallback to hardcoded values)
openssl_info = get_dependency_version("openssl", "darwin")
if openssl_info:
    openssl_version = openssl_info["version"]
    openssl_url = openssl_info["url"]
    openssl_checksum = openssl_info["sha256"]
else:
    openssl_version = "3.5.4"
    openssl_url = "https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz"
    openssl_checksum = "b75daac8e10f189abe28a076ba5905d363e4801f"

build.add(
    "openssl",
    build_func=build_openssl,
    download={
        "url": openssl_url,
        "version": openssl_version,
        "checksum": openssl_checksum,
    },
)

# Get XZ version from JSON
xz_info = get_dependency_version("xz", "darwin")
if xz_info:
    xz_version = xz_info["version"]
    xz_url = xz_info["url"]
    xz_checksum = xz_info["sha256"]
else:
    xz_version = "5.8.1"
    xz_url = "http://tukaani.org/xz/xz-{version}.tar.gz"
    xz_checksum = "ed4d5589c4cfe84e1697bd02a9954b76af336931"

build.add(
    "XZ",
    download={
        "url": xz_url,
        "version": xz_version,
        "checksum": xz_checksum,
    },
)

# Get SQLite version from JSON
sqlite_info = get_dependency_version("sqlite", "darwin")
if sqlite_info:
    sqlite_url = sqlite_info["url"]
    sqlite_checksum = sqlite_info["sha256"]
    sqlite_version_num = sqlite_info.get("sqliteversion", "3500400")
else:
    sqlite_version_num = "3500400"
    sqlite_url = "https://sqlite.org/2025/sqlite-autoconf-{version}.tar.gz"
    sqlite_checksum = "145048005c777796dd8494aa1cfed304e8c34283"

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": sqlite_url,
        "fallback_url": "https://woz.io/relenv/dependencies/sqlite-autoconf-{version}.tar.gz",
        "version": sqlite_version_num,
        "checksum": sqlite_checksum,
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
