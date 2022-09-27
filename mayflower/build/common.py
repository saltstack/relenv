import logging
import os.path
import codecs
import hashlib
import pathlib
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

from ..common import MODULE_DIR, work_root, work_dirs, get_toolchain
from ..relocate import main as relocate_main

log = logging.getLogger(__name__)
sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

PIPE=subprocess.PIPE

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
END = "\033[0m"
MOVEUP = "\033[F"


CICD = False
NODOWLOAD= False
WORK_IN_CWD = False

def get_build():
    if WORK_IN_CWD:
        base = pathlib.Path("build").resolve()
    else:
        base = MODULE_DIR / "_build"
    return base


def print_ui(events, processes, fails, flipstat={}):
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
            status = " {}{}".format(GREEN, ' ' if flipstat[name][0] == 1 else '.')
        elif name in fails:
            status = " {}\u2718".format(RED)
        else:
            status = " {}\u2718".format(GREEN)
        uiline.append(status)
    uiline.append("  " + END)
    sys.stdout.write("\r")
    sys.stdout.write("".join(uiline))
    sys.stdout.flush()

def xprint_ui(events, processes, fails, flipstat={}, first=False):
    uiline = []
    for name in events:
        if not events[name].is_set():
            status = "{}{} .".format(name, YELLOW)
        elif name in processes:
            now = time.time()
            if name not in flipstat:
                flipstat[name] = (0, now)
            if flipstat[name][1] < now:
                flipstat[name] = (1 - flipstat[name][0], now + random.random())
            status = "{}{} {}".format(GREEN, name, ' ' if flipstat[name][0] == 1 else '.')
        elif name in fails:
            status = "{}{} \u2718".format(RED, name)
        else:
            status = "{}{} \u2718".format(GREEN, name)
        uiline.append(status)

    if first is not False:
        sys.stdout.write(MOVEUP)
        for i in uiline:
            sys.stdout.write(MOVEUP)

    sys.stdout.write("\n" + "\n".join(uiline) + END + "\n")
    sys.stdout.flush()

def runcmd(*args, **kwargs):
    proc = subprocess.run(*args, **kwargs)
    if proc.returncode != 0:
        raise Exception("Build cmd '{}' failed".format(" ".join(args[0])))
    return proc

def download_url(url, dest):
    local = os.path.join(dest, os.path.basename(url))
    n = 0
    while n < 3:
        n += 1
        try:
            fin = urllib.request.urlopen(url)
        except urllib.error.HTTPError as exc:
            if n == 3:
                raise
            print("Unable to download: %s %r".format(url, exc))
            time.sleep(n + 1)
    fout = open(local, 'wb')
    block = fin.read(10240)
    try:
        while block:
            fout.write(block)
            block = fin.read(10240)
        fin.close()
        fout.close()
    except:
        try:
            os.unlink(local)
        except OSError:
            pass
        raise
    return local

def verify_checksum(file, checksum):
    if checksum is None:
        return
    with open(file, 'rb') as fp:
        if checksum != hashlib.md5(fp.read()).hexdigest():
            raise Exception("md5 checksum verification failed")

def extract_archive(to_dir, archive):
    if archive.endswith("tgz"):
        read_type = "r:gz"
    elif archive.endswith("xz"):
        read_type = "r:xz"
    elif archive.endswith("bz2"):
        read_type = "r:bz2"
    else:
        read_type = "r"
    with tarfile.open(archive, read_type) as t:
        t.extractall(to_dir)


def all_dirs(root, recurse=True):
    paths = [root]
    for root, dirs, files in os.walk(root):
        for name in dirs:
            paths.append(os.path.join(root, name))
    return paths

def _parse_gcc_version(stdout):
    vline  = stdout.splitlines()[0]
    vline, vstr = [_.strip() for _ in vline.rsplit(" ", 1)]
    if vstr.find(".") != -1:
        return vstr
    return vline.rsplit(" ", 1)[1].strip()


def gcc_version(cc):
    proc = runcmd([cc, "--version"], stderr=PIPE, stdout=PIPE)
    return _parse_gcc_version(proc.stdout.decode())

def _parse_kernel_version(stdout):
    stdout = stdout.split('-', 1)[0]
    return ".".join(stdout.split('.')[:3])

def kernel_version():
    proc = runcmd(["uname", "-r"], stderr=PIPE, stdout=PIPE)
    return _parse_kernel_version(proc.stdout.decode())

def populate_env(dirs, env):
    pass

def build_default(env, dirs, logfp):
    cmd = [
        './configure',
        "--prefix={}".format(dirs.prefix),
    ]
    if env["MAYFLOWER_HOST"].find('linux') > -1:
        cmd += [
            "--build=x86_64-linux-gnu",
            "--host={}".format(env["MAYFLOWER_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

def build_openssl(env, dirs, logfp):
    arch = "aarch64"
    if sys.platform == 'darwin':
        plat = 'darwin64'
        if env["MAYFLOWER_ARCH"] == 'x86_64':
            arch = 'x86_64-cc'
    else:
        plat = 'linux'
        if env["MAYFLOWER_ARCH"] == 'x86_64':
            arch = 'x86_64'
        elif env["MAYFLOWER_ARCH"] == 'aarch64':
            arch = "aarch64"
    runcmd([
        './Configure',
        "{}-{}".format(plat, arch),
        "no-idea",
        "shared",
        "--prefix={}".format(dirs.prefix),
        #"--openssldir={}/ssl".format(dirs.prefix),
        "--openssldir=/tmp/ssl",
        ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install_sw"], env=env, stderr=logfp, stdout=logfp)


def build_sqlite(env, dirs, logfp):
    #extra_cflags=('-Os '
    #              '-DSQLITE_ENABLE_FTS5 '
    #              '-DSQLITE_ENABLE_FTS4 '
    #              '-DSQLITE_ENABLE_FTS3_PARENTHESIS '
    #              '-DSQLITE_ENABLE_JSON1 '
    #              '-DSQLITE_ENABLE_RTREE '
    #              '-DSQLITE_TCL=0 '
    #              )
    #configure_pre=[
    #    '--enable-threadsafe',
    #    '--enable-shared=no',
    #    '--enable-static=yes',
    #    '--disable-readline',
    #    '--disable-dependency-tracking',
    #]
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
    if env["MAYFLOWER_HOST"].find('linux') > -1:
        cmd += [
            "--build=x86_64-linux-gnu",
            "--host={}".format(env["MAYFLOWER_HOST"]),
        ]
    runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)


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
            'name': self.name,
            'arch': self.arch,
            'root': self.root,
            'build': self.build,
            'downloads': self.downloads,
            'logs': self.logs,
            'sources': self.sources,
            'tmpbuild': self.tmpbuild,
        }

    def __setstate__(self, state):
        self.name = state['name']
        self.arch = state['arch']
        self.root = state['root']
        self.downloads = state['downloads']
        self.logs = state['logs']
        self.sources = state['sources']
        self.build = state['build']
        self.tmpbuild = state['tmpbuild']

    def to_dict(self):
        return { x: getattr(self, x) for x in [
            "root", "prefix", "downloads", "logs", "sources", "build",
             "toolchain",
            ]
        }


class Builder:

    def __init__(self, root=None, recipies=None, build_default=build_default, populate_env=populate_env, no_download=False, arch='x86_64'):
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
            return self.dirs.build / "x86_64-win" / "bin" / "python"
        else:
            return self.dirs.build / "x86_64-linux-gnu" / "bin" / "python3"

    def set_arch(self, arch):
        self.arch = arch
        if sys.platform == "darwin":
            self.triplet = "{}-macos".format(self.arch)
            self.prefix = self.dirs.build / "{}-macos".format(self.arch)
            #XXX Not used for MacOS
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

    def add(self, name, url, checksum, build_func=None, wait_on=None):
        if wait_on is None:
            wait_on = []
        if build_func is None:
            build_func = self.build_default
        self.recipies[name] = {
            'url': url,
            "checksum": checksum,
            "build_func": build_func,
            "wait_on": wait_on,
        }

    def run(self, name, event, url, checksum, build_func):
        while event.is_set() is False:
            time.sleep(.3)

        if not self.dirs.build.exists():
            os.makedirs(self.dirs.build, exist_ok=True)

        dirs = Dirs(self.dirs, name, self.arch)
        state = dirs.__getstate__()
        dirs.__setstate__(state)

        os.makedirs(dirs.sources, exist_ok=True)
        os.makedirs(dirs.downloads, exist_ok=True)
        os.makedirs(dirs.logs, exist_ok=True)
        os.makedirs(dirs.prefix, exist_ok=True)
        logfp = io.open(os.path.join(dirs.logs, "{}.log".format(name)), "w")

        # DEBUG: Uncomment to debug
        # logfp = sys.stdout

        #XXX should separate downloads and builds.
        if self.no_download:
            archive = os.path.join(dirs.downloads, os.path.basename(url))
        else:
            archive = download_url(url, dirs.downloads)
        verify_checksum(archive, checksum)
        extract_archive(dirs.sources, archive)
        dirs.source = dirs.sources / pathlib.Path(archive).name.split('.tar')[0]

        cwd = os.getcwd()
        os.chdir(dirs.source)
        if sys.platform == "win32":
            env = os.environ
            env["MAYFLOWER_HOST"] = self.triplet
            env["MAYFLOWER_ARCH"] = self.arch
        else:
            env = {
                "PATH": os.environ["PATH"],
                "MAYFLOWER_HOST": self.triplet,
                "MAYFLOWER_ARCH": self.arch,
            }
        self.populate_env(env, dirs)

        logfp.write("*" * 80 + "\n")
        _  = dirs.to_dict()
        for k in _:
            logfp.write("{} {}\n".format(k, _[k]))
        logfp.write("*" * 80 + "\n")
        for k in env:
            logfp.write("{} {}\n".format(k, env[k]))
        logfp.write("*" * 80 + "\n")
        try:
            return build_func(env, dirs, logfp)
        except Exception as exc:
            logfp.write(traceback.format_exc()+ "\n")
            sys.exit(1)
        finally:
            os.chdir(cwd)
            logfp.close()


# XXX This can be removed.
#PIP_WRAPPER="""#!/bin/sh
#"exec" "`dirname $0`/python3" "$0" "$@"
## -*- coding: utf-8 -*-
#import re
#import sys
#from pip._internal.cli.main import main
#if __name__ == "__main__":
#    sys.argv[0] = re.sub(r"(-script\.pyw|\.exe)?$", "", sys.argv[0])
#    sys.exit(main())
#"""


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
    pass
else:
    mayflower.runtime.bootstrap()
"""


def install_sysdata(mod, destfile, buildroot, toolchain):
    BUILDROOT = str(buildroot) #"/home/dan/src/Mayflower/mayflower/_build/x86_64-linux-gnu"
    TOOLCHAIN = str(toolchain) #"/home/dan/src/Mayflower/mayflower/_toolchain/x86_64-linux-gnu"
    dest = 'sysdata.py'
    data = {}
    buildroot = lambda _ : _.replace(BUILDROOT, "{BUILDROOT}")
    toolchain = lambda _ : _.replace(TOOLCHAIN, "{TOOLCHAIN}")
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

    with open(destfile, 'w', encoding='utf8') as f:
        f.write('# system configuration generated and used by'
                ' the mayflower at runtime\n')
        f.write('build_time_vars = ')
        pprint.pprint(data, stream=f)


def run_build(builder, argparser):
    random.seed()
    argparser.descrption = "Build Mayflower Python Environments"
    argparser.add_argument(
        "--arch", default="x86_64", type=str,
        help="The host architecture [default: x86_64]"
    )
    argparser.add_argument(
        "--clean", default=False, action="store_true",
        help="Clean up before running the build"
    )
    #XXX We should automatically skip downloads that can be verified as not
    #being corrupt and this can become --force-download
    argparser.add_argument(
        "--no-download", default=False, action="store_true",
        help="Skip downloading source tarballs"
    )
    ns, argv = argparser.parse_known_args()
    if getattr(ns, "help", None):
        argparser.print_help()
        sys.exit(0)
    global CICD
    if 'CICD' in os.environ:
        CICD = True
    builder.set_arch(ns.arch)
    if ns.clean:
      try:
          shutil.rmtree(builder.prefix)
          shutil.rmtree(builder.sources)
      except FileNotFoundError: pass
    builder.no_download = False
    if ns.no_download:
        builder.no_download = True

    import concurrent.futures

    fails = []
    futures = []
    events = {}
    waits = {}
    processes = {}

    # Start a process for each build passing it an event used to notify each
    # process if it's dependencies have finished.
    if "RUN" in os.environ:
        run = [_.strip() for _ in os.environ["RUN"].split(",") if _.strip()]
    else:
        run = builder.recipies
    for name in run:
        event = multiprocessing.Event()
        events[name] = event
        kwargs = dict(builder.recipies[name])
        waits[name] = kwargs.pop('wait_on', [])
        if not waits[name]:
            event.set()
        proc = multiprocessing.Process(name=name, target=builder.run, args=(name, event), kwargs=kwargs)
        proc.start()
        processes[name] = proc

    sys.stdout.write("\n")
    # DEBUG: Comment to debug
    print_ui(events, processes, fails)

    # Wait for the processes to finish and check if we should send any
    # dependency events.
    while processes:
        for proc in list(processes.values()):
            proc.join(.3)
            # DEBUG: Comment to debug
            print_ui(events, processes, fails)
            if proc.exitcode is None:
                continue
            processes.pop(proc.name)
            if proc.exitcode != 0:
                fails.append(proc.name)
                is_failure=True
            else:
                is_failure=False
            for name in waits:
                if proc.name in waits[name]:
                    if is_failure:
                        if name in processes:
                            processes[name].terminate()
                            time.sleep(.1)
                    waits[name].remove(proc.name)
                if not waits[name] and not events[name].is_set():
                    events[name].set()


    if fails:
        sys.stderr.write("The following failures were reported\n")
        for fail in fails :
            sys.stderr.write(fail + "\n")
        sys.stderr.flush()
        sys.exit(1)
    time.sleep(.1)
    # DEBUG: Comment to debug
    print_ui(events, processes, fails)
    sys.stdout.write("\n")
    sys.stdout.flush()

    # Run relok8 to make sure the rpaths are relocatable.
    builder.dirs.logs.mkdir(exist_ok=True, parents=True)
    logfp = io.open(str(builder.dirs.logs / "relok8.py.log"), "w")
    relocate_main(builder.prefix)

    # Fix the shebangs in python's scripts.
    if sys.platform == "win32":
        bindir = pathlib.Path(builder.prefix) / "Scripts"
    else:
        bindir = pathlib.Path(builder.prefix) / "bin"
    pyex = bindir / "python3.10"
    shebang = "#!{}".format(str(pyex))
    for root, dirs, files in os.walk(str(bindir)):
        #print(root), print(dirs), print(files)
        for file in files:
            with open(os.path.join(root, file), "rb") as fp:
                try:
                    data = fp.read(len(shebang.encode())).decode()
                except:
                    #print("skip: {}".format(file))
                    continue
                if data == shebang:
                    pass
                    #print(file)
                    #print(repr(data))
                else:
                    #print("skip: {}".format(file))
                    continue
                data = fp.read().decode()
            with open(os.path.join(root, file), "w") as fp:
                fp.write("#!/bin/sh\n")
                fp.write('"exec" "`dirname $0`/python3" "$0" "$@"')
                fp.write(data)

    # Install mayflower-sysconfigdata module
    if sys.platform != "win32":
        pymodules = pathlib.Path(builder.prefix) / "lib" / "python3.10"
        def find_sysconfigdata(pymodules):
            for root, dirs, files in os.walk(pymodules):
                for file in files:
                    if file.find('sysconfigdata') > -1 and file.endswith(".py"):
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
        install_sysdata(mod, dest, builder.prefix, builder.toolchain)

    # Lay down site customize
    if sys.platform == "win32":
        sitecustomize = bindir.parent / "Lib" / "site-packages" / "sitecustomize.py"
        mayflowerdir = bindir.parent / "Lib" / "site-packages" / "mayflower"
        python = bindir.parent / "python.exe"
    else:
        sitecustomize = bindir.parent / "lib" / "python3.10" / "site-packages" / "sitecustomize.py"
        mayflowerdir = bindir.parent / "lib" / "python3.10" / "site-packages" / "mayflower"
        python = builder.prefix / "bin" / "python3"
    with io.open(str(sitecustomize), "w") as fp:
        fp.write(SITECUSTOMIZE)

    # Lay down mayflower.runtime, we'll pip install the rest later
    if os.makedirs(mayflowerdir):
        runtime = MODULE_DIR / "runtime.py"
        dest = mayflowerdir / "runtime.py"
        with io.open(runtime, "r") as rfp:
            with io.open(dest, "r") as wfp:
                wfp.write(rfp.read())
    init = mayflowerdir / "__init__.py"
    init.touch()

    #MAYFLOWERCROSS=mayflower/_build/aarch64-linux-gnu  mayflower/_build/x86_64-linux-gnu/bin/python3 -m ensurepip
    env = os.environ.copy()
    if builder.arch == "aarch64":
        python = pathlib.Path(builder.prefix).parent / "x86_64-linux-gnu" / "bin" / "python3"
        env["MAYFLOWERCROSS"] = builder.prefix
    runcmd([str(python), "-m", "ensurepip"], env=env, stderr=logfp, stdout=logfp)

    # Install our pip wrapper
    #for file in ["pip3", "pip3.10"]:
    #    path = bindir / file
    #    with io.open(str(path), "w") as fp:
    #        fp.write(PIP_WRAPPER)
    #    os.chmod(path, 0o744)

    def runpip(pkg):
        pip = bindir / "pip3"
        env = os.environ.copy()
        target = None
        #XXX This needs to be more robust
        if sys.platform == "linux":
            if builder.arch != "x86_64":
                env["MAYFLOWER_CROSS"] = str(builder.native_python.parent.parent)
                target = pip.parent.parent / "lib" / "python3.10" / "site-packages"
        if sys.platform == "win32":
            cmd = [str(pip), "install", str(pkg)]
        else:
            cmd = [
                str(builder.native_python),
                str(pip),
                "install",
                str(pkg),
            ]
        if target:
            cmd.append("--target={}".format(target))
        runcmd(cmd, env=env, stderr=logfp, stdout=logfp)
    runpip("wheel")

    # This needs to handle running from the root of the git repo and also from
    # an installed Mayflower
    if (MODULE_DIR.parent / ".git").exists():
        runpip(MODULE_DIR.parent)
    else:
        runpip("mayflower")
