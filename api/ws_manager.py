"""
JARVIS API — WebSocket Manager (Phase 3.6 Hardened)
Thread-safe WebSocket broadcasting, authenticated session management,
and real-time task interruption routing.
"""

import asyncio
from typing import List, Dict, Any, Optional
from fastapi import WebSocket

from core.logger import log, error_log


class WebSocketManager:
    """
    Central manager for WebSocket clients.
    Features:
      - Main event-loop capture for thread-safe cross-thread event delivery.
      - Authenticated session binding for confirmations and controls.
      - Active task tracking with cooperative interruption signaling.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.connection_meta: Dict[WebSocket, dict] = {}
        self.active_tasks: Dict[str, Any] = {} # session_id / task_id -> AssistantTask or ExecutionContext
        self.task_metadata: Dict[str, dict] = {} # target_id -> metadata
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the primary FastAPI application event loop."""
        self.main_loop = loop
        log.info("WebSocketManager captured primary application event loop.")

    async def connect(self, websocket: WebSocket, session_id: Optional[str] = None):
        """Accept a new WebSocket connection and track session metadata."""
        await websocket.accept()
        if not self.main_loop or not self.main_loop.is_running():
            try:
                self.main_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        self.active_connections.append(websocket)
        sid = session_id or f"ws_{id(websocket)}"
        self.connection_meta[websocket] = {
            "session_id": sid,
            "authenticated": False,
            "token": None
        }
        log.info(f"WebSocket connected (session: {sid}).")
        await self.send_status(websocket, "IDLE")

    def disconnect(self, websocket: WebSocket):
        """Clean up disconnected socket and session metadata."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        meta = self.connection_meta.pop(websocket, None)
        if meta:
            sid = meta.get("session_id")
            # If an active task is tied to this session, cooperatively cancel it
            if sid and sid in self.active_tasks:
                task = self.active_tasks.pop(sid, None)
                if task and hasattr(task, "cancel") and not task.is_cancelled:
                    task.cancel("WEBSOCKET_DISCONNECTED")
            log.info(f"WebSocket disconnected (session: {sid}).")

    def authenticate_connection(
        self,
        websocket: WebSocket,
        token: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> None:
        """Mark a connection as authenticated with verified token, user_id, and optional session_id."""
        if websocket in self.connection_meta:
            self.connection_meta[websocket]["authenticated"] = True
            self.connection_meta[websocket]["token"] = token
            if user_id:
                self.connection_meta[websocket]["user_id"] = user_id
            if session_id:
                self.connection_meta[websocket]["session_id"] = session_id

    def is_authenticated(self, websocket: WebSocket) -> bool:
        """Check if a WebSocket connection is authenticated."""
        return self.connection_meta.get(websocket, {}).get("authenticated", False)

    def get_session_id(self, websocket: WebSocket) -> str:
        """Get session identifier for a WebSocket."""
        return self.connection_meta.get(websocket, {}).get("session_id", f"ws_{id(websocket)}")

    def get_user_id(self, websocket: WebSocket) -> Optional[str]:
        """Get authenticated user identifier for a WebSocket."""
        return self.connection_meta.get(websocket, {}).get("user_id")

    # ─── Task Interruption & Tracking ─────────────────────────────────────────

    def register_active_task(
        self,
        session_id: str,
        task: Any,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> None:
        """
        Register active task for interruption targeting.
        Tracks task_id, session_id, and user_id per active task.
        """
        real_task_id = task_id or getattr(task, "task_id", None) or getattr(task, "request_id", None) or session_id
        real_user_id = user_id or getattr(task, "user_id", None)
        real_session_id = getattr(task, "session_id", None) or session_id

        meta = {
            "task": task,
            "task_id": real_task_id,
            "session_id": real_session_id,
            "user_id": real_user_id
        }

        self.active_tasks[session_id] = task
        self.task_metadata[session_id] = meta

        if real_task_id and real_task_id != session_id:
            self.active_tasks[real_task_id] = task
            self.task_metadata[real_task_id] = meta

    def unregister_active_task(self, target_id: str, task_obj: Optional[Any] = None) -> None:
        """
        Remove completed or cancelled task from active registry identity-safely.
        Verifies that session/task aliases still reference the specific task being removed.
        """
        if not target_id:
            return

        target_meta = self.task_metadata.get(target_id)
        target_task = task_obj or (target_meta.get("task") if target_meta else self.active_tasks.get(target_id))

        # Only pop target_id if it still points to target_task (or if target_task is unknown)
        if target_id in self.active_tasks:
            if target_task is None or self.active_tasks[target_id] is target_task:
                self.active_tasks.pop(target_id, None)

        if target_id in self.task_metadata:
            meta = self.task_metadata[target_id]
            if target_task is None or meta.get("task") is target_task:
                self.task_metadata.pop(target_id, None)

        if target_meta:
            t_id = target_meta.get("task_id")
            s_id = target_meta.get("session_id")
            meta_task = target_meta.get("task")

            if t_id and t_id != target_id:
                if self.active_tasks.get(t_id) is meta_task:
                    self.active_tasks.pop(t_id, None)
                if self.task_metadata.get(t_id) and self.task_metadata[t_id].get("task") is meta_task:
                    self.task_metadata.pop(t_id, None)

            if s_id and s_id != target_id:
                if self.active_tasks.get(s_id) is meta_task:
                    self.active_tasks.pop(s_id, None)
                if self.task_metadata.get(s_id) and self.task_metadata[s_id].get("task") is meta_task:
                    self.task_metadata.pop(s_id, None)

    def get_task_metadata(self, target_id: str) -> Optional[dict]:
        """Look up task metadata by task_id or session_id."""
        if not target_id:
            return None
        if target_id in self.task_metadata:
            return self.task_metadata[target_id]
        for meta in self.task_metadata.values():
            if meta.get("task_id") == target_id or meta.get("session_id") == target_id:
                return meta
        return None

    def get_active_task(self, session_id: str) -> Optional[Any]:
        """Retrieve active task strictly by session or task identifier."""
        if session_id and session_id in self.active_tasks:
            return self.active_tasks[session_id]
        meta = self.get_task_metadata(session_id)
        if meta:
            return meta.get("task")
        return None

    def cancel_active_task(self, session_id: Optional[str] = None, reason: str = "INTERRUPTED") -> bool:
        """
        Interrupt and cancel running task for a specific session or task ID.
        Never cancels tasks of other sessions if session_id is unknown, missing, or invalid.
        """
        if not session_id:
            return False

        task = self.active_tasks.get(session_id)
        if not task:
            meta = self.get_task_metadata(session_id)
            if meta:
                task = meta.get("task")

        if not task:
            return False

        cancelled = False
        if hasattr(task, "cancel"):
            task.cancel(reason)
            cancelled = True
        elif hasattr(task, "cancellation_token") and task.cancellation_token:
            task.cancellation_token.set()
            cancelled = True
        elif hasattr(task, "set"):
            task.set()
            cancelled = True

        return cancelled

    # ─── Targeted & Broadcast Delivery ───────────────────────────────────────

    async def send_to_session(self, session_id: str, message: dict) -> bool:
        """Send a message asynchronously strictly to all active connections matching session_id."""
        if not session_id:
            return False
        delivered = False
        disconnected = []
        for connection in list(self.active_connections):
            meta = self.connection_meta.get(connection, {})
            if meta.get("session_id") == session_id:
                try:
                    await connection.send_json(message)
                    delivered = True
                except Exception as e:
                    error_log.error(f"Failed to send to websocket session {session_id}: {e}")
                    disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)
        return delivered

    async def send_chunk_to_session(self, session_id: str, chunk: str) -> bool:
        """Send a streaming text chunk strictly to the owning session."""
        msg = {"type": "stream_chunk", "chunk": chunk}
        return await self.send_to_session(session_id, msg)

    async def send_status_to_session(self, session_id: str, status: str = "IDLE") -> bool:
        """Send a status update strictly to the owning session."""
        msg = {"type": "status_update", "status": status}
        return await self.send_to_session(session_id, msg)

    async def send_stream_end_to_session(self, session_id: str) -> bool:
        """Send stream completion notice strictly to the owning session."""
        msg = {"type": "stream_done"}
        return await self.send_to_session(session_id, msg)

    async def send_execution_event_to_session(self, session_id: str, action: str, details: str, **kwargs) -> bool:
        """Send an execution step event strictly to the owning session."""
        msg = {"type": "execution_update", "action": action, "details": details, **kwargs}
        return await self.send_to_session(session_id, msg)

    def safe_send_to_session(self, session_id: str, message: dict) -> bool:
        """Thread-safe event delivery strictly to the owning session from background threads."""
        if not session_id:
            return False
        try:
            loop = self.main_loop
            if not (loop and loop.is_running()):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

            if loop and loop.is_running():
                try:
                    curr_loop = asyncio.get_running_loop()
                except RuntimeError:
                    curr_loop = None

                if curr_loop is loop:
                    asyncio.create_task(self.send_to_session(session_id, message))
                else:
                    asyncio.run_coroutine_threadsafe(self.send_to_session(session_id, message), loop)
                return True
            else:
                error_log.warning(f"Cannot send to session {session_id}: Main loop offline.")
                return False
        except Exception as e:
            error_log.error(f"safe_send_to_session failed: {e}")
            return False

    def send_confirmation_to_session(self, session_id: str, message: dict) -> bool:
        """
        Thread-safe delivery of confirmation notifications strictly to the owning session.
        Ensures confirmation events are never globally broadcast.
        """
        if not session_id:
            return False
        try:
            loop = self.main_loop
            if not (loop and loop.is_running()):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

            if loop and loop.is_running():
                try:
                    curr_loop = asyncio.get_running_loop()
                except RuntimeError:
                    curr_loop = None

                if curr_loop is loop:
                    asyncio.create_task(self.send_to_session(session_id, message))
                else:
                    asyncio.run_coroutine_threadsafe(self.send_to_session(session_id, message), loop)
                return True
            else:
                error_log.warning("Cannot send confirmation: Main application event loop is offline.")
                return False
        except Exception as e:
            error_log.error(f"send_confirmation_to_session failed: {e}")
            return False

    async def broadcast(self, message: dict):
        """Broadcast a message asynchronously to all active connections."""
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                error_log.error(f"Failed to send to websocket: {e}")
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)

    def safe_broadcast(self, message: dict) -> bool:
        """
        Thread-safe message broadcaster usable from ANY worker thread, tool, or agent.
        Uses asyncio.run_coroutine_threadsafe when called from background threads.
        """
        try:
            loop = self.main_loop
            if not (loop and loop.is_running()):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

            if loop and loop.is_running():
                # Running inside the main loop thread?
                try:
                    curr_loop = asyncio.get_running_loop()
                except RuntimeError:
                    curr_loop = None

                if curr_loop is loop:
                    asyncio.create_task(self.broadcast(message))
                else:
                    asyncio.run_coroutine_threadsafe(self.broadcast(message), loop)
                return True
            else:
                # Fallback if no main loop captured yet
                error_log.warning("Cannot broadcast event: Main application event loop is offline.")
                return False
        except Exception as e:
            error_log.error(f"safe_broadcast failed: {e}")
            return False

    async def send_status(self, websocket: WebSocket = None, status: str = "IDLE"):
        """Send a status update. If websocket is None, broadcast to all."""
        msg = {"type": "status_update", "status": status}
        if websocket:
            try:
                await websocket.send_json(msg)
            except Exception:
                self.disconnect(websocket)
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
