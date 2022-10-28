"""
The ``mayflower fetch`` command.
"""

import os

from .common import download_url, extract_archive, work_dir


def setup_parser(subparsers):
    """
    Setup the subparser for the ``fetch`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    fetch_subparser = subparsers.add_parser(
        "fetch", description="Fetch mayflower builds"
    )
    fetch_subparser.set_defaults(func=main)

    fetch_subparser.add_argument(
        "--arch",
        default="x86_64",
        choices=["x86_64", "x86", "aarch64"],
        help="Architecture to download. [default: %(default)s]",
    )


def main(args):
    """
    The entrypoint into the ``mayflower fetch`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    url = "https://woz.io/mayflower/{version}/build/{arch}-linux-gnu.tar.xz".format(
        version="0.0.0", arch=args.arch
    )
    builddir = work_dir("build")
    os.makedirs(builddir, exist_ok=True)
    archive = download_url(url, builddir)
    extract_archive(builddir, archive)
