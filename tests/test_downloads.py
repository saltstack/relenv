# Copyright 2022-2024 VMware, Inc.
# SPDX-License-Identifier: Apache-2
import pathlib
import subprocess
import sys
from unittest.mock import patch

from relenv.build.common import Download
from relenv.common import RelenvException


def test_download_url():
    download = Download(
        "test", "https://test.com/{version}/test-{version}.tar.xz", version="1.0.0"
    )
    assert download.url == "https://test.com/1.0.0/test-1.0.0.tar.xz"


def test_download_url_change_version():
    download = Download(
        "test", "https://test.com/{version}/test-{version}.tar.xz", version="1.0.0"
    )
    download.version = "1.2.2"
    assert download.url == "https://test.com/1.2.2/test-1.2.2.tar.xz"


def test_download_filepath():
    download = Download(
        "test",
        "https://test.com/{version}/test-{version}.tar.xz",
        version="1.0.0",
        destination="/tmp",
    )
    assert isinstance(download.filepath, pathlib.Path)
    if sys.platform.startswith("win"):
        assert str(download.filepath) == "\\tmp\\test-1.0.0.tar.xz"
    else:
        assert str(download.filepath) == "/tmp/test-1.0.0.tar.xz"


def test_download_filepath_change_destination():
    download = Download(
        "test",
        "https://test.com/{version}/test-{version}.tar.xz",
        version="1.0.0",
        destination="/tmp",
    )
    download.destination = "/tmp/foo"
    assert isinstance(download.filepath, pathlib.Path)
    if sys.platform.startswith("win"):
        assert str(download.filepath) == "\\tmp\\foo\\test-1.0.0.tar.xz"
    else:
        assert str(download.filepath) == "/tmp/foo/test-1.0.0.tar.xz"


def test_download_exists(tmp_path):
    download = Download(
        "test",
        "https://test.com/{version}/test-{version}.tar.xz",
        version="1.0.0",
        destination=tmp_path,
    )
    assert download.exists() is False
    (pathlib.Path(tmp_path) / "test-1.0.0.tar.xz").touch()
    assert download.exists() is True


def test_validate_md5sum(tmp_path):
    fake_md5 = "fakemd5"
    with patch("relenv.build.common.verify_checksum") as run_mock:
        assert Download.validate_checksum(str(tmp_path), fake_md5) is True
        run_mock.assert_called_with(str(tmp_path), fake_md5)


def test_validate_md5sum_failed(tmp_path):
    fake_md5 = "fakemd5"
    with patch(
        "relenv.build.common.verify_checksum", side_effect=RelenvException
    ) as run_mock:
        assert Download.validate_checksum(str(tmp_path), fake_md5) is False
        run_mock.assert_called_with(str(tmp_path), fake_md5)


def test_validate_signature(tmp_path):
    sig = "fakesig"
    with patch("relenv.build.common.runcmd") as run_mock:
        assert Download.validate_signature(str(tmp_path), sig) is True
        run_mock.assert_called_with(
            ["gpg", "--verify", sig, str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def test_validate_signature_failed(tmp_path):
    sig = "fakesig"
    with patch("relenv.build.common.runcmd", side_effect=RelenvException) as run_mock:
        assert Download.validate_signature(str(tmp_path), sig) is False
        run_mock.assert_called_with(
            ["gpg", "--verify", sig, str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
