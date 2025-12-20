# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
# mypy: ignore-errors
"""
Entry points for the ``relenv build`` CLI command.
"""
from __future__ import annotations

import argparse
import codecs
import random
import signal
import sys
from types import FrameType, ModuleType

from . import darwin, linux, windows
from .common import builds
from ..common import build_arch
from ..pyversions import (
    Version,
    get_default_python_version,
    python_versions,
    resolve_python_version,
)


def platform_module() -> ModuleType:
    """
    Return the right module based on `sys.platform`.
    """
    if sys.platform == "darwin":
        return darwin
    elif sys.platform == "linux":
        return linux
    elif sys.platform == "win32":
        return windows
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def setup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """
    Setup the subparser for the ``build`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    mod = platform_module()
    build_subparser = subparsers.add_parser(
        "build", description="Build Relenv Python Environments from source"
    )
    build_subparser.set_defaults(func=main)
    build_subparser.add_argument(
        "--arch",
        default=build_arch(),
        choices=mod.ARCHES,
        type=str,
        help="The host architecture [default: %(default)s]",
    )
    build_subparser.add_argument(
        "--clean",
        default=False,
        action="store_true",
        help=(
            "Clean up before running the build. This option will remove the "
            "logs, src, build, and previous tarball."
        ),
    )
    default_version = get_default_python_version()
    build_subparser.add_argument(
        "--python",
        default=default_version,
        type=str,
        help="The python version (e.g., 3.10, 3.13.7) [default: %(default)s]",
    )
    build_subparser.add_argument(
        "--no-cleanup",
        default=False,
        action="store_true",
        help=(
            "By default the build directory is removed after the build "
            "tarball is created. Setting this option will leave the build "
            "directory in place."
        ),
    )
    # XXX We should automatically skip downloads that can be verified as not
    # being corrupt and this can become --force-download
    build_subparser.add_argument(
        "--force-download",
        default=False,
        action="store_true",
        help="Force downloading source tarballs even if they exist",
    )
    build_subparser.add_argument(
        "--download-only",
        default=False,
        action="store_true",
        help="Stop after downloading source tarballs",
    )
    build_subparser.add_argument(
        "--step",
        dest="steps",
        metavar="STEP",
        action="append",
        default=[],
        help=(
            "A step to run alone, can use multiple of this argument. When this option is used to "
            "invoke builds, depenencies of the steps are ignored.  This option "
            "should be used with care, as it's easy to request a situation that "
            "has no chance of being succesful. "
        ),
    )
    build_subparser.add_argument(
        "--no-pretty",
        default=False,
        action="store_true",
        help="Log build output to stdout instead of displaying a simplified status.",
    )
    build_subparser.add_argument(
        "--compact-pretty",
        default=False,
        action="store_true",
        help="Use compact UI without progress bars (simpler, less detailed).",
    )
    build_subparser.add_argument(
        "--log-level",
        default="warning",
        choices=(
            "error",
            "warning",
            "info",
            "debug",
        ),
        help="Log level determines how verbose the logs will be.",
    )


def main(args: argparse.Namespace) -> None:
    """
    The entrypoint to the ``build`` command.

    :param args: The arguments to the command
    :type args: ``argparse.Namespace``
    """
    random.seed()

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

    if sys.platform not in builds.builds:
        print(f"Unsupported platform: {sys.platform}")
        sys.exit(1)

    try:
        build_version_str = resolve_python_version(args.python)
    except RuntimeError as e:
        print(f"Error: {e}")
        pyversions = python_versions()
        strversions = "\n".join([str(_) for _ in pyversions])
        print(f"Known versions are:\n{strversions}")
        sys.exit(1)

    build_version = Version(build_version_str)
    pyversions = python_versions()
    print(f"Build Python {build_version}")

    # XXX
    build = builds.builds[sys.platform]
    build.version = str(build_version)
    build.dirs.version = str(build_version)
    build.recipies["python"]["download"].version = str(build_version)
    build.recipies["python"]["download"].checksum = pyversions[build_version]

    build.set_arch(args.arch)
    if build.build_arch != build.arch:
        print(
            "Warning: Cross compilation support is experimental and is not fully tested or working!"
        )
    steps = None
    if args.steps:
        steps = [_.strip() for _ in args.steps]
    if args.no_pretty:
        show_ui = False
        expanded_ui = False
    else:
        show_ui = True
        # Expanded UI is default, --compact-pretty disables it
        expanded_ui = not args.compact_pretty

    def signal_handler(_signal: int, frame: FrameType | None) -> None:
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)

    build(
        steps=steps,
        arch=args.arch,
        clean=args.clean,
        cleanup=not args.no_cleanup,
        force_download=args.force_download,
        download_only=args.download_only,
        show_ui=show_ui,
        log_level=args.log_level.upper(),
        expanded_ui=expanded_ui,
    )
