import logging
import os.path
import codecs
import hashlib
import pathlib
import shutil
import tempfile
import time
import traceback
import subprocess
import random
import sys
import io
import os
import platform
import urllib.request as urllib_request
import multiprocessing

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
    fin = urllib_request.urlopen(url)
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
            os.unlink(name)
        except OSError:
            pass
    return local

def verify_checksum(file, checksum):
    if checksum is None:
        return
    with open(file, 'rb') as fp:
        if checksum != hashlib.md5(fp.read()).hexdigest():
            raise Exception("md5 checksum verification failed")

def extract_archive(todir, archive):
    proc = subprocess.run(["tar", "-C", todir, "-xf", archive], stderr=PIPE, stdout=PIPE)
    if proc.returncode != 0:
        raise Exception("Extracting archive failed {}".format(proc.stderr))

def all_dirs(root, recurse=True):
    paths = [root]
    for root, dirs, files in os.walk(root):
        for name in dirs:
            paths.append(os.path.join(root, name))
    return paths

def build_default(env, dirs, logfp):
    runcmd([
        './configure',
        "--prefix={}".format(dirs.prefix),
    ], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "-j8"], env=env, stderr=logfp, stdout=logfp)
    runcmd(["make", "install"], env=env, stderr=logfp, stdout=logfp)

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

class Builder:

    def __init__(self, install_dir='build', recipies=None, build_default=build_default, populate_env=populate_env):
        self.install_dir = str(pathlib.Path(install_dir).resolve())
        if recipies is None:
            self.recipies = {}
        else:
            self.recipies = recipies
        self.build_default = build_default
        self.populate_env = populate_env

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

        class dirs:
            cwd = pathlib.Path(os.getcwd())
            prefix = cwd / self.install_dir
            # This directory is only used to build the environment. We link
            # against the glibc headers but at runtime the system glibc is
            # used.
            glibc = prefix / "glibc"
            downloads = cwd / "download"
            logs = cwd / "logs"
            sources = cwd / "src"
            build = tempfile.mkdtemp(prefix="{}_build".format(name))

        logs = str(pathlib.Path('logs').resolve())
        os.makedirs(dirs.sources, exist_ok=True)
        os.makedirs(dirs.downloads, exist_ok=True)
        os.makedirs(logs, exist_ok=True)
        logfp = io.open(os.path.join(logs, "{}.log".format(name)), "w")
        #XXX should separate downloads and builds.
        #archive = os.path.join(dirs.downloads, os.path.basename(url))
        archive = download_url(url, dirs.downloads)
        verify_checksum(archive, checksum)
        extract_archive(dirs.sources, archive)
        dirs.source = dirs.sources / pathlib.Path(archive).name.split('.tar')[0]

        _ = os.getcwd()
        os.chdir(dirs.source)
        env = {}
        env["PATH"] = os.environ["PATH"]
        self.populate_env(dirs, env)
        try:
            return build_func(env, dirs, logfp)
        except Exception as exc:
            logfp.write(traceback.format_exc()+ "\n")
            sys.exit(1)
        finally:
            os.chdir(_)
            logfp.close()

PIP_WRAPPER="""#!/bin/sh
"exec" "`dirname $0`/python3" "$0" "$@"
import os
import re
import sys

bin_path = os.path.dirname(os.path.abspath(__file__))
if bin_path.endswith("bin"):
    prefix_path = os.path.dirname(bin_path)
else:
    prefix_path = bin_path


# Pin to the python in our directory
sys.prefix = prefix_path
sys.exec_prefix = prefix_path

# Remove paths outside of our python location
path = []
for i in list(sys.path):
    if i.startswith(sys.prefix):
        path.append(i)
sys.path = path

# isort: off

from pip._internal.cli.main import main
from pip._vendor.distlib.scripts import ScriptMaker

# isort: on

ScriptMaker.script_template = r\"\"\"# -*- coding: utf-8 -*-
import os
import re
import sys

bin_path = os.path.dirname(os.path.abspath(__file__))
if bin_path.endswith("bin"):
    prefix_path = os.path.dirname(bin_path)
else:
    prefix_path = bin_path

# Pin to the python in our directory
sys.prefix = prefix_path
sys.exec_prefix = prefix_path

# Remove paths outside of our python location
path = []
for i in list(sys.path):
    if i.startswith(sys.prefix):
        path.append(i)
sys.path = path

from %(module)s import %(import_name)s
if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw|\.exe)?$', '', sys.argv[0])
    sys.exit(%(func)s())
\"\"\"


if __name__ == "__main__":
    sys.argv[0] = re.sub(r"(-script\.pyw|\.exe)?$", "", sys.argv[0])
    sys.exit(main())
"""


def run_build(builder):
    global CICD
    if 'CICD' in os.environ:
        CICD = True
    random.seed()
    if '--clean' in sys.argv:
      try:
          shutil.rmtree(builder.install_dir)
      except FileNotFoundError: pass

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
    print_ui(events, processes, fails)

    # Wait for the processes to finish and check if we should send any
    # dependency events.
    while processes:
        for proc in list(processes.values()):
            proc.join(.3)
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
    print_ui(events, processes, fails)
    sys.stdout.write("\n")
    sys.stdout.flush()

    # Download and run relok8 to make sure the rpaths are relocatable.
    to = pathlib.Path(builder.install_dir).parent
    download_url("https://raw.githubusercontent.com/dwoz/relok8.py/main/relok8.py", to)
    logfp = io.open(str(pathlib.Path('logs') / "relok8.py.log"), "w")
    runcmd(["python3", "relok8.py", "--root=build", "--libs=build/libs", "--rpath-only"], stderr=logfp, stdout=logfp)

    # Fix the shebangs in python's scripts.
	#sed $(SED_OPTS) 's/^#!.*$$/#!\/bin\/sh\n"exec" "`dirname $$0`\/$(PYBIN)" "$$0" "$$@"/' $(SCRIPTS_DIR)/$@;

    bindir = pathlib.Path(builder.install_dir) / "bin"
    pyex = bindir / "python3.10"
    shebang = "#!{}".format(str(pyex))
    for root, dirs, files in os.walk(str(bindir)):
        #print(root), print(dirs), print(files)
        for file in files:
            with open(os.path.join(root, file), "rb") as fp:
                try:
                    data = fp.read(len(shebang.encode())).decode()
                except:
                    print("skip: {}".format(file))
                    continue
                if data == shebang:
                    print(file)
                    print(repr(data))
                else:
                    print("skip: {}".format(file))
                    continue
                data = fp.read().decode()
            with open(os.path.join(root, file), "w") as fp:
                fp.write("#!/bin/sh\n")
                fp.write('"exec" "`dirname $0`/python3" "$0" "$@"')
                fp.write(data)
    for file in ["pip3", "pip3.10"]:
        path = bindir / file
        with io.open(str(path), "w") as fp:
            fp.write(PIP_WRAPPER)
