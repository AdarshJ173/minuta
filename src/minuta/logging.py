"""Structured JSON logs with secret redaction. Transcript text is untrusted data."""

from __future__ import annotations

import json
import logging
import sys

from minuta.settings import get_settings

_configured = False


def _redactor() -> logging.Filter:
    settings = get_settings()
    secrets = sorted(settings.redaction_values(), key=len, reverse=True)

    class _Filter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                msg = record.getMessage()
                for s in secrets:
                    if s in msg:
                        msg = msg.replace(s, "<redacted>")
                record.msg, record.args = msg, ()
            except Exception:
                pass
            return True

    return _Filter()


def configure() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("minuta")
    root.handlers = [handler]
    root.setLevel(get_settings().log_level.upper())
    root.addFilter(_redactor())
    _configured = True


def log(event: str, **fields) -> None:
    configure()
    payload = {"event": event, **fields}
    logging.getLogger("minuta").info(json.dumps(payload, default=str))
