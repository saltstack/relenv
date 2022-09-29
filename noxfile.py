"""
Nox session definitions
"""


import datetime
import os
import pathlib
import sys

import nox  # isort:skip

SKIP_REQUIREMENTS_INSTALL = os.environ.get("SKIP_REQUIREMENTS_INSTALL", "0") == "1"

# Global Path Definitions
REPO_ROOT = pathlib.Path(os.path.dirname(__file__)).resolve()
os.chdir(str(REPO_ROOT))

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PYTEST_LOGFILE = ARTIFACTS_DIR.joinpath(
    "logs",
    "pytest-{}.log".format(datetime.datetime.now().strftime("%Y%m%d%H%M%S.%f")),
)

# Nox options
#  Reuse existing virtualenvs
nox.options.reuse_existing_virtualenvs = True
#  Don't fail on missing interpreters
nox.options.error_on_missing_interpreters = False


# Prevent Python from writing bytecode
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


# <---------------------- SESSIONS ---------------------->
@nox.session
def tests(session):
    run_pytest_session(session)


@nox.session
@nox.parametrize("arch", ("x86_64", "aarch64"))
def build(session, arch):
    invoke_mayflower(session, "toolchain", "download", f"--arch={arch}")
    invoke_mayflower(session, "build", f"--arch={arch}")


@nox.session
@nox.parametrize("arch", ("x86_64", "aarch64"))
def toolchain(session, arch):
    invoke_mayflower(session, "toolchain", "build", f"--arch={arch}")


# Convenience sessions
@nox.session
def build_x86_64(session):
    session.notify("build(arch='x86_64')")


@nox.session
def build_aarch64(session):
    session.notify("build(arch='aarch64')")


@nox.session
def toolchain_x86_64(session):
    session.notify("toolchain(arch='x86_64')")


@nox.session
def toolchain_aarch64(session):
    session.notify("toolchain(arch='aarch64')")


# <---------------------- HELPERS ---------------------->
def run_pytest_session(session, *cmd_args):
    make_artifacts_directory()

    if not SKIP_REQUIREMENTS_INSTALL:
        session.install("pytest")

    default_args = [
        "-vv",
        "--showlocals",
        "--show-capture=no",
        "-ra",
        "-s",
        "--log-file-level=debug",
    ]

    # check for --log-file
    for arg in cmd_args:
        if arg.startswith("--log-file"):
            break
    else:
        default_args.append(f"--log-file={PYTEST_LOGFILE}")

    pytest_args = default_args + list(cmd_args)
    session.run("python", "-m", "pytest", *pytest_args)


def invoke_mayflower(session, *cmd_args):
    session.run("python", "-m", "mayflower", *cmd_args)


def make_artifacts_directory():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.chmod(0o777)
