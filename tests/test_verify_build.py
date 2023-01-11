# Copyright 2022-2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
Verify relenv builds.
"""
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from relenv.common import DATA_DIR, archived_build, get_triplet
from relenv.create import create

pytestmark = [
    pytest.mark.skipif(
        not archived_build().exists(), reason="Build archive does not exist"
    ),
]


@pytest.fixture
def build(tmpdir):
    create("test", tmpdir)
    yield pathlib.Path(tmpdir) / "test"


@pytest.fixture
def pipexec(build):
    if sys.platform == "win32":
        exc = build / "Scripts" / "pip3.exe"
    else:
        exc = build / "bin" / "pip3"
    yield exc


@pytest.fixture
def pyexec(build):
    if sys.platform == "win32":
        exc = build / "Scripts" / "python.exe"
    else:
        exc = build / "bin" / "python3"
    yield exc


@pytest.mark.skip_unless_on_windows
def test_directories_win(build):
    assert (build / "Scripts").exists()
    assert (build / "DLLs").exists()
    assert (build / "Lib").exists()
    assert (build / "Lib" / "site-packages").exists()
    assert (build / "libs").exists()
    assert (build / "Include").exists()


@pytest.mark.skip_on_windows
def test_directories(build):
    assert (build / "bin").exists()
    assert (build / "lib").exists()
    assert (build / "lib" / "python3.10").exists()
    assert (build / "lib" / "python3.10" / "lib-dynload").exists()
    assert (build / "lib" / "python3.10" / "site-packages").exists()
    assert (build / "include").exists()


@pytest.mark.skip_unless_on_windows
def test_imports_windows(pyexec):
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


@pytest.mark.skip_on_windows
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


def test_pip_install_salt_git(pipexec, build, tmp_path, pyexec):
    packages = [
        "salt@git+https://github.com/saltstack/salt",
    ]
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"

    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
        assert p.returncode == 0, f"Failed to pip install {name}"

    names = ["salt", "salt-call", "salt-master", "salt-minion"]
    if sys.platform == "win32":
        names = ["salt-call.exe", "salt-minion.exe"]

    for _ in names:
        if sys.platform == "win32":
            script = pathlib.Path(build) / "Scripts" / _
        else:
            script = pathlib.Path(build) / "bin" / _
        assert script.exists()


@pytest.mark.skip_on_windows
def test_pip_install_salt(pipexec, build, tmp_path, pyexec):
    packages = [
        "salt==3005",
    ]
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"

    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
        assert p.returncode == 0, f"Failed to pip install {name}"

    names = ["salt", "salt-call", "salt-master", "salt-minion"]
    if sys.platform == "win32":
        names = ["salt-call.exe", "salt-minion.exe"]

    for _ in names:
        if sys.platform == "win32":
            script = pathlib.Path(build) / "Scripts" / _
        else:
            script = pathlib.Path(build) / "bin" / _
        assert script.exists()


@pytest.mark.skip_on_windows
def test_symlinked_scripts(pipexec, tmp_path, build):
    name = "chardet==5.1.0"
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"

    p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
    assert p.returncode == 0, f"Failed to pip install {name}"

    script = pathlib.Path(build) / "bin" / "chardetect"

    # make the link to pip
    link = tmp_path / "links" / "chardetectlink"
    link.parent.mkdir()
    link.symlink_to(script)

    # Make sure symlinks work with our custom shebang in the scripts
    p = subprocess.run([str(script), "--version"])
    assert (
        p.returncode == 0
    ), f"Could not run script for {name}, likely not pinning to the correct python"


def test_pip_install_salt_w_static_requirements(pipexec, build, tmpdir):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["USE_STATIC_REQUIREMENTS"] = "1"
    p = subprocess.run(["git", "clone", "https://github.com/saltstack/salt.git", f"{tmpdir / 'salt'}"])
    assert p.returncode == 0, "Failed clone salt repo"

    p = subprocess.run([str(pipexec), "install", f"{tmpdir / 'salt'}", "--no-cache"], env=env)
    assert p.returncode == 0, "Failed to pip install ./salt"

    names = ["salt", "salt-call", "salt-master", "salt-minion"]
    if sys.platform == "win32":
        names = ["salt-call.exe", "salt-minion.exe"]

    for _ in names:
        if sys.platform == "win32":
            script = pathlib.Path(build) / "Scripts" / _
        else:
            script = pathlib.Path(build) / "bin" / _
        assert script.exists()


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


def test_pip_install_and_import_libcloud(pipexec, pyexec):
    name = "apache-libcloud"
    p = subprocess.run([str(pipexec), "install", name, "--no-cache"])
    assert p.returncode == 0, f"Failed to pip install {name}"

    import_name = "libcloud.security"
    import_ret = subprocess.run(
        [str(pyexec), "-c", f"import {import_name}", "--no-cache"]
    )
    assert import_ret.returncode == 0, f"Failed to import {import_name}"


@pytest.mark.skip_on_windows
def test_pip_install_salt_pip_dir(pipexec, build):
    packages = [
        "salt",
    ]
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["RELENV_PIP_DIR"] = "yes"
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
        assert p.returncode == 0, f"Failed to pip install {name}"

    names = ["salt", "salt-call", "salt-master", "salt-minion"]
    if sys.platform == "win32":
        names = ["salt-call.exe", "salt-minion.exe"]

    for _ in names:
        script = pathlib.Path(build) / _
        assert script.exists()


def test_nox_virtualenvs(pipexec, build, tmp_path):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    name = "nox"

    p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
    assert p.returncode == 0, f"Failed to pip install {name}"

    if sys.platform == "win32":
        script = pathlib.Path(build) / "Scripts" / f"{name}.exe"
    else:
        script = pathlib.Path(build) / "bin" / name

    assert script.exists()

    session = "fake_session"
    nox_contents = textwrap.dedent(
        """
    import nox

    @nox.session()
    def {}(session):
        session.install("nox")
    """.format(
            session
        )
    )
    noxfile = tmp_path / "tmp_noxfile.py"
    noxfile.write_text(nox_contents)
    nox_venvs = tmp_path / ".tmpnox"
    nox_venvs.mkdir()

    p = subprocess.run(
        [str(script), "-f", str(noxfile), "--envdir", str(nox_venvs), "-e", session],
        env=env,
    )
    session = nox_venvs / session
    assert session.exists()
    if sys.platform == "win32":
        assert (session / "Scripts" / "nox.exe").exists()
    else:
        assert (session / "bin" / "nox").exists()


@pytest.mark.skip_unless_on_linux
def test_pip_install_m2crypto(pipexec, build, tmpdir):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    p = subprocess.run(
        [str(pipexec), "install", "m2crypto", "--no-cache", "-v"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert p.returncode == 0, "Failed to pip install m2crypto"
    gcc = str(
        pathlib.Path(DATA_DIR)
        / "toolchain"
        / f"{get_triplet()}"
        / "bin"
        / f"{get_triplet()}-gcc"
    )
    include = str(pathlib.Path(build) / "include")
    found_include = False
    for _ in p.stderr.splitlines():
        line = _.decode()
        if gcc in line:
            for arg in line.split():
                if arg == f"-I{include}":
                    found_include = True
    assert found_include


@pytest.mark.skip_on_windows
def test_shabangs(pipexec, build):
    def validate_shebang(path):
        with open(path, "r") as fp:
            return fp.read(9) == "#!/bin/sh"

    path = build / "bin" / "pip3"
    assert path.exists()
    assert validate_shebang(path)
    path = build / "lib" / "python3.10" / "cgi.py"
    assert path.exists()
    assert validate_shebang(path)
    if sys.platform == "linux":
        path = (
            build
            / "lib"
            / "python3.10"
            / f"config-3.10-{get_triplet()}"
            / "python-config.py"
        )
        assert path.exists()
        assert validate_shebang(path)
