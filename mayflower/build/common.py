import logging
import os.path
import codecs
import hashlib
import pathlib
import glob
import shutil
import tarfile
import tempfile
import time
import traceback
import subprocess
import random
import sys
import io
import os
import platform
import urllib.request
import urllib.error
import multiprocessing
import pprint

from mayflower.common import (
    MODULE_DIR,
    MayflowerException,
    work_root,
    work_dirs,
    get_toolchain,
    extract_archive,
    download_url,
    runcmd,
    PIPE,
)
from mayflower.relocate import main as relocate_main
from mayflower.create import create

log = logging.getLogger(__name__)

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
END = "\033[0m"
MOVEUP = "\033[F"


CICD = "CI" in os.environ
NODOWLOAD = False
WORK_IN_CWD = False


SITECUSTOMIZE = """\"\"\"
Mayflower site customize
\"\"\"
import site, os
site.ENABLE_USER_SITE = False
try:
    import mayflower.runtime
except ImportError:
    if "MAYFLOWER_DEBUG" in os.environ:
        print("Unable to find mayflower.runtime for bootstrap.")
else:
    mayflower.runtime.bootstrap()
"""


def get_build():
    if WORK_IN_CWD:
        base = pathlib.Path("build").resolve()
    else:
        base = MODULE_DIR / "_build"
    return base


def print_ui(events, processes, fails, flipstat={}):
    if CICD:
        sys.stdout.flush()
        return
    uiline = []
    for name in events:
        if not events[name].is_set():
            status = " {}.".format(YELLOW)
        elif name in processes:
            now = time.time()
            if name not in flipstat:
                flipstat[name] = (0, now)
            if flipstat[name][1] < now:
                flipstat[name] = (1 - flipstat[name][0], now + random.random())
            status = " {}{}".format(GREEN, " " if flipstat[name][0] == 1 else ".")
        elif name in fails:
            status = " {}\u2718".format(RED)
        else:
            status = " {}\u2718".format(GREEN)
        uiline.append(status)
    uiline.append("  " + END)
    sys.stdout.write("\r")
    sys.stdout.write("".join(uiline))
    sys.stdout.flush()


def verify_checksum(file, checksum):
    if checksum is None:
        log.error(f"Can't verify checksum because none was given")
        return False
    with open(file, "rb") as fp:
        if checksum != hashlib.md5(fp.read()).hexdigest():
            raise MayflowerException("md5 checksum verification failed")
    return True


def all_dirs(root, recurse=True):
    paths = [root]
    for root, dirs, files in os.walk(root):
        for name in dirs:
            paths.append(os.path.join(root, name))
    return paths


def _parse_gcc_version(stdout):
    vline = stdout.splitlines()[0]
    vline, vstr = [_.strip() for _ in vline.rsplit(" ", 1)]
    if vstr.find(".") != -1:
        return vstr
    return vline.rsplit(" ", 1)[1].strip()


def gcc_version(cc):
    proc = runcmd([cc, "--version"], stderr=PIPE, stdout=PIPE)
    return _parse_gcc_version(proc.stdout.decode())


def _parse_kernel_version(stdout):
    stdout = stdout.split("-", 1)[0]
    return ".".join(stdout.split(".")[:3])


def kernel_version():
    proc = runcmd(["uname", "-r"], stderr=PIPE, stdout=PIPE)
    return _parse_kernel_version(proc.stdout.decode())


def populate_env(dirs, env):
    pass


def build_default(env, dirs, logfp):
    cmd = [
        "./configure",
        "--prefix={}".format(dirs.prefix),
    ]
    if env["MAYFLOWER_HOST"].find("linux") > -1:
        cmd += [
            "--build=x86_64-linux-gnu",
            "--host={}".format(env["MAYFLOWER_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


def build_openssl(env, dirs, logfp):
    arch = "aarch64"
    if sys.platform == "darwin":
        plat = "darwin64"
        if env["MAYFLOWER_ARCH"] == "x86_64":
            arch = "x86_64-cc"
    else:
        plat = "linux"
        if env["MAYFLOWER_ARCH"] == "x86_64":
            arch = "x86_64"
        elif env["MAYFLOWER_ARCH"] == "aarch64":
            arch = "aarch64"
    runcmd(
        [
            "./Configure",
            "{}-{}".format(plat, arch),
            "no-idea",
            "shared",
            "--prefix={}".format(dirs.prefix),
            # "--openssldir={}/ssl".format(dirs.prefix),
            "--openssldir=/tmp/ssl",
        ],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install_sw"], env=env, stderr=logfp, stdout=logfp)


def build_sqlite(env, dirs, logfp):
    # extra_cflags=('-Os '
    #              '-DSQLITE_ENABLE_FTS5 '
    #              '-DSQLITE_ENABLE_FTS4 '
    #              '-DSQLITE_ENABLE_FTS3_PARENTHESIS '
    #              '-DSQLITE_ENABLE_JSON1 '
    #              '-DSQLITE_ENABLE_RTREE '
    #              '-DSQLITE_TCL=0 '
    #              )
    # configure_pre=[
    #    '--enable-threadsafe',
    #    '--enable-shared=no',
    #    '--enable-static=yes',
    #    '--disable-readline',
    #    '--disable-dependency-tracking',
    # ]
    cmd = [
        "./configure",
        "--with-shared",
        "--without-static",
        "--enable-threadsafe",
        "--disable-readline",
        "--disable-dependency-tracking",
        "--prefix={}".format(dirs.prefix),
        "--enable-add-ons=nptl,ports",
    ]
    if env["MAYFLOWER_HOST"].find("linux") > -1:
        cmd += [
            "--build=x86_64-linux-gnu",
            "--host={}".format(env["MAYFLOWER_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


class Download:
    def __init__(
        self, name, url, signature=None, destination="", version="", md5sum=None
    ):
        self.name = name
        self.url_tpl = url
        self.signature = signature
        self.destination = destination
        self.version = version
        self.md5sum = md5sum

    @property
    def url(self):
        return self.url_tpl.format(version=self.version)

    @property
    def filepath(self):
        _, name = self.url.rsplit("/", 1)
        return pathlib.Path(self.destination) / name

    @property
    def formatted_url(self):
        return self.url.format(version=self.version)

    def fetch_file(self):
        return download_url(self.url, self.destination)

    def fetch_signature(self, version):
        return download_url(self.url, self.destination)

    def exists(self):
        """
        True when the artifact already exists on disk
        """
        return self.filepath.exists()

    def valid_hash(self):
        pass

    @staticmethod
    def validate_signature(archive, signature):
        """
        True when the archive's signature is valid
        """
        if signature is None:
            log.error("Can't check signature because none was given")
            return False
        try:
            runcmd(["gpg", "--verify", signature, archive], stderr=PIPE, stdout=PIPE)
            return True
        except MayflowerException as exc:
            log.error("Signature validation failed on %s: %s", archive, exc)
            return False

    @staticmethod
    def validate_md5sum(archive, md5sum):
        """
        True when when the archive matches the md5 hash
        """
        try:
            verify_checksum(archive, md5sum)
            return True
        except MayflowerException as exc:
            log.error("md5 validation failed on %s: %s", archive, exc)
            return False

    def __call__(self):
        os.makedirs(self.filepath.parent, exist_ok=True)
        self.fetch_file()
        valid = True
        if self.signature is not None:
            valid_sig = self.validate_signature(self.filepath, self.signature)
            valid = valid and valid_sig
        if self.md5sum is not None:
            valid_md5 = self.validate_md5sum(self.filepath, self.md5sum)
            valid = valid and valid_md5
        log.debug("Checksum for %s: %s", self.name, self.md5sum)
        return valid


class Dirs:
    def __init__(self, dirs, name, arch):
        self.name = name
        self.arch = arch
        self.root = dirs.root
        self.build = dirs.build
        self.downloads = dirs.download
        self.logs = dirs.logs
        self.sources = dirs.src
        self.tmpbuild = tempfile.mkdtemp(prefix="{}_build".format(name))

    @property
    def toolchain(self):
        if sys.platform == "darwin":
            return get_toolchain(root=self.root)
        elif sys.platform == "win32":
            return get_toolchain(root=self.root)
        else:
            return get_toolchain(self.arch, self.root)

    @property
    def _triplet(self):
        if sys.platform == "darwin":
            return "{}-macos".format(self.arch)
        elif sys.platform == "win32":
            return "{}-win".format(self.arch)
        else:
            return "{}-linux-gnu".format(self.arch)

    @property
    def prefix(self):
        return self.build / self._triplet

    def __getstate__(self):
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

    def __setstate__(self, state):
        self.name = state["name"]
        self.arch = state["arch"]
        self.root = state["root"]
        self.downloads = state["downloads"]
        self.logs = state["logs"]
        self.sources = state["sources"]
        self.build = state["build"]
        self.tmpbuild = state["tmpbuild"]

    def to_dict(self):
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


class Builder:
    def __init__(
        self,
        root=None,
        recipies=None,
        build_default=build_default,
        populate_env=populate_env,
        no_download=False,
        arch="x86_64",
    ):
        self.dirs = work_dirs(root)
        self.arch = arch

        if sys.platform == "darwin":
            self.triplet = "{}-macos".format(self.arch)
        elif sys.platform == "win32":
            self.triplet = "{}-win".format(self.arch)
        else:
            self.triplet = "{}-linux-gnu".format(self.arch)

        self.prefix = self.dirs.build / self.triplet
        self.sources = self.dirs.src
        self.downloads = self.dirs.download

        if recipies is None:
            self.recipies = {}
        else:
            self.recipies = recipies

        self.build_default = build_default
        self.populate_env = populate_env
        self.no_download = no_download
        self.toolchains = get_toolchain(root=self.dirs.root)
        self.toolchain = get_toolchain(self.arch, self.dirs.root)

    @property
    def native_python(self):
        if sys.platform == "darwin":
            return self.dirs.build / "x86_64-macos" / "bin" / "python3"
        elif sys.platform == "win32":
            return self.dirs.build / "x86_64-win" / "Scripts" / "python.exe"
        else:
            return self.dirs.build / "x86_64-linux-gnu" / "bin" / "python3"

    def set_arch(self, arch):
        self.arch = arch
        if sys.platform == "darwin":
            self.triplet = "{}-macos".format(self.arch)
            self.prefix = self.dirs.build / "{}-macos".format(self.arch)
            # XXX Not used for MacOS
            self.toolchain = get_toolchain(root=self.dirs.root)
        elif sys.platform == "win32":
            self.triplet = "{}-win".format(self.arch)
            self.prefix = self.dirs.build / "{}-win".format(self.arch)
            # XXX Not used for Windows
            self.toolchain = get_toolchain(root=self.dirs.root)
        else:
            self.triplet = "{}-linux-gnu".format(self.arch)
            self.prefix = self.dirs.build / self.triplet
            self.toolchain = get_toolchain(self.arch, self.dirs.root)

    @property
    def _triplet(self):
        if sys.platform == "darwin":
            return "{}-macos".format(self.arch)
        elif sys.platform == "win32":
            return "{}-win".format(self.arch)
        else:
            return "{}-linux-gnu".format(self.arch)

    def add(self, name, build_func=None, wait_on=None, download=None):
        if wait_on is None:
            wait_on = []
        if build_func is None:
            build_func = self.build_default
        self.recipies[name] = {
            "build_func": build_func,
            "wait_on": wait_on,
            "download": download
            if download is None
            else Download(name, destination=self.downloads, **download),
        }

    def run(self, name, event, build_func, download):
        while event.is_set() is False:
            time.sleep(0.3)

        if not self.dirs.build.exists():
            os.makedirs(self.dirs.build, exist_ok=True)

        dirs = Dirs(self.dirs, name, self.arch)
        os.makedirs(dirs.sources, exist_ok=True)
        os.makedirs(dirs.logs, exist_ok=True)
        os.makedirs(dirs.prefix, exist_ok=True)
        logfp = io.open(os.path.join(dirs.logs, "{}.log".format(name)), "w")

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
            env = os.environ
        else:
            env = {
                "PATH": os.environ["PATH"],
            }

        env["MAYFLOWER_HOST"] = self.triplet
        env["MAYFLOWER_ARCH"] = self.arch
        if self.arch != "x86_64":
            env["MAYFLOWER_CROSS"] = str(self.native_python.parent.parent)
            native_root = MODULE_DIR / "_native"
            if not native_root.exists():
                create("_native", MODULE_DIR)
            env["MAYFLOWER_NATIVE_PY"] = native_root / "bin" / "python3"

        self.populate_env(env, dirs)

        logfp.write("*" * 80 + "\n")
        _ = dirs.to_dict()
        for k in _:
            logfp.write("{} {}\n".format(k, _[k]))
        logfp.write("*" * 80 + "\n")
        for k in env:
            logfp.write("{} {}\n".format(k, env[k]))
        logfp.write("*" * 80 + "\n")
        try:
            return build_func(env, dirs, logfp)
        except Exception as exc:
            logfp.write(traceback.format_exc() + "\n")
            sys.exit(1)
        finally:
            os.chdir(cwd)
            logfp.close()

    def cleanup(self):
        shutil.rmtree(self.prefix)

    def clean(self):
        # Clean directories
        for _ in [self.prefix, self.sources]:
            try:
                shutil.rmtree(_)
            except PermissionError:
                sys.stderr.write(f"Unable to remove directory: {_}")
            except FileNotFoundError:
                pass
        # Clean files
        for _ in [self.prefix.with_suffix(".tar.xz")]:
            try:
                os.remove(_)
            except FileNotFoundError:
                pass

    def download_files(self, steps=None):
        if steps is None:
            steps = list(self.recipies)

        fails = []
        processes = {}
        events = {}
        sys.stdout.write("Starting downloads \n")
        print_ui(events, processes, fails)
        for name in steps:
            download = self.recipies[name]["download"]
            if download is None:
                continue
            event = multiprocessing.Event()
            event.set()
            events[name] = event
            proc = multiprocessing.Process(name=name, target=download)
            proc.start()
            processes[name] = proc

        while processes:
            for proc in list(processes.values()):
                proc.join(0.3)
                # DEBUG: Comment to debug
                print_ui(events, processes, fails)
                if proc.exitcode is None:
                    continue
                processes.pop(proc.name)
                if proc.exitcode != 0:
                    fails.append(proc.name)
                    is_failure = True
                else:
                    is_failure = False
        print_ui(events, processes, fails)
        sys.stdout.write("\n")
        if fails:
            print_ui(events, processes, fails)
            sys.stderr.write("The following failures were reported\n")
            for fail in fails:
                sys.stderr.write(fail + "\n")
            sys.stderr.flush()
            sys.exit(1)

    def build(self, steps=None, cleanup=True):
        fails = []
        futures = []
        events = {}
        waits = {}
        processes = {}

        sys.stdout.write("Starting builds\n")
        # DEBUG: Comment to debug
        print_ui(events, processes, fails)

        for name in steps:
            event = multiprocessing.Event()
            events[name] = event
            kwargs = dict(self.recipies[name])

            # Determine needed dependency recipies.
            wait_on = kwargs.pop("wait_on", [])
            for _ in wait_on[:]:
                if _ not in steps:
                    wait_on.remove(_)

            waits[name] = wait_on
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
                # DEBUG: Comment to debug
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
            for fail in fails:
                sys.stderr.write(fail + "\n")
            sys.stderr.flush()
            if cleanup:
                self.cleanup()
            sys.exit(1)
        time.sleep(0.1)
        # DEBUG: Comment to debug
        print_ui(events, processes, fails)
        sys.stdout.write("\n")
        sys.stdout.flush()
        if cleanup:
            self.cleanup()

    def __call__(self, steps=None, arch=None, clean=True, cleanup=True, download=True):
        if arch:
            self.set_arch(arch)

        if steps is None:
            steps = self.recipies

        if clean:
            self.clean()

        # Start a process for each build passing it an event used to notify each
        # process if it's dependencies have finished.
        if download:
            self.download_files(steps)

        self.build(steps, cleanup)


def install_sysdata(mod, destfile, buildroot, toolchain):
    """
    Helper method used by the `finalize` build method to create a Mayflower
    Python environment's sysconfigdata.
    """
    BUILDROOT = str(
        buildroot
    )  # "/home/dan/src/Mayflower/mayflower/_build/x86_64-linux-gnu"
    TOOLCHAIN = str(
        toolchain
    )  # "/home/dan/src/Mayflower/mayflower/_toolchain/x86_64-linux-gnu"
    dest = "sysdata.py"
    data = {}
    buildroot = lambda _: _.replace(BUILDROOT, "{BUILDROOT}")
    toolchain = lambda _: _.replace(TOOLCHAIN, "{TOOLCHAIN}")
    keymap = {
        "BINDIR": (buildroot,),
        "BINLIBDEST": (buildroot,),
        "CFLAGS": (buildroot, toolchain),
        "CPPLAGS": (buildroot, toolchain),
        "CXXFLAGS": (buildroot, toolchain),
        "datarootdir": (buildroot,),
        "exec_prefix": (buildroot,),
        "LDFLAGS": (buildroot, toolchain),
        "LDSHARED": (buildroot, toolchain),
        "LIBDEST": (buildroot,),
        "prefix": (buildroot,),
        "SCRIPTDIR": (buildroot,),
    }
    for key in sorted(mod.build_time_vars):
        val = mod.build_time_vars[key]
        for _ in keymap.get(key, []):
            val = _(val)
        data[key] = val

    with open(destfile, "w", encoding="utf8") as f:
        f.write(
            "# system configuration generated and used by" " the mayflower at runtime\n"
        )
        f.write("build_time_vars = ")
        pprint.pprint(data, stream=f)


def finalize(env, dirs, logfp):
    """
    Run after we've fully built python. This method enhances the newly created
    python with Mayflower's runtime hacks.
    """
    # Run relok8 to make sure the rpaths are relocatable.
    relocate_main(dirs.prefix)
    # Install mayflower-sysconfigdata module
    pymodules = pathlib.Path(dirs.prefix) / "lib" / "python3.10"

    def find_sysconfigdata(pymodules):
        for root, dirs, files in os.walk(pymodules):
            for file in files:
                if file.find("sysconfigdata") > -1 and file.endswith(".py"):
                    return file[:-3]

    cwd = os.getcwd()
    modname = find_sysconfigdata(pymodules)
    path = sys.path
    sys.path = [str(pymodules)]
    try:
        mod = __import__(str(modname))
    finally:
        os.chdir(cwd)
        sys.path = path
    dest = pymodules / "site-packages" / "mayflower-sysconfigdata.py"
    install_sysdata(mod, dest, dirs.prefix, dirs.toolchain)

    # Lay down site customize
    bindir = pathlib.Path(dirs.prefix) / "bin"
    sitecustomize = (
        bindir.parent / "lib" / "python3.10" / "site-packages" / "sitecustomize.py"
    )
    with io.open(str(sitecustomize), "w") as fp:
        fp.write(SITECUSTOMIZE)

    # Lay down mayflower.runtime, we'll pip install the rest later
    mayflowerdir = bindir.parent / "lib" / "python3.10" / "site-packages" / "mayflower"
    os.makedirs(mayflowerdir, exist_ok=True)
    runtime = MODULE_DIR / "runtime.py"
    dest = mayflowerdir / "runtime.py"
    with io.open(runtime, "r") as rfp:
        with io.open(dest, "w") as wfp:
            wfp.write(rfp.read())
    runtime = MODULE_DIR / "common.py"
    dest = mayflowerdir / "common.py"
    with io.open(runtime, "r") as rfp:
        with io.open(dest, "w") as wfp:
            wfp.write(rfp.read())
    init = mayflowerdir / "__init__.py"
    init.touch()

    # Install pip
    python = dirs.prefix / "bin" / "python3"
    if env["MAYFLOWER_ARCH"] != "x86_64":
        env["MAYFLOWER_CROSS"] = dirs.prefix
        python = env["MAYFLOWER_NATIVE_PY"]
    runcmd(
        [python, "-m", "ensurepip"],
        env=env,
        stderr=logfp,
        stdout=logfp,
    )

    # XXX Is fixing shebangs still needed?
    # Fix the shebangs in python's scripts.
    bindir = pathlib.Path(dirs.prefix) / "bin"
    pyex = bindir / "python3.10"
    shebang = "#!{}".format(str(pyex))
    for root, _dirs, files in os.walk(str(bindir)):
        # print(root), print(dirs), print(files)
        for file in files:
            with open(os.path.join(root, file), "rb") as fp:
                try:
                    data = fp.read(len(shebang.encode())).decode()
                except UnicodeError as exc:
                    continue
                except Exception as exc:
                    print("Unhandled exception: {}".format(exc))
                    continue
                if data == shebang:
                    pass
                    # print(file)
                    # print(repr(data))
                else:
                    # print("skip: {}".format(file))
                    continue
                data = fp.read().decode()
            with open(os.path.join(root, file), "w") as fp:
                fp.write("#!/bin/sh\n")
                fp.write('"exec" "`dirname $0`/python3" "$0" "$@"')
                fp.write(data)

    def runpip(pkg, upgrade=False):
        target = None
        # XXX This needs to be more robust
        python = dirs.prefix / "bin" / "python3"
        pip = dirs.prefix / "bin" / "pip3"
        if sys.platform == "linux":
            if env["MAYFLOWER_ARCH"] != "x86_64":
                target = dirs.prefix / "lib" / "python3.10" / "site-packages"
                python = env["MAYFLOWER_NATIVE_PY"]
                # pip = pathlib.Path(env["MAYFLOWER_NATIVE_PY"]).parent / "pip3"
                # pip = dirs.prefix / "bin" / "pip3"
        cmd = [
            str(python),
            str(pip),
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
    # an installed Mayflower
    if (MODULE_DIR.parent / ".git").exists():
        runpip(MODULE_DIR.parent, upgrade=True)
    else:
        runpip("mayflower", upgrade=True)
    globs = [
        "/bin/python*",
        "/bin/pip*",
        "/lib/python3.10/site-packages/*",
        "/include/*",
        "*.so",
        "/lib/*.so.*",
        "*.a",
        "*.py",
        # Mac specific, factor this out
        "*.dylib",
    ]
    archive = dirs.prefix.with_suffix(".tar.xz")
    with tarfile.open(archive, mode="w:xz") as fp:
        create_archive(fp, dirs.prefix, globs, logfp)


def create_archive(tarfp, toarchive, globs, logfp=None):
    """
    Create an archive
    """
    logfp.write(f"CURRENT DIR {os.getcwd()}")
    if logfp:
        logfp.write(f"Creating archive {tarfp.name}\n")
    for root, _dirs, files in os.walk(toarchive):
        relroot = pathlib.Path(root).relative_to(toarchive)
        for f in files:
            relpath = relroot / f
            matches = False
            for g in globs:
                if glob.fnmatch.fnmatch("/" / relpath, g):
                    matches = True
                    break
            if matches:
                if logfp:
                    logfp.write("Adding {}\n".format(relpath))
                tarfp.add(relpath, relpath, recursive=False)
            else:
                if logfp:
                    logfp.write("Skipping {}\n".format(relpath))


def run_build(builder, args):
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    random.seed()
    builder.set_arch(args.arch)
    steps = None
    if args.steps:
        steps = [_.strip() for _ in args.steps.split(",")]
    builder(
        steps=steps,
        arch=args.arch,
        clean=args.clean,
        cleanup=args.no_cleanup,
        download=not args.no_download,
    )
