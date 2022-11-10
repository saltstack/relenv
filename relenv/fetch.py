# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The ``relenv fetch`` command.
"""

import os
import sys

from .common import (
    DATA_DIR,
    arches,
    download_url,
    extract_archive,
    get_triplet,
    host_arch,
    work_dir,
    __version__,
)


def setup_parser(subparsers):
    """
    Setup the subparser for the ``fetch`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser("fetch", description="Fetch relenv builds")
    subparser.set_defaults(func=main)

    subparser.add_argument(
        "--arch",
        default=host_arch(),
        choices=arches[sys.platform],
        help="Architecture to download. [default: %(default)s]",
    )
    subparser.add_argument(
        "--version",
        default=__version__,
        help="Version of relenv to fetch from, by default this is the latest relenv version"
    )


def main(args):
    """
    The entrypoint into the ``relenv fetch`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    url = "https://woz.io/relenv/{version}/build/{triplet}.tar.xz".format(
        version=args.version, platform=sys.platform, triplet=get_triplet()
    )
    builddir = work_dir("build", DATA_DIR)
    os.makedirs(builddir, exist_ok=True)
    archive = download_url(url, builddir)
