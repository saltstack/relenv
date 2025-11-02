# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
# mypy: ignore-errors
"""
The ``relenv fetch`` command.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from .build import platform_module
from .common import (
    CHECK_HOSTS,
    DATA_DIR,
    DEFAULT_PYTHON,
    __version__,
    build_arch,
    check_url,
    download_url,
    get_triplet,
    work_dir,
)


def setup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """
    Setup the subparser for the ``fetch`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    mod = platform_module()
    subparser = subparsers.add_parser("fetch", description="Fetch relenv builds")
    subparser.set_defaults(func=main)
    subparser.add_argument(
        "--arch",
        default=build_arch(),
        choices=mod.ARCHES,
        type=str,
        help="Architecture to download. [default: %(default)s]",
    )
    subparser.add_argument(
        "--python",
        default=DEFAULT_PYTHON,
        type=str,
        help="The python version [default: %(default)s]",
    )


def fetch(
    version: str,
    triplet: str,
    python: str,
    check_hosts: Sequence[str] = CHECK_HOSTS,
) -> None:
    """
    Fetch the specified python build.
    """
    url = f"https://github.com/saltstack/relenv/releases/download/v{version}/{python}-{triplet}.tar.xz"
    if not check_url(url, timeout=5):
        for host in check_hosts:
            url = f"https://{host}/relenv/{version}/build/{python}-{triplet}.tar.xz"
            if check_url(url, timeout=5):
                break
        else:
            print(
                f"Unable to find file on any hosts: github.com {' '.join(x.split('/')[0] for x in check_hosts)}"
            )
            sys.exit(1)
    builddir = work_dir("build", DATA_DIR)
    os.makedirs(builddir, exist_ok=True)
    download_url(url, builddir)


def main(args: argparse.Namespace) -> None:
    """
    The entrypoint into the ``relenv fetch`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    version = os.environ.get("RELENV_FETCH_VERSION", __version__)
    triplet = get_triplet(machine=args.arch)
    python = args.python
    check_hosts = CHECK_HOSTS
    if os.environ.get("RELENV_FETCH_HOST", ""):
        check_hosts = [os.environ["RELENV_FETCH_HOST"]]
    fetch(version, triplet, python, check_hosts)
