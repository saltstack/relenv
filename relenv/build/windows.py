# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2
# mypy: ignore-errors
"""
The windows build process.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import pathlib
import shutil
import sys
import tarfile
import time
from typing import IO, MutableMapping, Union

from .common import (
    Dirs,
    builds,
    create_archive,
    get_dependency_version,
    install_runtime,
    patch_file,
    update_ensurepip,
    update_sbom_checksums,
)
from ..common import (
    WIN32,
    arches,
    MODULE_DIR,
    download_url,
    extract_archive,
    runcmd,
)

log = logging.getLogger(__name__)

ARCHES = arches[WIN32]

EnvMapping = MutableMapping[str, str]

if sys.platform == WIN32:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def populate_env(env: EnvMapping, dirs: Dirs) -> None:
    """
    Make sure we have the correct environment variables set.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    """
    env["MSBUILDDISABLENODEREUSE"] = "1"


def update_props(source: pathlib.Path, old: str, new: str) -> None:
    """
    Overwrite a dependency string for Windows PCBuild.

    :param source: Python's source directory
    :type source: str
    :param old: Regular expression to search for
    :type old: str
    :param new: Replacement text
    :type new: str
    """
    patch_file(source / "PCbuild" / "python.props", old, new)
    patch_file(source / "PCbuild" / "get_externals.bat", old, new)


def get_externals_source(externals_dir: pathlib.Path, url: str) -> None:
    """
    Download external source code dependency.

    Download source code and extract to the "externals" directory in the root of
    the python source. Only works with a tarball
    """
    zips_dir = externals_dir / "zips"
    zips_dir.mkdir(parents=True, exist_ok=True)
    local_file = download_url(url=url, dest=str(zips_dir))
    extract_archive(archive=str(local_file), to_dir=str(externals_dir))
    try:
        os.remove(local_file)
    except OSError:
        log.exception("Failed to remove temporary file")


def get_externals_bin(source_root: pathlib.Path, url: str) -> None:
    """
    Download external binary dependency.

    Download binaries to the "externals" directory in the root of the python
    source.
    """
    pass


def update_sqlite(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the SQLITE library.
    """
    # Try to get version from JSON
    sqlite_info = get_dependency_version("sqlite", "win32")
    if sqlite_info:
        version = sqlite_info["version"]
        url_template = sqlite_info["url"]
        sha256 = sqlite_info["sha256"]
        sqliteversion = sqlite_info.get("sqliteversion", "3500400")
        # Format the URL with sqliteversion (the 7-digit version number)
        url = url_template.format(version=sqliteversion)
    else:
        # Fallback to hardcoded values
        version = "3.50.4.0"
        url = "https://sqlite.org/2025/sqlite-autoconf-3500400.tar.gz"
        sha256 = "a3db587a1b92ee5ddac2f66b3edb41b26f9c867275782d46c3a088977d6a5b18"
        sqliteversion = "3500400"
    ref_loc = f"cpe:2.3:a:sqlite:sqlite:{version}:*:*:*:*:*:*:*"
    target_dir = dirs.source / "externals" / f"sqlite-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(dirs.source, r"sqlite-\d+.\d+.\d+.\d+", f"sqlite-{version}")
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        # # we need to fix the name of the extracted directory
        extracted_dir = dirs.source / "externals" / f"sqlite-autoconf-{sqliteversion}"
        shutil.move(str(extracted_dir), str(target_dir))
    # Update externals.spdx.json with the correct version, url, and hash
    # This became a thing in 3.12
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        with open(str(spdx_json), "r") as f:
            data = json.load(f)
            for pkg in data["packages"]:
                if pkg["name"] == "sqlite":
                    pkg["versionInfo"] = version
                    pkg["downloadLocation"] = url
                    pkg["checksums"][0]["checksumValue"] = sha256
                    pkg["externalRefs"][0]["referenceLocator"] = ref_loc
        with open(str(spdx_json), "w") as f:
            json.dump(data, f, indent=2)


def update_xz(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the XZ library.

    COMPATIBILITY NOTE: We use config.h from XZ 5.4.7 for all XZ versions.
    Starting with XZ 5.5.0, the project removed Visual Studio .vcxproj files
    and switched to CMake. Python's build system (PCbuild/liblzma.vcxproj)
    still expects MSBuild-compatible builds, so we maintain a compatibility
    shim at relenv/_resources/xz/config.h.

    When updating XZ versions, verify compatibility by checking:
    1. Build completes without compiler errors
    2. test_xz_lzma_functionality passes
    3. No new HAVE_* defines required in src/liblzma source files
    4. No removed HAVE_* defines that config.h references

    If compatibility breaks, you have two options:
    - Use CMake to generate new config.h for Windows (see discussion at
      https://discuss.python.org/t/building-python-from-source-on-windows-using-a-custom-version-of-xz/74717)
    - Update relenv/_resources/xz/config.h manually from newer XZ source

    See also: relenv/_resources/xz/readme.md
    """
    # Try to get version from JSON
    # Note: Windows may use a different XZ version than Linux/Darwin due to MSBuild compatibility
    xz_info = get_dependency_version("xz", "win32")
    if xz_info:
        version = xz_info["version"]
        url_template = xz_info["url"]
        sha256 = xz_info["sha256"]
        url = url_template.format(version=version)
    else:
        # Fallback to hardcoded values
        # Note: Using 5.6.2 for MSBuild compatibility (5.5.0+ removed MSBuild support)
        version = "5.6.2"
        url = f"https://github.com/tukaani-project/xz/releases/download/v{version}/xz-{version}.tar.xz"
        sha256 = "8bfd20c0e1d86f0402f2497cfa71c6ab62d4cd35fd704276e3140bfb71414519"
    ref_loc = f"cpe:2.3:a:tukaani:xz:{version}:*:*:*:*:*:*:*"
    target_dir = dirs.source / "externals" / f"xz-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(dirs.source, r"xz-\d+.\d+.\d+", f"xz-{version}")
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
    # Starting with version v5.5.0, XZ-Utils removed the ability to compile
    # with MSBuild. We are bringing the config.h from the last version that
    # had it, 5.4.7
    config_file = target_dir / "src" / "common" / "config.h"
    config_file_source = dirs.root / "_resources" / "xz" / "config.h"
    if not config_file.exists():
        shutil.copy(str(config_file_source), str(config_file))

    # Also copy crc32_table.c and crc64_table.c which are missing in newer XZ tarballs
    check_dir = target_dir / "src" / "liblzma" / "check"
    for filename in ["crc32_table.c", "crc64_table.c"]:
        target_file = check_dir / filename
        source_file = dirs.root / "_resources" / "xz" / filename
        if not target_file.exists():
            shutil.copy(str(source_file), str(target_file))
    # Update externals.spdx.json with the correct version, url, and hash
    # This became a thing in 3.12
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12", "3.13", "3.14"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        with open(str(spdx_json), "r") as f:
            data = json.load(f)
            for pkg in data["packages"]:
                if pkg["name"] == "xz":
                    pkg["versionInfo"] = version
                    pkg["downloadLocation"] = url
                    pkg["checksums"][0]["checksumValue"] = sha256
                    pkg["externalRefs"][0]["referenceLocator"] = ref_loc
        with open(str(spdx_json), "w") as f:
            json.dump(data, f, indent=2)


def update_expat(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the EXPAT library.
    """
    # Patch <src>/Modules/expat/refresh.sh. When the SBOM is created, refresh.sh
    # is scanned for the expat version, even though it doesn't run on Windows.

    # Try to get version from JSON
    expat_info = get_dependency_version("expat", "win32")
    if expat_info:
        version = expat_info["version"]
        hash = expat_info["sha256"]
    else:
        # Fallback to hardcoded values
        version = "2.7.3"
        hash = "821ac9710d2c073eaf13e1b1895a9c9aa66c1157a99635c639fbff65cdbdd732"

    url = f'https://github.com/libexpat/libexpat/releases/download/R_{version.replace(".", "_")}/expat-{version}.tar.xz'
    bash_refresh = dirs.source / "Modules" / "expat" / "refresh.sh"
    old = r'expected_libexpat_tag="R_\d+_\d+_\d"'
    new = f'expected_libexpat_tag="R_{version.replace(".", "_")}"'
    patch_file(bash_refresh, old=old, new=new)
    old = r'expected_libexpat_version="\d+.\d+.\d"'
    new = f'expected_libexpat_version="{version}"'
    patch_file(bash_refresh, old=old, new=new)
    old = 'expected_libexpat_sha256=".*"'
    new = f'expected_libexpat_sha256="{hash}"'
    patch_file(bash_refresh, old=old, new=new)
    get_externals_source(externals_dir=dirs.source / "Modules" / "expat", url=url)
    # Copy *.h and *.c to expat directory
    expat_lib_dir = dirs.source / "Modules" / "expat" / f"expat-{version}" / "lib"
    expat_dir = dirs.source / "Modules" / "expat"
    updated_files = []
    for file in glob.glob(str(expat_lib_dir / "*.h")):
        target = expat_dir / os.path.basename(file)
        if target.exists():
            target.unlink()
        shutil.move(file, str(expat_dir))
        updated_files.append(target)
    for file in glob.glob(str(expat_lib_dir / "*.c")):
        target = expat_dir / os.path.basename(file)
        if target.exists():
            target.unlink()
        shutil.move(file, str(expat_dir))
        updated_files.append(target)

    # Touch all updated files to ensure MSBuild rebuilds them
    # (The original files may have newer timestamps)
    now = time.time()
    for target_file in updated_files:
        os.utime(target_file, (now, now))

    # Update SBOM with correct checksums for updated expat files
    # Map SBOM file names to actual file paths
    files_to_update = {}
    for target_file in updated_files:
        # SBOM uses relative paths from Python source root
        relative_path = f"Modules/expat/{target_file.name}"
        files_to_update[relative_path] = target_file

    # Also include refresh.sh which was patched
    bash_refresh = dirs.source / "Modules" / "expat" / "refresh.sh"
    if bash_refresh.exists():
        files_to_update["Modules/expat/refresh.sh"] = bash_refresh

    update_sbom_checksums(dirs.source, files_to_update)


def build_python(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Run the commands to build Python.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    # Override default versions

    # Create externals directory
    externals_dir = dirs.source / "externals"
    externals_dir.mkdir(parents=True, exist_ok=True)

    update_sqlite(dirs=dirs, env=env)

    update_xz(dirs=dirs, env=env)

    update_expat(dirs=dirs, env=env)

    arch_to_plat = {
        "amd64": "x64",
        "x86": "win32",
        "arm64": "arm64",
    }
    arch = env["RELENV_HOST_ARCH"]
    plat = arch_to_plat[arch]
    cmd = [
        str(dirs.source / "PCbuild" / "build.bat"),
        "-p",
        plat,
        "--no-tkinter",
    ]

    log.info("Start PCbuild")
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    log.info("PCbuild finished")

    # This is where build.bat puts everything
    # TODO: For now we'll only support 64bit
    if arch == "amd64":
        build_dir = dirs.source / "PCbuild" / arch
    else:
        build_dir = dirs.source / "PCbuild" / plat
    bin_dir = dirs.prefix / "Scripts"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Move python binaries
    binaries = [
        "py.exe",
        "pyw.exe",
        "python.exe",
        "pythonw.exe",
        "python3.dll",
        f"python{ env['RELENV_PY_MAJOR_VERSION'].replace('.', '') }.dll",
        "vcruntime140.dll",
        "venvlauncher.exe",
        "venvwlauncher.exe",
    ]
    for binary in binaries:
        shutil.move(src=str(build_dir / binary), dst=str(bin_dir / binary))

    # Create DLLs directory
    (dirs.prefix / "DLLs").mkdir(parents=True, exist_ok=True)
    # Move all library files to DLLs directory (*.pyd, *.dll)
    for file in glob.glob(str(build_dir / "*.pyd")):
        shutil.move(src=file, dst=str(dirs.prefix / "DLLs"))
    for file in glob.glob(str(build_dir / "*.dll")):
        shutil.move(src=file, dst=str(dirs.prefix / "DLLs"))

    # Copy include directory
    shutil.copytree(
        src=str(dirs.source / "Include"),
        dst=str(dirs.prefix / "Include"),
        dirs_exist_ok=True,
    )
    if "3.13" not in env["RELENV_PY_MAJOR_VERSION"]:
        shutil.copy(
            src=str(dirs.source / "PC" / "pyconfig.h"),
            dst=str(dirs.prefix / "Include"),
        )

    # Copy library files
    shutil.copytree(
        src=str(dirs.source / "Lib"),
        dst=str(dirs.prefix / "Lib"),
        dirs_exist_ok=True,
    )
    os.makedirs(str(dirs.prefix / "Lib" / "site-packages"), exist_ok=True)

    # Create libs directory
    (dirs.prefix / "libs").mkdir(parents=True, exist_ok=True)
    # Copy lib files
    shutil.copy(
        src=str(build_dir / "python3.lib"),
        dst=str(dirs.prefix / "libs" / "python3.lib"),
    )
    pylib = f"python{ env['RELENV_PY_MAJOR_VERSION'].replace('.', '') }.lib"
    shutil.copy(
        src=str(build_dir / pylib),
        dst=str(dirs.prefix / "libs" / pylib),
    )


build = builds.add("win32", populate_env=populate_env)

build.add(
    "python",
    build_func=build_python,
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "version": build.version,
        "checksum": "d31d548cd2c5ca2ae713bebe346ba15e8406633a",
    },
)


def finalize(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Finalize sitecustomize, relenv runtime, and pip for Windows.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    # Lay down site customize
    sitepackages = dirs.prefix / "Lib" / "site-packages"
    install_runtime(sitepackages)

    # update ensurepip
    update_ensurepip(dirs.prefix / "Lib")

    # Install pip
    python = dirs.prefix / "Scripts" / "python.exe"
    runcmd([str(python), "-m", "ensurepip"], env=env, stderr=logfp, stdout=logfp)

    def runpip(pkg: Union[str, os.PathLike[str]]) -> None:
        # XXX Support cross pip installs on windows
        env = os.environ.copy()
        target = None
        cmd = [
            str(python),
            "-m",
            "pip",
            "install",
            str(pkg),
        ]
        if target:
            cmd.append("--target={}".format(target))
        runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    runpip("wheel")
    # This needs to handle running from the root of the git repo and also from
    # an installed Relenv
    if (MODULE_DIR.parent / ".git").exists():
        runpip(MODULE_DIR.parent)
    else:
        runpip("relenv")

    for root, _, files in os.walk(dirs.prefix):
        for file in files:
            if file.endswith(".pyc"):
                os.remove(pathlib.Path(root) / file)

    globs = [
        "*.exe",
        "*.py",
        "*.pyd",
        "*.dll",
        "*.lib",
        "*.whl",
        "/Include/*",
        "/Lib/site-packages/*",
    ]
    archive = f"{dirs.prefix}.tar.xz"
    with tarfile.open(archive, mode="w:xz") as fp:
        create_archive(fp, dirs.prefix, globs, logfp)


build.add(
    "relenv-finalize",
    build_func=finalize,
    wait_on=["python"],
)
