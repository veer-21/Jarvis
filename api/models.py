"""
JARVIS API — Pydantic Request/Response Models
All API contracts are defined here for type safety and auto-documentation.
"""

# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────────────

class MessageRole(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


class MemoryCategory(str, Enum):
    CONVERSATION = "conversation"
    PREFERENCE   = "preference"
    TASK         = "task"
    KNOWLEDGE    = "knowledge"
    WORKFLOW     = "workflow"


class InteractionMode(str, Enum):
    TEXT  = "text"
    VOICE = "voice"


# ─── Auth ─────────────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    pin: str = Field(..., description="Owner PIN for authentication")


class AuthResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    expires_in:   int = Field(..., description="Token validity in seconds")
    message:      str


class SetPinRequest(BaseModel):
    new_pin:     str = Field(..., min_length=4, description="New owner PIN (min 4 chars)")
    confirm_pin: str = Field(..., description="Confirm new PIN")


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:      MessageRole
    content:   str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    message:  str = Field(..., min_length=1, max_length=10_000, description="User message")
    mode:     InteractionMode = InteractionMode.TEXT
    stream:   bool = Field(False, description="Enable streaming response")
    store:    bool = Field(True,  description="Store exchange in memory")


class ChatResponse(BaseModel):
    response:    str
    model:       str
    tokens_used: Optional[int] = None
    timestamp:   str


# ─── Task ─────────────────────────────────────────────────────────────────────

class TaskRequest(BaseModel):
    task:    str  = Field(..., min_length=1, max_length=5_000, description="Task description")
    verbose: bool = Field(True, description="Print step-by-step progress")
    store:   bool = Field(True, description="Store task outcome in memory")



class TaskStepResult(BaseModel):
    index:       int
    description: str
    status:      str
    result:      Optional[str] = None
    error:       Optional[str] = None
    retries:     int = 0


class TaskResponse(BaseModel):
    task:      str
    completed: bool
    steps:     List[TaskStepResult]
    summary:   str
    task_id:   Optional[str] = None
    status:    Optional[str] = "success"


# ─── Memory ───────────────────────────────────────────────────────────────────

class MemoryStoreRequest(BaseModel):
    content:  str            = Field(..., min_length=1)
    category: MemoryCategory = MemoryCategory.KNOWLEDGE
    encrypt:  bool           = False
    metadata: Optional[dict] = None


class MemoryEntry(BaseModel):
    id:       str
    content:  str
    category: str
    distance: Optional[float] = None
    timestamp: Optional[str]  = None


class MemorySearchRequest(BaseModel):
    query:    str            = Field(..., min_length=1)
    top_k:    int            = Field(5, ge=1, le=20)
    category: Optional[MemoryCategory] = None


class MemorySearchResponse(BaseModel):
    query:   str
    results: List[MemoryEntry]
    count:   int


class PreferenceSetRequest(BaseModel):
    key:   str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


# ─── System ───────────────────────────────────────────────────────────────────

class SystemStatus(BaseModel):
    status:          str = "online"
    model:           str
    tools_count:     int
    memory_active:   bool
    planner_active:  bool
    memory_stats:    dict
    uptime_seconds:  float
    version:         str = "3.0.0"


class HistoryResponse(BaseModel):
    turns:  List[ChatMessage]
    count:  int
    total:  int


# ─── Voice ────────────────────────────────────────────────────────────────────

class TranscribeResponse(BaseModel):
    transcript: str
    engine:     str
    duration_s: Optional[float] = None


# ─── Generic ─────────────────────────────────────────────────────────────────

class SuccessResponse(BaseModel):
    success: bool = True
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error:   str
    detail:  Optional[str] = None


# ─── Streaming (Phase 5) ─────────────────────────────────────────────────────

class StreamChunkType(str, Enum):
    TEXT             = "text"
    TOOL_CALL        = "tool_call"
    TOOL_RESULT      = "tool_result"
    EXECUTION_STATUS = "execution_status"
    THINKING         = "thinking"
    DONE             = "done"
    ERROR            = "error"


class StreamChunk(BaseModel):
    type:      StreamChunkType
    content:   str
    metadata:  Optional[dict] = None
    timestamp: Optional[str]  = None


# ─── Execution Events ────────────────────────────────────────────────────────

class ExecutionEventModel(BaseModel):
    event_type: str
    step_index: int
    data:       dict
    timestamp:  str


# ─── System Metrics ──────────────────────────────────────────────────────────

class SystemMetrics(BaseModel):
    cpu_percent:     Optional[float] = None
    ram_percent:     Optional[float] = None
    ram_used_gb:     Optional[float] = None
    ram_total_gb:    Optional[float] = None
    disk_percent:    Optional[float] = None
    active_tasks:    int = 0
    tools_registered: int = 0
    agents_active:   int = 0
    uptime_seconds:  float = 0


# ─── Agent Status ────────────────────────────────────────────────────────────

class AgentStatusModel(BaseModel):
    name:   str
    role:   str
    active: bool


class AgentSystemStatus(BaseModel):
    agents:       List[AgentStatusModel]
    bus_messages:  int = 0
    total_agents:  int = 0


# ─── Onboarding & Diagnostics ───────────────────────────────────────────────

class DiagnosticItem(BaseModel):
    ready: bool
    details: str
    optional: bool = False


class OnboardingDiagnosticsResponse(BaseModel):
    all_ready: bool
    llm_ready: bool
    voice_stt_ready: bool
    voice_tts_ready: bool
    browser_ready: bool
    ocr_ready: bool
    diagnostics: dict[str, DiagnosticItem]
    timestamp: str


class OnboardingConfigureRequest(BaseModel):
    user_name: Optional[str] = Field(None, max_length=100, description="Preferred display name for user")
    preferred_city: Optional[str] = Field(None, max_length=100, description="City for daily weather and briefing")
    gemini_api_key: Optional[str] = Field(None, max_length=200, description="Optional Google Gemini API key")
    owner_pin: Optional[str] = Field(None, min_length=4, max_length=64, description="Optional Owner PIN for system lock")


class OnboardingConfigureResponse(BaseModel):
    success: bool
    message: str
    configured_items: List[str]


