# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The ``relenv build`` command.
"""
import sys
import random
import codecs
import signal

from . import linux, darwin, windows
from .common import builds, CHECK_VERSIONS_SUPPORT

from ..common import build_arch


def platform_module():
    """
    Return the right module based on `sys.platform`.
    """
    if sys.platform == "darwin":
        return darwin
    elif sys.platform == "linux":
        return linux
    elif sys.platform == "win32":
        return windows


def platform_versions():
    """
    Return the right module based on `sys.platform`.
    """
    return list(builds.builds[sys.platform].keys())


def setup_parser(subparsers):
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
    build_subparser.add_argument(
        "--python",
        default=platform_versions()[0],
        choices=platform_versions(),
        type=str,
        help="The python version [default: %(default)s]",
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
        "--check-versions",
        default=False,
        action="store_true",
        help="Check for new version of python and it's depenencies, then exit.",
    )
    build_subparser.add_argument(
        "--no-pretty",
        default=False,
        action="store_true",
        help="Log build output to stdout instead of displaying a simplified status.",
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


def main(args):
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

    # XXX
    build = builds.builds[sys.platform][args.python]

    if args.check_versions:
        if not CHECK_VERSIONS_SUPPORT:
            print(
                "Check versions not supported. Please install the "
                "packaging and looseversion python packages."
            )
            sys.exit(2)
        if not build.check_versions():
            sys.exit(1)
        else:
            sys.exit(0)

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
    else:
        show_ui = True

    def signal_handler(signal, frame):
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)

    build(
        steps=steps,
        arch=args.arch,
        clean=args.clean,
        cleanup=not args.no_cleanup,
        force_download=args.force_download,
        show_ui=show_ui,
        log_level=args.log_level.upper(),
    )
