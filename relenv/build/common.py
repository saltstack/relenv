# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
Build process common methods.
"""
from __future__ import annotations

import fnmatch
import hashlib
import io
import logging
import multiprocessing
import os
import os.path
import pathlib
import pprint
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tarfile
from html.parser import HTMLParser
from types import ModuleType
from typing import (
    Any,
    Callable,
    Dict,
    IO,
    List,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

from typing import TYPE_CHECKING, Protocol, TypedDict

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event as SyncEvent
else:
    SyncEvent = Any

from relenv.common import (
    DATA_DIR,
    LINUX,
    MODULE_DIR,
    RelenvException,
    build_arch,
    download_url,
    extract_archive,
    format_shebang,
    get_download_location,
    get_toolchain,
    get_triplet,
    runcmd,
    work_dirs,
    fetch_url,
    Version,
    WorkDirs,
)
import relenv.relocate


PathLike = Union[str, os.PathLike[str]]


CHECK_VERSIONS_SUPPORT = True
try:
    from packaging.version import InvalidVersion, parse
    from looseversion import LooseVersion
except ImportError:
    CHECK_VERSIONS_SUPPORT = False

log = logging.getLogger(__name__)


GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
END = "\033[0m"
MOVEUP = "\033[F"


CICD = "CI" in os.environ
NODOWLOAD = False


RELENV_PTH = (
    "import os; "
    "import sys; "
    "from importlib import util; "
    "from pathlib import Path; "
    "spec = util.spec_from_file_location("
    "'relenv.runtime', str(Path(__file__).parent / 'site-packages' / 'relenv' / 'runtime.py')"
    "); "
    "mod = util.module_from_spec(spec); "
    "sys.modules['relenv.runtime'] = mod; "
    "spec.loader.exec_module(mod); mod.bootstrap();"
)


SYSCONFIGDATA = """
import pathlib, sys, platform, os, logging

log = logging.getLogger(__name__)

def build_arch():
    machine = platform.machine()
    return machine.lower()

def get_triplet(machine=None, plat=None):
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
        raise RelenvException("Unknown platform {}".format(platform))



pydir = pathlib.Path(__file__).resolve().parent
if sys.platform == "win32":
    DEFAULT_DATA_DIR = pathlib.Path.home() / "AppData" / "Local" / "relenv"
else:
    DEFAULT_DATA_DIR = pathlib.Path.home() / ".local" / "relenv"

if "RELENV_DATA" in os.environ:
    DATA_DIR = pathlib.Path(os.environ["RELENV_DATA"]).resolve()
else:
    DATA_DIR = DEFAULT_DATA_DIR

buildroot = pydir.parent.parent

toolchain = DATA_DIR / "toolchain" / get_triplet()

build_time_vars = {}
for key in _build_time_vars:
    val = _build_time_vars[key]
    orig = val
    if isinstance(val, str):
        val = val.format(
            BUILDROOT=buildroot,
            TOOLCHAIN=toolchain,
        )
    build_time_vars[key] = val
"""


def print_ui(
    events: MutableMapping[str, "multiprocessing.synchronize.Event"],
    processes: MutableMapping[str, multiprocessing.Process],
    fails: Sequence[str],
    flipstat: Optional[Dict[str, Tuple[int, float]]] = None,
) -> None:
    """
    Prints the UI during the relenv building process.

    :param events: A dictionary of events that are updated during the build process
    :type events: dict
    :param processes: A dictionary of build processes
    :type processes: dict
    :param fails: A list of processes that have failed
    :type fails: list
    :param flipstat: A dictionary of process statuses, defaults to {}
    :type flipstat: dict, optional
    """
    if flipstat is None:
        flipstat = {}
    if CICD:
        sys.stdout.flush()
        return
    uiline = []
    for name in events:
        if not events[name].is_set():
            status = " {}.".format(YELLOW)
        elif name in processes:
            now = time.time()
            if name not in flipstat:
                flipstat[name] = (0, now)
            if flipstat[name][1] < now:
                flipstat[name] = (1 - flipstat[name][0], now + random.random())
            status = " {}{}".format(GREEN, " " if flipstat[name][0] == 1 else ".")
        elif name in fails:
            status = " {}\u2718".format(RED)
        else:
            status = " {}\u2718".format(GREEN)
        uiline.append(status)
    uiline.append("  " + END)
    sys.stdout.write("\r")
    sys.stdout.write("".join(uiline))
    sys.stdout.flush()


def verify_checksum(file: PathLike, checksum: Optional[str]) -> bool:
    """
    Verify the checksum of a files.

    :param file: The path to the file to check.
    :type file: str
    :param checksum: The checksum to verify against
    :type checksum: str

    :raises RelenvException: If the checksum verification failed

    :return: True if it succeeded, or False if the checksum was None
    :rtype: bool
    """
    if checksum is None:
        log.error("Can't verify checksum because none was given")
        return False
    with open(file, "rb") as fp:
        file_checksum = hashlib.sha1(fp.read()).hexdigest()
        if checksum != file_checksum:
            raise RelenvException(
                f"sha1 checksum verification failed. expected={checksum} found={file_checksum}"
            )
    return True


def all_dirs(root: PathLike, recurse: bool = True) -> List[str]:
    """
    Get all directories under and including the given root.

    :param root: The root directory to traverse
    :type root: str
    :param recurse: Whether to recursively search for directories, defaults to True
    :type recurse: bool, optional

    :return: A list of directories found
    :rtype: list
    """
    root_str = os.fspath(root)
    paths: List[str] = [root_str]
    for current_root, dirs, _files in os.walk(root_str):
        if not recurse and current_root != root_str:
            continue
        for name in dirs:
            paths.append(os.path.join(current_root, name))
    return paths


def populate_env(env: MutableMapping[str, str], dirs: "Dirs") -> None:
    """Populate environment variables for a build step.

    This default implementation intentionally does nothing; specific steps may
    provide their own implementation via the ``populate_env`` hook.
    """
    _ = env
    _ = dirs


def build_default(env: MutableMapping[str, str], dirs: "Dirs", logfp: IO[str]) -> None:
    """
    The default build function if none is given during the build process.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    cmd = [
        "./configure",
        "--prefix={}".format(dirs.prefix),
    ]
    if env["RELENV_HOST"].find("linux") > -1:
        cmd += [
            "--build={}".format(env["RELENV_BUILD"]),
            "--host={}".format(env["RELENV_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_openssl_fips(
    env: MutableMapping[str, str], dirs: "Dirs", logfp: IO[str]
) -> None:
    return build_openssl(env, dirs, logfp, fips=True)


def build_openssl(
    env: MutableMapping[str, str],
    dirs: "Dirs",
    logfp: IO[str],
    fips: bool = False,
) -> None:
    """
    Build openssl.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    arch = "aarch64"
    if sys.platform == "darwin":
        plat = "darwin64"
        if env["RELENV_HOST_ARCH"] == "x86_64":
            arch = "x86_64-cc"
        elif env["RELENV_HOST_ARCH"] == "arm64":
            arch = "arm64-cc"
        else:
            raise RelenvException(f"Unable to build {env['RELENV_HOST_ARCH']}")
        extended_cmd = []
    else:
        plat = "linux"
        if env["RELENV_HOST_ARCH"] == "x86_64":
            arch = "x86_64"
        elif env["RELENV_HOST_ARCH"] == "aarch64":
            arch = "aarch64"
        else:
            raise RelenvException(f"Unable to build {env['RELENV_HOST_ARCH']}")
        extended_cmd = [
            "-Wl,-z,noexecstack",
        ]
    if fips:
        extended_cmd.append("enable-fips")
    cmd = [
        "./Configure",
        f"{plat}-{arch}",
        f"--prefix={dirs.prefix}",
        "--openssldir=/etc/ssl",
        "--libdir=lib",
        "--api=1.1.1",
        "--shared",
        "--with-rand-seed=os,egd",
        "enable-md2",
        "enable-egd",
        "no-idea",
    ]
    cmd.extend(extended_cmd)
    runcmd(
        cmd,
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    if fips:
        shutil.copy(
            pathlib.Path("providers") / "fips.so",
            pathlib.Path(dirs.prefix) / "lib" / "ossl-modules",
        )
    else:
        runcmd(["make", "install_sw"], env=env, stderr=logfp, stdout=logfp)


def build_sqlite(env: MutableMapping[str, str], dirs: "Dirs", logfp: IO[str]) -> None:
    """
    Build sqlite.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    # extra_cflags=('-Os '
    #              '-DSQLITE_ENABLE_FTS5 '
    #              '-DSQLITE_ENABLE_FTS4 '
    #              '-DSQLITE_ENABLE_FTS3_PARENTHESIS '
    #              '-DSQLITE_ENABLE_JSON1 '
    #              '-DSQLITE_ENABLE_RTREE '
    #              '-DSQLITE_TCL=0 '
    #              )
    # configure_pre=[
    #    '--enable-threadsafe',
    #    '--enable-shared=no',
    #    '--enable-static=yes',
    #    '--disable-readline',
    #    '--disable-dependency-tracking',
    # ]
    cmd = [
        "./configure",
        #     "--with-shared",
        #    "--without-static",
        "--enable-threadsafe",
        "--disable-readline",
        "--disable-dependency-tracking",
        "--prefix={}".format(dirs.prefix),
        #    "--enable-add-ons=nptl,ports",
    ]
    if env["RELENV_HOST"].find("linux") > -1:
        cmd += [
            "--build={}".format(env["RELENV_BUILD_ARCH"]),
            "--host={}".format(env["RELENV_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def update_ensurepip(directory: pathlib.Path) -> None:
    """
    Update bundled dependencies for ensurepip (pip & setuptools).
    """
    # ensurepip bundle location
    bundle_dir = directory / "ensurepip" / "_bundled"

    # Make sure the destination directory exists
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Detect existing whl. Later versions of python don't include setuptools. We
    # only want to update whl files that python expects to be there
    pip_version = "25.2"
    setuptools_version = "80.9.0"
    update_pip = False
    update_setuptools = False
    for file in bundle_dir.glob("*.whl"):

        log.debug("Checking whl: %s", str(file))
        if file.name.startswith("pip-"):
            found_version = file.name.split("-")[1]
            log.debug("Found version %s", found_version)
            if Version(found_version) >= Version(pip_version):
                log.debug("Found correct pip version or newer: %s", found_version)
            else:
                file.unlink()
                update_pip = True
        if file.name.startswith("setuptools-"):
            found_version = file.name.split("-")[1]
            log.debug("Found version %s", found_version)
            if Version(found_version) >= Version(setuptools_version):
                log.debug(
                    "Found correct setuptools version or newer: %s", found_version
                )
            else:
                file.unlink()
                update_setuptools = True

    # Download whl files and update __init__.py
    init_file = directory / "ensurepip" / "__init__.py"
    if update_pip:
        whl = f"pip-{pip_version}-py3-none-any.whl"
        whl_path = "b7/3f/945ef7ab14dc4f9d7f40288d2df998d1837ee0888ec3659c813487572faa"
        url = f"https://files.pythonhosted.org/packages/{whl_path}/{whl}"
        download_url(url=url, dest=bundle_dir)
        assert (bundle_dir / whl).exists()

        # Update __init__.py
        old = "^_PIP_VERSION.*"
        new = f'_PIP_VERSION = "{pip_version}"'
        patch_file(path=init_file, old=old, new=new)

    # setuptools
    if update_setuptools:
        whl = f"setuptools-{setuptools_version}-py3-none-any.whl"
        whl_path = "a3/dc/17031897dae0efacfea57dfd3a82fdd2a2aeb58e0ff71b77b87e44edc772"
        url = f"https://files.pythonhosted.org/packages/{whl_path}/{whl}"
        download_url(url=url, dest=bundle_dir)
        assert (bundle_dir / whl).exists()

        # setuptools
        old = "^_SETUPTOOLS_VERSION.*"
        new = f'_SETUPTOOLS_VERSION = "{setuptools_version}"'
        patch_file(path=init_file, old=old, new=new)

    log.debug("ensurepip __init__.py contents:")
    log.debug(init_file.read_text())


def patch_file(path: PathLike, old: str, new: str) -> None:
    """
    Search a file line by line for a string to replace.

    :param path: Location of the file to search
    :type path: str
    :param old: The value that will be replaced
    :type path: str
    :param new: The value that will replace the 'old' value.
    :type path: str
    """
    log.debug("Patching file: %s", path)
    import re

    with open(path, "r") as fp:
        content = fp.read()
    new_content = ""
    for line in content.splitlines():
        line = re.sub(old, new, line)
        new_content += line + "\n"
    with open(path, "w") as fp:
        fp.write(new_content)


def tarball_version(href: str) -> Optional[str]:
    if href.endswith("tar.gz"):
        try:
            x = href.split("-", 1)[1][:-7]
            if x != "latest":
                return x
        except IndexError:
            return None
    return None


def sqlite_version(href: str) -> Optional[str]:
    if "releaselog" in href:
        link = href.split("/")[1][:-5]
        return "{:d}{:02d}{:02d}00".format(*[int(_) for _ in link.split("_")])
    return None


def github_version(href: str) -> Optional[str]:
    if "tag/" in href:
        return href.split("/v")[-1]
    return None


def krb_version(href: str) -> Optional[str]:
    if re.match(r"\d\.\d\d/", href):
        return href[:-1]
    return None


def python_version(href: str) -> Optional[str]:
    if re.match(r"(\d+\.)+\d/", href):
        return href[:-1]
    return None


def uuid_version(href: str) -> Optional[str]:
    if "download" in href and "latest" not in href:
        return href[:-16].rsplit("/")[-1].replace("libuuid-", "")
    return None


def parse_links(text: str) -> List[str]:
    class HrefParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.hrefs: List[str] = []

        def handle_starttag(
            self, tag: str, attrs: List[Tuple[str, Optional[str]]]
        ) -> None:
            if tag == "a":
                link = dict(attrs).get("href")
                if link:
                    self.hrefs.append(link)

    parser = HrefParser()
    parser.feed(text)
    return parser.hrefs


class Comparable(Protocol):
    """Protocol capturing the comparison operations we rely on."""

    def __lt__(self, other: Any) -> bool:
        """Return True when self is ordered before *other*."""

    def __gt__(self, other: Any) -> bool:
        """Return True when self is ordered after *other*."""


def check_files(
    name: str,
    location: str,
    func: Optional[Callable[[str], Optional[str]]],
    current: str,
) -> None:
    fp = io.BytesIO()
    fetch_url(location, fp)
    fp.seek(0)
    text = fp.read().decode()
    loose = False
    current_version: Comparable
    try:
        current_version = cast(Comparable, parse(current))
    except InvalidVersion:
        current_version = LooseVersion(current)
        loose = True

    versions: List[Comparable] = []
    if func is None:
        return
    for link in parse_links(text):
        version = func(link)
        if version:
            if loose:
                versions.append(LooseVersion(version))
            else:
                try:
                    versions.append(cast(Comparable, parse(version)))
                except InvalidVersion:
                    pass
    versions.sort()
    compare_versions(name, current_version, versions)


def compare_versions(
    name: str, current: Comparable, versions: Sequence[Comparable]
) -> None:
    for version in versions:
        try:
            if version > current:
                print(f"Found new version of {name} {version} > {current}")
        except TypeError:
            print(f"Unable to compare versions {version}")


class Download:
    """
    A utility that holds information about content to be downloaded.

    :param name: The name of the download
    :type name: str
    :param url: The url of the download
    :type url: str
    :param signature: The signature of the download, defaults to None
    :type signature: str
    :param destination: The path to download the file to
    :type destination: str
    :param version: The version of the content to download
    :type version: str
    :param sha1: The sha1 sum of the download
    :type sha1: str

    """

    def __init__(
        self,
        name: str,
        url: str,
        fallback_url: Optional[str] = None,
        signature: Optional[str] = None,
        destination: PathLike = "",
        version: str = "",
        checksum: Optional[str] = None,
        checkfunc: Optional[Callable[[str], Optional[str]]] = None,
        checkurl: Optional[str] = None,
    ) -> None:
        self.name = name
        self.url_tpl = url
        self.fallback_url_tpl = fallback_url
        self.signature_tpl = signature
        self._destination: pathlib.Path = pathlib.Path()
        if destination:
            self._destination = pathlib.Path(destination)
        self.version = version
        self.checksum = checksum
        self.checkfunc = checkfunc
        self.checkurl = checkurl

    def copy(self) -> "Download":
        return Download(
            self.name,
            self.url_tpl,
            self.fallback_url_tpl,
            self.signature_tpl,
            self.destination,
            self.version,
            self.checksum,
            self.checkfunc,
            self.checkurl,
        )

    @property
    def destination(self) -> pathlib.Path:
        return self._destination

    @destination.setter
    def destination(self, value: Optional[PathLike]) -> None:
        if value:
            self._destination = pathlib.Path(value)
        else:
            self._destination = pathlib.Path()

    @property
    def url(self) -> str:
        return self.url_tpl.format(version=self.version)

    @property
    def fallback_url(self) -> Optional[str]:
        if self.fallback_url_tpl:
            return self.fallback_url_tpl.format(version=self.version)
        return None

    @property
    def signature_url(self) -> str:
        if self.signature_tpl is None:
            raise RelenvException("Signature template not configured")
        return self.signature_tpl.format(version=self.version)

    @property
    def filepath(self) -> pathlib.Path:
        _, name = self.url.rsplit("/", 1)
        return self.destination / name

    @property
    def formatted_url(self) -> str:
        return self.url_tpl.format(version=self.version)

    def fetch_file(self) -> Tuple[str, bool]:
        """
        Download the file.

        :return: The path to the downloaded content, and whether it was downloaded.
        :rtype: tuple(str, bool)
        """
        try:
            return download_url(self.url, self.destination, CICD), True
        except Exception as exc:
            fallback = self.fallback_url
            if fallback:
                print(f"Download failed {self.url} ({exc}); trying fallback url")
                return download_url(fallback, self.destination, CICD), True
            raise

    def fetch_signature(self, version: Optional[str] = None) -> Tuple[str, bool]:
        """
        Download the file signature.

        :return: The path to the downloaded signature.
        :rtype: str
        """
        return download_url(self.signature_url, self.destination, CICD), True

    def exists(self) -> bool:
        """
        True when the artifact already exists on disk.

        :return: True when the artifact already exists on disk
        :rtype: bool
        """
        return self.filepath.exists()

    def valid_hash(self) -> None:
        pass

    @staticmethod
    def validate_signature(archive: PathLike, signature: Optional[PathLike]) -> bool:
        """
        True when the archive's signature is valid.

        :param archive: The path to the archive to validate
        :type archive: str
        :param signature: The path to the signature to validate against
        :type signature: str

        :return: True if it validated properly, else False
        :rtype: bool
        """
        if signature is None:
            log.error("Can't check signature because none was given")
            return False
        try:
            runcmd(
                ["gpg", "--verify", signature, archive],
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            return True
        except RelenvException as exc:
            log.error("Signature validation failed on %s: %s", archive, exc)
            return False

    @staticmethod
    def validate_checksum(archive: PathLike, checksum: Optional[str]) -> bool:
        """
        True when when the archive matches the sha1 hash.

        :param archive: The path to the archive to validate
        :type archive: str
        :param checksum: The sha1 sum to validate against
        :type checksum: str
        :return: True if the sums matched, else False
        :rtype: bool
        """
        try:
            verify_checksum(archive, checksum)
            return True
        except RelenvException as exc:
            log.error("sha1 validation failed on %s: %s", archive, exc)
            return False

    def __call__(
        self,
        force_download: bool = False,
        show_ui: bool = False,
        exit_on_failure: bool = False,
    ) -> bool:
        """
        Downloads the url and validates the signature and sha1 sum.

        :return: Whether or not validation succeeded
        :rtype: bool
        """
        os.makedirs(self.filepath.parent, exist_ok=True)

        downloaded = False
        if force_download:
            _, downloaded = self.fetch_file()
        else:
            file_is_valid = False
            dest = get_download_location(self.url, self.destination)
            if self.checksum and os.path.exists(dest):
                file_is_valid = self.validate_checksum(dest, self.checksum)
            if file_is_valid:
                log.debug("%s already downloaded, skipping.", self.url)
            else:
                _, downloaded = self.fetch_file()
        valid = True
        if downloaded:
            if self.signature_tpl is not None:
                sig, _ = self.fetch_signature()
                valid_sig = self.validate_signature(self.filepath, sig)
                valid = valid and valid_sig
            if self.checksum is not None:
                valid_checksum = self.validate_checksum(self.filepath, self.checksum)
                valid = valid and valid_checksum

            if not valid:
                log.warning("Checksum did not match %s: %s", self.name, self.checksum)
                if show_ui:
                    sys.stderr.write(
                        f"\nChecksum did not match {self.name}: {self.checksum}\n"
                    )
                    sys.stderr.flush()
        if exit_on_failure and not valid:
            sys.exit(1)
        return valid

    def check_version(self) -> bool:
        if self.checkfunc is None:
            return True
        if self.checkurl:
            url = self.checkurl
        else:
            url = self.url.rsplit("/", 1)[0]
        check_files(self.name, url, self.checkfunc, self.version)
        return True


class Recipe(TypedDict):
    """Typed description of a build recipe entry."""

    build_func: Callable[[MutableMapping[str, str], "Dirs", IO[str]], None]
    wait_on: List[str]
    download: Optional[Download]


class Dirs:
    """
    A container for directories during build time.

    :param dirs: A collection of working directories
    :type dirs: ``relenv.common.WorkDirs``
    :param name: The name of this collection
    :type name: str
    :param arch: The architecture being worked with
    :type arch: str
    """

    def __init__(self, dirs: WorkDirs, name: str, arch: str, version: str) -> None:
        # XXX name is the specific to a step where as everything
        # else here is generalized to the entire build
        self.name = name
        self.version = version
        self.arch = arch
        self.root = dirs.root
        self.build = dirs.build
        self.downloads = dirs.download
        self.logs = dirs.logs
        self.sources = dirs.src
        self.tmpbuild = tempfile.mkdtemp(prefix="{}_build".format(name))
        self.source: Optional[pathlib.Path] = None

    @property
    def toolchain(self) -> Optional[pathlib.Path]:
        if sys.platform == "darwin":
            return get_toolchain(root=self.root)
        elif sys.platform == "win32":
            return get_toolchain(root=self.root)
        else:
            return get_toolchain(self.arch, self.root)

    @property
    def _triplet(self) -> str:
        if sys.platform == "darwin":
            return "{}-macos".format(self.arch)
        elif sys.platform == "win32":
            return "{}-win".format(self.arch)
        else:
            return "{}-linux-gnu".format(self.arch)

    @property
    def prefix(self) -> pathlib.Path:
        return self.build / f"{self.version}-{self._triplet}"

    def __getstate__(self) -> Dict[str, Any]:
        """
        Return an object used for pickling.

        :return: The picklable state
        """
        return {
            "name": self.name,
            "arch": self.arch,
            "root": self.root,
            "build": self.build,
            "downloads": self.downloads,
            "logs": self.logs,
            "sources": self.sources,
            "tmpbuild": self.tmpbuild,
        }

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """
        Unwrap the object returned from unpickling.

        :param state: The state to unpickle
        :type state: dict
        """
        self.name = state["name"]
        self.arch = state["arch"]
        self.root = state["root"]
        self.downloads = state["downloads"]
        self.logs = state["logs"]
        self.sources = state["sources"]
        self.build = state["build"]
        self.tmpbuild = state["tmpbuild"]

    def to_dict(self) -> Dict[str, Any]:
        """
        Get a dictionary representation of the directories in this collection.

        :return: A dictionary of all the directories
        :rtype: dict
        """
        return {
            x: getattr(self, x)
            for x in [
                "root",
                "prefix",
                "downloads",
                "logs",
                "sources",
                "build",
                "toolchain",
            ]
        }


class Builder:
    """
    Utility that handles the build process.

    :param root: The root of the working directories for this build
    :type root: str
    :param recipies: The instructions for the build steps
    :type recipes: list
    :param build_default: The default build function, defaults to ``build_default``
    :type build_default: types.FunctionType
    :param populate_env: The default function to populate the build environment, defaults to ``populate_env``
    :type populate_env: types.FunctionType
    :param force_download: If True, forces downloading the archives even if they exist, defaults to False
    :type force_download: bool
    :param arch: The architecture being built
    :type arch: str
    """

    def __init__(
        self,
        root: Optional[PathLike] = None,
        recipies: Optional[Dict[str, Recipe]] = None,
        build_default: Callable[
            [MutableMapping[str, str], "Dirs", IO[str]], None
        ] = build_default,
        populate_env: Callable[[MutableMapping[str, str], "Dirs"], None] = populate_env,
        arch: str = "x86_64",
        version: str = "",
    ) -> None:
        self.root = root
        self.dirs: WorkDirs = work_dirs(root)
        self.build_arch = build_arch()
        self.build_triplet = get_triplet(self.build_arch)
        self.arch = arch
        self.sources = self.dirs.src
        self.downloads = self.dirs.download

        if recipies is None:
            self.recipies: Dict[str, Recipe] = {}
        else:
            self.recipies = recipies

        self.build_default = build_default
        self.populate_env = populate_env
        self.version = version
        self.set_arch(self.arch)

    def copy(self, version: str, checksum: Optional[str]) -> "Builder":
        recipies: Dict[str, Recipe] = {}
        for name in self.recipies:
            recipe = self.recipies[name]
            recipies[name] = {
                "build_func": recipe["build_func"],
                "wait_on": list(recipe["wait_on"]),
                "download": recipe["download"].copy() if recipe["download"] else None,
            }
        build = Builder(
            self.root,
            recipies,
            self.build_default,
            self.populate_env,
            self.arch,
            version,
        )
        python_download = build.recipies["python"].get("download")
        if python_download is None:
            raise RelenvException("Python recipe is missing a download entry")
        python_download.version = version
        python_download.checksum = checksum
        return build

    def set_arch(self, arch: str) -> None:
        """
        Set the architecture for the build.

        :param arch: The arch to build
        :type arch: str
        """
        self.arch = arch
        self._toolchain: Optional[pathlib.Path] = None

    @property
    def toolchain(self) -> Optional[pathlib.Path]:
        """Lazily fetch toolchain only when needed."""
        if self._toolchain is None and sys.platform == "linux":
            self._toolchain = get_toolchain(self.arch, self.dirs.root)
        return self._toolchain

    @property
    def triplet(self) -> str:
        return get_triplet(self.arch)

    @property
    def prefix(self) -> pathlib.Path:
        return self.dirs.build / f"{self.version}-{self.triplet}"

    @property
    def _triplet(self) -> str:
        if sys.platform == "darwin":
            return "{}-macos".format(self.arch)
        elif sys.platform == "win32":
            return "{}-win".format(self.arch)
        else:
            return "{}-linux-gnu".format(self.arch)

    def add(
        self,
        name: str,
        build_func: Optional[Callable[..., Any]] = None,
        wait_on: Optional[Sequence[str]] = None,
        download: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add a step to the build process.

        :param name: The name of the step
        :type name: str
        :param build_func: The function that builds this step, defaults to None
        :type build_func: types.FunctionType, optional
        :param wait_on: Processes to wait on before running this step, defaults to None
        :type wait_on: list, optional
        :param download: A dictionary of download information, defaults to None
        :type download: dict, optional
        """
        if wait_on is None:
            wait_on_list: List[str] = []
        else:
            wait_on_list = list(wait_on)
        if build_func is None:
            build_func = self.build_default
        download_obj: Optional[Download] = None
        if download is not None:
            download_obj = Download(name, destination=self.downloads, **download)
        self.recipies[name] = {
            "build_func": build_func,
            "wait_on": wait_on_list,
            "download": download_obj,
        }

    def run(
        self,
        name: str,
        event: "multiprocessing.synchronize.Event",
        build_func: Callable[..., Any],
        download: Optional[Download],
        show_ui: bool = False,
        log_level: str = "WARNING",
    ) -> Any:
        """
        Run a build step.

        :param name: The name of the step to run
        :type name: str
        :param event: An event to track this process' status and alert waiting steps
        :type event: ``multiprocessing.Event``
        :param build_func: The function to use to build this step
        :type build_func: types.FunctionType
        :param download: The ``Download`` instance for this step
        :type download: ``Download``

        :return: The output of the build function
        """
        root_log = logging.getLogger(None)
        if sys.platform == "win32":
            if not show_ui:
                handler = logging.StreamHandler()
                handler.setLevel(logging.getLevelName(log_level))
                root_log.addHandler(handler)

        for handler in root_log.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setFormatter(
                    logging.Formatter(f"%(asctime)s {name} %(message)s")
                )

        if not self.dirs.build.exists():
            os.makedirs(self.dirs.build, exist_ok=True)

        dirs = Dirs(self.dirs, name, self.arch, self.version)
        os.makedirs(dirs.sources, exist_ok=True)
        os.makedirs(dirs.logs, exist_ok=True)
        os.makedirs(dirs.prefix, exist_ok=True)

        while event.is_set() is False:
            time.sleep(0.3)

        logfp = io.open(os.path.join(dirs.logs, "{}.log".format(name)), "w")
        handler = logging.FileHandler(dirs.logs / f"{name}.log")
        root_log.addHandler(handler)
        root_log.setLevel(logging.NOTSET)

        # DEBUG: Uncomment to debug
        # logfp = sys.stdout

        cwd = os.getcwd()
        if download:
            extract_archive(dirs.sources, str(download.filepath))
            dirs.source = dirs.sources / download.filepath.name.split(".tar")[0]
            os.chdir(dirs.source)
        else:
            os.chdir(dirs.prefix)

        if sys.platform == "win32":
            env = os.environ.copy()
        else:
            env = {
                "PATH": os.environ["PATH"],
            }
        env["RELENV_DEBUG"] = "1"
        env["RELENV_BUILDENV"] = "1"
        env["RELENV_HOST"] = self.triplet
        env["RELENV_HOST_ARCH"] = self.arch
        env["RELENV_BUILD"] = self.build_triplet
        env["RELENV_BUILD_ARCH"] = self.build_arch
        python_download = self.recipies["python"].get("download")
        if python_download is None:
            raise RelenvException("Python recipe is missing download configuration")
        env["RELENV_PY_VERSION"] = python_download.version
        env["RELENV_PY_MAJOR_VERSION"] = env["RELENV_PY_VERSION"].rsplit(".", 1)[0]
        if "RELENV_DATA" in os.environ:
            env["RELENV_DATA"] = os.environ["RELENV_DATA"]
        if self.build_arch != self.arch:
            native_root = DATA_DIR / "native"
            env["RELENV_NATIVE_PY"] = str(native_root / "bin" / "python3")

        self.populate_env(env, dirs)

        _ = dirs.to_dict()
        for k in _:
            log.info("Directory %s %s", k, _[k])
        for k in env:
            log.info("Environment %s %s", k, env[k])
        try:
            return build_func(env, dirs, logfp)
        except Exception:
            log.exception("Build failure")
            sys.exit(1)
        finally:
            os.chdir(cwd)
            log.removeHandler(handler)
            logfp.close()

    def cleanup(self) -> None:
        """
        Clean up the build directories.
        """
        shutil.rmtree(self.prefix)

    def clean(self) -> None:
        """
        Completely clean up the remnants of a relenv build.
        """
        # Clean directories
        for _ in [self.prefix, self.sources]:
            try:
                shutil.rmtree(_)
            except PermissionError:
                sys.stderr.write(f"Unable to remove directory: {_}")
            except FileNotFoundError:
                pass
        # Clean files
        archive = f"{self.prefix}.tar.xz"
        for _ in [archive]:
            try:
                os.remove(_)
            except FileNotFoundError:
                pass

    def download_files(
        self,
        steps: Optional[Sequence[str]] = None,
        force_download: bool = False,
        show_ui: bool = False,
    ) -> None:
        """
        Download all of the needed archives.

        :param steps: The steps to download archives for, defaults to None
        :type steps: list, optional
        """
        step_names = list(steps) if steps is not None else list(self.recipies)

        fails: List[str] = []
        processes: Dict[str, multiprocessing.Process] = {}
        events: Dict[str, SyncEvent] = {}
        if show_ui:
            sys.stdout.write("Starting downloads \n")
        log.info("Starting downloads")
        if show_ui:
            print_ui(events, processes, fails)
        for name in step_names:
            download = self.recipies[name]["download"]
            if download is None:
                continue
            event = multiprocessing.Event()
            event.set()
            events[name] = event
            proc = multiprocessing.Process(
                name=name,
                target=download,
                kwargs={
                    "force_download": force_download,
                    "show_ui": show_ui,
                    "exit_on_failure": True,
                },
            )
            proc.start()
            processes[name] = proc

        while processes:
            for proc in list(processes.values()):
                proc.join(0.3)
                # DEBUG: Comment to debug
                if show_ui:
                    print_ui(events, processes, fails)
                if proc.exitcode is None:
                    continue
                processes.pop(proc.name)
                if proc.exitcode != 0:
                    fails.append(proc.name)
        if show_ui:
            print_ui(events, processes, fails)
            sys.stdout.write("\n")
        if fails and False:
            if show_ui:
                print_ui(events, processes, fails)
                sys.stderr.write("The following failures were reported\n")
                for fail in fails:
                    sys.stderr.write(fail + "\n")
                sys.stderr.flush()
            sys.exit(1)

    def build(
        self,
        steps: Optional[Sequence[str]] = None,
        cleanup: bool = True,
        show_ui: bool = False,
        log_level: str = "WARNING",
    ) -> None:
        """
        Build!

        :param steps: The steps to run, defaults to None
        :type steps: list, optional
        :param cleanup: Whether to clean up or not, defaults to True
        :type cleanup: bool, optional
        """  # noqa: D400
        fails: List[str] = []
        events: Dict[str, SyncEvent] = {}
        waits: Dict[str, List[str]] = {}
        processes: Dict[str, multiprocessing.Process] = {}

        if show_ui:
            sys.stdout.write("Starting builds\n")
            # DEBUG: Comment to debug
            print_ui(events, processes, fails)
        log.info("Starting builds")

        step_names = list(steps) if steps is not None else list(self.recipies)

        for name in step_names:
            event = multiprocessing.Event()
            events[name] = event
            recipe = self.recipies[name]
            kwargs = dict(recipe)
            kwargs["show_ui"] = show_ui
            kwargs["log_level"] = log_level

            # Determine needed dependency recipies.
            wait_on_seq = cast(List[str], kwargs.pop("wait_on", []))
            wait_on_list = list(wait_on_seq)
            for dependency in wait_on_list[:]:
                if dependency not in step_names:
                    wait_on_list.remove(dependency)

            waits[name] = wait_on_list
            if not waits[name]:
                event.set()

            proc = multiprocessing.Process(
                name=name, target=self.run, args=(name, event), kwargs=kwargs
            )
            proc.start()
            processes[name] = proc

        # Wait for the processes to finish and check if we should send any
        # dependency events.
        while processes:
            for proc in list(processes.values()):
                proc.join(0.3)
                if show_ui:
                    # DEBUG: Comment to debug
                    print_ui(events, processes, fails)
                if proc.exitcode is None:
                    continue
                processes.pop(proc.name)
                if proc.exitcode != 0:
                    fails.append(proc.name)
                    is_failure = True
                else:
                    is_failure = False
                for name in waits:
                    if proc.name in waits[name]:
                        if is_failure:
                            if name in processes:
                                processes[name].terminate()
                                time.sleep(0.1)
                        waits[name].remove(proc.name)
                    if not waits[name] and not events[name].is_set():
                        events[name].set()

        if fails:
            sys.stderr.write("The following failures were reported\n")
            last_outs = {}
            for fail in fails:
                log_file = self.dirs.logs / f"{fail}.log"
                try:
                    with io.open(log_file) as fp:
                        fp.seek(0, 2)
                        end = fp.tell()
                        ind = end - 4096
                        if ind > 0:
                            fp.seek(ind)
                        else:
                            fp.seek(0)
                        last_out = fp.read()
                        if show_ui:
                            sys.stderr.write("=" * 20 + f" {fail} " + "=" * 20 + "\n")
                            sys.stderr.write(fp.read() + "\n\n")
                except FileNotFoundError:
                    last_outs[fail] = f"Log file not found: {log_file}"
                log.error("Build step %s has failed", fail)
                log.error(last_out)
            if show_ui:
                sys.stderr.flush()
            if cleanup:
                log.debug("Performing cleanup.")
                self.cleanup()
            sys.exit(1)
        if show_ui:
            time.sleep(0.3)
            print_ui(events, processes, fails)
            sys.stdout.write("\n")
            sys.stdout.flush()
        if cleanup:
            log.debug("Performing cleanup.")
            self.cleanup()

    def check_prereqs(self) -> List[str]:
        """
        Check pre-requsists for build.

        This method verifies all requrements for a successful build are satisfied.

        :return: Returns a list of string describing failed checks
        :rtype: list
        """
        fail: List[str] = []
        if sys.platform == "linux":
            if not self.toolchain or not self.toolchain.exists():
                fail.append(
                    f"Toolchain for {self.arch} does not exist. Please pip install ppbt."
                )
        return fail

    def __call__(
        self,
        steps: Optional[Sequence[str]] = None,
        arch: Optional[str] = None,
        clean: bool = True,
        cleanup: bool = True,
        force_download: bool = False,
        download_only: bool = False,
        show_ui: bool = False,
        log_level: str = "WARNING",
    ) -> None:
        """
        Set the architecture, define the steps, clean if needed, download what is needed, and build.

        :param steps: The steps to run, defaults to None
        :type steps: list, optional
        :param arch: The architecture to build, defaults to None
        :type arch: str, optional
        :param clean: If true, cleans the directories first, defaults to True
        :type clean: bool, optional
        :param cleanup: Cleans up after build if true, defaults to True
        :type cleanup: bool, optional
        :param force_download: Whether or not to download the content if it already exists, defaults to True
        :type force_download: bool, optional
        """
        log = logging.getLogger(None)
        log.setLevel(logging.NOTSET)

        stream_handler: Optional[logging.Handler] = None
        if not show_ui:
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.getLevelName(log_level))
            log.addHandler(stream_handler)

        os.makedirs(self.dirs.logs, exist_ok=True)
        file_handler = logging.FileHandler(self.dirs.logs / "build.log")
        file_handler.setLevel(logging.INFO)
        log.addHandler(file_handler)

        if arch:
            self.set_arch(arch)

        step_names = list(steps) if steps is not None else list(self.recipies)

        failures = self.check_prereqs()
        if not download_only and failures:
            for _ in failures:
                sys.stderr.write(f"{_}\n")
            sys.stderr.flush()
            sys.exit(1)

        if clean:
            self.clean()

        if self.build_arch != self.arch:
            native_root = DATA_DIR / "native"
            if not native_root.exists():
                if "RELENV_NATIVE_PY_VERSION" in os.environ:
                    version = os.environ["RELENV_NATIVE_PY_VERSION"]
                else:
                    version = self.version
                from relenv.create import create

                create("native", DATA_DIR, version=version)

        # Start a process for each build passing it an event used to notify each
        # process if it's dependencies have finished.
        try:
            self.download_files(
                step_names, force_download=force_download, show_ui=show_ui
            )
            if download_only:
                return
            self.build(step_names, cleanup, show_ui=show_ui, log_level=log_level)
        finally:
            log.removeHandler(file_handler)
            if stream_handler is not None:
                log.removeHandler(stream_handler)

    def check_versions(self) -> bool:
        success = True
        for step in list(self.recipies):
            download = self.recipies[step]["download"]
            if not download:
                continue
            if not download.check_version():
                success = False
        return success


class Builds:
    """Collection of platform-specific builders."""

    def __init__(self) -> None:
        self.builds: Dict[str, Builder] = {}

    def add(self, platform: str, *args: Any, **kwargs: Any) -> Builder:
        if "builder" in kwargs:
            build_candidate = kwargs.pop("builder")
            if args or kwargs:
                raise RuntimeError(
                    "builder keyword can not be used with other kwargs or args"
                )
            build = cast(Builder, build_candidate)
        else:
            build = Builder(*args, **kwargs)
        self.builds[platform] = build
        return build


builds = Builds()


def patch_shebang(path: PathLike, old: str, new: str) -> bool:
    """
    Replace a file's shebang.

    :param path: The path of the file to patch
    :type path: str
    :param old: The old shebang, will only patch when this is found
    :type old: str
    :param name: The new shebang to be written
    :type name: str
    """
    with open(path, "rb") as fp:
        try:
            data = fp.read(len(old.encode())).decode()
        except UnicodeError:
            return False
        except Exception as exc:
            log.warning("Unhandled exception: %r", exc)
            return False
        if data != old:
            log.warning("Shebang doesn't match: %s %r != %r", path, old, data)
            return False
        data = fp.read().decode()
    with open(path, "w") as fp:
        fp.write(new)
        fp.write(data)
    with open(path, "r") as fp:
        data = fp.read()
    log.info("Patched shebang of %s => %r", path, data)
    return True


def patch_shebangs(path: PathLike, old: str, new: str) -> None:
    """
    Traverse directory and patch shebangs.

    :param path: The of the directory to traverse
    :type path: str
    :param old: The old shebang, will only patch when this is found
    :type old: str
    :param name: The new shebang to be written
    :type name: str
    """
    for root, _dirs, files in os.walk(str(path)):
        for file in files:
            patch_shebang(os.path.join(root, file), old, new)


def install_sysdata(
    mod: ModuleType,
    destfile: PathLike,
    buildroot: PathLike,
    toolchain: Optional[PathLike],
) -> None:
    """
    Create a Relenv Python environment's sysconfigdata.

    Helper method used by the `finalize` build method to create a Relenv
    Python environment's sysconfigdata.

    :param mod: The module to operate on
    :type mod: ``types.ModuleType``
    :param destfile: Path to the file to write the data to
    :type destfile: str
    :param buildroot: Path to the root of the build
    :type buildroot: str
    :param toolchain: Path to the root of the toolchain
    :type toolchain: str
    """
    data = {}

    def fbuildroot(s: str) -> str:
        return s.replace(str(buildroot), "{BUILDROOT}")

    def ftoolchain(s: str) -> str:
        return s.replace(str(toolchain), "{TOOLCHAIN}")

    # XXX: keymap is not used, remove it?
    # keymap = {
    #    "BINDIR": (fbuildroot,),
    #    "BINLIBDEST": (fbuildroot,),
    #    "CFLAGS": (fbuildroot, ftoolchain),
    #    "CPPLAGS": (fbuildroot, ftoolchain),
    #    "CXXFLAGS": (fbuildroot, ftoolchain),
    #    "datarootdir": (fbuildroot,),
    #    "exec_prefix": (fbuildroot,),
    #    "LDFLAGS": (fbuildroot, ftoolchain),
    #    "LDSHARED": (fbuildroot, ftoolchain),
    #    "LIBDEST": (fbuildroot,),
    #    "prefix": (fbuildroot,),
    #    "SCRIPTDIR": (fbuildroot,),
    # }
    for key in sorted(mod.build_time_vars):
        val = mod.build_time_vars[key]
        if isinstance(val, str):
            for _ in (fbuildroot, ftoolchain):
                val = _(val)
                log.info("SYSCONFIG [%s] %s => %s", key, mod.build_time_vars[key], val)
        data[key] = val

    with open(destfile, "w", encoding="utf8") as f:
        f.write(
            "# system configuration generated and used by" " the relenv at runtime\n"
        )
        f.write("_build_time_vars = ")
        pprint.pprint(data, stream=f)
        f.write(SYSCONFIGDATA)


def find_sysconfigdata(pymodules: PathLike) -> str:
    """
    Find sysconfigdata directory for python installation.

    :param pymodules: Path to python modules (e.g. lib/python3.10)
    :type pymodules: str

    :return: The name of the sysconig data module
    :rtype: str
    """
    for root, dirs, files in os.walk(pymodules):
        for file in files:
            if file.find("sysconfigdata") > -1 and file.endswith(".py"):
                return file[:-3]
    raise RelenvException("Unable to locate sysconfigdata module")


def install_runtime(sitepackages: PathLike) -> None:
    """
    Install a base relenv runtime.
    """
    site_dir = pathlib.Path(sitepackages)
    relenv_pth = site_dir / "relenv.pth"
    with io.open(str(relenv_pth), "w") as fp:
        fp.write(RELENV_PTH)

    # Lay down relenv.runtime, we'll pip install the rest later
    relenv = site_dir / "relenv"
    os.makedirs(relenv, exist_ok=True)

    for name in [
        "runtime.py",
        "relocate.py",
        "common.py",
        "buildenv.py",
        "__init__.py",
    ]:
        src = MODULE_DIR / name
        dest = relenv / name
        with io.open(src, "r") as rfp:
            with io.open(dest, "w") as wfp:
                wfp.write(rfp.read())


def finalize(
    env: MutableMapping[str, str],
    dirs: Dirs,
    logfp: IO[str],
) -> None:
    """
    Run after we've fully built python.

    This method enhances the newly created python with Relenv's runtime hacks.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    # Run relok8 to make sure the rpaths are relocatable.
    relenv.relocate.main(dirs.prefix, log_file_name=str(dirs.logs / "relocate.py.log"))
    # Install relenv-sysconfigdata module
    libdir = pathlib.Path(dirs.prefix) / "lib"

    def find_pythonlib(libdir: pathlib.Path) -> Optional[str]:
        for _root, dirs, _files in os.walk(libdir):
            for entry in dirs:
                if entry.startswith("python"):
                    return entry
        return None

    python_lib = find_pythonlib(libdir)
    if python_lib is None:
        raise RelenvException("Unable to locate python library directory")

    pymodules = libdir / python_lib

    # update ensurepip
    update_ensurepip(pymodules)

    cwd = os.getcwd()
    modname = find_sysconfigdata(pymodules)
    path = sys.path
    sys.path = [str(pymodules)]
    try:
        mod = __import__(str(modname))
    finally:
        os.chdir(cwd)
        sys.path = path

    dest = pymodules / f"{modname}.py"
    install_sysdata(mod, dest, dirs.prefix, dirs.toolchain)

    # Lay down site customize
    bindir = pathlib.Path(dirs.prefix) / "bin"
    sitepackages = pymodules / "site-packages"
    install_runtime(sitepackages)

    # Install pip
    python_exe = str(dirs.prefix / "bin" / "python3")
    if env["RELENV_HOST_ARCH"] != env["RELENV_BUILD_ARCH"]:
        env["RELENV_CROSS"] = str(dirs.prefix)
        python_exe = env["RELENV_NATIVE_PY"]
    logfp.write("\nRUN ENSURE PIP\n")

    env.pop("RELENV_BUILDENV")

    runcmd(
        [python_exe, "-m", "ensurepip"],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )

    # Fix the shebangs in the scripts python layed down. Order matters.
    shebangs = [
        "#!{}".format(bindir / f"python{env['RELENV_PY_MAJOR_VERSION']}"),
        "#!{}".format(
            bindir / f"python{env['RELENV_PY_MAJOR_VERSION'].split('.', 1)[0]}"
        ),
    ]
    newshebang = format_shebang("/python3")
    for shebang in shebangs:
        log.info("Patch shebang %r with  %r", shebang, newshebang)
        patch_shebangs(
            str(pathlib.Path(dirs.prefix) / "bin"),
            shebang,
            newshebang,
        )

    if sys.platform == "linux":
        pyconf = f"config-{env['RELENV_PY_MAJOR_VERSION']}-{env['RELENV_HOST']}"
        patch_shebang(
            str(pymodules / pyconf / "python-config.py"),
            "#!{}".format(str(bindir / f"python{env['RELENV_PY_MAJOR_VERSION']}")),
            format_shebang("../../../bin/python3"),
        )

        toolchain_path = dirs.toolchain
        if toolchain_path is None:
            raise RelenvException("Toolchain path is required for linux builds")
        shutil.copy(
            pathlib.Path(toolchain_path)
            / env["RELENV_HOST"]
            / "sysroot"
            / "lib"
            / "libstdc++.so.6",
            libdir,
        )

    # Moved in python 3.13 or removed?
    if (pymodules / "cgi.py").exists():
        patch_shebang(
            str(pymodules / "cgi.py"),
            "#! /usr/local/bin/python",
            format_shebang("../../bin/python3"),
        )

    def runpip(pkg: Union[str, os.PathLike[str]], upgrade: bool = False) -> None:
        logfp.write(f"\nRUN PIP {pkg} {upgrade}\n")
        target: Optional[pathlib.Path] = None
        python_exe = str(dirs.prefix / "bin" / "python3")
        if sys.platform == LINUX:
            if env["RELENV_HOST_ARCH"] != env["RELENV_BUILD_ARCH"]:
                target = pymodules / "site-packages"
                python_exe = env["RELENV_NATIVE_PY"]
        cmd = [
            python_exe,
            "-m",
            "pip",
            "install",
            str(pkg),
        ]
        if upgrade:
            cmd.append("--upgrade")
        if target:
            cmd.append("--target={}".format(target))
        runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    runpip("wheel")
    # This needs to handle running from the root of the git repo and also from
    # an installed Relenv
    if (MODULE_DIR.parent / ".git").exists():
        runpip(MODULE_DIR.parent, upgrade=True)
    else:
        runpip("relenv", upgrade=True)
    globs = [
        "/bin/python*",
        "/bin/pip*",
        "/bin/relenv",
        "/lib/python*/ensurepip/*",
        "/lib/python*/site-packages/*",
        "/include/*",
        "*.so",
        "/lib/*.so.*",
        "*.py",
        # Mac specific, factor this out
        "*.dylib",
    ]
    archive = f"{ dirs.prefix }.tar.xz"
    log.info("Archive is %s", archive)
    with tarfile.open(archive, mode="w:xz") as fp:
        create_archive(fp, dirs.prefix, globs, logfp)


def create_archive(
    tarfp: tarfile.TarFile,
    toarchive: PathLike,
    globs: Sequence[str],
    logfp: Optional[IO[str]] = None,
) -> None:
    """
    Create an archive.

    :param tarfp: A pointer to the archive to be created
    :type tarfp: file
    :param toarchive: The path to the directory to archive
    :type toarchive: str
    :param globs: A list of filtering patterns to match against files to be added
    :type globs: list
    :param logfp: A pointer to the log file
    :type logfp: file
    """
    log.debug("Current directory %s", os.getcwd())
    log.debug("Creating archive %s", tarfp.name)
    for root, _dirs, files in os.walk(toarchive):
        relroot = pathlib.Path(root).relative_to(toarchive)
        for f in files:
            relpath = relroot / f
            matches = False
            for g in globs:
                candidate = pathlib.Path("/") / relpath
                if fnmatch.fnmatch(str(candidate), g):
                    matches = True
                    break
            if matches:
                log.debug("Adding %s", relpath)
                tarfp.add(relpath, arcname=str(relpath), recursive=False)
            else:
                log.debug("Skipping %s", relpath)
