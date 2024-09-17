# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
Common classes and values used around relenv.
"""
import http.client
import logging
import os
import pathlib
import platform
import queue
import selectors
import subprocess
import sys
import tarfile
import textwrap
import threading
import time

# relenv package version
__version__ = "0.17.2"

MODULE_DIR = pathlib.Path(__file__).resolve().parent

LINUX = "linux"
WIN32 = "win32"
DARWIN = "darwin"

MACOS_DEVELOPMENT_TARGET = "10.15"

CHECK_HOSTS = ("repo.saltproject.io", "woz.io")

arches = {
    LINUX: (
        "x86_64",
        "aarch64",
    ),
    DARWIN: ("x86_64", "arm64"),
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

SHEBANG_TPL_LINUX = textwrap.dedent(
    """#!/bin/sh
"true" ''''
"exec" "$(dirname "$(readlink -f "$0")"){}" "$0" "$@"
'''
"""
)

SHEBANG_TPL_MACOS = textwrap.dedent(
    """\
#!/bin/sh
"true" ''''
TARGET_FILE=$0
cd "$(dirname "$TARGET_FILE")" || return
TARGET_FILE=$(basename "$TARGET_FILE")
# Iterate down a (possible) chain of symlinks
while [ -L "$TARGET_FILE" ]
do
    TARGET_FILE=$(readlink "$TARGET_FILE")
    cd "$(dirname "$TARGET_FILE")" || return
    TARGET_FILE=$(basename "$TARGET_FILE")
done
PHYS_DIR=$(pwd -P)
REALPATH=$PHYS_DIR/$TARGET_FILE
"exec" "$(dirname "$REALPATH")"{} "$REALPATH" "$@"
'''"""
)

if sys.platform == "linux":
    SHEBANG_TPL = SHEBANG_TPL_LINUX
else:
    SHEBANG_TPL = SHEBANG_TPL_MACOS


log = logging.getLogger(__name__)


class RelenvException(Exception):
    """
    Base class for exeptions generated from relenv.
    """


def format_shebang(python, tpl=SHEBANG_TPL):
    """
    Return a formatted shebang.
    """
    return tpl.format(python).strip()


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


def plat_from_triplet(plat):
    """
    Convert platform from build to the value of sys.platform.
    """
    if plat == "linux-gnu":
        return "linux"
    elif plat == "macos":
        return "darwin"
    elif plat == "win":
        return "win32"
    raise RelenvException(f"Unkown platform {plat}")


def list_archived_builds():
    """
    Return a list of version, architecture and platforms for builds.
    """
    builds = []
    dirs = work_dirs(DATA_DIR)
    for root, dirs, files in os.walk(dirs.build):
        for file in files:
            if file.endswith(".tar.xz"):
                file = file[:-7]
                version, triplet = file.split("-", 1)
                arch, plat = triplet.split("-", 1)
                builds.append((version, arch, plat))
    return builds


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
    archive = f"{triplet}.tar.xz"
    return dirs.build / archive


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


def check_url(url, timeout=30):
    """
    Check that the url returns a 200.
    """
    # Late import so we do not import hashlib before runtime.bootstrap is called.
    import urllib.request

    fin = None
    try:
        fin = urllib.request.urlopen(url, timeout=timeout)
    except Exception:
        return False
    finally:
        if fin:
            fin.close()
    return True


def fetch_url(url, fp, backoff=3, timeout=30):
    """
    Fetch the contents of a url.

    This method will store the contents in the given file like object.
    """
    # Late import so we do not import hashlib before runtime.bootstrap is called.
    import urllib.error
    import urllib.request

    if backoff < 1:
        backoff = 1
    n = 0
    while n < backoff:
        n += 1
        try:
            fin = urllib.request.urlopen(url, timeout=timeout)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            http.client.RemoteDisconnected,
        ) as exc:
            if n >= backoff:
                raise RelenvException(f"Error fetching url {url} {exc}")
            time.sleep(n * 10)
    try:
        size = 1024 * 300
        block = fin.read(size)
        while block:
            fp.write(block)
            block = fin.read(10240)
    finally:
        fin.close()
        # fp.close()


def download_url(url, dest, verbose=True, backoff=3, timeout=60):
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
    fout = open(local, "wb")
    try:
        fetch_url(url, fout, backoff, timeout)
    except Exception as exc:
        if verbose:
            print(f"Unable to download: {url} {exc}", file=sys.stderr, flush=True)
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
    log.debug("Running command: %s", " ".join(args[0]))
    # if "stdout" not in kwargs:
    kwargs["stdout"] = subprocess.PIPE
    # if "stderr" not in kwargs:
    kwargs["stderr"] = subprocess.PIPE
    if "universal_newlines" not in kwargs:
        kwargs["universal_newlines"] = True
    if sys.platform != "win32":

        p = subprocess.Popen(*args, **kwargs)
        # Read both stdout and stderr simultaneously
        sel = selectors.DefaultSelector()
        sel.register(p.stdout, selectors.EVENT_READ)
        sel.register(p.stderr, selectors.EVENT_READ)
        ok = True
        while ok:
            for key, val1 in sel.select():
                line = key.fileobj.readline()
                if not line:
                    ok = False
                    break
                if line.endswith("\n"):
                    line = line[:-1]
                if key.fileobj is p.stdout:
                    log.info(line)
                else:
                    log.error(line)

    else:

        def enqueue_stream(stream, queue, type):
            NOOP = object()
            for line in iter(stream.readline, NOOP):
                if line is NOOP or line == "":
                    break
                if line:
                    queue.put((type, line))
            log.debug("stream close %r %r", type, line)
            stream.close()

        def enqueue_process(process, queue):
            process.wait()
            queue.put(("x", "x"))

        p = subprocess.Popen(*args, **kwargs)
        q = queue.Queue()
        to = threading.Thread(target=enqueue_stream, args=(p.stdout, q, 1))
        te = threading.Thread(target=enqueue_stream, args=(p.stderr, q, 2))
        tp = threading.Thread(target=enqueue_process, args=(p, q))
        te.start()
        to.start()
        tp.start()

        while True:
            kind, line = q.get()
            if kind == 1:  # stdout
                log.info(line[:-1])
            elif kind == 2:
                log.error(line[:-1])
            elif kind == "x":
                log.debug("process queue end")
                break

        tp.join()
        to.join()
        te.join()

    p.wait()
    if p.returncode != 0:
        raise RelenvException("Build cmd '{}' failed".format(" ".join(args[0])))
    return p


def relative_interpreter(root_dir, scripts_dir, interpreter):
    """
    Return a relativized path to the given scripts_dir and interpreter.
    """
    scripts = pathlib.Path(scripts_dir)
    interp = pathlib.Path(interpreter)
    root = pathlib.Path(root_dir)
    try:
        relinterp = interp.relative_to(root)
    except ValueError:
        raise ValueError("interperter not relative to root_dir")
    try:
        relscripts = pathlib.Path(*(".." for x in scripts.relative_to(root).parts))
    except ValueError:
        raise ValueError("scripts_dir not relative to root_dir")
    return relscripts / relinterp


def sanitize_sys_path(sys_path_entries):
    """
    Sanitize `sys.path` to only include paths relative to the onedir environment.
    """
    __sys_path = []
    __valid_path_prefixes = tuple(
        {
            pathlib.Path(sys.prefix).resolve(),
            pathlib.Path(sys.base_prefix).resolve(),
        }
    )
    for __path in sys_path_entries:
        for __valid_path_prefix in __valid_path_prefixes:
            try:
                __resolved_path = pathlib.Path(__path).resolve()
                __resolved_path.relative_to(__valid_path_prefix)
                __sys_path.append(str(__resolved_path))
            except ValueError:
                continue
    if "PYTHONPATH" in os.environ:
        for __path in os.environ["PYTHONPATH"].split(os.pathsep):
            __sys_path.append(__path)
    return __sys_path
