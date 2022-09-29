import contextlib
import os
import pathlib
import shutil
import sys
import tarfile
import tempfile

from .common import MODULE_DIR


@contextlib.contextmanager
def chdir(path):
    cwd = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


def main(argparser):
    argparser.descrption = "Create Mayflower Environments"
    argparser.add_argument("name", help="The name of the directory to create")
    ns, argv = argparser.parse_known_args()
    if getattr(ns, "help", None):
        argparser.print_help()
        sys.exit(0)
    name = ns.name
    if pathlib.Path(name).exists():
        print("The requested path already exists.")
        sys.exit(1)
    plat = sys.platform
    if plat == "win32":
        arch = "x86_64"
    else:
        arch = os.uname().machine
    if plat == "linux":
        if arch in ("x86_64", "aarch64"):
            triplet = "{}-{}-gnu".format(arch, plat)
        else:
            print("Unknown arch {}".format(arch))
            sys.exit(1)
    elif plat == "darwin":
        if arch in ("x86_64"):
            triplet = "{}-macos".format(arch)
        else:
            print("Unknown arch {}".format(arch))
            sys.exit(1)
    elif plat == "win32":
        if arch in ["x86_64"]:
            triplet = "{}-win".format(arch)
        else:
            print("Unknown arch {}".format(arch))
            sys.exit(1)
    else:
        print("Unknown platform {}".format(plat))
        sys.exit(1)
    build = MODULE_DIR / "_build" / triplet
    tar = build.with_suffix(".tar.xz")
    if not tar.exists():
        print(
            "Error, build archive for {} doesn't exist.\n"
            "You might try mayflower fetch to resolve this.".format(arch)
        )
        sys.exit(1)
    tmp = tempfile.mkdtemp()
    with tarfile.open(tar, "r:xz") as fp:
        for f in fp:
            fp.extract(f, name)
