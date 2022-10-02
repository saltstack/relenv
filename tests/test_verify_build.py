import pathlib
import subprocess
import tempfile

import pytest

from mayflower.common import archived_build
from mayflower.create import create

pytestmark = pytest.mark.skipif(
    not archived_build().exists(), reason="Build archive does not exist"
)


@pytest.fixture
def build(tmpdir):
    create("test_foo", tmpdir)
    yield pathlib.Path(tmpdir) / "test_foo"


def test_directories(build):
    assert (build / "bin").exists()
    assert (build / "lib").exists()
    assert (build / "lib" / "python3.10").exists()
    assert (build / "lib" / "python3.10" / "lib-dynload").exists()
    assert (build / "lib" / "python3.10" / "site-packages").exists()
    assert (build / "include").exists()


def test_imports(build):
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
        python = str(build / "bin" / "python3")
        p = subprocess.run([python, "-c", f"import {mod}"])
        assert p.returncode == 0, f"Failed to import {mod}"
