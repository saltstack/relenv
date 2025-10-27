# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
The windows build process.
"""
import glob
import json
import logging
import os
import pathlib
import shutil
import sys
import tarfile
from .common import (
    builds,
    create_archive,
    download_url,
    extract_archive,
    install_runtime,
    MODULE_DIR,
    patch_file,
    runcmd,
    update_ensurepip,
)
from ..common import arches, WIN32

log = logging.getLogger(__name__)

ARCHES = arches[WIN32]

if sys.platform == WIN32:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def populate_env(env, dirs):
    """
    Make sure we have the correct environment variables set.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    """
    env["MSBUILDDISABLENODEREUSE"] = "1"


def update_props(source, old, new):
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


def get_externals_source(externals_dir, url):
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


def get_externals_bin(source_root, url):
    """
    Download external binary dependency.

    Download binaries to the "externals" directory in the root of the python
    source.
    """
    pass


def build_python(env, dirs, logfp):
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

    # SQLITE
    # TODO: Python 3.12 started creating an SBOM. We're doing something wrong
    # TODO: updating sqlite so SBOM creation is failing. Gating here until we
    # TODO: fix this. Here's the original gate:
    # if env["RELENV_PY_MAJOR_VERSION"] in ["3.10", "3.11"]:
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.10", "3.11", "3.12"]:
        version = "3.50.4.0"
        url = "https://sqlite.org/2025/sqlite-autoconf-3500400.tar.gz"
        sha256 = "a3db587a1b92ee5ddac2f66b3edb41b26f9c867275782d46c3a088977d6a5b18"
        ref_loc = f"cpe:2.3:a:sqlite:sqlite:{version}:*:*:*:*:*:*:*"
        target_dir = externals_dir / f"sqlite-{version}"
        if not target_dir.exists():
            update_props(dirs.source, r"sqlite-\d+.\d+.\d+.\d+", f"sqlite-{version}")
            get_externals_source(externals_dir=externals_dir, url=url)
            # # we need to fix the name of the extracted directory
            extracted_dir = externals_dir / "sqlite-autoconf-3500400"
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

    # XZ-Utils
    # TODO: Python 3.12 started creating an SBOM. We're doing something wrong
    # TODO: updating XZ so SBOM creation is failing. Gating here until we fix
    # TODO: this. Here's the original gate:
    # if env["RELENV_PY_MAJOR_VERSION"] in ["3.10", "3.11"]:
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.10", "3.11", "3.12", "3.13", "3.14"]:
        version = "5.6.2"
        url = f"https://github.com/tukaani-project/xz/releases/download/v{version}/xz-{version}.tar.xz"
        sha256 = "8bfd20c0e1d86f0402f2497cfa71c6ab62d4cd35fd704276e3140bfb71414519"
        ref_loc = f"cpe:2.3:a:tukaani:xz:{version}:*:*:*:*:*:*:*"
        target_dir = externals_dir / f"xz-{version}"
        if not target_dir.exists():
            update_props(dirs.source, r"xz-\d+.\d+.\d+", f"xz-{version}")
            get_externals_source(externals_dir=externals_dir, url=url)
        # Starting with version v5.5.0, XZ-Utils removed the ability to compile
        # with MSBuild. We are bringing the config.h from the last version that
        # had it, 5.4.7
        config_file = target_dir / "src" / "common" / "config.h"
        config_file_source = dirs.root / "_resources" / "xz" / "config.h"
        if not config_file.exists():
            shutil.copy(str(config_file_source), str(config_file))
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


def finalize(env, dirs, logfp):
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

    def runpip(pkg):
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
