"""
tests/test_cli.py — Tests for the Murmurate Click CLI.

Uses Click's CliRunner for isolated, no-subprocess testing of every command.
The run command is not tested here since it requires a full async stack with
database, transports, and plugins — that belongs in integration tests.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock, AsyncMock
from murmurate.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_version(runner):
    """--version flag should print the package version and exit cleanly."""
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "murmurate" in result.output.lower() or "0." in result.output


def test_cli_help(runner):
    """--help flag should describe the tool and list subcommands."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Murmurate" in result.output


def test_plugins_list(runner):
    """plugins list should enumerate all bundled plugins including duckduckgo and wikipedia."""
    result = runner.invoke(cli, ["plugins", "list"])
    assert result.exit_code == 0
    assert "duckduckgo" in result.output
    assert "wikipedia" in result.output


def test_plugins_info(runner):
    """plugins info <name> should print plugin details for a known plugin."""
    result = runner.invoke(cli, ["plugins", "info", "duckduckgo"])
    assert result.exit_code == 0
    assert "duckduckgo" in result.output


def test_plugins_info_not_found(runner):
    """plugins info for an unknown plugin should report it was not found."""
    result = runner.invoke(cli, ["plugins", "info", "nonexistent"])
    assert result.exit_code == 0
    assert "not found" in result.output


def test_personas_list_empty(runner, tmp_path):
    """personas list should report no personas when the directory is empty."""
    result = runner.invoke(cli, ["personas", "list", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No personas" in result.output


def test_personas_add(runner, tmp_path):
    """personas add should create a JSON file for the new persona."""
    result = runner.invoke(
        cli,
        ["personas", "add", "tester", "-s", "cooking", "-s", "travel", "--config-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Created persona" in result.output
    # Verify the persona file was written to the personas subdirectory
    assert (tmp_path / "personas" / "tester.json").exists()


def test_personas_list_after_add(runner, tmp_path):
    """personas list should show a persona that was previously added."""
    # Add first
    runner.invoke(
        cli,
        ["personas", "add", "alice", "-s", "history", "-s", "science", "--config-dir", str(tmp_path)],
    )
    # Then list
    result = runner.invoke(cli, ["personas", "list", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "alice" in result.output


def test_status_not_running(runner, tmp_path):
    """status should report daemon is not running when no PID file exists."""
    result = runner.invoke(cli, ["status", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "not running" in result.output


def test_status_running(runner, tmp_path):
    """status should report the PID when a PID file is present."""
    pid_file = tmp_path / "murmurate.pid"
    pid_file.write_text("12345")
    result = runner.invoke(cli, ["status", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "12345" in result.output


def test_stop_command_not_running(runner, tmp_path):
    """stop command should report daemon not running when no PID file exists."""
    result = runner.invoke(cli, ["stop", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test_stop_command_with_stale_pid(runner, tmp_path):
    """stop command should handle a stale PID file gracefully."""
    pid_file = tmp_path / "murmurate.pid"
    # Use a PID that almost certainly doesn't exist
    pid_file.write_text("999999999")
    result = runner.invoke(cli, ["stop", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test_history_command_no_db(runner, tmp_path):
    """history command should report no history when database doesn't exist."""
    result = runner.invoke(cli, ["history", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No session history" in result.output


def test_history_command_with_n(runner, tmp_path):
    """history -n should accept a custom count and exit cleanly."""
    result = runner.invoke(cli, ["history", "-n", "20", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0


def test_stats_command_no_db(runner, tmp_path):
    """stats command should report no data when database doesn't exist."""
    result = runner.invoke(cli, ["stats", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No session data" in result.output


def test_stats_command_with_days(runner, tmp_path):
    """stats -d should accept a custom number of days and exit cleanly."""
    result = runner.invoke(cli, ["stats", "-d", "30", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0


def test_start_command_help(runner):
    """start --help should describe the daemon foreground mode."""
    result = runner.invoke(cli, ["start", "--help"])
    assert result.exit_code == 0
    assert "daemon" in result.output.lower() or "launchd" in result.output.lower()


def test_install_daemon_help(runner):
    """install-daemon --help should describe service installation."""
    result = runner.invoke(cli, ["install-daemon", "--help"])
    assert result.exit_code == 0
    assert "daemon" in result.output.lower()


def test_uninstall_daemon_help(runner):
    """uninstall-daemon --help should describe service removal."""
    result = runner.invoke(cli, ["uninstall-daemon", "--help"])
    assert result.exit_code == 0
