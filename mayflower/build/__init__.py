import sys


def setup_parser(subparsers):
    build_subparser = subparsers.add_parser(
        "build", description="Build Mayflower Python Environments from source"
    )
    build_subparser.set_defaults(func=main)

    build_subparser.add_argument(
        "--arch",
        default="x86_64",
        choices=["x86_64", "aarch64"],
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
        "--no-download",
        default=False,
        action="store_true",
        help="Skip downloading source tarballs",
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


def main(argparse):
    if sys.platform == "darwin":
        from .darwin import main

        main(argparse)
    elif sys.platform == "linux":
        from .linux import main

        main(argparse)
    elif sys.platform == "win32":
        from .windows import main

        main(argparse)
    else:
        print("Unsupported platform")
        sys.exit(1)
