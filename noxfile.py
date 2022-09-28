"""
Nox session definitions
"""


import datetime
import os
import pathlib
import sys

# fmt: off
if __name__ == "__main__":
    sys.stderr.write(
        "Do not execute this file directly. Use nox instead, it will know how to handle this file\n"
    )
    sys.stderr.flush()
    exit(1)
# fmt: on

import nox  # isort:skip

# Be verbose when runing under a CI context
CI_RUN = os.environ.get("CI") is None
PIP_INSTALL_SILENT = CI_RUN is False
SKIP_REQUIREMENTS_INSTALL = os.environ.get("SKIP_REQUIREMENTS_INSTALL", "0") == "1"

# Global Path Definitions
REPO_ROOT = pathlib.Path(os.path.dirname(__file__)).resolve()
os.chdir(str(REPO_ROOT))

ARTIFACTS_DIR = REPO_ROOT / "artifacts"

# Nox options
#  Reuse existing virtualenvs
nox.options.reuse_existing_virtualenvs = True
#  Don't fail on missing interpreters
nox.options.error_on_missing_interpreters = False

PYTEST_LOGFILE = ARTIFACTS_DIR.joinpath(
    "logs",
    "pytest-{}.log".format(datetime.datetime.now().strftime("%Y%m%d%H%M%S.%f")),
)

# Prevent Python from writing bytecode
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


# <---------------------- SESSIONS ---------------------->


@nox.session
def tests(session):
    session.install("pytest")
    run_pytest_session(session)


# <---------------------- HELPERS ---------------------->
def run_pytest_session(session, *cmd_args):
    make_artifacts_directory()
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


def make_artifacts_directory():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.chmod(0o777)
