# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
Builder and Builds classes for managing the build process.
"""
from __future__ import annotations

import io
import json
import logging
import multiprocessing
import os
import pathlib
import shutil
import sys
import time
from typing import (
    Any,
    Callable,
    Dict,
    IO,
    List,
    MutableMapping,
    Optional,
    Sequence,
    TypedDict,
    Union,
    cast,
)
import tempfile

from relenv.common import (
    DATA_DIR,
    MODULE_DIR,
    ConfigurationError,
    build_arch,
    extract_archive,
    get_toolchain,
    get_triplet,
    work_dirs,
    WorkDirs,
)

from .download import Download
from .ui import (
    LineCountHandler,
    load_build_stats,
    print_ui,
    print_ui_expanded,
    update_build_stats,
    BuildStats,
)
from .builders import build_default as _default_build_func

# Type alias for path-like objects
PathLike = Union[str, os.PathLike[str]]

log = logging.getLogger(__name__)


def _default_populate_env(env: MutableMapping[str, str], dirs: "Dirs") -> None:
    """Default populate_env implementation (does nothing).

    This default implementation intentionally does nothing; specific steps may
    provide their own implementation via the ``populate_env`` hook.
    """
    _ = env
    _ = dirs


def get_dependency_version(name: str, platform: str) -> Optional[Dict[str, str]]:
    """
    Get dependency version and metadata from python-versions.json.

    Returns dict with keys: version, url, sha256, and any extra fields (e.g., sqliteversion)
    Returns None if dependency not found.

    :param name: Dependency name (openssl, sqlite, xz)
    :param platform: Platform name (linux, darwin, win32)
    :return: Dict with version, url, sha256, and extra fields, or None
    """
    versions_file = MODULE_DIR / "python-versions.json"
    if not versions_file.exists():
        return None

    data = json.loads(versions_file.read_text())
    dependencies = data.get("dependencies", {})

    if name not in dependencies:
        return None

    # Get the latest version for this dependency that supports the platform
    dep_versions = dependencies[name]
    for version, info in sorted(
        dep_versions.items(),
        key=lambda x: [int(n) for n in x[0].split(".")],
        reverse=True,
    ):
        if platform in info.get("platforms", []):
            # Build result dict with version, url, sha256, and any extra fields
            result = {
                "version": version,
                "url": info["url"],
                "sha256": info.get("sha256", ""),
            }
            # Add any extra fields (like sqliteversion for SQLite)
            for key, value in info.items():
                if key not in ["url", "sha256", "platforms"]:
                    result[key] = value
            return result

    return None


# Public alias for _default_populate_env for backward compatibility
populate_env = _default_populate_env


class Dirs:
    """
    A container for directories during build time.

    :param dirs: A collection of working directories
    :type dirs: ``relenv.common.WorkDirs``
    :param name: The name of this collection
    :type name: str
    :param arch: The architecture being worked with
    :type arch: str
    """

    def __init__(self, dirs: WorkDirs, name: str, arch: str, version: str) -> None:
        # XXX name is the specific to a step where as everything
        # else here is generalized to the entire build
        self.name = name
        self.version = version
        self.arch = arch
        self.root = dirs.root
        self.build = dirs.build
        self.downloads = dirs.download
        self.logs = dirs.logs
        self.sources = dirs.src
        self.tmpbuild = tempfile.mkdtemp(prefix="{}_build".format(name))
        self.source: Optional[pathlib.Path] = None

    @property
    def toolchain(self) -> Optional[pathlib.Path]:
        """Get the toolchain directory path for the current platform."""
        if sys.platform == "darwin":
            return get_toolchain(root=self.root)
        elif sys.platform == "win32":
            return get_toolchain(root=self.root)
        else:
            return get_toolchain(self.arch, self.root)

    @property
    def _triplet(self) -> str:
        if sys.platform == "darwin":
            return "{}-macos".format(self.arch)
        elif sys.platform == "win32":
            return "{}-win".format(self.arch)
        else:
            return "{}-linux-gnu".format(self.arch)

    @property
    def prefix(self) -> pathlib.Path:
        """Get the build prefix directory path."""
        return self.build / f"{self.version}-{self._triplet}"

    def __getstate__(self) -> Dict[str, Any]:
        """
        Return an object used for pickling.

        :return: The picklable state
        """
        return {
            "name": self.name,
            "arch": self.arch,
            "root": self.root,
            "build": self.build,
            "downloads": self.downloads,
            "logs": self.logs,
            "sources": self.sources,
            "tmpbuild": self.tmpbuild,
        }

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """
        Unwrap the object returned from unpickling.

        :param state: The state to unpickle
        :type state: dict
        """
        self.name = state["name"]
        self.arch = state["arch"]
        self.root = state["root"]
        self.downloads = state["downloads"]
        self.logs = state["logs"]
        self.sources = state["sources"]
        self.build = state["build"]
        self.tmpbuild = state["tmpbuild"]

    def to_dict(self) -> Dict[str, Any]:
        """
        Get a dictionary representation of the directories in this collection.

        :return: A dictionary of all the directories
        :rtype: dict
        """
        return {
            x: getattr(self, x)
            for x in [
                "root",
                "prefix",
                "downloads",
                "logs",
                "sources",
                "build",
                "toolchain",
            ]
        }


class Recipe(TypedDict):
    """Typed description of a build recipe entry."""

    build_func: Callable[[MutableMapping[str, str], Dirs, IO[str]], None]
    wait_on: List[str]
    download: Optional[Download]


class Builder:
    """
    Utility that handles the build process.

    :param root: The root of the working directories for this build
    :type root: str
    :param recipies: The instructions for the build steps
    :type recipes: list
    :param build_default: The default build function, defaults to ``build_default``
    :type build_default: types.FunctionType
    :param populate_env: The default function to populate the build environment, defaults to ``populate_env``
    :type populate_env: types.FunctionType
    :param force_download: If True, forces downloading the archives even if they exist, defaults to False
    :type force_download: bool
    :param arch: The architecture being built
    :type arch: str
    """

    def __init__(
        self,
        root: Optional[PathLike] = None,
        recipies: Optional[Dict[str, Recipe]] = None,
        build_default: Optional[
            Callable[[MutableMapping[str, str], Dirs, IO[str]], None]
        ] = None,
        populate_env: Optional[Callable[[MutableMapping[str, str], Dirs], None]] = None,
        arch: str = "x86_64",
        version: str = "",
    ) -> None:
        self.root = root
        self.dirs: WorkDirs = work_dirs(root)
        self.build_arch = build_arch()
        self.build_triplet = get_triplet(self.build_arch)
        self.arch = arch
        self.sources = self.dirs.src
        self.downloads = self.dirs.download

        if recipies is None:
            self.recipies: Dict[str, Recipe] = {}
        else:
            self.recipies = recipies

        # Use dependency injection with sensible defaults
        self.build_default: Callable[
            [MutableMapping[str, str], Dirs, IO[str]], None
        ] = (build_default if build_default is not None else _default_build_func)

        # Use the default populate_env if none provided
        self.populate_env: Callable[[MutableMapping[str, str], Dirs], None] = (
            populate_env if populate_env is not None else _default_populate_env
        )

        self.version = version
        self.set_arch(self.arch)

    def copy(self, version: str, checksum: Optional[str]) -> "Builder":
        """Create a copy of this Builder with a different version."""
        recipies: Dict[str, Recipe] = {}
        for name in self.recipies:
            recipe = self.recipies[name]
            recipies[name] = {
                "build_func": recipe["build_func"],
                "wait_on": list(recipe["wait_on"]),
                "download": recipe["download"].copy() if recipe["download"] else None,
            }
        build = Builder(
            self.root,
            recipies,
            self.build_default,
            self.populate_env,
            self.arch,
            version,
        )
        python_download = build.recipies["python"].get("download")
        if python_download is None:
            raise ConfigurationError("Python recipe is missing a download entry")
        python_download.version = version
        python_download.checksum = checksum
        return build

    def set_arch(self, arch: str) -> None:
        """
        Set the architecture for the build.

        :param arch: The arch to build
        :type arch: str
        """
        self.arch = arch
        self._toolchain: Optional[pathlib.Path] = None

    @property
    def toolchain(self) -> Optional[pathlib.Path]:
        """Lazily fetch toolchain only when needed."""
        if self._toolchain is None and sys.platform == "linux":
            from relenv.common import get_toolchain

            self._toolchain = get_toolchain(self.arch, self.dirs.root)
        return self._toolchain

    @property
    def triplet(self) -> str:
        """Get the target triplet for the current architecture."""
        return get_triplet(self.arch)

    @property
    def prefix(self) -> pathlib.Path:
        """Get the build prefix directory path."""
        return self.dirs.build / f"{self.version}-{self.triplet}"

    @property
    def _triplet(self) -> str:
        if sys.platform == "darwin":
            return "{}-macos".format(self.arch)
        elif sys.platform == "win32":
            return "{}-win".format(self.arch)
        else:
            return "{}-linux-gnu".format(self.arch)

    def add(
        self,
        name: str,
        build_func: Optional[Callable[..., Any]] = None,
        wait_on: Optional[Sequence[str]] = None,
        download: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add a step to the build process.

        :param name: The name of the step
        :type name: str
        :param build_func: The function that builds this step, defaults to None
        :type build_func: types.FunctionType, optional
        :param wait_on: Processes to wait on before running this step, defaults to None
        :type wait_on: list, optional
        :param download: A dictionary of download information, defaults to None
        :type download: dict, optional
        """
        if wait_on is None:
            wait_on_list: List[str] = []
        else:
            wait_on_list = list(wait_on)
        if build_func is None:
            build_func = self.build_default
        download_obj: Optional[Download] = None
        if download is not None:
            download_obj = Download(name, destination=self.downloads, **download)
        self.recipies[name] = {
            "build_func": build_func,
            "wait_on": wait_on_list,
            "download": download_obj,
        }

    def run(
        self,
        name: str,
        event: "multiprocessing.synchronize.Event",
        build_func: Callable[..., Any],
        download: Optional[Download],
        show_ui: bool = False,
        log_level: str = "WARNING",
        line_counts: Optional[MutableMapping[str, int]] = None,
    ) -> Any:
        """
        Run a build step.

        :param name: The name of the step to run
        :type name: str
        :param event: An event to track this process' status and alert waiting steps
        :type event: ``multiprocessing.Event``
        :param build_func: The function to use to build this step
        :type build_func: types.FunctionType
        :param download: The ``Download`` instance for this step
        :type download: ``Download``
        :param line_counts: Optional shared dict for tracking log line counts
        :type line_counts: Optional[MutableMapping[str, int]]

        :return: The output of the build function
        """
        root_log = logging.getLogger(None)
        if sys.platform == "win32":
            if not show_ui:
                handler = logging.StreamHandler()
                handler.setLevel(logging.getLevelName(log_level))
                root_log.addHandler(handler)

        for handler in root_log.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setFormatter(
                    logging.Formatter(f"%(asctime)s {name} %(message)s")
                )

        if not self.dirs.build.exists():
            os.makedirs(self.dirs.build, exist_ok=True)

        dirs = Dirs(self.dirs, name, self.arch, self.version)
        os.makedirs(dirs.sources, exist_ok=True)
        os.makedirs(dirs.logs, exist_ok=True)
        os.makedirs(dirs.prefix, exist_ok=True)

        while event.is_set() is False:
            time.sleep(0.3)

        logfp = io.open(os.path.join(dirs.logs, "{}.log".format(name)), "w")
        handler = logging.FileHandler(dirs.logs / f"{name}.log")
        root_log.addHandler(handler)
        root_log.setLevel(logging.NOTSET)

        # Add line count handler if tracking is enabled
        line_count_handler: Optional[LineCountHandler] = None
        if line_counts is not None:
            line_count_handler = LineCountHandler(name, line_counts)
            root_log.addHandler(line_count_handler)

        # DEBUG: Uncomment to debug
        # logfp = sys.stdout

        cwd = os.getcwd()
        if download:
            extract_archive(dirs.sources, str(download.filepath))
            dirs.source = dirs.sources / download.filepath.name.split(".tar")[0]
            os.chdir(dirs.source)
        else:
            os.chdir(dirs.prefix)

        if sys.platform == "win32":
            env = os.environ.copy()
        else:
            env = {
                "PATH": os.environ["PATH"],
            }
        env["RELENV_DEBUG"] = "1"
        env["RELENV_BUILDENV"] = "1"
        env["RELENV_HOST"] = self.triplet
        env["RELENV_HOST_ARCH"] = self.arch
        env["RELENV_BUILD"] = self.build_triplet
        env["RELENV_BUILD_ARCH"] = self.build_arch
        python_download = self.recipies["python"].get("download")
        if python_download is None:
            raise ConfigurationError("Python recipe is missing download configuration")
        env["RELENV_PY_VERSION"] = python_download.version
        env["RELENV_PY_MAJOR_VERSION"] = env["RELENV_PY_VERSION"].rsplit(".", 1)[0]
        if "RELENV_DATA" in os.environ:
            env["RELENV_DATA"] = os.environ["RELENV_DATA"]
        if self.build_arch != self.arch:
            native_root = DATA_DIR / "native"
            env["RELENV_NATIVE_PY"] = str(native_root / "bin" / "python3")

        self.populate_env(env, dirs)

        _ = dirs.to_dict()
        for k in _:
            log.info("Directory %s %s", k, _[k])
        for k in env:
            log.info("Environment %s %s", k, env[k])
        try:
            result = build_func(env, dirs, logfp)
            # Update build stats with final line count on success
            if line_count_handler is not None and line_counts is not None:
                if name in line_counts:
                    final_count = line_counts[name]
                    update_build_stats(name, final_count)
            return result
        except Exception:
            log.exception("Build failure")
            sys.exit(1)
        finally:
            os.chdir(cwd)
            if line_count_handler is not None:
                root_log.removeHandler(line_count_handler)
            root_log.removeHandler(handler)
            logfp.close()

    def cleanup(self) -> None:
        """
        Clean up the build directories.
        """
        shutil.rmtree(self.prefix)

    def clean(self) -> None:
        """
        Completely clean up the remnants of a relenv build.
        """
        # Clean directories
        for _ in [self.prefix, self.sources]:
            try:
                shutil.rmtree(_)
            except PermissionError:
                sys.stderr.write(f"Unable to remove directory: {_}")
            except FileNotFoundError:
                pass
        # Clean files
        archive = f"{self.prefix}.tar.xz"
        for _ in [archive]:
            try:
                os.remove(_)
            except FileNotFoundError:
                pass

    def download_files(
        self,
        steps: Optional[Sequence[str]] = None,
        force_download: bool = False,
        show_ui: bool = False,
        expanded_ui: bool = False,
    ) -> None:
        """
        Download all of the needed archives.

        :param steps: The steps to download archives for, defaults to None
        :type steps: list, optional
        :param expanded_ui: Whether to use expanded UI with progress bars
        :type expanded_ui: bool, optional
        """
        step_names = list(steps) if steps is not None else list(self.recipies)

        fails: List[str] = []
        processes: Dict[str, multiprocessing.Process] = {}
        events: Dict[str, Any] = {}

        # For downloads, we don't track line counts but can still use expanded UI format
        manager = multiprocessing.Manager()
        line_counts: MutableMapping[str, int] = manager.dict()
        build_stats: Dict[str, BuildStats] = {}

        if show_ui:
            if not expanded_ui:
                sys.stdout.write("Starting downloads \n")
        log.info("Starting downloads")
        if show_ui and not expanded_ui:
            print_ui(events, processes, fails)
        for name in step_names:
            download = self.recipies[name]["download"]
            if download is None:
                continue
            event = multiprocessing.Event()
            event.set()
            events[name] = event

            # Create progress callback if using expanded UI
            def make_progress_callback(
                step_name: str, shared_dict: MutableMapping[str, int]
            ) -> Callable[[int, int], None]:
                def progress_callback(downloaded: int, total: int) -> None:
                    shared_dict[step_name] = downloaded
                    shared_dict[f"{step_name}_total"] = total

                return progress_callback

            download_kwargs: Dict[str, Any] = {
                "force_download": force_download,
                "show_ui": show_ui,
                "exit_on_failure": True,
            }
            if expanded_ui:
                download_kwargs["progress_callback"] = make_progress_callback(
                    name, line_counts
                )

            proc = multiprocessing.Process(
                name=name,
                target=download,
                kwargs=download_kwargs,
            )
            proc.start()
            processes[name] = proc

        while processes:
            for proc in list(processes.values()):
                proc.join(0.3)
                # DEBUG: Comment to debug
                if show_ui:
                    if expanded_ui:
                        print_ui_expanded(
                            events,
                            processes,
                            fails,
                            line_counts,
                            build_stats,
                            "download",
                        )
                    else:
                        print_ui(events, processes, fails)
                if proc.exitcode is None:
                    continue
                processes.pop(proc.name)
                if proc.exitcode != 0:
                    fails.append(proc.name)
        if show_ui:
            if expanded_ui:
                print_ui_expanded(
                    events, processes, fails, line_counts, build_stats, "download"
                )
            else:
                print_ui(events, processes, fails)
            sys.stdout.write("\n")
        if fails and False:
            if show_ui:
                print_ui(events, processes, fails)
                sys.stderr.write("The following failures were reported\n")
                for fail in fails:
                    sys.stderr.write(fail + "\n")
                sys.stderr.flush()
            sys.exit(1)

    def build(
        self,
        steps: Optional[Sequence[str]] = None,
        cleanup: bool = True,
        show_ui: bool = False,
        log_level: str = "WARNING",
        expanded_ui: bool = False,
    ) -> None:
        """
        Build!

        :param steps: The steps to run, defaults to None
        :type steps: list, optional
        :param cleanup: Whether to clean up or not, defaults to True
        :type cleanup: bool, optional
        :param expanded_ui: Whether to use expanded UI with progress bars
        :type expanded_ui: bool, optional
        """  # noqa: D400
        fails: List[str] = []
        events: Dict[str, Any] = {}
        waits: Dict[str, List[str]] = {}
        processes: Dict[str, multiprocessing.Process] = {}

        # Set up shared line counts and load build stats for expanded UI
        manager = multiprocessing.Manager()
        line_counts: MutableMapping[str, int] = manager.dict()
        build_stats: Dict[str, BuildStats] = {}
        if expanded_ui:
            build_stats = load_build_stats()

        if show_ui:
            if expanded_ui:
                # Expanded UI will print its own header
                pass
            else:
                sys.stdout.write("Starting builds\n")
                # DEBUG: Comment to debug
                print_ui(events, processes, fails)
        log.info("Starting builds")

        step_names = list(steps) if steps is not None else list(self.recipies)

        for name in step_names:
            event = multiprocessing.Event()
            events[name] = event
            recipe = self.recipies[name]
            kwargs = dict(recipe)
            kwargs["show_ui"] = show_ui
            kwargs["log_level"] = log_level
            kwargs["line_counts"] = line_counts

            # Determine needed dependency recipies.
            wait_on_seq = cast(List[str], kwargs.pop("wait_on", []))
            wait_on_list = list(wait_on_seq)
            for dependency in wait_on_list[:]:
                if dependency not in step_names:
                    wait_on_list.remove(dependency)

            waits[name] = wait_on_list
            if not waits[name]:
                event.set()

            proc = multiprocessing.Process(
                name=name, target=self.run, args=(name, event), kwargs=kwargs
            )
            proc.start()
            processes[name] = proc

        # Wait for the processes to finish and check if we should send any
        # dependency events.
        while processes:
            for proc in list(processes.values()):
                proc.join(0.3)
                if show_ui:
                    # DEBUG: Comment to debug
                    if expanded_ui:
                        print_ui_expanded(
                            events, processes, fails, line_counts, build_stats, "build"
                        )
                    else:
                        print_ui(events, processes, fails)
                if proc.exitcode is None:
                    continue
                processes.pop(proc.name)
                if proc.exitcode != 0:
                    fails.append(proc.name)
                    is_failure = True
                else:
                    is_failure = False
                for name in waits:
                    if proc.name in waits[name]:
                        if is_failure:
                            if name in processes:
                                processes[name].terminate()
                                time.sleep(0.1)
                        waits[name].remove(proc.name)
                    if not waits[name] and not events[name].is_set():
                        events[name].set()

        if fails:
            sys.stderr.write("The following failures were reported\n")
            last_outs = {}
            for fail in fails:
                log_file = self.dirs.logs / f"{fail}.log"
                try:
                    with io.open(log_file) as fp:
                        fp.seek(0, 2)
                        end = fp.tell()
                        ind = end - 4096
                        if ind > 0:
                            fp.seek(ind)
                        else:
                            fp.seek(0)
                        last_out = fp.read()
                        if show_ui:
                            sys.stderr.write("=" * 20 + f" {fail} " + "=" * 20 + "\n")
                            sys.stderr.write(fp.read() + "\n\n")
                except FileNotFoundError:
                    last_outs[fail] = f"Log file not found: {log_file}"
                log.error("Build step %s has failed", fail)
                log.error(last_out)
            if show_ui:
                sys.stderr.flush()
            if cleanup:
                log.debug("Performing cleanup.")
                self.cleanup()
            sys.exit(1)
        if show_ui:
            time.sleep(0.3)
            if expanded_ui:
                print_ui_expanded(
                    events, processes, fails, line_counts, build_stats, "build"
                )
            else:
                print_ui(events, processes, fails)
            sys.stdout.write("\n")
            sys.stdout.flush()
        if cleanup:
            log.debug("Performing cleanup.")
            self.cleanup()

    def check_prereqs(self) -> List[str]:
        """
        Check pre-requsists for build.

        This method verifies all requrements for a successful build are satisfied.

        :return: Returns a list of string describing failed checks
        :rtype: list
        """
        fail: List[str] = []
        if sys.platform == "linux":
            if not self.toolchain or not self.toolchain.exists():
                fail.append(
                    f"Toolchain for {self.arch} does not exist. Please pip install ppbt."
                )
        return fail

    def __call__(
        self,
        steps: Optional[Sequence[str]] = None,
        arch: Optional[str] = None,
        clean: bool = True,
        cleanup: bool = True,
        force_download: bool = False,
        download_only: bool = False,
        show_ui: bool = False,
        log_level: str = "WARNING",
        expanded_ui: bool = False,
    ) -> None:
        """
        Set the architecture, define the steps, clean if needed, download what is needed, and build.

        :param steps: The steps to run, defaults to None
        :type steps: list, optional
        :param arch: The architecture to build, defaults to None
        :type arch: str, optional
        :param clean: If true, cleans the directories first, defaults to True
        :type clean: bool, optional
        :param cleanup: Cleans up after build if true, defaults to True
        :type cleanup: bool, optional
        :param force_download: Whether or not to download the content if it already exists, defaults to True
        :type force_download: bool, optional
        :param expanded_ui: Whether to use expanded UI with progress bars
        :type expanded_ui: bool, optional
        """
        log = logging.getLogger(None)
        log.setLevel(logging.NOTSET)

        stream_handler: Optional[logging.Handler] = None
        if not show_ui:
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.getLevelName(log_level))
            log.addHandler(stream_handler)

        os.makedirs(self.dirs.logs, exist_ok=True)
        file_handler = logging.FileHandler(self.dirs.logs / "build.log")
        file_handler.setLevel(logging.INFO)
        log.addHandler(file_handler)

        if arch:
            self.set_arch(arch)

        step_names = list(steps) if steps is not None else list(self.recipies)

        failures = self.check_prereqs()
        if not download_only and failures:
            for _ in failures:
                sys.stderr.write(f"{_}\n")
            sys.stderr.flush()
            sys.exit(1)

        if clean:
            self.clean()

        if self.build_arch != self.arch:
            native_root = DATA_DIR / "native"
            if not native_root.exists():
                if "RELENV_NATIVE_PY_VERSION" in os.environ:
                    version = os.environ["RELENV_NATIVE_PY_VERSION"]
                else:
                    version = self.version
                from relenv.create import create

                create("native", DATA_DIR, version=version)

        # Start a process for each build passing it an event used to notify each
        # process if it's dependencies have finished.
        try:
            self.download_files(
                step_names,
                force_download=force_download,
                show_ui=show_ui,
                expanded_ui=expanded_ui,
            )
            if download_only:
                return
            self.build(
                step_names,
                cleanup,
                show_ui=show_ui,
                log_level=log_level,
                expanded_ui=expanded_ui,
            )
        finally:
            log.removeHandler(file_handler)
            if stream_handler is not None:
                log.removeHandler(stream_handler)


class Builds:
    """Collection of platform-specific builders."""

    def __init__(self) -> None:
        """Initialize an empty collection of builders."""
        self.builds: Dict[str, Builder] = {}

    def add(self, platform: str, *args: Any, **kwargs: Any) -> Builder:
        """Add a builder for a specific platform."""
        if "builder" in kwargs:
            build_candidate = kwargs.pop("builder")
            if args or kwargs:
                raise RuntimeError(
                    "builder keyword can not be used with other kwargs or args"
                )
            build = cast(Builder, build_candidate)
        else:
            build = Builder(*args, **kwargs)
        self.builds[platform] = build
        return build


builds = Builds()
