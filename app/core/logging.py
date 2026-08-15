import json
import logging
from contextvars import ContextVar
from logging.config import dictConfig

from app.config.settings import Settings

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(request_id: str) -> None:
    """Set the active request/trace id for log correlation (P2.7).

    Thread/task-local via ``contextvars``; clear with ``clear_request_id``.
    """
    _request_id_var.set(request_id or "")


def clear_request_id() -> None:
    _request_id_var.set("")


def _active_request_id() -> str:
    return _request_id_var.get()


class CorrelationFilter(logging.Filter):
    """Injects the active request id into every emitted record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _active_request_id() or None
        return True


class TextFormatter(logging.Formatter):
    """Default line formatter; appends the active request id when present."""

    def format(self, record: logging.LogRecord) -> str:
        line = logging.Formatter.format(self, record)
        request_id = getattr(record, "request_id", None)
        if request_id:
            line = f"{line} [request_id={request_id}]"
        return line


class JsonFormatter(logging.Formatter):
    """Emit each record as one JSON object with stable keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    json_format = settings.log_format.strip().lower() == "json"
    formatter_name = "json" if json_format else "text"
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "text": {
                    "()": "app.core.logging.TextFormatter",
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                },
                "json": {
                    "()": "app.core.logging.JsonFormatter",
                },
            },
            "filters": {
                "correlation": {
                    "()": "app.core.logging.CorrelationFilter",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": formatter_name,
                    "filters": ["correlation"],
                }
            },
            "root": {
                "handlers": ["console"],
                "level": settings.log_level,
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
