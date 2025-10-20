# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
The windows build process.
"""
import glob
import shutil
import sys
import os
import pathlib
import tarfile
import logging
from .common import (
    runcmd,
    create_archive,
    MODULE_DIR,
    builds,
    install_runtime,
    patch_file,
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


def override_dependency(source, old, new):
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
    if env["RELENV_PY_MAJOR_VERSION"] in [
        "3.10",
        "3.11",
    ]:
        override_dependency(dirs.source, r"sqlite-\d+.\d+.\d+.\d+", "sqlite-3.50.4.0")
        override_dependency(dirs.source, r"xz-\d+.\d+.\d+", "xz-5.6.2")
        # We don't have a way to pass --organization to build.bat, so we need to
        # patch it
        old = r'.*get_externals\.bat"'
        new = 'get_externals.bat --organization saltstack"'
        patch_file(dirs.source / "PCbuild" / "build.bat", old=old, new=new)

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
