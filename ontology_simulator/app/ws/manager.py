"""WebSocket Connection Manager – broadcast events to all connected clients."""
import json
from datetime import datetime
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        print(f"[WS] Client connected. Total: {len(self._connections)}")

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        print(f"[WS] Client disconnected. Total: {len(self._connections)}")

    async def broadcast(self, payload: dict) -> None:
        """Send JSON payload to all active connections; silently drop dead ones."""
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(payload, mode="text")
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)


# Singleton – imported by station_agent and main
manager = ConnectionManager()


def _default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat() + "Z"
    raise TypeError(f"Not serializable: {type(obj)}")
