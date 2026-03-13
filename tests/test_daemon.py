import os
import signal
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from murmurate.daemon.lifecycle import (
    write_pid, read_pid, is_running, check_already_running,
    setup_signal_handlers, stop_daemon, cleanup_pid,
)
from murmurate.daemon.install import (
    generate_launchd_plist, generate_systemd_unit,
)

def test_write_and_read_pid(tmp_path):
    pid_file = tmp_path / "test.pid"
    write_pid(pid_file)
    pid = read_pid(pid_file)
    assert pid == os.getpid()

def test_read_pid_missing(tmp_path):
    assert read_pid(tmp_path / "nonexistent.pid") is None

def test_read_pid_invalid(tmp_path):
    pid_file = tmp_path / "bad.pid"
    pid_file.write_text("not-a-number")
    assert read_pid(pid_file) is None

def test_is_running_current_process():
    assert is_running(os.getpid()) is True

def test_is_running_nonexistent():
    assert is_running(99999999) is False

def test_check_already_running_no_file(tmp_path):
    assert check_already_running(tmp_path / "test.pid") is False

def test_check_already_running_stale(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("99999999")  # Non-existent PID
    assert check_already_running(pid_file) is False
    assert not pid_file.exists()  # Stale file cleaned up

def test_check_already_running_active(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text(str(os.getpid()))
    assert check_already_running(pid_file) is True

def test_setup_signal_handlers():
    scheduler = MagicMock()
    reload_cb = MagicMock()
    setup_signal_handlers(scheduler, reload_callback=reload_cb)

    # Simulate SIGTERM
    handler = signal.getsignal(signal.SIGTERM)
    handler(signal.SIGTERM, None)
    scheduler.stop.assert_called_once()

def test_sighup_triggers_reload():
    scheduler = MagicMock()
    reload_cb = MagicMock()
    setup_signal_handlers(scheduler, reload_callback=reload_cb)

    handler = signal.getsignal(signal.SIGHUP)
    handler(signal.SIGHUP, None)
    reload_cb.assert_called_once()

def test_stop_daemon_no_pid(tmp_path):
    assert stop_daemon(tmp_path / "test.pid") is False

def test_stop_daemon_stale(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("99999999")
    assert stop_daemon(pid_file) is False
    assert not pid_file.exists()

def test_cleanup_pid(tmp_path):
    pid_file = tmp_path / "test.pid"
    pid_file.write_text("12345")
    cleanup_pid(pid_file)
    assert not pid_file.exists()

def test_cleanup_pid_missing(tmp_path):
    cleanup_pid(tmp_path / "nope.pid")  # Should not raise

# Install tests
def test_generate_launchd_plist():
    plist = generate_launchd_plist(Path("/home/user/.config/murmurate"))
    assert "com.murmurate.daemon" in plist
    assert "/home/user/.config/murmurate" in plist
    assert "murmurate" in plist
    assert "<?xml" in plist
    assert "<plist" in plist

def test_generate_launchd_plist_custom_label():
    plist = generate_launchd_plist(Path("/tmp/config"), label="com.test.murmurate")
    assert "com.test.murmurate" in plist

def test_generate_systemd_unit():
    unit = generate_systemd_unit(Path("/home/user/.config/murmurate"))
    assert "[Unit]" in unit
    assert "[Service]" in unit
    assert "[Install]" in unit
    assert "/home/user/.config/murmurate" in unit
    assert "murmurate" in unit
