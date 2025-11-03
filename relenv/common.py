# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Common classes and values used around relenv.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import pathlib
import platform
import queue
import selectors
import shutil
import subprocess
import sys
import tarfile
import textwrap
import threading
import time
from typing import IO, Any, BinaryIO, Iterable, Literal, Mapping, Optional, Union, cast

# relenv package version
__version__ = "0.21.2"

log = logging.getLogger(__name__)

MODULE_DIR = pathlib.Path(__file__).resolve().parent

DEFAULT_PYTHON = "3.10.18"

LINUX = "linux"
WIN32 = "win32"
DARWIN = "darwin"

MACOS_DEVELOPMENT_TARGET = "10.15"

TOOLCHAIN_CACHE_ENV = "RELENV_TOOLCHAIN_CACHE"
_TOOLCHAIN_MANIFEST = ".toolchain-manifest.json"


# 8 GiB archives are not unusual; stick to metadata to fingerprint them.
def _archive_metadata(path: pathlib.Path) -> dict[str, Union[str, int]]:
    stat = path.stat()
    return {
        "archive": str(path.resolve()),
        "size": stat.st_size,
        "mtime": stat.st_mtime_ns,
    }


def _toolchain_cache_root() -> Optional[pathlib.Path]:
    override = os.environ.get(TOOLCHAIN_CACHE_ENV)
    if override:
        if override.strip().lower() == "none":
            return None
        return pathlib.Path(override).expanduser()
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        base = pathlib.Path(cache_home)
    else:
        base = pathlib.Path.home() / ".cache"
    return base / "relenv" / "toolchains"


def _toolchain_manifest_path(toolchain_path: pathlib.Path) -> pathlib.Path:
    return toolchain_path / _TOOLCHAIN_MANIFEST


def _load_toolchain_manifest(path: pathlib.Path) -> Optional[Mapping[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _manifest_matches(manifest: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    return (
        manifest.get("archive") == metadata.get("archive")
        and manifest.get("size") == metadata.get("size")
        and manifest.get("mtime") == metadata.get("mtime")
    )


def _write_toolchain_manifest(
    toolchain_path: pathlib.Path, metadata: Mapping[str, Any]
) -> None:
    manifest_path = _toolchain_manifest_path(toolchain_path)
    try:
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:  # pragma: no cover - permissions edge cases
        log.warning(
            "Unable to persist toolchain manifest at %s: %s", manifest_path, exc
        )


def toolchain_root_dir() -> pathlib.Path:
    """Return the root directory used for cached toolchains."""
    if sys.platform != "linux":
        return DATA_DIR
    root = _toolchain_cache_root()
    if root is None:
        return DATA_DIR / "toolchain"
    return root


REQUEST_HEADERS = {"User-Agent": f"relenv {__version__}"}

CHECK_HOSTS = (
    "packages.broadcom.com/artifactory/saltproject-generic",
    "woz.io",
)

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
# shellcheck disable=SC2093
"exec" "$(dirname "$(readlink -f "$0")"){}" "$0" "$@"
' '''
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
# shellcheck disable=SC2093
"exec" "$(dirname "$REALPATH")"{} "$REALPATH" "$@"
' '''
"""
)

if sys.platform == "linux":
    SHEBANG_TPL = SHEBANG_TPL_LINUX
else:
    SHEBANG_TPL = SHEBANG_TPL_MACOS


class RelenvException(Exception):
    """
    Base class for exeptions generated from relenv.
    """


def format_shebang(python: str, tpl: str = SHEBANG_TPL) -> str:
    """
    Return a formatted shebang.
    """
    shebang = tpl.format(python).strip()
    if shebang.endswith("'''"):
        return shebang + "\n\n"
    return shebang + "\n"


def build_arch() -> str:
    """
    Return the current machine.
    """
    machine = platform.machine()
    return machine.lower()


def work_root(
    root: Optional[Union[str, os.PathLike[str]]] = None,
) -> pathlib.Path:
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


def work_dir(
    name: str, root: Optional[Union[str, os.PathLike[str]]] = None
) -> pathlib.Path:
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

    def __init__(self: "WorkDirs", root: Union[str, os.PathLike[str]]) -> None:
        self.root: pathlib.Path = pathlib.Path(root)
        self.data: pathlib.Path = DATA_DIR
        self.toolchain_config: pathlib.Path = work_dir("toolchain", self.root)
        self.toolchain: pathlib.Path = toolchain_root_dir()
        self.build: pathlib.Path = work_dir("build", DATA_DIR)
        self.src: pathlib.Path = work_dir("src", DATA_DIR)
        self.logs: pathlib.Path = work_dir("logs", DATA_DIR)
        self.download: pathlib.Path = work_dir("download", DATA_DIR)

    def __getstate__(self: "WorkDirs") -> dict[str, pathlib.Path]:
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

    def __setstate__(self: "WorkDirs", state: Mapping[str, pathlib.Path]) -> None:
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


def work_dirs(
    root: Optional[Union[str, os.PathLike[str]]] = None,
) -> WorkDirs:
    """
    Returns a WorkDirs instance based on the given root.

    :param root: The desired root of relenv's working directories
    :type root: str

    :return: A WorkDirs instance based on the given root
    :rtype: ``relenv.common.WorkDirs``
    """
    return WorkDirs(work_root(root))


def get_toolchain(
    arch: Optional[str] = None,
    root: Optional[Union[str, os.PathLike[str]]] = None,
) -> Optional[pathlib.Path]:
    """
    Get a the toolchain directory, specific to the arch if supplied.

    On Linux, this function will extract the toolchain from ppbt if needed.
    If the toolchain already exists, it will be returned even if ppbt is
    not available (e.g., when running tests on non-Linux platforms that
    patch sys.platform to "linux"). This allows using existing toolchains
    without requiring ppbt to be installed.

    :param arch: The architecture to get the toolchain for
    :type arch: str
    :param root: The root of the relenv working directories to search in
    :type root: str

    :return: The directory holding the toolchain, or None if on Linux and
             the toolchain doesn't exist and ppbt is unavailable
    :rtype: ``pathlib.Path``
    """
    del root  # Kept for backward compatibility; location driven by DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    if sys.platform != "linux":
        return toolchain_root_dir()

    toolchain_root = toolchain_root_dir()
    triplet = get_triplet(machine=arch)
    toolchain_path = toolchain_root / triplet
    metadata: Optional[Mapping[str, Any]] = None
    if toolchain_path.exists():
        metadata = _load_toolchain_manifest(_toolchain_manifest_path(toolchain_path))

    try:
        from importlib import import_module

        ppbt_common = import_module("ppbt.common")
    except ImportError:
        # If toolchain already exists, use it even without ppbt
        return toolchain_path if toolchain_path.exists() else None
    archive_attr = getattr(ppbt_common, "ARCHIVE", None)
    extract = getattr(ppbt_common, "extract_archive", None)
    if archive_attr is None or not callable(extract):
        raise RelenvException("ppbt.common missing ARCHIVE or extract_archive")

    toolchain_root.mkdir(parents=True, exist_ok=True)
    archive_path = pathlib.Path(archive_attr)
    archive_meta = _archive_metadata(archive_path)

    if (
        toolchain_path.exists()
        and metadata
        and _manifest_matches(metadata, archive_meta)
    ):
        return toolchain_path

    if toolchain_path.exists():
        shutil.rmtree(toolchain_path)

    extract(str(toolchain_root), str(archive_path))
    if not toolchain_path.exists():
        raise RelenvException(
            f"Toolchain archive {archive_path} did not produce {toolchain_path}"
        )
    _write_toolchain_manifest(toolchain_path, archive_meta)
    return toolchain_path


def get_triplet(machine: Optional[str] = None, plat: Optional[str] = None) -> str:
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


def plat_from_triplet(plat: str) -> str:
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


def list_archived_builds() -> list[tuple[str, str, str]]:
    """
    Return a list of version, architecture and platforms for builds.
    """
    builds: list[tuple[str, str, str]] = []
    working_dirs = work_dirs(DATA_DIR)
    for root_dir, dirnames, filenames in os.walk(working_dirs.build):
        del dirnames  # unused
        for filename in filenames:
            if filename.endswith(".tar.xz"):
                base_name = filename[:-7]
                version, triplet = base_name.split("-", 1)
                arch, plat = triplet.split("-", 1)
                builds.append((version, arch, plat))
    return builds


def archived_build(triplet: Optional[str] = None) -> pathlib.Path:
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


def extract_archive(
    to_dir: Union[str, os.PathLike[str]], archive: Union[str, os.PathLike[str]]
) -> None:
    """
    Extract an archive to a specific location.

    :param to_dir: The directory to extract to
    :type to_dir: str
    :param archive: The archive to extract
    :type archive: str
    """
    archive_path = pathlib.Path(archive)
    archive_str = str(archive_path)
    to_path = pathlib.Path(to_dir)
    TarReadMode = Literal["r:gz", "r:xz", "r:bz2", "r"]
    read_type: TarReadMode = "r"
    if archive_str.endswith(".tgz"):
        log.debug("Found tgz archive")
        read_type = "r:gz"
    elif archive_str.endswith(".tar.gz"):
        log.debug("Found tar.gz archive")
        read_type = "r:gz"
    elif archive_str.endswith(".xz"):
        log.debug("Found xz archive")
        read_type = "r:xz"
    elif archive_str.endswith(".bz2"):
        log.debug("Found bz2 archive")
        read_type = "r:bz2"
    else:
        log.warning("Found unknown archive type: %s", archive_path)
    with tarfile.open(str(archive_path), mode=read_type) as tar:
        tar.extractall(str(to_path))


def get_download_location(url: str, dest: Union[str, os.PathLike[str]]) -> str:
    """
    Get the full path to where the url will be downloaded to.

    :param url: The url to donwload
    :type url: str
    :param dest: Where to download the url to
    :type dest: str

    :return: The path to where the url will be downloaded to
    :rtype: str
    """
    return os.path.join(os.fspath(dest), os.path.basename(url))


def check_url(url: str, timestamp: Optional[float] = None, timeout: float = 30) -> bool:
    """
    Check that the url returns a 200.
    """
    # Late import so we do not import hashlib before runtime.bootstrap is called.
    import time
    import urllib.request

    headers = dict(REQUEST_HEADERS)
    req = urllib.request.Request(url)

    if timestamp:
        headers["If-Modified-Since"] = time.strftime(
            "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(timestamp)
        )

    for k, v in headers.items():
        req.add_header(k, v)

    fin = None
    try:
        fin = urllib.request.urlopen(req, timeout=timeout)
    except Exception as exc:
        print(exc)
        return False
    finally:
        if fin:
            fin.close()
    return True


def fetch_url(url: str, fp: BinaryIO, backoff: int = 3, timeout: float = 30) -> None:
    """
    Fetch the contents of a url.

    This method will store the contents in the given file like object.
    """
    # Late import so we do not import hashlib before runtime.bootstrap is called.
    import urllib.error
    import urllib.request

    last = time.time()
    attempts = max(backoff, 1)
    response: http.client.HTTPResponse | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = urllib.request.urlopen(url, timeout=timeout)
            break
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            http.client.RemoteDisconnected,
        ) as exc:
            if attempt >= attempts:
                raise RelenvException(f"Error fetching url {url} {exc}")
            log.debug("Unable to connect %s", url)
            time.sleep(attempt * 10)
    if response is None:
        raise RelenvException(f"Unable to open url {url}")
    log.info("url opened %s", url)
    try:
        total = 0
        size = 1024 * 300
        block = response.read(size)
        while block:
            total += size
            if time.time() - last > 10:
                log.info("%s > %d", url, total)
                last = time.time()
            fp.write(block)
            block = response.read(10240)
    finally:
        response.close()
    log.info("Download complete %s", url)


def fetch_url_content(url: str, backoff: int = 3, timeout: float = 30) -> str:
    """
    Fetch the contents of a url.

    This method will store the contents in the given file like object.
    """
    # Late import so we do not import hashlib before runtime.bootstrap is called.
    import gzip
    import urllib.error
    import urllib.request

    attempts = max(backoff, 1)
    response: http.client.HTTPResponse | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = urllib.request.urlopen(url, timeout=timeout)
            break
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            http.client.RemoteDisconnected,
        ) as exc:
            if attempt >= attempts:
                raise RelenvException(f"Error fetching url {url} {exc}")
            log.debug("Unable to connect %s", url)
            time.sleep(attempt * 10)
    if response is None:
        raise RelenvException(f"Unable to open url {url}")
    log.info("url opened %s", url)
    try:
        data = response.read()
        encoding = response.headers.get("content-encoding", "").lower()
    finally:
        response.close()
    if encoding == "gzip":
        log.debug("Found gzipped content")
        data = gzip.decompress(data)
    log.info("Download complete %s", url)
    return data.decode()


def download_url(
    url: str,
    dest: Union[str, os.PathLike[str]],
    verbose: bool = True,
    backoff: int = 3,
    timeout: float = 60,
) -> str:
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
        log.debug(f"Downloading {url} -> {local}")
    try:
        with open(local, "wb") as fout:
            fetch_url(url, fout, backoff, timeout)
    except Exception as exc:
        if verbose:
            log.error("Unable to download: %s\n%s", url, exc)
        try:
            os.unlink(local)
        except OSError:
            pass
        raise
    finally:
        log.debug(f"Finished downloading {url} -> {local}")
    return local


def runcmd(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
    """
    Run a command.

    Run the provided command, raising an Exception when the command finishes
    with a non zero exit code.  Arguments are passed through to ``subprocess.run``

    :return: The process result
    :rtype: ``subprocess.CompletedProcess``

    :raises RelenvException: If the command finishes with a non zero exit code
    """
    if not args:
        raise RelenvException("No command provided to runcmd")
    log.debug("Running command: %s", " ".join(map(str, args[0])))
    # if "stdout" not in kwargs:
    kwargs["stdout"] = subprocess.PIPE
    # if "stderr" not in kwargs:
    kwargs["stderr"] = subprocess.PIPE
    if "universal_newlines" not in kwargs:
        kwargs["universal_newlines"] = True
    if sys.platform != "win32":

        p = subprocess.Popen(*args, **kwargs)
        stdout_stream = p.stdout
        stderr_stream = p.stderr
        if stdout_stream is None or stderr_stream is None:
            p.wait()
            raise RelenvException("Process pipes are unavailable")
        # Read both stdout and stderr simultaneously
        sel = selectors.DefaultSelector()
        sel.register(stdout_stream, selectors.EVENT_READ)
        sel.register(stderr_stream, selectors.EVENT_READ)
        ok = True
        while ok:
            for key, val1 in sel.select():
                del val1  # unused
                stream = cast(IO[str], key.fileobj)
                line = stream.readline()
                if not line:
                    ok = False
                    break
                if line.endswith("\n"):
                    line = line[:-1]
                if stream is stdout_stream:
                    log.info(line)
                else:
                    log.error(line)

    else:

        def enqueue_stream(
            stream: IO[str],
            item_queue: "queue.Queue[tuple[int | str, str]]",
            kind: int,
        ) -> None:
            last_line = ""
            for line in iter(stream.readline, ""):
                if line == "":
                    break
                item_queue.put((kind, line))
                last_line = line
            log.debug("stream close %r %r", kind, last_line)
            stream.close()

        def enqueue_process(
            process: subprocess.Popen[str],
            item_queue: "queue.Queue[tuple[int | str, str]]",
        ) -> None:
            process.wait()
            item_queue.put(("x", ""))

        p = subprocess.Popen(*args, **kwargs)
        stdout_stream = p.stdout
        stderr_stream = p.stderr
        if stdout_stream is None or stderr_stream is None:
            p.wait()
            raise RelenvException("Process pipes are unavailable")
        q: "queue.Queue[tuple[int | str, str]]" = queue.Queue()
        to = threading.Thread(target=enqueue_stream, args=(stdout_stream, q, 1))
        te = threading.Thread(target=enqueue_stream, args=(stderr_stream, q, 2))
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


def relative_interpreter(
    root_dir: Union[str, os.PathLike[str]],
    scripts_dir: Union[str, os.PathLike[str]],
    interpreter: Union[str, os.PathLike[str]],
) -> pathlib.Path:
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


def makepath(*paths: Union[str, os.PathLike[str]]) -> tuple[str, str]:
    """
    Make a normalized path name from paths.
    """
    dir = os.path.join(*paths)
    try:
        dir = os.path.abspath(dir)
    except OSError:
        pass
    return dir, os.path.normcase(dir)


def addpackage(sitedir: str, name: Union[str, os.PathLike[str]]) -> list[str] | None:
    """
    Add editable package to path.
    """
    import io
    import stat

    fullname = os.path.join(sitedir, os.fspath(name))
    paths: list[str] = []
    try:
        st = os.lstat(fullname)
    except OSError:
        return None
    file_attr_hidden = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
    uf_hidden = getattr(stat, "UF_HIDDEN", 0)
    if (getattr(st, "st_flags", 0) & uf_hidden) or (
        getattr(st, "st_file_attributes", 0) & file_attr_hidden
    ):
        # print(f"Skipping hidden .pth file: {fullname!r}")
        return None
    # print(f"Processing .pth file: {fullname!r}")
    try:
        # locale encoding is not ideal especially on Windows. But we have used
        # it for a long time. setuptools uses the locale encoding too.
        f = io.TextIOWrapper(io.open_code(fullname), encoding="locale")
    except OSError:
        return None
    with f:
        for n, line in enumerate(f):
            if line.startswith("#"):
                continue
            if line.strip() == "":
                continue
            try:
                if line.startswith(("import ", "import\t")):
                    exec(line)
                    continue
                line = line.rstrip()
                dir, dircase = makepath(sitedir, line)
                if dircase not in paths and os.path.exists(dir):
                    paths.append(dir)
            except Exception:
                print(
                    "Error processing line {:d} of {}:\n".format(n + 1, fullname),
                    file=sys.stderr,
                )
                import traceback

                for record in traceback.format_exception(*sys.exc_info()):
                    for line in record.splitlines():
                        print("  " + line, file=sys.stderr)
                print("\nRemainder of file ignored", file=sys.stderr)
                break
    return paths


def sanitize_sys_path(sys_path_entries: Iterable[str]) -> list[str]:
    """
    Sanitize `sys.path` to only include paths relative to the onedir environment.
    """
    __sys_path: list[str] = []
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
    for known_path in __sys_path[:]:
        for _ in pathlib.Path(known_path).glob("__editable__.*.pth"):
            paths = addpackage(known_path, _)
            if not paths:
                continue
            for p in paths:
                if p not in __sys_path:
                    __sys_path.append(p)
    return __sys_path


class Version:
    """
    Version comparisons.
    """

    def __init__(self, data: str) -> None:
        major, minor, micro = self.parse_string(data)
        self.major: int = major
        self.minor: Optional[int] = minor
        self.micro: Optional[int] = micro
        self._data: str = data

    def __str__(self: "Version") -> str:
        """
        Version as string.
        """
        result = f"{self.major}"
        if self.minor is not None:
            result += f".{self.minor}"
            if self.micro is not None:
                result += f".{self.micro}"
        # XXX What if minor was None but micro was an int.
        return result

    def __hash__(self: "Version") -> int:
        """
        Hash of the version.

        Hash the major, minor, and micro attributes.
        """
        return hash((self.major, self.minor, self.micro))

    @staticmethod
    def parse_string(data: str) -> tuple[int, Optional[int], Optional[int]]:
        """
        Parse a version string into major, minor, and micro integers.
        """
        parts = data.split(".")
        if len(parts) == 1:
            return int(parts[0]), None, None
        elif len(parts) == 2:
            return int(parts[0]), int(parts[1]), None
        elif len(parts) == 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
        else:
            raise RuntimeError("Too many parts to  parse")

    def __eq__(self: "Version", other: object) -> bool:
        """
        Equality comparisons.
        """
        if not isinstance(other, Version):
            return NotImplemented
        mymajor = 0 if self.major is None else self.major
        myminor = 0 if self.minor is None else self.minor
        mymicro = 0 if self.micro is None else self.micro
        major = 0 if other.major is None else other.major
        minor = 0 if other.minor is None else other.minor
        micro = 0 if other.micro is None else other.micro
        return mymajor == major and myminor == minor and mymicro == micro

    def __lt__(self: "Version", other: object) -> bool:
        """
        Less than comparrison.
        """
        if not isinstance(other, Version):
            return NotImplemented
        mymajor = 0 if self.major is None else self.major
        myminor = 0 if self.minor is None else self.minor
        mymicro = 0 if self.micro is None else self.micro
        major = 0 if other.major is None else other.major
        minor = 0 if other.minor is None else other.minor
        micro = 0 if other.micro is None else other.micro
        if mymajor < major:
            return True
        elif mymajor == major:
            if myminor < minor:
                return True
            if myminor == minor and mymicro < micro:
                return True
        return False

    def __le__(self: "Version", other: object) -> bool:
        """
        Less than or equal to comparrison.
        """
        if not isinstance(other, Version):
            return NotImplemented
        mymajor = 0 if self.major is None else self.major
        myminor = 0 if self.minor is None else self.minor
        mymicro = 0 if self.micro is None else self.micro
        major = 0 if other.major is None else other.major
        minor = 0 if other.minor is None else other.minor
        micro = 0 if other.micro is None else other.micro
        if mymajor <= major:
            if myminor <= minor:
                if mymicro <= micro:
                    return True
        return False

    def __gt__(self: "Version", other: object) -> bool:
        """
        Greater than comparrison.
        """
        if not isinstance(other, Version):
            return NotImplemented
        return not self.__le__(other)

    def __ge__(self: "Version", other: object) -> bool:
        """
        Greater than or equal to comparrison.
        """
        if not isinstance(other, Version):
            return NotImplemented
        return not self.__lt__(other)
