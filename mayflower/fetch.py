import contextlib
import os
import pathlib
import shutil
import sys
import tarfile

from .common import MODULE_DIR, download_url, extract_archive, work_dir


def setup_parser(subparsers):
    fetch_subparser = subparsers.add_parser(
        "fetch", description="Fetch mayflower builds"
    )
    fetch_subparser.set_defaults(func=main)

    fetch_subparser.add_argument(
        "--arch",
        default="x86_64",
        choices=["x86_64", "aarch64"],
        help="Architecture to download",
    )


def main(args):
    url = "https://woz.io/mayflower/{version}/build/{arch}-linux-gnu.tar.xz".format(
        version="0.0.0", arch=args.arch
    )
    builddir = work_dir("build")
    os.makedirs(builddir, exist_ok=True)
    archive = download_url(url, builddir)
    extract_archive(builddir, archive)
