import contextlib
import os
import pathlib
import shutil
import sys
import tarfile

from .common import MODULE_DIR, download_url, extract_archive, work_dir


def main(args):
    url = "https://woz.io/mayflower/{version}/build/{arch}-linux-gnu.tar.xz".format(
        version="0.0.0", arch=args.arch
    )
    builddir = work_dir("build")
    os.makedirs(builddir, exist_ok=True)
    archive = download_url(url, builddir)
    extract_archive(builddir, archive)
