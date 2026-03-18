"""Tests for murmurate.log — structured JSON logging."""

import json
import logging

import pytest

from murmurate.log import get_logger, setup_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _last_json_line(log_file) -> dict:
    """Read the last non-empty line of *log_file* and parse it as JSON."""
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    assert lines, "Log file is empty"
    return json.loads(lines[-1])


def _all_json_lines(log_file) -> list[dict]:
    lines = [line for line in log_file.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


# ---------------------------------------------------------------------------
# Fixture: ensure a fresh root logger for every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_root_logger():
    """Tear down any file handlers added during the test so that the next
    test starts with a clean root logger and no open file descriptors."""
    yield
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()


# ---------------------------------------------------------------------------
# JSON format tests (the canonical path)
# ---------------------------------------------------------------------------


def test_json_log_output(tmp_path):
    """Reproduces the spec example exactly."""
    log_file = tmp_path / "test.log"
    setup_logging(log_file, level="DEBUG", json_format=True)
    logger = get_logger("test")
    logger.info("session_complete", extra={"persona": "woodworker", "plugin": "google"})

    lines = log_file.read_text().strip().split("\n")
    entry = json.loads(lines[-1])

    assert entry["level"] == "INFO"
    assert entry["persona"] == "woodworker"


def test_json_mandatory_fields(tmp_path):
    """Every JSON line must contain ts, level, and msg."""
    log_file = tmp_path / "mandatory.log"
    setup_logging(log_file, level="DEBUG", json_format=True)
    get_logger("mandatory").debug("hello")

    entry = _last_json_line(log_file)
    assert "ts" in entry
    assert "level" in entry
    assert "msg" in entry


def test_json_ts_is_iso8601(tmp_path):
    """The ts field should be parseable as an ISO 8601 timestamp."""
    from datetime import datetime

    log_file = tmp_path / "ts.log"
    setup_logging(log_file, level="DEBUG", json_format=True)
    get_logger("ts").warning("check timestamp")

    entry = _last_json_line(log_file)
    # datetime.fromisoformat raises ValueError if the string is malformed
    dt = datetime.fromisoformat(entry["ts"])
    assert dt.tzinfo is not None, "Timestamp should be timezone-aware"


def test_json_level_names(tmp_path):
    """level field reflects the actual logging level name."""
    log_file = tmp_path / "levels.log"
    setup_logging(log_file, level="DEBUG", json_format=True)
    logger = get_logger("levels")
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")
    logger.critical("c")

    entries = _all_json_lines(log_file)
    assert [e["level"] for e in entries] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_json_extra_fields_merged(tmp_path):
    """Extra kwargs are promoted to top-level JSON keys."""
    log_file = tmp_path / "extra.log"
    setup_logging(log_file, level="INFO", json_format=True)
    get_logger("extra").info("done", extra={"plugin": "google", "duration_ms": 42})

    entry = _last_json_line(log_file)
    assert entry["plugin"] == "google"
    assert entry["duration_ms"] == 42


def test_json_msg_field(tmp_path):
    """The msg field captures the formatted message string."""
    log_file = tmp_path / "msg.log"
    setup_logging(log_file, level="INFO", json_format=True)
    get_logger("msg").info("hello world")

    entry = _last_json_line(log_file)
    assert entry["msg"] == "hello world"


def test_json_level_filtering(tmp_path):
    """Messages below the configured level must not appear in the file."""
    log_file = tmp_path / "filter.log"
    setup_logging(log_file, level="WARNING", json_format=True)
    logger = get_logger("filter")
    logger.debug("should be suppressed")
    logger.info("also suppressed")
    logger.warning("this should appear")

    entries = _all_json_lines(log_file)
    assert len(entries) == 1
    assert entries[0]["level"] == "WARNING"


def test_parent_dirs_created(tmp_path):
    """setup_logging should create missing parent directories."""
    log_file = tmp_path / "nested" / "deep" / "app.log"
    setup_logging(log_file, level="INFO", json_format=True)
    get_logger("dirs").info("created")
    assert log_file.exists()


# ---------------------------------------------------------------------------
# Text format tests
# ---------------------------------------------------------------------------


def test_text_format_does_not_crash(tmp_path):
    """text format (json_format=False) must work without raising."""
    log_file = tmp_path / "text.log"
    setup_logging(log_file, level="INFO", json_format=False)
    logger = get_logger("text")
    logger.info("human readable message")
    logger.warning("another line")

    content = log_file.read_text()
    assert "human readable message" in content
    assert "another line" in content


def test_text_format_not_json(tmp_path):
    """Text format output must NOT be valid JSON lines."""
    log_file = tmp_path / "notjson.log"
    setup_logging(log_file, level="INFO", json_format=False)
    get_logger("notjson").info("plain text")

    lines = [entry for entry in log_file.read_text().splitlines() if entry.strip()]
    for line in lines:
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)


# ---------------------------------------------------------------------------
# get_logger tests
# ---------------------------------------------------------------------------


def test_get_logger_returns_named_logger(tmp_path):
    """get_logger('foo') should return a Logger named 'foo'."""
    log_file = tmp_path / "named.log"
    setup_logging(log_file, level="DEBUG", json_format=True)
    logger = get_logger("mymodule")
    assert logger.name == "mymodule"
    assert isinstance(logger, logging.Logger)


# ---------------------------------------------------------------------------
# Setup called multiple times (e.g. between tests)
# ---------------------------------------------------------------------------


def test_repeated_setup_does_not_duplicate_output(tmp_path):
    """Calling setup_logging twice should not produce duplicate lines."""
    log_file = tmp_path / "repeat.log"
    setup_logging(log_file, level="INFO", json_format=True)
    setup_logging(log_file, level="INFO", json_format=True)
    get_logger("repeat").info("once")

    entries = _all_json_lines(log_file)
    assert len(entries) == 1, f"Expected 1 line, got {len(entries)}"
