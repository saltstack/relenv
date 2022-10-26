"""
The ``mayflower toolchain`` command.
"""

import os
import platform
import sys

from .common import (
    TOOLCHAIN,
    download_url,
    extract_archive,
    get_toolchain,
    get_triplet,
    runcmd,
    work_dirs,
)

WORK_IN_CWD = False
CT_NG_VER = "1.25.0"
CT_URL = "http://crosstool-ng.org/download/crosstool-ng/crosstool-ng-{version}.tar.bz2"
TC_URL = "https://woz.io/mayflower/{version}/toolchain/{host}/{triplet}.tar.xz"
CICD = "CI" in os.environ


def setup_parser(subparsers):
    """
    Setup the subparser for the ``toolchain`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser(
        "toolchain", description="Build Linux Toolchains"
    )
    subparser.set_defaults(func=main)

    subparser.add_argument(
        "command",
        default="fetch",
        choices=["build", "fetch"],
        help="What type of toolchain operation to perform: build or fetch",
    )
    subparser.add_argument(
        "--arch",
        action="append",
        dest="arches",
        metavar="ARCH",
        default=[],
        choices=["x86_64", "aarch64"],
        help="Arches to build or fetch, can be specified more than once for multiple arches",
    )
    subparser.add_argument(
        "--clean",
        default=False,
        action="store_true",
        help="Whether or not to clean the toolchain directories",
    )
    subparser.add_argument(
        "--crosstool-only",
        default=False,
        action="store_true",
        help="When building only build Crosstool NG. Do not build toolchains",
    )


def fetch(arch, toolchain, clean=False):
    """
    Fetch a toolchain and extract it to the filesystem.

    :param arch: The architecture of the toolchain
    :type arch: str
    :param toolchain: Where to extract the toolchain
    :type toolchain: str
    :param clean: If true, clean the toolchain directories first
    :type clean: bool
    """
    triplet = get_triplet(arch)
    archdir = get_toolchain(root=TOOLCHAIN, arch=arch)
    if clean:
        shutil.rmtree(archdir)
    if archdir.exists():
        print("Toolchain directory exists, skipping {}".format(arch))
        return
    url = TC_URL.format(version="0.0.0", host=platform.machine(), triplet=triplet)
    print("Fetching {}".format(url))
    archive = download_url(url, toolchain)
    extract_archive(toolchain, archive)


def main(args):
    """
    The entrypoint into the ``mayflower toolchain`` command.

    :param args: The arguments for the command
    :type args: ``argparse.Namespace``
    """
    args.arches = {_.lower() for _ in args.arches}
    if not args.arches:
        args.arches = {"x86_64", "aarch64"}
    machine = platform.machine()
    dirs = work_dirs()
    print(dirs.toolchain)
    if not dirs.toolchain.exists():
        os.makedirs(dirs.toolchain)
    if args.command == "fetch":
        for arch in args.arches:
            fetch(arch, dirs.toolchain, args.clean)
        sys.exit(0)
    elif args.command == "build":
        ctngdir = dirs.toolchain / "crosstool-ng-{}".format(CT_NG_VER)
        if not ctngdir.exists():
            url = CT_URL.format(version=CT_NG_VER)
            archive = download_url(url, dirs.toolchain)
            extract_archive(dirs.toolchain, archive)
        os.chdir(ctngdir)
        ctng = ctngdir / "ct-ng"
        if not ctng.exists():
            runcmd(["./configure", "--enable-local"])
            runcmd(["make"])
        if args.crosstool_only:
            sys.exit(0)
        os.chdir(dirs.toolchain)
        ctng = ctngdir / "ct-ng"
        for arch in args.arches:
            triplet = get_triplet(arch)
            archdir = dirs.toolchain / triplet
            if archdir.exists():
                print("Toolchain directory exists: {}".format(archdir))
                continue
            config = dirs.toolchain_config / machine / "{}-ct-ng.config".format(triplet)
            if not config.exists():
                print("Toolchain config missing: {}".format(config))
                sys.exit(1)
            with open(config, "r") as rfp:
                with open(".config", "w") as wfp:
                    wfp.write(rfp.read())
            env = os.environ.copy()
            env["CT_PREFIX"] = dirs.toolchain
            env["CT_ALLOW_BUILD_AS_ROOT"] = "y"
            env["CT_ALLOW_BUILD_AS_ROOT_SURE"] = "y"
            if CICD:
                env["CT_LOG_PROGRESS"] = "n"
            runcmd(
                [
                    str(ctng),
                    "source",
                ],
                env=env,
            )
            runcmd(
                [
                    str(ctng),
                    "build",
                ],
                env=env,
            )


if __name__ == "__main__":
    from argparse import ArgumentParser

    main(ArgumentParser())
