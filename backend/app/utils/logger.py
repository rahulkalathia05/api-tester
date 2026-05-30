import json
import logging
import sys

from app.config import settings

_SKIP = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelno", "lineno", "module", "msecs", "msg", "name", "pathname",
    "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName", "message",
})


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in _SKIP and not key.startswith("_") and key not in entry:
                entry[key] = val
        return json.dumps(entry, default=str)


def setup_logging(json_logs: bool = False) -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    if json_logs:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logging.root.setLevel(level)
        logging.root.addHandler(handler)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
            handlers=[logging.StreamHandler(sys.stdout)],
        )

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
