"""结构化 JSON 日志配置（生产可接入 Loki/ELK）。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_EXTRA_FIELDS = ("user_id", "request_id", "duration_ms", "query_id")


class JsonFormatter(logging.Formatter):
    """输出单行 JSON 日志。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key in _EXTRA_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """配置根日志为结构化 JSON 输出（幂等）。"""
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
