import hashlib
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

from mayflower.build.common import Download


@pytest.fixture
def fake_download(tmp_path):
    download = tmp_path / "fake_download"
    download.write_text("This is some file contents")
    return download


@pytest.fixture
def fake_download_md5(fake_download):
    return hashlib.md5(fake_download.read_bytes()).hexdigest()


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
    assert download.exists() == False
    (pathlib.Path(tmp_path) / "test-1.0.0.tar.xz").touch()
    assert download.exists() == True


def test_validate_md5sum(fake_download, fake_download_md5):
    assert Download.validate_md5sum(str(fake_download), fake_download_md5) is True


def test_validate_md5sum_failed(fake_download):
    assert Download.validate_md5sum(str(fake_download), "fake_download_md5") is False


def test_validate_signature(fake_download):
    sig = "fakesig"
    with patch("mayflower.build.common.runcmd") as run_mock:
        assert Download.validate_signature(str(fake_download), sig) is True
        run_mock.assert_called_with(
            ["gpg", "--verify", sig, str(fake_download)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
