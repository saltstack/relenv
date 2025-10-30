# Copyright 2023-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Helper for building libraries to install into a relenv environment.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .common import (
    MACOS_DEVELOPMENT_TARGET,
    RelenvException,
    get_toolchain,
    get_triplet,
)

log = logging.getLogger()


def setup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """
    Setup the subparser for the ``relenv buildenv`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser(
        "buildenv", description="Relenv build environment"
    )
    subparser.set_defaults(func=main)
    subparser.add_argument(
        "--json",
        default=False,
        action="store_true",
        help=("Output json to stdout instead of export statments"),
    )


def is_relenv() -> bool:
    """
    True when we are in a relenv environment.
    """
    return hasattr(sys, "RELENV")


def buildenv(
    relenv_path: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """
    Relenv build environment variable mapping.
    """
    if not relenv_path:
        if not is_relenv():
            raise RelenvException("Not in a relenv environment")
        relenv_path = sys.RELENV

    if sys.platform != "linux":
        raise RelenvException("buildenv is only supported on Linux")

    toolchain = get_toolchain()
    if not toolchain:
        raise RelenvException("buildenv is only supported on Linux")

    triplet = get_triplet()
    env = {
        "RELENV_BUILDENV": "1",
        "TOOLCHAIN_PATH": f"{toolchain}",
        "TRIPLET": f"{triplet}",
        "RELENV_PATH": f"{relenv_path}",
        "CC": f"{toolchain}/bin/{triplet}-gcc",
        "CXX": f"{toolchain}/bin/{triplet}-g++",
        "CFLAGS": f"-I{relenv_path}/include -I{toolchain}/sysroot/usr/include",
        "CXXFLAGS": (
            f"-I{relenv_path}/include "
            f"-I{toolchain}/{triplet}/sysroot/usr/include "
            f"-L{relenv_path}/lib -L{toolchain}/{triplet}/sysroot/lib "
            f"-Wl,-rpath,{relenv_path}/lib"
        ),
        "CPPFLAGS": (
            f"-I{relenv_path}/include " f"-I{toolchain}/{triplet}/sysroot/usr/include"
        ),
        "CMAKE_CFLAGS": (
            f"-I{relenv_path}/include " f"-I{toolchain}/{triplet}/sysroot/usr/include"
        ),
        "LDFLAGS": (
            f"-L{relenv_path}/lib -L{toolchain}/{triplet}/sysroot/lib "
            f"-Wl,-rpath,{relenv_path}/lib"
        ),
    }
    if sys.platform == "dawin":
        env["MACOS_DEVELOPMENT_TARGET"] = MACOS_DEVELOPMENT_TARGET
    return env


def main(args: argparse.Namespace) -> None:
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

    if args.json:
        print(json.dumps(buildenv()))
        sys.exit(0)

    script = ""
    for k, v in buildenv().items():
        script += f'export {k}="{v}"\n'

    print(script)
    sys.exit(0)
