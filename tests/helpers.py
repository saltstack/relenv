import pathlib
import shutil

class BaseProject:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.libs_dir = self.root_dir / "lib"

    def make_project(self):
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.libs_dir.mkdir(parents=True, exist_ok=True)

    def destroy_project(self):
        # Make sure the project is torn down properly
        if pathlib.Path(self.root_dir).exists():
            shutil.rmtree(self.root_dir, ignore_errors=True)

    def add_file(self, name, contents, *relpath, binary=False):
        file_path = (self.root_dir / pathlib.Path(*relpath) / name).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            file_path.write_bytes(contents)
        else:
            file_path.write_text(contents)
        return file_path

    def __enter__(self):
        self.make_project()
        return self

    def __exit__(self, *exc):
        self.destroy_project()


class LinuxProject(BaseProject):
    def add_simple_elf(self, name, *relpath):
        return self.add_file(name, b"\x7f\x45\x4c\x46", *relpath, binary=True)
