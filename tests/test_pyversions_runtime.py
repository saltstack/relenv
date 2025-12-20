# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
from __future__ import annotations

import hashlib
import pathlib
import subprocess
from typing import Any, Dict, Sequence

import pytest

from relenv import pyversions


def test_python_versions_returns_versions() -> None:
    versions: Dict[pyversions.Version, str] = pyversions.python_versions()
    assert versions, "python_versions() should return known versions"
    first_version = next(iter(versions))
    assert isinstance(first_version, pyversions.Version)
    assert isinstance(versions[first_version], str)


def test_python_versions_filters_minor() -> None:
    versions = pyversions.python_versions("3.11")
    assert versions
    assert all(version.major == 3 and version.minor == 11 for version in versions)
    sorted_versions = sorted(versions)
    assert sorted_versions[-1] in versions


def test_release_urls_handles_old_versions() -> None:
    tarball, signature = pyversions._release_urls(pyversions.Version("3.1.3"))
    assert tarball.endswith(".tar.xz")
    assert signature is not None


def test_release_urls_no_signature_before_23() -> None:
    tarball, signature = pyversions._release_urls(pyversions.Version("2.2.3"))
    assert tarball.endswith(".tar.xz")
    assert signature is None


def test_ref_version_and_path_helpers() -> None:
    html = '<a href="download/Python-3.11.9.tgz">Python 3.11.9</a>'
    version = pyversions._ref_version(html)
    assert str(version) == "3.11.9"
    assert pyversions._ref_path(html) == "download/Python-3.11.9.tgz"


def test_digest(tmp_path: pathlib.Path) -> None:
    file = tmp_path / "data.bin"
    file.write_bytes(b"abc")
    assert pyversions.digest(file) == hashlib.sha1(b"abc").hexdigest()


def test_get_keyid_parses_second_line() -> None:
    proc = subprocess.CompletedProcess(
        ["gpg"],
        1,
        stdout=b"",
        stderr=b"gpg: error\n[GNUPG:] INV_SGNR 0 CB1234\n",
    )
    assert pyversions._get_keyid(proc) == "CB1234"


def test_verify_signature_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    called: Dict[str, list[str]] = {}

    def fake_run(
        cmd: Sequence[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        called.setdefault("cmd", []).extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pyversions.subprocess, "run", fake_run)
    assert pyversions.verify_signature("archive.tgz", "archive.tgz.asc") is True
    assert called["cmd"][0] == "gpg"


def test_verify_signature_failure_with_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: list[str] = []

    def fake_run(
        cmd: Sequence[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        if len(responses) == 0:
            responses.append("first")
            stderr = b"gpg: error\n[GNUPG:] INV_SGNR 0 ABCDEF12\nNo public key\n"
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=stderr)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pyversions.subprocess, "run", fake_run)
    monkeypatch.setattr(pyversions, "_receive_key", lambda keyid, server: True)
    assert pyversions.verify_signature("archive.tgz", "archive.tgz.asc") is True


def test_sha256_digest(tmp_path: pathlib.Path) -> None:
    """Test SHA-256 digest computation."""
    file = tmp_path / "data.bin"
    file.write_bytes(b"test data")
    assert pyversions.sha256_digest(file) == hashlib.sha256(b"test data").hexdigest()


def test_detect_openssl_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test OpenSSL version detection from GitHub releases."""
    mock_html = """
    <html>
    <a href="/openssl/openssl/releases/tag/openssl-3.5.4">openssl-3.5.4</a>
    <a href="/openssl/openssl/releases/tag/openssl-3.5.3">openssl-3.5.3</a>
    <a href="/openssl/openssl/releases/tag/openssl-3.4.0">openssl-3.4.0</a>
    </html>
    """

    def fake_fetch(url: str) -> str:
        return mock_html

    monkeypatch.setattr(pyversions, "fetch_url_content", fake_fetch)
    versions = pyversions.detect_openssl_versions()
    assert isinstance(versions, list)
    assert "3.5.4" in versions
    assert "3.5.3" in versions
    assert "3.4.0" in versions
    # Verify sorting (latest first)
    assert versions[0] == "3.5.4"


def test_detect_sqlite_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test SQLite version detection from sqlite.org."""
    mock_html = """
    <html>
    <a href="2024/sqlite-autoconf-3500400.tar.gz">sqlite-autoconf-3500400.tar.gz</a>
    <a href="2024/sqlite-autoconf-3500300.tar.gz">sqlite-autoconf-3500300.tar.gz</a>
    </html>
    """

    def fake_fetch(url: str) -> str:
        return mock_html

    monkeypatch.setattr(pyversions, "fetch_url_content", fake_fetch)
    versions = pyversions.detect_sqlite_versions()
    assert isinstance(versions, list)
    # Should return list of tuples (version, sqliteversion)
    assert len(versions) > 0
    assert isinstance(versions[0], tuple)
    assert len(versions[0]) == 2
    # Check that conversion worked
    version, sqlite_ver = versions[0]
    assert version == "3.50.4.0"
    assert sqlite_ver == "3500400"


def test_detect_xz_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test XZ version detection from tukaani.org."""
    mock_html = """
    <html>
    <a href="xz-5.8.1.tar.gz">xz-5.8.1.tar.gz</a>
    <a href="xz-5.8.0.tar.gz">xz-5.8.0.tar.gz</a>
    <a href="xz-5.6.3.tar.gz">xz-5.6.3.tar.gz</a>
    </html>
    """

    def fake_fetch(url: str) -> str:
        return mock_html

    monkeypatch.setattr(pyversions, "fetch_url_content", fake_fetch)
    versions = pyversions.detect_xz_versions()
    assert isinstance(versions, list)
    assert "5.8.1" in versions
    assert "5.8.0" in versions
    assert "5.6.3" in versions
    # Verify sorting (latest first)
    assert versions[0] == "5.8.1"


def test_resolve_python_version_none_defaults_to_latest_310() -> None:
    """Test that None resolves to the latest 3.10 version."""
    result = pyversions.resolve_python_version(None)
    assert result.startswith("3.10.")
    # Verify it's a valid version in the registry
    versions = pyversions.python_versions("3.10")
    assert pyversions.Version(result) in versions
    # Verify it's the latest 3.10 version
    latest = sorted(list(versions.keys()))[-1]
    assert result == str(latest)


def test_resolve_python_version_partial_minor() -> None:
    """Test that partial versions (3.10) resolve to latest micro."""
    result = pyversions.resolve_python_version("3.10")
    assert result.startswith("3.10.")
    # Verify it resolves to the latest micro version
    versions = pyversions.python_versions("3.10")
    latest = sorted(list(versions.keys()))[-1]
    assert result == str(latest)


def test_resolve_python_version_different_minors() -> None:
    """Test resolution works for different minor versions."""
    result_311 = pyversions.resolve_python_version("3.11")
    assert result_311.startswith("3.11.")

    result_313 = pyversions.resolve_python_version("3.13")
    assert result_313.startswith("3.13.")

    # Verify they're different
    assert result_311 != result_313

    # Verify each is the latest for its minor version
    versions_311 = pyversions.python_versions("3.11")
    latest_311 = sorted(list(versions_311.keys()))[-1]
    assert result_311 == str(latest_311)

    versions_313 = pyversions.python_versions("3.13")
    latest_313 = sorted(list(versions_313.keys()))[-1]
    assert result_313 == str(latest_313)


def test_resolve_python_version_full_version() -> None:
    """Test that full versions are validated and returned as-is."""
    # Get any valid version from the registry
    all_versions = pyversions.python_versions()
    some_version = str(next(iter(all_versions)))

    result = pyversions.resolve_python_version(some_version)
    assert result == some_version


def test_resolve_python_version_invalid_full_version() -> None:
    """Test that invalid full versions raise RuntimeError."""
    with pytest.raises(RuntimeError, match="Unknown version"):
        pyversions.resolve_python_version("3.10.999")


def test_resolve_python_version_invalid_minor_version() -> None:
    """Test that invalid minor versions raise RuntimeError."""
    with pytest.raises(RuntimeError, match="Unknown minor version"):
        pyversions.resolve_python_version("3.99")


def test_resolve_python_version_consistency() -> None:
    """Test that resolve_python_version is idempotent for full versions."""
    # Get a valid full version from the registry
    all_versions = pyversions.python_versions()
    some_version = str(next(iter(all_versions)))

    # Resolving a full version twice should give the same result
    first = pyversions.resolve_python_version(some_version)
    second = pyversions.resolve_python_version(first)
    assert first == second
