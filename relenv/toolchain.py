# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The ``relenv toolchain`` command.
"""

import os
import pathlib
import platform
import shutil
import sys

from .common import (
    CHECK_HOSTS,
    DATA_DIR,
    __version__,
    arches,
    build_arch,
    check_url,
    download_url,
    extract_archive,
    get_toolchain,
    get_triplet,
    runcmd,
    work_dirs,
)

CT_NG_VER = "1.25.0"
CT_URL = "http://crosstool-ng.org/download/crosstool-ng/crosstool-ng-{version}.tar.bz2"
TC_URL = "https://{hostname}/relenv/{version}/toolchain/{host}/{triplet}.tar.xz"
CICD = "CI" in os.environ


def setup_parser(subparsers):
    """
    Setup the subparser for the ``toolchain`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser("toolchain", description="Build Linux Toolchains")
    subparser.set_defaults(func=main)

    subparser.add_argument(
        "command",
        default="fetch",
        choices=["build", "fetch"],
        help="What type of toolchain operation to perform: build or fetch",
    )
    subparser.add_argument(
        "--arch",
        default=build_arch(),
        choices=arches[sys.platform],
        help="Architecture to build or fetch",
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


def fetch(arch, toolchain, clean=False, version=__version__):
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
    archdir = get_toolchain(root=pathlib.Path(DATA_DIR) / "toolchain", arch=arch)
    if clean:
        shutil.rmtree(archdir)
    if archdir.exists():
        print(f"Toolchain directory exists, skipping {arch}")
        return

    check_hosts = CHECK_HOSTS
    if os.environ.get("RELENV_FETCH_HOST", ""):
        check_hosts = [os.environ["RELENV_FETCH_HOST"]]
    for host in check_hosts:
        url = TC_URL.format(
            hostname=host, version=version, host=platform.machine(), triplet=triplet
        )
        if check_url(url, timeout=5):
            break
    else:
        print(f"Unable to find file on an hosts {' '.join(check_hosts)}")
        sys.exit(1)

    archive = download_url(url, toolchain)
    extract_archive(toolchain, archive)


def _configure_ctng(ctngdir, dirs):
    """
    Configure crosstool-ng.

    :param ctngdir: The directory holding crosstool-ng
    :type ctngdir: str
    :param dirs: The working directories
    :type dirs: ``relenv.common.WorkDirs``
    """
    if not ctngdir.exists():
        url = CT_URL.format(version=CT_NG_VER)
        archive = download_url(url, dirs.toolchain)
        extract_archive(dirs.toolchain, archive)
    os.chdir(ctngdir)
    ctng = ctngdir / "ct-ng"
    if not ctng.exists():
        runcmd(["./configure", "--enable-local"])
        runcmd(["make"])


def build(arch, dirs, machine, ctngdir):
    """
    Build a toolchaing for the given arch.

    :param arch: The architecture to build for
    :type arch: str
    :param dirs: The working directories
    :type dirs: ``relenv.common.WorkDirs``
    :param machine: The machine to build for
    :type machine: str
    :param ctngdir: The directory holding crosstool-ng
    :type ctngdir: ``pathlib.Path``
    """
    os.chdir(dirs.toolchain)
    ctng = ctngdir / "ct-ng"
    triplet = get_triplet(arch)
    archdir = dirs.toolchain / triplet
    if archdir.exists():
        print("Toolchain directory exists: {}".format(archdir))
    else:
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


def main(args):
    """
    The entrypoint into the ``relenv toolchain`` command.

    :param args: The arguments for the command
    :type args: ``argparse.Namespace``
    """
    version = os.environ.get("RELENV_FETCH_VERSION", __version__)
    machine = platform.machine()
    dirs = work_dirs()
    print(f"Toolchain directory: {dirs.toolchain}")
    if not dirs.toolchain.exists():
        os.makedirs(dirs.toolchain)
    if args.command == "fetch":
        fetch(args.arch, dirs.toolchain, args.clean, version)
        sys.exit(0)
    elif args.command == "build":
        ctngdir = dirs.toolchain / "crosstool-ng-{}".format(CT_NG_VER)
        _configure_ctng(ctngdir, dirs)
        if args.crosstool_only:
            sys.exit(0)
        build(args.arch, dirs, machine, ctngdir)


if __name__ == "__main__":
    from argparse import ArgumentParser

    main(ArgumentParser())
