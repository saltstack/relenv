# Copyright 2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Helper for building libraries to install into a relenv environment.
"""
import logging
import sys
import textwrap

from .common import get_triplet, work_dirs

log = logging.getLogger()


def setup_parser(subparsers):
    """
    Setup the subparser for the ``relenv buildenv`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser(
        "buildenv", description="Relenv build environment"
    )
    subparser.set_defaults(func=main)


def main(args):
    """
    The entrypoint into the ``relenv buildenv`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    logging.basicConfig(level=logging.INFO)
    if not hasattr(sys, "RELENV"):
        log.error("Not in a relenv environment.")
        sys.exit(1)
    if sys.platform != "linux":
        log.error("buildenv is only supported on Linux.")

    dirs = work_dirs()
    triplet = get_triplet()
    toolchain = dirs.toolchain / get_triplet()

    print(
        textwrap.dedent(
            """\
            export RELENV_BUILDENV=1
            export TOOLCHAIN_PATH="{toolchain}"
            export RELENV_PATH="{relenv}"
            export CC="${{TOOLCHAIN_PATH}}/bin/{triplet}-gcc -no-pie"
            export CXX="${{TOOLCHAIN_PATH}}/bin/{triplet}-g++ -no-pie"
            export CFLAGS="-L${{RELENV_PATH}}/lib -L${{TOOLCHAIN_PATH}}/sysroot/lib \
-I${{RELENV_PATH}}/include -I${{TOOLCHAIN_PATH}}/sysroot/usr/include"
            export CPPFLAGS="-L${{RELENV_PATH}}/lib -L${{TOOLCHAIN_PATH}}/sysroot/lib \
-I${{RELENV_PATH}}/include -I${{TOOLCHAIN_PATH}}/sysroot/usr/include"
            export CMAKE_CFLAGS="-L${{RELENV_PATH}}/lib -L${{TOOLCHAIN_PATH}}/sysroot/lib \
-I${{RELENV_PATH}}/include -I${{TOOLCHAIN_PATH}}/sysroot/usr/include"
            export LDFLAGS="-L${{RELENV_PATH}}/lib -L${{TOOLCHAIN_PATH}}/sysroot/lib \
-Wl,-rpath,${{RELENV_PATH}}/lib"
        """.format(
                relenv=sys.RELENV,
                toolchain=toolchain,
                triplet=triplet,
            )
        )
    )
