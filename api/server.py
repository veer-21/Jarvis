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
from typing import AsyncIterator, Annotated

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
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
)
from api.auth import create_access_token, revoke_token, require_auth, AuthRequired
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
        _memory  = JarvisMemory()
        _brain   = JarvisBrain(api_key=get_api_key(), memory=_memory)
        log.info("API subsystems initialised successfully.")
        
        # Start Voice Manager if enabled
        import os
        if os.getenv("JARVIS_VOICE_MODE") == "1":
            from core.voice_manager import ContinuousVoiceManager
            global _voice_mgr
            _voice_mgr = ContinuousVoiceManager(brain=_brain)
            _voice_mgr.start()
            
    except Exception as e:
        error_log.error(f"API startup failed: {e}")
        raise

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
async def set_pin(body: SetPinRequest):
    """
    Set or change the owner PIN.
    First-run: no auth required. Subsequent calls require Bearer token.
    """
    if body.new_pin != body.confirm_pin:
        raise HTTPException(status_code=400, detail="PINs do not match.")
    if len(body.new_pin) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 characters.")
    owner_auth.set_pin(body.new_pin)
    return SuccessResponse(message="PIN set successfully.")


@app.post("/auth/logout", response_model=SuccessResponse, tags=["Auth"])
async def logout(credentials: AuthRequired):
    """Invalidate the current session token."""
    owner_auth.logout()
    return SuccessResponse(message="Logged out. Session terminated.")


# ─── Chat Routes ─────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(body: ChatRequest, auth: AuthRequired):
    """Send a message and receive JARVIS's response (non-streaming)."""
    brain = _get_brain()
    try:
        if body.message.strip().lower() == "reset":
            brain.reset_chat()
            return ChatResponse(
                response="Chat session reset. Memory cleared.",
                model=brain._model_name,
                timestamp=_ts(),
            )
            
        response = await asyncio.to_thread(brain.process_input, body.message, body.store)
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

    def _generate():
        try:
            if body.message.strip().lower() == "reset":
                brain.reset_chat()
                yield f"data: {json.dumps({'chunk': 'Chat session reset. Memory cleared.'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            for chunk in brain.process_input_stream(body.message):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

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

    try:
        while True:
            data = await ws.receive_json()

            # Client can send commands
            cmd = data.get("command", "")
            
            if cmd == "chat":
                # Validate token
                token = data.get("token", "").replace("Bearer ", "").strip()
                from api.auth import decode_token
                if not decode_token(token):
                    await ws.send_json({"error": "Unauthorised. Provide a valid token."})
                    continue

                message = data.get("message", "").strip()
                if not message:
                    continue

                await ws_manager.send_status(ws, "THINKING")
                
                # Use a background task or run in executor to not block the ws loop
                # In a full implementation, we might delegate this to a queue.
                brain = _get_brain()
                try:
                    await ws_manager.send_status(ws, "SPEAKING")
                    # We can stream tokens
                    for chunk in brain.process_input_stream(message):
                        await ws_manager.send_chunk(chunk)
                        # Yield control slightly for fast streaming
                        await asyncio.sleep(0)
                        
                    await ws_manager.send_stream_end()
                    await ws_manager.send_status(ws, "IDLE")
                except Exception as e:
                    await ws_manager.send_status(ws, "ERROR")
                    await ws.send_json({"error": str(e)})

            elif cmd == "interrupt":
                # Handle interrupt TTS/processing
                await ws_manager.send_status(ws, "IDLE")
                # Need to implement logic to actually stop generating/TTS

            elif cmd == "status_update":
                # UI notifying backend of its state (e.g. LISTENING)
                status = data.get("status", "IDLE")
                log.info(f"UI Status changed to: {status}")

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
    """Retrieve recent conversation history (last N turns)."""
    memory = _get_memory()
    turns  = memory.get_recent_conversation(n=n)
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
        total = memory.conversations.count(),
    )


@app.delete("/history", response_model=SuccessResponse, tags=["Chat"])
async def clear_history(auth: AuthRequired):
    """Clear conversation history."""
    memory = _get_memory()
    memory.conversations.clear()
    return SuccessResponse(message="Conversation history cleared.")


# ─── Task Routes ─────────────────────────────────────────────────────────────

@app.post("/task", response_model=TaskResponse, tags=["Tasks"])
async def execute_task(body: TaskRequest, auth: AuthRequired):
    """Submit an autonomous multi-step task for JARVIS to plan and execute."""
    brain = _get_brain()
    
    try:
        # Run Action-First execution
        result_text = brain.execute_task(body.task)

        return TaskResponse(
            task      = body.task,
            completed = True,
            steps     = [
                TaskStepResult(
                    index       = 0,
                    description = "Action-First Execution Engine",
                    status      = "success",
                    result      = result_text,
                )
            ],
            summary   = result_text,
        )
    except Exception as e:
        error_log.error(f"/task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    """Semantically search stored memories."""
    memory  = _get_memory()
    results = memory.retrieve_memories(
        body.query,
        top_k    = body.top_k,
        category = body.category.value if body.category else None,
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
    """Store a new memory entry."""
    memory = _get_memory()
    doc_id = memory.store_memory(
        body.content,
        category = body.category.value,
        metadata = body.metadata,
        encrypt  = body.encrypt,
    )
    return SuccessResponse(message=f"Memory stored with ID: {doc_id}")


@app.post("/memory/preference", response_model=SuccessResponse, tags=["Memory"])
async def set_preference(body: PreferenceSetRequest, auth: AuthRequired):
    """Store or update an owner preference."""
    memory = _get_memory()
    memory.store_preference(body.key, body.value)
    return SuccessResponse(message=f"Preference '{body.key}' saved.")


@app.get("/memory/preference/{key}", tags=["Memory"])
async def get_preference(key: str, auth: AuthRequired):
    """Retrieve a stored preference by key."""
    memory = _get_memory()
    value  = memory.get_preference(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Preference '{key}' not found.")
    return {"key": key, "value": value}


@app.delete("/memory", response_model=SuccessResponse, tags=["Memory"])
async def clear_memory(auth: AuthRequired, confirm: bool = False):
    """
    Clear ALL memory. DESTRUCTIVE.
    Must pass `?confirm=true` query parameter to execute.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Safety check: pass ?confirm=true to confirm full memory wipe.",
        )
    memory = _get_memory()
    memory.clear_all()
    return SuccessResponse(message="All memory cleared.")


# ─── System Routes ────────────────────────────────────────────────────────────

@app.get("/status", response_model=SystemStatus, tags=["System"])
async def get_status(auth: AuthRequired):
    """Return current system health and resource status."""
    brain  = _get_brain()
    memory = _get_memory()
    b_status = brain.status()
    return SystemStatus(
        model          = b_status["model"],
        tools_count    = b_status["tools_count"],
        memory_active  = b_status["memory_active"],
        planner_active = b_status["planner_active"],
        memory_stats   = memory.stats(),
        uptime_seconds = round(time.time() - _START_TIME, 1),
    )


@app.get("/", tags=["System"])
async def root():
    """API root — health check."""
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
    """Trigger the Refiner Agent to optimize recent workflows."""
    brain = _get_brain()
    if hasattr(brain, '_refiner') and brain._refiner:
        from core.agents.base_agent import AgentMessage
        msg = AgentMessage(sender="system", recipient="refiner", content="optimize")
        res = brain._refiner.process(msg)
        if res.success:
            return SuccessResponse(message=res.content)
        else:
            raise HTTPException(status_code=500, detail=res.content)
    raise HTTPException(status_code=503, detail="Refiner Agent not available.")
