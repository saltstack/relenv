# Copyright 2023-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Helper for building libraries to install into a relenv environment.
"""
import logging
import sys

from .common import MACOS_DEVELOPMENT_TARGET, RelenvException, get_triplet, work_dirs

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


def is_relenv():
    """
    True when we are in a relenv environment.
    """
    return hasattr(sys, "RELENV")


def buildenv(relenv_path=None):
    """
    Relenv build environment variable mapping.
    """
    if not relenv_path:
        if not is_relenv():
            raise RelenvException("Not in a relenv environment")
        relenv_path = sys.RELENV

    if sys.platform != "linux":
        raise RelenvException("buildenv is only supported on Linux")

    dirs = work_dirs()
    triplet = get_triplet()
    toolchain = dirs.toolchain / get_triplet()
    env = {
        "RELENV_BUILDENV": "1",
        "TOOLCHAIN_PATH": f"{toolchain}",
        "TRIPLET": f"{triplet}",
        "RELENV_PATH": f"{relenv_path}",
        "CC": f"{toolchain}/bin/{triplet}-gcc -no-pie",
        "CXX": f"{toolchain}/bin/{triplet}-g++ -no-pie",
        "CFLAGS": (
            #   f"-L{relenv_path}/lib -L{toolchain}/{triplet}/sysroot/lib "
            f"-I{relenv_path}/include "
            f"-I{toolchain}/sysroot/usr/include"
        ),
        "CPPFLAGS": (
            #   f"-L{relenv_path}/lib -L{toolchain}/{triplet}/sysroot/lib "
            f"-I{relenv_path}/include -I{toolchain}/{triplet}/sysroot/usr/include"
        ),
        "CMAKE_CFLAGS": (
            #   f"-L{relenv_path}/lib -L{toolchain}/{triplet}/sysroot/lib "
            f"-I{relenv_path}/include -I{toolchain}/{triplet}/sysroot/usr/include"
        ),
        "LDFLAGS": (
            f"-L{relenv_path}/lib -L{toolchain}/{triplet}/sysroot/lib "
            f"-Wl,-rpath,{relenv_path}/lib"
        ),
    }
    if sys.platform == "dawin":
        env["MACOS_DEVELOPMENT_TARGET"] = MACOS_DEVELOPMENT_TARGET
    return env


def main(args):
    """
    The entrypoint into the ``relenv buildenv`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    logging.basicConfig(level=logging.INFO)
    if not is_relenv():
        log.error("Not in a relenv environment.")
        sys.exit(1)
    if sys.platform != "linux":
        log.error("buildenv is only supported on Linux.")

    # dirs = work_dirs()
    # triplet = get_triplet()
    # toolchain = dirs.toolchain / get_triplet()

    script = ""
    for k, v in buildenv().items():
        script += f'export {k}="{v}"\n'

    print(script)
