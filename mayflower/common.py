import os, pathlib

MODULE_DIR = pathlib.Path(__file__).resolve().parent
WORK_IN_CWD = False

def work_root(root=None):
    if root is not None:
        base = pathlib.Path(root).resolve()
    elif WORK_IN_CWD:
        base = pathlib.Path(os.getcwd()).resolve()
    else:
        base = MODULE_DIR
    return base


def work_dir(name, root=None):
    root = work_root(root)
    if root == MODULE_DIR:
        base = root / "_{}".format(name)
    else:
        base = root / name
    return base


def work_dirs(root=None):
    _root = root
    class dirs:
        root = work_root(_root)
        toolchain = work_dir("toolchain", _root)
        build = work_dir("build", _root)
        src = work_dir("src", _root)
        logs = work_dir("logs", _root)
        download = work_dir("download", _root)
    return dirs


def get_toolchain(arch=None, root=None):
    dirs = work_dirs(root)
    if arch:
        return dirs.toolchain / "{}-linux-gnu".format(arch)
    return dirs.toolchain

