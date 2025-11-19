# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
The ``relenv create`` command.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import pathlib
import shutil
import sys
import tarfile
from collections.abc import Iterator

from .common import (
    RelenvException,
    arches,
    archived_build,
    build_arch,
    format_shebang,
    relative_interpreter,
)
from .pyversions import Version, python_versions


@contextlib.contextmanager
def chdir(path: str | os.PathLike[str]) -> Iterator[None]:
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


def setup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """
    Setup the subparser for the ``create`` command.

    :param subparsers: The subparsers object returned from ``add_subparsers``
    :type subparsers: argparse._SubParsersAction
    """
    subparser = subparsers.add_parser(
        "create",
        description=(
            "Create a Relenv environment. This will create a directory of the given "
            "name with newly created Relenv environment."
        ),
    )
    subparser.set_defaults(func=main)
    subparser.add_argument("name", help="The name of the directory to create")
    subparser.add_argument(
        "--arch",
        default=build_arch(),
        choices=arches[sys.platform],
        type=str,
        help="The host architecture [default: %(default)s]",
    )
    subparser.add_argument(
        "--python",
        default="3.10.17",
        type=str,
        help="The python version [default: %(default)s]",
    )


def create(
    name: str,
    dest: str | os.PathLike[str] | None = None,
    arch: str | None = None,
    version: str | None = None,
) -> None:
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

    if version is None:
        version = "3.10.17"

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

    # XXX refactor
    tar = archived_build(f"{version}-{triplet}")
    if not tar.exists():
        raise CreateException(
            f"Error, build archive for {arch} doesn't exist: {tar}\n"
            "You might try relenv fetch to resolve this."
        )
    with tarfile.open(tar, "r:xz") as fp:
        for f in fp:
            fp.extract(f, writeto)
    _sync_relenv_package(writeto, version)
    _repair_script_shebangs(writeto, version)


def _site_packages_dir(root: pathlib.Path, version: str) -> pathlib.Path:
    """
    Return the site-packages directory within the created environment.
    """
    major_minor = ".".join(version.split(".")[:2])
    if sys.platform == "win32":
        return root / "Lib" / "site-packages"
    return root / "lib" / f"python{major_minor}" / "site-packages"


def _sync_relenv_package(root: pathlib.Path, version: str) -> None:
    """
    Ensure the relenv package within the created environment matches this CLI.
    """
    target_site = _site_packages_dir(root, version)
    if not target_site.exists():
        return
    target = target_site / "relenv"
    source = pathlib.Path(__file__).resolve().parent
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def _repair_script_shebangs(root: pathlib.Path, version: str) -> None:
    """
    Update legacy shell-wrapped entry points to the current shebang format.

    Older archives shipped scripts that started with the ``"true" ''''`` preamble.
    Those files break when executed directly under Python (the parser sees the
    unmatched triple-quoted literal). Patch any remaining copies to the new
    `format_shebang` layout so fresh installs do not inherit stale loaders.
    """
    if sys.platform == "win32":
        return

    scripts_dir = root / "bin"
    if not scripts_dir.is_dir():
        return

    major_minor = ".".join(version.split(".")[:2])
    interpreter_candidates = [
        scripts_dir / f"python{major_minor}",
        scripts_dir / f"python{major_minor.split('.')[0]}",
        scripts_dir / "python3",
        scripts_dir / "python",
    ]
    interpreter_path: pathlib.Path | None = None
    for candidate in interpreter_candidates:
        if candidate.exists():
            interpreter_path = candidate
            break
    if interpreter_path is None:
        return

    try:
        rel_interpreter = relative_interpreter(root, scripts_dir, interpreter_path)
    except ValueError:
        # Paths are not relative to the install root; abandon the rewrite.
        return

    try:
        shebang = format_shebang(str(pathlib.PurePosixPath("/") / rel_interpreter))
    except Exception:
        return

    legacy_prefix = "#!/bin/sh\n\"true\" ''''\n"
    marker = "\n'''"
    for script in scripts_dir.iterdir():
        if not script.is_file():
            continue
        try:
            text = script.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not text.startswith(legacy_prefix):
            continue
        idx = text.find(marker)
        if idx == -1:
            continue
        idy = idx + len(marker)
        rest = text[idy:]
        updated = shebang + rest.lstrip("\n")
        try:
            script.write_text(updated, encoding="utf-8")
        except OSError:
            continue


def main(args: argparse.Namespace) -> None:
    """
    The entrypoint into the ``relenv create`` command.

    :param args: The args passed to the command
    :type args: argparse.Namespace
    """
    name = args.name
    if args.arch != build_arch():
        print(
            "Warning: Cross compilation support is experimental and is not fully tested or working!"
        )

    # Resolve version (support minor version like "3.12" or full version like "3.12.7")
    requested = Version(args.python)

    if requested.micro:
        # Full version specified (e.g., "3.12.7")
        pyversions = python_versions()
        if requested not in pyversions:
            print(f"Unknown version {requested}")
            strversions = "\n".join([str(_) for _ in pyversions])
            print(f"Known versions are:\n{strversions}")
            sys.exit(1)
        create_version = requested
    else:
        # Minor version specified (e.g., "3.12"), resolve to latest
        pyversions = python_versions(args.python)
        if not pyversions:
            print(f"Unknown minor version {requested}")
            all_versions = python_versions()
            strversions = "\n".join([str(_) for _ in all_versions])
            print(f"Known versions are:\n{strversions}")
            sys.exit(1)
        create_version = sorted(list(pyversions.keys()))[-1]

    try:
        create(name, arch=args.arch, version=str(create_version))
    except CreateException as exc:
        print(exc)
        sys.exit(1)
