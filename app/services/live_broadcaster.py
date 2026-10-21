"""Live Admin Monitoring & WebSocket Broadcaster service."""

import json
from typing import Dict, Set
from fastapi import WebSocket
from app.utils.logging import logger
from app.utils.pii_masking import mask_sensitive_pii


class AdminLiveBroadcaster:
    """Broadcaster forwarding live call audio levels, transcripts, and QA scores to connected admin dashboards."""

    def __init__(self):
        self._active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._active_connections.add(websocket)
        logger.info("admin_live_monitor_connected", total_admins=len(self._active_connections))

    def disconnect(self, websocket: WebSocket):
        self._active_connections.discard(websocket)
        logger.info("admin_live_monitor_disconnected", total_admins=len(self._active_connections))

    async def broadcast(self, message: Dict):
        if not self._active_connections:
            return

        # Ensure any text payload has PII masked
        if "text" in message:
            message["text"] = mask_sensitive_pii(message["text"])
        if "transcript" in message:
            message["transcript"] = mask_sensitive_pii(message["transcript"])

        payload = json.dumps(message)
        dead = set()
        for ws in self._active_connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)

        for d in dead:
            self._active_connections.discard(d)


_broadcaster = AdminLiveBroadcaster()


def get_live_broadcaster() -> AdminLiveBroadcaster:
    return _broadcaster
