import os
from .build.common import download_url, extract_archive
from .common import work_dir


def main(argparser):
    argparser.descrption = "Fetch mayflower builds"
    argparser.add_argument(
        "--arch", default="x86_64",
        help="Architecture to download"
    )
    ns, argv = argparser.parse_known_args()
    if getattr(ns, "help", None):
        argparser.print_help()
        sys.exit(0)
    url = "https://woz.io/mayflower/{version}/build/{arch}-linux-gnu.tar.xz".format(
        version="0.0.0", arch=ns.arch
    )
    builddir = work_dir("build")
    os.makedirs(builddir, exist_ok=True)
    archive = download_url(url, builddir)
    extract_archive(builddir, archive)
