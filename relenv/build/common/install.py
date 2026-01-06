# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Installation and finalization functions for the build process.
"""
from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import logging
import os
import os.path
import pathlib
import pprint
import re
import shutil
import sys
import tarfile
from types import ModuleType
from typing import IO, MutableMapping, Optional, Sequence, Union, TYPE_CHECKING

from relenv.common import (
    LINUX,
    MODULE_DIR,
    MissingDependencyError,
    Version,
    download_url,
    format_shebang,
    runcmd,
)
import relenv.relocate

if TYPE_CHECKING:
    from .builder import Dirs

# Type alias for path-like objects
PathLike = Union[str, os.PathLike[str]]

# Relenv PTH file content for bootstrapping
RELENV_PTH = (
    "import os; "
    "import sys; "
    "from importlib import util; "
    "from pathlib import Path; "
    "spec = util.spec_from_file_location("
    "'relenv.runtime', str(Path(__file__).parent / 'site-packages' / 'relenv' / 'runtime.py')"
    "); "
    "mod = util.module_from_spec(spec); "
    "sys.modules['relenv.runtime'] = mod; "
    "spec.loader.exec_module(mod); mod.bootstrap();"
)

log = logging.getLogger(__name__)


def patch_file(path: PathLike, old: str, new: str) -> None:
    """
    Search a file line by line for a string to replace.

    :param path: Location of the file to search
    :type path: str
    :param old: The value that will be replaced
    :type path: str
    :param new: The value that will replace the 'old' value.
    :type path: str
    """
    log.debug("Patching file: %s", path)
    with open(path, "r") as fp:
        content = fp.read()
    new_content = ""
    for line in content.splitlines():
        line = re.sub(old, new, line)
        new_content += line + "\n"
    with open(path, "w") as fp:
        fp.write(new_content)


def update_sbom_checksums(
    source_dir: PathLike, files_to_update: MutableMapping[str, PathLike]
) -> None:
    """
    Update checksums in sbom.spdx.json for modified files.

    Python 3.12+ includes an SBOM (Software Bill of Materials) that tracks
    file checksums. When we update files (e.g., expat sources), we need to
    recalculate their checksums.

    :param source_dir: Path to the Python source directory
    :type source_dir: PathLike
    :param files_to_update: Mapping of SBOM relative paths to actual file paths
    :type files_to_update: MutableMapping[str, PathLike]
    """
    source_path = pathlib.Path(source_dir)
    spdx_json = source_path / "Misc" / "sbom.spdx.json"

    # SBOM only exists in Python 3.12+
    if not spdx_json.exists():
        log.debug("SBOM file not found, skipping checksum updates")
        return

    # Read the SBOM JSON
    with open(spdx_json, "r") as f:
        data = json.load(f)

    # Compute checksums for each file
    checksums = {}
    for relative_path, file_path in files_to_update.items():
        file_path = pathlib.Path(file_path)
        if not file_path.exists():
            log.warning("File not found for checksum: %s", file_path)
            continue

        # Compute SHA1 and SHA256
        sha1 = hashlib.sha1()
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            content = f.read()
            sha1.update(content)
            sha256.update(content)

        checksums[relative_path] = [
            {
                "algorithm": "SHA1",
                "checksumValue": sha1.hexdigest(),
            },
            {
                "algorithm": "SHA256",
                "checksumValue": sha256.hexdigest(),
            },
        ]
        log.debug(
            "Computed checksums for %s: SHA1=%s, SHA256=%s",
            relative_path,
            sha1.hexdigest(),
            sha256.hexdigest(),
        )

    # Update the SBOM with new checksums
    updated_count = 0
    for file_entry in data.get("files", []):
        file_name = file_entry.get("fileName")
        if file_name in checksums:
            file_entry["checksums"] = checksums[file_name]
            updated_count += 1
            log.info("Updated SBOM checksums for %s", file_name)

    # Write back the updated SBOM
    with open(spdx_json, "w") as f:
        json.dump(data, f, indent=2)

    log.info("Updated %d file checksums in SBOM", updated_count)


def patch_shebang(path: PathLike, old: str, new: str) -> bool:
    """
    Replace a file's shebang.

    :param path: The path of the file to patch
    :type path: str
    :param old: The old shebang, will only patch when this is found
    :type old: str
    :param name: The new shebang to be written
    :type name: str
    """
    with open(path, "rb") as fp:
        try:
            data = fp.read(len(old.encode())).decode()
        except UnicodeError:
            return False
        except Exception as exc:
            log.warning("Unhandled exception: %r", exc)
            return False
        if data != old:
            log.warning("Shebang doesn't match: %s %r != %r", path, old, data)
            return False
        data = fp.read().decode()
    with open(path, "w") as fp:
        fp.write(new)
        fp.write(data)
    with open(path, "r") as fp:
        data = fp.read()
    log.info("Patched shebang of %s => %r", path, data)
    return True


def patch_shebangs(path: PathLike, old: str, new: str) -> None:
    """
    Traverse directory and patch shebangs.

    :param path: The of the directory to traverse
    :type path: str
    :param old: The old shebang, will only patch when this is found
    :type old: str
    :param name: The new shebang to be written
    :type name: str
    """
    for root, _dirs, files in os.walk(str(path)):
        for file in files:
            patch_shebang(os.path.join(root, file), old, new)


def _load_sysconfigdata_template() -> str:
    """Load the sysconfigdata template from disk.

    Returns:
        The Python code template for sysconfigdata module.

    Note:
        This is loaded from a .py file rather than embedded as a string
        to enable syntax checking, IDE support, and easier maintenance.
        Follows CPython convention of separating data from code.
    """
    template_path = pathlib.Path(__file__).parent / "_sysconfigdata_template.py"
    template_content = template_path.read_text(encoding="utf-8")

    # Extract only the code after the docstring
    # Skip the copyright header and module docstring
    lines = template_content.split("\n")
    code_lines = []
    found_code = False

    for line in lines:
        # Skip until we find the first import statement
        if not found_code:
            if line.startswith("import ") or line.startswith("from "):
                found_code = True
            else:
                continue

        code_lines.append(line)

    return "\n".join(code_lines)


def update_ensurepip(directory: pathlib.Path) -> None:
    """
    Update bundled dependencies for ensurepip (pip & setuptools).
    """
    # ensurepip bundle location
    bundle_dir = directory / "ensurepip" / "_bundled"

    # Make sure the destination directory exists
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Detect existing whl. Later versions of python don't include setuptools. We
    # only want to update whl files that python expects to be there
    pip_version = "25.2"
    setuptools_version = "80.9.0"
    update_pip = False
    update_setuptools = False
    for file in bundle_dir.glob("*.whl"):

        log.debug("Checking whl: %s", str(file))
        if file.name.startswith("pip-"):
            found_version = file.name.split("-")[1]
            log.debug("Found version %s", found_version)
            if Version(found_version) >= Version(pip_version):
                log.debug("Found correct pip version or newer: %s", found_version)
            else:
                file.unlink()
                update_pip = True
        if file.name.startswith("setuptools-"):
            found_version = file.name.split("-")[1]
            log.debug("Found version %s", found_version)
            if Version(found_version) >= Version(setuptools_version):
                log.debug(
                    "Found correct setuptools version or newer: %s", found_version
                )
            else:
                file.unlink()
                update_setuptools = True

    # Download whl files and update __init__.py
    init_file = directory / "ensurepip" / "__init__.py"
    if update_pip:
        whl = f"pip-{pip_version}-py3-none-any.whl"
        whl_path = "b7/3f/945ef7ab14dc4f9d7f40288d2df998d1837ee0888ec3659c813487572faa"
        url = f"https://files.pythonhosted.org/packages/{whl_path}/{whl}"
        download_url(url=url, dest=bundle_dir)
        assert (bundle_dir / whl).exists()

        # Update __init__.py
        old = "^_PIP_VERSION.*"
        new = f'_PIP_VERSION = "{pip_version}"'
        patch_file(path=init_file, old=old, new=new)

    # setuptools
    if update_setuptools:
        whl = f"setuptools-{setuptools_version}-py3-none-any.whl"
        whl_path = "a3/dc/17031897dae0efacfea57dfd3a82fdd2a2aeb58e0ff71b77b87e44edc772"
        url = f"https://files.pythonhosted.org/packages/{whl_path}/{whl}"
        download_url(url=url, dest=bundle_dir)
        assert (bundle_dir / whl).exists()

        # setuptools
        old = "^_SETUPTOOLS_VERSION.*"
        new = f'_SETUPTOOLS_VERSION = "{setuptools_version}"'
        patch_file(path=init_file, old=old, new=new)

    log.debug("ensurepip __init__.py contents:")
    log.debug(init_file.read_text())


def install_sysdata(
    mod: ModuleType,
    destfile: PathLike,
    buildroot: PathLike,
    toolchain: Optional[PathLike],
) -> None:
    """
    Create a Relenv Python environment's sysconfigdata.

    Helper method used by the `finalize` build method to create a Relenv
    Python environment's sysconfigdata.

    :param mod: The module to operate on
    :type mod: ``types.ModuleType``
    :param destfile: Path to the file to write the data to
    :type destfile: str
    :param buildroot: Path to the root of the build
    :type buildroot: str
    :param toolchain: Path to the root of the toolchain
    :type toolchain: str
    """
    data = {}

    def fbuildroot(s: str) -> str:
        return s.replace(str(buildroot), "{BUILDROOT}")

    def ftoolchain(s: str) -> str:
        return s.replace(str(toolchain), "{TOOLCHAIN}")

    # XXX: keymap is not used, remove it?
    # keymap = {
    #    "BINDIR": (fbuildroot,),
    #    "BINLIBDEST": (fbuildroot,),
    #    "CFLAGS": (fbuildroot, ftoolchain),
    #    "CPPLAGS": (fbuildroot, ftoolchain),
    #    "CXXFLAGS": (fbuildroot, ftoolchain),
    #    "datarootdir": (fbuildroot,),
    #    "exec_prefix": (fbuildroot,),
    #    "LDFLAGS": (fbuildroot, ftoolchain),
    #    "LDSHARED": (fbuildroot, ftoolchain),
    #    "LIBDEST": (fbuildroot,),
    #    "prefix": (fbuildroot,),
    #    "SCRIPTDIR": (fbuildroot,),
    # }
    for key in sorted(mod.build_time_vars):
        val = mod.build_time_vars[key]
        if isinstance(val, str):
            for _ in (fbuildroot, ftoolchain):
                val = _(val)
                log.info("SYSCONFIG [%s] %s => %s", key, mod.build_time_vars[key], val)
        data[key] = val

    sysconfigdata_code = _load_sysconfigdata_template()
    with open(destfile, "w", encoding="utf8") as f:
        f.write(
            "# system configuration generated and used by" " the relenv at runtime\n"
        )
        f.write("_build_time_vars = ")
        pprint.pprint(data, stream=f)
        f.write(sysconfigdata_code)


def find_sysconfigdata(pymodules: PathLike) -> str:
    """
    Find sysconfigdata directory for python installation.

    :param pymodules: Path to python modules (e.g. lib/python3.10)
    :type pymodules: str

    :return: The name of the sysconig data module
    :rtype: str
    """
    for root, dirs, files in os.walk(pymodules):
        for file in files:
            if file.find("sysconfigdata") > -1 and file.endswith(".py"):
                return file[:-3]
    raise MissingDependencyError("Unable to locate sysconfigdata module")


def install_runtime(sitepackages: PathLike) -> None:
    """
    Install a base relenv runtime.
    """
    site_dir = pathlib.Path(sitepackages)
    relenv_pth = site_dir / "relenv.pth"
    with io.open(str(relenv_pth), "w") as fp:
        fp.write(RELENV_PTH)

    # Lay down relenv.runtime, we'll pip install the rest later
    relenv = site_dir / "relenv"
    os.makedirs(relenv, exist_ok=True)

    for name in [
        "runtime.py",
        "relocate.py",
        "common.py",
        "buildenv.py",
        "__init__.py",
    ]:
        src = MODULE_DIR / name
        dest = relenv / name
        with io.open(src, "r") as rfp:
            with io.open(dest, "w") as wfp:
                wfp.write(rfp.read())


def finalize(
    env: MutableMapping[str, str],
    dirs: Dirs,
    logfp: IO[str],
) -> None:
    """
    Run after we've fully built python.

    This method enhances the newly created python with Relenv's runtime hacks.

    :param env: The environment dictionary
    :type env: dict
    :param dirs: The working directories
    :type dirs: ``relenv.build.common.Dirs``
    :param logfp: A handle for the log file
    :type logfp: file
    """
    # Run relok8 to make sure the rpaths are relocatable.
    # Modules that don't link to relenv libs will have their RPATH removed
    relenv.relocate.main(
        dirs.prefix,
        log_file_name=str(dirs.logs / "relocate.py.log"),
    )
    # Install relenv-sysconfigdata module
    libdir = pathlib.Path(dirs.prefix) / "lib"

    def find_pythonlib(libdir: pathlib.Path) -> Optional[str]:
        for _root, dirs, _files in os.walk(libdir):
            for entry in dirs:
                if entry.startswith("python"):
                    return entry
        return None

    python_lib = find_pythonlib(libdir)
    if python_lib is None:
        raise MissingDependencyError("Unable to locate python library directory")

    pymodules = libdir / python_lib

    # update ensurepip
    update_ensurepip(pymodules)

    cwd = os.getcwd()
    modname = find_sysconfigdata(pymodules)
    path = sys.path
    sys.path = [str(pymodules)]
    try:
        mod = __import__(str(modname))
    finally:
        os.chdir(cwd)
        sys.path = path

    dest = pymodules / f"{modname}.py"
    install_sysdata(mod, dest, dirs.prefix, dirs.toolchain)

    # Lay down site customize
    bindir = pathlib.Path(dirs.prefix) / "bin"
    sitepackages = pymodules / "site-packages"
    install_runtime(sitepackages)

    # Install pip
    python_exe = str(dirs.prefix / "bin" / "python3")
    if env["RELENV_HOST_ARCH"] != env["RELENV_BUILD_ARCH"]:
        env["RELENV_CROSS"] = str(dirs.prefix)
        python_exe = env["RELENV_NATIVE_PY"]
    logfp.write("\nRUN ENSURE PIP\n")

    env.pop("RELENV_BUILDENV")

    runcmd(
        [python_exe, "-m", "ensurepip"],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )

    # Fix the shebangs in the scripts python layed down. Order matters.
    shebangs = [
        "#!{}".format(bindir / f"python{env['RELENV_PY_MAJOR_VERSION']}"),
        "#!{}".format(
            bindir / f"python{env['RELENV_PY_MAJOR_VERSION'].split('.', 1)[0]}"
        ),
    ]
    newshebang = format_shebang("/python3")
    for shebang in shebangs:
        log.info("Patch shebang %r with  %r", shebang, newshebang)
        patch_shebangs(
            str(pathlib.Path(dirs.prefix) / "bin"),
            shebang,
            newshebang,
        )

    if sys.platform == "linux":
        pyconf = f"config-{env['RELENV_PY_MAJOR_VERSION']}-{env['RELENV_HOST']}"
        patch_shebang(
            str(pymodules / pyconf / "python-config.py"),
            "#!{}".format(str(bindir / f"python{env['RELENV_PY_MAJOR_VERSION']}")),
            format_shebang("../../../bin/python3"),
        )

        toolchain_path = dirs.toolchain
        if toolchain_path is None:
            raise MissingDependencyError("Toolchain path is required for linux builds")
        shutil.copy(
            pathlib.Path(toolchain_path)
            / env["RELENV_HOST"]
            / "sysroot"
            / "lib"
            / "libstdc++.so.6",
            libdir,
        )

    # Moved in python 3.13 or removed?
    if (pymodules / "cgi.py").exists():
        patch_shebang(
            str(pymodules / "cgi.py"),
            "#! /usr/local/bin/python",
            format_shebang("../../bin/python3"),
        )

    def runpip(pkg: Union[str, os.PathLike[str]], upgrade: bool = False) -> None:
        logfp.write(f"\nRUN PIP {pkg} {upgrade}\n")
        target: Optional[pathlib.Path] = None
        python_exe = str(dirs.prefix / "bin" / "python3")
        if sys.platform == LINUX:
            if env["RELENV_HOST_ARCH"] != env["RELENV_BUILD_ARCH"]:
                target = pymodules / "site-packages"
                python_exe = env["RELENV_NATIVE_PY"]
        cmd = [
            python_exe,
            "-m",
            "pip",
            "install",
            str(pkg),
        ]
        if upgrade:
            cmd.append("--upgrade")
        if target:
            cmd.append("--target={}".format(target))
        runcmd(cmd, env=env, stderr=logfp, stdout=logfp)

    runpip("wheel")
    # This needs to handle running from the root of the git repo and also from
    # an installed Relenv
    if (MODULE_DIR.parent / ".git").exists():
        runpip(MODULE_DIR.parent, upgrade=True)
    else:
        runpip("relenv", upgrade=True)
    globs = [
        "/bin/python*",
        "/bin/pip*",
        "/bin/relenv",
        "/lib/python*/ensurepip/*",
        "/lib/python*/site-packages/*",
        "/include/*",
        "*.so",
        "/lib/*.so.*",
        "*.py",
        # Mac specific, factor this out
        "*.dylib",
    ]
    archive = f"{ dirs.prefix }.tar.xz"
    log.info("Archive is %s", archive)
    with tarfile.open(archive, mode="w:xz") as fp:
        create_archive(fp, dirs.prefix, globs, logfp)


def create_archive(
    tarfp: tarfile.TarFile,
    toarchive: PathLike,
    globs: Sequence[str],
    logfp: Optional[IO[str]] = None,
) -> None:
    """
    Create an archive.

    :param tarfp: A pointer to the archive to be created
    :type tarfp: file
    :param toarchive: The path to the directory to archive
    :type toarchive: str
    :param globs: A list of filtering patterns to match against files to be added
    :type globs: list
    :param logfp: A pointer to the log file
    :type logfp: file
    """
    log.debug("Current directory %s", os.getcwd())
    log.debug("Creating archive %s", tarfp.name)
    for root, _dirs, files in os.walk(toarchive):
        relroot = pathlib.Path(root).relative_to(toarchive)
        for f in files:
            relpath = relroot / f
            matches = False
            for g in globs:
                candidate = pathlib.Path("/") / relpath
                if fnmatch.fnmatch(str(candidate), g):
                    matches = True
                    break
            if matches:
                log.debug("Adding %s", relpath)
                tarfp.add(relpath, arcname=str(relpath), recursive=False)
            else:
                log.debug("Skipping %s", relpath)
