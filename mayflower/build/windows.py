import glob
import shutil
import urllib.request
from .common import *


def populate_env(env, dirs):
    env["MSBUILDDISABLENODEREUSE"] = "1"


def build_python(env, dirs, logfp):
    # Build python
    cmd = [
        str(dirs.source / "PCbuild" / "build.bat"),
        "-p",
        "x64" if dirs.arch == "x86_64" else "x86",
        "--no-tkinter",
    ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    # This is where build.bat puts everything
    # TODO: For now we'll only support 64bit
    build_dir = dirs.source / "PCbuild" / "amd64"
    bin_dir = dirs.prefix / "bin"

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
    (bin_dir / "DLLs").mkdir(parents=True, exist_ok=True)
    # Move all library files to DLLs directory (*.pyd, *.dll)
    for file in glob.glob(str(build_dir / "*.pyd")):
        shutil.move(src=file, dst=str(bin_dir / "DLLs"))
    for file in glob.glob(str(build_dir / "*.dll")):
        shutil.move(src=file, dst=str(bin_dir / "DLLs"))

    # Copy include directory
    shutil.copytree(
        src=str(dirs.source / "Include"),
        dst=str(bin_dir / "Include"),
    )
    shutil.copy(
        src=str(dirs.source / "PC" / "pyconfig.h"),
        dst=str(bin_dir / "Include"),
    )

    # Copy library files
    shutil.copytree(src=str(dirs.source / "Lib"), dst=str(bin_dir / "Lib"))

    # Create libs directory
    (bin_dir / "libs").mkdir(parents=True, exist_ok=True)
    # Copy lib files
    shutil.copy(
        src=str(build_dir / "python3.lib"),
        dst=str(bin_dir / "libs" / "python3.lib"),
    )
    shutil.copy(
        src=str(build_dir / "python38.lib"),
        dst=str(bin_dir / "libs" / "python38.lib"),
    )

    # TODO: This part will be removed when we build our own OpenSSL
    # Download OpenSSL dlls
    base_url = "https://repo.saltproject.io/windows/dependencies/64"
    urllib.request.urlretrieve(
        url="{}/openssl/1.1.1k/libeay32.dll".format(base_url),
        filename=str(bin_dir / "libeay32.dll"),
    )
    urllib.request.urlretrieve(
        url="{}/openssl/1.1.1k/ssleay32.dll".format(base_url),
        filename=str(bin_dir / "ssleay32.dll"),
    )

    # Download and install Pip


build = Builder(populate_env=populate_env)

build.add(
    "Python",
    "https://www.python.org/ftp/python/3.8.14/Python-3.8.14.tar.xz",
    None,
    build_func=build_python,
)


def main(argparse):
    run_build(build, argparse)


if __name__ == "__main__":
    from argparse import ArgumentParser
    main(ArgumentParser())
