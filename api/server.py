"""
JARVIS FastAPI Backend Server
Full REST + WebSocket API for the JARVIS AI Operating System.

Endpoints:
  POST   /auth/login            — Authenticate with PIN, receive JWT
  POST   /auth/set-pin          — Set owner PIN (first-run or change)
  POST   /auth/logout           — Invalidate current token

  POST   /chat                  — Send message, get response
  WS     /ws/stream             — Real-time streaming WebSocket chat

  GET    /history               — Recent conversation history
  DELETE /history               — Clear conversation history

  POST   /task                  — Submit autonomous multi-step task

  GET    /memory/search         — Semantic memory search
  POST   /memory                — Store new memory entry
  POST   /memory/preference     — Set a user preference
  GET    /memory/preference/{k} — Get a user preference
  DELETE /memory                — Clear all memory (DESTRUCTIVE)

  GET    /status                — System status and health

Run with:
    uvicorn api.server:app --host 127.0.0.1 --port 7799 --reload
"""

import time
import json
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Annotated, Optional, Any
from pydantic import BaseModel

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles

from api.models import (
    AuthRequest, AuthResponse, SetPinRequest,
    ChatRequest, ChatResponse,
    TaskRequest, TaskResponse, TaskStepResult,
    MemoryStoreRequest, MemorySearchRequest, MemorySearchResponse, MemoryEntry,
    PreferenceSetRequest,
    SystemStatus, HistoryResponse, ChatMessage, MessageRole,
    SuccessResponse, ErrorResponse,
    SystemMetrics, AgentStatusModel, AgentSystemStatus,
    OnboardingDiagnosticsResponse, DiagnosticItem,
    OnboardingConfigureRequest, OnboardingConfigureResponse,
)
from api.auth import create_access_token, revoke_token, require_auth, AuthRequired, _bearer_scheme
from core.logger import log, error_log
from core.security import owner_auth, guard
from api.ws_manager import ws_manager
from core.brain import Brain as JarvisBrain
from core.memory import JarvisMemory

# ─── Application State ────────────────────────────────────────────────────────
_START_TIME: float = 0.0
_brain:   JarvisBrain  | None = None
_memory:  JarvisMemory | None = None
_voice_mgr = None


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _brain, _memory, _START_TIME
    _START_TIME = time.time()
    log.info("JARVIS API starting up...")

    from dotenv import load_dotenv
    load_dotenv()
    from core.config import get_api_key

    try:
        try:
            _memory  = JarvisMemory()
        except Exception as mem_err:
            error_log.error(f"Resilient memory initialization fallback: {mem_err}")
            _memory = None

        _brain   = JarvisBrain(api_key=get_api_key(), memory=_memory)
        log.info("API subsystems initialised successfully.")

        # Register UI/WebSocket security confirmation handler so high-risk tools don't block on terminal input
        from typing import Any
        from core.security import guard, mask_sensitive_data
        main_loop = asyncio.get_running_loop()
        ws_manager.set_main_loop(main_loop)

        def _api_confirmation_handler(tool_name: str, args: dict, risk_level: Any) -> tuple[bool, str]:
            from core.brain.task_model import current_execution_context
            ctx = current_execution_context.get()
            session_id = ctx.session_id if ctx else None
            user_id = ctx.user_id if ctx else None
            task_id = ctx.request_id if ctx else None

            conf_id, event = guard.create_pending_confirmation(
                tool_name, args, risk_level, timeout_sec=60,
                session_id=session_id, user_id=user_id, task_id=task_id
            )
            risk_str = risk_level.value if hasattr(risk_level, "value") else str(risk_level)

            # Deliver structured confirmation event strictly to owning session (P0-3 privacy)
            conf_payload = {
                "type": "WAITING_FOR_CONFIRMATION",
                "confirmation_id": conf_id,
                "session_id": session_id,
                "user_id": user_id,
                "task_id": task_id,
                "action": f"Execute {tool_name}",
                "tool_name": tool_name,
                "tool": tool_name,
                "args": mask_sensitive_data(args),
                "parameters": mask_sensitive_data(args),
                "risk_level": risk_str,
                "risk_reason": f"High-risk action requiring owner approval: {tool_name}",
                "timeout_seconds": 60,
                "message": f"Tool '{tool_name}' requires approval ({risk_str})."
            }
            if session_id:
                ws_manager.send_confirmation_to_session(session_id, conf_payload)

            finished = event.wait(timeout=60.0)
            if not finished:
                guard.remove_confirmation(conf_id)
                return False, "Confirmation request timed out after 60 seconds."

            with guard._confirm_lock:
                conf = guard._pending_confirmations.get(conf_id, {})
                approved = conf.get("approved", False)

            # Clean up completed confirmation from pending storage
            guard.remove_confirmation(conf_id)
            return approved, "Approved via UI/WebSocket" if approved else "Denied via UI/WebSocket"

        guard.register_confirmation_handler(_api_confirmation_handler)
        
        # Start Voice Manager if enabled
        import os
        if os.getenv("JARVIS_VOICE_MODE") == "1":
            try:
                from core.voice_manager import ContinuousVoiceManager
                global _voice_mgr
                _voice_mgr = ContinuousVoiceManager(brain=_brain)
                _voice_mgr.start()
            except Exception as voice_err:
                error_log.error(f"Resilient Voice Manager startup fallback: {voice_err}")

        # Restore pending reminders on startup (Phase 7.0)
        try:
            from tools.everyday_tools import restore_pending_reminders_on_startup
            res = restore_pending_reminders_on_startup()
            log.info(f"Restored pending reminders on startup: {res}")
        except Exception as rem_err:
            error_log.error(f"Resilient reminder restoration fallback: {rem_err}")
            
    except Exception as e:
        error_log.error(f"API startup warning: {e}. Proceeding with degraded capability.")

    yield

    # Shutdown
    if _voice_mgr:
        _voice_mgr.stop()
    log.info("JARVIS API shutting down.")


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "JARVIS AI Operating System API",
    description = "Production API for the JARVIS personal AI OS",
    version     = "2.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = False,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def set_server_brain(brain: JarvisBrain, memory: JarvisMemory = None):
    global _brain, _memory
    _brain = brain
    if memory:
        _memory = memory

def _get_brain() -> JarvisBrain:
    if _brain is None:
        raise HTTPException(status_code=503, detail="AI Brain not initialised.")
    return _brain

def _get_memory() -> JarvisMemory:
    if _memory is None:
        raise HTTPException(status_code=503, detail="Memory system not initialised.")
    return _memory

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Auth Routes ─────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=AuthResponse, tags=["Auth"])
async def login(body: AuthRequest):
    """Authenticate with the owner PIN. Returns a JWT access token."""
    if not owner_auth.verify_pin(body.pin):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect PIN.",
        )
    token, expires = create_access_token()
    return AuthResponse(
        access_token=token,
        expires_in=expires,
        message="Authentication successful. JARVIS systems unlocked.",
    )


@app.post("/auth/set-pin", response_model=SuccessResponse, tags=["Auth"])
async def set_pin(body: SetPinRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme)):
    """
    Set or change the owner PIN.
    First-run: no auth required. Subsequent calls require Bearer token.
    """
    from core.security import PIN_FILE
    if PIN_FILE.exists():
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to change existing owner PIN.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        from api.auth import decode_token
        if not decode_token(credentials.credentials):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if body.new_pin != body.confirm_pin:
        raise HTTPException(status_code=400, detail="PINs do not match.")
    if len(body.new_pin) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 characters.")
    owner_auth.set_pin(body.new_pin)
    return SuccessResponse(message="Owner PIN configured successfully.")


@app.post("/auth/logout", response_model=SuccessResponse, tags=["Auth"])
async def logout(credentials: AuthRequired):
    """Invalidate the current session token."""
    owner_auth.logout()
    return SuccessResponse(message="Logged out. Session terminated.")


def _extract_auth_user(auth: Any) -> str:
    if isinstance(auth, dict):
        return auth.get("sub", "default")
    return getattr(auth, "username", "default")


def _extract_auth_session(auth: Any) -> str:
    if isinstance(auth, dict):
        return auth.get("session_id") or auth.get("jti") or auth.get("sub", "default_session")
    return getattr(auth, "session_id", None) or getattr(auth, "username", "default_session")


# ─── Chat Routes ─────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(body: ChatRequest, auth: AuthRequired):
    """Send a message and receive JARVIS's response (non-streaming)."""
    brain = _get_brain()
    try:
        caller_user = _extract_auth_user(auth)
        session_id = _extract_auth_session(auth)
        if body.message.strip().lower() == "reset":
            brain.reset_chat(session_id=session_id, user_id=caller_user)
            return ChatResponse(
                response="Chat session reset. Memory cleared.",
                model=brain._model_name,
                timestamp=_ts(),
            )
        from core.brain.task_model import ExecutionContext
        ctx = ExecutionContext(
            store_memory=body.store,
            session_id=session_id,
            user_id=caller_user
        )
        response = await asyncio.to_thread(brain.process_input, body.message, body.store, ctx)
        return ChatResponse(
            response=response,
            model=brain._model_name,
            timestamp=_ts(),
        )
    except Exception as e:
        error_log.error(f"/chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/stream", tags=["Chat"])
async def chat_stream(body: ChatRequest, auth: AuthRequired):
    """Stream JARVIS's response token-by-token via Server-Sent Events."""
    brain = _get_brain()
    caller_user = _extract_auth_user(auth)
    session_id = _extract_auth_session(auth)
    from core.brain.task_model import ExecutionContext
    import threading
    cancel_token = threading.Event()
    ctx = ExecutionContext(
        store_memory=body.store,
        session_id=session_id,
        user_id=caller_user,
        cancellation_token=cancel_token
    )
    ws_manager.register_active_task(session_id, ctx, user_id=caller_user)

    async def _generate():
        try:
            if body.message.strip().lower() == "reset":
                brain.reset_chat(session_id=session_id, user_id=caller_user)
                yield f"data: {json.dumps({'chunk': 'Chat session reset. Memory cleared.'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            async for chunk in brain.process_input_stream(body.message, interrupt_event=cancel_token, context=ctx):
                if cancel_token.is_set():
                    yield f"data: {json.dumps({'interrupted': True})}\n\n"
                    break
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            ws_manager.unregister_active_task(session_id)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ─── Voice Routes ─────────────────────────────────────────────────────────────

@app.post("/voice/toggle", response_model=SuccessResponse, tags=["Voice"])
async def toggle_voice(auth: AuthRequired):
    """Toggle continuous voice listening."""
    global _voice_mgr
    if not _voice_mgr:
        raise HTTPException(status_code=503, detail="Voice manager not running.")
        
    if _voice_mgr.is_running:
        _voice_mgr.stop()
        return SuccessResponse(message="Voice listening paused.")
    else:
        _voice_mgr.start()
        return SuccessResponse(message="Voice listening resumed.")

from pydantic import BaseModel

class VoiceSettingsRequest(BaseModel):
    engine: str
    profile: str

@app.post("/settings/voice", response_model=SuccessResponse, tags=["Voice"])
async def update_voice_settings(body: VoiceSettingsRequest, auth: AuthRequired):
    """Update voice engine and profile."""
    import os
    os.environ["VOICE_ENGINE"] = body.engine
    os.environ["VOICE_PROFILE"] = body.profile
    global _voice_mgr
    if _voice_mgr and hasattr(_voice_mgr, 'voice'):
        _voice_mgr.voice.engine_type = body.engine
        _voice_mgr.voice.profile = body.profile
    return SuccessResponse(message="Voice settings updated.")

class TTSRequest(BaseModel):
    text: str

@app.post("/voice/tts", response_model=SuccessResponse, tags=["Voice"])
async def test_tts(body: TTSRequest, auth: AuthRequired):
    """Test text-to-speech engine."""
    from core.voice import VoiceInterface
    try:
        tts = VoiceInterface()
        import threading
        
        # Create a simple generator that yields the text
        def text_generator():
            yield body.text
            
        dummy_event = threading.Event()
        tts.speak_stream(text_generator(), dummy_event)
        return SuccessResponse(message="TTS executed successfully.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── WebSocket Streaming ──────────────────────────────────────────────────────

@app.websocket("/ws/jarvis")
async def websocket_jarvis(ws: WebSocket):
    """
    Unified WebSocket endpoint for real-time bidirectional communication.
    Handles UI state streaming, text streaming, and execution feeds.
    """
    await ws_manager.connect(ws)

    # Check query params for token at initial connection time
    query_token = ws.query_params.get("token", "").replace("Bearer ", "").strip()
    if query_token:
        from api.auth import decode_token
        user = decode_token(query_token)
        if user:
            ws_manager.authenticate_connection(
                ws,
                token=query_token,
                user_id=user.get("sub", "default"),
                session_id=user.get("session_id")
            )

    try:
        while True:
            data = await ws.receive_json()

            # Client can send commands
            cmd = data.get("command", "")
            
            # Authenticate connection whenever token is supplied
            token = data.get("token", "").replace("Bearer ", "").strip()
            if token:
                from api.auth import decode_token
                user = decode_token(token)
                if user:
                    ws_manager.authenticate_connection(
                        ws,
                        token=token,
                        user_id=user.get("sub", "default"),
                        session_id=user.get("session_id")
                    )

            if cmd == "auth":
                if ws_manager.is_authenticated(ws):
                    await ws.send_json({
                        "type": "AUTH_SUCCESS",
                        "user": ws_manager.get_user_id(ws),
                        "session_id": ws_manager.get_session_id(ws)
                    })
                else:
                    await ws.send_json({"type": "AUTH_FAILED", "error": "Invalid token."})
                continue

            if cmd == "chat":
                # Validate token or existing authenticated connection
                if not ws_manager.is_authenticated(ws):
                    await ws.send_json({"error": "Unauthorised. Provide a valid token."})
                    continue

                message = data.get("message", "").strip()
                if not message:
                    continue

                # Server-derived session identity
                session_id = ws_manager.get_session_id(ws)
                user_id = ws_manager.get_user_id(ws)
                store_mem = data.get("store", True)
                brain = _get_brain()
                from core.brain.task_model import ExecutionContext
                import threading
                cancel_token = threading.Event()
                ctx = ExecutionContext(
                    session_id=session_id,
                    user_id=user_id,
                    store_memory=store_mem,
                    cancellation_token=cancel_token
                )
                ws_manager.register_active_task(session_id, ctx)
                try:
                    async for chunk in brain.process_input_stream(message, interrupt_event=cancel_token, context=ctx):
                        if cancel_token.is_set():
                            break
                        await asyncio.sleep(0)
                        
                    await ws_manager.send_stream_end_to_session(session_id)
                except Exception as e:
                    await ws_manager.send_status_to_session(session_id, "ERROR")
                    await ws.send_json({"error": str(e)})
                finally:
                    ws_manager.unregister_active_task(session_id)

            elif cmd == "interrupt":
                if not ws_manager.is_authenticated(ws):
                    await ws.send_json({
                        "type": "AUTH_FAILED",
                        "error": "Unauthorised. Interrupt requires an authenticated connection.",
                        "success": False
                    })
                    continue

                # Derive session identity strictly from the authenticated WebSocket connection
                session_id = ws_manager.get_session_id(ws)
                cancelled = ws_manager.cancel_active_task(session_id, "User requested interruption via WebSocket")
                
                # If continuous voice is running, enforce explicit session owner policy (P0-2)
                global _voice_mgr
                if _voice_mgr and hasattr(_voice_mgr, "stop_speaking_for_session"):
                    _voice_mgr.stop_speaking_for_session(session_id)
                elif _voice_mgr and hasattr(_voice_mgr, "voice"):
                    try:
                        _voice_mgr.voice.stop_speaking()
                    except Exception as ve:
                        log.debug(f"Voice stop speaking notice: {ve}")

                await ws_manager.send_status_to_session(session_id, "IDLE")
                await ws.send_json({
                    "type": "TASK_CANCELLED",
                    "session_id": session_id,
                    "cancelled": cancelled,
                    "reason": "WebSocket interrupt"
                })

            elif cmd == "confirm":
                if not ws_manager.is_authenticated(ws):
                    await ws.send_json({
                        "type": "CONFIRMATION_RESULT",
                        "error": "Unauthorised. Confirmation mutations require an authenticated connection.",
                        "success": False
                    })
                    continue

                conf_id = data.get("confirmation_id")
                approved = bool(data.get("approved", False))
                # Derive identity strictly from server-side authenticated connection (never trust client payload)
                conn_session_id = ws_manager.get_session_id(ws)
                conn_user_id = ws_manager.get_user_id(ws)
                from core.security import guard
                success = guard.submit_confirmation(
                    conf_id,
                    approved,
                    session_id=conn_session_id,
                    user_id=conn_user_id
                )
                await ws.send_json({
                    "type": "CONFIRMATION_RESULT",
                    "confirmation_id": conf_id,
                    "approved": approved,
                    "success": success
                })
                if success:
                    ws_manager.send_confirmation_to_session(conn_session_id, {
                        "type": "CONFIRMATION_PROCESSED",
                        "confirmation_id": conf_id,
                        "approved": approved,
                        "success": success
                    })

            elif cmd == "status_update":
                if not ws_manager.is_authenticated(ws):
                    await ws.send_json({
                        "type": "AUTH_FAILED",
                        "error": "Unauthorised. Status update requires an authenticated connection.",
                        "success": False
                    })
                    continue

                conn_session_id = ws_manager.get_session_id(ws)
                conn_user_id = ws_manager.get_user_id(ws)
                status = data.get("status", "IDLE")
                log.info(f"UI Status changed to: {status}")
                if status == "LISTENING":
                    try:
                        brain = _get_brain()
                        turns = brain.memory_manager.get_recent_conversation(n=1, session_id=conn_session_id, user_id=conn_user_id)
                        if turns:
                            brain.context.start_prefetch(turns[0]["content"], session_id=conn_session_id, user_id=conn_user_id)
                    except Exception as e:
                        log.warning(f"Could not trigger pre-fetch on LISTENING status: {e}")

    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as e:
        error_log.error(f"WebSocket error: {e}")
        ws_manager.disconnect(ws)
        try:
            await ws.close()
        except Exception:
            pass


# ─── History Routes ───────────────────────────────────────────────────────────

@app.get("/history", response_model=HistoryResponse, tags=["Chat"])
async def get_history(auth: AuthRequired, n: int = 20):
    """Retrieve recent conversation history (last N turns) scoped to the caller's session (P1-5)."""
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)
    memory = _get_memory()
    turns  = memory.get_recent_conversation(n=n, session_id=caller_session, user_id=caller_user)
    return HistoryResponse(
        turns=[
            ChatMessage(
                role      = MessageRole.USER if t["role"] == "user" else MessageRole.ASSISTANT,
                content   = t["content"],
                timestamp = t.get("timestamp"),
            )
            for t in turns
        ],
        count = len(turns),
        total = memory.conversations.count(session_id=caller_session, user_id=caller_user),
    )


@app.delete("/history", response_model=SuccessResponse, tags=["Chat"])
async def clear_history(auth: AuthRequired):
    """Clear conversation history for the authenticated caller's session (P1-5)."""
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)
    memory = _get_memory()
    memory.conversations.clear(session_id=caller_session, user_id=caller_user)
    return SuccessResponse(message="Conversation history cleared.")


# ─── Task Routes ─────────────────────────────────────────────────────────────

@app.post("/task", response_model=TaskResponse, tags=["Tasks"])
async def execute_task(body: TaskRequest, auth: AuthRequired):
    """Submit an autonomous multi-step task for JARVIS to plan and execute."""
    brain = _get_brain()
    caller_user = _extract_auth_user(auth)
    session_id = _extract_auth_session(auth)
    from core.brain.task_model import ExecutionContext, TaskStatus
    import uuid
    import threading
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    cancel_token = threading.Event()
    ctx = ExecutionContext(
        task_id=task_id,
        request_id=task_id,
        session_id=session_id,
        user_id=caller_user,
        store_memory=body.store,
        cancellation_token=cancel_token
    )
    ws_manager.register_active_task(session_id, ctx, task_id=task_id, user_id=caller_user)

    try:
        # P0-2: Deliver task initiation strictly to owning session if available (never broadcast)
        start_event = {
            "type": "execution_event",
            "event_type": "task_started",
            "goal": body.task,
            "task_id": task_id,
            "node_id": "root",
            "description": body.task,
            "status": "running"
        }
        if session_id:
            await ws_manager.send_to_session(session_id, start_event)
        else:
            log.info(f"[Task Execution] Task {task_id} started without session - skipping websocket delivery.")

        # Run Action-First execution via AssistantOrchestrator
        result_text = await asyncio.to_thread(brain.execute_task, body.task, body.store, ctx)

        # P0-3 & P0-6: Derive completed and status string from actual AssistantTask
        from core.brain.task_model import map_task_status_to_api
        actual_task = getattr(ctx, "task", None)
        real_task_id = getattr(actual_task, "task_id", None) or getattr(actual_task, "id", None) or task_id
        status_enum = getattr(actual_task, "status", None)
        completed, status_str = map_task_status_to_api(status_enum, is_cancelled=cancel_token.is_set())

        # P0-2: Deliver task completion strictly to owning session if available (never broadcast)
        completion_event = {
            "type": "execution_event",
            "event_type": "task_completed",
            "goal": body.task,
            "task_id": real_task_id,
            "node_id": "root",
            "description": body.task,
            "status": status_str,
            "result": result_text[:200]
        }
        if session_id:
            await ws_manager.send_to_session(session_id, completion_event)
        else:
            log.info(f"[Task Execution] Task {real_task_id} completed without session - skipping websocket delivery.")

        return TaskResponse(
            task      = body.task,
            completed = completed,
            status    = status_str,
            task_id   = real_task_id,
            steps     = [
                TaskStepResult(
                    index       = 0,
                    description = "AssistantOrchestrator Canonical Execution Engine",
                    status      = status_str,
                    result      = result_text,
                )
            ],
            summary   = result_text,
        )
    except Exception as e:
        error_log.error(f"/task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ws_manager.unregister_active_task(session_id, task_obj=ctx)
        ws_manager.unregister_active_task(task_id, task_obj=ctx)
        actual_task = getattr(ctx, "task", None)
        if actual_task and getattr(actual_task, "task_id", None):
            ws_manager.unregister_active_task(actual_task.task_id, task_obj=actual_task)


class TaskInterruptRequest(BaseModel):
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    reason: str = "User requested cancellation"


@app.post("/tasks/interrupt", response_model=SuccessResponse, tags=["Tasks"])
async def interrupt_task(body: TaskInterruptRequest, auth: AuthRequired):
    """Cancel an active task or session execution with strict fail-closed user AND session ownership validation (P1-5)."""
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)

    if not caller_user or not caller_session:
        raise HTTPException(status_code=403, detail="Forbidden: Caller identity metadata is incomplete.")

    if body.task_id:
        # Cancel by task_id: resolve owner metadata by task_id
        meta = ws_manager.get_task_metadata(body.task_id)
        if not meta:
            # Unknown task -> nothing cancelled
            return SuccessResponse(message="No active task found for the specified task ID.")

        task_owner_user = meta.get("user_id")
        task_owner_session = meta.get("session_id")

        if not task_owner_user or not task_owner_session:
            raise HTTPException(status_code=403, detail="Forbidden: Task ownership metadata is absent or incomplete.")

        if task_owner_user != caller_user:
            raise HTTPException(status_code=403, detail="Forbidden: Cannot interrupt another user's task.")
        if task_owner_session != caller_session:
            raise HTTPException(status_code=403, detail="Forbidden: Cannot interrupt a task belonging to another session.")

        cancelled = ws_manager.cancel_active_task(body.task_id, reason=body.reason)
        target_task_id = body.task_id
        target_session_id = task_owner_session
    else:
        # Cancel by session: use server-side identity and strictly ignore spoofed client session IDs
        meta = ws_manager.get_task_metadata(caller_session)
        if not meta:
            return SuccessResponse(message="No active task found for the specified session.")

        task_owner_user = meta.get("user_id")
        task_owner_session = meta.get("session_id")

        if not task_owner_user or not task_owner_session:
            raise HTTPException(status_code=403, detail="Forbidden: Task ownership metadata is absent or incomplete.")

        if task_owner_user != caller_user:
            raise HTTPException(status_code=403, detail="Forbidden: Cannot interrupt another user's session.")
        if task_owner_session != caller_session:
            raise HTTPException(status_code=403, detail="Forbidden: Cannot interrupt a task belonging to another session.")

        cancelled = ws_manager.cancel_active_task(caller_session, reason=body.reason)
        target_task_id = meta.get("task_id")
        target_session_id = caller_session

    if not cancelled:
        return SuccessResponse(message="No active task found for the specified session or task ID.")

    # P0-3: Send cancellation event strictly to authorized session (no global broadcast)
    if target_session_id:
        await ws_manager.send_to_session(target_session_id, {
            "type": "TASK_CANCELLED",
            "task_id": target_task_id,
            "session_id": target_session_id,
            "cancelled": cancelled
        })
    return SuccessResponse(message="Task cancellation signalled.")


@app.get("/tasks/history", tags=["Tasks"])
async def get_task_history(auth: AuthRequired, limit: int = 50):
    """Retrieve persisted multi-step task history across application restarts, filtered by authenticated owner."""
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)
    from core.brain.task_store import task_store
    tasks = task_store.list_tasks(limit=limit, user_id=caller_user, session_id=caller_session)
    return {"tasks": tasks}


@app.get("/tasks/reminders", tags=["Tasks"])
async def get_active_reminders(auth: AuthRequired):
    """
    Returns active reminders and pending count for Everyday Mode dashboard.
    """
    from tools.everyday_tools import list_and_manage_reminders
    result = list_and_manage_reminders(action="list")
    return {
        "success": True,
        "active_reminders": result.get("active_reminders", []),
        "pending_count": result.get("pending_count", len(result.get("active_reminders", []))),
    }


@app.delete("/tasks/reminders/{reminder_id}", tags=["Tasks"])
async def cancel_reminder_by_id(reminder_id: str, auth: AuthRequired):
    """
    Cancels a scheduled reminder by reminder ID.
    """
    from tools.everyday_tools import list_and_manage_reminders
    result = list_and_manage_reminders(action="cancel", reminder_id=reminder_id)
    return result


class TodoCreateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    notes: Optional[str] = ""
    category: Optional[str] = "todo"
    due_date: Optional[str] = None


@app.get("/tasks/todos", tags=["Tasks"])
async def get_personal_todos(auth: AuthRequired, category: Optional[str] = None):
    """Returns personal to-dos list for the Everyday Mode dashboard."""
    from tools.everyday_tools import manage_personal_notes_and_todos
    result = manage_personal_notes_and_todos(action="list", category=category or "all")
    return result


@app.post("/tasks/todos", tags=["Tasks"])
async def create_personal_todo(body: TodoCreateRequest, auth: AuthRequired):
    """Create a personal to-do item."""
    from tools.everyday_tools import manage_personal_notes_and_todos
    item_title = (body.title or body.content or "").strip()
    if not item_title:
        raise HTTPException(status_code=400, detail="title or content is required to create a to-do")
    result = manage_personal_notes_and_todos(
        action="add",
        title=item_title,
        content=body.content or item_title,
        notes=body.notes or "",
        category=body.category or "todo",
        due_date=body.due_date
    )
    return result


@app.post("/tasks/todos/{item_id}/complete", tags=["Tasks"])
async def complete_personal_todo(item_id: str, auth: AuthRequired):
    """Marks a personal to-do item as completed."""
    from tools.everyday_tools import manage_personal_notes_and_todos
    result = manage_personal_notes_and_todos(action="complete", item_id=item_id)
    return result


@app.delete("/tasks/todos/{item_id}", tags=["Tasks"])
async def delete_personal_todo(item_id: str, auth: AuthRequired):
    """Deletes a personal to-do item."""
    from tools.everyday_tools import manage_personal_notes_and_todos
    result = manage_personal_notes_and_todos(action="delete", item_id=item_id)
    return result


@app.get("/tasks/{task_id}", tags=["Tasks"])
async def get_task_detail(task_id: str, auth: AuthRequired):
    """Retrieve a specific persisted task record by ID, enforcing strict user and session ownership."""
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)
    from core.brain.task_store import task_store
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task_user = task.get("user_id")
    task_session = task.get("session_id")

    # P0-3: Fail closed: task detail must not be returned when ownership metadata is missing or incomplete
    if not task_user or not task_session:
        raise HTTPException(status_code=403, detail="Forbidden: Task ownership metadata is missing or incomplete.")

    if task_user != caller_user:
        raise HTTPException(status_code=403, detail="Forbidden: Task belongs to another user.")
    if task_session != caller_session:
        raise HTTPException(status_code=403, detail="Forbidden: Task belongs to another session.")

    return task


# ─── Security Confirmation Routes ─────────────────────────────────────────────

class ConfirmationRequest(BaseModel):
    approved: bool


@app.get("/security/confirmations", tags=["Security"])
async def list_pending_confirmations(auth: AuthRequired):
    """List active security confirmations strictly for caller authorization (P0-3)."""
    from core.security import guard
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)
    confirmations = guard.get_pending_confirmations(user_id=caller_user, session_id=caller_session)
    return {"confirmations": confirmations}


@app.post("/security/confirmations/{confirmation_id}", tags=["Security"])
async def respond_confirmation(confirmation_id: str, body: ConfirmationRequest, auth: AuthRequired):
    """Approve or deny a pending security confirmation with server-side identity validation (P0-2)."""
    from core.security import guard
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)
    success = guard.submit_confirmation(
        confirmation_id,
        body.approved,
        session_id=caller_session,
        user_id=caller_user
    )
    if not success:
        raise HTTPException(status_code=403, detail="Confirmation ID not found, expired, or unauthorized.")
    return SuccessResponse(message=f"Confirmation {'approved' if body.approved else 'denied'}.")



# ─── Static UI Serving ────────────────────────────────────────────────────────
ui_path = Path(__file__).parent.parent / "ui"
if ui_path.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_path)), name="ui")

    @app.get("/", tags=["UI"])
    async def serve_ui():
        """Redirect root to the UI."""
        return FileResponse(str(ui_path / "index.html"))


# ─── Memory Routes ────────────────────────────────────────────────────────────

@app.post("/memory/search", response_model=MemorySearchResponse, tags=["Memory"])
async def search_memory(body: MemorySearchRequest, auth: AuthRequired):
    """Semantically search stored memories scoped to caller user (P0-2)."""
    caller_user = _extract_auth_user(auth)
    memory  = _get_memory()
    results = memory.retrieve_memories(
        body.query,
        top_k    = body.top_k,
        category = body.category.value if body.category else None,
        user_id  = caller_user,
    )
    return MemorySearchResponse(
        query   = body.query,
        results = [
            MemoryEntry(
                id        = r["id"],
                content   = r["content"],
                category  = r["metadata"].get("category", "?"),
                distance  = r.get("distance"),
                timestamp = r["metadata"].get("timestamp"),
            )
            for r in results
        ],
        count   = len(results),
    )


@app.post("/memory", response_model=SuccessResponse, tags=["Memory"])
async def store_memory(body: MemoryStoreRequest, auth: AuthRequired):
    """Store a new memory entry with explicit caller ownership (P0-2)."""
    caller_user = _extract_auth_user(auth)
    memory = _get_memory()
    doc_id = memory.store_memory(
        body.content,
        category = body.category.value,
        metadata = body.metadata,
        encrypt  = body.encrypt,
        user_id  = caller_user,
    )
    return SuccessResponse(message=f"Memory stored with ID: {doc_id}")


@app.post("/memory/preference", response_model=SuccessResponse, tags=["Memory"])
async def set_preference(body: PreferenceSetRequest, auth: AuthRequired):
    """Store or update a user preference (P0-2)."""
    caller_user = _extract_auth_user(auth)
    memory = _get_memory()
    memory.store_preference(body.key, body.value, user_id=caller_user)
    return SuccessResponse(message=f"Preference '{body.key}' saved.")


@app.get("/memory/preference/{key}", tags=["Memory"])
async def get_preference(key: str, auth: AuthRequired):
    """Retrieve a stored preference by key for caller user (P0-2)."""
    caller_user = _extract_auth_user(auth)
    memory = _get_memory()
    value  = memory.get_preference(key, user_id=caller_user)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Preference '{key}' not found.")
    return {"key": key, "value": value}


@app.delete("/memory", response_model=SuccessResponse, tags=["Memory"])
async def clear_memory(auth: AuthRequired, confirm: bool = False):
    """
    Clear caller user's memory (P0-2). DESTRUCTIVE.
    Must pass `?confirm=true` query parameter to execute.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Safety check: pass ?confirm=true to confirm memory wipe.",
        )
    caller_user = _extract_auth_user(auth)
    if not caller_user:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Verified user identity required to clear memory.",
        )
    memory = _get_memory()
    memory.clear_all(user_id=caller_user)
    return SuccessResponse(message="User memory cleared.")


# ─── System Routes ────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """Unauthenticated fast health check endpoint for launchers and monitoring."""
    return {
        "status": "ok",
        "healthy": True,
        "version": "3.0.0",
        "uptime_seconds": round(time.time() - _START_TIME, 1) if _START_TIME > 0 else 0.0
    }


@app.get("/status", response_model=SystemStatus, tags=["System"])
async def get_status(auth: AuthRequired):
    """Return current system health and resource status."""
    caller_user = _extract_auth_user(auth)
    brain  = _get_brain()
    memory = _get_memory()
    b_status = brain.status()
    return SystemStatus(
        model          = b_status["model"],
        tools_count    = b_status["tools_count"],
        memory_active  = b_status["memory_active"],
        planner_active = b_status["planner_active"],
        memory_stats   = memory.stats(user_id=caller_user),
        uptime_seconds = round(time.time() - _START_TIME, 1),
    )


@app.get("/", tags=["System"])
async def root():
    """API root — serves the Mission Control UI dashboard."""
    ui_path = Path(__file__).parent.parent / "ui" / "index.html"
    if ui_path.exists():
        return FileResponse(ui_path, media_type="text/html")
    return {
        "name":    "JARVIS AI Operating System",
        "version": "3.0.0",
        "status":  "online",
        "architecture": "modular-multi-agent",
        "docs":    "/docs",
    }


# ─── Agent Routes (Phase 4) ───────────────────────────────────────────────────

@app.get("/agents/status", response_model=AgentSystemStatus, tags=["Agents"])
async def get_agents_status(auth: AuthRequired):
    """Return status of all registered agents."""
    brain = _get_brain()
    # Check if brain has agent bus
    if hasattr(brain, 'agent_bus') and brain.agent_bus:
        agents = brain.agent_bus.list_agents()
        return AgentSystemStatus(
            agents=[AgentStatusModel(**a) for a in agents],
            bus_messages=len(brain.agent_bus.get_message_log()),
            total_agents=brain.agent_bus.agent_count,
        )
    return AgentSystemStatus(agents=[], total_agents=0)


@app.get("/tools", tags=["System"])
async def list_tools(auth: AuthRequired):
    """List all registered tools with their categories and risk levels."""
    brain = _get_brain()
    return {
        "tools": brain.tools.list_tools(),
        "categories": brain.tools.get_categories(),
        "total": brain.tools.tool_count,
    }


@app.get("/metrics", response_model=SystemMetrics, tags=["System"])
async def get_metrics(auth: AuthRequired):
    """Return real-time system metrics."""
    brain = _get_brain()
    metrics = {"uptime_seconds": round(time.time() - _START_TIME, 1)}
    metrics["tools_registered"] = brain.tools.tool_count

    try:
        import psutil
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        metrics["ram_percent"] = ram.percent
        metrics["ram_used_gb"] = round(ram.used / 1e9, 2)
        metrics["ram_total_gb"] = round(ram.total / 1e9, 2)
        disk = psutil.disk_usage("/")
        metrics["disk_percent"] = disk.percent
    except ImportError:
        pass

    return SystemMetrics(**metrics)

@app.post("/optimize", response_model=SuccessResponse, tags=["Agents"])
async def trigger_optimization(auth: AuthRequired):
    """Trigger the Refiner Agent to optimize recent workflows scoped to the authenticated caller owner (P0-1, P0-4)."""
    caller_user = _extract_auth_user(auth)
    caller_session = _extract_auth_session(auth)
    if not caller_user:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Verified user identity required for workflow optimization."
        )

    brain = _get_brain()
    if hasattr(brain, '_refiner') and brain._refiner:
        from core.agents.base_agent import AgentMessage
        msg = AgentMessage(
            sender=caller_user,
            recipient="refiner",
            content="optimize",
            user_id=caller_user,
            session_id=caller_session,
            system_authorized=False,
        )
        res = brain._refiner.process(msg)
        if res.success:
            return SuccessResponse(message=res.content)
        else:
            raise HTTPException(status_code=500, detail=res.content)
    raise HTTPException(status_code=503, detail="Refiner Agent not available.")


# ─── Onboarding & Diagnostics Routes ──────────────────────────────────────────

_DIAGNOSTICS_CACHE: dict[str, Any] = {"data": None, "timestamp": 0.0}

def _check_diagnostics_internal() -> dict[str, Any]:
    now = time.time()
    if _DIAGNOSTICS_CACHE["data"] and (now - _DIAGNOSTICS_CACHE["timestamp"]) < 5.0:
        return _DIAGNOSTICS_CACHE["data"]

    import os
    from datetime import datetime, timezone

    # 1. LLM Readiness
    has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    has_fallback = bool(os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OLLAMA_HOST"))
    llm_ready = has_gemini or has_fallback
    if has_gemini:
        llm_details = "Google Gemini API key configured and operational."
    elif has_fallback:
        llm_details = "Fallback LLM engine key configured."
    else:
        llm_details = "No LLM API key detected in .env. Configure GEMINI_API_KEY."

    # 2. Voice STT Readiness
    voice_stt_ready = False
    stt_details = ""
    try:
        import faster_whisper
        voice_stt_ready = True
        stt_details = "faster-whisper STT engine installed and operational."
    except Exception as e:
        stt_details = f"faster-whisper not available: {e}"

    # 3. Voice TTS Readiness
    voice_tts_ready = False
    tts_details = ""
    try:
        import pyttsx3
        voice_tts_ready = True
        tts_details = "pyttsx3 native speech synthesis operational."
    except Exception as e:
        tts_details = f"TTS engine error: {e}"

    # 4. Playwright Browser Readiness
    browser_ready = False
    browser_details = ""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exec_path = p.chromium.executable_path
            if exec_path and os.path.exists(exec_path):
                browser_ready = True
                browser_details = f"Playwright Chromium browser ready at {exec_path}."
            else:
                browser_details = "Playwright Chromium binary not found on disk."
    except Exception as e:
        browser_details = f"Playwright browser check: {e}"

    # 5. Windows Native OCR Readiness
    ocr_ready = False
    ocr_details = ""
    try:
        import winocr
        ocr_ready = True
        ocr_details = "Windows Native OCR (winocr) available."
    except Exception as e:
        ocr_details = f"winocr not available: {e}"

    all_ready = llm_ready and voice_stt_ready and voice_tts_ready and browser_ready and ocr_ready

    data = {
        "all_ready": all_ready,
        "llm_ready": llm_ready,
        "voice_stt_ready": voice_stt_ready,
        "voice_tts_ready": voice_tts_ready,
        "browser_ready": browser_ready,
        "ocr_ready": ocr_ready,
        "diagnostics": {
            "llm": {"ready": llm_ready, "details": llm_details, "optional": False},
            "voice_stt": {"ready": voice_stt_ready, "details": stt_details, "optional": False},
            "voice_tts": {"ready": voice_tts_ready, "details": tts_details, "optional": False},
            "browser": {"ready": browser_ready, "details": browser_details, "optional": True},
            "ocr": {"ready": ocr_ready, "details": ocr_details, "optional": True},
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _DIAGNOSTICS_CACHE["data"] = data
    _DIAGNOSTICS_CACHE["timestamp"] = now
    return data


@app.get("/onboarding/diagnostics", response_model=OnboardingDiagnosticsResponse, tags=["Onboarding"])
async def get_onboarding_diagnostics(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme)
):
    """
    Returns real-time readiness checks for LLM, Voice STT, Voice TTS, Browser, and OCR.
    Accessible without credentials on initial setup or with Bearer token.
    """
    from core.security import PIN_FILE
    if PIN_FILE.exists() and credentials:
        from api.auth import decode_token
        decode_token(credentials.credentials)
    data = await asyncio.to_thread(_check_diagnostics_internal)
    return OnboardingDiagnosticsResponse(**data)


@app.post("/onboarding/configure", response_model=OnboardingConfigureResponse, tags=["Onboarding"])
async def configure_onboarding(
    body: OnboardingConfigureRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme)
):
    """
    Allows first-run configuration of user name, preferred city, API key, and Owner PIN.
    If an Owner PIN is already configured, authentication is strictly required.
    """
    from core.security import PIN_FILE
    if PIN_FILE.exists():
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to modify existing system configuration.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        from api.auth import decode_token
        if not decode_token(credentials.credentials):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    configured_items: list[str] = []
    user_prefs_file = Path(r"D:\Jarvis\data\user_preferences.json")
    user_prefs_file.parent.mkdir(parents=True, exist_ok=True)
    prefs_data = {}
    if user_prefs_file.exists():
        try:
            with open(user_prefs_file, "r", encoding="utf-8") as f:
                prefs_data = json.load(f)
        except Exception:
            prefs_data = {}

    # 1. User Name
    if body.user_name:
        prefs_data["user_name"] = body.user_name.strip()
        configured_items.append("user_name")

    # 2. Preferred City
    if body.preferred_city:
        prefs_data["preferred_city"] = body.preferred_city.strip()
        configured_items.append("preferred_city")

    if body.user_name or body.preferred_city:
        with open(user_prefs_file, "w", encoding="utf-8") as f:
            json.dump(prefs_data, f, indent=2)

    # 3. Gemini API Key
    if body.gemini_api_key:
        api_key = body.gemini_api_key.strip()
        if len(api_key) > 5:
            env_file = Path(r"D:\Jarvis\.env")
            lines = []
            found = False
            if env_file.exists():
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped.startswith("GEMINI_API_KEY=") or stripped.startswith("export GEMINI_API_KEY="):
                            lines.append(f"GEMINI_API_KEY={api_key}\n")
                            found = True
                        else:
                            lines.append(line)
            if not found:
                lines.append(f"GEMINI_API_KEY={api_key}\n")
            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
            import os
            os.environ["GEMINI_API_KEY"] = api_key
            masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) >= 8 else "***"
            log.info(f"Configured GEMINI_API_KEY securely (masked: {masked})")
            configured_items.append("gemini_api_key")

    # 4. Owner PIN
    if body.owner_pin:
        if len(body.owner_pin) < 4:
            raise HTTPException(status_code=400, detail="Owner PIN must be at least 4 characters.")
        owner_auth.set_pin(body.owner_pin)
        configured_items.append("owner_pin")

    # Invalidate diagnostic cache after configuration
    _DIAGNOSTICS_CACHE["data"] = None

    msg = f"Successfully configured: {', '.join(configured_items)}" if configured_items else "No configuration changes requested."
    return OnboardingConfigureResponse(
        success=True,
        message=msg,
        configured_items=configured_items
    )


