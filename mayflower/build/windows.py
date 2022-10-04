import glob
import shutil
import urllib.request
import sys
from .common import *

if sys.platform == "win32":
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def populate_env(env, dirs):
    env["MSBUILDDISABLENODEREUSE"] = "1"


def build_python(env, dirs, logfp):
    # Build python
    cmd = [
        str(dirs.source / "PCbuild" / "build.bat"),
        "-p",
        "x64" if env["MAYFLOWER_ARCH"] == "x86_64" else "x86",
        "--no-tkinter",
    ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    # This is where build.bat puts everything
    # TODO: For now we'll only support 64bit
    build_dir = dirs.source / "PCbuild" / "amd64"
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
    "Python",
    build_func=build_python,
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "version": "3.8.14",
    },
)


def finalize(env, dirs, logfp):
    # Lay down site customize
    bindir = pathlib.Path(dirs.prefix) / "Scripts"
    sitepackages = dirs.prefix / "Lib" / "site-packages"
    sitecustomize = sitepackages / "sitecustomize.py"
    with io.open(str(sitecustomize), "w") as fp:
        fp.write(SITECUSTOMIZE)

    # Lay down mayflower.runtime, we'll pip install the rest later
    mayflowerdir = sitepackages / "mayflower"
    os.makedirs(mayflowerdir, exist_ok=True)
    runtime = MODULE_DIR / "runtime.py"
    dest = mayflowerdir / "runtime.py"
    with io.open(runtime, "r") as rfp:
        with io.open(dest, "w") as wfp:
            wfp.write(rfp.read())
    runtime = MODULE_DIR / "common.py"
    dest = mayflowerdir / "common.py"
    with io.open(runtime, "r") as rfp:
        with io.open(dest, "w") as wfp:
            wfp.write(rfp.read())
    init = mayflowerdir / "__init__.py"
    init.touch()

    # Install pip
    python = dirs.prefix / "Scripts" / "python.exe"
    runcmd([python, "-m", "ensurepip"], env=env, stderr=logfp, stdout=logfp)

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
        print(cmd)
        if target:
            cmd.append("--target={}".format(target))
        runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    runpip("wheel")
    # This needs to handle running from the root of the git repo and also from
    # an installed Mayflower
    if (MODULE_DIR.parent / ".git").exists():
        runpip(MODULE_DIR.parent)
    else:
        runpip("mayflower")
    globs = [
        "*.exe",
        "*.py",
        "*.pyd",
        "*.dll",
    ]
    archive = dirs.prefix.with_suffix(".tar.xz")
    with tarfile.open(archive, mode="w:xz") as fp:
        create_archive(fp, dirs.prefix, globs, logfp)


build.add(
    "mayflower-finalize",
    build_func=finalize,
    wait_on=["Python"],
)


def main(argparse):
    run_build(build, argparse)


if __name__ == "__main__":
    from argparse import ArgumentParser

    main(ArgumentParser())
