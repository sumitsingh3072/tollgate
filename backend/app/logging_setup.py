"""Process-wide logging: console or JSON lines, with the current request id on every record."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes every LogRecord has; anything else was passed via `extra=` and is emitted as a field.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "request_id", "color_message"}


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def _extras(record: logging.LogRecord) -> dict[str, object]:
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            **_extras(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-5s %(name)s [%(request_id)s] %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extras(record)
        if extras:
            line += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return line


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # Our access middleware replaces uvicorn's access log; route uvicorn's own logs through root.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
