# Copyright 2022-2026 Broadcom.
# SPDX-License-Identifier: Apache-2
"""
Nox session definitions.
"""
import datetime
import os
import pathlib

import nox  # isort:skip

CI_RUN = os.environ.get("CI") is not None
PIP_INSTALL_SILENT = CI_RUN is False
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
    invoke_relenv(session, "toolchain", "download", f"--arch={arch}")
    invoke_relenv(session, "build", f"--arch={arch}")


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


@nox.session
def docs(session):
    if not SKIP_REQUIREMENTS_INSTALL:
        session.install(
            "-r",
            str(REPO_ROOT / "requirements" / "docs.txt"),
            silent=PIP_INSTALL_SILENT,
        )

    os.chdir("docs")
    session.run("sphinx-build", "-b", "html", "source", "build")


# <---------------------- HELPERS ---------------------->
def run_pytest_session(session, *cmd_args):
    make_artifacts_directory()

    if not SKIP_REQUIREMENTS_INSTALL:
        session.install(
            "-r",
            str(REPO_ROOT / "requirements" / "tests.txt"),
            silent=PIP_INSTALL_SILENT,
        )

    default_args = [
        "-vv",
        "--showlocals",
        "--show-capture=no",
        "-ra",
        "-s",
        "--log-file-level=debug",
        "--strict-markers",
    ]

    # check for --log-file
    for arg in cmd_args:
        if arg.startswith("--log-file"):
            break
    else:
        default_args.append(f"--log-file={PYTEST_LOGFILE}")

    pytest_args = default_args + list(cmd_args) + session.posargs
    env = {}
    if "RELENV_DATA" in os.environ:
        env["RELENV_DATA"] = os.environ["RELENV_DATA"]
    session.run("python", "-m", "pytest", *pytest_args, env=env)


def invoke_relenv(session, *cmd_args):
    session.run("python", "-m", "relenv", *cmd_args)


def make_artifacts_directory():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.chmod(0o777)
