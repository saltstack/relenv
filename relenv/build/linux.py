# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2
# mypy: ignore-errors
"""
The linux build process.
"""
from __future__ import annotations

import glob
import io
import os
import pathlib
import shutil
import tarfile
import tempfile
import time
import urllib.request
from typing import IO, MutableMapping

from .common import (
    Dirs,
    build_openssl,
    build_openssl_fips,
    build_sqlite,
    builds,
    finalize,
    get_dependency_version,
    runcmd,
    update_sbom_checksums,
)
from ..common import LINUX, Version, arches, runcmd


ARCHES = arches[LINUX]

EnvMapping = MutableMapping[str, str]

# Patch for Python's setup.py
PATCH = """--- ./setup.py
+++ ./setup.py
@@ -664,6 +664,7 @@
             self.failed.append(ext.name)

     def add_multiarch_paths(self):
+        return
         # Debian/Ubuntu multiarch support.
         # https://wiki.ubuntu.com/MultiarchSpec
         tmpfile = os.path.join(self.build_temp, 'multiarch')
"""


def populate_env(env: EnvMapping, dirs: Dirs) -> None:
    """
    Make sure we have the correct environment variables set.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    """
    # CC and CXX need to be to have the full path to the executable
    env["CC"] = f"{dirs.toolchain}/bin/{env['RELENV_HOST']}-gcc"
    env["CXX"] = f"{dirs.toolchain}/bin/{env['RELENV_HOST']}-g++"
    # Add our toolchain binaries to the path. We also add the bin directory of
    # our prefix so that libtirpc can find krb5-config
    env["PATH"] = f"{dirs.toolchain}/bin/:{dirs.prefix}/bin/:{env['PATH']}"
    ldflags = [
        "-Wl,--build-id=sha1",
        f"-Wl,--rpath={dirs.prefix}/lib",
        f"-L{dirs.prefix}/lib",
        f"-L{dirs.toolchain}/{env['RELENV_HOST']}/sysroot/lib",
    ]
    env["LDFLAGS"] = " ".join(ldflags)
    cflags = [
        "-g",
        f"-I{dirs.prefix}/include",
        f"-I{dirs.prefix}/include/readline",
        f"-I{dirs.prefix}/include/ncursesw",
        f"-I{dirs.toolchain}/{env['RELENV_HOST']}/sysroot/usr/include",
    ]
    env["CFLAGS"] = " ".join(cflags)
    # CPPFLAGS are needed for Python's setup.py to find the 'nessicery bits'
    # for things like zlib and sqlite.
    cpplags = [
        f"-I{dirs.prefix}/include",
        f"-I{dirs.prefix}/include/readline",
        f"-I{dirs.prefix}/include/ncursesw",
        f"-I{dirs.toolchain}/{env['RELENV_HOST']}/sysroot/usr/include",
    ]
    # env["CXXFLAGS"] = " ".join(cpplags)
    env["CPPFLAGS"] = " ".join(cpplags)
    env["PKG_CONFIG_PATH"] = f"{dirs.prefix}/lib/pkgconfig"


def build_bzip2(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build bzip2.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    runcmd(
        [
            "make",
            "-j8",
            f"PREFIX={dirs.prefix}",
            f"LDFLAGS={env['LDFLAGS']}",
            "CFLAGS=-fPIC",
            f"CC={env['CC']}",
            "BUILD=x86_64-linux-gnu",
            f"HOST={env['RELENV_HOST']}",
            "install",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(
        [
            "make",
            "-f",
            "Makefile-libbz2_so",
            f"CC={env['CC']}",
            f"LDFLAGS={env['LDFLAGS']}",
            "BUILD=x86_64-linux-gnu",
            f"HOST={env['RELENV_HOST']}",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    shutil.copy2("libbz2.so.1.0.8", os.path.join(dirs.prefix, "lib"))


def build_libxcrypt(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build libxcrypt.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    runcmd(
        [
            "./configure",
            f"--prefix={dirs.prefix}",
            # "--enable-libgdbm-compat",
            f"--build={env['RELENV_BUILD']}",
            f"--host={env['RELENV_HOST']}",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_gdbm(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build gdbm.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    runcmd(
        [
            "./configure",
            f"--prefix={dirs.prefix}",
            "--enable-libgdbm-compat",
            f"--build={env['RELENV_BUILD']}",
            f"--host={env['RELENV_HOST']}",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_ncurses(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build ncurses.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    configure = pathlib.Path(dirs.source) / "configure"
    if env["RELENV_BUILD_ARCH"] == "aarch64" or env["RELENV_HOST_ARCH"] == "aarch64":
        os.chdir(dirs.tmpbuild)
        runcmd([str(configure)], stderr=logfp, stdout=logfp)
        runcmd(["make", "-C", "include"], stderr=logfp, stdout=logfp)
        runcmd(["make", "-C", "progs", "tic"], stderr=logfp, stdout=logfp)
    os.chdir(dirs.source)

    # Configure with a prefix of '/' so things will be installed to '/lib'
    # instead of '/usr/local/lib'. The root of the install will be specified
    # via the DESTDIR make argument.
    runcmd(
        [
            str(configure),
            "--prefix=/",
            "--with-shared",
            "--enable-termcap",
            "--with-termlib",
            "--without-cxx-shared",
            "--without-static",
            "--without-cxx",
            "--enable-widec",
            "--without-normal",
            "--disable-stripping",
            f"--with-pkg-config={dirs.prefix}/lib/pkgconfig",
            "--enable-pc-files",
            f"--build={env['RELENV_BUILD']}",
            f"--host={env['RELENV_HOST']}",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    ticdir = str(pathlib.Path(dirs.tmpbuild) / "progs" / "tic")
    runcmd(
        [
            "make",
            f"DESTDIR={dirs.prefix}",
            f"TIC_PATH={ticdir}",
            "install",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )


def build_readline(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build readline library.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    env["LDFLAGS"] = f"{env['LDFLAGS']} -ltinfow"
    cmd = [
        "./configure",
        f"--prefix={dirs.prefix}",
    ]
    if env["RELENV_HOST"].find("linux") > -1:
        cmd += [
            f"--build={env['RELENV_BUILD']}",
            f"--host={env['RELENV_HOST']}",
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_libffi(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build libffi.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    runcmd(
        [
            "./configure",
            f"--prefix={dirs.prefix}",
            "--disable-multi-os-directory",
            f"--build={env['RELENV_BUILD']}",
            f"--host={env['RELENV_HOST']}",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    # libffi doens't want to honor libdir, force install to lib instead of lib64
    runcmd(
        ["sed", "-i", "s/lib64/lib/g", "Makefile"], env=env, stderr=logfp, stdout=logfp
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_zlib(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build zlib.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    env["CFLAGS"] = f"-fPIC {env['CFLAGS']}"
    runcmd(
        [
            "./configure",
            f"--prefix={dirs.prefix}",
            f"--libdir={dirs.prefix}/lib",
            "--shared",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-no-pie", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_krb(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Build kerberos.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    if env["RELENV_BUILD_ARCH"] != env["RELENV_HOST_ARCH"]:
        env["krb5_cv_attr_constructor_destructor"] = "yes,yes"
        env["ac_cv_func_regcomp"] = "yes"
        env["ac_cv_printf_positional"] = "yes"
    os.chdir(dirs.source / "src")
    runcmd(
        [
            "./configure",
            f"--prefix={dirs.prefix}",
            "--without-system-verto",
            "--without-libedit",
            f"--build={env['RELENV_BUILD']}",
            f"--host={env['RELENV_HOST']}",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def update_expat(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the bundled expat library to the latest version.

    Python ships with an older bundled expat. This function updates it
    to the latest version for security and bug fixes.
    """
    # Get version from JSON
    expat_info = get_dependency_version("expat", "linux")
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


def build_python(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
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

    ldflagopt = f"-Wl,--rpath={dirs.prefix}/lib"
    if ldflagopt not in env["LDFLAGS"]:
        env["LDFLAGS"] = f"{ldflagopt} {env['LDFLAGS']}"

    # Needed when using a toolchain even if build and host match.
    runcmd(
        [
            "sed",
            "-i",
            "s/ac_cv_buggy_getaddrinfo=yes/ac_cv_buggy_getaddrinfo=no/g",
            "configure",
        ]
    )
    runcmd(
        [
            "sed",
            "-i",
            (
                "s/ac_cv_enable_implicit_function_declaration_error=yes/"
                "ac_cv_enable_implicit_function_declaration_error=no/g"
            ),
            "configure",
        ]
    )

    if pathlib.Path("setup.py").exists():
        with tempfile.NamedTemporaryFile(mode="w", suffix="_patch") as p_file:
            p_file.write(PATCH)
            p_file.flush()
            runcmd(
                ["patch", "-p0", "-i", p_file.name],
                env=env,
                stderr=logfp,
                stdout=logfp,
            )

    env["OPENSSL_CFLAGS"] = f"-I{dirs.prefix}/include  -Wno-coverage-mismatch"
    env["OPENSSL_LDFLAGS"] = f"-L{dirs.prefix}/lib"
    env["CFLAGS"] = f"-Wno-coverage-mismatch {env['CFLAGS']}"

    runcmd(
        [
            "sed",
            "-i",
            "s/#readline readline.c -lreadline -ltermcap/readline readline.c -lreadline -ltinfow/g",
            "Modules/Setup",
        ]
    )
    if Version.parse_string(env["RELENV_PY_MAJOR_VERSION"]) <= Version.parse_string(
        "3.10"
    ):
        runcmd(
            [
                "sed",
                "-i",
                (
                    "s/#_curses -lncurses -lncursesw -ltermcap _cursesmodule.c"
                    "/_curses -lncursesw -ltinfow _cursesmodule.c/g"
                ),
                "Modules/Setup",
            ]
        )
        runcmd(
            [
                "sed",
                "-i",
                (
                    "s/#_curses_panel _curses_panel.c -lpanel -lncurses"
                    "/_curses_panel _curses_panel.c -lpanelw -lncursesw/g"
                ),
                "Modules/Setup",
            ]
        )
    else:
        env["CURSES_LIBS"] = "-lncursesw -ltinfow"
        env["PANEL_LIBS"] = "-lpanelw"

    cmd = [
        "./configure",
        "-v",
        f"--prefix={dirs.prefix}",
        f"--with-openssl={dirs.prefix}",
        "--enable-optimizations",
        "--with-ensurepip=no",
        f"--build={env['RELENV_BUILD']}",
        f"--host={env['RELENV_HOST']}",
        "--disable-test-modules",
        "--with-ssl-default-suites=openssl",
        "--with-builtin-hashlib-hashes=blake2,md5,sha1,sha2,sha3",
        "--with-readline=readline",
        "--with-pkg-config=yes",
    ]

    if env["RELENV_HOST_ARCH"] != env["RELENV_BUILD_ARCH"]:
        # env["RELENV_CROSS"] = dirs.prefix
        cmd += [
            f"--with-build-python={env['RELENV_NATIVE_PY']}",
        ]
    # Needed when using a toolchain even if build and host match.
    cmd += [
        "ac_cv_file__dev_ptmx=yes",
        "ac_cv_file__dev_ptc=no",
    ]

    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    with io.open("Modules/Setup", "a+") as fp:
        fp.seek(0, io.SEEK_END)
        fp.write("*disabled*\n" "_tkinter\n" "nsl\n" "nis\n")
    for _ in ["LDFLAGS", "CFLAGS", "CPPFLAGS", "CXX", "CC"]:
        env.pop(_)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

    # RELENVCROSS=relenv/_build/aarch64-linux-gnu  relenv/_build/x86_64-linux-gnu/bin/python3 -m ensurepip
    # python = dirs.prefix / "bin" / "python3"
    # if env["RELENV_BUILD_ARCH"] == "aarch64":
    #    python = env["RELENV_NATIVE_PY"]
    # env["PYTHONUSERBASE"] = dirs.prefix
    # runcmd([str(python), "-m", "ensurepip", "-U"], env=env, stderr=logfp, stdout=logfp)


build = builds.add("linux", populate_env=populate_env)

# Get dependency versions from JSON (with fallback to hardcoded values)
openssl_info = get_dependency_version("openssl", "linux")
if openssl_info:
    openssl_version = openssl_info["version"]
    openssl_url = openssl_info["url"]
    openssl_checksum = openssl_info["sha256"]
else:
    # Fallback to hardcoded values
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

# If openssl-fips-module runs before openssl we get an error installing openssl
# becuase <prefix>/lib/ossl-modules exists.
build.add(
    "openssl-fips-module",
    wait_on=["openssl"],
    build_func=build_openssl_fips,
    download={
        "url": "https://www.openssl.org/source/openssl-{version}.tar.gz",
        "version": "3.1.2",
        "checksum": "206036c21264e53f0196f715d81d905742e6245b",
    },
)


# Get libxcrypt version from JSON
libxcrypt_info = get_dependency_version("libxcrypt", "linux")
if libxcrypt_info:
    libxcrypt_version = libxcrypt_info["version"]
    libxcrypt_url = libxcrypt_info["url"]
    libxcrypt_checksum = libxcrypt_info["sha256"]
else:
    libxcrypt_version = "4.4.38"
    libxcrypt_url = "https://github.com/besser82/libxcrypt/releases/download/v{version}/libxcrypt-{version}.tar.xz"
    libxcrypt_checksum = "9aa2fa261be6144af492e9b6bfd03bfaa47f7159"

build.add(
    "libxcrypt",
    download={
        "url": libxcrypt_url,
        "version": libxcrypt_version,
        "checksum": libxcrypt_checksum,
    },
)

# Get XZ version from JSON
xz_info = get_dependency_version("xz", "linux")
if xz_info:
    xz_version = xz_info["version"]
    xz_url = xz_info["url"]
    xz_checksum = xz_info["sha256"]
else:
    # Fallback to hardcoded values
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
sqlite_info = get_dependency_version("sqlite", "linux")
if sqlite_info:
    sqlite_url = sqlite_info["url"]
    sqlite_checksum = sqlite_info["sha256"]
    # SQLite uses a special 7-digit version number
    sqlite_version_num = sqlite_info.get("sqliteversion", "3500400")
else:
    # Fallback to hardcoded values
    sqlite_version_num = "3500400"
    sqlite_url = "https://sqlite.org/2025/sqlite-autoconf-{version}.tar.gz"
    sqlite_checksum = "145048005c777796dd8494aa1cfed304e8c34283"

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": sqlite_url,
        "version": sqlite_version_num,
        "checksum": sqlite_checksum,
    },
)

# Get bzip2 version from JSON
bzip2_info = get_dependency_version("bzip2", "linux")
if bzip2_info:
    bzip2_version = bzip2_info["version"]
    bzip2_url = bzip2_info["url"]
    bzip2_checksum = bzip2_info["sha256"]
else:
    bzip2_version = "1.0.8"
    bzip2_url = "https://sourceware.org/pub/bzip2/bzip2-{version}.tar.gz"
    bzip2_checksum = "bf7badf7e248e0ecf465d33c2f5aeec774209227"

build.add(
    name="bzip2",
    build_func=build_bzip2,
    download={
        "url": bzip2_url,
        "version": bzip2_version,
        "checksum": bzip2_checksum,
    },
)

# Get gdbm version from JSON
gdbm_info = get_dependency_version("gdbm", "linux")
if gdbm_info:
    gdbm_version = gdbm_info["version"]
    gdbm_url = gdbm_info["url"]
    gdbm_checksum = gdbm_info["sha256"]
else:
    gdbm_version = "1.26"
    gdbm_url = "https://mirrors.ocf.berkeley.edu/gnu/gdbm/gdbm-{version}.tar.gz"
    gdbm_checksum = "6cee3657de948e691e8df26509157be950cef4d4"

build.add(
    name="gdbm",
    build_func=build_gdbm,
    download={
        "url": gdbm_url,
        "version": gdbm_version,
        "checksum": gdbm_checksum,
    },
)

# Get ncurses version from JSON
ncurses_info = get_dependency_version("ncurses", "linux")
if ncurses_info:
    ncurses_version = ncurses_info["version"]
    ncurses_url = ncurses_info["url"]
    ncurses_checksum = ncurses_info["sha256"]
else:
    ncurses_version = "6.5"
    ncurses_url = (
        "https://mirrors.ocf.berkeley.edu/gnu/ncurses/ncurses-{version}.tar.gz"
    )
    ncurses_checksum = "cde3024ac3f9ef21eaed6f001476ea8fffcaa381"

build.add(
    name="ncurses",
    build_func=build_ncurses,
    download={
        "url": ncurses_url,
        "version": ncurses_version,
        "checksum": ncurses_checksum,
    },
)

# Get libffi version from JSON
libffi_info = get_dependency_version("libffi", "linux")
if libffi_info:
    libffi_version = libffi_info["version"]
    libffi_url = libffi_info["url"]
    libffi_checksum = libffi_info["sha256"]
else:
    libffi_version = "3.5.2"
    libffi_url = "https://github.com/libffi/libffi/releases/download/v{version}/libffi-{version}.tar.gz"
    libffi_checksum = "2bd35b135b0eeb5c631e02422c9dbe786ddb626a"

build.add(
    "libffi",
    build_libffi,
    download={
        "url": libffi_url,
        "version": libffi_version,
        "checksum": libffi_checksum,
    },
)

# Get zlib version from JSON
zlib_info = get_dependency_version("zlib", "linux")
if zlib_info:
    zlib_version = zlib_info["version"]
    zlib_url = zlib_info["url"]
    zlib_checksum = zlib_info["sha256"]
else:
    zlib_version = "1.3.1"
    zlib_url = "https://zlib.net/fossils/zlib-{version}.tar.gz"
    zlib_checksum = "f535367b1a11e2f9ac3bec723fb007fbc0d189e5"

build.add(
    "zlib",
    build_zlib,
    download={
        "url": zlib_url,
        "version": zlib_version,
        "checksum": zlib_checksum,
    },
)

# Get uuid version from JSON
uuid_info = get_dependency_version("uuid", "linux")
if uuid_info:
    uuid_ver = uuid_info["version"]
    uuid_url = uuid_info["url"]
    uuid_checksum = uuid_info["sha256"]
else:
    uuid_ver = "1.0.3"
    uuid_url = "https://sourceforge.net/projects/libuuid/files/libuuid-{version}.tar.gz"
    uuid_checksum = "46eaedb875ae6e63677b51ec583656199241d597"

build.add(
    "uuid",
    download={
        "url": uuid_url,
        "version": uuid_ver,
        "checksum": uuid_checksum,
    },
)

# Get krb5 version from JSON
krb5_info = get_dependency_version("krb5", "linux")
if krb5_info:
    krb5_version = krb5_info["version"]
    krb5_url = krb5_info["url"]
    krb5_checksum = krb5_info["sha256"]
else:
    krb5_version = "1.22"
    krb5_url = "https://kerberos.org/dist/krb5/{version}/krb5-{version}.tar.gz"
    krb5_checksum = "3ad930ab036a8dc3678356fbb9de9246567e7984"

build.add(
    "krb5",
    build_func=build_krb,
    wait_on=["openssl"],
    download={
        "url": krb5_url,
        "version": krb5_version,
        "checksum": krb5_checksum,
    },
)

# Get readline version from JSON
readline_info = get_dependency_version("readline", "linux")
if readline_info:
    readline_version = readline_info["version"]
    readline_url = readline_info["url"]
    readline_checksum = readline_info["sha256"]
else:
    readline_version = "8.3"
    readline_url = (
        "https://mirrors.ocf.berkeley.edu/gnu/readline/readline-{version}.tar.gz"
    )
    readline_checksum = "2c05ae9350b695f69d70b47f17f092611de2081f"

build.add(
    "readline",
    build_func=build_readline,
    wait_on=["ncurses"],
    download={
        "url": readline_url,
        "version": readline_version,
        "checksum": readline_checksum,
    },
)

# Get tirpc version from JSON
tirpc_info = get_dependency_version("tirpc", "linux")
if tirpc_info:
    tirpc_version = tirpc_info["version"]
    tirpc_url = tirpc_info["url"]
    tirpc_checksum = tirpc_info["sha256"]
else:
    tirpc_version = "1.3.4"
    tirpc_url = (
        "https://sourceforge.net/projects/libtirpc/files/libtirpc-{version}.tar.bz2"
    )
    tirpc_checksum = "63c800f81f823254d2706637bab551dec176b99b"

build.add(
    "tirpc",
    wait_on=[
        "krb5",
    ],
    download={
        "url": tirpc_url,
        # "url": "https://downloads.sourceforge.net/projects/libtirpc/files/libtirpc-{version}.tar.bz2",
        "version": tirpc_version,
        "checksum": tirpc_checksum,
    },
)

build.add(
    "python",
    build_func=build_python,
    wait_on=[
        "openssl",
        "libxcrypt",
        "XZ",
        "SQLite",
        "bzip2",
        "gdbm",
        "ncurses",
        "libffi",
        "zlib",
        "uuid",
        "krb5",
        "readline",
        "tirpc",
    ],
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "version": build.version,
        "checksum": "d31d548cd2c5ca2ae713bebe346ba15e8406633a",
    },
)


build.add(
    "relenv-finalize",
    build_func=finalize,
    wait_on=[
        "python",
        "openssl-fips-module",
    ],
)
