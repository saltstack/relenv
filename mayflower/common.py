import os
import pathlib
import platform
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

MODULE_DIR = pathlib.Path(__file__).resolve().parent
WORK_IN_CWD = False
PIPE = subprocess.PIPE

TOOLCHAIN = os.environ.get(
    "MAYFLOWER_TOOLCHAINS", pathlib.Path.home() / ".local" / "mayflower" / "toolchain"
)


class MayflowerException(Exception):
    """
    Base class for exeptions generated from mayflower
    """


def work_root(root=None):
    if root is not None:
        base = pathlib.Path(root).resolve()
    elif WORK_IN_CWD:
        base = pathlib.Path(os.getcwd()).resolve()
    else:
        base = MODULE_DIR
    return base


def work_dir(name, root=None):
    root = work_root(root)
    if root == MODULE_DIR:
        base = root / "_{}".format(name)
    else:
        base = root / name
    return base


class WorkDirs:
    def __init__(self, root):
        self.root = root
        self.toolchain_config = work_dir("toolchain", self.root)
        self.toolchain = pathlib.Path(TOOLCHAIN)
        self.build = work_dir("build", self.root)
        self.src = work_dir("src", self.root)
        self.logs = work_dir("logs", self.root)
        self.download = work_dir("download", self.root)

    def __getstate__(self):
        return {
            "root": self.root,
            "toolchain_config": self.toolchain_config,
            "toolchain": self.toolchain,
            "build": self.build,
            "src": self.src,
            "logs": self.logs,
            "download": self.download,
        }

    def __setstate__(self, state):
        self.root = state["root"]
        self.toolchain_config = state["toolchain_config"]
        self.toolchain = state["toolchain"]
        self.build = state["build"]
        self.src = state["src"]
        self.logs = state["logs"]
        self.download = state["download"]


def work_dirs(root=None):
    return WorkDirs(work_root(root))


def get_toolchain(arch=None, root=None):
    dirs = work_dirs(root)
    if arch:
        return dirs.toolchain / "{}-linux-gnu".format(arch)
    return dirs.toolchain


def get_triplet(machine=None, plat=None):
    if not plat:
        plat = sys.platform
    if not machine:
        machine = platform.machine()
    machine = machine.lower()
    if plat == "darwin":
        return f"{machine}-macos"
    elif plat == "win32":
        return f"{machine}-win"
    elif plat == "linux":
        return f"{machine}-linux-gnu"
    else:
        raise MayflowerException("Unknown platform {}".format(platform))


def archived_build(triplet=None):
    """
    Returns a `Path` object pointing to the location of an archived build.
    """
    if not triplet:
        triplet = get_triplet()
    dirs = work_dirs()
    return (dirs.build / triplet).with_suffix(".tar.xz")


def extract_archive(to_dir, archive):
    """
    Extract an archive to a specific location
    """
    if archive.endswith("tgz"):
        read_type = "r:gz"
    elif archive.endswith("xz"):
        read_type = "r:xz"
    elif archive.endswith("bz2"):
        read_type = "r:bz2"
    else:
        read_type = "r"
    with tarfile.open(archive, read_type) as t:
        t.extractall(to_dir)


def download_url(url, dest):
    """
    Download the url to the provided destination. This method assumes the last
    part of the url is a filename. (https://foo.com/bar/myfile.tar.xz)
    """
    local = os.path.join(dest, os.path.basename(url))
    n = 0
    while n < 3:
        n += 1
        try:
            fin = urllib.request.urlopen(url)
        except urllib.error.HTTPError as exc:
            if n == 3:
                raise
            print("Unable to download: %s %r".format(url, exc))
            time.sleep(n + 1 * 10)
    fout = open(local, "wb")
    block = fin.read(10240)
    try:
        while block:
            fout.write(block)
            block = fin.read(10240)
        fin.close()
        fout.close()
    except:
        try:
            os.unlink(local)
        except OSError:
            pass
        raise
    return local


def runcmd(*args, **kwargs):
    """
    Run the provided command, raising an Exception when the command finishes
    with a non zero exit code.
    """
    proc = subprocess.run(*args, **kwargs)
    if proc.returncode != 0:
        raise MayflowerException("Build cmd '{}' failed".format(" ".join(args[0])))
    return proc
