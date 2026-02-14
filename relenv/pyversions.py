# Copyright 2022-2026 Broadcom.
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

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os as _os
import pathlib
import re
import subprocess as _subprocess
import sys as _sys
import time
from typing import Any

from relenv.common import Version, check_url, download_url, fetch_url_content

log = logging.getLogger(__name__)

os = _os
subprocess = _subprocess
sys = _sys

__all__ = [
    "Version",
    "os",
    "subprocess",
    "sys",
]

KEYSERVERS = [
    "keyserver.ubuntu.com",
    "keys.openpgp.org",
    "pgp.mit.edu",
]

ARCHIVE = "https://www.python.org/ftp/python/{version}/Python-{version}.{ext}"


def _ref_version(x: str) -> Version:
    _ = x.split("Python ", 1)[1].split("<", 1)[0]
    return Version(_)


def _ref_path(x: str) -> str:
    return x.split('href="')[1].split('"')[0]


def _release_urls(version: Version, gzip: bool = False) -> tuple[str, str | None]:
    if gzip:
        tarball = f"https://www.python.org/ftp/python/{version}/Python-{version}.tgz"
    else:
        tarball = f"https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz"
    # No signatures prior to 2.3
    if version < Version("2.3"):
        return tarball, None
    return tarball, f"{tarball}.asc"


def _receive_key(keyid: str, server: str) -> bool:
    proc = subprocess.run(
        ["gpg", "--keyserver", server, "--recv-keys", keyid], capture_output=True
    )
    if proc.returncode == 0:
        return True
    return False


def _get_keyid(proc: subprocess.CompletedProcess[bytes]) -> str | None:
    try:
        err = proc.stderr.decode()
        return err.splitlines()[1].rsplit(" ", 1)[-1]
    except (AttributeError, IndexError):
        return None


def verify_signature(
    path: str | os.PathLike[str],
    signature: str | os.PathLike[str],
) -> bool:
    """
    Verify gpg signature.
    """
    proc = subprocess.run(["gpg", "--verify", signature, path], capture_output=True)
    keyid = _get_keyid(proc)
    if proc.returncode == 0:
        print(f"Valid signature {path} {keyid or ''}")
        return True
    err = proc.stderr.decode()
    if keyid and "No public key" in err:
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


def digest(file: str | os.PathLike[str]) -> str:
    """
    SHA-256 digest of file.
    """
    hsh = hashlib.sha1()
    with open(file, "rb") as fp:
        hsh.update(fp.read())
    return hsh.hexdigest()


def _main() -> None:

    pyversions: dict[str, Any] = {"versions": []}

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
        pyversions = {"versions": []}
        vfile.write_text(json.dumps(pyversions, indent=1))
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

    out: dict[str, dict[str, str]] = {}

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
        vfile.write_text(json.dumps(pyversions, indent=1))
    elif not CHECK and out:
        vfile.write_text(json.dumps(out, indent=1))


def sha256_digest(file: str | os.PathLike[str]) -> str:
    """
    SHA-256 digest of file.
    """
    hsh = hashlib.sha256()
    with open(file, "rb") as fp:
        hsh.update(fp.read())
    return hsh.hexdigest()


def detect_openssl_versions() -> list[str]:
    """
    Detect available OpenSSL versions from GitHub releases.
    """
    url = "https://github.com/openssl/openssl/tags"
    content = fetch_url_content(url)
    # Find tags like openssl-3.5.4
    pattern = r'openssl-(\d+\.\d+\.\d+)"'
    matches = re.findall(pattern, content)
    # Deduplicate and sort
    versions = sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )
    return versions


def detect_sqlite_versions() -> list[tuple[str, str]]:
    """
    Detect available SQLite versions from sqlite.org.

    Returns list of (version, sqliteversion) tuples.
    """
    url = "https://sqlite.org/download.html"
    content = fetch_url_content(url)
    # Find sqlite-autoconf-NNNNNNN.tar.gz
    pattern = r"sqlite-autoconf-(\d{7})\.tar\.gz"
    matches = re.findall(pattern, content)
    # Convert to version format
    versions = []
    for sqlite_ver in set(matches):
        # SQLite version format: 3XXYYZZ where XX=minor, YY=patch, ZZ=subpatch
        if len(sqlite_ver) == 7 and sqlite_ver[0] == "3":
            major = 3
            minor = int(sqlite_ver[1:3])
            patch = int(sqlite_ver[3:5])
            subpatch = int(sqlite_ver[5:7])
            version = f"{major}.{minor}.{patch}.{subpatch}"
            versions.append((version, sqlite_ver))
    return sorted(
        versions, key=lambda x: [int(n) for n in x[0].split(".")], reverse=True
    )


def detect_xz_versions() -> list[str]:
    """
    Detect available XZ versions from tukaani.org.
    """
    url = "https://tukaani.org/xz/"
    content = fetch_url_content(url)
    # Find xz-X.Y.Z.tar.gz
    pattern = r"xz-(\d+\.\d+\.\d+)\.tar\.gz"
    matches = re.findall(pattern, content)
    # Deduplicate and sort
    versions = sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )
    return versions


def detect_libffi_versions() -> list[str]:
    """Detect available libffi versions from GitHub releases."""
    url = "https://github.com/libffi/libffi/tags"
    content = fetch_url_content(url)
    pattern = r'v(\d+\.\d+\.\d+)"'
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_zlib_versions() -> list[str]:
    """Detect available zlib versions from zlib.net."""
    url = "https://zlib.net/"
    content = fetch_url_content(url)
    pattern = r"zlib-(\d+\.\d+\.\d+)\.tar\.gz"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_bzip2_versions() -> list[str]:
    """Detect available bzip2 versions from sourceware.org."""
    url = "https://sourceware.org/pub/bzip2/"
    content = fetch_url_content(url)
    pattern = r"bzip2-(\d+\.\d+\.\d+)\.tar\.gz"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_ncurses_versions() -> list[str]:
    """Detect available ncurses versions from GNU mirrors."""
    url = "https://mirrors.ocf.berkeley.edu/gnu/ncurses/"
    content = fetch_url_content(url)
    pattern = r"ncurses-(\d+\.\d+)\.tar\.gz"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_readline_versions() -> list[str]:
    """Detect available readline versions from GNU mirrors."""
    url = "https://mirrors.ocf.berkeley.edu/gnu/readline/"
    content = fetch_url_content(url)
    pattern = r"readline-(\d+\.\d+)\.tar\.gz"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_gdbm_versions() -> list[str]:
    """Detect available gdbm versions from GNU mirrors."""
    url = "https://mirrors.ocf.berkeley.edu/gnu/gdbm/"
    content = fetch_url_content(url)
    pattern = r"gdbm-(\d+\.\d+)\.tar\.gz"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_libxcrypt_versions() -> list[str]:
    """Detect available libxcrypt versions from GitHub releases."""
    url = "https://github.com/besser82/libxcrypt/tags"
    content = fetch_url_content(url)
    pattern = r'v(\d+\.\d+\.\d+)"'
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_krb5_versions() -> list[str]:
    """Detect available krb5 versions from kerberos.org."""
    url = "https://kerberos.org/dist/krb5/"
    content = fetch_url_content(url)
    # krb5 versions are like 1.22/
    pattern = r"(\d+\.\d+)/"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_uuid_versions() -> list[str]:
    """Detect available libuuid versions from SourceForge."""
    url = "https://sourceforge.net/projects/libuuid/files/"
    content = fetch_url_content(url)
    pattern = r"libuuid-(\d+\.\d+\.\d+)\.tar\.gz"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_tirpc_versions() -> list[str]:
    """Detect available libtirpc versions from SourceForge."""
    url = "https://sourceforge.net/projects/libtirpc/files/libtirpc/"
    content = fetch_url_content(url)
    pattern = r"(\d+\.\d+\.\d+)/"
    matches = re.findall(pattern, content)
    return sorted(
        set(matches), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def detect_expat_versions() -> list[str]:
    """Detect available expat versions from GitHub releases."""
    url = "https://github.com/libexpat/libexpat/tags"
    content = fetch_url_content(url)
    # Expat versions are tagged like R_2_7_3
    pattern = r'R_(\d+)_(\d+)_(\d+)"'
    matches = re.findall(pattern, content)
    # Convert R_2_7_3 to 2.7.3
    versions = [f"{m[0]}.{m[1]}.{m[2]}" for m in matches]
    return sorted(
        set(versions), key=lambda v: [int(x) for x in v.split(".")], reverse=True
    )


def update_dependency_versions(
    path: pathlib.Path, deps_to_update: list[str] | None = None
) -> None:
    """
    Update dependency versions in python-versions.json.

    Downloads tarballs, computes SHA-256, and updates the JSON file.

    :param path: Path to python-versions.json
    :param deps_to_update: List of dependencies to update (openssl, sqlite, xz), or None for all
    """
    cwd = os.getcwd()

    # Read existing data
    if path.exists():
        all_data = json.loads(path.read_text())
        if "python" in all_data:
            pydata = all_data["python"]
            dependencies = all_data.get("dependencies", {})
        else:
            # Old format
            pydata = all_data
            dependencies = {}
    else:
        pydata = {}
        dependencies = {}

    # Determine which dependencies to update
    if deps_to_update is None:
        # By default, update commonly-changed dependencies
        # Full list: openssl, sqlite, xz, libffi, zlib, bzip2, ncurses,
        # readline, gdbm, libxcrypt, krb5, uuid, tirpc, expat
        deps_to_update = [
            "openssl",
            "sqlite",
            "xz",
            "libffi",
            "zlib",
            "ncurses",
            "readline",
            "gdbm",
            "libxcrypt",
            "krb5",
            "bzip2",
            "uuid",
            "tirpc",
            "expat",
        ]

    # Update OpenSSL
    if "openssl" in deps_to_update:
        print("Checking OpenSSL versions...")
        openssl_versions = detect_openssl_versions()
        if openssl_versions:
            latest = openssl_versions[0]
            print(f"Latest OpenSSL: {latest}")
            if "openssl" not in dependencies:
                dependencies["openssl"] = {}
            if latest not in dependencies["openssl"]:
                url = f"https://github.com/openssl/openssl/releases/download/openssl-{latest}/openssl-{latest}.tar.gz"
                print(f"Downloading {url}...")
                download_path = download_url(url, cwd)
                checksum = sha256_digest(download_path)
                print(f"SHA-256: {checksum}")
                url_template = (
                    "https://github.com/openssl/openssl/releases/download/"
                    "openssl-{version}/openssl-{version}.tar.gz"
                )
                dependencies["openssl"][latest] = {
                    "url": url_template,
                    "sha256": checksum,
                    "platforms": ["linux", "darwin"],
                }
                # Clean up download
                os.remove(download_path)

    # Update SQLite
    if "sqlite" in deps_to_update:
        print("Checking SQLite versions...")
        sqlite_versions = detect_sqlite_versions()
        if sqlite_versions:
            latest_version, latest_sqliteversion = sqlite_versions[0]
            print(
                f"Latest SQLite: {latest_version} (sqlite version {latest_sqliteversion})"
            )
            if "sqlite" not in dependencies:
                dependencies["sqlite"] = {}
            if latest_version not in dependencies["sqlite"]:
                # SQLite URLs include year, try current year
                import datetime

                year = datetime.datetime.now().year
                url = f"https://sqlite.org/{year}/sqlite-autoconf-{latest_sqliteversion}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    # Store URL with actual year and {version} placeholder (not {sqliteversion})
                    # The build scripts pass sqliteversion value as "version" parameter
                    dependencies["sqlite"][latest_version] = {
                        "url": f"https://sqlite.org/{year}/sqlite-autoconf-{{version}}.tar.gz",
                        "sha256": checksum,
                        "sqliteversion": latest_sqliteversion,
                        "platforms": ["linux", "darwin", "win32"],
                    }
                    # Clean up download
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download SQLite: {e}")

    # Update XZ
    if "xz" in deps_to_update:
        print("Checking XZ versions...")
        xz_versions = detect_xz_versions()
        if xz_versions:
            latest = xz_versions[0]
            print(f"Latest XZ: {latest}")
            if "xz" not in dependencies:
                dependencies["xz"] = {}
            if latest not in dependencies["xz"]:
                url = f"http://tukaani.org/xz/xz-{latest}.tar.gz"
                print(f"Downloading {url}...")
                download_path = download_url(url, cwd)
                checksum = sha256_digest(download_path)
                print(f"SHA-256: {checksum}")
                dependencies["xz"][latest] = {
                    "url": "http://tukaani.org/xz/xz-{version}.tar.gz",
                    "sha256": checksum,
                    "platforms": ["linux", "darwin", "win32"],
                }
                # Clean up download
                os.remove(download_path)

    # Update libffi
    if "libffi" in deps_to_update:
        print("Checking libffi versions...")
        libffi_versions = detect_libffi_versions()
        if libffi_versions:
            latest = libffi_versions[0]
            print(f"Latest libffi: {latest}")
            if "libffi" not in dependencies:
                dependencies["libffi"] = {}
            if latest not in dependencies["libffi"]:
                url = f"https://github.com/libffi/libffi/releases/download/v{latest}/libffi-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["libffi"][latest] = {
                        "url": "https://github.com/libffi/libffi/releases/download/v{version}/libffi-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download libffi: {e}")

    # Update zlib
    if "zlib" in deps_to_update:
        print("Checking zlib versions...")
        zlib_versions = detect_zlib_versions()
        if zlib_versions:
            latest = zlib_versions[0]
            print(f"Latest zlib: {latest}")
            if "zlib" not in dependencies:
                dependencies["zlib"] = {}
            if latest not in dependencies["zlib"]:
                url = f"https://zlib.net/fossils/zlib-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["zlib"][latest] = {
                        "url": "https://zlib.net/fossils/zlib-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux", "win32"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download zlib: {e}")

    # Update ncurses
    if "ncurses" in deps_to_update:
        print("Checking ncurses versions...")
        ncurses_versions = detect_ncurses_versions()
        if ncurses_versions:
            latest = ncurses_versions[0]
            print(f"Latest ncurses: {latest}")
            if "ncurses" not in dependencies:
                dependencies["ncurses"] = {}
            if latest not in dependencies["ncurses"]:
                url = f"https://mirrors.ocf.berkeley.edu/gnu/ncurses/ncurses-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["ncurses"][latest] = {
                        "url": "https://mirrors.ocf.berkeley.edu/gnu/ncurses/ncurses-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download ncurses: {e}")

    # Update readline
    if "readline" in deps_to_update:
        print("Checking readline versions...")
        readline_versions = detect_readline_versions()
        if readline_versions:
            latest = readline_versions[0]
            print(f"Latest readline: {latest}")
            if "readline" not in dependencies:
                dependencies["readline"] = {}
            if latest not in dependencies["readline"]:
                url = f"https://mirrors.ocf.berkeley.edu/gnu/readline/readline-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["readline"][latest] = {
                        "url": "https://mirrors.ocf.berkeley.edu/gnu/readline/readline-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download readline: {e}")

    # Update gdbm
    if "gdbm" in deps_to_update:
        print("Checking gdbm versions...")
        gdbm_versions = detect_gdbm_versions()
        if gdbm_versions:
            latest = gdbm_versions[0]
            print(f"Latest gdbm: {latest}")
            if "gdbm" not in dependencies:
                dependencies["gdbm"] = {}
            if latest not in dependencies["gdbm"]:
                url = f"https://mirrors.ocf.berkeley.edu/gnu/gdbm/gdbm-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["gdbm"][latest] = {
                        "url": "https://mirrors.ocf.berkeley.edu/gnu/gdbm/gdbm-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download gdbm: {e}")

    # Update libxcrypt
    if "libxcrypt" in deps_to_update:
        print("Checking libxcrypt versions...")
        libxcrypt_versions = detect_libxcrypt_versions()
        if libxcrypt_versions:
            latest = libxcrypt_versions[0]
            print(f"Latest libxcrypt: {latest}")
            if "libxcrypt" not in dependencies:
                dependencies["libxcrypt"] = {}
            if latest not in dependencies["libxcrypt"]:
                url = f"https://github.com/besser82/libxcrypt/releases/download/v{latest}/libxcrypt-{latest}.tar.xz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["libxcrypt"][latest] = {
                        "url": (
                            "https://github.com/besser82/libxcrypt/releases/"
                            "download/v{version}/libxcrypt-{version}.tar.xz"
                        ),
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download libxcrypt: {e}")

    # Update krb5
    if "krb5" in deps_to_update:
        print("Checking krb5 versions...")
        krb5_versions = detect_krb5_versions()
        if krb5_versions:
            latest = krb5_versions[0]
            print(f"Latest krb5: {latest}")
            if "krb5" not in dependencies:
                dependencies["krb5"] = {}
            if latest not in dependencies["krb5"]:
                url = f"https://kerberos.org/dist/krb5/{latest}/krb5-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["krb5"][latest] = {
                        "url": "https://kerberos.org/dist/krb5/{version}/krb5-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download krb5: {e}")

    # Update bzip2
    if "bzip2" in deps_to_update:
        print("Checking bzip2 versions...")
        bzip2_versions = detect_bzip2_versions()
        if bzip2_versions:
            latest = bzip2_versions[0]
            print(f"Latest bzip2: {latest}")
            if "bzip2" not in dependencies:
                dependencies["bzip2"] = {}
            if latest not in dependencies["bzip2"]:
                url = f"https://sourceware.org/pub/bzip2/bzip2-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["bzip2"][latest] = {
                        "url": "https://sourceware.org/pub/bzip2/bzip2-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux", "darwin", "win32"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download bzip2: {e}")

    # Update uuid
    if "uuid" in deps_to_update:
        print("Checking uuid versions...")
        uuid_versions = detect_uuid_versions()
        if uuid_versions:
            latest = uuid_versions[0]
            print(f"Latest uuid: {latest}")
            if "uuid" not in dependencies:
                dependencies["uuid"] = {}
            if latest not in dependencies["uuid"]:
                url = f"https://sourceforge.net/projects/libuuid/files/libuuid-{latest}.tar.gz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["uuid"][latest] = {
                        "url": "https://sourceforge.net/projects/libuuid/files/libuuid-{version}.tar.gz",
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download uuid: {e}")

    # Update tirpc
    if "tirpc" in deps_to_update:
        print("Checking tirpc versions...")
        tirpc_versions = detect_tirpc_versions()
        if tirpc_versions:
            latest = tirpc_versions[0]
            print(f"Latest tirpc: {latest}")
            if "tirpc" not in dependencies:
                dependencies["tirpc"] = {}
            if latest not in dependencies["tirpc"]:
                url = f"https://sourceforge.net/projects/libtirpc/files/libtirpc-{latest}.tar.bz2"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    dependencies["tirpc"][latest] = {
                        "url": "https://sourceforge.net/projects/libtirpc/files/libtirpc-{version}.tar.bz2",
                        "sha256": checksum,
                        "platforms": ["linux"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download tirpc: {e}")

    # Update expat
    if "expat" in deps_to_update:
        print("Checking expat versions...")
        expat_versions = detect_expat_versions()
        if expat_versions:
            latest = expat_versions[0]
            print(f"Latest expat: {latest}")
            if "expat" not in dependencies:
                dependencies["expat"] = {}
            if latest not in dependencies["expat"]:
                # Expat uses R_X_Y_Z format for releases
                version_tag = latest.replace(".", "_")
                url = f"https://github.com/libexpat/libexpat/releases/download/R_{version_tag}/expat-{latest}.tar.xz"
                print(f"Downloading {url}...")
                try:
                    download_path = download_url(url, cwd)
                    checksum = sha256_digest(download_path)
                    print(f"SHA-256: {checksum}")
                    # Store URL template with placeholder for version
                    # Build scripts will construct actual URL dynamically from version
                    dependencies["expat"][latest] = {
                        "url": (
                            f"https://github.com/libexpat/libexpat/releases/"
                            f"download/R_{version_tag}/expat-{{version}}.tar.xz"
                        ),
                        "sha256": checksum,
                        "platforms": ["linux", "darwin", "win32"],
                    }
                    os.remove(download_path)
                except Exception as e:
                    print(f"Failed to download expat: {e}")

    # Write updated data
    all_data = {"python": pydata, "dependencies": dependencies}
    path.write_text(json.dumps(all_data, indent=1))
    print(f"Updated {path}")


def create_pyversions(path: pathlib.Path) -> None:
    """
    Create python-versions.json file.
    """
    url = "https://www.python.org/downloads/"
    content = fetch_url_content(url)
    matched = re.findall(r'<a href="/downloads/.*">Python.*</a>', content)
    cwd = os.getcwd()
    parsed_versions = sorted([_ref_version(_) for _ in matched], reverse=True)
    versions = [_ for _ in parsed_versions if _.major >= 3]

    if path.exists():
        all_data = json.loads(path.read_text())
        # Handle both old format (flat dict) and new format (nested)
        if "python" in all_data:
            pydata = all_data["python"]
            dependencies = all_data.get("dependencies", {})
        else:
            # Old format - convert to new
            pydata = all_data
            dependencies = {}
    else:
        pydata = {}
        dependencies = {}

    for version in versions:
        if version >= Version("3.14"):
            continue

        if str(version) in pydata:
            continue

        if version <= Version("3.2") and version.micro == 0:
            url_version = Version(f"{version.major}.{version.minor}")
        else:
            url_version = version
        if version >= Version("3.1.4"):
            url = ARCHIVE.format(version=url_version, ext="tar.xz")
        else:
            url = ARCHIVE.format(version=url_version, ext="tgz")
        download_path = download_url(url, cwd)
        sig_path = download_url(f"{url}.asc", cwd)
        verified = verify_signature(download_path, sig_path)
        if verified:
            print(f"Version {version} has digest {digest(download_path)}")
            pydata[str(version)] = digest(download_path)
        else:
            raise Exception("Signature failed to verify: {url}")

        # Write in new structured format
        all_data = {"python": pydata, "dependencies": dependencies}
        path.write_text(json.dumps(all_data, indent=1))

    # Final write in new structured format
    all_data = {"python": pydata, "dependencies": dependencies}
    path.write_text(json.dumps(all_data, indent=1))


def python_versions(
    minor: str | None = None,
    *,
    create: bool = False,
    update: bool = False,
) -> dict[Version, str]:
    """
    List python versions.
    """
    packaged = pathlib.Path(__file__).parent / "python-versions.json"
    local = pathlib.Path("~/.local/relenv/python-versions.json")

    if update:
        create = True

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
    data = json.loads(readfrom.read_text())
    # Handle both old format (flat dict) and new format (nested with "python" key)
    pyversions = (
        data.get("python", data)
        if isinstance(data, dict) and "python" in data
        else data
    )
    versions = [Version(_) for _ in pyversions]
    if minor:
        mv = Version(minor)
        versions = [_ for _ in versions if _.major == mv.major and _.minor == mv.minor]
    return {version: pyversions[str(version)] for version in versions}


def get_default_python_version() -> str:
    """
    Get the default Python version to use when none is specified.

    :return: The default Python version string (e.g., "3.10.19")
    """
    # Default to latest 3.10 version
    pyversions = python_versions("3.10")
    if not pyversions:
        raise RuntimeError("No 3.10 versions found")
    latest = sorted(list(pyversions.keys()))[-1]
    return str(latest)


def resolve_python_version(version_spec: str | None = None) -> str:
    """
    Resolve a Python version specification to a full version string.

    If version_spec is None, returns the latest Python 3.10 version.
    If version_spec is partial (e.g., "3.10"), returns the latest micro version.
    If version_spec is full (e.g., "3.10.19"), returns it as-is after validation.

    :param version_spec: Version specification (None, "3.10", or "3.10.19")
    :return: Full version string (e.g., "3.10.19")
    :raises RuntimeError: If the version is not found
    """
    if version_spec is None:
        # Default to latest 3.10 version
        return get_default_python_version()

    requested = Version(version_spec)

    if requested.micro is not None:
        # Full version specified - validate it exists
        pyversions = python_versions()
        if requested not in pyversions:
            raise RuntimeError(f"Unknown version {requested}")
        return str(requested)
    else:
        # Partial version (major.minor) - get latest micro
        pyversions = python_versions(version_spec)
        if not pyversions:
            raise RuntimeError(f"Unknown minor version {requested}")
        # Return the latest version for this major.minor
        latest = sorted(list(pyversions.keys()))[-1]
        return str(latest)


def setup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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
    subparser.add_argument(
        "--check-deps",
        default=False,
        action="store_true",
        help="Check for new dependency versions",
    )
    subparser.add_argument(
        "--update-deps",
        default=False,
        action="store_true",
        help="Update dependency versions (downloads and computes checksums)",
    )


def main(args: argparse.Namespace) -> None:
    """
    Versions utility main method.
    """
    packaged = pathlib.Path(__file__).parent / "python-versions.json"

    # Handle dependency operations
    if args.check_deps:
        print("Checking for new dependency versions...\n")

        # Load current versions from JSON
        with open(packaged) as f:
            data = json.load(f)

        current_deps = data.get("dependencies", {})
        updates_available = []
        up_to_date = []

        # Detect terminal capabilities for fancy vs ASCII output
        use_unicode = True
        if sys.platform == "win32":
            # Check if we're in a modern terminal that supports Unicode
            import os

            # Windows Terminal and modern PowerShell support Unicode
            wt_session = os.environ.get("WT_SESSION")
            term_program = os.environ.get("TERM_PROGRAM")
            if not wt_session and not term_program:
                # Likely cmd.exe or old PowerShell, use ASCII
                use_unicode = False

        if use_unicode:
            ok_symbol = "✓"
            update_symbol = "⚠"
            new_symbol = "✗"
            arrow = "→"
        else:
            ok_symbol = "[OK]    "
            update_symbol = "[UPDATE]"
            new_symbol = "[NEW]   "
            arrow = "->"

        # Check each dependency
        checks = [
            ("openssl", "OpenSSL", detect_openssl_versions),
            ("sqlite", "SQLite", detect_sqlite_versions),
            ("xz", "XZ", detect_xz_versions),
            ("libffi", "libffi", detect_libffi_versions),
            ("zlib", "zlib", detect_zlib_versions),
            ("ncurses", "ncurses", detect_ncurses_versions),
            ("readline", "readline", detect_readline_versions),
            ("gdbm", "gdbm", detect_gdbm_versions),
            ("libxcrypt", "libxcrypt", detect_libxcrypt_versions),
            ("krb5", "krb5", detect_krb5_versions),
            ("bzip2", "bzip2", detect_bzip2_versions),
            ("uuid", "uuid", detect_uuid_versions),
            ("tirpc", "tirpc", detect_tirpc_versions),
            ("expat", "expat", detect_expat_versions),
        ]

        for dep_key, dep_name, detect_func in checks:
            detected = detect_func()
            if not detected:
                continue

            # Handle SQLite's tuple return
            if dep_key == "sqlite":
                latest_version = detected[0][0]  # type: ignore[index]
            else:
                latest_version = detected[0]  # type: ignore[index]

            # Get current version from JSON
            current_version = None
            if dep_key in current_deps:
                versions = sorted(current_deps[dep_key].keys(), reverse=True)
                if versions:
                    current_version = versions[0]

            # Compare versions
            if current_version == latest_version:
                print(
                    f"{ok_symbol} {dep_name:12} {current_version:15} " f"(up-to-date)"
                )
                up_to_date.append(dep_name)
            elif current_version:
                print(
                    f"{update_symbol} {dep_name:12} {current_version:15} "
                    f"{arrow} {latest_version} (update available)"
                )
                updates_available.append((dep_name, current_version, latest_version))
            else:
                print(
                    f"{new_symbol} {dep_name:12} {'(not tracked)':15} "
                    f"{arrow} {latest_version}"
                )
                updates_available.append((dep_name, None, latest_version))

        # Summary
        print(f"\n{'=' * 60}")
        print(f"Summary: {len(up_to_date)} up-to-date, ", end="")
        print(f"{len(updates_available)} updates available")

        if updates_available:
            print("\nTo update dependencies, run:")
            print("  python3 -m relenv versions --update-deps")

        sys.exit(0)

    if args.update_deps:
        update_dependency_versions(packaged)
        sys.exit(0)

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
            build_version = sorted(list(pyversions.keys()))[-1]
        print(build_version)
        sys.exit()


if __name__ == "__main__":
    _main()
