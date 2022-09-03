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
    return ".".join(stdout.decode().split('.')[:3])

def kernel_version():
    proc = runcmd(["uname", "-r"], stderr=PIPE, stdout=PIPE)
    return _parse_kernel_version(proc.stdout)

def populate_env(dirs, env):
    pass

class Builder:

    def __init__(self, install_dir='build', recipies=None, build_default=build_default, populate_env=populate_env):
        self.install_dir = install_dir
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
            sources = prefix / "src"
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


def run_build(builder):
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
