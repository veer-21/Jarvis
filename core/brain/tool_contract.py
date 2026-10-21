"""
JARVIS Brain — Tool Contract
Defines the canonical, strongly typed contract for all tools.
Ensures every tool declares its schema, risk, confirmation, timeout, and reversibility.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, Any, Type
from enum import Enum
from pydantic import BaseModel, Field

from core.security import RiskLevel

class ConfirmationPolicy(str, Enum):
    NEVER     = "NEVER"      # Read-only, inspection, or zero-risk
    ALWAYS    = "ALWAYS"     # High risk or critical
    ON_ERROR  = "ON_ERROR"   # Ask user only if an issue occurs
    DYNAMIC   = "DYNAMIC"    # Evaluated at runtime based on parameters

class RetryPolicy(str, Enum):
    NO_RETRY        = "NO_RETRY"        # Non-idempotent or irreversible actions
    RETRY_ONCE      = "RETRY_ONCE"      # Safe read/list/fetch operations
    RETRY_WITH_BACKOFF = "RETRY_WITH_BACKOFF"

@dataclass
class ToolExecutionResult:
    """Canonical structured execution result for every tool execution."""
    success: bool
    status: str = "COMPLETED"  # "COMPLETED", "TIMED_OUT", "CANCELLED", "FAILED"
    timed_out: bool = False
    cleanup_succeeded: Optional[bool] = None
    output: Any = None
    evidence: Any = None
    error: Optional[str] = None
    reversible: bool = False
    verified: bool = False
    execution_time_ms: float = 0.0

    @property
    def result(self) -> Any:
        return self.output

    def __getitem__(self, key: str) -> Any:
        if key == "result":
            return self.output
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "result":
            return self.output
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or key == "result"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "status": self.status,
            "timed_out": self.timed_out,
            "cleanup_succeeded": self.cleanup_succeeded,
            "result": self.output,
            "output": self.output,
            "evidence": self.evidence,
            "error": self.error,
            "reversible": self.reversible,
            "verified": self.verified,
            "execution_time_ms": self.execution_time_ms,
        }

@dataclass
class ToolContract:
    """
    Canonical interface declaration for every registered tool.
    Does not rely solely on raw Python function signatures or docstrings.
    """
    name:                 str
    description:          str
    category:             str
    callable:             Callable
    input_schema:         Optional[Type[BaseModel]] = None
    output_schema:        Optional[Type[BaseModel]] = None
    risk_level:           RiskLevel = RiskLevel.READ_ONLY
    permission_level:     str = "user"  # user, admin, owner
    confirmation_policy:  ConfirmationPolicy = ConfirmationPolicy.NEVER
    timeout_seconds:      int = 30
    retry_policy:         RetryPolicy = RetryPolicy.RETRY_ONCE
    reversible:           bool = False
    parameters:           dict = field(default_factory=dict)
    
    # Backwards compatibility attributes with ToolSchema
    @property
    def requires_confirmation(self) -> bool:
        return self.confirmation_policy in (ConfirmationPolicy.ALWAYS, ConfirmationPolicy.DYNAMIC) or self.risk_level in (RiskLevel.HIGH_RISK, RiskLevel.CRITICAL)

    @property
    def retry_allowed(self) -> bool:
        return self.retry_policy != RetryPolicy.NO_RETRY

    @property
    def pydantic_model(self) -> Optional[Type[BaseModel]]:
        return self.input_schema
