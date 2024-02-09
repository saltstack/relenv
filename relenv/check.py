# Copyright 2023-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Check the integrety of a relenv environment.
"""
import logging
import pathlib
import sys

from . import relocate

log = logging.getLogger()


def setup_parser(subparsers):
    """
    Setup the subparser for the ``relenv check`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser("check", description="Check relenv integrity")
    subparser.set_defaults(func=main)


def main(args):
    """
    The entrypoint into the ``relenv check`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    logging.basicConfig(level=logging.INFO)
    if not hasattr(sys, "RELENV"):
        log.error("Not in a relenv environment")
        sys.exit(1)
    relocate.main(sys.RELENV, pathlib.Path(sys.RELENV) / "lib")
