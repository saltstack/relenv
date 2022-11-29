# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2
import glob
import shutil
import sys
import io
import os
import pathlib
import tarfile

from .common import Builder, runcmd, create_archive, MODULE_DIR, SITECUSTOMIZE
from ..common import arches, WIN32

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
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

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
        "python38.dll",
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
    shutil.copy(
        src=str(build_dir / "python38.lib"),
        dst=str(dirs.prefix / "libs" / "python38.lib"),
    )


build = Builder(populate_env=populate_env)

build.add(
    "python",
    build_func=build_python,
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "version": "3.8.14",
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
    bindir = pathlib.Path(dirs.prefix) / "Scripts"
    sitepackages = dirs.prefix / "Lib" / "site-packages"
    sitecustomize = sitepackages / "sitecustomize.py"
    with io.open(str(sitecustomize), "w") as fp:
        fp.write(SITECUSTOMIZE)

    # Lay down relenv.runtime, we'll pip install the rest later
    relenvdir = sitepackages / "relenv"
    os.makedirs(relenvdir, exist_ok=True)
    runtime = MODULE_DIR / "runtime.py"
    dest = relenvdir / "runtime.py"
    with io.open(runtime, "r") as rfp:
        with io.open(dest, "w") as wfp:
            wfp.write(rfp.read())
    runtime = MODULE_DIR / "common.py"
    dest = relenvdir / "common.py"
    with io.open(runtime, "r") as rfp:
        with io.open(dest, "w") as wfp:
            wfp.write(rfp.read())
    init = relenvdir / "__init__.py"
    init.touch()

    # Install pip
    python = dirs.prefix / "Scripts" / "python.exe"
    runcmd([str(python), "-m", "ensurepip"], env=env, stderr=logfp, stdout=logfp)

    def runpip(pkg):
        # XXX Support cross pip installs on windows
        pip = bindir / "pip3.exe"
        env = os.environ.copy()
        target = None
        cmd = [
            str(pip),
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
    archive = dirs.prefix.with_suffix(".tar.xz")
    with tarfile.open(archive, mode="w:xz") as fp:
        create_archive(fp, dirs.prefix, globs, logfp)


build.add(
    "relenv-finalize",
    build_func=finalize,
    wait_on=["python"],
)
