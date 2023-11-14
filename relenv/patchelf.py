# Copyright 2022-2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
Utility methods for our bundled patchelf. We only do this on linux.
"""
import os
import shutil
import pathlib
import relenv.common
import relenv.buildenv
import subprocess


URL = "https://github.com/NixOS/patchelf/releases/download/0.17.2/patchelf-0.17.2.tar.gz"

def find_patchelf():
    """
    Find the patchelf binary.

    First look for a bundled patchelf then use shutil.which to find a system
    patchelf. When all else failes,re turn the string 'patchelf'
    """
    bundled =  pathlib.Path(__file__).resolve().parent / "patchelf"
    if bundled.exists():
        return bundled
    if shutil.which("patchelf"):
        return shutil.which("patchelf")
    return "patchelf"


def build(clean=True):
    """
    Build our bundled patchelf
    """
    dest = pathlib.Path(".").resolve()
    archive_path = relenv.common.download_url(URL, dest, verbose=False)
    relenv.common.extract_archive(".", archive_path)
    prefix = pathlib.Path(__file__).resolve().parent

    # Remove .tar.gz
    source_dir = archive_path[:-7]

    orig_dir = os.getcwd()
    os.chdir(source_dir)
    env = os.environ.copy()
    env.update(relenv.buildenv.buildenv(prefix, include_rpath=False))
    subprocess.run("./configure", env=env, capture_output=True)
    subprocess.run("make", env=env, capture_output=True)
    os.chdir(orig_dir)
    src = pathlib.Path(source_dir) / "src" / "patchelf"
    dst = pathlib.Path("relenv") / "patchelf"
    shutil.copyfile(src, dst)
    shutil.copymode(src, dst)
    if clean:
        shutil.rmtree(source_dir)
        os.remove(archive_path)
