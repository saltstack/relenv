# Copyright 2023-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
#
from __future__ import annotations

import importlib
import json
import os
import pathlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest

import relenv.runtime

# mypy: ignore-errors


def _raise(exc: Exception):
    raise exc


def test_path_import_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setattr(
        importlib.util, "spec_from_file_location", lambda *args, **kwargs: None
    )
    with pytest.raises(ImportError):
        relenv.runtime.path_import("demo", tmp_path / "demo.py")


def test_path_import_success(tmp_path: pathlib.Path) -> None:
    module_file = tmp_path / "mod.py"
    module_file.write_text("value = 42\n")
    mod = relenv.runtime.path_import("temp_mod", module_file)
    assert mod.value == 42
    assert sys.modules["temp_mod"] is mod


def test_debug_print(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RELENV_DEBUG", "1")
    relenv.runtime.debug("hello")
    out = capsys.readouterr().out
    assert "hello" in out
    monkeypatch.delenv("RELENV_DEBUG", raising=False)


def test_pushd_changes_directory(tmp_path: pathlib.Path) -> None:
    original = os.getcwd()
    with relenv.runtime.pushd(tmp_path):
        assert os.getcwd() == str(tmp_path)
    assert os.getcwd() == original


def test_relenv_root_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    module_dir = pathlib.Path(relenv.runtime.__file__).resolve().parent
    fake_sys = SimpleNamespace(platform="win32")
    monkeypatch.setattr(relenv.runtime, "sys", fake_sys)
    expected = module_dir.parent.parent.parent
    assert relenv.runtime.relenv_root() == expected


def test_get_major_version() -> None:
    result = relenv.runtime.get_major_version()
    major, minor = result.split(".")
    assert major.isdigit() and minor.isdigit()


def test_importer() -> None:
    def mywrapper(name: str) -> ModuleType:
        mod = importlib.import_module(name)
        mod.__test_case__ = True  # type: ignore[attr-defined]
        return mod

    importer = relenv.runtime.RelenvImporter(
        wrappers=[
            relenv.runtime.Wrapper(
                "pip._internal.locations",
                mywrapper,
            ),
        ]
    )

    sys.meta_path = [importer] + sys.meta_path

    import pip._internal.locations  # type: ignore[import]

    assert hasattr(pip._internal.locations, "__test_case__")
    assert pip._internal.locations.__test_case__ is True


def test_set_env_if_not_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env_name = "RELENV_TEST_ENV"
    monkeypatch.delenv(env_name, raising=False)
    relenv.runtime.set_env_if_not_set(env_name, "value")
    assert os.environ[env_name] == "value"

    monkeypatch.setenv(env_name, "other")
    relenv.runtime.set_env_if_not_set(env_name, "value")
    captured = capsys.readouterr()
    assert "Warning:" in captured.out


def test_get_config_var_wrapper_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime, "relenv_root", lambda: pathlib.Path("/root"))
    monkeypatch.setenv("RELENV_PIP_DIR", "1")
    wrapped = relenv.runtime.get_config_var_wrapper(lambda name: "/orig")
    assert wrapped("BINDIR") == pathlib.Path("/root")
    monkeypatch.delenv("RELENV_PIP_DIR", raising=False)


def test_system_sysconfig_uses_system_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime, "_SYSTEM_CONFIG_VARS", None, raising=False)

    original_exists = pathlib.Path.exists

    def fake_exists(path: pathlib.Path) -> bool:
        return str(path) == "/usr/bin/python3"

    monkeypatch.setattr(pathlib.Path, "exists", fake_exists)
    expected = {"AR": "ar"}
    completed = SimpleNamespace(stdout=json.dumps(expected).encode(), returncode=0)
    monkeypatch.setattr(
        relenv.runtime.subprocess, "run", lambda *args, **kwargs: completed
    )

    result = relenv.runtime.system_sysconfig()
    assert result["AR"] == "ar"

    monkeypatch.setattr(pathlib.Path, "exists", original_exists)


def test_system_sysconfig_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = {"AR": "cached"}
    monkeypatch.setattr(relenv.runtime, "_SYSTEM_CONFIG_VARS", cache, raising=False)
    result = relenv.runtime.system_sysconfig()
    assert result is cache
    monkeypatch.setattr(relenv.runtime, "_SYSTEM_CONFIG_VARS", None, raising=False)


def test_system_sysconfig_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime, "_SYSTEM_CONFIG_VARS", None, raising=False)
    monkeypatch.setattr(pathlib.Path, "exists", lambda _path: False)
    result = relenv.runtime.system_sysconfig()
    assert result == relenv.runtime.CONFIG_VARS_DEFAULTS


def test_install_cargo_config_creates_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    toolchain_dir = tmp_path / "toolchain" / "x86_64-linux-gnu"
    (toolchain_dir / "sysroot" / "lib").mkdir(parents=True)
    (toolchain_dir / "bin").mkdir(parents=True)
    (toolchain_dir / "bin" / "x86_64-linux-gnu-gcc").touch()

    class StubDirs:
        def __init__(self, data: pathlib.Path) -> None:
            self.data = data

    stub_dirs = StubDirs(data_dir)
    stub_common = SimpleNamespace(
        DATA_DIR=tmp_path,
        work_dirs=lambda: stub_dirs,
        get_triplet=lambda: "x86_64-linux-gnu",
        get_toolchain=lambda: toolchain_dir,
    )

    monkeypatch.setattr(relenv.runtime, "common", lambda: stub_common)
    relenv.runtime.install_cargo_config()
    config_path = data_dir / "cargo" / "config.toml"
    assert config_path.exists()
    assert "x86_64-unknown-linux-gnu" in config_path.read_text()


def test_build_shebang_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(
        relenv.runtime,
        "common",
        lambda: SimpleNamespace(
            relative_interpreter=lambda *args, **kwargs: _raise(ValueError("boom"))
        ),
    )

    called = {"count": 0}

    def original(self: object, *args: object, **kwargs: object) -> bytes:  # type: ignore[override]
        called["count"] += 1
        return b"orig"

    wrapped = relenv.runtime._build_shebang(original)
    result = wrapped(SimpleNamespace(target_dir="/tmp/dir"))
    assert result == b"orig"
    assert called["count"] == 1


def test_build_shebang_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(
        relenv.runtime,
        "common",
        lambda: SimpleNamespace(
            relative_interpreter=lambda *args: pathlib.Path("python.exe")
        ),
    )

    def original(self: object) -> bytes:  # type: ignore[override]
        return b""

    wrapped = relenv.runtime._build_shebang(original)
    result = wrapped(SimpleNamespace(target_dir="/tmp/dir"))
    assert result.startswith(b"#!") and result.endswith(b"\r\n")


def test_get_config_var_wrapper_bindir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime, "relenv_root", lambda: pathlib.Path("/root"))
    wrapped = relenv.runtime.get_config_var_wrapper(lambda name: "/orig")
    result = wrapped("BINDIR")
    assert result == pathlib.Path("/root/Scripts")


def test_get_config_var_wrapper_other(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(relenv.runtime, "relenv_root", lambda: pathlib.Path("/root"))
    result = relenv.runtime.get_config_var_wrapper(lambda name: "value")("OTHER")
    assert result == "value"


def test_system_sysconfig_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime, "_SYSTEM_CONFIG_VARS", None, raising=False)
    monkeypatch.setattr(
        pathlib.Path, "exists", lambda self: str(self) == "/usr/bin/python3"
    )
    monkeypatch.setattr(
        relenv.runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"invalid", returncode=0),
    )

    def fake_loads(_data: bytes) -> dict:
        raise json.JSONDecodeError("msg", "doc", 0)

    monkeypatch.setattr(relenv.runtime.json, "loads", fake_loads)
    result = relenv.runtime.system_sysconfig()
    assert result == relenv.runtime.CONFIG_VARS_DEFAULTS


def test_get_paths_wrapper_updates_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    def original_get_paths(
        *, scheme: Optional[str], vars: Optional[dict[str, str]], expand: bool
    ) -> dict[str, str]:
        return {"scripts": "/original/scripts"}

    wrapped = relenv.runtime.get_paths_wrapper(original_get_paths, "default")
    monkeypatch.setenv("RELENV_PIP_DIR", "/tmp/scripts")
    monkeypatch.setattr(relenv.runtime, "relenv_root", lambda: pathlib.Path("/relroot"))

    result = wrapped()
    expected_root = os.fspath(pathlib.Path("/relroot"))
    assert result["scripts"] == expected_root
    assert relenv.runtime.sys.exec_prefix == expected_root

    monkeypatch.delenv("RELENV_PIP_DIR", raising=False)


def test_get_config_vars_wrapper_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("sysconfig")
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)

    def original() -> dict[str, str]:
        return {
            key: "orig"
            for key in (
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
            )
        }

    monkeypatch.setattr(
        relenv.runtime,
        "system_sysconfig",
        lambda: {
            key: "sys"
            for key in (
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
            )
        },
    )
    wrapped = relenv.runtime.get_config_vars_wrapper(original, module)
    result = wrapped()
    assert module._CONFIG_VARS["AR"] == "sys"
    assert result == {
        key: "orig"
        for key in (
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
        )
    }


def test_get_config_vars_wrapper_buildenv_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("sysconfig")
    monkeypatch.setenv("RELENV_BUILDENV", "1")
    marker = object()
    wrapped = relenv.runtime.get_config_vars_wrapper(lambda: marker, module)
    assert wrapped() is marker
    monkeypatch.delenv("RELENV_BUILDENV", raising=False)


def test_finalize_options_wrapper_appends_include(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Dummy:
        def __init__(self) -> None:
            self.include_dirs: list[str] = []

    def original(self: Dummy, *args: object, **kwargs: object) -> None:
        self.include_dirs.append("existing")

    wrapped = relenv.runtime.finalize_options_wrapper(original)
    dummy = Dummy()
    monkeypatch.setenv("RELENV_BUILDENV", "1")
    monkeypatch.setattr(relenv.runtime, "relenv_root", lambda: pathlib.Path("/relroot"))
    wrapped(dummy)
    expected_include = os.fspath(pathlib.Path("/relroot") / "include")
    assert dummy.include_dirs == ["existing", expected_include]
    monkeypatch.delenv("RELENV_BUILDENV", raising=False)


def test_install_wheel_wrapper_processes_record(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat_dir = tmp_path / "plat"
    info_dir = plat_dir / "demo.dist-info"
    info_dir.mkdir(parents=True)
    record = info_dir / "RECORD"
    record.write_text("libdemo.so,,\n")
    binary = plat_dir / "libdemo.so"
    binary.touch()

    handled: list[tuple[pathlib.Path, pathlib.Path]] = []
    monkeypatch.setattr(
        relenv.runtime,
        "relocate",
        lambda: SimpleNamespace(
            is_elf=lambda path: path.name.endswith(".so"),
            is_macho=lambda path: False,
            handle_elf=lambda file, lib_dir, fix, root: handled.append((file, lib_dir)),
            handle_macho=lambda *args, **kwargs: None,
        ),
    )

    wheel_utils = ModuleType("pip._internal.utils.wheel")
    wheel_utils.parse_wheel = lambda _zf, _name: ("demo.dist-info", {})
    monkeypatch.setitem(sys.modules, wheel_utils.__name__, wheel_utils)

    class DummyZip:
        def __init__(self, path: pathlib.Path) -> None:
            self.path = path

        def __enter__(self) -> DummyZip:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr("zipfile.ZipFile", DummyZip)

    install_module = ModuleType("pip._internal.operations.install.wheel")

    def original_install(*_args: object, **_kwargs: object) -> str:
        return "original"

    install_module.install_wheel = original_install  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, install_module.__name__, install_module)

    wrapped_module = relenv.runtime.wrap_pip_install_wheel(install_module.__name__)

    scheme = SimpleNamespace(
        platlib=str(plat_dir),
    )
    wrapped_module.install_wheel(
        "demo",
        tmp_path / "wheel.whl",
        scheme,
        "desc",
        None,
        None,
        None,
        None,
    )

    assert handled and handled[0][0].name == "libdemo.so"


def test_install_wheel_wrapper_missing_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat_dir = tmp_path / "plat"
    info_dir = plat_dir / "demo.dist-info"
    info_dir.mkdir(parents=True)
    (info_dir / "RECORD").write_text("missing.so,,\n")
    (info_dir / "WHEEL").write_text("Wheel-Version: 1.0\n")
    import zipfile

    wheel_path = tmp_path / "demo_missing.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("demo.dist-info/RECORD", "missing.so,,\n")
        zf.writestr("demo.dist-info/WHEEL", "Wheel-Version: 1.0\n")

    monkeypatch.setattr(
        relenv.runtime,
        "relocate",
        lambda: SimpleNamespace(is_elf=lambda path: False, is_macho=lambda path: False),
    )
    module_utils = ModuleType("pip._internal.utils.wheel.missing")
    module_utils.parse_wheel = lambda zf, name: ("demo.dist-info", {})
    wheel_module = ModuleType("pip._internal.operations.install.wheel.missing")
    wheel_module.install_wheel = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_utils.__name__, module_utils)
    monkeypatch.setitem(sys.modules, wheel_module.__name__, wheel_module)
    monkeypatch.setattr(
        relenv.runtime.importlib,
        "import_module",
        lambda name: wheel_module if name == wheel_module.__name__ else module_utils,
    )
    scheme = SimpleNamespace(platlib=str(plat_dir))
    relenv.runtime.wrap_pip_install_wheel(wheel_module.__name__).install_wheel(
        "demo", wheel_path, scheme, "desc", None, None, None, None
    )


def test_install_wheel_wrapper_macho_with_otool(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat_dir = tmp_path / "plat"
    info_dir = plat_dir / "demo.dist-info"
    info_dir.mkdir(parents=True)
    (plat_dir / "libmach.dylib").touch()
    (info_dir / "RECORD").write_text("libmach.dylib,,\n")
    (info_dir / "WHEEL").write_text("Wheel-Version: 1.0\n")
    import zipfile

    wheel_path = tmp_path / "demo_otool.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("demo.dist-info/RECORD", "libmach.dylib,,\n")
        zf.writestr("demo.dist-info/WHEEL", "Wheel-Version: 1.0\n")

    monkeypatch.setattr(
        relenv.runtime,
        "relocate",
        lambda: SimpleNamespace(
            is_elf=lambda path: False,
            is_macho=lambda path: True,
            handle_macho=lambda *args, **kwargs: None,
        ),
    )
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda cmd: "/usr/bin/otool")
    module_utils = ModuleType("pip._internal.utils.wheel.otool")
    module_utils.parse_wheel = lambda zf, name: ("demo.dist-info", {})
    wheel_module = ModuleType("pip._internal.operations.install.wheel.otool")
    wheel_module.install_wheel = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_utils.__name__, module_utils)
    monkeypatch.setitem(sys.modules, wheel_module.__name__, wheel_module)
    monkeypatch.setattr(
        relenv.runtime.importlib,
        "import_module",
        lambda name: wheel_module if name == wheel_module.__name__ else module_utils,
    )
    scheme = SimpleNamespace(platlib=str(plat_dir))
    relenv.runtime.wrap_pip_install_wheel(wheel_module.__name__).install_wheel(
        "demo", wheel_path, scheme, "desc", None, None, None, None
    )


def test_install_wheel_wrapper_macho_without_otool(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat_dir = tmp_path / "plat"
    info_dir = plat_dir / "demo.dist-info"
    info_dir.mkdir(parents=True)
    (plat_dir / "libmach.dylib").touch()
    (info_dir / "RECORD").write_text("libmach.dylib,,\n")
    (info_dir / "WHEEL").write_text("Wheel-Version: 1.0\n")
    import zipfile

    wheel_path = tmp_path / "demo_no_otool.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("demo.dist-info/RECORD", "libmach.dylib,,\n")
        zf.writestr("demo.dist-info/WHEEL", "Wheel-Version: 1.0\n")

    monkeypatch.setattr(
        relenv.runtime,
        "relocate",
        lambda: SimpleNamespace(
            is_elf=lambda path: False,
            is_macho=lambda path: True,
            handle_macho=lambda *args, **kwargs: _raise(
                AssertionError("unexpected macho")
            ),
        ),
    )
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda cmd: None)
    messages: list[str] = []
    monkeypatch.setattr(relenv.runtime, "debug", lambda msg: messages.append(str(msg)))
    module_utils = ModuleType("pip._internal.utils.wheel.no_otool")
    module_utils.parse_wheel = lambda zf, name: ("demo.dist-info", {})
    wheel_module = ModuleType("pip._internal.operations.install.wheel.no_otool")
    wheel_module.install_wheel = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_utils.__name__, module_utils)
    monkeypatch.setitem(sys.modules, wheel_module.__name__, wheel_module)
    monkeypatch.setattr(
        relenv.runtime.importlib,
        "import_module",
        lambda name: wheel_module if name == wheel_module.__name__ else module_utils,
    )
    scheme = SimpleNamespace(platlib=str(plat_dir))
    relenv.runtime.wrap_pip_install_wheel(wheel_module.__name__).install_wheel(
        "demo", wheel_path, scheme, "desc", None, None, None, None
    )
    assert any("otool command is not available" in msg for msg in messages)


def test_install_legacy_wrapper_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "PKG-INFO").write_text("Version: 1.0\nName: demo\n")
    sitepack = (
        tmp_path
        / "prefix"
        / "lib"
        / f"python{relenv.runtime.get_major_version()}"
        / "site-packages"
    )
    egg_dir = sitepack / "demo-1.0.egg-info"
    egg_dir.mkdir(parents=True)
    (egg_dir / "installed-files.txt").write_text("missing.so\n")
    scheme = SimpleNamespace(
        purelib=str(tmp_path / "pure"), platlib=str(tmp_path / "pure")
    )
    module = ModuleType("pip._internal.operations.install.legacy.prefix")
    module.install = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(
        relenv.runtime,
        "relocate",
        lambda: SimpleNamespace(is_elf=lambda path: False, is_macho=lambda path: False),
    )
    wrapper = relenv.runtime.wrap_pip_install_legacy(module.__name__)
    wrapper.install(
        None,
        None,
        str(sitepack.parent.parent.parent),
        None,
        str(sitepack.parent.parent.parent),
        False,
        False,
        scheme,
        str(pkg_dir / "setup.py"),
        False,
        "demo",
        None,
        pkg_dir,
        "demo",
    )


def test_install_legacy_wrapper_no_egginfo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "PKG-INFO").write_text("Name: demo\nVersion: 1.0\n")
    scheme = SimpleNamespace(purelib=str(tmp_path / "pure"))
    module = ModuleType("pip._internal.operations.install.legacy.none")
    module.install = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)
    wrapper = relenv.runtime.wrap_pip_install_legacy(module.__name__)
    wrapper.install(
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        scheme,
        str(pkg_dir / "setup.py"),
        False,
        "demo",
        None,
        pkg_dir,
        "demo",
    )


def test_install_legacy_wrapper_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "PKG-INFO").write_text("Name: demo\nVersion: 1.0\n")
    egg_dir = tmp_path / "pure" / "demo-1.0.egg-info"
    egg_dir.mkdir(parents=True)
    (egg_dir / "installed-files.txt").write_text("missing.so\n")
    scheme = SimpleNamespace(
        purelib=str(tmp_path / "pure"), platlib=str(tmp_path / "pure")
    )
    module = ModuleType("pip._internal.operations.install.legacy.missing")
    module.install = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(
        relenv.runtime,
        "relocate",
        lambda: SimpleNamespace(is_elf=lambda path: False, is_macho=lambda path: False),
    )
    wrapper = relenv.runtime.wrap_pip_install_legacy(module.__name__)
    wrapper.install(
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        scheme,
        str(pkg_dir / "setup.py"),
        False,
        "demo",
        None,
        pkg_dir,
        "demo",
    )


def test_install_legacy_wrapper_handles_elf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "PKG-INFO").write_text("Name: demo\nVersion: 1.0\n")
    egg_dir = tmp_path / "pure" / "demo-1.0.egg-info"
    egg_dir.mkdir(parents=True)
    binary = tmp_path / "pure" / "libdemo.so"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"")
    (egg_dir / "installed-files.txt").write_text(f"{binary}\n")
    scheme = SimpleNamespace(
        purelib=str(tmp_path / "pure"), platlib=str(tmp_path / "pure")
    )
    module = ModuleType("pip._internal.operations.install.legacy.elf")
    module.install = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)
    handled: list[tuple[pathlib.Path, pathlib.Path, bool, pathlib.Path]] = []

    def fake_relocate() -> SimpleNamespace:
        return SimpleNamespace(
            is_elf=lambda path: path == binary,
            is_macho=lambda path: False,
            handle_elf=lambda *args: handled.append(args),
        )

    monkeypatch.setattr(relenv.runtime, "relocate", fake_relocate)
    monkeypatch.setattr(relenv.runtime, "relenv_root", lambda: tmp_path)
    wrapper = relenv.runtime.wrap_pip_install_legacy(module.__name__)
    wrapper.install(
        None,
        None,
        None,
        None,
        None,
        False,
        False,
        scheme,
        str(pkg_dir / "setup.py"),
        False,
        "demo",
        None,
        pkg_dir,
        "demo",
    )
    assert handled and handled[0][0] == binary


def test_wrap_sysconfig_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("sysconfig")

    def get_config_var(name: str) -> str:
        return name

    def get_config_vars() -> dict[str, str]:
        return relenv.runtime.CONFIG_VARS_DEFAULTS.copy()

    def get_paths(**kwargs: object) -> dict[str, str]:
        return {"scripts": "/tmp"}

    def default_scheme() -> str:
        return "legacy"

    module.get_config_var = get_config_var
    module.get_config_vars = get_config_vars
    module.get_paths = get_paths
    module._get_default_scheme = default_scheme  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sysconfig.legacy", module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)
    wrapped = relenv.runtime.wrap_sysconfig("sysconfig.legacy")
    assert wrapped is module


def test_wrap_pip_distlib_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    class ScriptMaker:
        def __init__(self) -> None:
            self.target_dir = "/tmp/dir"

        def _build_shebang(self, target: str) -> bytes:
            return b"orig"

    module = ModuleType("pip._vendor.distlib.scripts")
    module.ScriptMaker = ScriptMaker
    monkeypatch.setitem(sys.modules, module.__name__, module)
    wrapped = relenv.runtime.wrap_pip_distlib_scripts(module.__name__)
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(
        relenv.runtime,
        "common",
        lambda: SimpleNamespace(
            relative_interpreter=lambda *args, **kwargs: _raise(ValueError("boom"))
        ),
    )
    result = wrapped.ScriptMaker()._build_shebang("target")
    assert result == b"orig"


def test_wrap_distutils_command(monkeypatch: pytest.MonkeyPatch) -> None:
    class BuildExt:
        def finalize_options(self) -> None:
            return None

    module = ModuleType("distutils.command.build_ext")
    module.build_ext = BuildExt
    monkeypatch.setitem(sys.modules, module.__name__, module)
    wrapped = relenv.runtime.wrap_distutils_command(module.__name__)
    dummy = wrapped.build_ext()
    monkeypatch.setenv("RELENV_BUILDENV", "1")
    monkeypatch.setattr(relenv.runtime, "relenv_root", lambda: pathlib.Path("/rel"))
    dummy.include_dirs = []
    wrapped.build_ext.finalize_options(dummy)
    expected_include = os.fspath(pathlib.Path("/rel") / "include")
    assert expected_include in dummy.include_dirs
    monkeypatch.delenv("RELENV_BUILDENV", raising=False)


def test_wrap_pip_build_wheel_sets_env(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relenv.runtime.TARGET.TARGET = False
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    toolchain = tmp_path / "toolchain" / "trip"
    (toolchain / "sysroot" / "lib").mkdir(parents=True)
    toolchain.mkdir(parents=True, exist_ok=True)
    base_dir = tmp_path
    set_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        relenv.runtime,
        "set_env_if_not_set",
        lambda name, value: set_calls.append((name, value)),
    )
    stub_common = SimpleNamespace(
        DATA_DIR=base_dir,
        get_triplet=lambda: "trip",
        get_toolchain=lambda: toolchain,
    )
    monkeypatch.setattr(relenv.runtime, "common", lambda: stub_common)

    class DummyModule(ModuleType):
        def build_wheel_pep517(self, *args: object, **kwargs: object) -> str:  # type: ignore[override]
            return "built"

    module_name = "pip._internal.operations.build.wheel"
    dummy = DummyModule(module_name)
    monkeypatch.setitem(sys.modules, module_name, dummy)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: dummy)

    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    wrapped = relenv.runtime.wrap_pip_build_wheel(module_name)
    result = wrapped.build_wheel_pep517("backend", {}, {})
    assert result == "built"
    assert any(name == "CARGO_HOME" for name, _ in set_calls)


def test_wrap_pip_build_wheel_toolchain_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relenv.runtime.TARGET.TARGET = False
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    stub_common = SimpleNamespace(
        DATA_DIR=pathlib.Path("/data"),
        get_triplet=lambda: "trip",
        get_toolchain=lambda: None,
    )
    monkeypatch.setattr(relenv.runtime, "common", lambda: stub_common)
    module_name = "pip._internal.operations.build.none"
    module = ModuleType(module_name)
    module.build_wheel_pep517 = lambda *args, **kwargs: "built"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)

    wrapped = relenv.runtime.wrap_pip_build_wheel(module_name)
    assert wrapped.build_wheel_pep517("backend", {}, {}) == "built"


def test_wrap_pip_build_wheel_non_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "darwin", raising=False)
    module_name = "pip._internal.operations.build.nonlinux"
    module = ModuleType(module_name)
    module.build_wheel_pep517 = lambda *args, **kwargs: "built"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)
    wrapped = relenv.runtime.wrap_pip_build_wheel(module_name)
    assert wrapped.build_wheel_pep517("backend", {}, {}) == "built"


def test_wrap_cmd_install_updates_target(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = False
    relenv.runtime.TARGET.PATH = None
    relenv.runtime.TARGET.IGNORE = False

    fake_module = ModuleType("pip._internal.commands.install")

    class FakeInstallCommand:
        def run(self, options: SimpleNamespace, args: list[str]) -> str:
            options.ran = True
            return "ran"

        def _handle_target_dir(
            self, target_dir: str, target_temp_dir: str, upgrade: bool
        ) -> str:
            return "handled"

    fake_module.InstallCommand = FakeInstallCommand
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)

    status_module = ModuleType("pip._internal.cli.status_codes")
    status_module.SUCCESS = 0
    monkeypatch.setitem(sys.modules, status_module.__name__, status_module)

    original_import = relenv.runtime.importlib.import_module

    def fake_import_module(name: str) -> ModuleType:
        if name == fake_module.__name__:
            return fake_module
        return original_import(name)

    monkeypatch.setattr(relenv.runtime.importlib, "import_module", fake_import_module)

    wrapped = relenv.runtime.wrap_cmd_install(fake_module.__name__)
    options = SimpleNamespace(
        use_user_site=False, target_dir="/tmp/target", ignore_installed=True
    )
    command = wrapped.InstallCommand()
    result = command.run(options, [])

    assert result == "ran"
    assert relenv.runtime.TARGET.TARGET is True
    assert relenv.runtime.TARGET.PATH == "/tmp/target"
    assert relenv.runtime.TARGET.IGNORE is True
    assert command._handle_target_dir("a", "b", True) == 0


def test_wrap_cmd_install_no_user_site(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = False
    fake_module = ModuleType("pip._internal.commands.install.skip")

    class InstallCommand:
        def run(self, options: SimpleNamespace, args: list[str]) -> str:
            return "ran"

    fake_module.InstallCommand = InstallCommand
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)

    module_status = ModuleType("pip._internal.cli.status_codes")
    module_status.SUCCESS = 0
    monkeypatch.setitem(sys.modules, module_status.__name__, module_status)

    monkeypatch.setattr(
        relenv.runtime.importlib,
        "import_module",
        lambda name: fake_module if name == fake_module.__name__ else module_status,
    )

    wrapped = relenv.runtime.wrap_cmd_install(fake_module.__name__)
    options = SimpleNamespace(
        use_user_site=True, target_dir=None, ignore_installed=False
    )
    result = wrapped.InstallCommand().run(options, [])
    assert result == "ran"
    assert relenv.runtime.TARGET.TARGET is False


def test_wrap_locations_applies_target(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = True
    relenv.runtime.TARGET.INSTALL = True
    relenv.runtime.TARGET.PATH = "/target/path"

    scheme_module = ModuleType("pip._internal.models.scheme")

    class Scheme:
        def __init__(
            self,
            platlib: str,
            purelib: str,
            headers: str,
            scripts: str,
            data: str,
        ) -> None:
            self.platlib = platlib
            self.purelib = purelib
            self.headers = headers
            self.scripts = scripts
            self.data = data

    scheme_module.Scheme = Scheme
    monkeypatch.setitem(sys.modules, scheme_module.__name__, scheme_module)

    fake_locations = ModuleType("pip._internal.locations")

    class OriginalScheme:
        platlib = "/original/plat"
        purelib = "/original/pure"
        headers = "headers"
        scripts = "scripts"
        data = "data"

    def get_scheme(
        dist_name: str,
        user: bool = False,
        home: str | None = None,
        root: str | None = None,
        isolated: bool = False,
        prefix: str | None = None,
    ) -> OriginalScheme:
        return OriginalScheme()

    fake_locations.get_scheme = get_scheme  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, fake_locations.__name__, fake_locations)

    original_import = relenv.runtime.importlib.import_module

    def fake_import_module(name: str) -> ModuleType:
        if name == fake_locations.__name__:
            return fake_locations
        if name == scheme_module.__name__:
            return scheme_module
        return original_import(name)

    monkeypatch.setattr(relenv.runtime.importlib, "import_module", fake_import_module)

    wrapped = relenv.runtime.wrap_locations(fake_locations.__name__)
    scheme = wrapped.get_scheme("dist")
    assert scheme.platlib == "/target/path"
    assert scheme.purelib == "/target/path"
    assert scheme.headers == "headers"
    assert scheme.scripts == "scripts"
    assert scheme.data == "data"


def test_wrap_locations_without_target(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = False
    fake_module = ModuleType("pip._internal.locations.plain")

    class OriginalScheme:
        def __init__(self) -> None:
            self.platlib = "/plat"

    fake_module.get_scheme = lambda *args, **kwargs: OriginalScheme()
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)
    monkeypatch.setattr(
        relenv.runtime.importlib, "import_module", lambda name: fake_module
    )

    wrapped = relenv.runtime.wrap_locations(fake_module.__name__)
    scheme = wrapped.get_scheme("dist")
    assert scheme.platlib == "/plat"


def test_wrap_req_command_honors_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = True
    relenv.runtime.TARGET.IGNORE = True

    fake_module = ModuleType("pip._internal.cli.req_command")

    class RequirementCommand:
        def _build_package_finder(
            self,
            options: SimpleNamespace,
            session: object,
            target_python: object | None = None,
            ignore_requires_python: object | None = None,
        ) -> bool:
            return options.ignore_installed

    fake_module.RequirementCommand = RequirementCommand
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)

    original_import = relenv.runtime.importlib.import_module

    def fake_import_module(name: str) -> ModuleType:
        if name == fake_module.__name__:
            return fake_module
        return original_import(name)

    monkeypatch.setattr(relenv.runtime.importlib, "import_module", fake_import_module)

    wrapped = relenv.runtime.wrap_req_command(fake_module.__name__)
    command = wrapped.RequirementCommand()
    options = SimpleNamespace(ignore_installed=False)
    result = command._build_package_finder(options, object())
    assert options.ignore_installed is True
    assert result is True


def test_wrap_req_command_without_target(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = False
    fake_module = ModuleType("pip._internal.cli.req_command.plain")

    class RequirementCommand:
        def _build_package_finder(
            self,
            options: SimpleNamespace,
            session: object,
            target_python: object | None = None,
            ignore_requires_python: object | None = None,
        ) -> bool:
            return options.ignore_installed

    fake_module.RequirementCommand = RequirementCommand
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)
    monkeypatch.setattr(
        relenv.runtime.importlib, "import_module", lambda name: fake_module
    )

    wrapped = relenv.runtime.wrap_req_command(fake_module.__name__)
    options = SimpleNamespace(ignore_installed=False)
    result = wrapped.RequirementCommand()._build_package_finder(options, object())
    assert result is False


def test_wrap_req_install_sets_target_home(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = True
    relenv.runtime.TARGET.PATH = "/target/path"

    fake_module = ModuleType("pip._internal.req.req_install")

    class InstallRequirement:
        def install(
            self,
            install_options: object,
            global_options: object,
            root: object,
            home: object,
            prefix: object,
            warn_script_location: bool,
            use_user_site: bool,
            pycompile: bool,
        ) -> tuple[object, object]:
            return install_options, home

    fake_module.InstallRequirement = InstallRequirement
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)

    original_import = relenv.runtime.importlib.import_module

    def fake_import_module(name: str) -> ModuleType:
        if name == fake_module.__name__:
            return fake_module
        return original_import(name)

    monkeypatch.setattr(relenv.runtime.importlib, "import_module", fake_import_module)

    wrapped = relenv.runtime.wrap_req_install(fake_module.__name__)
    installer = wrapped.InstallRequirement()
    _, home = installer.install(None, None, None, None, None, True, False, True)
    assert home == relenv.runtime.TARGET.PATH


def test_wrap_req_install_short_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = True
    relenv.runtime.TARGET.PATH = "/another/path"

    module_name = "pip._internal.req.req_install.short"
    short_module = ModuleType(module_name)

    class InstallRequirement:
        def install(
            self,
            global_options: object = None,
            root: object = None,
            home: object = None,
            prefix: object = None,
            warn_script_location: bool = True,
            use_user_site: bool = False,
            pycompile: bool = True,
        ) -> tuple[object, object]:
            return global_options, home

    short_module.InstallRequirement = InstallRequirement
    monkeypatch.setitem(sys.modules, module_name, short_module)

    original_import = relenv.runtime.importlib.import_module

    def fake_import_module(name: str) -> ModuleType:
        if name == module_name:
            return short_module
        return original_import(name)

    monkeypatch.setattr(relenv.runtime.importlib, "import_module", fake_import_module)

    wrapped = relenv.runtime.wrap_req_install(module_name)
    installer = wrapped.InstallRequirement()
    _, home = installer.install()
    assert home == relenv.runtime.TARGET.PATH


def test_wrap_req_install_no_target(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = False
    module_name = "pip._internal.req.req_install.none"
    module = ModuleType(module_name)

    class InstallRequirement:
        def install(
            self,
            install_options: object,
            global_options: object,
            root: object,
            home: object,
            prefix: object,
            warn_script_location: bool,
            use_user_site: bool,
            pycompile: bool,
        ) -> str:
            return "installed"

    module.InstallRequirement = InstallRequirement
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(relenv.runtime.importlib, "import_module", lambda name: module)

    wrapped = relenv.runtime.wrap_req_install(module_name)
    installer = wrapped.InstallRequirement()
    result = installer.install(None, None, None, None, None, True, False, True)
    assert result == "installed"


def test_wrapsitecustomize_sanitizes_sys_path(monkeypatch: pytest.MonkeyPatch) -> None:
    sanitized = ["sanitized/path"]
    monkeypatch.setattr(
        relenv.runtime,
        "common",
        lambda: SimpleNamespace(sanitize_sys_path=lambda _: sanitized),
    )
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )

    def original() -> None:
        pass

    wrapped = relenv.runtime.wrapsitecustomize(original)
    wrapped()
    assert relenv.runtime.site.ENABLE_USER_SITE is False
    assert relenv.runtime.sys.path == sanitized


def test_install_cargo_config_toolchain_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    stub_common = SimpleNamespace(
        DATA_DIR=pathlib.Path("/data"),
        work_dirs=lambda: SimpleNamespace(data=pathlib.Path("/data")),
        get_triplet=lambda: "trip",
        get_toolchain=lambda: None,
    )
    monkeypatch.setattr(relenv.runtime, "common", lambda: stub_common)
    relenv.runtime.install_cargo_config()


def test_install_cargo_config_toolchain_missing_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    toolchain = SimpleNamespace(exists=lambda: False)
    stub_common = SimpleNamespace(
        DATA_DIR=pathlib.Path("/data"),
        work_dirs=lambda: SimpleNamespace(data=pathlib.Path("/data")),
        get_triplet=lambda: "trip",
        get_toolchain=lambda: toolchain,
    )
    monkeypatch.setattr(relenv.runtime, "common", lambda: stub_common)
    relenv.runtime.install_cargo_config()


def test_install_cargo_config_non_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "darwin", raising=False)
    relenv.runtime.install_cargo_config()


def test_install_cargo_config_alt_triplet(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    toolchain_dir = tmp_path / "toolchain" / "aarch"
    (toolchain_dir / "sysroot" / "lib").mkdir(parents=True)
    (toolchain_dir / "bin").mkdir(parents=True)
    (toolchain_dir / "bin" / "aarch-gcc").touch()
    stub_common = SimpleNamespace(
        DATA_DIR=tmp_path,
        work_dirs=lambda: SimpleNamespace(data=data_dir),
        get_triplet=lambda: "aarch",
        get_toolchain=lambda: toolchain_dir,
    )
    monkeypatch.setattr(relenv.runtime, "common", lambda: stub_common)
    relenv.runtime.install_cargo_config()
    assert (data_dir / "cargo" / "config.toml").exists()


def test_setup_openssl_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "win32", raising=False)
    relenv.runtime.setup_openssl()


def test_setup_openssl_without_binary(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "RELENV", tmp_path, raising=False)
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux")
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: None)

    modules_dirs: list[str] = []
    monkeypatch.setattr(relenv.runtime, "set_openssl_modules_dir", modules_dirs.append)
    providers: list[str] = []

    def fail_provider(name: str) -> int:
        providers.append(name)
        return 0

    monkeypatch.setattr(relenv.runtime, "load_openssl_provider", fail_provider)

    monkeypatch.delenv("OPENSSL_MODULES", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    relenv.runtime.setup_openssl()
    assert modules_dirs[-1].endswith("ossl-modules")
    assert providers == ["default", "legacy"]


def test_setup_openssl_with_system_binary(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "RELENV", tmp_path, raising=False)
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux")
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: "/usr/bin/openssl")

    module_calls: list[str] = []
    monkeypatch.setattr(relenv.runtime, "set_openssl_modules_dir", module_calls.append)

    providers: list[str] = []
    monkeypatch.setattr(
        relenv.runtime,
        "load_openssl_provider",
        lambda name: providers.append(name) or 1,
    )

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if args[:2] == ["/usr/bin/openssl", "version"]:
            if "-m" in args:
                return SimpleNamespace(
                    returncode=0, stdout='MODULESDIR: "/usr/lib/ssl"'
                )
            if "-d" in args:
                return SimpleNamespace(returncode=0, stdout='OPENSSLDIR: "/etc/ssl"')
        return SimpleNamespace(returncode=1, stdout="", stderr="error")

    monkeypatch.setattr(relenv.runtime.subprocess, "run", fake_run)

    certs_dir = pathlib.Path("/etc/ssl/certs")
    monkeypatch.setattr(
        pathlib.Path,
        "exists",
        lambda self: str(self)
        in (str(certs_dir), str(tmp_path / "lib" / "libcrypto.so")),
    )

    monkeypatch.delenv("OPENSSL_MODULES", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    relenv.runtime.setup_openssl()

    assert module_calls[0] == "/usr/lib/ssl"
    assert module_calls[-1].endswith("ossl-modules")
    assert {"default", "legacy"} <= set(providers)
    assert os.environ["SSL_CERT_DIR"] == str(certs_dir)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)


def test_relenv_importer_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[str] = []

    def wrapper(name: str) -> ModuleType:
        mod = ModuleType(name)
        mod.loaded = True  # type: ignore[attr-defined]
        loaded.append(name)
        return mod

    wrapper_obj = relenv.runtime.Wrapper("pkg.sub", wrapper, matcher="startswith")
    importer = relenv.runtime.RelenvImporter([wrapper_obj])
    assert importer.find_module("pkg.sub.module") is importer
    wrapper_obj.loading = False
    spec = importer.find_spec("pkg.sub.module")
    assert spec is not None
    module = importer.load_module("pkg.sub.module")
    assert getattr(module, "loaded", False)
    assert loaded == ["pkg.sub.module"]
    importer.create_module(spec)
    importer.exec_module(module)


def test_relenv_importer_defaults() -> None:
    importer = relenv.runtime.RelenvImporter()
    assert importer.wrappers == set()
    assert importer._loads == {}


def test_install_cargo_config_toolchain_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    stub_common = SimpleNamespace(
        DATA_DIR=pathlib.Path("/data"),
        work_dirs=lambda: SimpleNamespace(data=pathlib.Path("/data")),
        get_triplet=lambda: "trip",
        get_toolchain=lambda: None,
    )
    monkeypatch.setattr(relenv.runtime, "common", lambda: stub_common)
    relenv.runtime.install_cargo_config()


def test_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        relenv.runtime, "relenv_root", lambda: pathlib.Path("/relbootstrap")
    )
    monkeypatch.setattr(relenv.runtime, "setup_openssl", lambda: calls.append("ssl"))
    monkeypatch.setattr(
        relenv.runtime.site, "execsitecustomize", lambda: None, raising=False
    )
    monkeypatch.setattr(
        relenv.runtime, "setup_crossroot", lambda: calls.append("cross")
    )
    monkeypatch.setattr(
        relenv.runtime, "install_cargo_config", lambda: calls.append("cargo")
    )
    monkeypatch.setattr(
        relenv.runtime.warnings, "filterwarnings", lambda *args, **kwargs: None
    )
    original_meta = list(relenv.runtime.sys.meta_path)
    relenv.runtime.bootstrap()
    assert relenv.runtime.sys.RELENV == pathlib.Path("/relbootstrap")
    assert calls == ["ssl", "cross", "cargo"]
    assert relenv.runtime.sys.meta_path[0] is relenv.runtime.importer
    relenv.runtime.sys.meta_path = original_meta


def test_common_path_import_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(relenv.runtime.common, "common", raising=False)
    sentinel = ModuleType("cached.common")
    monkeypatch.setattr(relenv.runtime, "path_import", lambda name, path: sentinel)
    result = relenv.runtime.common()
    assert result is sentinel


def test_relocate_path_import_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(relenv.runtime.relocate, "relocate", raising=False)
    sentinel = ModuleType("cached.relocate")
    monkeypatch.setattr(relenv.runtime, "path_import", lambda name, path: sentinel)
    result = relenv.runtime.relocate()
    assert result is sentinel


def test_buildenv_path_import_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(relenv.runtime.buildenv, "builenv", raising=False)
    monkeypatch.delattr(relenv.runtime.buildenv, "buildenv", raising=False)
    sentinel = ModuleType("cached.buildenv")
    monkeypatch.setattr(relenv.runtime, "path_import", lambda name, path: sentinel)
    result = relenv.runtime.buildenv()
    assert result is sentinel


def test_common_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    count = {"calls": 0}

    def loader(name: str, path: str) -> ModuleType:
        count["calls"] += 1
        return ModuleType(name)

    monkeypatch.setattr(relenv.runtime, "path_import", loader)
    module1 = relenv.runtime.common()
    module2 = relenv.runtime.common()
    assert module1 is module2
    assert count["calls"] == 0


def test_relocate_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("relenv.relocate.cached")
    monkeypatch.setattr(relenv.runtime, "_RELOCATE", module, raising=False)
    result = relenv.runtime.relocate()
    assert result is module


def test_buildenv_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("relenv.buildenv.cached")
    monkeypatch.setattr(relenv.runtime, "_BUILDENV", module, raising=False)
    result = relenv.runtime.buildenv()
    assert result is module


def test_build_shebang_target(monkeypatch: pytest.MonkeyPatch) -> None:
    relenv.runtime.TARGET.TARGET = True
    relenv.runtime.TARGET.PATH = "/target"
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(
        relenv.runtime,
        "common",
        lambda: SimpleNamespace(
            relative_interpreter=lambda *args: pathlib.Path("bin/python"),
            format_shebang=lambda path: f"#!{path}",
        ),
    )

    def original(self: object) -> bytes:  # type: ignore[override]
        return b""

    result = relenv.runtime._build_shebang(original)(
        SimpleNamespace(target_dir="/tmp/scripts")
    )
    shebang = result.decode().strip()
    assert shebang.startswith("#!")
    path_part = shebang[2:]
    expected_suffix = os.fspath(pathlib.Path("bin") / "python")
    normalized = path_part.replace("\\", "/")
    assert normalized.endswith(expected_suffix.replace("\\", "/"))
    relenv.runtime.TARGET.TARGET = False
    relenv.runtime.TARGET.PATH = None


def test_build_shebang_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )

    class StubCommon:
        @staticmethod
        def relative_interpreter(_relenv, _scripts, _exec):
            return pathlib.Path("bin/python")

        @staticmethod
        def format_shebang(path: pathlib.Path) -> str:
            return f"#!{path}"

    monkeypatch.setattr(relenv.runtime, "common", lambda: StubCommon())

    def original(self: object) -> bytes:  # type: ignore[override]
        return b""

    result = relenv.runtime._build_shebang(original)(
        SimpleNamespace(target_dir="/tmp/dir")
    )
    shebang = result.decode().strip()
    assert shebang.startswith("#!")
    path_part = shebang[2:]
    # Use PurePosixPath since we're testing Linux behavior
    expected = os.fspath(pathlib.PurePosixPath("/") / "bin" / "python")
    assert path_part == expected


def test_setup_openssl_version_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: "/usr/bin/openssl")
    monkeypatch.setattr(relenv.runtime, "set_openssl_modules_dir", lambda path: None)
    monkeypatch.setattr(relenv.runtime, "load_openssl_provider", lambda name: 1)

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="err")

    monkeypatch.setattr(relenv.runtime.subprocess, "run", fake_run)
    relenv.runtime.setup_openssl()


def test_setup_openssl_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: "/usr/bin/openssl")
    monkeypatch.setattr(relenv.runtime, "load_openssl_provider", lambda name: 1)
    monkeypatch.setattr(relenv.runtime, "set_openssl_modules_dir", lambda path: None)
    monkeypatch.delenv("OPENSSL_MODULES", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if "-m" in args:
            return SimpleNamespace(returncode=0, stdout="invalid", stderr="")
        return SimpleNamespace(returncode=0, stdout='OPENSSLDIR: "/etc/ssl"', stderr="")

    monkeypatch.setattr(relenv.runtime.subprocess, "run", fake_run)
    relenv.runtime.setup_openssl()


def test_setup_openssl_cert_dir_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: "/usr/bin/openssl")
    monkeypatch.setattr(relenv.runtime, "load_openssl_provider", lambda name: 1)
    monkeypatch.setattr(relenv.runtime, "set_openssl_modules_dir", lambda path: None)

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if "-m" in args:
            return SimpleNamespace(
                returncode=0, stdout='MODULESDIR: "/usr/lib"', stderr=""
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="error")

    monkeypatch.setattr(relenv.runtime.subprocess, "run", fake_run)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    relenv.runtime.setup_openssl()


def test_setup_openssl_cert_dir_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: "/usr/bin/openssl")
    monkeypatch.setattr(relenv.runtime, "load_openssl_provider", lambda name: 1)
    monkeypatch.setattr(relenv.runtime, "set_openssl_modules_dir", lambda path: None)
    monkeypatch.delenv("OPENSSL_MODULES", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if "-m" in args:
            return SimpleNamespace(
                returncode=0, stdout='MODULESDIR: "/usr/lib"', stderr=""
            )
        return SimpleNamespace(returncode=0, stdout="invalid", stderr="")

    monkeypatch.setattr(relenv.runtime.subprocess, "run", fake_run)
    relenv.runtime.setup_openssl()


def test_setup_openssl_cert_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: "/usr/bin/openssl")
    cert_dir = tmp_path / "etc" / "ssl"
    cert_dir.mkdir(parents=True)
    cert_file = cert_dir / "cert.pem"
    cert_file.write_text("cert")

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        if "-m" in args:
            return SimpleNamespace(
                returncode=0, stdout='MODULESDIR: "{}"'.format(cert_dir), stderr=""
            )
        return SimpleNamespace(
            returncode=0, stdout='OPENSSLDIR: "{}"'.format(cert_dir), stderr=""
        )

    monkeypatch.setattr(relenv.runtime.subprocess, "run", fake_run)
    monkeypatch.setenv("OPENSSL_MODULES", "")
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(relenv.runtime, "set_openssl_modules_dir", lambda path: None)
    monkeypatch.setattr(relenv.runtime, "load_openssl_provider", lambda name: 1)
    relenv.runtime.setup_openssl()
    assert os.environ["SSL_CERT_FILE"] == os.fspath(cert_file)
    monkeypatch.delenv("OPENSSL_MODULES", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)


def test_set_openssl_modules_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    class FakeLib:
        def __init__(self) -> None:
            self.OSSL_PROVIDER_set_default_search_path = (
                lambda ctx, path: called.update({"path": path}) or 1
            )

    monkeypatch.setattr(relenv.runtime.ctypes, "CDLL", lambda path: FakeLib())
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "darwin", raising=False)
    relenv.runtime.set_openssl_modules_dir("/mods")
    assert called["path"] == b"/mods"


def test_load_openssl_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLib:
        def __init__(self) -> None:
            self.OSSL_PROVIDER_load = lambda ctx, name: 123

    monkeypatch.setattr(relenv.runtime.ctypes, "CDLL", lambda path: FakeLib())
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "darwin", raising=False)
    assert relenv.runtime.load_openssl_provider("default") == 123


def test_setup_crossroot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("RELENV_CROSS", str(tmp_path))
    original_path = sys.path[:]
    try:
        relenv.runtime.setup_crossroot()
        assert sys.prefix == str(tmp_path.resolve())
        assert str(tmp_path / "lib") in sys.path[0]
    finally:
        sys.path = original_path
        monkeypatch.delenv("RELENV_CROSS", raising=False)


def test_setup_openssl_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(relenv.runtime.shutil, "which", lambda _: "/usr/bin/openssl")
    order: list[str] = []
    monkeypatch.setattr(
        relenv.runtime, "set_openssl_modules_dir", lambda path: order.append(path)
    )
    providers: list[str] = []
    monkeypatch.setattr(
        relenv.runtime,
        "load_openssl_provider",
        lambda name: providers.append(name) or 0,
    )
    monkeypatch.setattr(
        relenv.runtime.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout='MODULESDIR: "/usr/lib"'
            if "-m" in args
            else 'OPENSSLDIR: "/etc/ssl"',
            stderr="",
        ),
    )
    monkeypatch.delenv("OPENSSL_MODULES", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    relenv.runtime.setup_openssl()
    assert order[0] == "/usr/lib"
    assert order[-1].endswith("ossl-modules")
    assert providers == ["fips", "default", "legacy"]
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)


def test_wrapsitecustomize_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def original() -> None:
        pass

    class CustomError(ImportError):
        def __init__(self) -> None:
            super().__init__("other")
            self.name = "other"

    import builtins

    orig_import = builtins.__import__

    def fake_import(
        name: str,
        globals: Optional[dict] = None,
        locals: Optional[dict] = None,
        fromlist=(),
        level: int = 0,
    ):
        if name == "sitecustomize":
            raise CustomError()
        return orig_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        relenv.runtime,
        "common",
        lambda: SimpleNamespace(sanitize_sys_path=lambda paths: paths),
    )
    wrapped = relenv.runtime.wrapsitecustomize(original)
    with pytest.raises(ImportError):
        wrapped()


def test_wrapsitecustomize_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    def original() -> None:
        pass

    fake_module = ModuleType("sitecustomize")
    fake_module.__file__ = "/tmp/pip-build-env/sitecustomize.py"
    monkeypatch.setitem(sys.modules, "sitecustomize", fake_module)
    monkeypatch.setattr(
        relenv.runtime,
        "common",
        lambda: SimpleNamespace(sanitize_sys_path=lambda paths: paths),
    )
    wrapped = relenv.runtime.wrapsitecustomize(original)
    monkeypatch.setattr(relenv.runtime, "debug", lambda msg: None)
    wrapped()


def test_set_openssl_modules_dir_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    class FakeLib:
        def __init__(self) -> None:
            self.OSSL_PROVIDER_set_default_search_path = (
                lambda ctx, path: called.update({"path": path}) or 1
            )

    monkeypatch.setattr(relenv.runtime.ctypes, "CDLL", lambda path: FakeLib())
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    relenv.runtime.set_openssl_modules_dir("/mods")
    assert called["path"] == b"/mods"


def test_load_openssl_provider_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLib:
        def __init__(self) -> None:
            self.OSSL_PROVIDER_load = lambda ctx, name: 456

    monkeypatch.setattr(relenv.runtime.ctypes, "CDLL", lambda path: FakeLib())
    monkeypatch.setattr(
        relenv.runtime.sys, "RELENV", pathlib.Path("/rel"), raising=False
    )
    monkeypatch.setattr(relenv.runtime.sys, "platform", "linux", raising=False)
    assert relenv.runtime.load_openssl_provider("default") == 456
