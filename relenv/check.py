# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Check the integrety of a relenv environment.
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from relenv import relocate

log: logging.Logger = logging.getLogger(__name__)


def setup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """
    Setup the subparser for the ``relenv check`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser("check", description="Check relenv integrity")
    subparser.set_defaults(func=main)


def main(args: argparse.Namespace) -> None:
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
