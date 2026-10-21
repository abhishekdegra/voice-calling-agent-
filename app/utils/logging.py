"""Structured logging utility with secret masking and contextual logging."""

import json
import logging
import sys
import time
from typing import Any, Dict, Optional


SENSITIVE_KEYS = {
    "password", "secret", "token", "api_key", "authorization", 
    "gemini_api_key", "telecmi_app_secret", "telecmi_user_password",
    "qdrant_api_key"
}


def mask_sensitive_data(data: Any) -> Any:
    """Recursively mask sensitive values in dicts, lists, or strings."""
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                masked[k] = "***MASKED***"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    return data


class StructuredLogger:
    def __init__(self, name: str = "welfog_voice_agent"):
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(formatter)
            self.logger.addHandler(stream_handler)
            try:
                file_handler = logging.FileHandler("app/server.log", encoding="utf-8")
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
            except Exception:
                pass
            self.logger.setLevel(logging.INFO)

    def set_level(self, level: str):
        self.logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    def _format_event(
        self,
        event: str,
        call_id: Optional[str] = None,
        order_id: Optional[str] = None,
        user_id: Optional[int] = None,
        tool_name: Optional[str] = None,
        latency_ms: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        payload: Dict[str, Any] = {"event": event}
        if call_id:
            payload["call_id"] = call_id
        if order_id:
            payload["order_id"] = order_id
        if user_id is not None:
            payload["user_id"] = user_id
        if tool_name:
            payload["tool_name"] = tool_name
        if latency_ms is not None:
            payload["latency_ms"] = round(latency_ms, 2)
        if error:
            payload["error"] = error
        if extra:
            payload.update(mask_sensitive_data(extra))
        if kwargs:
            payload.update(mask_sensitive_data(kwargs))
        return json.dumps(payload, default=str)

    def info(self, event_name: str, **kwargs):
        if "event" in kwargs:
            kwargs["action_event"] = kwargs.pop("event")
        self.logger.info(self._format_event(event_name, **kwargs))

    def warning(self, event_name: str, **kwargs):
        if "event" in kwargs:
            kwargs["action_event"] = kwargs.pop("event")
        self.logger.warning(self._format_event(event_name, **kwargs))

    def error(self, event_name: str, **kwargs):
        if "event" in kwargs:
            kwargs["action_event"] = kwargs.pop("event")
        self.logger.error(self._format_event(event_name, **kwargs))

    def debug(self, event_name: str, **kwargs):
        if "event" in kwargs:
            kwargs["action_event"] = kwargs.pop("event")
        self.logger.debug(self._format_event(event_name, **kwargs))


logger = StructuredLogger()
