"""
This code is run when initializing the python interperter in a Mayflower
environment.

- Point Mayflower's Openssl to the system installed Openssl certificate path
- Make sure pip creates scripts with a shebang that points to the correct
  python using a relative path.
- On linux, provide pip with the proper location of the Mayflower toolchain
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

SYSCONFIGDATA = "_sysconfigdata__linux_{arch}-linux-gnu"


def debug(string):
    if os.environ.get("MAYFLOWER_DEBUG"):
        print(string)


def _build_shebang(*args, **kwargs):
    if sys.platform == "win32":
        if os.environ.get("MAYFLOWER_PIP_DIR"):
            return "#!<launch_dir>\\Scripts\\python.exe".encode()
        return "#!<launcher_dir>\\python.exe".encode()
    if os.environ.get("MAYFLOWER_PIP_DIR"):
        return ("#!/bin/sh\n" '"exec" "`dirname $0`/bin/python3" "$0" "$@"').encode()
    return ("#!/bin/sh\n" '"exec" "`dirname $0`/python3" "$0" "$@"').encode()


def get_config_var_wrapper(func):
    def wrapped(name):
        if name == "BINDIR":
            orig = func(name)
            if os.environ.get("MAYFLOWER_PIP_DIR"):
                val = "../"
            else:
                val = "./"
            debug(f"get_config_var call {name} old: {orig} new: {val}")
            return val
        else:
            val = func(name)
            debug(f"get_config_var call {name} {val}")
            return val

    return wrapped


class MayflowerImporter:

    loading_pip_scripts = False
    loading_sysconfig_data = False
    loading_sysconfig = False

    build_time_vars = None
    sysconfigdata = "_sysconfigdata__linux_x86_64-linux-gnu"

    def find_module(self, module_name, package_path=None):
        if module_name.startswith("sysconfig") and sys.platform == "win32":
            if self.loading_sysconfig:
                return None
            debug(f"MayflowerImporter - match {module_name}")
            self.loading_sysconfig = True
            return self
        elif module_name == "pip._vendor.distlib.scripts":
            if self.loading_pip_scripts:
                return None
            debug(f"MayflowerImporter - match {module_name}")
            self.loading_pip_scripts = True
            return self
        elif module_name == self.sysconfigdata:
            if self.loading_sysconfig_data:
                return None
            debug(f"MayflowerImporter - match {module_name}")
            self.loading_sysconfig_data = True
            return self
        return None

    def load_module(self, name):
        if name.startswith("sysconfig"):
            debug(f"MayflowerImporter - load_module {name}")
            mod = importlib.import_module("sysconfig")
            mod.get_config_var = get_config_var_wrapper(mod.get_config_var)
            self.loading_sysconfig = False
        elif name == "pip._vendor.distlib.scripts":
            debug(f"MayflowerImporter - load_module {name}")
            mod = importlib.import_module(name)
            mod.ScriptMaker._build_shebang = _build_shebang
            self.loading_pip_scripts = False
        elif name == self.sysconfigdata:
            debug(f"MayflowerImporter - load_module {name}")
            mod = importlib.import_module(name)
            try:
                maymod = importlib.import_module("mayflower-sysconfigdata")
            except ImportError:
                debug("Unable to import mayflower-sysconfigdata")
                return mod
            buildroot = MODULE_DIR.parent.parent.parent.parent
            toolchain = MODULE_DIR / "_toolchain" / "x86_64-linux-gnu"
            build_time_vars = {}
            for key in maymod.build_time_vars:
                val = maymod.build_time_vars[key]
                if isinstance(val, str):
                    val = val.format(
                        BUILDROOT=buildroot,
                        TOOLCHAIN=toolchain,
                    )
                build_time_vars[key] = val
                # self.build_time_vars.build_time_vars = build_time_vars
                mod.build_time_vars = build_time_vars
            self.loading_sysconfig_data = False
            return self
        sys.modules[name] = mod
        return mod


class BuildTimeVars(collections.abc.Mapping):

    # This is getting set in MayflowerImporter
    _build_time_vars = {}

    def __getitem__(self, key, *args, **kwargs):
        debug(f"BuildTimeVars - getitem {name}")
        val = self._build_time_vars.__getitem__(key, *args, **kwargs)
        sys.stdout.flush()
        if key == "BINDIR":
            return self.buildroot
        if isinstance(val, str):
            return val.format(
                BUILDROOT=self.buildroot,
                TOOLCHAIN=self.toolchain,
            )
        return val

    def __iter__(self):
        return iter(self._build_time_vars)

    def __len__(self):
        return len(self._build_time_vars)


def bootstrap():
    cross = os.environ.get("MAYFLOWER_CROSS", "")
    if cross:
        crossroot = pathlib.Path(cross).resolve()
        sys.prefix = str(crossroot)
        sys.exec_prefix = str(crossroot)
        sys.path = [
            str(crossroot / "lib" / "python3.10"),
            str(crossroot / "lib" / "python3.10" / "lib-dynload"),
            str(crossroot / "lib" / "python3.10" / "site-packages"),
        ] + [x for x in sys.path if x.find("site-packages") == -1]
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

        label, _ = proc.stdout.split(":")
        path = pathlib.Path(_.strip().strip('"'))
        os.environ["SSL_CERT_DIR"] = str(path / "certs")
    build_time_vars = BuildTimeVars()
    importer = MayflowerImporter()
    importer.build_time_vars = build_time_vars
    sys.meta_path = [importer] + sys.meta_path
