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

class WorkDirs:
    def __init__(self, root):
        self.root = root
        self.toolchain = work_dir("toolchain", self.root)
        self.build = work_dir("build", self.root)
        self.src = work_dir("src", self.root)
        self.logs = work_dir("logs", self.root)
        self.download = work_dir("download", self.root)

    def __getstate__(self):
        return {
            'root': self.root,
            'toolchain': self.toolchain,
            'build': self.build,
            'src': self.src,
            'logs': self.logs,
            'download': self.download,
        }

    def __setstate__(self, state):
        self.root = state['root']
        self.toolchain = state['toolchain']
        self.build = state['build']
        self.src = state['src']
        self.logs = state['logs']
        self.download = state['download']



def work_dirs(root=None):
    return WorkDirs(work_root(root))


def get_toolchain(arch=None, root=None):
    dirs = work_dirs(root)
    if arch:
        return dirs.toolchain / "{}-linux-gnu".format(arch)
    return dirs.toolchain

