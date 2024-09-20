# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
The ``relenv toolchain`` command.
"""


def setup_parser(subparsers):
    """
    Setup the subparser for the ``toolchain`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser("toolchain", description="Build Linux Toolchains")
    subparser.set_defaults(func=main)


def main(*args, **kwargs):
    """
    Notify users of toolchain command deprecation.
    """
    print("The relenv toolchain command has been deprecated. Please pip install ppbt.")


if __name__ == "__main__":
    main()
