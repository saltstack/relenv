# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
# mypy: ignore-errors
"""
Verify relenv builds.
"""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
import uuid

import packaging
import pytest

from relenv.common import build_arch, get_triplet

from .conftest import get_build_version

pytestmark = [
    pytest.mark.skipif(not get_build_version(), reason="Build archive does not exist"),
]


EXTRAS_PY = """
import pathlib
import sys


def setup(pth_file_path):
    # Discover the extras-<py-major>.<py-minor> directory
    extras_parent_path = pathlib.Path(pth_file_path).resolve().parent.parent
    if not sys.platform.startswith("win"):
        extras_parent_path = extras_parent_path.parent

    extras_path = str(extras_parent_path / "extras-{}.{}".format(*sys.version_info))

    if extras_path in sys.path and sys.path[0] != extras_path:
        # The extras directory must come first
        sys.path.remove(extras_path)

    if extras_path not in sys.path:
        sys.path.insert(0, extras_path)
"""


def _install_ppbt(pexec):
    if sys.platform in ["win32", "darwin"]:
        return
    p = subprocess.run(
        [
            str(pexec),
            "-m",
            "pip",
            "install",
            "ppbt",
        ]
    )
    assert p.returncode == 0, "Failed to install ppbt"
    p = subprocess.run(
        [str(pexec), "-c", "from relenv import common; assert common.get_toolchain()"]
    )
    assert p.returncode == 0, "Failed to extract toolchain"


def _setup_buildenv(pyexec, env):
    """
    Setup build environment variables for compiling C extensions.

    On Linux, this calls 'relenv buildenv --json' to get the proper compiler
    flags and paths to use the relenv toolchain and bundled libraries instead
    of system libraries.

    :param pyexec: Path to the relenv Python executable
    :param env: Environment dictionary to update with buildenv variables
    """
    if sys.platform != "linux":
        return

    p = subprocess.run(
        [
            str(pyexec),
            "-m",
            "relenv",
            "buildenv",
            "--json",
        ],
        capture_output=True,
    )
    try:
        buildenv = json.loads(p.stdout)
    except json.JSONDecodeError:
        assert False, f"Failed to decode json: {p.stdout.decode()} {p.stderr.decode()}"

    for k in buildenv:
        env[k] = buildenv[k]


@pytest.fixture(autouse=True)
def _clear_ssl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure preceding tests do not leave stale certificate paths behind.
    """
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)


@pytest.fixture(scope="module")
def arch():
    return build_arch()


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


def test_pip_install_salt_git(pipexec, build, build_dir, pyexec, build_version):
    if (
        sys.platform == "win32"
        and "3.11" in build_version
        or "3.12" in build_version
        or "3.13" in build_version
    ):
        pytest.xfail("Salt does not work with 3.11 or 3.12 on windows yet")
    if sys.platform == "darwin" and "3.12" in build_version:
        pytest.xfail("Salt does not work with 3.12 on macos yet")
    if sys.platform == "darwin" and "3.13" in build_version:
        pytest.xfail("Salt does not work with 3.13 on macos yet")

    _install_ppbt(pyexec)

    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
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
        p = subprocess.run([str(pipexec), "install", name, "--no-cache-dir"], env=env)
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
    get_build_version()
    and packaging.version.parse(get_build_version())
    >= packaging.version.parse("3.11.7"),
    reason="3.11.7 and greater will not work with 3005.x",
)
def test_pip_install_salt(pipexec, build, tmp_path, pyexec):

    _install_ppbt(pyexec)

    packages = [
        "salt==3005",
    ]
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["RELENV_BUILDENV"] = "yes"

    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache-dir"], env=env)
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
def test_symlinked_scripts(pipexec, pyexec, tmp_path, build):
    _install_ppbt(pyexec)

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


@pytest.mark.parametrize("salt_branch", ["3006.x", "3007.x", "master"])
def test_pip_install_salt_w_static_requirements(
    pipexec, pyexec, build, tmp_path, salt_branch, build_version
):
    if salt_branch in ["3007.x", "master"]:
        pytest.xfail("Known failure")

    if sys.platform == "darwin" and salt_branch in ["3006.x"]:
        pytest.xfail("Known failure")

    for py_version in ("3.11", "3.12", "3.13"):
        if build_version.startswith(py_version):
            pytest.xfail(f"{py_version} builds fail.")

    if salt_branch == "3006.x" and sys.platform == "win32":
        pytest.xfail("Known failure")

    _install_ppbt(pyexec)

    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    env["USE_STATIC_REQUIREMENTS"] = "1"
    p = subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            f"--branch={salt_branch}",
            "https://github.com/saltstack/salt.git",
            f"{tmp_path / 'salt'}",
        ]
    )
    assert p.returncode == 0, "Failed clone salt repo"

    p = subprocess.run(
        [
            str(pipexec),
            "install",
            f"{tmp_path / 'salt'}",
            "-v",
            "--no-cache-dir",
            "--no-binary=:all:",
            "--use-pep517",
        ],
        env=env,
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


@pytest.mark.parametrize("salt_branch", ["3006.x", "master"])
def test_pip_install_salt_w_package_requirements(
    pipexec, pyexec, tmp_path, salt_branch, build_version
):

    for py_version in ("3.11", "3.12", "3.13"):
        if build_version.startswith(py_version):
            pytest.xfail(f"{py_version} builds fail.")

    if salt_branch in ["3007.x", "master"]:
        pytest.xfail("Known failure")

    if sys.platform == "win32":
        pytest.xfail("Known failure")

    if sys.platform == "darwin" and salt_branch == "3006.x":
        pytest.xfail("Known failure")

    _install_ppbt(pyexec)
    env = os.environ.copy()
    _setup_buildenv(pyexec, env)
    env["RELENV_BUILDENV"] = "yes"
    env["USE_STATIC_REQUIREMENTS"] = "1"
    p = subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            f"--branch={salt_branch}",
            "https://github.com/saltstack/salt.git",
            f"{tmp_path / 'salt'}",
        ]
    )
    assert p.returncode == 0, "Failed clone salt repo"

    # p = subprocess.run(
    #     [
    #         str(pipexec),
    #         "install",
    #         f"{tmp_path / 'salt'}",
    #         "--no-cache-dir",
    #         "--no-binary=:all",
    #         "--use-pep517",
    #     ],
    #     env=env,
    # )
    # assert p.returncode == 0, "Failed to pip install ./salt"
    if sys.platform == "win32":
        reqfile = "windows.txt"
    else:
        reqfile = sys.platform
    req = os.path.join(
        f"{tmp_path / 'salt'}",
        "requirements",
        "static",
        "pkg",
        f"py{build_version.rsplit('.', 1)[0]}",
        f"{reqfile}.txt",
    )
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "--no-cache-dir",
            "--no-binary=:all:",
            "--use-pep517",
            f"--requirement={req}",
        ],
        env=env,
    )
    assert p.returncode == 0, "Failed to pip install package requirements"

    # names = ["salt", "salt-call", "salt-master", "salt-minion"]
    # if sys.platform == "win32":
    #     names = ["salt-call.exe", "salt-minion.exe"]

    # for _ in names:
    #     if sys.platform == "win32":
    #         script = pathlib.Path(build) / "Scripts" / _
    #     else:
    #         script = pathlib.Path(build) / "bin" / _
    #     assert script.exists()


@pytest.mark.parametrize(
    "pyzmq_version",
    [
        "23.2.0",
        "25.1.2",
        "26.2.0",
        "26.4.0",
    ],
)
def test_pip_install_pyzmq(
    pipexec,
    pyexec,
    pyzmq_version,
    build_version,
    arch,
    build,
    tmp_path: pathlib.Path,
) -> None:

    if pyzmq_version == "23.2.0" and "3.12" in build_version:
        pytest.xfail(f"{pyzmq_version} does not install on 3.12")

    if pyzmq_version == "23.2.0" and "3.13" in build_version:
        pytest.xfail(f"{pyzmq_version} does not install on 3.13")

    if pyzmq_version == "23.2.0" and sys.platform == "darwin":
        pytest.xfail("pyzmq 23.2.0 fails on macos arm64")

    if pyzmq_version == "23.2.0" and sys.platform == "win32":
        pytest.xfail("vcredist not found as of 9/9/24")

    if pyzmq_version == "25.1.2" and "3.13" in build_version:
        pytest.xfail(f"{pyzmq_version} does not install on 3.13")

    if pyzmq_version == "25.1.2" and sys.platform == "win32":
        pytest.xfail("pyzmq 25.1.2 fails on windows")

    if pyzmq_version == "26.2.0" and sys.platform == "win32":
        pytest.xfail("vcredist not found as of 9/9/24")

    if pyzmq_version == "26.4.0" and sys.platform == "win32":
        pytest.xfail("Needs troubleshooting 4/12/25")

    _install_ppbt(pyexec)

    env = os.environ.copy()

    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "--upgrade",
            "pip",
            "setuptools",
        ],
        env=env,
    )
    if pyzmq_version == "26.2.0" and sys.platform == "darwin":
        pytest.xfail(f"{pyzmq_version} does not install on m1 mac")
    if pyzmq_version == "26.2.0" and sys.platform == "darwin":
        env[
            "CFLAGS"
        ] = f"{env.get('CFLAGS', '')} -DCMAKE_OSX_ARCHITECTURES='arm64' -DZMQ_HAVE_CURVE=0"
    env = os.environ.copy()
    if sys.platform == "linux":
        p = subprocess.run(
            [
                pyexec,
                "-m",
                "relenv",
                "buildenv",
                "--json",
            ],
            capture_output=True,
        )
        try:
            buildenv = json.loads(p.stdout)
        except json.JSONDecodeError:
            assert (
                False
            ), f"Failed to decode json: {p.stdout.decode()} {p.stderr.decode()}"
        for k in buildenv:
            env[k] = buildenv[k]

    env["ZMQ_PREFIX"] = "bundled"
    env["RELENV_BUILDENV"] = "yes"
    env["USE_STATIC_REQUIREMENTS"] = "1"

    if sys.platform == "linux":
        fake_bsd_root = tmp_path / "fake_libbsd"
        (fake_bsd_root / "bsd").mkdir(parents=True, exist_ok=True)
        (fake_bsd_root / "bsd" / "string.h").write_text(
            textwrap.dedent(
                """\
                #ifndef RELENV_FAKE_BSD_STRING_H
                #define RELENV_FAKE_BSD_STRING_H

                #include <stddef.h>

                #ifdef __cplusplus
                extern "C" {
                #endif

                size_t strlcpy(char *dst, const char *src, size_t siz);
                size_t strlcat(char *dst, const char *src, size_t siz);

                #ifdef __cplusplus
                }
                #endif

                #endif  /* RELENV_FAKE_BSD_STRING_H */
                """
            )
        )
        (fake_bsd_root / "string.c").write_text(
            textwrap.dedent(
                """\
                #include <stddef.h>
                #include <string.h>

                static size_t relenv_strlen(const char *s) {
                    size_t len = 0;
                    if (s == NULL) {
                        return 0;
                    }
                    while (s[len] != '\\0') {
                        ++len;
                    }
                    return len;
                }

                static size_t relenv_strnlen(const char *s, size_t maxlen) {
                    size_t len = 0;
                    if (s == NULL) {
                        return 0;
                    }
                    while (len < maxlen && s[len] != '\\0') {
                        ++len;
                    }
                    return len;
                }

                size_t strlcpy(char *dst, const char *src, size_t siz) {
                    size_t src_len = relenv_strlen(src);
                    if (siz == 0 || dst == NULL) {
                        return src_len;
                    }
                    size_t copy = src_len;
                    if (copy >= siz) {
                        copy = siz - 1;
                    }
                    if (copy > 0 && src != NULL) {
                        memcpy(dst, src, copy);
                    }
                    dst[copy] = '\\0';
                    return src_len;
                }

                size_t strlcat(char *dst, const char *src, size_t siz) {
                    size_t dst_len = relenv_strnlen(dst, siz);
                    size_t src_len = relenv_strlen(src);
                    size_t initial_len = dst_len;
                    if (dst == NULL || dst_len >= siz) {
                        return initial_len + src_len;
                    }
                    size_t space = (siz > dst_len + 1) ? siz - dst_len - 1 : 0;
                    size_t copy = 0;
                    if (space > 0 && src != NULL) {
                        copy = src_len;
                        if (copy > space) {
                            copy = space;
                        }
                        if (copy > 0) {
                            memcpy(dst + dst_len, src, copy);
                        }
                        dst_len += copy;
                    }
                    dst[dst_len] = '\\0';
                    return initial_len + src_len;
                }
                """
            )
        )
        include_flag = f"-I{fake_bsd_root}"
        for key in ("CFLAGS", "CXXFLAGS", "CPPFLAGS"):
            env[key] = " ".join(filter(None, [env.get(key, ""), include_flag])).strip()
        env["CPATH"] = ":".join(
            filter(None, [str(fake_bsd_root), env.get("CPATH", "")])
        )
        for key in ("C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
            env[key] = ":".join(filter(None, [str(fake_bsd_root), env.get(key, "")]))
        cc_value = env.get("CC")
        if cc_value:
            cc_args = shlex.split(cc_value)
        else:
            cc_path = shutil.which("cc") or shutil.which("gcc")
            assert cc_path, "C compiler not found for libbsd shim"
            cc_args = [cc_path]
        obj_path = fake_bsd_root / "string.o"
        compile_result = subprocess.run(
            cc_args
            + [
                "-c",
                "-O2",
                "-fPIC",
                "-o",
                str(obj_path),
                str(fake_bsd_root / "string.c"),
            ],
            env=env,
        )
        assert compile_result.returncode == 0, "Failed to compile libbsd shim"
        ar_value = env.get("AR")
        if ar_value:
            ar_args = shlex.split(ar_value)
        else:
            ar_path = shutil.which("ar")
            assert ar_path, "Archiver not found for libbsd shim"
            ar_args = [ar_path]
        libbsd_static = fake_bsd_root / "libbsd.a"
        archive_result = subprocess.run(
            ar_args + ["rcs", str(libbsd_static), str(obj_path)],
            env=env,
        )
        assert archive_result.returncode == 0, "Failed to archive libbsd shim"
        lib_dir_flag = f"-L{fake_bsd_root}"
        env["LDFLAGS"] = " ".join(
            filter(None, [lib_dir_flag, env.get("LDFLAGS", "")])
        ).strip()
        env["LIBS"] = " ".join(filter(None, ["-lbsd", env.get("LIBS", "")])).strip()
        env["LIBRARY_PATH"] = ":".join(
            filter(None, [str(fake_bsd_root), env.get("LIBRARY_PATH", "")])
        )
        env["ac_cv_func_strlcpy"] = "yes"
        env["ac_cv_func_strlcat"] = "yes"
        env["ac_cv_have_decl_strlcpy"] = "yes"
        env["ac_cv_have_decl_strlcat"] = "yes"

    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "-v",
            "--no-cache-dir",
            "--no-binary=:all:",
            "--use-pep517",
            f"pyzmq=={pyzmq_version}",
        ],
        env=env,
    )
    assert p.returncode == 0, "Failed to pip install package requirements"

    if shutil.which("docker"):
        subprocess.run(
            [
                "docker",
                "run",
                "-v",
                f"{build}:/test",
                "amazonlinux:2",
                "/test/bin/python3",
                "-c",
                "import zmq",
            ],
            check=True,
        )


def test_pip_install_cryptography(pipexec, pyexec):
    _install_ppbt(pyexec)
    packages = [
        "cryptography",
    ]
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache-dir"], env=env)
        assert p.returncode == 0, f"Failed to pip install {name}"


def test_pip_install_idem(pipexec, pyexec):
    _install_ppbt(pyexec)
    packages = [
        "idem",
    ]
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    for name in packages:
        p = subprocess.run([str(pipexec), "install", name, "--no-cache-dir"], env=env)
        assert p.returncode == 0, f"Failed to pip install {name}"


def test_pip_install_and_import_libcloud(pipexec, pyexec):
    _install_ppbt(pyexec)
    name = "apache-libcloud"
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    p = subprocess.run([str(pipexec), "install", name, "--no-cache-dir"], env=env)
    assert p.returncode == 0, f"Failed to pip install {name}"

    import_name = "libcloud.security"
    import_ret = subprocess.run([str(pyexec), "-c", f"import {import_name}"])
    assert import_ret.returncode == 0, f"Failed to import {import_name}"


def test_pip_install_salt_pip_dir(pipexec, pyexec, build, build_version, arch):

    if "3.12" in build_version:
        pytest.xfail("Don't try to install on 3.12 yet")

    if build_version.startswith("3.11") and sys.platform == "darwin":

        pytest.xfail("Known failure on py 3.11 macos")

    if sys.platform == "win32" and arch == "amd64":
        pytest.xfail("Known failure on windows amd64")

    if sys.platform == "darwin" and "3.13" in build_version:
        pytest.xfail("Salt does not work with 3.13 on macos yet")

    _install_ppbt(pyexec)
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    env["RELENV_DEBUG"] = "yes"
    env["RELENV_PIP_DIR"] = "yes"
    p = subprocess.run([str(pipexec), "install", "salt", "--no-cache-dir"], env=env)
    assert p.returncode == 0, "Failed to pip install salt"

    names = ["salt", "salt-call", "salt-master", "salt-minion"]
    if sys.platform == "win32":
        names = ["salt-call.exe", "salt-minion.exe"]

    for _ in names:
        script = pathlib.Path(build) / _
        assert script.exists()


def test_nox_virtualenvs(pipexec, pyexec, build, tmp_path):
    _install_ppbt(pyexec)
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    env["RELENV_DEBUG"] = "yes"
    name = "nox"

    p = subprocess.run([str(pipexec), "install", name, "--no-cache-dir"], env=env)
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
def test_pip_install_m2crypto_system_ssl(pipexec, pyexec):
    pytest.xfail("Failure needs troubleshooting")
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    env["LDFLAGS"] = "-L/usr/lib"
    env["CFLAGS"] = "-I/usr/include"
    env["SWIG_FEATURES"] = "-I/usr/include"
    p = subprocess.run(
        ["swig", "-version"],
    )
    p = subprocess.run(
        [str(pipexec), "install", "m2crypto", "--no-cache-dir", "-v"],
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


SSLVERSION = """
import ctypes
import ctypes.util
import platform

def get_openssl_version():
    '''
    Programmatically discovers the OpenSSL version using ctypes.
    '''
    # Determine the library name based on the operating system
    if platform.system() == "Windows":
        lib_name = ctypes.util.find_library("libcrypto-3") or ctypes.util.find_library("libcrypto-1_1")
    else:
        lib_name = ctypes.util.find_library("crypto")

    if not lib_name:
        print("Could not find OpenSSL libcrypto library.")
        return None, None

    libcrypto = ctypes.CDLL(lib_name)

    # Define the C function prototypes
    libcrypto.OpenSSL_version_num.restype = ctypes.c_ulong
    libcrypto.OpenSSL_version.argtypes = [ctypes.c_int]
    libcrypto.OpenSSL_version.restype = ctypes.c_char_p

    # Call the C functions
    version_num_hex = libcrypto.OpenSSL_version_num()
    version_str = libcrypto.OpenSSL_version(0).decode("utf-8")

    # Parse the numeric version
    # The version number format is MNNFFPPS
    major = (version_num_hex >> 28) & 0xFF
    minor = (version_num_hex >> 20) & 0xFF
    patch = (version_num_hex >> 4) & 0xFF

    return (major, minor, patch)

if __name__ == "__main__":
    print(
        ",".join([str(x) for x in get_openssl_version()]
        )
    )
"""


@pytest.fixture
def ssl_version(pyexec, tmp_path):
    file = tmp_path / "script.py"
    file.write_text(SSLVERSION)
    ret = subprocess.run([pyexec, str(file)], capture_output=True)
    print(ret)
    return tuple([int(x) for x in ret.stdout.decode().strip().split(",")])


@pytest.mark.skip_unless_on_linux
@pytest.mark.parametrize(
    "m2crypto_version",
    ["0.38.0", "0.44.0", "0.46.0"],
)
def test_pip_install_m2crypto_relenv_ssl(
    m2crypto_version, pipexec, pyexec, build, build_version, minor_version, ssl_version
):
    if m2crypto_version == "0.38.0" and minor_version in ["3.12", "3.13"]:
        pytest.xfail("Fails due to no distutils")

    if ssl_version >= (3, 5) and m2crypto_version in ["0.38.0", "0.44.0"]:
        pytest.xfail("Openssl Needs newer m2crypto")

    _install_ppbt(pyexec)

    p = subprocess.run(
        [
            pyexec,
            "-m",
            "relenv",
            "buildenv",
            "--json",
        ],
        capture_output=True,
    )
    try:
        buildenv = json.loads(p.stdout)
    except json.JSONDecodeError:
        assert False, f"Failed to decode json: {p.stdout.decode()} {p.stderr.decode()}"
    env = os.environ.copy()
    for k in buildenv:
        env[k] = buildenv[k]

    # assert False, buildenv["TOOLCHAIN_PATH"]
    env["RELENV_BUILDENV"] = "yes"
    env["RELENV_DEBUG"] = "yes"
    env["CFLAGS"] = f"{env['CFLAGS']} -I{build}/include/python{minor_version}"
    env["SWIG_FEATURES"] = f"-I{build}/include -I{build}/include/python{minor_version}"
    p = subprocess.run(
        ["swig", "-version"],
    )
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            f"m2crypto=={m2crypto_version}",
            "--no-cache-dir",
            "--no-binary=':all:'",
            "-v",
        ],
        env=env,
        stderr=subprocess.PIPE,
    )
    assert p.returncode == 0, "Failed to pip install m2crypto"
    gcc = str(pathlib.Path(buildenv["TOOLCHAIN_PATH"]) / "bin" / f"{get_triplet()}-gcc")
    include = str(pathlib.Path(build) / "include")
    found_include = False
    for _ in p.stderr.splitlines():
        line = _.decode()
        if gcc in line:
            for arg in line.split():
                if arg == f"-I{include}":
                    found_include = True
    assert found_include, f"{gcc}\n{include}\n{p.stderr.decode()}"
    env.pop("RELENV_DEBUG")
    p = subprocess.run(
        [str(pyexec), "-c", "import M2Crypto"],
        env=env,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        check=False,
    )
    assert p.returncode == 0, (p.stdout, p.stderr)


@pytest.mark.skip_on_windows
def test_shebangs(pipexec, build, minor_version):
    def validate_shebang(path):
        with open(path, "r") as fp:
            return fp.read(9) == "#!/bin/sh"

    path = build / "bin" / "pip3"
    assert path.exists()
    assert validate_shebang(path)
    if "3.13" not in minor_version:
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
def test_moving_pip_installed_c_extentions(pipexec, pyexec, build, minor_version):
    _install_ppbt(pyexec)
    env = os.environ.copy()
    _setup_buildenv(pyexec, env)
    env["RELENV_DEBUG"] = "yes"
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
def test_cryptography_rpath(
    pyexec, pipexec, build, minor_version, cryptography_version
):
    _install_ppbt(pyexec)

    def find_library(path, search):
        for root, dirs, files in os.walk(path):
            for fname in files:
                if fname.startswith(search) and fname.endswith(".so"):
                    return fname

    env = os.environ.copy()
    _setup_buildenv(pyexec, env)
    env["RELENV_BUILDENV"] = "yes"
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "-v",
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
        osslinked = find_library(bindings, "_openssl")
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
    assert valid, p.stdout.decode()


@pytest.mark.skip_unless_on_darwin
@pytest.mark.parametrize("cryptography_version", ["42.0.5", "40.0.1"])
def test_cryptography_rpath_darwin(pipexec, build, minor_version, cryptography_version):
    # def find_library(path, search):
    #    for root, dirs, files in os.walk(path):
    #        for fname in files:
    #            if fname.startswith(search) and fname.endswith(".so"):
    #                return fname

    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    env["OPENSSL_DIR"] = f"{build}"

    if minor_version == "3.13":
        env["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"

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
    p = subprocess.run(
        [
            "otool",
            "-L",
            f"{build}/lib/python{minor_version}/site-packages/cryptography/hazmat/bindings/_rust.abi3.so",
        ],
        capture_output=True,
    )
    assert "/usr/local" not in p.stdout.decode(), p.stdout.decode()


@pytest.mark.skip_unless_on_linux
def test_install_pycurl(pipexec, pyexec, build):
    _install_ppbt(pyexec)
    curlver = "8.0.1"

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
        [str(pipexec), "install", "pycurl", "--no-cache-dir"], env=env, check=True
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


@pytest.fixture
def build_dir(tmp_path):
    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(orig)


@pytest.mark.skipif(True, reason="pipeline failures due to 403 forbbiden resource")
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
def test_install_libgit2(pipexec, build, minor_version, build_dir, versions):
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
            "--no-cache-dir",
            "--no-binary=:all:",
        ],
        check=True,
        env=env,
    )


@pytest.mark.skip_unless_on_linux
def test_install_python_ldap(pipexec, pyexec, build):
    _install_ppbt(pyexec)
    saslver = "2.1.28"
    ldapver = "2.5.14"

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
    make -j"$(nproc)"
    make install
    cd ..

    # Build and Install Open LDAP
    wget https://www.openldap.org/software/download/OpenLDAP/openldap-release/openldap-{ldapver}.tgz
    tar xvf openldap-{ldapver}.tgz
    cd openldap-{ldapver}
    ./configure --prefix=$RELENV_PATH
    make -j"$(nproc)"
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
    _setup_buildenv(pyexec, env)
    env["RELENV_DEBUG"] = "yes"
    env["RELENV_BUILDENV"] = "yes"

    subprocess.run(
        [str(pipexec), "install", "python-ldap", "--no-cache-dir", "--no-binary=:all:"],
        check=True,
        env=env,
    )


@pytest.mark.skip_unless_on_linux
def test_install_python_ldap_system_libs(pipexec):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    subprocess.run(
        [str(pipexec), "install", "python-ldap", "--no-cache-dir", "--no-binary=:all:"],
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
    exec_line = ""
    for line in pathlib.Path(extras / "bin" / "cowsay").read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith('"exec"'):
            exec_line = stripped
            break
    assert (
        exec_line
        == '"exec" "$(dirname "$(readlink -f "$0")")/../../bin/python{}" "$0" "$@"'.format(
            minor_version
        )
    )


@pytest.mark.skip_unless_on_linux
def test_install_shebang_pip_24_2(pipexec, build, minor_version):
    subprocess.run(
        [str(pipexec), "install", "--upgrade", "pip==24.2"],
        check=True,
    )
    subprocess.run(
        [str(pipexec), "install", "cowsay"],
        check=True,
    )
    ret = subprocess.run(
        [str(build / "bin" / "cowsay"), "-t", "moo"],
        check=False,
    )
    assert ret.returncode == 0


@pytest.mark.skip_unless_on_linux
def test_install_shebang_pip_25_2(pipexec, build, minor_version):
    subprocess.run(
        [str(pipexec), "install", "--upgrade", "pip==25.2"],
        check=True,
    )
    subprocess.run(
        [str(pipexec), "install", "cowsay"],
        check=True,
    )
    ret = subprocess.run(
        [str(build / "bin" / "cowsay"), "-t", "moo"],
        check=False,
    )
    assert ret.returncode == 0


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


def test_install_with_target_cffi_versions(pipexec, pyexec, build, build_version):
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    if "3.13" not in build_version:
        subprocess.run(
            [str(pipexec), "install", "cffi==1.14.6"],
            check=True,
            env=env,
        )
        subprocess.run(
            [str(pipexec), "install", "cffi==1.16.0", f"--target={extras}"],
            check=True,
            env=env,
        )
    subprocess.run(
        [str(pipexec), "install", "cffi==1.17.1", f"--target={extras}"],
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
    proc.stdout.decode().strip() == "1.17.1"


def test_install_with_target_no_ignore_installed(pipexec, pyexec, build, build_version):
    if build_version.startswith("3.13"):
        cffi = "cffi==1.17.1"
        pygit2 = "pygit2==1.16.0"
    elif build_version.startswith("3.12"):
        cffi = "cffi==1.16.0"
        pygit2 = "pygit2==1.14.0"
    else:
        cffi = "cffi==1.15.1"
        pygit2 = "pygit2==1.12.0"
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    install_cffi = subprocess.run(
        [str(pipexec), "install", cffi],
        # check=True,
        env=env,
    )
    assert install_cffi.returncode == 0
    install_pygit2 = subprocess.run(
        [str(pipexec), "install", pygit2, f"--target={extras}"],
        env=env,
        capture_output=True,
    )
    assert install_pygit2.returncode == 0, (
        install_pygit2.stdout,
        install_pygit2.stderr,
    )
    out = install_pygit2.stdout.decode()
    assert "already satisfied: cffi" in out
    assert "installed cffi" not in out


def test_install_with_target_ignore_installed(pipexec, pyexec, build, build_version):
    if build_version.startswith("3.13"):
        cffi = "cffi==1.17.1"
        pygit2 = "pygit2==1.16.0"
    elif build_version.startswith("3.12"):
        cffi = "cffi==1.16.0"
        pygit2 = "pygit2==1.14.0"
    else:
        cffi = "cffi==1.15.1"
        pygit2 = "pygit2==1.12.0"
    env = os.environ.copy()
    env["RELENV_DEBUG"] = "yes"
    extras = build / "extras"
    subprocess.run(
        [str(pipexec), "install", cffi],
        check=True,
        env=env,
    )
    proc = subprocess.run(
        [
            str(pipexec),
            "install",
            pygit2,
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


@pytest.mark.skipif(True, reason="This test is no longer valid, refactor needed")
@pytest.mark.skip_on_windows
def test_no_legacy_hashlib(pipexec, pyexec, build):
    """
    Verify hashlib can find the legacy openssl provider.
    """
    env = {
        "OPENSSL_CONF": str(build / "openssl.cnf"),
        "OPENSSL_MODULES": str(build / "lib" / "ossl-modules"),
    }
    with open(env["OPENSSL_CONF"], "w") as fp:
        fp.write(
            textwrap.dedent(
                """
            HOME			= .
            openssl_conf = openssl_init
            [openssl_init]
            providers = provider_sect
            [provider_sect]
            default = default_sect
            [default_sect]
            activate = 1
            """
            )
        )
    proc = subprocess.run(
        [
            pyexec,
            "-c",
            "import hashlib; print(hashlib.algorithms_available)",
        ],
        check=True,
        stdout=subprocess.PIPE,
        env=env,
    )
    assert b"md4" not in proc.stdout


@pytest.mark.skip_on_windows
def test_legacy_hashlib(pipexec, pyexec, build):
    """
    Verify hashlib can find the legacy openssl provider.
    """
    env = {
        "OPENSSL_CONF": str(build / "openssl.cnf"),
        "OPENSSL_MODULES": str(build / "lib" / "ossl-modules"),
    }

    # https://github.com/openssl/openssl/issues/16079
    if sys.platform == "darwin":
        env["DYLD_LIBRARY_PATH"] = str(build / "lib")

    with open(env["OPENSSL_CONF"], "w") as fp:
        fp.write(
            textwrap.dedent(
                """
            HOME			= .
            openssl_conf = openssl_init
            [openssl_init]
            providers = provider_sect
            [provider_sect]
            default = default_sect
            legacy = legacy_sect
            [default_sect]
            activate = 1
            [legacy_sect]
            activate = 1
            """
            )
        )
    proc = subprocess.run(
        [
            pyexec,
            "-c",
            "import hashlib; print(hashlib.algorithms_available)",
        ],
        check=True,
        stdout=subprocess.PIPE,
        env=env,
    )
    with open(env["OPENSSL_CONF"], "r") as fp:
        print(fp.read())
    assert b"md4" in proc.stdout


@pytest.mark.skipif(True, reason="Passes outside of pipelines, needs troubleshooting")
@pytest.mark.skip_unless_on_linux
@pytest.mark.skip_if_binaries_missing("openssl")
def test_hashlib_fips_module(pipexec, pyexec, build):
    """
    Verify hashlib works with fips module.
    """
    proc = subprocess.run(
        [
            "openssl",
            "fipsinstall",
            "-out",
            str(build / "fipsmodule.cnf"),
            "-module",
            str(build / "lib" / "ossl-modules" / "fips.so"),
        ],
        check=True,
    )
    env = os.environ.copy()
    env.update(
        {
            "OPENSSL_CONF": str(build / "openssl.cnf"),
            "OPENSSL_MODULES": str(build / "lib" / "ossl-modules"),
        }
    )
    with open(env["OPENSSL_CONF"], "w") as fp:
        fp.write(
            textwrap.dedent(
                """
            HOME			= .
            openssl_conf = openssl_init
            [openssl_init]
            providers = provider_sect
            alg_section = algorithm_sect
            .include fipsmodule.cnf
            [provider_sect]
            default = default_sect
            fips = fips_sect
            [default_sect]
            activate = 1
            [algorithm_sect]
            default_properties = fips=yes
            """
            )
        )
    proc = subprocess.run(
        [
            pyexec,
            "-c",
            "import hashlib; hashlib.md5(b'')",
        ],
        check=False,
        env=env,
        capture_output=True,
    )
    assert b"ValueError" in proc.stderr


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


@pytest.mark.skip_unless_on_linux
def test_install_with_target_namespaces(pipexec, build, minor_version, build_version):
    env = os.environ.copy()
    os.chdir(build)
    env["RELENV_DEBUG"] = "yes"

    subprocess.run(
        [
            str(pipexec),
            "install",
            "cython",
            "setuptools",
            "-v",
            "--no-build-isolation",
        ],
        check=True,
        env=env,
    )

    extras = build / "extras"
    subprocess.run(
        [
            str(pipexec),
            "install",
            "saltext.vmware",
            f"--target={extras}",
            "-v",
            "--no-build-isolation",
        ],
        check=True,
        env=env,
    )
    assert (extras / "saltext" / "vmware").exists()
    subprocess.run(
        [
            str(pipexec),
            "install",
            "saltext.bitwarden",
            f"--target={extras}",
            "--no-build-isolation",
        ],
        check=True,
        env=env,
    )
    assert (extras / "saltext" / "bitwarden").exists()


@pytest.mark.skip_unless_on_linux
def test_debugpy(pipexec, build, arch, minor_version):
    if "3.13" in minor_version:
        pytest.xfail("Failes on python 3.13.0")
    if arch == "arm64":
        pytest.xfail("Failes on arm64")

    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "debugpy",
        ]
    )
    assert p.returncode == 0, "Failed install debugpy"
    server = subprocess.Popen(
        [
            str(build / "bin" / "python3"),
            "-Xfrozen_modules=off",
            "-c",
            "import debugpy; debugpy.listen(5678); debugpy.wait_for_client()",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Simply makeing a tcp connection to the port isn't enough to cuase
    # debugpy.wait_for_client to return. For now, just wait 5 seconds to see if
    # there is any output from debugpy and if not, consider this a success.
    time.sleep(5)
    server.kill()
    server.wait()
    assert server.stdout.read() == b""
    assert server.stderr.read() == b""


@pytest.mark.skip_unless_on_linux
def test_install_libvirt(pipexec, build, minor_version):
    extras = build / "extras"
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "--no-cache-dir",
            "--no-binary=:all:",
            f"--target={extras}",
            "libvirt-python",
        ]
    )
    assert p.returncode == 0, "Failed install libvirt-python"
    # Validate libvirt.py ends up in the extras directory
    assert (extras / "libvirt.py").exists()


@pytest.mark.skip_unless_on_linux
def test_install_mysqlclient(pipexec, build, minor_version):
    version = "2.2.4"
    extras = build / "extras"
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "--no-cache-dir",
            "--no-binary=:all:",
            f"--target={extras}",
            f"mysqlclient=={version}",
        ]
    )
    assert p.returncode == 0, "Failed install mysqlclient"
    assert (extras / "MySQLdb").exists()
    assert (extras / f"mysqlclient-{version}.dist-info").exists()


@pytest.mark.skip_unless_on_linux
def test_install_m2crypto(pipexec, build, minor_version):
    pytest.xfail("Failure needs troubleshooting")
    version = "0.42.0"
    extras = build / "extras"
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "--no-cache-dir",
            "--no-binary=:all:",
            f"--target={extras}",
            f"m2crypto=={version}",
        ]
    )
    assert p.returncode == 0, "Failed install M2Crypto"
    assert (extras / "M2Crypto").exists()
    assert (extras / f"M2Crypto-{version}.dist-info").exists()


@pytest.mark.skip_unless_on_linux
def test_install_pyinotify_w_latest_pip(pipexec, build, minor_version):
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "--upgrade",
            "pip",
        ]
    )
    extras = build / "extras"
    p = subprocess.run(
        [
            str(pipexec),
            "install",
            "--no-cache-dir",
            "--no-binary=:all:",
            f"--target={extras}",
            "pyinotify",
        ]
    )
    assert p.returncode == 0, "Failed install pyinotify"
    assert (extras / "pyinotify.py").exists()


@pytest.mark.skip_unless_on_linux
def test_install_editable_package(pipexec, pyexec, build, minor_version, tmp_path):
    _install_ppbt(pyexec)
    os.chdir(tmp_path)
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    p = subprocess.run(
        [
            "git",
            "clone",
            "https://github.com/salt-extensions/saltext-zabbix.git",
            "--depth",
            "1",
        ],
        env=env,
    )
    assert p.returncode == 0
    p = subprocess.run([str(pipexec), "install", "-e", "saltext-zabbix"], env=env)
    assert p.returncode == 0
    p = subprocess.run([str(pyexec), "-c", "import saltext.zabbix"], env=env)
    assert p.returncode == 0


@pytest.mark.skip_unless_on_linux
def test_install_editable_package_in_extras(
    pipexec, pyexec, build, minor_version, tmp_path
):
    _install_ppbt(pyexec)
    sitepkgs = pathlib.Path(build) / "lib" / f"python{minor_version}" / "site-packages"

    (sitepkgs / "_extras.pth").write_text("import _extras; _extras.setup(__file__)")
    (sitepkgs / "_extras.py").write_text(EXTRAS_PY)
    extras = pathlib.Path(build) / f"extras-{minor_version}"
    extras.mkdir()
    os.chdir(tmp_path)
    env = os.environ.copy()
    env["RELENV_BUILDENV"] = "yes"
    p = subprocess.run(
        [
            "git",
            "clone",
            "https://github.com/salt-extensions/saltext-zabbix.git",
            "--depth",
            "1",
        ],
        env=env,
    )
    assert p.returncode == 0
    p = subprocess.run(
        [str(pipexec), "install", f"--target={extras}", "-e", "saltext-zabbix"], env=env
    )
    assert p.returncode == 0
    p = subprocess.run([str(pyexec), "-c", "import saltext.zabbix"], env=env)
    assert p.returncode == 0


@pytest.fixture
def rockycontainer(build):
    if not shutil.which("docker"):
        pytest.skip(reason="No docker binary found")
    name = f"rocky10-{uuid.uuid4().hex}"
    subprocess.run(
        [
            "docker",
            "create",
            "--name",
            name,
            "-v",
            f"{build}:/test",
            "--entrypoint",
            "tail",
            "rockylinux/rockylinux:10",
            "-f",
            "/dev/null",
        ],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "start",
            name,
        ],
        capture_output=True,
        check=True,
    )
    try:
        yield name
    finally:
        subprocess.run(
            [
                "docker",
                "stop",
                name,
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "docker",
                "rm",
                name,
            ],
            capture_output=True,
            check=True,
        )


@pytest.mark.skip_on_windows
def test_no_openssl_binary(rockycontainer, pipexec, pyexec, build):
    _install_ppbt(pyexec)
    env = os.environ.copy()
    _setup_buildenv(pyexec, env)
    env["RELENV_BUILDENV"] = "yes"
    if sys.platform == "linux":
        toolchain_path = pathlib.Path(env["TOOLCHAIN_PATH"])
        triplet = env["TRIPLET"]
        sysroot_lib = toolchain_path / triplet / "sysroot" / "lib"
        sysroot_lib.mkdir(parents=True, exist_ok=True)
        bz2_sources = sorted(
            (pathlib.Path(build) / "lib").glob("libbz2.so*"),
            key=lambda p: len(p.name),
        )
        if not bz2_sources:
            pytest.fail(
                "libbz2.so not found in relenv build; cryptography build cannot proceed"
            )
        for bz2_source in bz2_sources:
            target = sysroot_lib / bz2_source.name
            if target.exists() or target.is_symlink():
                if target.is_symlink():
                    try:
                        if target.readlink() == bz2_source:
                            continue
                    except OSError:
                        pass
                target.unlink()
            target.symlink_to(bz2_source)
    proc = subprocess.run(
        [
            str(pipexec),
            "install",
            "cryptography",
            "--no-binary=:all:",
            "--no-cache-dir",
        ],
        env=env,
    )
    assert proc.returncode == 0
    proc = subprocess.run(
        [
            "docker",
            "exec",
            rockycontainer,
            "test/bin/python3",
            "-c",
            "import cryptography.exceptions",
        ],
        capture_output=True,
    )

    errors = proc.stderr.decode()
    assert "legacy provider failed to load" not in errors


@pytest.mark.skip_unless_on_darwin
def test_darwin_python_linking(pipexec, pyexec, build, minor_version):
    proc = subprocess.run(["otool", "-L", str(pyexec)], capture_output=True, check=True)
    assert "/usr/local/opt" not in proc.stdout.decode()


def test_import_ssl_module(pyexec):
    proc = subprocess.run(
        [pyexec, "-c", "import ssl"], capture_output=True, check=False
    )
    assert proc.returncode == 0
    assert proc.stdout.decode() == ""
    assert proc.stderr.decode() == ""


@pytest.mark.skip_unless_on_linux
@pytest.mark.parametrize("pip_version", ["25.2", "25.3"])
def test_install_setuptools_25_2_to_25_3(pipexec, build, minor_version, pip_version):
    """
    Validate we handle the changes to pip._internal.req.InstallRequirement.install signature.
    """
    subprocess.run(
        [str(pipexec), "install", "--upgrade", f"pip=={pip_version}"],
        check=True,
    )
    subprocess.run(
        [
            str(pipexec),
            "install",
            "--upgrade",
            "--no-binary=:all:",
            "--no-cache-dir",
            "setuptools",
        ],
        check=True,
    )


def test_expat_version(pyexec):
    """
    Verify that the build contains the correct expat version.

    This validates that update_expat() successfully updated the bundled
    expat library to match the version in python-versions.json.

    Works on all platforms: Linux, Darwin (macOS), and Windows.
    """
    from relenv.build.common import get_dependency_version

    # Map sys.platform to relenv platform names
    platform_map = {
        "linux": "linux",
        "darwin": "darwin",
        "win32": "win32",
    }
    platform = platform_map.get(sys.platform)
    if not platform:
        pytest.skip(f"Unknown platform: {sys.platform}")

    # Get expected version from python-versions.json
    expat_info = get_dependency_version("expat", platform)
    if not expat_info:
        pytest.skip(f"No expat version defined in python-versions.json for {platform}")

    expected_version = expat_info["version"]

    # Get actual version from the build
    proc = subprocess.run(
        [str(pyexec), "-c", "import pyexpat; print(pyexpat.EXPAT_VERSION)"],
        capture_output=True,
        check=True,
    )

    actual_version_str = proc.stdout.decode().strip()
    # Format is "expat_X_Y_Z", extract version
    assert actual_version_str.startswith(
        "expat_"
    ), f"Unexpected EXPAT_VERSION format: {actual_version_str}"

    # Convert "expat_2_7_3" -> "2.7.3"
    actual_version = actual_version_str.replace("expat_", "").replace("_", ".")

    assert actual_version == expected_version, (
        f"Expat version mismatch on {platform}: expected {expected_version}, "
        f"found {actual_version} (from {actual_version_str})"
    )


def test_sqlite_version(pyexec):
    """
    Verify that the build contains the correct SQLite version.

    This validates that SQLite was built with the version specified
    in python-versions.json.

    Works on all platforms: Linux, Darwin (macOS), and Windows.
    """
    from relenv.build.common import get_dependency_version

    # Map sys.platform to relenv platform names
    platform_map = {
        "linux": "linux",
        "darwin": "darwin",
        "win32": "win32",
    }
    platform = platform_map.get(sys.platform)
    if not platform:
        pytest.skip(f"Unknown platform: {sys.platform}")

    # Get expected version from python-versions.json
    sqlite_info = get_dependency_version("sqlite", platform)
    if not sqlite_info:
        pytest.skip(f"No sqlite version defined in python-versions.json for {platform}")

    expected_version = sqlite_info["version"]

    # Get actual version from the build
    proc = subprocess.run(
        [str(pyexec), "-c", "import sqlite3; print(sqlite3.sqlite_version)"],
        capture_output=True,
        check=True,
    )

    actual_version = proc.stdout.decode().strip()

    # SQLite version in JSON is like "3.50.4.0" but runtime shows "3.50.4"
    # So we need to handle both formats
    if expected_version.count(".") == 3:
        # Remove trailing .0 for comparison
        expected_version = ".".join(expected_version.split(".")[:3])

    assert actual_version == expected_version, (
        f"SQLite version mismatch on {platform}: expected {expected_version}, "
        f"found {actual_version}"
    )


def test_openssl_version(pyexec):
    """
    Verify that the build contains the correct OpenSSL version.

    This validates that OpenSSL was built with the version specified
    in python-versions.json.

    Works on all platforms: Linux, Darwin (macOS), and Windows.
    """
    import re

    from relenv.build.common import get_dependency_version

    # Map sys.platform to relenv platform names
    platform_map = {
        "linux": "linux",
        "darwin": "darwin",
        "win32": "win32",
    }
    platform = platform_map.get(sys.platform)
    if not platform:
        pytest.skip(f"Unknown platform: {sys.platform}")

    # Get expected version from python-versions.json
    openssl_info = get_dependency_version("openssl", platform)
    if not openssl_info:
        pytest.skip(
            f"No openssl version defined in python-versions.json for {platform}"
        )

    expected_version = openssl_info["version"]

    # Get actual version from the build
    proc = subprocess.run(
        [str(pyexec), "-c", "import ssl; print(ssl.OPENSSL_VERSION)"],
        capture_output=True,
        check=True,
    )

    actual_version_str = proc.stdout.decode().strip()
    # Format is "OpenSSL 3.5.4 30 Sep 2025"
    # Extract version number
    match = re.search(r"OpenSSL (\d+\.\d+\.\d+)", actual_version_str)
    if not match:
        pytest.fail(f"Could not parse OpenSSL version from: {actual_version_str}")

    actual_version = match.group(1)

    assert actual_version == expected_version, (
        f"OpenSSL version mismatch on {platform}: expected {expected_version}, "
        f"found {actual_version} (from {actual_version_str})"
    )
