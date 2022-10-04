"""
Verify mayflower builds
"""
import pathlib
import subprocess
import sys
import tempfile

import pytest

from mayflower.common import archived_build
from mayflower.create import create

pytestmark = pytest.mark.skipif(
    not archived_build().exists(), reason="Build archive does not exist"
)


@pytest.fixture
def pipexec(build):
    if sys.platform == "win32":
        yield build / "Scripts" / "pip3.exe"
    else:
        yield build / "bin" / "pip3"


@pytest.fixture
def pyexec(build):
    if sys.platform == "win32":
        yield build / "Scripts" / "python.exe"
    yield build / "bin" / "python3"


@pytest.fixture
def build(tmpdir):
    create("test", tmpdir)
    yield pathlib.Path(tmpdir) / "test"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_directories_win(build):
    assert (build / "Scripts").exists()
    assert (build / "DLLs").exists()
    assert (build / "Lib").exists()
    assert (build / "Lib" / "site-packages").exists()
    assert (build / "libs").exists()
    assert (build / "Include").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Non windows only")
def test_directories(build):
    assert (build / "bin").exists()
    assert (build / "lib").exists()
    assert (build / "lib" / "python3.10").exists()
    assert (build / "lib" / "python3.10" / "lib-dynload").exists()
    assert (build / "lib" / "python3.10" / "site-packages").exists()
    assert (build / "include").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_imports(pyexec):
    modules = [
        "asyncio",
        "binascii",
        "bz2",
        "ctypes",
        "hashlib",
        "math",
        "select",
        "socket",
        "ssl",
        "sqlite3",
        "unicodedata",
    ]
    for mod in modules:
        p = subprocess.run([str(pyexec), "-c", f"import {mod}"])
        assert p.returncode == 0, f"Failed to import {mod}"


@pytest.mark.skipif(sys.platform == "win32", reason="Non windows only")
def test_imports(pyexec):
    modules = [
        "asyncio",
        "binascii",
        "bz2",
        "ctypes",
        "curses",
        "hashlib",
        "math",
        "readline",
        "select",
        "socket",
        "ssl",
        "sqlite3",
        "termios",
        "unicodedata",
    ]
    for mod in modules:
        p = subprocess.run([str(pyexec), "-c", f"import {mod}"])
        assert p.returncode == 0, f"Failed to import {mod}"


def test_pip_install_salt(pipexec):
    packages = [
        "salt",
    ]
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"])
        assert p.returncode == 0, f"Failed to pip install {name}"


def test_pip_install_cryptography(pipexec):
    packages = [
        "cryptography",
    ]
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"])
        assert p.returncode == 0, f"Failed to pip install {name}"


def test_pip_install_idem(pipexec):
    packages = [
        "idem",
    ]
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"])
        assert p.returncode == 0, f"Failed to pip install {name}"
