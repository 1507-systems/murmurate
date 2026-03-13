"""Daemon lifecycle — PID files, signal handlers, process management."""

import logging
import os
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

def write_pid(pid_file: Path) -> None:
    """Write current process PID to file."""
    pid_file.write_text(str(os.getpid()))

def read_pid(pid_file: Path) -> int | None:
    """Read PID from file. Returns None if file doesn't exist or is invalid."""
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None

def is_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)  # Signal 0 = check existence
        return True
    except (ProcessLookupError, PermissionError):
        return False

def check_already_running(pid_file: Path) -> bool:
    """Check if daemon is already running. Cleans up stale PID files.

    Returns True if daemon is running, False if not (stale PID cleaned up).
    """
    pid = read_pid(pid_file)
    if pid is None:
        return False
    if is_running(pid):
        return True
    # Stale PID — clean up
    logger.info(f"Cleaning up stale PID file (PID {pid} not running)")
    pid_file.unlink(missing_ok=True)
    return False

def setup_signal_handlers(scheduler, reload_callback=None):
    """Set up signal handlers for daemon operation.

    SIGTERM → graceful shutdown (scheduler.stop())
    SIGINT  → immediate shutdown
    SIGHUP  → reload config and personas (calls reload_callback)
    """
    def handle_term(signum, frame):
        logger.info("Received SIGTERM, shutting down gracefully...")
        scheduler.stop()

    def handle_int(signum, frame):
        logger.info("Received SIGINT, stopping immediately...")
        scheduler.stop()

    def handle_hup(signum, frame):
        logger.info("Received SIGHUP, reloading configuration...")
        if reload_callback:
            reload_callback()

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_int)
    signal.signal(signal.SIGHUP, handle_hup)

def stop_daemon(pid_file: Path) -> bool:
    """Send SIGTERM to the daemon. Returns True if signal sent."""
    pid = read_pid(pid_file)
    if pid is None:
        logger.warning("No PID file found")
        return False
    if not is_running(pid):
        logger.warning(f"PID {pid} is not running, cleaning up stale PID file")
        pid_file.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    logger.info(f"Sent SIGTERM to PID {pid}")
    return True

def cleanup_pid(pid_file: Path) -> None:
    """Remove PID file on clean exit."""
    pid_file.unlink(missing_ok=True)
