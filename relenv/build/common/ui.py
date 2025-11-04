# Copyright 2022-2025 Broadcom.
# SPDX-License-Identifier: Apache-2.0
"""
UI and build statistics utilities.
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
import threading
from typing import Dict, MutableMapping, Optional, Sequence, cast

import multiprocessing

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event as SyncEvent
else:
    SyncEvent = None

from relenv.common import DATA_DIR

from .download import CICD


log = logging.getLogger(__name__)


# ANSI color codes for terminal output
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
END = "\033[0m"
MOVEUP = "\033[F"


# Detect terminal capabilities for Unicode vs ASCII output
USE_UNICODE = True

# Allow forcing ASCII mode via environment variable (useful for testing/debugging)
if os.environ.get("RELENV_ASCII"):
    USE_UNICODE = False
elif sys.platform == "win32":
    # Check if we're in a modern terminal that supports Unicode
    # Windows Terminal and modern PowerShell support Unicode
    wt_session = os.environ.get("WT_SESSION")
    term_program = os.environ.get("TERM_PROGRAM")
    if not wt_session and not term_program:
        # Likely cmd.exe or old PowerShell, use ASCII
        USE_UNICODE = False


# Spinner frames for in-progress builds
if USE_UNICODE:
    # Modern Unicode spinner (looks great in most terminals)
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    SYMBOL_PENDING = "◯"
    SYMBOL_RUNNING = None  # Will use spinner
    SYMBOL_SUCCESS = "✓"
    SYMBOL_FAILED = "✗"
else:
    # ASCII fallback for Windows cmd.exe
    SPINNER_FRAMES = ["|", "/", "-", "\\"]
    SYMBOL_PENDING = "o"
    SYMBOL_RUNNING = None  # Will use spinner
    SYMBOL_SUCCESS = "+"
    SYMBOL_FAILED = "X"


# Build statistics filename (path computed at runtime)
BUILD_STATS_FILENAME = "build_stats.json"


def _get_build_stats_file() -> pathlib.Path:
    """Get the path to the build statistics file.

    Returns:
        Path to build_stats.json in the relenv data directory.

    Note:
        This is a function rather than a module-level constant to avoid
        import-time dependencies on DATA_DIR, following CPython conventions.
    """
    return DATA_DIR / BUILD_STATS_FILENAME


class SpinnerState:
    """Thread-safe spinner state management.

    Tracks the animation frame index for each named spinner to ensure
    smooth, consistent animation across multiple UI updates.
    """

    def __init__(self) -> None:
        """Initialize empty spinner state with thread safety."""
        self._state: Dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> int:
        """Get the current frame index for a named spinner.

        Args:
            name: The spinner identifier

        Returns:
            The current frame index (0 if spinner hasn't been used yet)
        """
        with self._lock:
            return self._state.get(name, 0)

    def increment(self, name: str) -> None:
        """Increment the frame index for a named spinner.

        Args:
            name: The spinner identifier
        """
        with self._lock:
            self._state[name] = self._state.get(name, 0) + 1

    def reset(self, name: Optional[str] = None) -> None:
        """Reset spinner state.

        Args:
            name: The spinner to reset, or None to reset all spinners
        """
        with self._lock:
            if name is None:
                self._state.clear()
            elif name in self._state:
                del self._state[name]


# Module-level spinner state instance
_spinner_state = SpinnerState()


class BuildStats(TypedDict):
    """Structure for tracking build step statistics."""

    avg_lines: int
    samples: int
    last_lines: int


def print_ui(
    events: MutableMapping[str, "multiprocessing.synchronize.Event"],
    processes: MutableMapping[str, multiprocessing.Process],
    fails: Sequence[str],
    flipstat: Optional[Dict[str, tuple[int, float]]] = None,
) -> None:
    """
    Prints the UI during the relenv building process.

    :param events: A dictionary of events that are updated during the build process
    :type events: dict
    :param processes: A dictionary of build processes
    :type processes: dict
    :param fails: A list of processes that have failed
    :type fails: list
    :param flipstat: Deprecated parameter, no longer used
    :type flipstat: dict, optional
    """
    if CICD:
        sys.stdout.flush()
        return
    uiline = []
    for name in events:
        if not events[name].is_set():
            # Pending: event not yet started
            status = " {}{}".format(YELLOW, SYMBOL_PENDING)
        elif name in processes:
            # Running: show animated spinner
            frame_idx = _spinner_state.get(name) % len(SPINNER_FRAMES)
            spinner = SPINNER_FRAMES[frame_idx]
            _spinner_state.increment(name)
            status = " {}{}".format(GREEN, spinner)
        elif name in fails:
            # Failed: show error symbol
            status = " {}{}".format(RED, SYMBOL_FAILED)
        else:
            # Success: show success symbol
            status = " {}{}".format(GREEN, SYMBOL_SUCCESS)
        uiline.append(status)
    uiline.append("  " + END)
    sys.stdout.write("\r")
    sys.stdout.write("".join(uiline))
    sys.stdout.flush()


def print_ui_expanded(
    events: MutableMapping[str, "multiprocessing.synchronize.Event"],
    processes: MutableMapping[str, multiprocessing.Process],
    fails: Sequence[str],
    line_counts: MutableMapping[str, int],
    build_stats: Dict[str, BuildStats],
    phase: str = "build",
) -> None:
    """
    Prints an expanded UI with progress bars during the relenv building process.

    :param events: A dictionary of events that are updated during the build process
    :type events: dict
    :param processes: A dictionary of build processes
    :type processes: dict
    :param fails: A list of processes that have failed
    :type fails: list
    :param line_counts: Current line counts for each step
    :type line_counts: MutableMapping[str, int]
    :param build_stats: Historical build statistics
    :type build_stats: dict
    :param phase: The current phase ("download" or "build")
    :type phase: str
    """
    if CICD:
        sys.stdout.flush()
        return

    # Track state per phase to handle download->build transitions
    if not hasattr(print_ui_expanded, "_phase_state"):
        print_ui_expanded._phase_state = {}  # type: ignore

    phase_state = print_ui_expanded._phase_state  # type: ignore

    # Number of lines = number of steps + 2 (header + separator)
    num_lines = len(events) + 2

    # If this phase has been called before, move up to overwrite previous output
    if phase in phase_state:
        prev_lines = phase_state[phase]
        # Move up by previous line count to overwrite
        sys.stdout.write(MOVEUP * prev_lines)
    else:
        # First call for this phase - if we're starting builds after downloads,
        # add a newline to separate them
        if phase == "build" and "download" in phase_state:
            sys.stdout.write("\n")

    # Store line count for this phase
    phase_state[phase] = num_lines

    # Clear line and print header
    phase_name = "Downloads" if phase == "download" else "Builds"
    sys.stdout.write("\r\033[K")  # Clear line
    sys.stdout.write(f"{phase_name}\n")
    sys.stdout.write("─" * 70 + "\n")

    # Print each step
    for name in events:
        # Determine status
        if not events[name].is_set():
            # Pending
            status_symbol = f"{YELLOW}{SYMBOL_PENDING}{END}"
            status_text = "Pending"
            progress_bar = ""
        elif name in processes:
            # Running - show spinner and progress
            frame_idx = _spinner_state.get(name) % len(SPINNER_FRAMES)
            spinner = SPINNER_FRAMES[frame_idx]
            _spinner_state.increment(name)
            status_symbol = f"{GREEN}{spinner}{END}"

            # Determine if this is download or build phase
            phase_action = "Downloading" if phase == "download" else "Building"

            # Calculate progress if we have historical data
            current_lines = line_counts.get(name, 0)
            if phase == "download":
                # For downloads, line_counts stores bytes downloaded and total bytes
                # Format: line_counts[name] = downloaded, line_counts[f"{name}_total"] = total
                downloaded = current_lines
                total = line_counts.get(f"{name}_total", 0)
                if total > 0:
                    progress = min(100, int((downloaded / total) * 100))
                    status_text = f"{phase_action} {progress:3d}%"
                    # Progress bar (20 chars wide)
                    filled = int(progress / 5)  # 20 segments = 100% / 5
                    bar = (
                        "█" * filled + "░" * (20 - filled)
                        if USE_UNICODE
                        else ("#" * filled + "-" * (20 - filled))
                    )
                    progress_bar = f" [{bar}]"
                else:
                    status_text = phase_action
                    progress_bar = ""
            else:
                # For builds, use historical line count data
                if name in build_stats and build_stats[name]["avg_lines"] > 0:
                    avg_lines = build_stats[name]["avg_lines"]
                    progress = min(100, int((current_lines / avg_lines) * 100))
                    status_text = f"{phase_action} {progress:3d}%"

                    # Progress bar (20 chars wide)
                    filled = int(progress / 5)  # 20 segments = 100% / 5
                    bar = (
                        "█" * filled + "░" * (20 - filled)
                        if USE_UNICODE
                        else ("#" * filled + "-" * (20 - filled))
                    )
                    progress_bar = f" [{bar}]"
                else:
                    status_text = phase_action
                    progress_bar = ""
        elif name in fails:
            # Failed
            status_symbol = f"{RED}{SYMBOL_FAILED}{END}"
            status_text = "Failed"
            progress_bar = ""
        else:
            # Success
            status_symbol = f"{GREEN}{SYMBOL_SUCCESS}{END}"
            status_text = "Done"
            progress_bar = ""

        # Format step name (truncate/pad to 20 chars)
        name_display = f"{name:<20}"[:20]
        status_display = f"{status_text:<12}"

        # Clear line before writing to prevent leftover text
        sys.stdout.write("\r\033[K")
        sys.stdout.write(
            f"{status_symbol} {name_display} {status_display}{progress_bar}\n"
        )

    sys.stdout.flush()


def load_build_stats() -> Dict[str, BuildStats]:
    """
    Load historical build statistics from disk.

    :return: Dictionary mapping step names to their statistics
    :rtype: dict
    """
    stats_file = _get_build_stats_file()
    if not stats_file.exists():
        return {}
    try:
        import json

        with open(stats_file, "r") as f:
            data = json.load(f)
            return cast(Dict[str, BuildStats], data)
    except (json.JSONDecodeError, IOError):
        log.warning("Failed to load build stats, starting fresh")
        return {}


def save_build_stats(stats: Dict[str, BuildStats]) -> None:
    """
    Save build statistics to disk.

    :param stats: Dictionary mapping step names to their statistics
    :type stats: dict
    """
    try:
        import json

        stats_file = _get_build_stats_file()
        stats_file.parent.mkdir(parents=True, exist_ok=True)
        with open(stats_file, "w") as f:
            json.dump(stats, f, indent=2)
    except IOError:
        log.warning("Failed to save build stats")


def update_build_stats(step_name: str, line_count: int) -> None:
    """
    Update statistics for a build step with a new sample.

    Uses exponential moving average with weight 0.7 for new samples.

    :param step_name: Name of the build step
    :type step_name: str
    :param line_count: Number of log lines for this build
    :type line_count: int
    """
    stats = load_build_stats()
    if step_name not in stats:
        stats[step_name] = BuildStats(
            avg_lines=line_count, samples=1, last_lines=line_count
        )
    else:
        old_avg = stats[step_name]["avg_lines"]
        # Exponential moving average: 70% new value, 30% old average
        new_avg = int(0.7 * line_count + 0.3 * old_avg)
        stats[step_name] = BuildStats(
            avg_lines=new_avg,
            samples=stats[step_name]["samples"] + 1,
            last_lines=line_count,
        )
    save_build_stats(stats)


class LineCountHandler(logging.Handler):
    """
    Custom logging handler that counts log lines for progress tracking.

    This handler increments a counter in a shared multiprocessing dict
    for each log message emitted, enabling real-time progress estimation.
    """

    def __init__(self, step_name: str, shared_dict: MutableMapping[str, int]) -> None:
        """
        Initialize the line count handler.

        :param step_name: Name of the build step being tracked
        :type step_name: str
        :param shared_dict: Multiprocessing-safe dict for sharing counts
        :type shared_dict: MutableMapping[str, int]
        """
        super().__init__()
        self.step_name = step_name
        self.shared_dict = shared_dict

    def emit(self, record: logging.LogRecord) -> None:
        """
        Count each log record as a line.

        :param record: The log record to process
        :type record: logging.LogRecord
        """
        try:
            # Increment line count in shared memory
            current = self.shared_dict.get(self.step_name, 0)
            self.shared_dict[self.step_name] = current + 1
        except Exception:
            # Silently ignore errors in the handler to avoid breaking builds
            pass
