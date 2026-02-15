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
import subprocess
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


def find_vcvarsall(env: EnvMapping) -> pathlib.Path | None:
    """
    Locate vcvarsall.bat using multiple strategies.
    """
    # 1. Check MSBUILD env var and search upwards
    msbuild_path = env.get("MSBUILD")
    if msbuild_path:
        msbuild_path = pathlib.Path(msbuild_path)
        if msbuild_path.exists():
            for parent in msbuild_path.parents:
                candidate = parent / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
                if candidate.exists():
                    return candidate

    # 2. Use vswhere.exe if available
    vswhere = shutil.which("vswhere.exe")
    if not vswhere:
        # Check common location
        vswhere_path = (
            pathlib.Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"))
            / "Microsoft Visual Studio"
            / "Installer"
            / "vswhere.exe"
        )
        if vswhere_path.exists():
            vswhere = str(vswhere_path)

    if vswhere:
        try:
            # -latest: Use newest version
            # -products *: Search all products (Enterprise, Professional, Community, BuildTools)
            # -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64: Ensure C++ tools are present
            # -property installationPath: Return the path
            cmd = [
                vswhere,
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            vs_path = result.stdout.strip()
            if vs_path:
                candidate = (
                    pathlib.Path(vs_path) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
                )
                if candidate.exists():
                    return candidate
        except subprocess.CalledProcessError:
            pass

    # 3. Check common installation paths as a last resort
    program_files = [
        os.environ.get("ProgramFiles", "C:\\Program Files"),
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    ]
    editions = ["Enterprise", "Professional", "Community", "BuildTools"]
    years = ["2022", "2019", "2017"]

    for pf in program_files:
        for year in years:
            for edition in editions:
                candidate = (
                    pathlib.Path(pf)
                    / "Microsoft Visual Studio"
                    / year
                    / edition
                    / "VC"
                    / "Auxiliary"
                    / "Build"
                    / "vcvarsall.bat"
                )
                if candidate.exists():
                    return candidate

    return None


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
    # patch_file uses re.sub, so we need to ensure backslashes are preserved.
    new_escaped = new.replace("\\", "\\\\")
    patch_file(source / "PCbuild" / "python.props", old, new_escaped)
    patch_file(source / "PCbuild" / "get_externals.bat", old, new_escaped)


def flatten_externals(dirs: Dirs, name: str, version: str) -> None:
    """
    Handle nested folders in extracted tarballs.
    """
    # Look for the extracted directory
    # For cpython-bin-deps, it often extracts to <repo>-<tag>/...
    # We want it to be in externals/<name>-<version>/
    externals_dir = dirs.source / "externals"

    # Identify what was actually extracted
    # extract_archive usually extracts into externals_dir
    # We search for any directory that isn't 'zips'
    extracted_dirs = [
        x for x in externals_dir.iterdir() if x.is_dir() and x.name != "zips"
    ]

    target_dir = externals_dir / f"{name}-{version}"

    for d in extracted_dirs:
        if d == target_dir:
            # Check if it's nested (e.g. openssl-3.0.15/openssl-3.0.15/...)
            subdirs = [x for x in d.iterdir() if x.is_dir()]
            if len(subdirs) == 1 and subdirs[0].name.startswith(name):
                log.info("Flattening nested %s", d.name)
                temp_dir = externals_dir / f"{name}-{version}-tmp"
                shutil.move(str(subdirs[0]), str(temp_dir))
                shutil.rmtree(str(d))
                shutil.move(str(temp_dir), str(d))
            continue

        if d.name.startswith(name) or "cpython-bin-deps" in d.name:
            log.info("Moving %s to %s", d.name, target_dir.name)
            if target_dir.exists():
                shutil.rmtree(str(target_dir))
            shutil.move(str(d), str(target_dir))
            # Recurse once to handle nested folder inside the renamed folder
            flatten_externals(dirs, name, version)


def get_externals_source(externals_dir: pathlib.Path, url: str) -> None:
    """
    Download external source code dependency.
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
        return

    version = sqlite_info["version"]
    sqliteversion = sqlite_info.get("sqliteversion", "3500400")
    url = sqlite_info["url"].format(version=sqliteversion)
    sha256 = sqlite_info["sha256"]
    ref_loc = f"cpe:2.3:a:sqlite:sqlite:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"sqlite-{version}"
    update_props(dirs.source, r"sqlite-\d+(\.\d+)*", f"sqlite-{version}")
    if not target_dir.exists():
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        # Fix the extracted directory name (sqlite-autoconf-...)
        for d in (dirs.source / "externals").iterdir():
            if d.is_dir() and d.name.startswith("sqlite-autoconf"):
                shutil.move(str(d), str(target_dir))

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
        return

    version = xz_info["version"]
    url = xz_info["url"].format(version=version)
    sha256 = xz_info["sha256"]
    ref_loc = f"cpe:2.3:a:tukaani:xz:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"xz-{version}"
    update_props(dirs.source, r"xz-\d+(\.\d+)*", f"xz-{version}")
    if not target_dir.exists():
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
        return

    version = expat_info["version"]
    url = expat_info["url"].format(version=version)
    sha256 = expat_info["sha256"]

    bash_refresh = dirs.source / "Modules" / "expat" / "refresh.sh"
    if bash_refresh.exists():
        patch_file(
            bash_refresh,
            old=r'expected_libexpat_tag="R_\d+(_\d+)*"',
            new=f'expected_libexpat_tag="R_{version.replace(".", "_")}"',
        )
        patch_file(
            bash_refresh,
            old=r'expected_libexpat_version="\d+(\.\d+)*"',
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
        return

    version = openssl_info["version"]
    url = openssl_info["url"].format(version=version)
    sha256 = openssl_info["sha256"]
    ref_loc = f"cpe:2.3:a:openssl:openssl:{version}:*:*:*:*:*:*:*"

    is_binary = "cpython-bin-deps" in url
    target_dir = dirs.source / "externals" / f"openssl-{version}"

    update_props(dirs.source, r"openssl-\d+(\.\d+)*[a-z]*", f"openssl-{version}")
    # Binary deps tarball from cpython-bin-deps includes both source and binaries
    # We need to ensure openssl-bin-<version> is also pointed to the same place if needed
    update_props(
        dirs.source, r"openssl-bin-\d+(\.\d+)*[a-z]*", f"openssl-{version}"
    )

    if not target_dir.exists():
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "openssl", version)

        if not is_binary:
            # Build from source
            log.info("Building OpenSSL %s from source", version)
            perl_dir = update_perl(dirs, env)
            perl_bin = perl_dir / "perl" / "bin" / "perl.exe"
            
            nasm_info = get_dependency_version("nasm", "win32")
            nasm_version = nasm_info["version"]
            nasm_dir = dirs.source / "externals" / f"nasm-{nasm_version}"
            
            # Find nasm.exe
            nasm_exe = list(nasm_dir.glob("**/nasm.exe"))
            if not nasm_exe:
                log.error("Could not find nasm.exe in %s", nasm_dir)
                return
            
            arch_map = {
                "amd64": "VC-WIN64A",
                "x86": "VC-WIN32",
                "arm64": "VC-WIN64-ARM",
            }
            target = arch_map.get(env["RELENV_HOST_ARCH"], "VC-WIN64A")
            
            vcvars = find_vcvarsall(env)
            if not vcvars:
                log.warning("Could not find vcvarsall.bat, build may fail")
                vcvars_cmd = "echo"
            else:
                vcvars_arch = "x64" if env["RELENV_HOST_ARCH"] == "amd64" else env["RELENV_HOST_ARCH"]
                vcvars_cmd = f'call "{vcvars}" {vcvars_arch}'

            env_path = os.environ.get("PATH", "")
            build_env = env.copy()
            build_env["PATH"] = f"{perl_bin.parent};{nasm_exe[0].parent};{env_path}"
            
            prefix = target_dir / "build"
            openssldir = prefix / "ssl"
            
            # Create a temporary batch file to run the build
            # This is more robust than passing a long string to cmd /c
            build_bat = target_dir / "relenv_build_openssl.bat"
            with open(str(build_bat), "w") as f:
                f.write("@echo off\n")
                f.write(f'{vcvars_cmd}\n')
                f.write(f'if %errorlevel% neq 0 exit /b %errorlevel%\n')
                f.write(f'cd /d "{target_dir}"\n')
                f.write(f'"{perl_bin}" Configure {target} --prefix="{prefix}" --openssldir="{openssldir}" no-unit-test no-tests\n')
                f.write(f'if %errorlevel% neq 0 exit /b %errorlevel%\n')
                f.write(f'nmake\n')
                f.write(f'if %errorlevel% neq 0 exit /b %errorlevel%\n')
                f.write(f'nmake install_sw\n')
                f.write(f'if %errorlevel% neq 0 exit /b %errorlevel%\n')

            log.info("Running OpenSSL build batch file")
            runcmd([str(build_bat)], env=build_env)
            
        # CPython expects binaries in a specific structure
        # opensslOutDir = $(ExternalsDir)openssl-bin-<version)\$(ArchName)\
        # We'll move them to match.
        out_dir = target_dir / env["RELENV_HOST_ARCH"]
        out_dir.mkdir(parents=True, exist_ok=True)
        
        prefix = target_dir / "build"
        bin_dir = prefix / "bin"
        lib_dir = prefix / "lib"
        inc_dir = prefix / "include"
        
        if prefix.exists():
            for f in bin_dir.glob("*.dll"):
                shutil.copy(str(f), str(out_dir))
            for f in bin_dir.glob("*.pdb"):
                shutil.copy(str(f), str(out_dir))
            for f in lib_dir.glob("*.lib"):
                shutil.copy(str(f), str(out_dir))
            
            # CPython expects headers in $(opensslOutDir)include
            (out_dir / "include").mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(inc_dir), str(out_dir / "include"), dirs_exist_ok=True)
            
            # CPython specifically looks for applink.c in the include directory
            if (target_dir / "ms" / "applink.c").exists():
                shutil.copy(
                    target_dir / "ms" / "applink.c",
                    out_dir / "include" / "applink.c",
                )
            
            # Copy LICENSE file to out_dir to satisfy CPython build
            for license_file in ["LICENSE", "LICENSE.txt", "COPYING"]:
                if (target_dir / license_file).exists():
                    shutil.copy(str(target_dir / license_file), str(out_dir / "LICENSE"))
                    break

        else:
            # Ensure include/openssl exists
            inc_dir = target_dir / "include" / "openssl"
            if not inc_dir.exists():
                # Try to find headers and move them
                for h in target_dir.glob("**/opensslv.h"):
                    if h.parent.name == "openssl":
                        # Found it, move its parent to include/
                        shutil.copytree(str(h.parent), str(inc_dir), dirs_exist_ok=True)
                        break

            # Ensure applink.c is in include/
            if not (target_dir / "include" / "applink.c").exists():
                for a in target_dir.glob("**/applink.c"):
                    shutil.copy(str(a), str(target_dir / "include" / "applink.c"))
                    break

    if not is_binary:
        # Update props to point to our custom build
        update_props(dirs.source, r"openssl-bin-\d+(\.\d+)*[a-z]*", f"openssl-{version}\\\\{env['RELENV_HOST_ARCH']}")
        # And opensslOutDir needs to be just the folder containing include
        patch_file(dirs.source / "PCbuild" / "python.props", 
                   rf"<opensslOutDir Condition=\"\$\(opensslOutDir\) == ''\">\$\(ExternalsDir\)openssl-{version}\\\\{env['RELENV_HOST_ARCH']}\\\$\(ArchName\)\\\</opensslOutDir>",
                   f"<opensslOutDir Condition=\"$(opensslOutDir) == ''\">$(ExternalsDir)openssl-{version}\\\\{env['RELENV_HOST_ARCH']}\\\\</opensslOutDir>")

    # Patch openssl.props to use correct DLL suffix for OpenSSL 3.x
    if version.startswith("3."):
        suffix = "-3"
        if not is_binary and env["RELENV_HOST_ARCH"] == "amd64":
            suffix = "-3-x64"
        
        log.info("Patching openssl.props DLL suffix to %s", suffix)
        patch_file(
            dirs.source / "PCbuild" / "openssl.props",
            r"<_DLLSuffix>.*</_DLLSuffix>",
            f"<_DLLSuffix>{suffix}</_DLLSuffix>",
        )

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
        return

    version = bzip2_info["version"]
    url = bzip2_info["url"].format(version=version)
    sha256 = bzip2_info["sha256"]
    ref_loc = f"cpe:2.3:a:bzip:bzip2:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"bzip2-{version}"
    update_props(dirs.source, r"bzip2-\d+(\.\d+)*", f"bzip2-{version}")
    if not target_dir.exists():
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
        return

    version = libffi_info["version"]
    url = libffi_info["url"].format(version=version)
    sha256 = libffi_info["sha256"]
    ref_loc = f"cpe:2.3:a:libffi_project:libffi:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"libffi-{version}"
    update_props(dirs.source, r"libffi-\d+(\.\d+)*", f"libffi-{version}")
    if not target_dir.exists():
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "libffi", version)

    # Patch libffi library name if needed.
    # Newer libffi (3.4.4+) uses libffi-8.lib, older uses libffi-7.lib.
    # We'll search for the lib file after extraction.
    # Find the .lib file to determine the name
    lib_files = list(target_dir.glob("**/*.lib"))
    if lib_files:
        lib_name = lib_files[0].name
        if lib_name != "libffi-7.lib":
            log.info("Patching libffi library name to %s", lib_name)
            patch_file(
                dirs.source / "PCbuild" / "libffi.props", r"libffi-7\.lib", lib_name
            )
            patch_file(
                dirs.source / "PCbuild" / "libffi.props",
                r"libffi-7\.dll",
                lib_name.replace(".lib", ".dll"),
            )

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
        return

    version = zlib_info["version"]
    url = zlib_info["url"].format(version=version)
    sha256 = zlib_info["sha256"]
    ref_loc = f"cpe:2.3:a:gnu:zlib:{version}:*:*:*:*:*:*:*"

    target_dir = dirs.source / "externals" / f"zlib-{version}"
    update_props(dirs.source, r"zlib-\d+(\.\d+)*", f"zlib-{version}")
    if not target_dir.exists():
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


def update_mpdecimal(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the MPDECIMAL library.
    """
    mpdecimal_info = get_dependency_version("mpdecimal", "win32")
    if not mpdecimal_info:
        return

    version = mpdecimal_info["version"]
    url = mpdecimal_info["url"].format(version=version)
    sha256 = mpdecimal_info["sha256"]

    target_dir = dirs.source / "externals" / f"mpdecimal-{version}"
    update_props(dirs.source, r"mpdecimal-\d+(\.\d+)*", f"mpdecimal-{version}")
    if not target_dir.exists():
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "mpdecimal", version)


def update_nasm(dirs: Dirs, env: EnvMapping) -> None:
    """
    Update the NASM library.
    """
    nasm_info = get_dependency_version("nasm", "win32")
    if not nasm_info:
        return

    version = nasm_info["version"]
    url = nasm_info["url"].format(version=version)
    sha256 = nasm_info["sha256"]

    target_dir = dirs.source / "externals" / f"nasm-{version}"
    update_props(dirs.source, r"nasm-\d+(\.\d+)*", f"nasm-{version}")
    if not target_dir.exists():
        get_externals_source(externals_dir=dirs.source / "externals", url=url)
        flatten_externals(dirs, "nasm", version)


def update_perl(dirs: Dirs, env: EnvMapping) -> pathlib.Path:
    """
    Update the Perl library.
    """
    perl_info = get_dependency_version("perl", "win32")
    if not perl_info:
        return None

    version = perl_info["version"]
    url = perl_info["url"].format(version=version)
    sha256 = perl_info["sha256"]

    target_dir = dirs.source / "externals" / f"perl-{version}"
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        get_externals_source(externals_dir=target_dir, url=url)
    return target_dir


def build_python(env: EnvMapping, dirs: Dirs, logfp: IO[str]) -> None:
    """
    Run the commands to build Python.
    """
    externals_dir = dirs.source / "externals"
    externals_dir.mkdir(parents=True, exist_ok=True)

    update_sqlite(dirs=dirs, env=env)
    update_xz(dirs=dirs, env=env)
    update_expat(dirs=dirs, env=env)
    update_bzip2(dirs=dirs, env=env)
    update_libffi(dirs=dirs, env=env)
    update_zlib(dirs=dirs, env=env)
    update_mpdecimal(dirs=dirs, env=env)
    update_nasm(dirs=dirs, env=env)
    update_perl(dirs=dirs, env=env)
    update_openssl(dirs=dirs, env=env)

    # Disable SBOM validation in Python 3.12+
    regen_targets = dirs.source / "PCbuild" / "regen.targets"
    if regen_targets.exists():
        log.info("Patching regen.targets to skip SBOM generation")
        patch_file(
            regen_targets,
            r'Command="py -3.13 .*generate_sbom\.py.*"',
            'Command="echo skipping sbom"',
        )

    # Secondary defense: overwrite the script itself if it exists
    sbom_script = dirs.source / "Tools" / "build" / "generate_sbom.py"
    if sbom_script.exists():
        with open(str(sbom_script), "w") as f:
            f.write("import sys\nif __name__ == '__main__':\n    sys.exit(0)\n")

    # Disable get_externals.bat to avoid network fetches during MSBuild
    batch_file = dirs.source / "PCbuild" / "get_externals.bat"
    if batch_file.exists():
        with open(str(batch_file), "w") as f:
            f.write("@echo off\necho skipping fetch\n")

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
