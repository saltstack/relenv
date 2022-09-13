import sys, os, pathlib, shutil, contextlib, tarfile
from .build.common import download_url, extract_archive
from .common import MODULE_DIR


def main(argparser):
    argparser.descrption = "Fetch mayflower builds"
    argparser.add_argument(
        "--arch", default="x86_64",
        help="Architecture to download"
    )
    url = "https://woz.io/mayflower/build/x86_64-linux-gnu.tar.xz"
    builddir = pathlib.Path("build").resolve()
    os.makedirs(builddir, exist_ok=True)
    archive = download_url(url, builddir)
    extract_archive(builddir, archive)
