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
    sys.platform != "linux" and get_build_version() == "3.11.4",
    reason="3.11.4 will not work on windows yet",
)
def test_pip_install_salt_git(pipexec, build, tmp_path, pyexec):
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    if sys.platform == "linux" and not shutil.which("git"):
        os.chdir(tmp_path)
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


@pytest.mark.skip_on_darwin
@pytest.mark.skip_on_windows
@pytest.mark.skipif(
    get_build_version() == "3.11.4", reason="3.11.4 will not work with 3005.x"
)
def test_pip_install_salt(pipexec, build, tmp_path, pyexec):
    packages = [
        "salt==3005",
    ]
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["RELENV_BUILDENV"] = "yes"

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
    env["RELENV_BUILDENV"] = "yes"

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
    get_build_version() == "3.11.4",
    reason="3.11.4 will not work until pyzmq is upgraded",
)
def test_pip_install_salt_w_static_requirements(pipexec, build, tmpdir):
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
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
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
        assert p.returncode == 0, f"Failed to pip install {name}"


def test_pip_install_idem(pipexec):
    packages = [
        "idem",
    ]
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
        assert p.returncode == 0, f"Failed to pip install {name}"


def test_pip_install_and_import_libcloud(pipexec, pyexec):
    name = "apache-libcloud"
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    p = subprocess.run([str(pipexec), "install", name, "--no-cache"], env=env)
    assert p.returncode == 0, f"Failed to pip install {name}"

    import_name = "libcloud.security"
    import_ret = subprocess.run([str(pyexec), "-c", f"import {import_name}"])
    assert import_ret.returncode == 0, f"Failed to import {import_name}"


# XXX Re-enable after 3006.2 has been released
@pytest.mark.skip_on_darwin
@pytest.mark.skip_on_windows
@pytest.mark.skipif(
    get_build_version() == "3.11.4", reason="3.11.4 will not work with 3005.x"
)
def test_pip_install_salt_pip_dir(pipexec, build):
    packages = [
        "salt",
    ]
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
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
    env["RELENV_BUILDENV"] = "yes"
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
def test_pip_install_m2crypto_system_ssl(pipexec, pyexec, build, tmpdir):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["LDFLAGS"] = "-L/usr/lib"
    env["CFLAGS"] = "-I/usr/include"
    env["SWIG_FEATURES"] = "-I/usr/include"
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
    include = "/usr/include"
    found_include = False
    for _ in p.stderr.splitlines():
        line = _.decode()
        if "gcc" in line:
            for arg in line.split():
                if arg == f"-I{include}":
                    found_include = True
    assert found_include
    p = subprocess.run(
        [str(pyexec), "-c", "import M2Crypto"],
        env=env,
        # stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert p.returncode == 0, p.stderr


@pytest.mark.skip_unless_on_linux
def test_pip_install_m2crypto_relenv_ssl(pipexec, pyexec, build, tmpdir):
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    env["RELENV_DEBUG"] = "yes"
    env["LDFLAGS"] = f"-L{build}lib"
    env["CFLAGS"] = f"-I{build}/include"
    env["SWIG_FEATURES"] = f"-I{build}/include"
    p = subprocess.run(
        ["swig", "-version"],
    )
    p = subprocess.run(
        [str(pipexec), "install", "m2crypto", "--no-cache", "-v"],
        env=env,
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
    p = subprocess.run(
        [str(pyexec), "-c", "import M2Crypto"],
        env=env,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert p.returncode == 0, p.stderr


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
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    p = subprocess.run(
        [str(pipexec), "install", "cffi==1.15.1", "--no-cache-dir", "--no-binary=cffi"],
        env=env,
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
@pytest.mark.parametrize("cryptography_version", ["40.0.1", "39.0.2"])
def test_cryptography_rpath(pipexec, build, minor_version, cryptography_version):
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            f"cryptography=={cryptography_version}",
            "--no-cache-dir",
            "--no-binary=cryptography",
        ],
        env=env,
    )
    assert p.returncode != 1, "Failed to pip install cryptography"
    bindings = (
        build
        / "lib"
        / f"python{minor_version}"
        / "site-packages"
        / "cryptography"
        / "hazmat"
        / "bindings"
    )
    if cryptography_version == "39.0.2":
        osslinked = "_openssl.abi3.so"
    else:
        osslinked = "_rust.abi3.so"
    p = subprocess.run(
        ["ldd", bindings / osslinked], stdout=subprocess.PIPE, check=True
    )
    found = 0
    for line in p.stdout.splitlines():
        line = line.decode()
        if "=>" not in line:
            continue
        lib, dest = [_.strip() for _ in line.split("=>", 1)]
        baselib = ".".join(lib.split(".")[:2])
        if baselib == "libssl.so":
            found += 1
            assert str(build) in dest
        elif baselib == "libcrypto.so":
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


@pytest.mark.skip_unless_on_linux
def test_install_pycurl(pipexec, build, minor_version, tmpdir):
    curlver = "8.0.1"
    os.chdir(tmpdir)

    # Build curl and install it into the relenv environment
    buildscript = textwrap.dedent(
        """\
    set -e
    wget https://curl.se/download/curl-{curlver}.tar.gz
    tar xvf curl-{curlver}.tar.gz
    cd curl-{curlver}
    source <({build}/bin/relenv buildenv)
    export LDFLAGS="${{LDFLAGS}} -Wl,-rpath-link,${{RELENV_PATH}}/lib"
    env
    ./configure --prefix=$RELENV_PATH --with-openssl=$RELENV_PATH
    make
    make install

    # Fix any non-relative rpaths
    {build}/bin/relenv check
    """
    )
    with open("buildcurl.sh", "w") as fp:
        fp.write(
            buildscript.format(
                curlver=curlver,
                build=build,
            )
        )

    subprocess.run(["/usr/bin/bash", "buildcurl.sh"], check=True)

    # Make sure curl-config exists.
    assert (build / "bin" / "curl-config").exists()

    # Add the relenv environment to the path so pycurl can find the curl-config
    # executable
    env = os.environ.copy()
    env["PATH"] = f"{build}/bin:{env['PATH']}"
    env["RELENV_BUILDENV"] = "yes"

    # Install pycurl
    subprocess.run(
        [str(pipexec), "install", "pycurl", "--no-cache"], env=env, check=True
    )

    # Move the relenv environment, if something goes wrong this will break the linker.
    b2 = build.parent / "test2"
    build.rename(b2)

    # Test pycurl
    py3 = str(b2 / "bin" / "python3")
    testscript = textwrap.dedent(
        """\
    import pycurl
    import io
    import re
    curl = pycurl.Curl()
    buff = io.BytesIO()
    hdr = io.BytesIO()
    curl.setopt(pycurl.URL, 'http://example.org')
    curl.setopt(pycurl.WRITEFUNCTION, buff.write)
    curl.setopt(pycurl.HEADERFUNCTION, hdr.write)
    curl.perform()
    print(curl.getinfo(pycurl.HTTP_CODE))
    """
    )
    subprocess.run([py3, "-c", testscript], check=True)


@pytest.mark.skip_unless_on_linux
@pytest.mark.parametrize(
    "versions",
    [
        {
            "libssh2": "1.10.0",
            "libgit2": "1.5.2",
            "pygit2": "1.11.1",
        },
        {
            "libssh2": "1.10.0",
            "libgit2": "1.6.2",
            "pygit2": "1.12.0",
        },
    ],
)
def test_install_libgit2(pipexec, build, minor_version, tmpdir, versions):
    os.chdir(tmpdir)

    buildscript = textwrap.dedent(
        """\
    set -e

    # Setup the build environment
    source <({build}/bin/relenv buildenv)

    # Build and install libssh2
    wget https://www.libssh2.org/download/libssh2-{libssh2}.tar.gz
    tar xvf libssh2-{libssh2}.tar.gz
    cd libssh2-{libssh2}
    mkdir bin
    cd bin
    cmake .. \
      -DENABLE_ZLIB_COMPRESSION=ON \
      -DOPENSSL_ROOT_DIR="$RELENV_PATH" \
      -DBUILD_SHARED_LIBS=ON \
      -DBUILD_EXAMPLES=OFF \
      -DBUILD_TESTING=OFF \
      -DCMAKE_INSTALL_PREFIX="$RELENV_PATH"
    cmake --build .
    cmake --build . --target install

    cd ../..

    # Build and install libgit2
    wget https://github.com/libgit2/libgit2/archive/refs/tags/v{libgit2}.tar.gz
    tar xvf v{libgit2}.tar.gz
    cd libgit2-{libgit2}
    mkdir build
    cd build
    cmake ..  \
      -DOPENSSL_ROOT_DIR="$RELENV_PATH" \
      -DBUILD_CLI=OFF \
      -DBUILD_TESTS=OFF \
      -DUSE_SSH=ON \
      -DCMAKE_INSTALL_PREFIX="$RELENV_PATH"
    cmake --build .
    cmake --build . --target install

    cd ../..

    # Fix any non-relative rpaths
    {build}/bin/relenv check
    """
    )
    print(versions)

    with open("buildscript.sh", "w") as fp:
        fp.write(
            buildscript.format(
                libssh2=versions["libssh2"], libgit2=versions["libgit2"], build=build
            )
        )

    subprocess.run(["/usr/bin/bash", "buildscript.sh"], check=True)

    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["RELENV_BUILDENV"] = "yes"
    subprocess.run(
        [
            str(pipexec),
            "install",
            f"pygit2=={versions['pygit2']}",
            "--no-cache",
            "--no-binary=:all:",
        ],
        check=True,
        env=env,
    )


@pytest.mark.skip_unless_on_linux
def test_install_python_ldap(pipexec, build, minor_version, tmpdir):
    saslver = "2.1.28"
    ldapver = "2.5.14"
    os.chdir(tmpdir)

    buildscript = textwrap.dedent(
        """\
    # Setup the environment
    set -e
    source <({build}/bin/relenv buildenv)

    # Build and Install sasl
    wget https://github.com/cyrusimap/cyrus-sasl/releases/download/cyrus-sasl-{saslver}/cyrus-sasl-{saslver}.tar.gz
    tar xvf cyrus-sasl-{saslver}.tar.gz
    cd cyrus-sasl-{saslver}
    ./configure --prefix=$RELENV_PATH
    make
    make install
    cd ..

    # Build and Install Open LDAP
    wget https://www.openldap.org/software/download/OpenLDAP/openldap-release/openldap-{ldapver}.tgz
    tar xvf openldap-{ldapver}.tgz
    cd openldap-{ldapver}
    ./configure --prefix=$RELENV_PATH
    make
    make install
    cd ..

    # Fix any non-relative rpaths
    {build}/bin/relenv check
    """
    )

    with open("buildscript.sh", "w") as fp:
        fp.write(
            buildscript.format(
                saslver=saslver,
                ldapver=ldapver,
                build=build,
            )
        )

    subprocess.run(["/usr/bin/bash", "buildscript.sh"], check=True)
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["RELENV_BUILDENV"] = "yes"

    subprocess.run(
        [str(pipexec), "install", "python-ldap", "--no-cache", "--no-binary=:all:"],
        check=True,
        env=env,
    )


@pytest.mark.skip_unless_on_linux
def test_install_python_ldap_system_libs(pipexec):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    subprocess.run(
        [str(pipexec), "install", "python-ldap", "--no-cache", "--no-binary=:all:"],
        check=True,
        env=env,
    )


@pytest.mark.skip_unless_on_linux
def test_install_with_target_shebang(pipexec, build, minor_version):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    subprocess.run(
        [str(pipexec), "install", "cowsay", f"--target={extras}"],
        check=True,
        env=env,
    )
    shebang = pathlib.Path(extras / "bin" / "cowsay").open().readlines()[2].strip()
    assert (
        shebang
        == '"exec" "$(dirname "$(readlink -f "$0")")/../../bin/python{}" "$0" "$@"'.format(
            minor_version
        )
    )


@pytest.mark.skip_unless_on_linux
def test_install_with_target_uninstall(pipexec, build):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    subprocess.run(
        [str(pipexec), "install", "cowsay", f"--target={extras}"],
        check=True,
        env=env,
    )
    assert (extras / "cowsay").exists()
    assert (extras / "bin" / "cowsay").exists()
    env["PYTHONPATH"] = extras
    subprocess.run(
        [str(pipexec), "uninstall", "cowsay", "-y"],
        check=True,
        env=env,
    )
    assert not (extras / "cowsay").exists()
    assert not (extras / "bin" / "cowsay").exists()


def test_install_with_target_cffi_versions(pipexec, pyexec, build):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    subprocess.run(
        [str(pipexec), "install", "cffi==1.14.6"],
        check=True,
        env=env,
    )
    subprocess.run(
        [str(pipexec), "install", "cffi==1.15.1", f"--target={extras}"],
        check=True,
        env=env,
    )
    env["PYTHONPATH"] = str(extras)
    proc = subprocess.run(
        [str(pyexec), "-c", "import cffi; cffi.FFI(); print(cffi.__version__)"],
        check=True,
        env=env,
        capture_output=True,
    )
    proc.stdout.decode().strip() == "1.15.1"


def test_install_with_target_no_ignore_installed(pipexec, pyexec, build):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    subprocess.run(
        [str(pipexec), "install", "cffi==1.15.1"],
        check=True,
        env=env,
    )
    proc = subprocess.run(
        [str(pipexec), "install", "pygit2==1.12.0", f"--target={extras}"],
        check=True,
        env=env,
        capture_output=True,
    )
    out = proc.stdout.decode()
    assert "already satisfied: cffi" in out
    assert "installed cffi" not in out


def test_install_with_target_ignore_installed(pipexec, pyexec, build):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    subprocess.run(
        [str(pipexec), "install", "cffi==1.15.1"],
        check=True,
        env=env,
    )
    proc = subprocess.run(
        [
            str(pipexec),
            "install",
            "pygit2==1.12.0",
            f"--target={extras}",
            "--ignore-installed",
        ],
        check=True,
        env=env,
        capture_output=True,
    )
    out = proc.stdout.decode()
    assert "installed cffi" in out
    assert "already satisfied: cffi" not in out

@pytest.mark.skip_unless_on_linux
def test_install_with_target_scripts(pipexec, build, minor_version):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    subprocess.run(
        [str(pipexec), "install", "rend", f"--target={extras}"],
        check=True,
        env=env,
    )
    assert (extras / "bin" / "rend").exists()
    subprocess.run(
        [str(pipexec), "install", "cowsay", f"--target={extras}"],
        check=True,
        env=env,
    )
    assert (extras / "bin" / "cowsay").exists()
