# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Versions utility.
"""
# try:
#    from packaging.version import Version
# except ImportError:
#    raise RuntimeError(
#        "Required dependencies not found. Please pip install relenv[pyversions]"
#    )
#

import hashlib
import json
import logging
import os
import pathlib
import re
import subprocess
import sys
import time

from relenv.common import check_url, download_url, fetch_url_content

log = logging.getLogger(__name__)

KEYSERVERS = [
    "keyserver.ubuntu.com",
    "keys.openpgp.org",
    "pgp.mit.edu",
]

ARCHIVE = "https://www.python.org/ftp/python/{version}/Python-{version}.{ext}"


def _ref_version(x):
    _ = x.split("Python ", 1)[1].split("<", 1)[0]
    return Version(_)


def _ref_path(x):
    return x.split('href="')[1].split('"')[0]


class Version:
    """
    Version comparrisons.
    """

    def __init__(self, data):
        self.major, self.minor, self.micro = self.parse_string(data)
        self._data = data

    def __str__(self):
        """
        Version as string.
        """
        _ = f"{self.major}"
        if self.minor is not None:
            _ += f".{self.minor}"
            if self.micro is not None:
                _ += f".{self.micro}"
        # XXX What if minor was None but micro was an int.
        return _

    @staticmethod
    def parse_string(data):
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

    def __eq__(self, other):
        """
        Equality comparrison.
        """
        mymajor = 0 if self.major is None else self.major
        myminor = 0 if self.minor is None else self.minor
        mymicro = 0 if self.micro is None else self.micro
        major = 0 if other.major is None else other.major
        minor = 0 if other.minor is None else other.minor
        micro = 0 if other.micro is None else other.micro
        return mymajor == major and myminor == minor and mymicro == micro

    def __lt__(self, other):
        """
        Less than comparrison.
        """
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

    def __le__(self, other):
        """
        Less than or equal to comparrison.
        """
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

    def __gt__(self, other):
        """
        Greater than comparrison.
        """
        return not self.__le__(other)

    def __ge__(self, other):
        """
        Greater than or equal to comparrison.
        """
        return not self.__lt__(other)


def _release_urls(version, gzip=False):
    if gzip:
        tarball = f"https://www.python.org/ftp/python/{version}/Python-{version}.tgz"
    else:
        tarball = f"https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz"
    # No signatures prior to 2.3
    if version < Version("2.3"):
        return tarball, None
    return tarball, f"{tarball}.asc"


def _receive_key(keyid, server):
    proc = subprocess.run(
        ["gpg", "--keyserver", server, "--recv-keys", keyid], capture_output=True
    )
    if proc.returncode == 0:
        return True
    return False


def _get_keyid(proc):
    try:
        err = proc.stderr.decode()
        return err.splitlines()[1].rsplit(" ", 1)[-1]
    except (AttributeError, IndexError):
        return False


def verify_signature(path, signature):
    """
    Verify gpg signature.
    """
    proc = subprocess.run(["gpg", "--verify", signature, path], capture_output=True)
    keyid = _get_keyid(proc)
    if proc.returncode == 0:
        print(f"Valid signature {path} {keyid}")
        return True
    err = proc.stderr.decode()
    if "No public key" in err:
        for server in KEYSERVERS:
            if _receive_key(keyid, server):
                print(f"found public key {keyid} on {server}")
                break
        else:
            print(f"Unable to find key {keyid}  on any server")
    else:
        print(f"Signature verification failed {proc.stderr.decode()}")
        return False
    proc = subprocess.run(["gpg", "--verify", signature, path], capture_output=True)
    if proc.returncode == 0:
        print(f"Valid signature {path} {signature}")
        return True
    err = proc.stderr.decode()
    print(f"Signature verification failed {proc.stderr.decode()}")
    return False


PRINT = True
CHECK = True
VERSION = None  # '3.13.2'
UPDATE = False


def digest(file):
    """
    SHA-256 digest of file.
    """
    hsh = hashlib.sha256()
    with open(file, "rb") as fp:
        hsh.update(fp.read())
    return hsh.hexdigest()


def _main():

    pyversions = {"versions": []}

    vfile = pathlib.Path(".pyversions")
    cfile = pathlib.Path(".content")
    tsfile = pathlib.Path(".ts")
    url = "https://www.python.org/downloads/"
    if not cfile.exists() or not tsfile.exists():
        print("Get downloads page")
        ts = int(time.time())
        content = fetch_url_content(url)
        cfile.write_text(content)
        tsfile.write_text(str(ts))
    elif CHECK:
        ts = int(tsfile.read_text())
        if check_url(url, timestamp=ts):
            print("Get downloads page")
            ts = int(time.time())
            content = fetch_url_content(url)
            cfile.write_text(content)
            tsfile.write_text(str(ts))
        else:
            pyversions = json.loads(vfile.read_text())
            content = cfile.read_text()
    else:
        pyversions = json.loads(vfile.read_text())
        content = cfile.read_text()

    matched = re.findall(r'<a href="/downloads/.*">Python.*</a>', content)

    parsed_versions = sorted([_ref_version(_) for _ in matched], reverse=True)

    versions = [_ for _ in parsed_versions if _.major >= 3]
    cwd = os.getcwd()

    out = {}

    for version in versions:
        if VERSION and Version(VERSION) != version:
            continue

        if PRINT:
            pyversions["versions"].append(str(version))
            print(version)
            continue

        print(f"Check version {version}")

        # Prior to 3.2.0 the url format only included major and minor.
        if version <= Version("3.2") and version.micro == 0:
            url_version = Version(f"{version.major}.{version.minor}")
        else:
            url_version = version

        # No xz archives prior to 3.1.4
        if version >= Version("3.1.4"):
            url = ARCHIVE.format(version=url_version, ext="tar.xz")
            if CHECK:
                check_url(url)
                check_url(f"{url}.asc")
            else:
                path = download_url(url, cwd)
                sig_path = download_url(f"{url}.asc", cwd)
                verified = verify_signature(path, sig_path)
                if verified:
                    if str(version) in out:
                        out[str(version)][url] = digest(path)
                    else:
                        out[str(version)] = {url: digest(path)}

        url = ARCHIVE.format(version=url_version, ext="tgz")
        if CHECK:
            check_url(url)
            # No signatures prior to 2.3
            if version >= Version("2.3"):
                check_url(f"{url}.asc")
        else:
            path = download_url(url, cwd)
            if version >= Version("2.3"):
                sig_path = download_url(f"{url}.asc", cwd)
                verified = verify_signature(path, sig_path)
                if verified:
                    if str(version) in out:
                        out[str(version)][url] = digest(path)
                    else:
                        out[str(version)] = {url: digest(path)}

    if PRINT:
        vfile.write_text(json.dumps(pyversions))
    elif not CHECK and out:
        vfile.write_text(json.dumps(out))


def create_pyversions(path):
    """
    Create python-versions.json file.
    """
    url = "https://www.python.org/downloads/"
    content = fetch_url_content(url)
    matched = re.findall(r'<a href="/downloads/.*">Python.*</a>', content)
    parsed_versions = sorted([_ref_version(_) for _ in matched], reverse=True)
    versions = [_ for _ in parsed_versions if _.major >= 3]
    path.write_text(json.dumps({"versions": [str(_) for _ in versions]}))


def python_versions(minor=None, create=False, update=False):
    """
    List python versions.
    """
    packaged = pathlib.Path(__file__).parent / "python-versions.json"
    local = pathlib.Path("~/.local/relenv/python-versions.json")

    if create:
        create_pyversions(packaged)

    if local.exists():
        readfrom = local
    elif packaged.exists():
        readfrom = packaged
    elif create:
        readfrom = packaged
    else:
        raise RuntimeError("No versions file found")
    pyversions = json.loads(readfrom.read_text())
    versions = [Version(_) for _ in pyversions["versions"]]
    if minor:
        mv = Version(minor)
        versions = [_ for _ in versions if _.major == mv.major and _.minor == mv.minor]
    return versions


def setup_parser(subparsers):
    """
    Setup the subparser for the ``versions`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser(
        "versions",
        description=("Versions utility"),
    )
    subparser.set_defaults(func=main)
    subparser.add_argument(
        "-u",
        "--update",
        default=False,
        action="store_true",
        help="Update versions",
    )
    subparser.add_argument(
        "-l",
        "--list",
        default=False,
        action="store_true",
        help="List versions",
    )
    subparser.add_argument(
        "--version",
        default="3.13",
        type=str,
        help="The python version [default: %(default)s]",
    )


def main(args):
    """
    Versions utility main method.
    """
    if args.update:
        python_versions(create=True)
    if args.list:
        for version in python_versions():
            print(version)
        sys.exit()
    if args.version:
        requested = Version(args.version)

        if requested.micro:
            pyversions = python_versions()
            if requested not in pyversions:
                print(f"Unknown version {requested}")
                sys.exit(1)
            build_version = requested
        else:
            pyversions = python_versions(args.version)
            if not pyversions:
                print(f"Unknown minor version {requested}")
                sys.exit(1)
            build_version = pyversions[0]
        print(build_version)
        sys.exit()


if __name__ == "__main__":
    print("WTF")
    _main()
