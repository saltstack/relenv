# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
The linux build process.
"""
import pathlib
import tempfile
from .common import *
from ..common import arches, LINUX, Version


ARCHES = arches[LINUX]

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


def populate_env(env, dirs):
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


def build_bzip2(env, dirs, logfp):
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


def build_libxcrypt(env, dirs, logfp):
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


def build_gdbm(env, dirs, logfp):
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


def build_ncurses(env, dirs, logfp):
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


def build_readline(env, dirs, logfp):
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


def build_libffi(env, dirs, logfp):
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


def build_zlib(env, dirs, logfp):
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


def build_krb(env, dirs, logfp):
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

    # Patch libexpat
    bash_refresh = pathlib.Path(dirs.source) / "Modules" / "expat" / "refresh.sh"
    runcmd(
        [
            "sed",
            "-i",
            's/^expected_libexpat_tag.*$/expected_libexpat_tag="R_2_7_3"',
            bash_refresh,
        ]
    )
    runcmd(
        [
            "sed",
            "-i",
            's/^expected_libexpat_ver.*$/expected_libexpat_version="2.7.3"',
            bash_refresh,
        ]
    )
    expat_hash = "821ac9710d2c073eaf13e1b1895a9c9aa66c1157a99635c639fbff65cdbdd732"
    runcmd(
        [
            "sed",
            "-i",
            f's/^expected_libexpat_sha.*$/expected_libexpat_sha256="{expat_hash}"',
            bash_refresh,
        ]
    )
    run_cmd([bash_refresh])

    print("#" * 80)
    expat_root = pathlib.Path(dirs.source) / "Modules" / "expat"
    run_cmd(["cat", expat_root / "expat.h"])
    run_cmd(["cat", expat_root / "internal.h"])
    run_cmd(["cat", expat_root / "refresh.sh"])
    run_cmd(["cat", expat_root / "xmlparse.c"])
    run_cmd(["cat", expat_root / "xmlrole.h"])
    print("#" * 80)

    if pathlib.Path("setup.py").exists():
        with tempfile.NamedTemporaryFile(mode="w", suffix="_patch") as patch_file:
            patch_file.write(PATCH)
            patch_file.flush()
            runcmd(
                ["patch", "-p0", "-i", patch_file.name],
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

build.add(
    "openssl",
    build_func=build_openssl,
    download={
        "url": "https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz",
        "version": "3.5.4",
        "checksum": "b75daac8e10f189abe28a076ba5905d363e4801f",
        "checkfunc": tarball_version,
        "checkurl": "https://www.openssl.org/source/",
    },
)

build.add(
    "openssl-fips-module",
    build_func=build_openssl_fips,
    wait_on=["openssl"],
    download={
        "url": "https://www.openssl.org/source/openssl-{version}.tar.gz",
        "version": "3.1.2",
        "checksum": "206036c21264e53f0196f715d81d905742e6245b",
        "checkfunc": tarball_version,
        "checkurl": "https://www.openssl.org/source/",
    },
)


build.add(
    "libxcrypt",
    download={
        "url": "https://github.com/besser82/libxcrypt/releases/download/v{version}/libxcrypt-{version}.tar.xz",
        "version": "4.4.38",
        "checksum": "9aa2fa261be6144af492e9b6bfd03bfaa47f7159",
        "checkfunc": github_version,
        "checkurl": "https://github.com/besser82/libxcrypt/releases/",
    },
)

build.add(
    "XZ",
    download={
        "url": "http://tukaani.org/xz/xz-{version}.tar.gz",
        "version": "5.8.1",
        "checksum": "ed4d5589c4cfe84e1697bd02a9954b76af336931",
        "checkfunc": tarball_version,
    },
)

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": "https://sqlite.org/2025/sqlite-autoconf-{version}.tar.gz",
        "version": "3500400",
        "checksum": "145048005c777796dd8494aa1cfed304e8c34283",
        "checkfunc": sqlite_version,
        "checkurl": "https://sqlite.org/",
    },
)

build.add(
    name="bzip2",
    build_func=build_bzip2,
    download={
        "url": "https://sourceware.org/pub/bzip2/bzip2-{version}.tar.gz",
        "version": "1.0.8",
        "checksum": "bf7badf7e248e0ecf465d33c2f5aeec774209227",
        "checkfunc": tarball_version,
    },
)

build.add(
    name="gdbm",
    build_func=build_gdbm,
    download={
        "url": "https://mirrors.ocf.berkeley.edu/gnu/gdbm/gdbm-{version}.tar.gz",
        "version": "1.26",
        "checksum": "6cee3657de948e691e8df26509157be950cef4d4",
        "checkfunc": tarball_version,
    },
)

build.add(
    name="ncurses",
    build_func=build_ncurses,
    download={
        "url": "https://mirrors.ocf.berkeley.edu/gnu/ncurses/ncurses-{version}.tar.gz",
        "version": "6.5",
        "checksum": "cde3024ac3f9ef21eaed6f001476ea8fffcaa381",
        "checkfunc": tarball_version,
    },
)

build.add(
    "libffi",
    build_libffi,
    download={
        "url": "https://github.com/libffi/libffi/releases/download/v{version}/libffi-{version}.tar.gz",
        "version": "3.5.2",
        "checksum": "2bd35b135b0eeb5c631e02422c9dbe786ddb626a",
        "checkfunc": github_version,
        "checkurl": "https://github.com/libffi/libffi/releases/",
    },
)

build.add(
    "zlib",
    build_zlib,
    download={
        "url": "https://zlib.net/fossils/zlib-{version}.tar.gz",
        "version": "1.3.1",
        "checksum": "f535367b1a11e2f9ac3bec723fb007fbc0d189e5",
        "checkfunc": tarball_version,
    },
)

build.add(
    "uuid",
    download={
        "url": "https://sourceforge.net/projects/libuuid/files/libuuid-{version}.tar.gz",
        "version": "1.0.3",
        "checksum": "46eaedb875ae6e63677b51ec583656199241d597",
        "checkfunc": uuid_version,
    },
)

build.add(
    "krb5",
    build_func=build_krb,
    wait_on=["openssl"],
    download={
        "url": "https://kerberos.org/dist/krb5/{version}/krb5-{version}.tar.gz",
        "version": "1.22",
        "checksum": "3ad930ab036a8dc3678356fbb9de9246567e7984",
        "checkfunc": krb_version,
        "checkurl": "https://kerberos.org/dist/krb5/",
    },
)

build.add(
    "readline",
    build_func=build_readline,
    wait_on=["ncurses"],
    download={
        "url": "https://mirrors.ocf.berkeley.edu/gnu/readline/readline-{version}.tar.gz",
        "version": "8.3",
        "checksum": "2c05ae9350b695f69d70b47f17f092611de2081f",
        "checkfunc": tarball_version,
    },
)

build.add(
    "tirpc",
    wait_on=[
        "krb5",
    ],
    download={
        "url": "https://sourceforge.net/projects/libtirpc/files/libtirpc-{version}.tar.bz2",
        # "url": "https://downloads.sourceforge.net/projects/libtirpc/files/libtirpc-{version}.tar.bz2",
        "version": "1.3.4",
        "checksum": "63c800f81f823254d2706637bab551dec176b99b",
        "checkfunc": tarball_version,
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
        "checkfunc": python_version,
        "checkurl": "https://www.python.org/ftp/python/",
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
