# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Tests for SBOM (Software Bill of Materials) functionality.
"""
from __future__ import annotations

import json
import pathlib
from unittest import mock

import pytest

from relenv import sbom


def test_find_relenv_root_from_root(tmp_path: pathlib.Path) -> None:
    """Test finding relenv root when starting at root directory."""
    # Create a fake relenv environment structure
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    python_exe = bin_dir / "python3"
    python_exe.touch()

    # Should find the root
    root = sbom.find_relenv_root(tmp_path)
    assert root == tmp_path


def test_find_relenv_root_from_subdir(tmp_path: pathlib.Path) -> None:
    """Test finding relenv root when starting from subdirectory."""
    # Create a fake relenv environment structure
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    python_exe = bin_dir / "python3"
    python_exe.touch()

    # Should find the root from bin directory
    root = sbom.find_relenv_root(bin_dir)
    assert root == tmp_path


def test_find_relenv_root_not_found(tmp_path: pathlib.Path) -> None:
    """Test finding relenv root when not in a relenv environment."""
    # Empty directory - should raise
    with pytest.raises(FileNotFoundError, match="Not a relenv environment"):
        sbom.find_relenv_root(tmp_path)


def test_get_python_version(tmp_path: pathlib.Path) -> None:
    """Test getting Python version from a relenv environment."""
    # Create fake Python executable
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    python_exe = bin_dir / "python3"
    python_exe.write_text("#!/bin/bash\necho '3.12.1'")
    python_exe.chmod(0o755)

    # Mock subprocess to return version
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "3.12.1\n"

        version = sbom.get_python_version(tmp_path)
        assert version == (3, 12, 1)


def test_get_python_version_not_found(tmp_path: pathlib.Path) -> None:
    """Test getting Python version when python3 doesn't exist."""
    version = sbom.get_python_version(tmp_path)
    assert version is None


def test_scan_installed_packages_empty(tmp_path: pathlib.Path) -> None:
    """Test scanning packages when none are installed."""
    packages = sbom.scan_installed_packages(tmp_path)
    assert packages == []


def test_scan_installed_packages(tmp_path: pathlib.Path) -> None:
    """Test scanning installed packages from dist-info directories."""
    # Create fake site-packages with dist-info
    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)

    # Create some fake dist-info directories
    (site_packages / "pip-23.0.1.dist-info").mkdir()
    (site_packages / "setuptools-68.0.0.dist-info").mkdir()
    (site_packages / "relenv-0.21.2.dist-info").mkdir()
    (site_packages / "cowsay-5.0.dist-info").mkdir()

    # Scan packages
    packages = sbom.scan_installed_packages(tmp_path)

    # Should find all 4 packages
    assert len(packages) == 4

    # Check structure of first package
    pip_pkg = next(p for p in packages if p["name"] == "pip")
    assert pip_pkg["SPDXID"] == "SPDXRef-PACKAGE-python-pip"
    assert pip_pkg["name"] == "pip"
    assert pip_pkg["versionInfo"] == "23.0.1"
    assert pip_pkg["downloadLocation"] == "NOASSERTION"
    assert pip_pkg["primaryPackagePurpose"] == "LIBRARY"
    assert pip_pkg["licenseConcluded"] == "NOASSERTION"
    assert pip_pkg["comment"] == "Python package installed via pip"

    # Check all packages are present
    pkg_names = {p["name"] for p in packages}
    assert pkg_names == {"pip", "setuptools", "relenv", "cowsay"}


def test_update_sbom_create_new(tmp_path: pathlib.Path) -> None:
    """Test creating a new SBOM when none exists."""
    # Create fake relenv environment
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").touch()

    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "pip-23.0.1.dist-info").mkdir()
    (site_packages / "relenv-0.21.2.dist-info").mkdir()

    # Mock Python version to be 3.12
    with mock.patch("relenv.sbom.get_python_version", return_value=(3, 12, 1)):
        # Update SBOM (should create new one)
        sbom.update_sbom(tmp_path)

    # Verify SBOM was created
    sbom_path = tmp_path / "relenv-sbom.spdx.json"
    assert sbom_path.exists()

    # Load and verify structure
    with open(sbom_path) as f:
        sbom_data = json.load(f)

    assert sbom_data["SPDXID"] == "SPDXRef-DOCUMENT"
    assert sbom_data["spdxVersion"] == "SPDX-2.3"
    assert sbom_data["dataLicense"] == "CC0-1.0"
    assert "creationInfo" in sbom_data
    assert "created" in sbom_data["creationInfo"]
    assert len(sbom_data["creationInfo"]["creators"]) == 1
    assert sbom_data["creationInfo"]["creators"][0].startswith("Tool: relenv-")

    # Should have 2 Python packages
    packages = sbom_data["packages"]
    assert len(packages) == 2
    pkg_names = {p["name"] for p in packages}
    assert pkg_names == {"pip", "relenv"}


def test_update_sbom_preserve_build_deps(tmp_path: pathlib.Path) -> None:
    """Test that updating SBOM preserves build dependencies."""
    # Create fake relenv environment
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").touch()

    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "pip-23.0.1.dist-info").mkdir()

    # Mock Python version
    with mock.patch("relenv.sbom.get_python_version", return_value=(3, 12, 1)):
        # Create initial SBOM with build deps
        sbom_path = tmp_path / "relenv-sbom.spdx.json"
        initial_sbom = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "spdxVersion": "SPDX-2.3",
            "name": "relenv-test",
            "dataLicense": "CC0-1.0",
            "creationInfo": {
                "created": "2025-01-01T00:00:00Z",
                "creators": ["Tool: relenv-0.21.0"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-PACKAGE-openssl",
                    "name": "openssl",
                    "versionInfo": "3.6.0",
                    "downloadLocation": "https://example.com/openssl.tar.gz",
                    "primaryPackagePurpose": "SOURCE",
                    "licenseConcluded": "NOASSERTION",
                },
                {
                    "SPDXID": "SPDXRef-PACKAGE-sqlite",
                    "name": "sqlite",
                    "versionInfo": "3.50.4.0",
                    "downloadLocation": "https://example.com/sqlite.tar.gz",
                    "primaryPackagePurpose": "SOURCE",
                    "licenseConcluded": "NOASSERTION",
                },
                {
                    "SPDXID": "SPDXRef-PACKAGE-python-wheel",
                    "name": "wheel",
                    "versionInfo": "0.42.0",
                    "downloadLocation": "NOASSERTION",
                    "primaryPackagePurpose": "LIBRARY",
                    "licenseConcluded": "NOASSERTION",
                    "comment": "Python package installed via pip",
                },
            ],
        }

        with open(sbom_path, "w") as f:
            json.dump(initial_sbom, f, indent=2)

        # Update SBOM (should preserve build deps, update Python packages)
        sbom.update_sbom(tmp_path)

    # Load and verify
    with open(sbom_path) as f:
        updated_sbom = json.load(f)

    packages = updated_sbom["packages"]

    # Should have 2 build deps + 1 new Python package
    assert len(packages) == 3

    # Build deps should be preserved
    openssl = next((p for p in packages if p["name"] == "openssl"), None)
    assert openssl is not None
    assert openssl["versionInfo"] == "3.6.0"

    sqlite = next((p for p in packages if p["name"] == "sqlite"), None)
    assert sqlite is not None
    assert sqlite["versionInfo"] == "3.50.4.0"

    # Old wheel package should be removed, new pip package should be present
    pip_pkg = next((p for p in packages if p["name"] == "pip"), None)
    assert pip_pkg is not None
    assert pip_pkg["versionInfo"] == "23.0.1"

    wheel = next((p for p in packages if p["name"] == "wheel"), None)
    assert wheel is None


def test_update_sbom_replaces_python_packages(tmp_path: pathlib.Path) -> None:
    """Test that updating SBOM replaces Python packages with current scan."""
    # Create fake relenv environment
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").touch()

    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)

    # Mock Python version
    with mock.patch("relenv.sbom.get_python_version", return_value=(3, 12, 1)):
        # Initially install pip and cowsay
        (site_packages / "pip-23.0.1.dist-info").mkdir()
        (site_packages / "cowsay-5.0.dist-info").mkdir()

        # First update
        sbom.update_sbom(tmp_path)

        # Verify initial state
        sbom_path = tmp_path / "relenv-sbom.spdx.json"
        with open(sbom_path) as f:
            sbom_data = json.load(f)
        assert len(sbom_data["packages"]) == 2
        pkg_names = {p["name"] for p in sbom_data["packages"]}
        assert pkg_names == {"pip", "cowsay"}

        # Now "uninstall" cowsay and "install" relenv
        (site_packages / "cowsay-5.0.dist-info").rmdir()
        (site_packages / "relenv-0.21.2.dist-info").mkdir()

        # Second update
        sbom.update_sbom(tmp_path)

        # Verify updated state
        with open(sbom_path) as f:
            sbom_data = json.load(f)
        assert len(sbom_data["packages"]) == 2
        pkg_names = {p["name"] for p in sbom_data["packages"]}
        assert pkg_names == {"pip", "relenv"}


def test_update_sbom_python_version_too_old(tmp_path: pathlib.Path) -> None:
    """Test that update_sbom fails gracefully for Python < 3.12."""
    # Create fake relenv environment
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").touch()

    # Mock Python version to be 3.10
    with mock.patch("relenv.sbom.get_python_version", return_value=(3, 10, 18)):
        with pytest.raises(
            RuntimeError, match="SBOM generation is only supported for Python 3.12+"
        ):
            sbom.update_sbom(tmp_path)


def test_main_success(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    """Test main() with valid relenv environment."""
    # Create fake relenv environment
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python3").touch()

    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "pip-23.0.1.dist-info").mkdir()

    # Create args
    import argparse

    args = argparse.Namespace(path=str(tmp_path))

    # Mock Python version
    with mock.patch("relenv.sbom.get_python_version", return_value=(3, 12, 1)):
        # Run main
        result = sbom.main(args)
        assert result == 0

    # Check output
    captured = capsys.readouterr()
    assert "Found relenv environment at:" in captured.out
    assert "Updated" in captured.out
    assert "relenv-sbom.spdx.json" in captured.out


def test_main_not_relenv(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    """Test main() with non-relenv directory."""
    # Empty directory
    import argparse

    args = argparse.Namespace(path=str(tmp_path))

    # Run main
    result = sbom.main(args)
    assert result == 1

    # Check error output
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "Not a relenv environment" in captured.err
