from .common import *

def populate_env(dirs, env):
    env["CC"] = "gcc"
    ldflags = [
        "-Wl,--rpath={prefix}/lib",
        "-L{glibc}/lib",
        "-L{prefix}/lib",
    ]
    env["LDFLAGS"] = " ".join(ldflags).format(glibc=dirs.glibc, prefix=dirs.prefix)
    cflags = [
        "-L{glibc}/lib",
        "-L{prefix}/lib",
        "-I{glibc}/include",
        "-I{prefix}/include",
        "-I{prefix}/include/readline",
    ]
    env["CFLAGS"] = " ".join(cflags).format(glibc=dirs.glibc, prefix=dirs.prefix)


def build_glibc(env, dirs, logfp):
    os.chdir(dirs.build)
    env["CFLAGS"] = "-O2 -no-pie" # -D_FORTIFY_SOURCE -Wno-missing-attributes -Wno-array-bounds -Wno-array-parameter -Wno-stringop-overflow -Wno-maybe-uninitialized"
    env["LDFLAGS"] = "-no-pie"
    config = str(dirs.source / 'configure')
    # Allow any version of make
    runcmd(["sed", "-i", 's/3.79/*/g', config])
    # Allow any version of gcc
    runcmd(["sed", "-i", 's/4\.\[3-9\]\.*/*/', config])
    #XXX audit these options
    runcmd([
        config,
        "--disable-werror",
        "--prefix={}".format(dirs.glibc),
        "--enable-kernel={}".format(kernel_version()) if not CICD else "",
    ], env=env, stderr=logfp, stdout=logfp)
    makefile = str(dirs.source / 'Makefile')
    runcmd(["sed", "-i", 's/ifndef abi-variants/ifdef api-variants/g ', makefile])
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_openssl(env, dirs, logfp):
    runcmd([
        './Configure',
        "darwin64-x86_64-cc" if sys.platform == 'darwin' else "linux-x86_64",
        "no-idea",
        "shared",
        "--prefix={}".format(dirs.prefix),
        "--openssldir={}/ssl".format(dirs.prefix),
        ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install_sw", "install_ssldirs"], env=env, stderr=logfp, stdout=logfp)



def build_sqlite(env, dirs, logfp):
    #extra_cflags=('-Os '
    #              '-DSQLITE_ENABLE_FTS5 '
    #              '-DSQLITE_ENABLE_FTS4 '
    #              '-DSQLITE_ENABLE_FTS3_PARENTHESIS '
    #              '-DSQLITE_ENABLE_JSON1 '
    #              '-DSQLITE_ENABLE_RTREE '
    #              '-DSQLITE_TCL=0 '
    #              )
    #configure_pre=[
    #    '--enable-threadsafe',
    #    '--enable-shared=no',
    #    '--enable-static=yes',
    #    '--disable-readline',
    #    '--disable-dependency-tracking',
    #]
    runcmd([
        "./configure",
        "--enable-threadsafe",
        "--disable-readline",
        "--disable-dependency-tracking",
        "--prefix={}".format(dirs.prefix),
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_bzip2(env, dirs, logfp):
    runcmd([
        "make",
        "-j8",
        "PREFIX={}".format(dirs.prefix),
        "LDFLAGS={}".format(env["LDFLAGS"]),
        "CFLAGS=-fPIC",
        "CC={}".format(env["CC"]),
        "install",
    ],  stderr=logfp, stdout=logfp)
    runcmd([
        "make",
        "-f",
        "Makefile-libbz2_so",
        "CC={}".format(env["CC"]),
        "LDFLAGS={}".format(env["LDFLAGS"]),
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
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_ncurses(env, dirs, logfp):
    runcmd([
        "./configure",
        "--prefix={}".format(dirs.prefix),
        "--with-shared",
        "--without-cxx",
        "--enable-widec",
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

def build_libffi(env, dirs, logfp):
    runcmd([
        './configure',
        "--prefix={}".format(dirs.prefix),
        "--disable-multi-os-directory"
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
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-no-pie", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_krb(env, dirs, logfp):
    env["CFLAGS"] = "-fPIC {}".format(env["CFLAGS"])
    env["LDFLAGS"] = "-lm -lresolv -ldl {}".format(env["LDFLAGS"])
    os.chdir(dirs.source / "src")
    runcmd([
        './configure',
        "--prefix={}".format(dirs.prefix),
        "--with-shared",
        "--without-static",
        "--without-system-libverto",
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

def build_python(env, dirs, logfp):
    env["LDFLAGS"] = "-Wl,--rpath={prefix}/lib {ldflags}".format(
        prefix=dirs.prefix, ldflags=env["LDFLAGS"])
    runcmd([
        './configure',
         "-v",
        "--prefix={}".format(dirs.prefix),
        "--with-openssl={}".format(dirs.prefix),
        "--enable-optimizations",
    ], env=env, stderr=logfp, stdout=logfp)
    with io.open("Modules/Setup", "a+") as fp:
        fp.seek(0, io.SEEK_END)
        fp.write(
            "*disabled*\n"
            "_tkinter\n"
            "nsl\n"
            "ncurses\n"
            "nis\n"
        )
    runcmd(["sed", "s/#zlib/zlib/g", "Modules/Setup"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

build = Builder(populate_env=populate_env)

build.add(
    "glibc",
    "https://ftpmirror.gnu.org/glibc/glibc-2.17.tar.xz",
    None,
    build_func=build_glibc,
)

build.add(
    "OpenSSL",
    "https://www.openssl.org/source/openssl-1.1.1n.tar.gz",
    "2aad5635f9bb338bc2c6b7d19cbc9676",
    build_func=build_openssl,
    wait_on=["glibc"],
)


build.add(
    "XZ",
    "http://tukaani.org/xz/xz-5.2.3.tar.gz",
    'ef68674fb47a8b8e741b34e429d86e9d',
    wait_on=["glibc"],
)

build.add(
    name="SQLite",
    url="https://sqlite.org/2022/sqlite-autoconf-3370200.tar.gz",
    checksum='683cc5312ee74e71079c14d24b7a6d27',
    build_func=build_sqlite,
    wait_on=["glibc"],
)

build.add(
    name="bzip2",
    url = "https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz",
    checksum = "67e051268d0c475ea773822f7500d0e5",
    build_func=build_bzip2,
    wait_on=["glibc"],
)

build.add(
    name="gdbm",
    url = "https://ftp.gnu.org/gnu/gdbm/gdbm-1.21.tar.gz",
    checksum = "a285c6e2dfed78668664c0555a7d202b",
    build_func=build_gdbm,
    wait_on=["glibc"],
)

build.add(
    name="ncurses",
    url = "https://ftp.gnu.org/pub/gnu/ncurses/ncurses-6.3.tar.gz",
    #checksum = "a2736befde5fee7d2b7eb45eb281cdbe",
    checksum = None,
    build_func=build_ncurses,
    wait_on=["readline", "glibc"],
)

build.add(
    "libffi",
    "https://github.com/libffi/libffi/releases/download/v3.3/libffi-3.3.tar.gz",
    "6313289e32f1d38a9df4770b014a2ca7",
    build_libffi,
    wait_on=["glibc"],
)

build.add(
    "zlib",
    "https://zlib.net/fossils/zlib-1.2.12.tar.gz",
    "5fc414a9726be31427b440b434d05f78",
    build_zlib,
    wait_on=["glibc"],
)

build.add(
    "uuid",
    "https://sourceforge.net/projects/libuuid/files/libuuid-1.0.3.tar.gz",
    "d44d866d06286c08ba0846aba1086d68",
    wait_on=["glibc"],
)

build.add(
    "krb5",
    "https://kerberos.org/dist/krb5/1.20/krb5-1.20.tar.gz",
    None,
    build_func=build_krb,
    wait_on=["OpenSSL", "glibc"],
)

build.add(
  "readline",
  "https://ftp.gnu.org/gnu/readline/readline-8.1.2.tar.gz",
  "12819fa739a78a6172400f399ab34f81",
  wait_on=["glibc"],
)

build.add(
    "Python",
    "https://www.python.org/ftp/python/3.10.6/Python-3.10.6.tar.xz",
    None,
    build_func=build_python,
    wait_on=[
        "glibc",
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



if __name__ == "__main__":
    run_build(build)
