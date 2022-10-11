import os
import pathlib
import sys

from .common import (
    MODULE_DIR,
    download_url,
    extract_archive,
    get_toolchain,
    runcmd,
    work_dirs,
    work_root,
)

WORK_IN_CWD = False
CT_NG_VER = "1.25.0"
CT_URL = "http://crosstool-ng.org/download/crosstool-ng/crosstool-ng-{version}.tar.bz2"

# XXX This should be triplet not arch
TC_URL = "https://woz.io/mayflower/{version}/toolchain/{arch}-linux-gnu.tar.xz"


def main(args):
    args.arch = [_.strip() for _ in args.arch.split(",")]
    toolchain = get_toolchain()
    if not toolchain.exists():
        os.makedirs(toolchain)
    if args.command == "download":
        for arch in args.arch:
            archdir = get_toolchain(arch)
            if args.clean:
                shutil.rmtree(archdir)
            if archdir.exists():
                print("Toolchain directory exists, skipping {}".format(arch))
            url = TC_URL.format(version="0.0.0", arch=arch)
            print("Downloading {}".format(url))
            archive = download_url(url, toolchain)
            extract_archive(toolchain, archive)
        sys.exit(0)
    elif args.command == "build":
        ctngdir = toolchain / "crosstool-ng-{}".format(CT_NG_VER)
        if not ctngdir.exists():
            url = CT_URL.format(version=CT_NG_VER)
            archive = download_url(url, toolchain)
            extract_archive(toolchain, archive)
            os.chdir(ctngdir)
            runcmd(["./configure", "--enable-local"])
            runcmd(["make"])
            os.chdir(toolchain)
        if args.crosstool_only:
            sys.exit(0)

        ctng = ctngdir / "ct-ng"
        for arch in args.arch:
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
