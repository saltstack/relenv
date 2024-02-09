# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The linux build process.
"""
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
    env["PATH"] = "{}/bin/:{PATH}".format(dirs.toolchain, **env)
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
    runcmd(
        [
            str(configure),
            "--prefix=/",
            "--with-shared",
            "--without-cxx-shared",
            "--without-static",
            "--without-cxx",
            "--enable-widec",
            "--without-normal",
            "--disable-stripping",
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

    with open("/tmp/patch", "w") as fp:
        fp.write(PATCH)
    runcmd(["patch", "-p0", "-i", "/tmp/patch"], env=env, stderr=logfp, stdout=logfp)

    env["PKG_CONFIG_PATH"] = f"{dirs.prefix}/lib/pkgconfig"
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
        "--with-builtin-hashlib-hashes=blake2",
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
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

    # RELENVCROSS=relenv/_build/aarch64-linux-gnu  relenv/_build/x86_64-linux-gnu/bin/python3 -m ensurepip
    # python = dirs.prefix / "bin" / "python3"
    # if env["RELENV_BUILD_ARCH"] == "aarch64":
    #    python = env["RELENV_NATIVE_PY"]
    # env["PYTHONUSERBASE"] = dirs.prefix
    # runcmd([str(python), "-m", "ensurepip", "-U"], env=env, stderr=logfp, stdout=logfp)


build = builds.add("linux", populate_env=populate_env, version="3.10.13")

build.add(
    "openssl",
    build_func=build_openssl,
    download={
        "url": "https://www.openssl.org/source/openssl-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/openssl-{version}.tar.gz",
        "version": "3.1.5",
        "md5sum": "567235bf15ad72fcb9555e3b1c8ee4bc",
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
        "md5sum": "61e017cf4fea1b599048f621f1490fbd",
        "checkfunc": tarball_version,
        "checkurl": "https://www.openssl.org/source/",
    },
)


build.add(
    "libxcrypt",
    download={
        "url": "https://github.com/besser82/libxcrypt/releases/download/v{version}/libxcrypt-{version}.tar.xz",
        "version": "4.4.36",
        "md5sum": "b84cd4104e08c975063ec6c4d0372446",
        "checkfunc": github_version,
        "checkurl": "https://github.com/besser82/libxcrypt/releases/",
    },
)

build.add(
    "XZ",
    download={
        "url": "http://tukaani.org/xz/xz-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/xz-{version}.tar.gz",
        "version": "5.4.4",
        "md5sum": "b9c34fed669c3e84aa1fa1246a99943b",
        "checkfunc": tarball_version,
    },
)

build.add(
    name="SQLite",
    build_func=build_sqlite,
    download={
        "url": "https://sqlite.org/2023/sqlite-autoconf-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/sqlite-autoconf-{version}.tar.gz",
        "version": "3430200",
        "md5sum": "94fb06bfebc437762e489c355ae63716",
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
        "md5sum": "67e051268d0c475ea773822f7500d0e5",
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
        "md5sum": "8551961e36bf8c70b7500d255d3658ec",
        "checkfunc": tarball_version,
    },
)

build.add(
    name="ncurses",
    build_func=build_ncurses,
    wait_on=["readline"],
    download={
        "url": "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/ncurses-{version}.tar.gz",
        "version": "6.4",
        "md5sum": "5a62487b5d4ac6b132fe2bf9f8fad29b",
        "checkfunc": tarball_version,
    },
)

build.add(
    "libffi",
    build_libffi,
    download={
        "url": "https://github.com/libffi/libffi/releases/download/v{version}/libffi-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/libffi-{version}.tar.gz",
        "version": "3.4.4",
        "md5sum": "0da1a5ed7786ac12dcbaf0d499d8a049",
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
        "version": "1.3",
        "md5sum": "60373b133d630f74f4a1f94c1185a53f",
        "checkfunc": tarball_version,
    },
)

build.add(
    "uuid",
    download={
        "url": "https://sourceforge.net/projects/libuuid/files/libuuid-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/libuuid-{version}.tar.gz",
        "version": "1.0.3",
        "md5sum": "d44d866d06286c08ba0846aba1086d68",
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
        "md5sum": "304b335236d86a7e8effec31bd782baf",
        "checkfunc": krb_version,
        "checkurl": "https://kerberos.org/dist/krb5/",
    },
)

build.add(
    "readline",
    download={
        "url": "https://ftp.gnu.org/gnu/readline/readline-{version}.tar.gz",
        "fallback_url": "https://woz.io/relenv/dependencies/readline-{version}.tar.gz",
        "version": "8.2",
        "md5sum": "4aa1b31be779e6b84f9a96cb66bc50f6",
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
    ],
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "fallback_url": "https://woz.io/relenv/dependencies/Python-{version}.tar.xz",
        "version": build.version,
        "md5sum": "8847dc6458d1431d0ae0f55942deeb89",
        "checkfunc": python_version,
        "checkurl": "https://www.python.org/ftp/python/",
    },
)


build.add(
    "relenv-finalize",
    build_func=finalize,
    wait_on=[
        "python",
    ],
)

build = build.copy(version="3.11.7", md5sum="96c7e134c35a8c46236f8a0e566b69c")
builds.add("linux", builder=build)
