# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
The ``relenv create`` command.
"""

import contextlib
import os
import pathlib
import sys
import tarfile

from .common import RelenvException, arches, archived_build, build_arch


@contextlib.contextmanager
def chdir(path):
    """
    Context manager that changes to the specified directory and back.

    :param path: The path to temporarily change to
    :type path: str
    """
    cwd = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


class CreateException(RelenvException):
    """
    Raised when there is an issue creating a new relenv environment.
    """


def setup_parser(subparsers):
    """
    Setup the subparser for the ``create`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    create_subparser = subparsers.add_parser(
        "create",
        description=(
            "Create a Relenv environment. This will create a directory of the given "
            "name with newly created Relenv environment.",
        ),
    )
    create_subparser.set_defaults(func=main)
    create_subparser.add_argument("name", help="The name of the directory to create")
    create_subparser.add_argument(
        "--arch",
        default=build_arch(),
        choices=arches[sys.platform],
        type=str,
        help="The host architecture [default: %(default)s]",
    )


def create(name, dest=None, arch=None):
    """
    Create a relenv environment.

    :param name: The name of the environment
    :type name: str
    :param dest: The path the environment should be created under
    :type dest: str
    :param arch: The architecture to create the environment for
    :type arch: str

    :raises CreateException: If there is a problem in creating the relenv environment
    """
    if arch is None:
        arch = build_arch()
    if dest:
        writeto = pathlib.Path(dest) / name
    else:
        writeto = pathlib.Path(name).resolve()

    if pathlib.Path(writeto).exists():
        raise CreateException("The requested path already exists.")

    plat = sys.platform

    if plat == "linux":
        if arch in arches[plat]:
            triplet = "{}-{}-gnu".format(arch, plat)
        else:
            raise CreateException("Unknown arch")
    elif plat == "darwin":
        if arch in arches[plat]:
            triplet = "{}-macos".format(arch)
        else:
            raise CreateException("Unknown arch")
    elif plat == "win32":
        if arch in arches[plat]:
            triplet = "{}-win".format(arch)
        else:
            raise CreateException("Unknown arch")
    else:
        raise CreateException("Unknown platform")

    tar = archived_build(triplet)
    if not tar.exists():
        raise CreateException(
            f"Error, build archive for {arch} doesn't exist: {tar}\n"
            "You might try relenv fetch to resolve this."
        )
    with tarfile.open(tar, "r:xz") as fp:
        for f in fp:
            fp.extract(f, writeto)


def main(args):
    """
    The entrypoint into the ``relenv create`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    name = args.name
    try:
        create(name, arch=args.arch)
    except CreateException as exc:
        print(exc)
        sys.exit(1)
