# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2
# mypy: ignore-errors
"""
The windows build process.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import pathlib
import shutil
import sys
import tarfile
import time
from typing import IO, MutableMapping, Union

from .common import (
    Dirs,
    builds,
    create_archive,
    get_dependency_version,
    install_runtime,
    patch_file,
    update_ensurepip,
    update_sbom_checksums,
)
from ..common import (
    WIN32,
    arches,
    MODULE_DIR,
    download_url,
    extract_archive,
    runcmd,
)

log = logging.getLogger(__name__)

ARCHES = arches[WIN32]

EnvMapping = MutableMapping[str, str]

if sys.platform == WIN32:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def populate_env(env: EnvMapping, dirs: Dirs) -> None:
    """
    Make sure we have the correct environment variables set.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    """
    env["MSBUILDDISABLENODEREUSE"] = "1"


def update_props(source: pathlib.Path, old: str, new: str) -> None:
    """
    Overwrite a dependency string for Windows PCBuild.

    :param source: Python's source directory
    :type source: str
    :param old: Regular expression to search for
    :type old: str
    :param new: Replacement text
    :type new: str
    """
    log.info("Patching props in %s: %s -> %s", source, old, new)
    # Use double-backslashes for the replacement string because it goes into re.sub
    new_for_re = new.replace("\\", "\\\\")
    patch_file(source / "PCbuild" / "python.props", old, new_for_re)
    patch_file(source / "PCbuild" / "get_externals.bat", old, new_for_re)


def flatten_externals(dirs: Dirs, name: str, version: str) -> None:
    """
    Handle nested folders in extracted tarballs.
    """
    extracted_dir = dirs.source / "externals" / f"{name}-{version}"
    if not extracted_dir.exists():
        return
    subdirs = [x for x in extracted_dir.iterdir() if x.is_dir() and x.name != "zips"]
    if len(subdirs) == 1:
        log.info("Flattening %s-%s from %s", name, version, subdirs[0].name)
        temp_dir = dirs.source / "externals" / f"{name}-{version}-tmp"
        if temp_dir.exists():
            shutil.rmtree(str(temp_dir))
        shutil.move(str(subdirs[0]), str(temp_dir))
        shutil.rmtree(str(extracted_dir))
        shutil.move(str(temp_dir), str(extracted_dir))


def get_externals_source(externals_dir: pathlib.Path, url: str) -> None:
    """
    Download external source code dependency.

    Download source code and extract to the "externals" directory in the root of
    the python source. Only works with a tarball
    """
    zips_dir = externals_dir / "zips"
    zips_dir.mkdir(parents=True, exist_ok=True)
    local_file = download_url(url=url, dest=str(zips_dir))
    extract_archive(archive=str(local_file), to_dir=str(externals_dir))
    try:
        os.remove(local_file)
    except OSError:
        log.exception("Failed to remove temporary file")


def update_sqlite(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the SQLITE library.
    """
    sqlite_info = get_dependency_version("sqlite", "win32")
    if not sqlite_info:
        log.error("sqlite dependency not found for win32")
        return

    version = sqlite_info["version"]
    sqliteversion = sqlite_info.get("sqliteversion", "3500400")
    url = sqlite_info["url"].format(version=sqliteversion)
    sha256 = sqlite_info["sha256"]
    ref_loc = f"cpe:2.3:a:sqlite:sqlite:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"sqlite-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(
            dirs.source, r"sqlite-\d+\.\d+\.\d+\.\d+\\?", f"sqlite-{version}\\"
        )
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        # Fix the extracted directory name
        extracted_dir = dirs.source / "externals" / f"sqlite-autoconf-{sqliteversion}"
        if extracted_dir.exists():
            shutil.move(str(extracted_dir), str(target_dir))

    # Update externals.spdx.json
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12", "3.13", "3.14"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        if spdx_json.exists():
            with open(str(spdx_json), "r") as f:
                data = json.load(f)
                for pkg in data["packages"]:
                    if pkg["name"] == "sqlite":
                        pkg["versionInfo"] = version
                        pkg["downloadLocation"] = url
                        pkg["checksums"][0]["checksumValue"] = sha256
                        pkg["externalRefs"][0]["referenceLocator"] = ref_loc
            with open(str(spdx_json), "w") as f:
                json.dump(data, f, indent=2)


def update_xz(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the XZ library.
    """
    xz_info = get_dependency_version("xz", "win32")
    if not xz_info:
        log.error("xz dependency not found for win32")
        return

    version = xz_info["version"]
    url = xz_info["url"].format(version=version)
    sha256 = xz_info["sha256"]
    ref_loc = f"cpe:2.3:a:tukaani:xz:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"xz-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(dirs.source, r"xz-\d+\.\d+\.\d+\\?", f"xz-{version}\\")
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "xz", version)

    # Bring config.h for MSBuild compatibility
    config_file = target_dir / "src" / "common" / "config.h"
    config_file_source = dirs.root / "_resources" / "xz" / "config.h"
    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(config_file_source), str(config_file))

    # Copy missing crc source files
    check_dir = target_dir / "src" / "liblzma" / "check"
    for filename in ["crc32_table.c", "crc64_table.c"]:
        target_file = check_dir / filename
        source_file = dirs.root / "_resources" / "xz" / filename
        if not target_file.exists():
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(source_file), str(target_file))

    # Update externals.spdx.json
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12", "3.13", "3.14"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        if spdx_json.exists():
            with open(str(spdx_json), "r") as f:
                data = json.load(f)
                for pkg in data["packages"]:
                    if pkg["name"] == "xz":
                        pkg["versionInfo"] = version
                        pkg["downloadLocation"] = url
                        pkg["checksums"][0]["checksumValue"] = sha256
                        pkg["externalRefs"][0]["referenceLocator"] = ref_loc
            with open(str(spdx_json), "w") as f:
                json.dump(data, f, indent=2)


def update_expat(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the EXPAT library.
    """
    expat_info = get_dependency_version("expat", "win32")
    if not expat_info:
        log.error("expat dependency not found for win32")
        return

    version = expat_info["version"]
    url = expat_info["url"].format(version=version)
    sha256 = expat_info["sha256"]

    bash_refresh = dirs.source / "Modules" / "expat" / "refresh.sh"
    if bash_refresh.exists():
        patch_file(
            bash_refresh,
            old=r'expected_libexpat_tag="R_\d+_\d+_\d"',
            new=f'expected_libexpat_tag="R_{version.replace(".", "_")}"',
        )
        patch_file(
            bash_refresh,
            old=r'expected_libexpat_version="\d+.\d+.\d"',
            new=f'expected_libexpat_version="{version}"',
        )
        patch_file(
            bash_refresh,
            old='expected_libexpat_sha256=".*"',
            new=f'expected_libexpat_sha256="{sha256}"',
        )

    get_externals_source(externals_dir=dirs.source / "Modules" / "expat", url=url)
    expat_lib_dir = dirs.source / "Modules" / "expat" / f"expat-{version}" / "lib"
    expat_dir = dirs.source / "Modules" / "expat"
    updated_files = []
    for ext in ["*.h", "*.c"]:
        for file in glob.glob(str(expat_lib_dir / ext)):
            target = expat_dir / os.path.basename(file)
            if target.exists():
                target.unlink()
            shutil.move(file, str(expat_dir))
            updated_files.append(target)

    now = time.time()
    for target_file in updated_files:
        os.utime(target_file, (now, now))

    # Update SBOM with correct checksums for updated expat files
    files_to_update = {f"Modules/expat/{f.name}": f for f in updated_files}
    if bash_refresh.exists():
        files_to_update["Modules/expat/refresh.sh"] = bash_refresh
    update_sbom_checksums(dirs.source, files_to_update)


def update_openssl(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the OPENSSL library.
    """
    openssl_info = get_dependency_version("openssl", "win32")
    if not openssl_info:
        log.error("openssl dependency not found for win32")
        return

    version = openssl_info["version"]
    url = openssl_info["url"].format(version=version)
    sha256 = openssl_info["sha256"]
    ref_loc = f"cpe:2.3:a:openssl:openssl:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"openssl-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(
            dirs.source, r"openssl-\d+\.\d+\.\d+[a-z]*\\?", f"openssl-{version}\\"
        )
        update_props(
            dirs.source,
            r"openssl-bin-\d+\.\d+\.\d+[a-z]*\\?",
            f"openssl-bin-{version}\\",
        )

        # Patch python.props to point include dir to the source instead of a non-existent bin dir
        inc_dir = (
            "<opensslIncludeDir Condition=\"$(opensslIncludeDir) == ''\">"
            "$(opensslDir)include</opensslIncludeDir>"
        )
        patch_file(
            dirs.source / "PCbuild" / "python.props",
            r"<opensslIncludeDir.*>.*</opensslIncludeDir>",
            inc_dir.replace("\\", "\\\\"),
        )
        out_dir = (
            "<opensslOutDir Condition=\"$(opensslOutDir) == ''\">"
            "$(opensslDir)</opensslOutDir>"
        )
        patch_file(
            dirs.source / "PCbuild" / "python.props",
            r"<opensslOutDir.*>.*</opensslOutDir>",
            out_dir.replace("\\", "\\\\"),
        )

        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "openssl", version)

        # Ensure include directory exists where MSBuild expects it
        if not (target_dir / "include").exists() and (target_dir / "inc32").exists():
            shutil.copytree(str(target_dir / "inc32"), str(target_dir / "include"))

        # OpenSSL 3.x source build requires configuration.h (usually generated)
        conf_h = target_dir / "include" / "openssl" / "configuration.h"
        if not conf_h.exists():
            conf_h.parent.mkdir(parents=True, exist_ok=True)
            with open(str(conf_h), "w") as f:
                f.write("/* Stubs for OpenSSL 3.x */\n")
                f.write("#ifndef OPENSSL_CONFIGURATION_H\n")
                f.write("#define OPENSSL_CONFIGURATION_H\n")
                f.write("#include <openssl/opensslconf.h>\n")
                f.write("#endif\n")

    # Update externals.spdx.json
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12", "3.13", "3.14"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        if spdx_json.exists():
            with open(str(spdx_json), "r") as f:
                data = json.load(f)
                for pkg in data["packages"]:
                    if pkg["name"] == "openssl":
                        pkg["versionInfo"] = version
                        pkg["downloadLocation"] = url
                        pkg["checksums"][0]["checksumValue"] = sha256
                        pkg["externalRefs"][0]["referenceLocator"] = ref_loc
            with open(str(spdx_json), "w") as f:
                json.dump(data, f, indent=2)


def update_bzip2(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the BZIP2 library.
    """
    bzip2_info = get_dependency_version("bzip2", "win32")
    if not bzip2_info:
        log.error("bzip2 dependency not found for win32")
        return

    version = bzip2_info["version"]
    url = bzip2_info["url"].format(version=version)
    sha256 = bzip2_info["sha256"]
    ref_loc = f"cpe:2.3:a:bzip:bzip2:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"bzip2-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(dirs.source, r"bzip2-\d+\.\d+\.\d+\\?", f"bzip2-{version}\\")
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "bzip2", version)

    # Update externals.spdx.json
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12", "3.13", "3.14"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        if spdx_json.exists():
            with open(str(spdx_json), "r") as f:
                data = json.load(f)
                for pkg in data["packages"]:
                    if pkg["name"] == "bzip2":
                        pkg["versionInfo"] = version
                        pkg["downloadLocation"] = url
                        pkg["checksums"][0]["checksumValue"] = sha256
                        pkg["externalRefs"][0]["referenceLocator"] = ref_loc
            with open(str(spdx_json), "w") as f:
                json.dump(data, f, indent=2)


def update_libffi(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the LIBFFI library.
    """
    libffi_info = get_dependency_version("libffi", "win32")
    if not libffi_info:
        log.error("libffi dependency not found for win32")
        return

    version = libffi_info["version"]
    url = libffi_info["url"].format(version=version)
    sha256 = libffi_info["sha256"]
    ref_loc = f"cpe:2.3:a:libffi_project:libffi:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"libffi-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(dirs.source, r"libffi-\d+\.\d+\.\d+\\?", f"libffi-{version}\\")

        # Patch libffi library name (3.5.2 uses libffi-8.lib)
        patch_file(
            dirs.source / "PCbuild" / "libffi.props", r"libffi-7.lib", r"libffi-8.lib"
        )
        patch_file(
            dirs.source / "PCbuild" / "libffi.props", r"libffi-7.dll", r"libffi-8.dll"
        )

        # Patch libffi.props to look for headers in 'include'
        inc_dir = (
            "<libffiIncludeDir Condition=\"$(libffiIncludeDir) == ''\">"
            "$(libffiDir)include</libffiIncludeDir>"
        )
        patch_file(
            dirs.source / "PCbuild" / "python.props",
            r"<libffiIncludeDir.*>.*</libffiIncludeDir>",
            inc_dir.replace("\\", "\\\\"),
        )
        out_dir = (
            "<libffiOutDir Condition=\"$(libffiOutDir) == ''\">"
            "$(libffiDir)</libffiOutDir>"
        )
        patch_file(
            dirs.source / "PCbuild" / "python.props",
            r"<libffiOutDir.*>.*</libffiOutDir>",
            out_dir.replace("\\", "\\\\"),
        )

        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "libffi", version)

        # Migrate headers to 'include' for Python
        include_dir = target_dir / "include"
        include_dir.mkdir(exist_ok=True)
        for header in target_dir.glob("**/ffi.h"):
            if header.parent != include_dir:
                shutil.copy(str(header), str(include_dir / "ffi.h"))
        for header in target_dir.glob("**/ffitarget.h"):
            if header.parent != include_dir:
                shutil.copy(str(header), str(include_dir / "ffitarget.h"))

    # Update externals.spdx.json
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12", "3.13", "3.14"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        if spdx_json.exists():
            with open(str(spdx_json), "r") as f:
                data = json.load(f)
                for pkg in data["packages"]:
                    if pkg["name"] == "libffi":
                        pkg["versionInfo"] = version
                        pkg["downloadLocation"] = url
                        pkg["checksums"][0]["checksumValue"] = sha256
                        pkg["externalRefs"][0]["referenceLocator"] = ref_loc
            with open(str(spdx_json), "w") as f:
                json.dump(data, f, indent=2)


def update_zlib(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the ZLIB library.
    """
    zlib_info = get_dependency_version("zlib", "win32")
    if not zlib_info:
        log.error("zlib dependency not found for win32")
        return

    version = zlib_info["version"]
    url = zlib_info["url"].format(version=version)
    sha256 = zlib_info["sha256"]
    ref_loc = f"cpe:2.3:a:gnu:zlib:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"zlib-{version}"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        update_props(dirs.source, r"zlib-\d+\.\d+\.\d+\\?", f"zlib-{version}\\")
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "zlib", version)

    # Update externals.spdx.json
    if env["RELENV_PY_MAJOR_VERSION"] in ["3.12", "3.13", "3.14"]:
        spdx_json = dirs.source / "Misc" / "externals.spdx.json"
        if spdx_json.exists():
            with open(str(spdx_json), "r") as f:
                data = json.load(f)
                for pkg in data["packages"]:
                    if pkg["name"] == "zlib":
                        pkg["versionInfo"] = version
                        pkg["downloadLocation"] = url
                        pkg["checksums"][0]["checksumValue"] = sha256
                        pkg["externalRefs"][0]["referenceLocator"] = ref_loc
            with open(str(spdx_json), "w") as f:
                json.dump(data, f, indent=2)


def build_python(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Run the commands to build Python.
    """
    externals_dir = dirs.source / "externals"
    externals_dir.mkdir(parents=True, exist_ok=True)

    update_sqlite(dirs=dirs, env=env)
    update_xz(dirs=dirs, env=env)
    update_expat(dirs=dirs, env=env)
    update_openssl(dirs=dirs, env=env)
    update_bzip2(dirs=dirs, env=env)
    update_libffi(dirs=dirs, env=env)
    update_zlib(dirs=dirs, env=env)

    arch_to_plat = {"amd64": "x64", "x86": "win32", "arm64": "arm64"}
    arch = env["RELENV_HOST_ARCH"]
    plat = arch_to_plat[arch]

    # -e skips fetching externals if they already exist.
    cmd = [
        str(dirs.source / "PCbuild" / "build.bat"),
        "-e",
        "-p",
        plat,
        "--no-tkinter",
    ]

    log.info("Start PCbuild")
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    log.info("PCbuild finished")

    if arch == "amd64":
        build_dir = dirs.source / "PCbuild" / arch
    else:
        build_dir = dirs.source / "PCbuild" / plat
    bin_dir = dirs.prefix / "Scripts"
    bin_dir.mkdir(parents=True, exist_ok=True)

    binaries = [
        "py.exe",
        "pyw.exe",
        "python.exe",
        "pythonw.exe",
        "python3.dll",
        f"python{ env['RELENV_PY_MAJOR_VERSION'].replace('.', '') }.dll",
        "vcruntime140.dll",
        "venvlauncher.exe",
        "venvwlauncher.exe",
    ]
    for binary in binaries:
        shutil.move(src=str(build_dir / binary), dst=str(bin_dir / binary))

    (dirs.prefix / "DLLs").mkdir(parents=True, exist_ok=True)
    for file in glob.glob(str(build_dir / "*.pyd")):
        shutil.move(src=file, dst=str(dirs.prefix / "DLLs"))
    for file in glob.glob(str(build_dir / "*.dll")):
        shutil.move(src=file, dst=str(dirs.prefix / "DLLs"))

    shutil.copytree(
        src=str(dirs.source / "Include"),
        dst=str(dirs.prefix / "Include"),
        dirs_exist_ok=True,
    )
    if "3.13" not in env["RELENV_PY_MAJOR_VERSION"]:
        shutil.copy(
            src=str(dirs.source / "PC" / "pyconfig.h"), dst=str(dirs.prefix / "Include")
        )

    shutil.copytree(
        src=str(dirs.source / "Lib"), dst=str(dirs.prefix / "Lib"), dirs_exist_ok=True
    )
    os.makedirs(str(dirs.prefix / "Lib" / "site-packages"), exist_ok=True)

    (dirs.prefix / "libs").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        src=str(build_dir / "python3.lib"),
        dst=str(dirs.prefix / "libs" / "python3.lib"),
    )
    pylib = f"python{ env['RELENV_PY_MAJOR_VERSION'].replace('.', '') }.lib"
    shutil.copy(src=str(build_dir / pylib), dst=str(dirs.prefix / "libs" / pylib))


build = builds.add("win32", populate_env=populate_env)

build.add(
    "python",
    build_func=build_python,
    download={
        "url": "https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
        "version": build.version,
        "checksum": "d31d548cd2c5ca2ae713bebe346ba15e8406633a",
    },
)


def finalize(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Finalize sitecustomize, relenv runtime, and pip for Windows.
    """
    sitepackages = dirs.prefix / "Lib" / "site-packages"
    install_runtime(sitepackages)
    update_ensurepip(dirs.prefix / "Lib")

    python = dirs.prefix / "Scripts" / "python.exe"
    runcmd([str(python), "-m", "ensurepip"], env=env, stderr=logfp, stdout=logfp)

    def runpip(pkg: Union[str, os.PathLike[str]]) -> None:
        env = os.environ.copy()
        cmd = [str(python), "-m", "pip", "install", str(pkg)]
        runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    runpip("wheel")
    if (MODULE_DIR.parent / ".git").exists():
        runpip(MODULE_DIR.parent)
    else:
        runpip("relenv")

    for root, _, files in os.walk(dirs.prefix):
        for file in files:
            if file.endswith(".pyc"):
                os.remove(pathlib.Path(root) / file)

    globs = [
        "*.exe",
        "*.py",
        "*.pyd",
        "*.dll",
        "*.lib",
        "*.whl",
        "/Include/*",
        "/Lib/site-packages/*",
    ]
    archive = f"{dirs.prefix}.tar.xz"
    with tarfile.open(archive, mode="w:xz") as fp:
        create_archive(fp, dirs.prefix, globs, logfp)


build.add("relenv-finalize", build_func=finalize, wait_on=["python"])
