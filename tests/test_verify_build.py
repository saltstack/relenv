# Copyright 2022-2023 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
Verify relenv builds.
"""
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import textwrap

import pytest

from relenv.common import DATA_DIR, get_triplet, list_archived_builds, plat_from_triplet
from relenv.create import create


def get_build_version():
    if "RELENV_PY_VERSION" in os.environ:
        return os.environ["RELENV_PY_VERSION"]
    builds = list(list_archived_builds())
    versions = []
    for version, arch, plat in builds:
        sysplat = plat_from_triplet(plat)
        if sysplat == sys.platform and arch == platform.machine().lower():
            versions.append(version)
    if versions:
        return versions[0]


@pytest.fixture(scope="module")
def build_version():
    version = get_build_version()
    yield version


@pytest.fixture(scope="module")
def minor_version():
    yield get_build_version().rsplit(".", 1)[0]


pytestmark = [
    pytest.mark.skipif(not get_build_version(), reason="Build archive does not exist"),
]


@pytest.fixture
def build(tmpdir, build_version):
    create("test", tmpdir, version=build_version)
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
def test_directories(build, minor_version):
    vpy = f"python{minor_version}"
    assert (build / "bin").exists()
    assert (build / "lib").exists()
    assert (build / "lib" / vpy).exists()
    assert (build / "lib" / vpy / "lib-dynload").exists()
    assert (build / "lib" / vpy / "site-packages").exists()
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


@pytest.mark.skipif(
    sys.platform != "linux" and get_build_version() == "3.11.2",
    reason="3.11.2 will not work on windows yet",
)
def test_pip_install_salt_git(pipexec, build, tmp_path, pyexec):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    if sys.platform == "linux" and shutil.which("git"):
        packages = [
            "./salt",
        ]
        p = subprocess.run(
            ["git", "clone", "https://github.com/saltstack/salt.git", "--depth", "1"],
            env=env,
        )
        assert p.returncode == 0, "Failed to clone salt repository"
    else:
        packages = ["salt@git+https://github.com/saltstack/salt"]

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
@pytest.mark.skipif(
    get_build_version() == "3.11.2", reason="3.11.2 will not work with 3005.x"
)
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


@pytest.mark.skipif(
    get_build_version() == "3.11.2",
    reason="3.11.2 will not work until pyzmq is upgraded",
)
def test_pip_install_salt_w_static_requirements(pipexec, build, tmpdir):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["USE_STATIC_REQUIREMENTS"] = "1"
    p = subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            "https://github.com/saltstack/salt.git",
            f"{tmpdir / 'salt'}",
        ]
    )
    assert p.returncode == 0, "Failed clone salt repo"

    p = subprocess.run(
        [str(pipexec), "install", f"{tmpdir / 'salt'}", "--no-cache"], env=env
    )
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
    import_ret = subprocess.run([str(pyexec), "-c", f"import {import_name}"])
    assert import_ret.returncode == 0, f"Failed to import {import_name}"


@pytest.mark.skip_on_windows
@pytest.mark.skipif(
    get_build_version() == "3.11.2", reason="3.11.2 will not work with 3005.x"
)
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
        ["swig", "-version"],
    )
    p = subprocess.run(
        [str(pipexec), "install", "m2crypto", "--no-cache", "-v"],
        env=env,
        # stdout=subprocess.PIPE,
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
def test_shabangs(pipexec, build, minor_version):
    def validate_shebang(path):
        with open(path, "r") as fp:
            return fp.read(9) == "#!/bin/sh"

    path = build / "bin" / "pip3"
    assert path.exists()
    assert validate_shebang(path)
    path = build / "lib" / f"python{minor_version}" / "cgi.py"
    assert path.exists()
    assert validate_shebang(path)
    if sys.platform == "linux":
        path = (
            build
            / "lib"
            / f"python{minor_version}"
            / f"config-{minor_version}-{get_triplet()}"
            / "python-config.py"
        )
        assert path.exists()
        assert validate_shebang(path)


# XXX Mac support
@pytest.mark.skip_unless_on_linux
def test_moving_pip_installed_c_extentions(pipexec, build, minor_version):
    p = subprocess.run(
        [str(pipexec), "install", "cffi==1.15.1", "--no-cache-dir", "--no-binary=cffi"],
    )
    assert p.returncode == 0, "Failed to pip install cffi"
    b2 = build.parent / "test2"
    build.rename(b2)
    libname = (
        f"_cffi_backend.cpython-{minor_version.replace('.', '')}-x86_64-linux-gnu.so"
    )
    p = subprocess.run(
        ["ldd", b2 / "lib" / f"python{minor_version}" / "site-packages" / libname],
        stdout=subprocess.PIPE,
    )
    for line in p.stdout.splitlines():
        line = line.decode()
        if "=>" not in line:
            continue
        lib, dest = [_.strip() for _ in line.split("=>", 1)]
        if lib == "libffi.so.8":
            assert str(b2) in dest


@pytest.mark.skip_unless_on_linux
def test_cryptography_rpath(pipexec, build, minor_version):
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "cryptography",
            "--no-cache-dir",
            "--no-binary=cryptography",
        ],
    )
    assert p.returncode == 0, "Failed to pip install cryptography"
    bindings = (
        build
        / "lib"
        / f"python{minor_version}"
        / "site-packages"
        / "cryptography"
        / "hazmat"
        / "bindings"
    )
    p = subprocess.run(
        ["ldd", bindings / "_openssl.abi3.so"], stdout=subprocess.PIPE, check=True
    )
    found = 0
    for line in p.stdout.splitlines():
        line = line.decode()
        if "=>" not in line:
            continue
        lib, dest = [_.strip() for _ in line.split("=>", 1)]
        if lib == "libssl.so.1.1":
            found += 1
            assert str(build) in dest
        elif lib == "libcrypto.so.1.1":
            found += 1
            assert str(build) in dest
    assert found == 2, f"Found {found} of 2 shared libraries"

    # Verify the rust binary was compiled against relenv's glibc
    p = subprocess.run(
        ["readelf", "--version-info", bindings / "_rust.abi3.so"],
        stdout=subprocess.PIPE,
        check=True,
    )
    valid = True
    for line in p.stdout.decode().splitlines():
        if "GLIBC_2.33" in line:
            valid = False
            break
    assert valid
