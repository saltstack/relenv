import pathlib
import sys

import pytest

from mayflower.build.common import Download


def test_download_url():
    download = Download('test', 'https://test.com/{version}/test-{version}.tar.xz', version="1.0.0")
    assert download.url == "https://test.com/1.0.0/test-1.0.0.tar.xz"

def test_download_url_change_vesion():
    download = Download('test', 'https://test.com/{version}/test-{version}.tar.xz', version="1.0.0")
    download.version = "1.2.2"
    assert download.url == "https://test.com/1.2.2/test-1.2.2.tar.xz"

def test_download_filepath():
    download = Download('test', 'https://test.com/{version}/test-{version}.tar.xz', version="1.0.0", destination="/tmp")
    assert isinstance(download.filepath, pathlib.Path)
    if sys.platform.startswith("win"):
        assert str(download.filepath) == "\\tmp\\test-1.0.0.tar.xz"
    else:
        assert str(download.filepath) == "/tmp/test-1.0.0.tar.xz"

def test_download_filepath_change_destination():
    download = Download('test', 'https://test.com/{version}/test-{version}.tar.xz', version="1.0.0", destination="/tmp")
    download.destination = "/tmp/foo"
    assert isinstance(download.filepath, pathlib.Path)
    if sys.platform.startswith("win"):
        assert str(download.filepath) == "\\tmp\\foo\\test-1.0.0.tar.xz"
    else:
        assert str(download.filepath) == "/tmp/foo/test-1.0.0.tar.xz"

def test_download_exists(tmpdir):
    download = Download('test', 'https://test.com/{version}/test-{version}.tar.xz', version="1.0.0", destination=tmpdir)
    assert download.exists() == False
    (pathlib.Path(tmpdir) / "test-1.0.0.tar.xz").touch()
    assert download.exists() == True
