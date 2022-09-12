from .common import *
import textwrap

def populate_env(env, dirs):
    env["CC"] = dirs.toolchain / "bin" / "{}-gcc -no-pie".format(
        env["MAYFLOWER_HOST"])
    env["PATH"] = "{}/bin/:{PATH}".format(dirs.toolchain, **env)
    #env["PATH"] = "{}/{MAYFLOWER_HOST}/bin:{PATH}".format(dirs.toolchain, **env)
    ldflags = [
        "-Wl,--rpath={prefix}/lib",
        "-L{prefix}/lib",
        "-L{}/{MAYFLOWER_HOST}/sysroot/lib".format(dirs.toolchain, **env),
    ]
    env["LDFLAGS"] = " ".join(ldflags).format(glibc=dirs.glibc, prefix=dirs.prefix)
    cflags = [
        "-L{prefix}/lib",
        "-L{}/{MAYFLOWER_HOST}/sysroot/lib".format(dirs.toolchain, **env),
        "-I{prefix}/include",
        "-I{prefix}/include/readline",
        "-I{prefix}/include/ncursesw",
        "-I{}/{MAYFLOWER_HOST}/sysroot/usr/include".format(dirs.toolchain, **env),
    ]
    env["CFLAGS"] = " ".join(cflags).format(glibc=dirs.glibc, prefix=dirs.prefix)
    # CPPFLAGS are needed for Python's setup.py to find the 'nessicery bits'
    # for things like zlib and sqlite.
    cpplags = [
        "-L{prefix}/lib",
        "-L{}/{MAYFLOWER_HOST}/sysroot/lib".format(dirs.toolchain, **env),
        "-I{prefix}/include",
        "-I{prefix}/include/readline",
        "-I{prefix}/include/ncursesw",
        "-I{}/{MAYFLOWER_HOST}/sysroot/usr/include".format(dirs.toolchain, **env),
    ]
    env["CPPFLAGS"] = " ".join(cpplags).format(glibc=dirs.glibc, prefix=dirs.prefix)
    if env["MAYFLOWER_ARCH"] == "aarch64":
        env["LDFLAGS"] = "-Wl,--no-apply-dynamic-relocs {}".format(env["LDFLAGS"])


def build_bzip2(env, dirs, logfp):
    runcmd([
        "make",
        "-j8",
        "PREFIX={}".format(dirs.prefix),
        "LDFLAGS={}".format(env["LDFLAGS"]),
        "CFLAGS=-fPIC",
        "CC={}".format(env["CC"]),
        "BUILD={}".format("x86_64-linux-gnu"),
        "HOST={}".format(env["MAYFLOWER_HOST"]),
        "install",
    ],  stderr=logfp, stdout=logfp)
    runcmd([
        "make",
        "-f",
        "Makefile-libbz2_so",
        "CC={}".format(env["CC"]),
        "LDFLAGS={}".format(env["LDFLAGS"]),
        "BUILD={}".format("x86_64-linux-gnu"),
        "HOST={}".format(env["MAYFLOWER_HOST"]),
    ], env=env, stderr=logfp, stdout=logfp)
    shutil.copy2(
        "libbz2.so.1.0.8",
        os.path.join(dirs.prefix, "lib")
    )


def build_gdbm(env, dirs, logfp):
    runcmd([
        './configure',
        "--prefix={}".format(dirs.prefix),
        "--enable-libgdbm-compat",
        "--build=x86_64-linux-gnu",
        "--host={}".format(env["MAYFLOWER_HOST"]),
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_ncurses(env, dirs, logfp):
    configure = pathlib.Path(dirs.source) / "configure"
    if env["MAYFLOWER_ARCH"] == "aarch64":
        os.chdir(dirs.build)
        runcmd([str(configure)], stderr=logfp, stdout=logfp)
        runcmd(["make", "-C", "include"], stderr=logfp, stdout=logfp)
        runcmd(["make", "-C", "progs", "tic"], stderr=logfp, stdout=logfp)
    os.chdir(dirs.source)
    runcmd([
        str(configure),
        "--prefix=/",
        "--with-shared",
        "--without-cxx-shared",
        "--without-static",
        "--without-cxx",
        "--enable-widec",
        "--without-normal",
        "--disable-stripping",
        #"--disable-multiarch",
        "--build=x86_64-linux-gnu",
        "--host={}".format(env["MAYFLOWER_HOST"]),
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd([
        "make",
        "DESTDIR={}".format(dirs.prefix),
        "TIC_PATH={}".format(str(pathlib.Path(dirs.build) / "progs" / "tic")),
        "install"], env=env, stderr=logfp, stdout=logfp)


def build_libffi(env, dirs, logfp):
    runcmd([
        './configure',
        "--prefix={}".format(dirs.prefix),
        "--disable-multi-os-directory",
        "--build=x86_64-linux-gnu",
        "--host={}".format(env["MAYFLOWER_HOST"]),
    ], env=env, stderr=logfp, stdout=logfp)
    # libffi doens't want to honor libdir, force install to lib instead of lib64
    runcmd(["sed", "-i", "s/lib64/lib/g", "Makefile"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_zlib(env, dirs, logfp):
    env["CFLAGS"] = "-fPIC {}".format(env["CFLAGS"])
    runcmd([
        './configure',
        "--prefix={}".format(dirs.prefix),
        "--libdir={}/lib".format(dirs.prefix),
        "--shared",
        "--archs=\"-arch {}\"".format(env["MAYFLOWER_ARCH"]),
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-no-pie", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_krb(env, dirs, logfp):
    #env["CFLAGS"] = "-fPIC {}".format(env["CFLAGS"])
    #env["LDFLAGS"] = "-lm -lresolv -ldl -lrt {}".format(env["LDFLAGS"])
    if env["MAYFLOWER_ARCH"] == "aarch64":
        env["krb5_cv_attr_constructor_destructor"] = "yes,yes"
        env["ac_cv_func_regcomp"] = "yes"
        env["ac_cv_printf_positional"] = "yes"
    os.chdir(dirs.source / "src")
    runcmd([
        './configure',
        "--prefix={}".format(dirs.prefix),
        #"--shared",
        #"--without-static",
        "--without-system-verto",
        "--without-libedit",
    #    "--build=x86_64-linux-gnu",
        "--host={}".format(env["MAYFLOWER_HOST"]),
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

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

def build_python(env, dirs, logfp):
    env["LDFLAGS"] = "-Wl,--rpath={prefix}/lib {ldflags}".format(
        prefix=dirs.prefix, ldflags=env["LDFLAGS"])

    # Modify config script to allow aarch64 cross
    #if env["MAYFLOWER_HOST"] == "aarch64-linux-gnu":
    runcmd(["sed", "-i", 's/ac_cv_buggy_getaddrinfo=yes/ac_cv_buggy_getaddrinfo=no/g', 'configure'])
    runcmd(["sed", "-i", 's/ac_cv_enable_implicit_function_declaration_error=yes/ac_cv_enable_implicit_function_declaration_error=no/g', 'configure'])
    #runcmd(["echo", "ac_cv_file__dev_ptmx=no", "config.site"])
    #runcmd(["echo", "ac_cv_file__dev_ptmx=no", "config.site"])
    with open('/tmp/patch', 'w') as fp:
        fp.write(PATCH)
    runcmd(["patch", "-p0", "-i", "/tmp/patch"],
        env=env, stderr=logfp, stdout=logfp)

    cmd = [
        './configure',
         "-v",
        "--prefix={}".format(dirs.prefix),
        "--with-openssl={}".format(dirs.prefix),
        "--enable-optimizations",
    #    "--build=x86_64-linux-gnu",
        "--build={}".format(env["MAYFLOWER_ARCH"]),
        "--host={}".format(env["MAYFLOWER_HOST"]),
    ]
    #if env["MAYFLOWER_HOST"] == "aarch64-linux-gnu":
    cmd += [
        "ac_cv_file__dev_ptmx=yes",
        "ac_cv_file__dev_ptc=no",
    ]

    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    # Link with '-lncurses' insead of '-lcurses'.
    #runcmd(["sed", "-i", "s/#_curses _cursesmodule.c -lcurses/_curses _cursesmodule.c -lncurses/g", "Modules/Setup"], env=env, stderr=logfp, stdout=logfp)
    #runcmd(["sed", "-i", "s/#_curses_panel/_curses_panel/g", "Modules/Setup"], env=env, stderr=logfp, stdout=logfp)

    #XXX Is this working?
    #runcmd(["sed", "-i", "s/#zlib/zlib/g", "./Modules/Setup"], env=env, stderr=logfp, stdout=logfp)

    with io.open("Modules/Setup", "a+") as fp:
        fp.seek(0, io.SEEK_END)
        fp.write(
            "*disabled*\n"
            "_tkinter\n"
            "nsl\n"
    #        "ncurses\n"
            "nis\n"
        )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


build = Builder(populate_env=populate_env)

build.add(
    "OpenSSL",
    "https://www.openssl.org/source/openssl-1.1.1n.tar.gz",
    "2aad5635f9bb338bc2c6b7d19cbc9676",
    build_func=build_openssl,
)


build.add(
    "XZ",
    "http://tukaani.org/xz/xz-5.2.3.tar.gz",
    'ef68674fb47a8b8e741b34e429d86e9d',
)

build.add(
    name="SQLite",
    url="https://sqlite.org/2022/sqlite-autoconf-3390300.tar.gz",
    #checksum='683cc5312ee74e71079c14d24b7a6d27',
    checksum=None,
    build_func=build_sqlite,
)

build.add(
    name="bzip2",
    url = "https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz",
    checksum = "67e051268d0c475ea773822f7500d0e5",
    build_func=build_bzip2,
)

build.add(
    name="gdbm",
    url = "https://ftp.gnu.org/gnu/gdbm/gdbm-1.21.tar.gz",
    checksum = "a285c6e2dfed78668664c0555a7d202b",
    build_func=build_gdbm,
)

build.add(
    name="ncurses",
    url = "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-6.3.tar.gz",
    #checksum = "a2736befde5fee7d2b7eb45eb281cdbe",
    checksum = None,
    build_func=build_ncurses,
    wait_on=["readline"],
)

build.add(
    "libffi",
    "https://github.com/libffi/libffi/releases/download/v3.3/libffi-3.3.tar.gz",
    "6313289e32f1d38a9df4770b014a2ca7",
    build_libffi,
)

build.add(
    "zlib",
    "https://zlib.net/fossils/zlib-1.2.12.tar.gz",
    "5fc414a9726be31427b440b434d05f78",
    build_zlib,
)

build.add(
    "uuid",
    "https://sourceforge.net/projects/libuuid/files/libuuid-1.0.3.tar.gz",
    "d44d866d06286c08ba0846aba1086d68",
)

build.add(
    "krb5",
    "https://kerberos.org/dist/krb5/1.20/krb5-1.20.tar.gz",
    None,
    build_func=build_krb,
    wait_on=["OpenSSL"],
)

build.add(
  "readline",
  "https://ftp.gnu.org/gnu/readline/readline-8.1.2.tar.gz",
  "12819fa739a78a6172400f399ab34f81",
)

build.add(
    "Python",
    "https://www.python.org/ftp/python/3.10.6/Python-3.10.6.tar.xz",
    None,
    build_func=build_python,
    wait_on=[
        "OpenSSL",
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
    ]
)

def main(argparse):
    run_build(build, argparse)

if __name__ == "__main__":
    from argparse import ArgumentParser
    main(ArgumentParser())
