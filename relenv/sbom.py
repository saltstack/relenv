# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
SBOM (Software Bill of Materials) management for relenv.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


def get_python_version(relenv_root: pathlib.Path) -> Optional[Tuple[int, int, int]]:
    """
    Get the Python version of a relenv environment.

    :param relenv_root: Path to relenv environment root
    :return: Tuple of (major, minor, micro) version numbers, or None if cannot determine
    """
    python_exe = relenv_root / "bin" / "python3"
    if not python_exe.exists():
        python_exe = relenv_root / "bin" / "python3.exe"

    if not python_exe.exists():
        return None

    try:
        import subprocess

        result = subprocess.run(
            [
                str(python_exe),
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version_str = result.stdout.strip()
            parts = version_str.split(".")
            if len(parts) >= 3:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        pass

    return None


def find_relenv_root(start_path: pathlib.Path) -> pathlib.Path:
    """
    Find the root of a relenv environment.

    Looks for indicators like bin/python3 and relenv-sbom.spdx.json or sbom.spdx.json.

    :param start_path: Starting path to search from
    :return: Path to relenv root
    :raises FileNotFoundError: If not a relenv environment
    """
    # Normalize the path
    path = start_path.resolve()

    # Check if we're already at the root
    if (path / "bin" / "python3").exists() or (path / "bin" / "python3.exe").exists():
        return path

    # Check if we're inside a relenv environment (e.g., in bin/)
    if (path.parent / "bin" / "python3").exists():
        return path.parent

    # Not a relenv environment
    raise FileNotFoundError(
        f"Not a relenv environment: {start_path}\n"
        f"Expected to find bin/python3 or bin/python3.exe"
    )


def scan_installed_packages(relenv_root: pathlib.Path) -> List[Dict[str, Any]]:
    """
    Scan for installed Python packages in a relenv environment.

    :param relenv_root: Path to relenv environment root
    :return: List of package dicts with SPDX metadata
    """
    packages: List[Dict[str, Any]] = []

    # Find the Python site-packages directory
    lib_dir = relenv_root / "lib"
    if not lib_dir.exists():
        return packages

    # Scan for .dist-info directories
    for entry in lib_dir.glob("python*/site-packages/*.dist-info"):
        # Parse package name and version from dist-info directory
        # Format: package-version.dist-info
        dist_name = entry.name.replace(".dist-info", "")
        if "-" in dist_name:
            parts = dist_name.rsplit("-", 1)
            if len(parts) == 2:
                pkg_name, pkg_version = parts
                package: Dict[str, Any] = {
                    "SPDXID": f"SPDXRef-PACKAGE-python-{pkg_name}",
                    "name": pkg_name,
                    "versionInfo": pkg_version,
                    "downloadLocation": "NOASSERTION",
                    "primaryPackagePurpose": "LIBRARY",
                    "licenseConcluded": "NOASSERTION",
                    "comment": "Python package installed via pip",
                }
                packages.append(package)

    return packages


def update_sbom(relenv_root: pathlib.Path) -> None:
    """
    Update relenv-sbom.spdx.json with currently installed packages.

    This updates only the Python packages section, preserving the build
    dependencies section from the original SBOM.

    Only works for Python 3.12+ environments (when Python started including SBOM files).

    :param relenv_root: Path to relenv environment root
    :raises RuntimeError: If Python version is less than 3.12
    """
    import relenv

    # Check Python version
    py_version = get_python_version(relenv_root)
    if py_version is None:
        raise RuntimeError(f"Could not determine Python version for {relenv_root}")

    major, minor, micro = py_version
    if major < 3 or (major == 3 and minor < 12):
        raise RuntimeError(
            f"SBOM generation is only supported for Python 3.12+. "
            f"This environment is Python {major}.{minor}.{micro}"
        )

    sbom_path = relenv_root / "relenv-sbom.spdx.json"

    # Load existing SBOM if it exists
    if sbom_path.exists():
        with open(sbom_path, "r") as f:
            sbom = json.load(f)
    else:
        # Create new SBOM if it doesn't exist
        sbom = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "name": f"relenv-{relenv_root.name}",
            "dataLicense": "CC0-1.0",
            "creationInfo": {
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "creators": [f"Tool: relenv-{relenv.__version__}"],
            },
            "packages": [],
        }

    # Separate build dependencies from Python packages
    build_deps = [
        pkg
        for pkg in sbom.get("packages", [])
        if not pkg.get("SPDXID", "").startswith("SPDXRef-PACKAGE-python-")
    ]

    # Scan for currently installed packages
    python_packages = scan_installed_packages(relenv_root)

    # Combine build deps + current Python packages
    sbom["packages"] = build_deps + python_packages

    # Update creation time
    if "creationInfo" not in sbom:
        sbom["creationInfo"] = {}
    sbom["creationInfo"]["created"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sbom["creationInfo"]["creators"] = [f"Tool: relenv-{relenv.__version__}"]

    # Write updated SBOM
    with open(sbom_path, "w") as f:
        json.dump(sbom, f, indent=2)

    print(f"Updated {sbom_path}")
    print(f"  Build dependencies: {len(build_deps)}")
    print(f"  Python packages: {len(python_packages)}")


def setup_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """
    Setup argument parser for sbom-update command.

    :param subparsers: Subparser action from argparse
    """
    parser = subparsers.add_parser(
        "sbom-update",
        description="Update relenv-sbom.spdx.json with currently installed packages",
        help="Update SBOM with installed packages",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to relenv environment (default: current directory)",
    )
    parser.set_defaults(func=main)


def main(args: argparse.Namespace) -> int:
    """
    Main entry point for sbom-update command.

    :param args: Parsed command-line arguments
    :return: Exit code (0 for success, 1 for error)
    """
    try:
        # Find the relenv root
        start_path = pathlib.Path(args.path)
        relenv_root = find_relenv_root(start_path)

        print(f"Found relenv environment at: {relenv_root}")

        # Update the SBOM
        update_sbom(relenv_root)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error updating SBOM: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
