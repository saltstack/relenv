import sys, os, pathlib, shutil, contextlib, tarfile
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
    argparser.add_argument('name', help='The name of the directory to create')
    ns, argv = argparser.parse_known_args()
    if getattr(ns, "help", None):
        argparser.print_help()
        sys.exit(0)
    name = ns.name
    plat = sys.platform
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
    if not build.exists():
        tar = build.with_suffix(".tar.xz")
        if not tar.exists():
            print("Error, build archive for {} doesn't exist.\n"
                  "You might try mayflower fetch to resolve this.".format(arch))
            sys.exit(1)
        with chdir(build.parent):
            with tarfile.open(tar, "r:xz") as fp:
                fp.extractall()
    dest = pathlib.Path(name).resolve()
    shutil.copytree(
        build,
        dest,
    )




