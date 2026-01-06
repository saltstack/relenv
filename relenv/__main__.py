# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
The entrypoint into relenv.
"""

from __future__ import annotations

import argparse
from argparse import ArgumentParser
from types import ModuleType

from . import build, buildenv, check, create, fetch, pyversions, toolchain
from .common import __version__


def setup_cli() -> ArgumentParser:
    """
    Build the argparser with its subparsers.

    The modules with commands to add must specify a setup_parser function
    that takes in the subparsers object from `argparse.add_subparsers()`

    :return: The fully setup argument parser
    :rtype: ``argparse.ArgumentParser``
    """
    argparser = ArgumentParser(
        prog="relenv",
        description="Relenv",
    )
    argparser.add_argument("--version", action="version", version=__version__)
    subparsers: argparse._SubParsersAction[
        argparse.ArgumentParser
    ] = argparser.add_subparsers()

    modules_to_setup: list[ModuleType] = [
        build,
        toolchain,
        create,
        fetch,
        check,
        buildenv,
        pyversions,
    ]
    for mod in modules_to_setup:
        mod.setup_parser(subparsers)

    return argparser


def main() -> None:
    """
    Run the relenv cli and disbatch to subcommands.
    """
    parser = setup_cli()
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
        parser.exit(1, "\nNo subcommand given...\n\n")


if __name__ == "__main__":
    main()
