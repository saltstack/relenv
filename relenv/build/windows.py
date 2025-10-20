# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
The windows build process.
"""
import glob
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


def get_externals_source(source_root, url):
    """
    Download external source code dependency.

    Download source code and extract to the "externals" directory in the root of
    the python source. Only works with a tarball
    """
    externals_dir = source_root / "externals"
    externals_dir.mkdir(parents=True, exist_ok=True)
    local_file = download_url(url, str(externals_dir))
    extract_archive(str(local_file), str(externals_dir))
    os.path.unlink(str(local_file))


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
    # SQLITE
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.10", "3.11", "3.12"]:
        version = "3.50.4.0"
        update_props(dirs.source, r"sqlite-\d+.\d+.\d+.\d+", "sqlite-{ver}")
        url = "https://sqlite.org/2025/sqlite-autoconf-3500400.tar.gz"
        get_externals_source(dirs.source, url=url)
        # we need to fix the name of the extracted directory
        extracted_dir = dirs.source / "externals" / "sqlite-src-3500400"
        target_dir = dirs.source / "externals" / f"sqlite-{version}"
        shutil.move(str(extracted_dir), str(target_dir))

    # XZ-Utils
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.10", "3.11", "3.12", "3.13", "3.14"]:
        update_props(dirs.source, r"xz-\d+.\d+.\d+", "xz-5.6.2")
        url = "https://github.com/tukaani-project/xz/releases/download/v5.6.2/xz-5.6.2.tar.xz"
        get_externals_source(dirs.source, url=url)

    # zlib (3.14 uses zlib-ng)
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.10", "3.11", "3.12", "3.13"]:
        # already in python.props with the correct version in all the above versions
        # update_props(dirs.source, r"zlib-\d+.\d+.\d+", "zlib-1.3.1")
        # but it still needs to be in "externals"
        url = "https://zlib.net/zlib-1.3.1.tar.gz"
        get_externals_source(dirs.source, url=url)

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
        "-e",
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
