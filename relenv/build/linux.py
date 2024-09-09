# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The linux build process.
"""
import pathlib
import tempfile
from .common import *
from ..common import arches, LINUX


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
    env["CC"] = "{}/bin/{}-gcc -no-pie".format(dirs.toolchain, env["RELENV_HOST"])
    env["CXX"] = "{}/bin/{}-g++ -no-pie".format(dirs.toolchain, env["RELENV_HOST"])
    # Add our toolchain binaries to the path. We also add the bin directory of
    # our prefix so that libtirpc can find krb5-config
    env["PATH"] = "{}/bin/:{}/bin/:{PATH}".format(dirs.toolchain, dirs.prefix, **env)
    ldflags = [
        "-Wl,--build-id=sha1",
        "-Wl,--rpath={prefix}/lib",
        "-L{prefix}/lib",
        "-L{}/{RELENV_HOST}/sysroot/lib".format(dirs.toolchain, **env),
        "-static-libstdc++",
    ]
    env["LDFLAGS"] = " ".join(ldflags).format(prefix=dirs.prefix)
    cflags = [
        "-g",
        "-I{prefix}/include",
        "-I{prefix}/include/readline",
        "-I{prefix}/include/ncursesw",
        "-I{}/{RELENV_HOST}/sysroot/usr/include".format(dirs.toolchain, **env),
    ]
    env["CFLAGS"] = " ".join(cflags).format(prefix=dirs.prefix)
    # CPPFLAGS are needed for Python's setup.py to find the 'nessicery bits'
    # for things like zlib and sqlite.
    cpplags = [
        "-I{prefix}/include",
        "-I{prefix}/include/readline",
        "-I{prefix}/include/ncursesw",
        "-I{}/{RELENV_HOST}/sysroot/usr/include".format(dirs.toolchain, **env),
    ]
    env["CPPFLAGS"] = " ".join(cpplags).format(prefix=dirs.prefix)
    env["CXXFLAGS"] = " ".join(cpplags).format(prefix=dirs.prefix)
    env["LD_LIBRARY_PATH"] = "{prefix}/lib"
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
            "PREFIX={}".format(dirs.prefix),
            "LDFLAGS={}".format(env["LDFLAGS"]),
            "CFLAGS=-fPIC",
            "CC={}".format(env["CC"]),
            "BUILD={}".format("x86_64-linux-gnu"),
            "HOST={}".format(env["RELENV_HOST"]),
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
            "CC={}".format(env["CC"]),
            "LDFLAGS={}".format(env["LDFLAGS"]),
            "BUILD={}".format("x86_64-linux-gnu"),
            "HOST={}".format(env["RELENV_HOST"]),
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
            "--prefix={}".format(dirs.prefix),
            # "--enable-libgdbm-compat",
            "--build={}".format(env["RELENV_BUILD"]),
            "--host={}".format(env["RELENV_HOST"]),
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
            "--prefix={}".format(dirs.prefix),
            "--enable-libgdbm-compat",
            "--build={}".format(env["RELENV_BUILD"]),
            "--host={}".format(env["RELENV_HOST"]),
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
            "--build={}".format(env["RELENV_BUILD"]),
            "--host={}".format(env["RELENV_HOST"]),
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(
        [
            "make",
            "DESTDIR={}".format(dirs.prefix),
            "TIC_PATH={}".format(str(pathlib.Path(dirs.tmpbuild) / "progs" / "tic")),
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
            "--prefix={}".format(dirs.prefix),
            "--disable-multi-os-directory",
            "--build={}".format(env["RELENV_BUILD"]),
            "--host={}".format(env["RELENV_HOST"]),
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
    env["CFLAGS"] = "-fPIC {}".format(env["CFLAGS"])
    runcmd(
        [
            "./configure",
            "--prefix={}".format(dirs.prefix),
            "--libdir={}/lib".format(dirs.prefix),
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
            "--prefix={}".format(dirs.prefix),
            "--without-system-verto",
            "--without-libedit",
            "--build={}".format(env["RELENV_BUILD"]),
            "--host={}".format(env["RELENV_HOST"]),
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
    env["LDFLAGS"] = "-Wl,--rpath={prefix}/lib {ldflags}".format(
        prefix=dirs.prefix, ldflags=env["LDFLAGS"]
    )

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
    runcmd(
        [
            "sed",
            "-i",
            "s/#readline readline.c -lreadline -ltermcap/readline readline.c -lreadline -ltinfow/g",
            "Modules/Setup",
        ]
    )
    with io.open("Modules/Setup", "a+") as fp:
        fp.seek(0, io.SEEK_END)
        fp.write("*disabled*\n" "_tkinter\n" "nsl\n" "nis\n")
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

    # RELENVCROSS=relenv/_build/aarch64-linux-gnu  relenv/_build/x86_64-linux-gnu/bin/python3 -m ensurepip
    # python = dirs.prefix / "bin" / "python3"
    # if env["RELENV_BUILD_ARCH"] == "aarch64":
    #    python = env["RELENV_NATIVE_PY"]
    # env["PYTHONUSERBASE"] = dirs.prefix
    # runcmd([str(python), "-m", "ensurepip", "-U"], env=env, stderr=logfp, stdout=logfp)


build = builds.add("linux", populate_env=populate_env, version="3.10.14")

build.add(
    "openssl",
    build_func=build_openssl,
    download={
        "url": "https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/openssl-{version}.tar.gz",
        "version": "3.2.3",
        "checksum": "1c04294b2493a868ac5f65d166c29625181a31ed",
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
        "fallback_url": "https://woz.io/relenv/dependencies/openssl-{version}.tar.gz",
        "version": "3.0.8",
        "checksum": "580d8a7232327fe1fa6e7db54ac060d4321f40ab",
        "checkfunc": tarball_version,
        "checkurl": "https://www.openssl.org/source/",
    },
)


build.add(
    "libxcrypt",
    download={
        "url": "https://github.com/besser82/libxcrypt/releases/download/v{version}/libxcrypt-{version}.tar.xz",
        "version": "4.4.36",
        "checksum": "c040de2fd534f84082c9c42114ba11b4e1a67635",
        "checkfunc": github_version,
        "checkurl": "https://github.com/besser82/libxcrypt/releases/",
    },
)

build.add(
    "XZ",
    download={
        "url": "http://tukaani.org/xz/xz-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/xz-{version}.tar.gz",
        "version": "5.6.2",
        "checksum": "0d6b10e4628fe08e19293c65e8dbcaade084a083",
        "checkfunc": tarball_version,
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
        "checkfunc": sqlite_version,
        "checkurl": "https://sqlite.org/",
    },
)

build.add(
    name="bzip2",
    build_func=build_bzip2,
    download={
        "url": "https://sourceware.org/pub/bzip2/bzip2-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/bzip2-{version}.tar.gz",
        "version": "1.0.8",
        "checksum": "bf7badf7e248e0ecf465d33c2f5aeec774209227",
        "checkfunc": tarball_version,
    },
)

build.add(
    name="gdbm",
    build_func=build_gdbm,
    download={
        "url": "https://ftp.gnu.org/gnu/gdbm/gdbm-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/gdbm-{version}.tar.gz",
        "version": "1.23",
        "checksum": "50ba1b1d45ce33fd44e4fdaaf3b55a9d8f3dc418",
        "checkfunc": tarball_version,
    },
)

build.add(
    name="ncurses",
    build_func=build_ncurses,
    download={
        "url": "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/ncurses-{version}.tar.gz",
        # XXX: Need to work out tinfo linkage
        # "version": "6.5",
        # "checksum": "cde3024ac3f9ef21eaed6f001476ea8fffcaa381",
        "version": "6.4",
        "checksum": "bb5eb3f34b3ecd5bac8d0b58164b847f135b3d62",
        "checkfunc": tarball_version,
    },
)

build.add(
    "libffi",
    build_libffi,
    download={
        "url": "https://github.com/libffi/libffi/releases/download/v{version}/libffi-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/libffi-{version}.tar.gz",
        "version": "3.4.6",
        "checksum": "19251dfee520dff42acefe36bfe76d7168071e01",
        "checkfunc": github_version,
        "checkurl": "https://github.com/libffi/libffi/releases/",
    },
)

build.add(
    "zlib",
    build_zlib,
    download={
        "url": "https://zlib.net/fossils/zlib-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/zlib-{version}.tar.gz",
        "version": "1.3.1",
        "checksum": "f535367b1a11e2f9ac3bec723fb007fbc0d189e5",
        "checkfunc": tarball_version,
    },
)

build.add(
    "uuid",
    download={
        "url": "https://sourceforge.net/projects/libuuid/files/libuuid-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/libuuid-{version}.tar.gz",
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
        "fallback_url": "https://woz.io/relenv/dependencies/krb5-{version}.tar.gz",
        "version": "1.21",
        "checksum": "e2ee531443122376ac8b62b3848d94376f646089",
        "checkfunc": krb_version,
        "checkurl": "https://kerberos.org/dist/krb5/",
    },
)

build.add(
    "readline",
    build_func=build_readline,
    wait_on=["ncurses"],
    download={
        "url": "https://ftp.gnu.org/gnu/readline/readline-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/readline-{version}.tar.gz",
        "version": "8.2",
        "checksum": "97ad98be243a857b639c0f3da2fe7d81c6d1d36e",
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
        "fallback_url": "https://woz.io/relenv/dependencies/libtirpc-{version}.tar.bz2",
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
        "fallback_url": "https://woz.io/relenv/dependencies/Python-{version}.tar.xz",
        "version": build.version,
        "checksum": "9103b4716dff30b40fd0239982f3a2d851143a46",
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

build = build.copy(
    version="3.11.9", checksum="926cd6a577b2e8dcbb17671b30eda04019328ada"
)
builds.add("linux", builder=build)

build = build.copy(
    version="3.12.4", checksum="c221421f3ba734daaf013dbdc7b48aa725cea18e"
)
builds.add("linux", builder=build)
