# Copyright 2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
import hashlib
import subprocess

from relenv import pyversions


def test_python_versions_returns_versions():
    versions = pyversions.python_versions()
    assert versions, "python_versions() should return known versions"
    first_version = next(iter(versions))
    assert isinstance(first_version, pyversions.Version)
    assert isinstance(versions[first_version], str)


def test_python_versions_filters_minor():
    versions = pyversions.python_versions("3.11")
    assert versions
    assert all(version.major == 3 and version.minor == 11 for version in versions)
    sorted_versions = sorted(versions)
    assert sorted_versions[-1] in versions


def test_release_urls_handles_old_versions():
    tarball, signature = pyversions._release_urls(pyversions.Version("3.1.3"))
    assert tarball.endswith(".tar.xz")
    assert signature is not None


def test_release_urls_no_signature_before_23():
    tarball, signature = pyversions._release_urls(pyversions.Version("2.2.3"))
    assert tarball.endswith(".tar.xz")
    assert signature is None


def test_ref_version_and_path_helpers():
    html = '<a href="download/Python-3.11.9.tgz">Python 3.11.9</a>'
    version = pyversions._ref_version(html)
    assert str(version) == "3.11.9"
    assert pyversions._ref_path(html) == "download/Python-3.11.9.tgz"


def test_digest(tmp_path):
    file = tmp_path / "data.bin"
    file.write_bytes(b"abc")
    assert pyversions.digest(file) == hashlib.sha1(b"abc").hexdigest()


def test_get_keyid_parses_second_line():
    proc = subprocess.CompletedProcess(
        ["gpg"],
        1,
        stdout=b"",
        stderr=b"gpg: error\n[GNUPG:] INV_SGNR 0 CB1234\n",
    )
    assert pyversions._get_keyid(proc) == "CB1234"


def test_verify_signature_success(monkeypatch, tmp_path):
    called = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pyversions.subprocess, "run", fake_run)
    assert pyversions.verify_signature("archive.tgz", "archive.tgz.asc") is True
    assert called["cmd"][0] == "gpg"


def test_verify_signature_failure_with_missing_key(monkeypatch):
    responses = []

    def fake_run(cmd, **kwargs):
        if len(responses) == 0:
            responses.append("first")
            stderr = b"gpg: error\n[GNUPG:] INV_SGNR 0 ABCDEF12\nNo public key\n"
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=stderr)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pyversions.subprocess, "run", fake_run)
    monkeypatch.setattr(pyversions, "_receive_key", lambda keyid, server: True)
    assert pyversions.verify_signature("archive.tgz", "archive.tgz.asc") is True
