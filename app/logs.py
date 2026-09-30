"""Logging for the whole app: one line per event, with the request it belongs to.

    2026-09-30 10:12:03 INFO  app.api [req=7f3a2c1b user=Dhineshwar] POST /api/documents 200 8123ms
    2026-09-30 10:12:03 ERROR app.pipeline [req=7f3a2c1b user=Dhineshwar] document 42 failed while reading ...

- Level from LOG_LEVEL (default INFO). LOG_FORMAT=json writes one JSON object per line (for log tools).
- Every request gets an id, returned to the browser in the X-Request-ID header and shown in error
  messages ("Reference: 7f3a2c1b"), so a complaint can be matched to its log lines in seconds.
- Never logs passwords, cookies, API keys or document contents.
On Vercel the lines appear under Project -> Logs; with Docker, `docker compose logs app`.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_name: contextvars.ContextVar[str] = contextvars.ContextVar("user_name", default="-")
_configured = False


class _Context(logging.Filter):
    def filter(self, record):
        record.req = request_id.get()
        record.user = user_name.get()
        return True


class _Json(logging.Formatter):
    def format(self, record):
        out = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
               "logger": record.name, "req": getattr(record, "req", "-"), "user": getattr(record, "user", "-"),
               "message": record.getMessage()}
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup() -> None:
    """Configure logging once (safe to call again)."""
    global _configured
    if _configured:
        return
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_Context())
    if os.environ.get("LOG_FORMAT", "").lower() == "json":
        handler.setFormatter(_Json())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s [req=%(req)s user=%(user)s] %(message)s",
                                               "%Y-%m-%d %H:%M:%S"))
    app_log = logging.getLogger("app")
    app_log.handlers[:] = [handler]
    app_log.setLevel(getattr(logging, level, logging.INFO))
    app_log.propagate = False
    for noisy in ("httpx", "httpcore", "pdfminer", "pdfplumber", "anthropic", "alembic.runtime.migration"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True
