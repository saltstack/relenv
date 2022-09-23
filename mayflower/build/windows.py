import ctypes
from .common import *


def populate_env(env, dirs):
    env["MSBUILDDISABLENODEREUSE"] = "1"


def build_python(env, dirs, logfp):
    cmd = [
        str(dirs.source / "PCbuild" / "build.bat"),
        "-p",
        "x64" if dirs.arch == "x86_64" else "x86",
        "--no-tkinter",
    ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    print("build: %s" % dirs.build)
    print("prefix: %s" % dirs.prefix)
    print("arch: %s" % dirs.arch)
    print("sources: %s" % dirs.sources)
    print("source: %s" % dirs.source)
    exit()


build = Builder(populate_env=populate_env)

build.add(
    "Python",
    "https://www.python.org/ftp/python/3.8.14/Python-3.8.14.tar.xz",
    None,
    build_func=build_python,
)


def main(argparse):
    run_build(build, argparse)


if __name__ == "__main__":
    from argparse import ArgumentParser
    main(ArgumentParser())
