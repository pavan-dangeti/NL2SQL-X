import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if rid := request_id.get():
            payload["request_id"] = rid
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class Logger:
    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(f"nl2sql.{name}")

    def _emit(self, level: int, event: str, **fields) -> None:
        if self._log.isEnabledFor(level):
            self._log.log(level, event, extra={"fields": fields})

    def info(self, event: str, **fields) -> None:
        self._emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields) -> None:
        self._emit(logging.WARNING, event, **fields)

    def error(self, event: str, **fields) -> None:
        self._emit(logging.ERROR, event, **fields)

    def exception(self, event: str, **fields) -> None:
        self._log.exception(event, extra={"fields": fields})


def get_logger(name: str) -> Logger:
    return Logger(name)


def configure(level: str) -> None:
    root = logging.getLogger("nl2sql")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)
        root.propagate = False
    root.setLevel(level.upper())
