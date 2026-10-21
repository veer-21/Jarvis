"""
JARVIS Brain — Structured Task Model
Defines the authoritative lifecycle states, execution graph nodes,
and audit trails for personal assistant tasks.
"""

import uuid
import threading
import contextvars
from typing import Optional, Any
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field, PrivateAttr

from core.security import mask_sensitive_data

current_execution_context: contextvars.ContextVar[Optional['ExecutionContext']] = contextvars.ContextVar('current_execution_context', default=None)

class TaskStatus(str, Enum):
    RECEIVED                 = "RECEIVED"
    UNDERSTANDING            = "UNDERSTANDING"
    PLANNING                 = "PLANNING"
    WAITING_FOR_INPUT        = "WAITING_FOR_INPUT"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    EXECUTING                = "EXECUTING"
    VERIFYING                = "VERIFYING"
    RECOVERING               = "RECOVERING"
    COMPLETED                = "COMPLETED"
    FAILED                   = "FAILED"
    CANCELLED                = "CANCELLED"
    TIMED_OUT                = "TIMED_OUT"


def map_task_status_to_api(status: Optional[TaskStatus], is_cancelled: bool = False) -> tuple[bool, str]:
    """
    Authoritative mapping of AssistantTask status to API (completed: bool, status: str).
    Only TaskStatus.COMPLETED may return completed=True, status='success'.
    All other states, unknown values, or missing values return completed=False.
    """
    if is_cancelled:
        return False, "cancelled"
    if status == TaskStatus.COMPLETED:
        return True, "success"
    if status == TaskStatus.CANCELLED:
        return False, "cancelled"
    if status == TaskStatus.FAILED:
        return False, "failed"
    if status == TaskStatus.WAITING_FOR_INPUT:
        return False, "waiting_for_input"
    if status == TaskStatus.WAITING_FOR_CONFIRMATION:
        return False, "waiting_for_confirmation"
    if status == TaskStatus.TIMED_OUT:
        return False, "timed_out"
    return False, "failed"


class TaskStepStatus(str, Enum):
    PENDING    = "PENDING"
    RUNNING    = "RUNNING"
    VERIFYING  = "VERIFYING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"
    SKIPPED    = "SKIPPED"
    CANCELLED  = "CANCELLED"

class TaskStep(BaseModel):
    """Discrete step within a multi-step task execution plan."""
    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:6]}")
    description: str
    capability: str = "general" # general, file, web, system, browser, desktop, reasoning
    tool_name: Optional[str] = None
    input_variables: dict[str, Any] = Field(default_factory=dict)
    output_variables: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    verification_level: str = "LEVEL_1"
    expected_outcome: Optional[str] = None
    status: TaskStepStatus = TaskStepStatus.PENDING
    result: Optional[Any] = None
    evidence: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    reversible: bool = False

class TaskAuditRecord(BaseModel):
    """Structured audit trail record without secret exposure."""
    event: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: dict[str, Any] = Field(default_factory=dict)

class ExecutionContext(BaseModel):
    """
    Authoritative request context passed across the entire cognitive execution chain.
    Carries memory policy, cancellation signaling, session metadata, deadlines, and audit context.
    """
    store_memory: bool = Field(default=True, description="Controls whether interaction is persisted to long-term memory")
    session_id: Optional[str] = Field(default=None, description="Authenticated session or connection identifier")
    user_id: Optional[str] = Field(default=None, description="Authenticated user identifier")
    task_id: Optional[str] = Field(default=None, description="Authoritative task identifier for correlation")
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    deadline: Optional[float] = Field(default=None, description="Absolute epoch timestamp deadline")
    timeout_seconds: Optional[int] = Field(default=60, description="Maximum execution timeout")
    confirmation_context: Optional[dict[str, Any]] = Field(default=None, description="Security confirmation context")
    task: Optional[Any] = Field(default=None, description="Active or completed AssistantTask reference")
    stream_completed: bool = Field(default=False, description="Flag indicating stream completed cleanly")
    is_interrupted: bool = Field(default=False, description="Flag indicating stream was interrupted")
    stream_error: Optional[str] = Field(default=None, description="Error string if streaming failed")

    # Private cancellation event for cooperative interruption
    _cancel_event: threading.Event = PrivateAttr(default_factory=threading.Event)

    def __init__(self, **data):
        cancellation_token = data.pop("cancellation_token", None)
        super().__init__(**data)
        if cancellation_token is not None:
            self._cancel_event = cancellation_token

    @property
    def cancellation_token(self) -> threading.Event:
        return self._cancel_event

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self, reason: str = "CANCELLED") -> None:
        self._cancel_event.set()


class AssistantTask(BaseModel):
    """
    Authoritative state model representing an assistant task from ingestion to completion.
    """
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    user_request: str
    intent: str = "general"
    status: TaskStatus = TaskStatus.RECEIVED
    priority: str = "normal"
    store_memory: bool = True
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    context: dict[str, Any] = Field(default_factory=dict)
    plan: list[TaskStep] = Field(default_factory=list)
    current_step: int = 0
    completed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)
    pending_confirmation: Optional[dict[str, Any]] = None
    
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    memory_references: list[str] = Field(default_factory=list)
    audit_trail: list[TaskAuditRecord] = Field(default_factory=list)

    # Cooperative cancellation event (unserialized private attribute)
    _cancel_event: threading.Event = PrivateAttr(default_factory=threading.Event)


    def transition_to(self, new_status: TaskStatus, event_name: Optional[str] = None, details: Optional[dict] = None) -> None:
        """Transitions state and records a structured audit event."""
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc).isoformat()
        
        event = event_name or f"STATUS_TRANSITION_TO_{new_status.value}"
        cleaned_details = mask_sensitive_data(details or {})
        self.audit_trail.append(TaskAuditRecord(event=event, details=cleaned_details))

    def add_audit_event(self, event: str, details: Optional[dict] = None) -> None:
        """Appends an event to the audit trail with secret scrubbing."""
        cleaned_details = mask_sensitive_data(details or {})
        self.audit_trail.append(TaskAuditRecord(event=event, details=cleaned_details))

    def cancel(self, reason: str = "TASK_CANCELLED_BY_USER") -> None:
        """Cooperatively cancel the task and signal in-flight operations."""
        self._cancel_event.set()
        self.transition_to(TaskStatus.CANCELLED, event_name="TASK_CANCELLED", details={"reason": reason})

    @property
    def is_cancelled(self) -> bool:
        """Check if the task has been cancelled."""
        return self.status == TaskStatus.CANCELLED or self._cancel_event.is_set()

    @property
    def cancellation_token(self) -> threading.Event:
        """Expose the threading.Event for cooperative checking."""
        return self._cancel_event

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary with scrubbed secrets."""
        data = self.model_dump(mode="json")
        return mask_sensitive_data(data)


def validate_plan(
    plan: list[TaskStep],
    available_tools: Optional[list[str]] = None,
    tool_schemas: Optional[dict[str, Any]] = None
) -> tuple[bool, Optional[str]]:
    """
    Validates a generated task plan before execution against registered schemas and capabilities.
    
    Checks:
      1. Non-empty step list.
      2. Unique step IDs.
      3. Valid capabilities.
      4. Tool existence in registry.
      5. Parameter validation against Pydantic schemas (required parameters present).
      6. Dependency references exist and do not contain cycles.
    
    Returns:
      (True, None) if valid, or (False, error_reason).
    """
    if not plan:
        return False, "Plan is empty. At least one step is required."
        
    step_ids = set()
    step_order = []
    task_map = {}
    valid_capabilities = {"general", "file", "web", "system", "browser", "desktop", "reasoning", "automation", "everyday"}

    for step in plan:
        if not step.step_id:
            return False, "Encountered step with missing step_id."
        if step.step_id in step_ids:
            return False, f"Duplicate step_id detected: '{step.step_id}'."
        step_ids.add(step.step_id)
        step_order.append(step.step_id)
        task_map[step.step_id] = step

        if step.capability not in valid_capabilities:
            return False, f"Unsupported capability '{step.capability}' in step '{step.step_id}'."

        if step.tool_name:
            if available_tools is not None and step.tool_name not in available_tools:
                return False, f"Tool '{step.tool_name}' referenced in step '{step.step_id}' does not exist in registry."

            # Detailed parameter validation against registered schema
            if tool_schemas and step.tool_name in tool_schemas:
                schema = tool_schemas[step.tool_name]
                if hasattr(schema, "pydantic_model") and schema.pydantic_model:
                    model = schema.pydantic_model
                    param_aliases = {
                        "file_path": ["path", "filepath", "filename"],
                        "path": ["file_path", "filepath", "filename"],
                        "query": ["q", "search_query"],
                        "q": ["query", "search_query"],
                        "app_name": ["app", "application", "name"],
                        "app": ["app_name", "application", "name"],
                        "command": ["cmd", "action"],
                        "cmd": ["command", "action"],
                    }
                    for fname, ffield in model.model_fields.items():
                        if ffield.is_required() and fname not in step.input_variables:
                            has_alias = any(a in step.input_variables for a in param_aliases.get(fname, []))
                            has_interp = any(f"{{{{{dep}." in str(v) for v in step.input_variables.values() for dep in step.dependencies)
                            if not has_alias and not has_interp:
                                return False, f"Step '{step.step_id}' missing required parameter '{fname}' for tool '{step.tool_name}'."

    # Validate dependencies
    for step in plan:
        for dep in step.dependencies:
            if dep not in step_ids:
                return False, f"Step '{step.step_id}' references unknown dependency '{dep}'."
            if dep == step.step_id:
                return False, f"Step '{step.step_id}' cannot depend on itself (circular reference)."

    # Cycle detection via DFS
    visited = {} # 0: unvisited, 1: visiting, 2: visited
    for sid in step_ids:
        visited[sid] = 0

    def has_cycle(curr_id: str, path: list[str]) -> bool:
        visited[curr_id] = 1
        for dep in task_map[curr_id].dependencies:
            if visited[dep] == 1:
                return True
            if visited[dep] == 0:
                if has_cycle(dep, path + [dep]):
                    return True
        visited[curr_id] = 2
        return False

    for sid in step_ids:
        if visited[sid] == 0:
            if has_cycle(sid, [sid]):
                return False, "Circular dependency detected in execution graph."

    return True, None
