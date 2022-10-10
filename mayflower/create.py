import contextlib
import os
import pathlib
import sys
import tarfile
import tempfile

from .common import MODULE_DIR, MayflowerException


@contextlib.contextmanager
def chdir(path):
    cwd = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


class CreateException(MayflowerException):
    """
    Raised when there is an issue creating a new mayflower environment.
    """


def create(name, dest=None, arch="x86_64"):

    if dest:
        writeto = pathlib.Path(dest) / name
    else:
        writeto = pathlib.Path(name).resolve()

    if pathlib.Path(writeto).exists():
        raise CreateException("The requested path already exists.")

    plat = sys.platform
    # if plat == "win32":
    #    arch = "x86_64"
    # else:
    #    arch = os.uname().machine

    if plat == "linux":
        if arch in ("x86_64", "aarch64"):
            triplet = "{}-{}-gnu".format(arch, plat)
        else:
            raise CreateException("Unknown arch")
    elif plat == "darwin":
        if arch in ("x86_64"):
            triplet = "{}-macos".format(arch)
        else:
            raise CreateException("Unknown arch")
    elif plat == "win32":
        if arch in ["x86_64"]:
            triplet = "{}-win".format(arch)
        else:
            raise CreateException("Unknown arch")
    else:
        raise CreateException("Unknown platform")

    tar = (MODULE_DIR / "_build" / triplet).with_suffix(".tar.xz")
    if not tar.exists():
        raise CreateException(
            "Error, build archive for {} doesn't exist.\n"
            "You might try mayflower fetch to resolve this.".format(arch)
        )
    tmp = tempfile.mkdtemp()
    with tarfile.open(tar, "r:xz") as fp:
        for f in fp:
            fp.extract(f, writeto)


def main(argparser):
    argparser.description = (
        "Create a Mayflower environment. This will create a directory of the "
        "given name with newly created Mayflower environment."
    )
    argparser.add_argument("name", help="The name of the directory to create")
    argparser.add_argument(
        "--arch",
        default="x86_64",
        type=str,
        help="The host architecture [default: x86_64]",
    )
    ns, argv = argparser.parse_known_args()
    if getattr(ns, "help", None):
        argparser.print_help()
        sys.exit(0)
    name = ns.name
    try:
        create(name, arch=ns.arch)
    except CreateException as exc:
        print(exc)
        sys.exit(1)
