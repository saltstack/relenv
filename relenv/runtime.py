# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
This code is run when initializing the python interperter in a Relenv environment.

- Point Relenv's Openssl to the system installed Openssl certificate path
- Make sure pip creates scripts with a shebang that points to the correct
  python using a relative path.
- On linux, provide pip with the proper location of the Relenv toolchain
  gcc. This ensures when using pip any c dependencies are compiled against the
  proper glibc version.
"""
from __future__ import annotations

import contextlib
import ctypes as _ctypes
import functools
import importlib as _importlib
import json as _json
import os
import pathlib
import shutil as _shutil
import site as _site
import subprocess as _subprocess
import sys as _sys
import textwrap
import warnings as _warnings
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    Optional,
    Sequence,
    Union,
    cast,
)

# The tests monkeypatch these module-level imports (e.g., json.loads) inside
# relenv.runtime itself; keeping them as Any both preserves test isolation—no
# need to patch the global stdlib modules—and avoids mypy attr-defined noise
# while still exercising the real runtime wiring.
json = cast(Any, _json)
importlib = cast(Any, _importlib)
site = cast(Any, _site)
subprocess = cast(Any, _subprocess)
sys = cast(Any, _sys)
ctypes = cast(Any, _ctypes)
shutil = cast(Any, _shutil)
warnings = cast(Any, _warnings)

__all__ = [
    "sys",
    "shutil",
    "subprocess",
    "json",
    "importlib",
    "site",
    "ctypes",
    "warnings",
]

PathType = Union[str, os.PathLike[str]]
ConfigVars = Dict[str, str]

# relenv.pth has a __file__ which is set to the path to site.py of the python
# interpreter being used. We're using that to determine the proper
# relenv.runtime to import. Working around the rest of the import mechanisims.
# Import any other needed modules from this same relenv. This prevents pulling
# in a relenv from some other location in the path and is needed because these
# imports happen before our path munghing in site in wrapsitecustomize.


def path_import(name: str, path: PathType) -> ModuleType:
    """
    Import module from a path.

    This causes hashlib to be imported because of importing importlib.util so
    it can not be used until after openssl has been configured.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


def common() -> ModuleType:
    """
    Late import relenv common.
    """
    if not hasattr(common, "common"):
        common.common = path_import(
            "relenv.common", str(pathlib.Path(__file__).parent / "common.py")
        )
    return cast(ModuleType, common.common)


def relocate() -> ModuleType:
    """
    Late import relenv relocate.
    """
    if not hasattr(relocate, "relocate"):
        relocate.relocate = path_import(
            "relenv.relocate", str(pathlib.Path(__file__).parent / "relocate.py")
        )
    return cast(ModuleType, relocate.relocate)


def buildenv() -> ModuleType:
    """
    Late import relenv buildenv.
    """
    if not hasattr(buildenv, "builenv"):
        buildenv.buildenv = path_import(
            "relenv.buildenv", str(pathlib.Path(__file__).parent / "buildenv.py")
        )
    return cast(ModuleType, buildenv.buildenv)


def get_major_version() -> str:
    """
    Current python major version.
    """
    return "{}.{}".format(*sys.version_info)


@contextlib.contextmanager
def pushd(new_dir: PathType) -> Iterator[None]:
    """
    Changedir context.
    """
    old_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(old_dir)


def debug(string: str) -> None:
    """
    Prints the provided message if RELENV_DEBUG is truthy in the environment.

    :param string: The message to print
    :type string: str
    """
    if os.environ.get("RELENV_DEBUG"):
        print(string)
        sys.stdout.flush()


def relenv_root() -> pathlib.Path:
    """
    Return the relenv module root.
    """
    MODULE_DIR = pathlib.Path(__file__).resolve().parent
    # XXX Look for rootdir / ".relenv"
    if sys.platform == "win32":
        # /Lib/site-packages/relenv/
        return MODULE_DIR.parent.parent.parent
    # /lib/pythonX.X/site-packages/relenv/
    return MODULE_DIR.parent.parent.parent.parent


def _build_shebang(
    func: Callable[..., bytes], *args: Any, **kwargs: Any
) -> Callable[..., bytes]:
    """
    Build a shebang to point to the proper location.

    :return: The shebang
    :rtype: bytes
    """

    @functools.wraps(func)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> bytes:
        scripts = pathlib.Path(self.target_dir)
        if TARGET.TARGET:
            scripts = pathlib.Path(_ensure_target_path()).absolute() / "bin"
        try:
            interpreter = common().relative_interpreter(
                sys.RELENV, scripts, pathlib.Path(sys.executable).resolve()
            )
        except ValueError:
            debug(f"Relenv Value Error - _build_shebang {self.target_dir}")
            return func(self, *args, **kwargs)
        debug(f"Relenv - _build_shebang {scripts} {interpreter}")
        if sys.platform == "win32":
            return (
                str(pathlib.Path("#!<launcher_dir>") / interpreter).encode() + b"\r\n"
            )
        return common().format_shebang("/" / interpreter).encode()

    return wrapped


def get_config_var_wrapper(func: Callable[[str], Any]) -> Callable[[str], Any]:
    """
    Return a wrapper to resolve paths relative to the relenv root.
    """

    @functools.wraps(func)
    def wrapped(name: str) -> Any:
        if name == "BINDIR":
            orig = func(name)
            if os.environ.get("RELENV_PIP_DIR"):
                val = relenv_root()
            else:
                val = relenv_root() / "Scripts"
            debug(f"get_config_var call {name} old: {orig} new: {val}")
            return val
        else:
            val = func(name)
            debug(f"get_config_var call {name} {val}")
            return val

    return wrapped


CONFIG_VARS_DEFAULTS: ConfigVars = {
    "AR": "ar",
    "CC": "gcc",
    "CFLAGS": "-Wno-unused-result -Wsign-compare -DNDEBUG -g -fwrapv -O3 -Wall",
    "CPPFLAGS": "-I. -I./Include",
    "CXX": "g++",
    "LIBDEST": "/usr/local/lib/python3.10",
    "SCRIPTDIR": "/usr/local/lib",
    "BLDSHARED": "gcc -shared",
    "LDFLAGS": "",
    "LDCXXSHARED": "g++ -shared",
    "LDSHARED": "gcc -shared",
}

_SYSTEM_CONFIG_VARS: Optional[ConfigVars] = None


def system_sysconfig() -> ConfigVars:
    """
    Read the system python's sysconfig values.

    Th system python isthe one installed by your package manager. Memoize them
    to avoid the overhead of shelling out.
    """
    global _SYSTEM_CONFIG_VARS
    if _SYSTEM_CONFIG_VARS:
        return _SYSTEM_CONFIG_VARS
    pyexec = pathlib.Path("/usr/bin/python3")
    if pyexec.exists():
        p = subprocess.run(
            [
                str(pyexec),
                "-c",
                "import json, sysconfig; print(json.dumps(sysconfig.get_config_vars()))",
            ],
            capture_output=True,
        )
        try:
            _SYSTEM_CONFIG_VARS = json.loads(p.stdout.strip())
        except json.JSONDecodeError:
            debug(f"Failed to load JSON from: {p.stdout.strip()}")
            _SYSTEM_CONFIG_VARS = CONFIG_VARS_DEFAULTS
    else:
        debug("System python not found")
        _SYSTEM_CONFIG_VARS = CONFIG_VARS_DEFAULTS
    return _SYSTEM_CONFIG_VARS


def get_config_vars_wrapper(
    func: Callable[..., ConfigVars], mod: ModuleType
) -> Callable[..., ConfigVars]:
    """
    Return a wrapper to resolve paths relative to the relenv root.
    """

    @functools.wraps(func)
    def wrapped(*args: Any) -> ConfigVars:
        if sys.platform == "win32" or "RELENV_BUILDENV" in os.environ:
            return func(*args)

        config_vars = func()
        system_config_vars = system_sysconfig()
        for name in [
            "AR",
            "CC",
            "CFLAGS",
            "CPPFLAGS",
            "CXX",
            "LIBDEST",
            "SCRIPTDIR",
            "BLDSHARED",
            "LDFLAGS",
            "LDCXXSHARED",
            "LDSHARED",
        ]:
            config_vars[name] = system_config_vars[name]
        mod._CONFIG_VARS = config_vars
        return func(*args)

    return wrapped


def get_paths_wrapper(
    func: Callable[..., Dict[str, str]], default_scheme: str
) -> Callable[..., Dict[str, str]]:
    """
    Return a wrapper to resolve paths relative to the relenv root.
    """

    @functools.wraps(func)
    def wrapped(
        scheme: Optional[str] = default_scheme,
        vars: Optional[Dict[str, str]] = None,
        expand: bool = True,
    ) -> Dict[str, str]:
        paths = func(scheme=scheme, vars=vars, expand=expand)
        if "RELENV_PIP_DIR" in os.environ:
            paths["scripts"] = str(relenv_root())
            sys.exec_prefix = paths["scripts"]
        return paths

    return wrapped


def finalize_options_wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Wrapper around build_ext.finalize_options.

    Used to add the relenv environment's include path.
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> None:
        func(self, *args, **kwargs)
        if "RELENV_BUILDENV" in os.environ:
            self.include_dirs.append(str(relenv_root() / "include"))

    return wrapper


def install_wheel_wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Wrap pip's wheel install function.

    This method determines any newly installed files and checks their RPATHs.
    """

    @functools.wraps(func)
    def wrapper(
        name: str,
        wheel_path: PathType,
        scheme: Any,
        req_description: str,
        pycompile: Any,
        warn_script_location: Any,
        direct_url: Any,
        requested: Any,
    ) -> Any:
        from zipfile import ZipFile

        from pip._internal.utils.wheel import parse_wheel

        with ZipFile(wheel_path) as zf:
            info_dir, metadata = parse_wheel(zf, name)
        func(
            name,
            wheel_path,
            scheme,
            req_description,
            pycompile,
            warn_script_location,
            direct_url,
            requested,
        )
        plat = pathlib.Path(scheme.platlib)
        rootdir = relenv_root()
        with open(plat / info_dir / "RECORD") as fp:
            for line in fp.readlines():
                file = plat / line.split(",", 1)[0]
                if not file.exists():
                    debug(f"Relenv - File not found {file}")
                    continue
                if relocate().is_elf(file):
                    debug(f"Relenv - Found elf {file}")
                    relocate().handle_elf(plat / file, rootdir / "lib", True, rootdir)
                elif relocate().is_macho(file):
                    otool_bin = shutil.which("otool")
                    if otool_bin:
                        relocate().handle_macho(str(plat / file), str(rootdir), True)
                    else:
                        debug(
                            "The otool command is not available, please run `xcode-select --install`"
                        )

    return wrapper


def install_legacy_wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Wrap pip's legacy install function.

    This method determines any newly installed files and checks their RPATHs.
    """
    # XXX It might be better to handle legacy installs by overriding things in
    # setuptools, would we get more bang for our buck or increase complexity?

    @functools.wraps(func)
    def wrapper(
        install_options: Any,
        global_options: Any,
        root: Any,
        home: Any,
        prefix: Any,
        use_user_site: Any,
        pycompile: Any,
        scheme: Any,
        setup_py_path: Any,
        isolated: Any,
        req_name: Any,
        build_env: Any,
        unpacked_source_directory: Any,
        req_description: Any,
    ) -> Any:

        pkginfo = pathlib.Path(setup_py_path).parent / "PKG-INFO"
        with open(pkginfo) as fp:
            pkg_info = fp.read()
        version = None
        name = None
        for line in pkg_info.splitlines():
            if line.startswith("Version:"):
                version = line.split("Version: ")[1].strip()
                if name:
                    break
            if line.startswith("Name:"):
                name = line.split("Name: ")[1].strip()
                if version:
                    break
        func(
            install_options,
            global_options,
            root,
            home,
            prefix,
            use_user_site,
            pycompile,
            scheme,
            setup_py_path,
            isolated,
            req_name,
            build_env,
            unpacked_source_directory,
            req_description,
        )
        egginfo = None
        if prefix:
            sitepack = (
                pathlib.Path(prefix)
                / "lib"
                / f"python{get_major_version()}"
                / "site-packages"
            )
            for path in sorted(sitepack.glob("*.egg-info")):
                if path.name.startswith(f"{name}-{version}"):
                    egginfo = path
                    break
        for path in sorted(pathlib.Path(scheme.purelib).glob("*.egg-info")):
            if path.name.startswith(f"{name}-{version}"):
                egginfo = path
                break
        if egginfo is None:
            debug(f"Relenv was not able to find egg info for: {req_description}")
            return
        plat = pathlib.Path(scheme.platlib)
        rootdir = relenv_root()
        with pushd(egginfo):
            with open("installed-files.txt") as fp:
                for line in fp.readlines():
                    file = pathlib.Path(line.strip()).resolve()
                    if not file.exists():
                        debug(f"Relenv - File not found {file}")
                        continue
                    if relocate().is_elf(file):
                        debug(f"Relenv - Found elf {file}")
                        relocate().handle_elf(
                            plat / file, rootdir / "lib", True, rootdir
                        )

    return wrapper


class Wrapper:
    """
    Wrap methods of an imported module.
    """

    def __init__(
        self,
        module: str,
        wrapper: Callable[[str], ModuleType],
        matcher: str = "equals",
        _loading: bool = False,
    ) -> None:
        self.module = module
        self.wrapper = wrapper
        self.matcher = matcher
        self.loading = _loading

    def matches(self: "Wrapper", module: str) -> bool:
        """
        Check if wrapper metches module being imported.
        """
        if self.matcher == "startswith":
            return module.startswith(self.module)
        return self.module == module

    def __call__(self: "Wrapper", module_name: str) -> ModuleType:
        """
        Preform the wrapper operation.
        """
        return self.wrapper(module_name)


class RelenvImporter:
    """
    Handle runtime wrapping of module methods.
    """

    def __init__(
        self,
        wrappers: Optional[Iterable[Wrapper]] = None,
        _loads: Optional[Dict[str, ModuleType]] = None,
    ) -> None:
        if wrappers is None:
            wrappers = []
        self.wrappers: set[Wrapper] = set(wrappers)
        if _loads is None:
            _loads = {}
        self._loads: Dict[str, ModuleType] = _loads

    def find_spec(
        self: "RelenvImporter",
        module_name: str,
        package_path: Optional[Sequence[str]] = None,
        target: Any = None,
    ) -> Optional[ModuleSpec]:
        """
        Find modules being imported.
        """
        for wrapper in self.wrappers:
            if wrapper.matches(module_name) and not wrapper.loading:
                debug(f"RelenvImporter - match {module_name} {package_path} {target}")
                wrapper.loading = True
                return importlib.util.spec_from_loader(module_name, self)

    def find_module(
        self: "RelenvImporter",
        module_name: str,
        package_path: Optional[Sequence[str]] = None,
    ) -> Optional["RelenvImporter"]:
        """
        Find modules being imported.
        """
        for wrapper in self.wrappers:
            if wrapper.matches(module_name) and not wrapper.loading:
                debug(f"RelenvImporter - match {module_name}")
                wrapper.loading = True
                return self

    def load_module(self: "RelenvImporter", name: str) -> ModuleType:
        """
        Load an imported module.
        """
        mod: Optional[ModuleType] = None
        for wrapper in self.wrappers:
            if wrapper.matches(name):
                debug(f"RelenvImporter - load_module {name}")
                mod = wrapper(name)
                wrapper.loading = False
                break
        if mod is None:
            mod = importlib.import_module(name)
        sys.modules[name] = mod
        return mod

    def create_module(self: "RelenvImporter", spec: ModuleSpec) -> Optional[ModuleType]:
        """
        Create the module via a spec.
        """
        return self.load_module(spec.name)

    def exec_module(self: "RelenvImporter", module: ModuleType) -> None:
        """
        Exec module noop.
        """
        return None


def wrap_sysconfig(name: str) -> ModuleType:
    """
    Sysconfig wrapper.
    """
    mod = importlib.import_module("sysconfig")
    mod.get_config_var = get_config_var_wrapper(mod.get_config_var)
    mod.get_config_vars = get_config_vars_wrapper(mod.get_config_vars, mod)
    mod._PIP_USE_SYSCONFIG = True
    try:
        # Python >= 3.10
        scheme = mod.get_default_scheme()
    except AttributeError:
        # Python < 3.10
        scheme = mod._get_default_scheme()
    mod.get_paths = get_paths_wrapper(mod.get_paths, scheme)
    return mod


def wrap_pip_distlib_scripts(name: str) -> ModuleType:
    """
    pip.distlib.scripts wrapper.
    """
    module = importlib.import_module(name)
    mod = cast(Any, module)
    mod.ScriptMaker._build_shebang = _build_shebang(mod.ScriptMaker._build_shebang)
    return mod


def wrap_distutils_command(name: str) -> ModuleType:
    """
    distutils.command wrapper.
    """
    mod = importlib.import_module(name)
    mod.build_ext.finalize_options = finalize_options_wrapper(
        mod.build_ext.finalize_options
    )
    return mod


def wrap_pip_install_wheel(name: str) -> ModuleType:
    """
    pip._internal.operations.install.wheel wrapper.
    """
    mod = importlib.import_module(name)
    mod.install_wheel = install_wheel_wrapper(mod.install_wheel)
    return mod


def wrap_pip_install_legacy(name: str) -> ModuleType:
    """
    pip._internal.operations.install.legacy wrapper.
    """
    mod = importlib.import_module(name)
    mod.install = install_legacy_wrapper(mod.install)
    return mod


def set_env_if_not_set(name: str, value: str) -> None:
    """
    Set an environment variable if not already set.

    If the environment variable is already set and not equal to value, warn the
    user.
    """
    if name in os.environ and os.environ[name] != value:
        print(
            f"Warning: {name} environment not set to relenv's root!\n"
            f"expected: {value}\ncurrent: {os.environ[name]}"
        )
    else:
        debug(f"Relenv set {name}")
        os.environ[name] = value


def wrap_pip_build_wheel(name: str) -> ModuleType:
    """
    pip._internal.operations.build wrapper.
    """
    mod = importlib.import_module(name)

    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if sys.platform != "linux":
                return func(*args, **kwargs)
            base_dir = common().DATA_DIR / "toolchain"
            toolchain = base_dir / common().get_triplet()
            cargo_home = str(common().DATA_DIR / "cargo")
            if not toolchain.exists():
                debug("Unable to set CARGO_HOME no toolchain exists")
            else:
                relenvroot = str(sys.RELENV)
                rustflags = (
                    f"-C link-arg=-Wl,-rpath,{relenvroot}/lib "
                    f"-C link-arg=-L{relenvroot}/lib "
                    f"-C link-arg=-L{toolchain}/sysroot/lib"
                )
                set_env_if_not_set("CARGO_HOME", cargo_home)
                set_env_if_not_set("OPENSSL_DIR", relenvroot)
                set_env_if_not_set("RUSTFLAGS", rustflags)
            return func(*args, **kwargs)

        return wrapper

    mod.build_wheel_pep517 = wrap(mod.build_wheel_pep517)
    return mod


class TARGET:
    """
    Container for global pip target state.
    """

    TARGET: bool = False
    PATH: Optional[str] = None
    IGNORE: bool = False
    INSTALL: bool = False


def _ensure_target_path() -> str:
    """
    Return the stored target path, raising if it is unavailable.
    """
    if TARGET.PATH is None:
        raise RuntimeError("TARGET path requested but not initialized")
    return TARGET.PATH


def wrap_cmd_install(name: str) -> ModuleType:
    """
    Wrap pip install command to store target argument state.
    """
    module = importlib.import_module(name)
    mod = cast(Any, module)

    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(self: Any, options: Any, args: Sequence[str]) -> Any:
            if not options.use_user_site:
                if options.target_dir:
                    TARGET.TARGET = True
                    TARGET.PATH = options.target_dir
                    TARGET.IGNORE = options.ignore_installed
            return func(self, options, args)

        return wrapper

    mod.InstallCommand.run = wrap(mod.InstallCommand.run)

    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(
            self: Any, target_dir: str, target_temp_dir: str, upgrade: bool
        ) -> int:
            from pip._internal.cli.status_codes import SUCCESS

            return SUCCESS

        return wrapper

    if hasattr(mod.InstallCommand, "_handle_target_dir"):
        mod.InstallCommand._handle_target_dir = wrap(
            mod.InstallCommand._handle_target_dir
        )
    return cast(ModuleType, mod)


def wrap_locations(name: str) -> ModuleType:
    """
    Wrap pip locations to fix locations when installing with target.
    """
    module = importlib.import_module(name)
    mod = cast(Any, module)

    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(
            dist_name: str,
            user: bool = False,
            home: Optional[PathType] = None,
            root: Optional[PathType] = None,
            isolated: bool = False,
            prefix: Optional[PathType] = None,
        ) -> Any:
            scheme = func(dist_name, user, home, root, isolated, prefix)
            if TARGET.TARGET and TARGET.INSTALL:
                from pip._internal.models.scheme import Scheme

                target_path = _ensure_target_path()
                scheme = Scheme(
                    platlib=target_path,
                    purelib=target_path,
                    headers=scheme.headers,
                    scripts=scheme.scripts,
                    data=scheme.data,
                )
            return scheme

        return wrapper

    # get_scheme is not available on pip-19.2.3
    # try:
    mod.get_scheme = wrap(mod.get_scheme)
    # except AttributeError:
    #    debug(f"Module {mod} does not have attribute get_scheme")

    return mod


def wrap_req_command(name: str) -> ModuleType:
    """
    Honor ignore installed option from pip cli.
    """
    mod = importlib.import_module(name)

    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(
            self: Any,
            options: Any,
            session: Any,
            target_python: Any = None,
            ignore_requires_python: Any = None,
        ) -> Any:
            if TARGET.TARGET:
                options.ignore_installed = TARGET.IGNORE
            return func(self, options, session, target_python, ignore_requires_python)

        return wrapper

    mod.RequirementCommand._build_package_finder = wrap(
        mod.RequirementCommand._build_package_finder
    )
    return cast(ModuleType, mod)


def wrap_req_install(name: str) -> ModuleType:
    """
    Honor ignore installed option from pip cli.
    """
    module = importlib.import_module(name)
    mod = cast(Any, module)

    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        argcount = mod.InstallRequirement.install.__code__.co_argcount

        if argcount == 7:

            @functools.wraps(func)
            def wrapper(
                self: Any,
                root: Optional[PathType] = None,
                home: Optional[PathType] = None,
                prefix: Optional[PathType] = None,
                warn_script_location: bool = True,
                use_user_site: bool = False,
                pycompile: bool = True,
            ) -> Any:
                try:
                    if TARGET.TARGET:
                        TARGET.INSTALL = True
                        home = _ensure_target_path()
                    return func(
                        self,
                        root,
                        home,
                        prefix,
                        warn_script_location,
                        use_user_site,
                        pycompile,
                    )
                finally:
                    TARGET.INSTALL = False

            return wrapper

        if argcount == 8:

            @functools.wraps(func)
            def wrapper(
                self: Any,
                global_options: Any = None,
                root: Optional[PathType] = None,
                home: Optional[PathType] = None,
                prefix: Optional[PathType] = None,
                warn_script_location: bool = True,
                use_user_site: bool = False,
                pycompile: bool = True,
            ) -> Any:
                try:
                    if TARGET.TARGET:
                        TARGET.INSTALL = True
                        home = _ensure_target_path()
                    return func(
                        self,
                        global_options,
                        root,
                        home,
                        prefix,
                        warn_script_location,
                        use_user_site,
                        pycompile,
                    )
                finally:
                    TARGET.INSTALL = False

            return wrapper

        if argcount == 9:

            @functools.wraps(func)
            def wrapper(
                self: Any,
                install_options: Any,
                global_options: Any = None,
                root: Optional[PathType] = None,
                home: Optional[PathType] = None,
                prefix: Optional[PathType] = None,
                warn_script_location: bool = True,
                use_user_site: bool = False,
                pycompile: bool = True,
            ) -> Any:
                try:
                    if TARGET.TARGET:
                        TARGET.INSTALL = True
                        home = _ensure_target_path()
                    return func(
                        self,
                        install_options,
                        global_options,
                        root,
                        home,
                        prefix,
                        warn_script_location,
                        use_user_site,
                        pycompile,
                    )
                finally:
                    TARGET.INSTALL = False

            return wrapper

        @functools.wraps(func)
        def wrapper(
            self: Any,
            global_options: Any = None,
            root: Optional[PathType] = None,
            home: Optional[PathType] = None,
            prefix: Optional[PathType] = None,
            warn_script_location: bool = True,
            use_user_site: bool = False,
            pycompile: bool = True,
        ) -> Any:
            try:
                if TARGET.TARGET:
                    TARGET.INSTALL = True
                    home = _ensure_target_path()
                return func(
                    self,
                    global_options,
                    root,
                    home,
                    prefix,
                    warn_script_location,
                    use_user_site,
                    pycompile,
                )
            finally:
                TARGET.INSTALL = False

        return wrapper

    mod.InstallRequirement.install = wrap(mod.InstallRequirement.install)
    return cast(ModuleType, mod)


importer = RelenvImporter(
    wrappers=[
        Wrapper("sysconfig", wrap_sysconfig),
        Wrapper("pip._vendor.distlib.scripts", wrap_pip_distlib_scripts),
        Wrapper("distutils.command.build_ext", wrap_distutils_command),
        Wrapper("pip._internal.operations.install.wheel", wrap_pip_install_wheel),
        Wrapper("pip._internal.operations.install.legacy", wrap_pip_install_legacy),
        Wrapper("pip._internal.operations.build.wheel", wrap_pip_build_wheel),
        Wrapper("pip._internal.commands.install", wrap_cmd_install),
        Wrapper("pip._internal.locations", wrap_locations),
        Wrapper("pip._internal.cli.req_command", wrap_req_command),
        Wrapper("pip._internal.req.req_install", wrap_req_install),
    ],
)


def install_cargo_config() -> None:
    """
    Setup cargo config.
    """
    if sys.platform != "linux":
        return

    # We need this as a late import for python < 3.12 becuase importing it will
    # load the ssl module. Causing out setup_openssl method to fail to load
    # fips module.
    dirs = common().work_dirs()
    cargo_home = dirs.data / "cargo"
    triplet = common().get_triplet()

    toolchain = common().get_toolchain()
    if not toolchain:
        debug("Unable to set CARGO_HOME ppbt package not installed")
        return

    if not toolchain.exists():
        debug("Unable to set CARGO_HOME no toolchain exists")
        return

    # cargo_home = dirs.data / "cargo"
    cargo_home.mkdir(parents=True, exist_ok=True)
    cargo_config = cargo_home / "config.toml"
    if triplet == "x86_64-linux-gnu":
        cargo_triplet = "x86_64-unknown-linux-gnu"
    else:
        cargo_triplet = "aarch64-unknown-linux-gnu"
    gcc = toolchain / "bin" / f"{triplet}-gcc"

    def existing_linker() -> str | None:
        if not cargo_config.exists():
            return None
        try:
            contents = cargo_config.read_text()
        except OSError:
            return None
        marker = f"[target.{cargo_triplet}]"
        if marker not in contents:
            return None
        for line in contents.splitlines():
            stripped = line.strip()
            if stripped.startswith("linker"):
                _, _, value = stripped.partition("=")
                value = value.strip().strip('"')
                if value:
                    return value
        return None

    if existing_linker() != str(gcc):
        cargo_config.write_text(
            textwrap.dedent(
                """\
            [target.{triplet}]
            linker = "{linker}"
            """
            ).format(triplet=cargo_triplet, linker=gcc)
        )


def setup_openssl() -> None:
    """
    Configure openssl certificate locations.
    """
    if sys.platform == "win32":
        return

    openssl_bin = shutil.which("openssl")
    if not openssl_bin:
        debug("Could not find the 'openssl' binary in the path")
        set_openssl_modules_dir(str(sys.RELENV / "lib" / "ossl-modules"))

        if load_openssl_provider("default") == 0:
            debug("Unable to load the default openssl provider")
        if load_openssl_provider("legacy") == 0:
            debug("Unable to load the legacy openssl provider")

        return

    if "OPENSSL_MODULES" not in os.environ:
        # First try and load the system's fips provider. Then load relenv's
        # legacy and default providers. The fips provider must be loaded first
        # in order OpenSSl to work properly..

        # Try and determine the system's openssl modules directory. This is so
        # we can use the system installed fips provider if it configured.
        proc = subprocess.run(
            [openssl_bin, "version", "-m"],
            universal_newlines=True,
            shell=False,
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            msg = "Unable to get the modules directory from openssl"
            if proc.stderr:
                msg += f": {proc.stderr}"
            debug(msg)
        else:
            try:
                _, directory = proc.stdout.split(":", 1)
            except ValueError:
                debug("Unable to parse modules dir")
                return
            path = directory.strip().strip('"')
            set_openssl_modules_dir(path)
            if load_openssl_provider("fips") == 0:
                debug("Unable to load the fips openssl provider")

        set_openssl_modules_dir(str(sys.RELENV / "lib" / "ossl-modules"))

        if load_openssl_provider("default") == 0:
            debug("Unable to load the default openssl provider")
        if load_openssl_provider("legacy") == 0:
            debug("Unable to load the legacy openssl provider")

    # Use system openssl dirs
    # XXX Should we also setup SSL_CERT_FILE, OPENSSL_CONF &
    # OPENSSL_CONF_INCLUDE?
    if "SSL_CERT_DIR" not in os.environ:
        proc = subprocess.run(
            [openssl_bin, "version", "-d"],
            universal_newlines=True,
            shell=False,
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0:
            msg = "Unable to get the certificates directory from openssl"
            if proc.stderr:
                msg += f": {proc.stderr}"
            debug(msg)
        else:
            try:
                _, directory = proc.stdout.split(":", 1)
            except ValueError:
                debug("Unable to parse openssldir")
                return
            path = pathlib.Path(directory.strip().strip('"'))
            if not os.environ.get("SSL_CERT_DIR"):
                os.environ["SSL_CERT_DIR"] = str(path / "certs")
            cert_file = path / "cert.pem"
            if cert_file.exists() and not os.environ.get("SSL_CERT_FILE"):
                os.environ["SSL_CERT_FILE"] = str(cert_file)


def set_openssl_modules_dir(path: str) -> None:
    """
    Set the default search location for openssl modules.
    """
    if sys.platform == "darwin":
        cryptopath = str(sys.RELENV / "lib" / "libcrypto.dylib")
    else:
        cryptopath = str(sys.RELENV / "lib" / "libcrypto.so")
    libcrypto = ctypes.CDLL(cryptopath)
    POSSL_LIB_CTX = ctypes.c_void_p
    OSSL_PROVIDER_set_default_search_path = (
        libcrypto.OSSL_PROVIDER_set_default_search_path
    )
    OSSL_PROVIDER_set_default_search_path.argtypes = (POSSL_LIB_CTX, ctypes.c_char_p)
    OSSL_PROVIDER_set_default_search_path.restype = ctypes.c_int
    OSSL_PROVIDER_set_default_search_path(None, path.encode())


def load_openssl_provider(name: str) -> int:
    """
    Load an openssl module.
    """
    if sys.platform == "darwin":
        cryptopath = str(sys.RELENV / "lib" / "libcrypto.dylib")
    else:
        cryptopath = str(sys.RELENV / "lib" / "libcrypto.so")
    libcrypto = ctypes.CDLL(cryptopath)
    POSSL_LIB_CTX = ctypes.c_void_p
    OSSL_PROVIDER_load = libcrypto.OSSL_PROVIDER_load
    OSSL_PROVIDER_load.argtypes = (POSSL_LIB_CTX, ctypes.c_char_p)
    OSSL_PROVIDER_load.restype = ctypes.c_int
    return OSSL_PROVIDER_load(None, name.encode())


def setup_crossroot() -> None:
    """
    Setup cross root if needed.
    """
    cross = os.environ.get("RELENV_CROSS", "")
    if cross:
        crossroot = pathlib.Path(cross).resolve()
        sys.prefix = str(crossroot)
        sys.exec_prefix = str(crossroot)
        # XXX What about dist-packages
        pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        sys.path = [
            str(crossroot / "lib" / pyver),
            str(crossroot / "lib" / pyver / "lib-dynload"),
            str(crossroot / "lib" / pyver / "site-packages"),
        ] + [_ for _ in sys.path if "site-packages" not in _]


def wrapsitecustomize(func: Callable[[], Any]) -> Callable[[], None]:
    """
    Wrap site.execsitecustomize.

    This allows relenv a hook to be the last thing that runs when pythong is
    setting itself up.
    """

    @functools.wraps(func)
    def wrapper() -> None:
        func()

        sitecustomize = None
        try:
            import sitecustomize
        except ImportError as exc:
            if exc.name != "sitecustomize":
                raise

        # Attempt to make sure we're not pulling in packages outside of the
        # relenv environment. This can't be done when pip is using build_env to
        # install packages. This code seems potentially brittle and there may
        # be reasonable arguments against doing it at all.
        if sitecustomize is None or "pip-build-env" not in sitecustomize.__file__:
            _orig = sys.path[:]
            # Replace sys.path
            sys.path[:] = common().sanitize_sys_path(sys.path)
            debug(f"original sys.path was {_orig}")
            debug(f"new sys.path is {sys.path}")
        else:
            debug("Skip path munging")

        site.ENABLE_USER_SITE = False
        debug("After site customize wrapper")

    return wrapper


def bootstrap() -> None:
    """
    Bootstrap the relenv environment.
    """
    warnings.filterwarnings(
        "ignore",
        message=".*falling back to find_module.*",
        category=ImportWarning,
        module="importlib._bootstrap",
        lineno=914,
    )
    sys.RELENV = relenv_root()
    setup_openssl()
    site.execsitecustomize = wrapsitecustomize(site.execsitecustomize)
    setup_crossroot()
    install_cargo_config()
    sys.meta_path = [importer] + sys.meta_path
