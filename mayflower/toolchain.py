import os
import pathlib
import platform
import sys

from .common import (
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


def setup_parser(subparsers):
    toolchain_subparser = subparsers.add_parser(
        "toolchain", description="Build Linux Toolchains"
    )
    toolchain_subparser.set_defaults(func=main)

    toolchain_subparser.add_argument(
        "command",
        default="download",
        help="What type of toolchain operation to perform: build or download",
    )
    toolchain_subparser.add_argument(
        "--arch",
        action="append",
        dest="arches",
        metavar="ARCH",
        default=[],
        choices=["x86_64", "aarch64"],
        help="Arches to build or download, can be specified more than once for multiple arches",
    )
    toolchain_subparser.add_argument(
        "--clean",
        default=False,
        action="store_true",
        help="Whether or not to clean the toolchain directories",
    )
    toolchain_subparser.add_argument(
        "--crosstool-only",
        default=False,
        action="store_true",
        help="When building only build Crosstool NG. Do not build toolchains",
    )

def download(arch, toolchain, clean=False):
    """
    Download a toolchain and extract it to the filesystem.

    :param str arch: the architecture of the toolchain
    :param str toolchain: where to extract the toolchain
    """
    triplet = get_triplet(arch)
    archdir = get_toolchain(arch)
    if clean:
        shutil.rmtree(archdir)
    if archdir.exists():
        print("Toolchain directory exists, skipping {}".format(arch))
    url = TC_URL.format(version="0.0.0", host=platform.machine(), triplet=triplet)
    print("Downloading {}".format(url))
    archive = download_url(url, toolchain)
    extract_archive(toolchain, archive)


def main(args):
    args.arches = {_.lower() for _ in args.arches}
    if not args.arches:
        args.arches = {"x86_64", "aarch64"}
    machine = platform.machine()
    toolchain = get_toolchain()
    if not toolchain.exists():
        os.makedirs(toolchain)
    if args.command == "download":
        for arch in args.arches:
            download(arch, dirs.toolchain, ns.clean)
        sys.exit(0)
    elif args.command == "build":
        ctngdir = toolchain / "crosstool-ng-{}".format(CT_NG_VER)
    dirs = work_dirs()
    if not dirs.toolchain.exists():
        os.makedirs(dirs.toolchain)
    if ns.command == "download":
        for arch in ns.arch:
            download(arch, dirs.toolchain, ns.clean)
        sys.exit(0)
    elif ns.command == "build":
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
            os.chdir(toolchain)
        if args.crosstool_only:
            sys.exit(0)
        ctng = ctngdir / "ct-ng"
        for arch in args.arches:
            triplet = get_triplet(arch)
            archdir = dirs.toolchain / triplet
            if archdir.exists():
                print("Toolchain directory exists: {}".format(archdir))
                continue
            config = dirs.toolchain / machine / "{}-ct-ng.config".format(triplet)
            if not config.exists():
                print("Toolchain config missing: {}".format(config))
                sys.exit(1)
            with open(config, "r") as rfp:
                with open(".config", "w") as wfp:
                    wfp.write(rfp.read())
            env = os.environ.copy()
            env["CT_PREFIX"] = dirs.toolchain
            env["CT_ALLOW_BUILD_AS_ROOT"] = "yes"
            env["CT_ALLOW_BUILD_AS_ROOT_SURE"] = "yes"
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
