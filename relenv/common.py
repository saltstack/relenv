# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
Common classes and values used around relenv.
"""
import os
import pathlib
import platform
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

# relenv package version
__version__ = "0.4.5"

MODULE_DIR = pathlib.Path(__file__).resolve().parent

LINUX = "linux"
WIN32 = "win32"
DARWIN = "darwin"

arches = {
    LINUX: (
        "x86_64",
        "aarch64",
    ),
    DARWIN: ("x86_64",),
    WIN32: (
        "amd64",
        "x86",
        #    "arm64", # Python 11 should support arm.
    ),
}


if sys.platform == "win32":
    DEFAULT_DATA_DIR = pathlib.Path.home() / "AppData" / "Local" / "relenv"
else:
    DEFAULT_DATA_DIR = pathlib.Path.home() / ".local" / "relenv"

DATA_DIR = pathlib.Path(os.environ.get("RELENV_DATA", DEFAULT_DATA_DIR)).resolve()


class RelenvException(Exception):
    """
    Base class for exeptions generated from relenv.
    """


def build_arch():
    """
    Return the current machine.
    """
    machine = platform.machine()
    return machine.lower()


def work_root(root=None):
    """
    Get the root directory that all other relenv working directories should be based on.

    :param root: An explicitly requested root directory
    :type root: str

    :return: An absolute path to the relenv root working directory
    :rtype: ``pathlib.Path``
    """
    if root is not None:
        base = pathlib.Path(root).resolve()
    else:
        base = MODULE_DIR
    return base


def work_dir(name, root=None):
    """
    Get the absolute path to the relenv working directory of the given name.

    :param name: The name of the directory
    :type name: str
    :param root: The root directory that this working directory will be relative to
    :type root: str

    :return: An absolute path to the requested relenv working directory
    :rtype: ``pathlib.Path``
    """
    root = work_root(root)
    if root == MODULE_DIR:
        base = root / "_{}".format(name)
    else:
        base = root / name
    return base


class WorkDirs:
    """
    Simple class used to hold references to working directories relenv uses relative to a given root.

    :param root: The root of the working directories tree
    :type root: str
    """

    def __init__(self, root):
        self.root = root
        self.toolchain_config = work_dir("toolchain", self.root)
        self.toolchain = work_dir("toolchain", DATA_DIR)
        self.build = work_dir("build", DATA_DIR)
        self.src = work_dir("src", DATA_DIR)
        self.logs = work_dir("logs", DATA_DIR)
        self.download = work_dir("download", DATA_DIR)

    def __getstate__(self):
        """
        Return an object used for pickling.

        :return: The picklable state
        """
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
        """
        Unwrap the object returned from unpickling.

        :param state: The state to unpickle
        :type state: dict
        """
        self.root = state["root"]
        self.toolchain_config = state["toolchain_config"]
        self.toolchain = state["toolchain"]
        self.build = state["build"]
        self.src = state["src"]
        self.logs = state["logs"]
        self.download = state["download"]


def work_dirs(root=None):
    """
    Returns a WorkDirs instance based on the given root.

    :param root: The desired root of relenv's working directories
    :type root: str

    :return: A WorkDirs instance based on the given root
    :rtype: ``relenv.common.WorkDirs``
    """
    return WorkDirs(work_root(root))


def get_toolchain(arch=None, root=None):
    """
    Get a the toolchain directory, specific to the arch if supplied.

    :param arch: The architecture to get the toolchain for
    :type arch: str
    :param root: The root of the relenv working directories to search in
    :type root: str

    :return: The directory holding the toolchain
    :rtype: ``pathlib.Path``
    """
    dirs = work_dirs(root)
    if arch:
        return dirs.toolchain / "{}-linux-gnu".format(arch)
    return dirs.toolchain


def get_triplet(machine=None, plat=None):
    """
    Get the target triplet for the specified machine and platform.

    If any of the args are None, it will try to deduce what they should be.

    :param machine: The machine for the triplet
    :type machine: str
    :param plat: The platform for the triplet
    :type plat: str

    :raises RelenvException: If the platform is unknown

    :return: The target triplet
    :rtype: str
    """
    if not plat:
        plat = sys.platform
    if not machine:
        machine = build_arch()
    if plat == "darwin":
        return f"{machine}-macos"
    elif plat == "win32":
        return f"{machine}-win"
    elif plat == "linux":
        return f"{machine}-linux-gnu"
    else:
        raise RelenvException(f"Unknown platform {plat}")


def archived_build(triplet=None):
    """
    Finds a the location of an archived build.

    :param triplet: The build triplet to find
    :type triplet: str

    :return: The location of the archived build
    :rtype: ``pathlib.Path``
    """
    if not triplet:
        triplet = get_triplet()
    dirs = work_dirs(DATA_DIR)
    return (dirs.build / triplet).with_suffix(".tar.xz")


def extract_archive(to_dir, archive):
    """
    Extract an archive to a specific location.

    :param to_dir: The directory to extract to
    :type to_dir: str
    :param archive: The archive to extract
    :type archive: str
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


def get_download_location(url, dest):
    """
    Get the full path to where the url will be downloaded to.

    :param url: The url to donwload
    :type url: str
    :param dest: Where to download the url to
    :type dest: str

    :return: The path to where the url will be downloaded to
    :rtype: str
    """
    return os.path.join(dest, os.path.basename(url))


def download_url(url, dest, verbose=True):
    """
    Download the url to the provided destination.

    This method assumes the last part of the url is a filename. (https://foo.com/bar/myfile.tar.xz)

    :param url: The url to download
    :type url: str
    :param dest: Where to download the url to
    :type dest: str
    :param verbose: Print download url and destination to stdout
    :type verbose: bool

    :raises urllib.error.HTTPError: If the url was unable to be downloaded

    :return: The path to the downloaded content
    :rtype: str
    """
    local = get_download_location(url, dest)
    if verbose:
        print(f"Downloading {url} -> {local}")
    n = 0
    while n < 3:
        n += 1
        try:
            fin = urllib.request.urlopen(url)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            if n == 3:
                print(f"Unable to download: {url} {exc}", file=sys.stderr, flush=True)
                raise
            time.sleep(n * 10)
    fout = open(local, "wb")
    block = fin.read(10240)
    try:
        while block:
            fout.write(block)
            block = fin.read(10240)
        fin.close()
        fout.close()
    except Exception:
        try:
            os.unlink(local)
        except OSError:
            pass
        raise
    return local


def runcmd(*args, **kwargs):
    """
    Run a command.

    Run the provided command, raising an Exception when the command finishes
    with a non zero exit code.  Arguments are passed through to ``subprocess.run``

    :return: The process result
    :rtype: ``subprocess.CompletedProcess``

    :raises RelenvException: If the command finishes with a non zero exit code
    """
    proc = subprocess.run(*args, **kwargs)
    if proc.returncode != 0:
        raise RelenvException("Build cmd '{}' failed".format(" ".join(args[0])))
    return proc
