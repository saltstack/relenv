import os
import pathlib
import sys

from .build.common import download_url, extract_archive, runcmd
from .common import MODULE_DIR, get_toolchain, work_dirs, work_root

WORK_IN_CWD = False
CT_NG_VER = "1.25.0"
CT_URL = "http://crosstool-ng.org/download/crosstool-ng/crosstool-ng-{version}.tar.bz2"

# XXX This should be triplet not arch
TC_URL = "https://woz.io/mayflower/{version}/toolchain/{arch}-linux-gnu.tar.xz"


def main(argparser):
    argparser.descrption = "Build Linux Toolchains"
    argparser.add_argument(
        "command",
        default="download",
        help="What type of toolchain operation to perform: build or download",
    )
    argparser.add_argument(
        "--arch",
        default="x86_64,aarch64",
        help="Comma separated list of arches to build or download",
    )
    argparser.add_argument(
        "--clean",
        default=False,
        action="store_true",
        help="Comma separated list of arches to build or download",
    )
    argparser.add_argument(
        "--crosstool-only",
        default=False,
        action="store_true",
        help="When building only build Crosstool NG. Do not build toolchains",
    )
    ns, argv = argparser.parse_known_args()
    if getattr(ns, "help", None):
        argparser.print_help()
        sys.exit(0)
    ns.arch = [_.strip() for _ in ns.arch.split(",")]
    toolchain = get_toolchain()
    if not toolchain.exists():
        os.makedirs(toolchain)
    if ns.command == "download":
        for arch in ns.arch:
            archdir = get_toolchain(arch)
            if ns.clean:
                shutil.rmtree(archdir)
            if archdir.exists():
                print("Toolchain directory exists, skipping {}".format(arch))
            url = TC_URL.format(version="0.0.0", arch=arch)
            print("Downloading {}".format(url))
            archive = download_url(url, toolchain)
            extract_archive(toolchain, archive)
        sys.exit(0)
    elif ns.command == "build":
        ctngdir = toolchain / "crosstool-ng-{}".format(CT_NG_VER)
        if not ctngdir.exists():
            url = CT_URL.format(version=CT_NG_VER)
            archive = download_url(url, toolchain)
            extract_archive(toolchain, archive)
            os.chdir(ctngdir)
            runcmd(["./configure", "--enable-local"])
            runcmd(["make"])
            os.chdir(toolchain)
        if ns.crosstool_only:
            sys.exit(0)

        ctng = ctngdir / "ct-ng"
        for arch in ns.arch:
            triplet = "{}-linux-gnu".format(arch)
            archdir = toolchain / triplet
            if archdir.exists():
                print("Toolchain directory exists: {}".format(arch))
                continue
            config = toolchain / "{}-ct-ng.config".format(triplet)
            if not config.exists():
                print("Toolchain config missing: {}".format(config))
                sys.exit(1)
            with open(config, "r") as rfp:
                with open(".config", "w") as wfp:
                    wfp.write(rfp.read())
            env = os.environ.copy()
            env["CT_PREFIX"] = toolchain
            runcmd(
                [
                    ctng,
                    "build",
                ],
                env=env,
            )


if __name__ == "__main__":
    from argparse import ArgumentParser

    main(ArgumentParser())
