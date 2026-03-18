"""
Structured logging for Murmurate.

Provides JSON-formatted logging (one object per line) suitable for log
aggregation and machine parsing, with a fallback to human-readable format
for local development.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


class _JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Each record emits exactly one JSON line with the mandatory fields
    ``ts``, ``level``, and ``msg``.  Any keys passed via the ``extra``
    dict on the logger call are merged into the top-level object so that
    callers can attach arbitrary structured context without nesting.
    """

    # Keys that are part of the stdlib LogRecord but should NOT be
    # forwarded as top-level fields in the JSON output.
    _RESERVED = frozenset(
        logging.LogRecord(
            name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
        ).__dict__.keys()
    ) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        # Let the base class handle exception/stack info serialisation
        # into record.exc_text and record.stack_info before we touch it.
        super().format(record)

        entry: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }

        # Merge any extra fields the caller attached, skipping internal
        # LogRecord attributes so we don't leak implementation details.
        for key, value in record.__dict__.items():
            if key not in self._RESERVED:
                entry[key] = value

        if record.exc_text:
            entry["exc"] = record.exc_text

        return json.dumps(entry, default=str)


def setup_logging(
    log_file: Path,
    level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configure the root logger to write to *log_file*.

    Args:
        log_file: Destination file.  Parent directories are created if
            they do not already exist.
        level: Minimum severity to record (DEBUG / INFO / WARNING /
            ERROR / CRITICAL).  Case-insensitive.
        json_format: When ``True`` (default) each line is a JSON object.
            When ``False`` a human-readable format is used instead.
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    # Remove any handlers that were attached in a previous call so that
    # repeated calls to setup_logging (e.g. in tests) start clean.
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(numeric_level)

    if json_format:
        file_handler.setFormatter(_JsonFormatter())
    else:
        fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
        file_handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S"))

    root.setLevel(numeric_level)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    A thin convenience wrapper around :func:`logging.getLogger` so that
    callers don't need to import the stdlib ``logging`` module directly.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A :class:`logging.Logger` configured by the most recent call to
        :func:`setup_logging`.
    """
    return logging.getLogger(name)
