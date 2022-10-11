import argparse
import sys
from argparse import RawTextHelpFormatter

from . import build, create, fetch, toolchain


class ArgParser(argparse.ArgumentParser):
    """
    Wrap default ArgParser implementation adding the ability to suppress
    a positional argument from the example command output by the
    print_help method.
    """

    def __init__(self, *args, **kwargs):
        # if "formatter_class" not in kwargs:
        #     kwargs["formatter_class"] = RawTextHelpFormatter
        super(ArgParser, self).__init__(*args, **kwargs)
        self._errors = []

    def error(self, err):
        self._errors.append(err)

    # def supress_positional(self, dest):
    #     for i in self._positionals._group_actions:
    #         if i.dest == dest:
    #             i.help = argparse.SUPPRESS


# Build the argparser with its subparsers
argparser = ArgParser(
    description="Mayflower",
)


def foo(args):
    print(args)


subparsers = argparser.add_subparsers()

build_subparser = subparsers.add_parser(
    "build", description="Build Mayflower Python Environments from source"
)
build_subparser.set_defaults(_func=build.main)

build_subparser.add_argument(
    "--arch",
    default="x86_64",
    type=str,
    help="The host architecture [default: x86_64]",
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
    "--steps",
    default=None,
    help=(
        "Comman separated list of steps to run. When this option is used to "
        "invoke builds, depenencies of the steps are ignored.  This option "
        "should be used with care, as it's easy to request a situation that "
        "has no chance of being succesful. "
    ),
)

toolchain_subparser = subparsers.add_parser(
    "toolchain", description="Build Linux Toolchains"
)
toolchain_subparser.set_defaults(_func=toolchain.main)

toolchain_subparser.add_argument(
    "command",
    default="download",
    help="What type of toolchain operation to perform: build or download",
)
toolchain_subparser.add_argument(
    "--arch",
    default="x86_64,aarch64",
    help="Comma separated list of arches to build or download",
)
toolchain_subparser.add_argument(
    "--clean",
    default=False,
    action="store_true",
    help="Comma separated list of arches to build or download",
)
toolchain_subparser.add_argument(
    "--crosstool-only",
    default=False,
    action="store_true",
    help="When building only build Crosstool NG. Do not build toolchains",
)

create_subparser = subparsers.add_parser(
    "create",
    description="Create a Mayflower environment. This will create a directory of the given name with newly created Mayflower environment.",
)
create_subparser.set_defaults(_func=create.main)

create_subparser.add_argument("name", help="The name of the directory to create")
create_subparser.add_argument(
    "--arch",
    default="x86_64",
    type=str,
    help="The host architecture [default: x86_64]",
)

fetch_subparser = subparsers.add_parser("fetch", description="Fetch mayflower builds")
fetch_subparser.set_defaults(_func=fetch.main)

fetch_subparser.add_argument(
    "--arch", default="x86_64", help="Architecture to download"
)


def main():
    mayflower_args, argv = argparser.parse_known_args()
    mayflower_args._func(mayflower_args)


if __name__ == "__main__":
    main()
