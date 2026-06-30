import asyncio
from typing import List, Dict, Any
from fastapi import WebSocket

from core.logger import log, error_log

class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log.info("WebSocket connected.")
        # Send initial status
        await self.send_status(websocket, "IDLE")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            log.info("WebSocket disconnected.")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                error_log.error(f"Failed to send to websocket: {e}")
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)

    async def send_status(self, websocket: WebSocket = None, status: str = "IDLE"):
        """Send a status update. If websocket is None, broadcast to all."""
        msg = {"type": "status_update", "status": status}
        if websocket:
            await websocket.send_json(msg)
        else:
            await self.broadcast(msg)

    async def send_execution_event(self, action: str, details: str):
        """Send an execution step event."""
        msg = {"type": "execution_update", "action": action, "details": details}
        await self.broadcast(msg)

    async def send_chunk(self, chunk: str):
        """Send a streaming text chunk."""
        msg = {"type": "stream_chunk", "chunk": chunk}
        await self.broadcast(msg)
        
    async def send_stream_end(self):
        msg = {"type": "stream_done"}
        await self.broadcast(msg)

ws_manager = WebSocketManager()
