# Copyright 2022 VMware, Inc.
# SPDX-License-Identifier: Apache-2
"""
This code is run when initializing the python interperter in a Relenv
environment.

- Point Relenv's Openssl to the system installed Openssl certificate path
- Make sure pip creates scripts with a shebang that points to the correct
  python using a relative path.
- On linux, provide pip with the proper location of the Relenv toolchain
  gcc. This ensures when using pip any c dependencies are compiled against the
  proper glibc version.
"""
import collections.abc
import importlib
import os
import pathlib
import shutil
import subprocess
import sys

from .common import MODULE_DIR


def debug(string):
    """
    Prints the provided message if RELENV_DEBUG is truthy in the environment.

    :param string: The message to print
    :type string: str
    """
    if os.environ.get("RELENV_DEBUG"):
        print(string)


def root():
    # XXX Look for rootdir / ".relenv"
    if sys.platform == "win32":
        # /Lib/site-packages/relenv/
        return MODULE_DIR.parent.parent.parent
    # /lib/pythonX.X/site-packages/relenv/
    return MODULE_DIR.parent.parent.parent.parent


def _build_shebang(*args, **kwargs):
    """
    Build a shebang to point to the proper location

    :return: The shebang
    :rtype: bytes
    """
    if sys.platform == "win32":
        if os.environ.get("RELENV_PIP_DIR"):
            return "#!<launch_dir>\\Scripts\\python.exe".encode()
        return "#!<launcher_dir>\\python.exe".encode()
    if os.environ.get("RELENV_PIP_DIR"):
        return ("#!/bin/sh\n" '"exec" "`dirname $0`/bin/python3" "$0" "$@"').encode()
    return ("#!/bin/sh\n" '"exec" "`dirname $0`/python3" "$0" "$@"').encode()


def get_config_var_wrapper(func):
    def wrapped(name):
        if name == "BINDIR":
            orig = func(name)
            if os.environ.get("RELENV_PIP_DIR"):
                val = root()
            else:
                val = root() / "Scripts"
            debug(f"get_config_var call {name} old: {orig} new: {val}")
            return val
        else:
            val = func(name)
            debug(f"get_config_var call {name} {val}")
            return val

    return wrapped


def get_paths_wrapper(func, default_scheme):
    def wrapped(scheme=default_scheme, vars=None, expand=True):
        paths = func(scheme=scheme, vars=vars, expand=expand)
        if "RELENV_PIP_DIR" in os.environ:
            paths["scripts"] = str(root())
            sys.exec_prefix = paths["scripts"]
        return paths

    return wrapped


class RelenvImporter:
    """
    An importer to be added to ``sys.meta_path`` to handle importing into a relenv environment.
    """

    loading_pip_scripts = False
    loading_sysconfig_data = False
    loading_sysconfig = False

    sysconfigdata = "_sysconfigdata__linux_x86_64-linux-gnu"

    def find_module(self, module_name, package_path=None):
        """
        Find a module for importing into the relenv environment

        :param module_name: The name of the module
        :type module_name: str
        :param package_path: The path to the package, defaults to None
        :type package_path: str, optional
        :return: The instance that called this method if it found the module, or None if it didn't
        :rtype: RelenvImporter or None
        """
        if module_name.startswith("sysconfig"):  # and sys.platform == "win32":
            if self.loading_sysconfig:
                return None
            debug(f"RelenvImporter - match {module_name}")
            self.loading_sysconfig = True
            return self
        elif module_name == "pip._vendor.distlib.scripts":
            if self.loading_pip_scripts:
                return None
            debug(f"RelenvImporter - match {module_name}")
            self.loading_pip_scripts = True
            return self
        return None

    def load_module(self, name):
        """
        Load the given module

        :param name: The module name to load
        :type name: str
        :return: The loaded module or the calling instance if importing sysconfigdata
        :rtype: types.ModuleType or RelenvImporter
        """
        if name.startswith("sysconfig"):
            debug(f"RelenvImporter - load_module {name}")
            mod = importlib.import_module("sysconfig")
            mod.get_config_var = get_config_var_wrapper(mod.get_config_var)
            mod._PIP_USE_SYSCONFIG = True
            try:
                # Python >= 3.10
                scheme = mod.get_default_scheme()
            except AttributeError:
                # Python < 3.10
                scheme = mod._get_default_scheme()
            mod.get_paths = get_paths_wrapper(mod.get_paths, scheme)
            self.loading_sysconfig = False
        elif name == "pip._vendor.distlib.scripts":
            debug(f"RelenvImporter - load_module {name}")
            mod = importlib.import_module(name)
            mod.ScriptMaker._build_shebang = _build_shebang
            self.loading_pip_scripts = False
        sys.modules[name] = mod
        return mod


def bootstrap():
    """
    Bootstrap the relenv environment.
    """
    cross = os.environ.get("RELENV_CROSS", "")
    if cross:
        crossroot = pathlib.Path(cross).resolve()
        sys.prefix = str(crossroot)
        sys.exec_prefix = str(crossroot)
        # XXX What about dist-packages
        sys.path = [
            str(crossroot / "lib" / "python3.10"),
            str(crossroot / "lib" / "python3.10" / "lib-dynload"),
            str(crossroot / "lib" / "python3.10" / "site-packages"),
        ] + [_ for _ in sys.path if "site-packages" not in _]

    # Use system openssl dirs
    # XXX Should we also setup SSL_CERT_FILE, OPENSSL_CONF &
    # OPENSSL_CONF_INCLUDE?
    if "SSL_CERT_DIR" not in os.environ and sys.platform != "win32":
        openssl_bin = shutil.which("openssl")
        if not openssl_bin:
            debug("Could not find the 'openssl' binary in the path")
            return

        proc = subprocess.run(
            [openssl_bin, "version", "-d"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            shell=False,
            check=False,
        )
        if proc.returncode != 0:
            msg = "Unable to get the certificates directory from openssl"
            if proc.stderr:
                msg += f": {proc.stderr}"
            debug(msg)
            return

        _, directory = proc.stdout.split(":")
        path = pathlib.Path(directory.strip().strip('"'))
        os.environ["SSL_CERT_DIR"] = str(path / "certs")
        os.environ["SSL_CERT_FILE"] = str(path / "cert.pem")

    importer = RelenvImporter()
    sys.meta_path = [importer] + sys.meta_path
