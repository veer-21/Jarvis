"""
JARVIS Security Layer
Handles:
  - Owner PIN authentication (bcrypt hashed)
  - Symmetric encryption/decryption of sensitive data (Fernet)
  - Permission gating for dangerous actions
  - Action audit logging
  - Session token management
"""

import os
import json
import secrets
import hashlib
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
from typing import Optional, Any
from enum import Enum

from core.logger import log, audit_log

# ─── Optional Dependencies ───────────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    log.warning("cryptography package not installed — encrypted storage disabled. Run: pip install cryptography")

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False
    log.warning("bcrypt not installed — using SHA-256 PIN hashing (less secure). Run: pip install bcrypt")


# ─── Paths ───────────────────────────────────────────────────────────────────
SECURITY_DIR  = Path(__file__).parent.parent / "data" / "security"
SECURITY_DIR.mkdir(parents=True, exist_ok=True)
PIN_FILE      = SECURITY_DIR / ".owner_pin.hash"
KEY_FILE      = SECURITY_DIR / ".jarvis.key"


# ─── Risk Levels ─────────────────────────────────────────────────────────────
class RiskLevel(str, Enum):
    # Phase 3 Canonical Categories
    READ_ONLY      = "READ_ONLY"
    LOW_RISK       = "LOW_RISK"
    MODERATE_RISK  = "MODERATE_RISK"
    HIGH_RISK      = "HIGH_RISK"
    CRITICAL       = "CRITICAL"

    # Backward-compatible aliases
    SAFE           = "READ_ONLY"
    LOW            = "LOW_RISK"
    MEDIUM         = "MODERATE_RISK"
    HIGH           = "HIGH_RISK"
    CRITICAL_RISK  = "CRITICAL"


def mask_sensitive_data(data: Any) -> Any:
    """Recursively mask secrets, passwords, tokens, and keys from logs and events."""
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in ("key", "secret", "token", "password", "pin", "auth", "credential")):
                masked[k] = "[MASKED_SECRET]"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        # Mask obvious token / api key patterns
        if len(data) > 30 and any(prefix in data for prefix in ("sk-", "gsk_", "AIza", "eyJh")):
            return "[MASKED_TOKEN]"
    return data


# ─── Dangerous Action Registry ────────────────────────────────────────────────
DANGEROUS_COMMANDS: dict[str, RiskLevel] = {
    # Critical — always require confirmation
    "del":        RiskLevel.CRITICAL,
    "rm":         RiskLevel.CRITICAL,
    "rmdir":      RiskLevel.CRITICAL,
    "format":     RiskLevel.CRITICAL,
    "fdisk":      RiskLevel.CRITICAL,
    "diskpart":   RiskLevel.CRITICAL,
    "shutdown":   RiskLevel.HIGH_RISK,
    "restart":    RiskLevel.HIGH_RISK,
    "reg":        RiskLevel.HIGH_RISK,
    "regedit":    RiskLevel.HIGH_RISK,
    "netsh":      RiskLevel.HIGH_RISK,
    "powercfg":   RiskLevel.HIGH_RISK,
    "cipher":     RiskLevel.HIGH_RISK,
    "bcdedit":    RiskLevel.CRITICAL,
    "attrib":     RiskLevel.MODERATE_RISK,
    "icacls":     RiskLevel.MODERATE_RISK,
    "takeown":    RiskLevel.HIGH_RISK,
    "sfc":        RiskLevel.MODERATE_RISK,
    "wmic":       RiskLevel.HIGH_RISK,
    "taskkill":   RiskLevel.MODERATE_RISK,
    "net user":   RiskLevel.CRITICAL,
    "net localgroup": RiskLevel.CRITICAL,
}


# ─── Encryption Engine ────────────────────────────────────────────────────────
class EncryptionEngine:
    """Fernet symmetric encryption for sensitive data storage."""

    def __init__(self):
        self._key: Optional[bytes] = None
        self._fernet: Any = None

        if HAS_CRYPTOGRAPHY:
            self._key = self._load_or_generate_key()
            self._fernet = Fernet(self._key)

    def _load_or_generate_key(self) -> bytes:
        """Load existing key or generate and persist a new one."""
        if KEY_FILE.exists():
            return KEY_FILE.read_bytes()
        key = Fernet.generate_key()
        KEY_FILE.write_bytes(key)
        # Restrict file permissions on creation (best-effort on Windows)
        try:
            KEY_FILE.chmod(0o600)
        except Exception:
            pass
        log.info("Generated new Fernet encryption key")
        return key

    def encrypt(self, data: str) -> str:
        """Encrypt a string, returning base64-encoded ciphertext."""
        if not HAS_CRYPTOGRAPHY or not self._fernet:
            return data  # No-op fallback
        return self._fernet.encrypt(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt a Fernet token back to plaintext."""
        if not HAS_CRYPTOGRAPHY or not self._fernet:
            return token
        return self._fernet.decrypt(token.encode()).decode()

    def encrypt_dict(self, data: dict) -> str:
        """Serialize a dict to JSON and encrypt it."""
        return self.encrypt(json.dumps(data))

    def decrypt_dict(self, token: str) -> dict:
        """Decrypt and deserialize a dict."""
        return json.loads(self.decrypt(token))


# ─── PIN Authentication ───────────────────────────────────────────────────────
class OwnerAuth:
    """Manages owner PIN storage and verification."""

    def __init__(self):
        self._authenticated = False
        self._session_token: Optional[str] = None
        self._session_expiry: Optional[datetime] = None

    def set_pin(self, pin: str) -> None:
        """Hash and store the owner PIN."""
        if HAS_BCRYPT:
            hashed = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()
        else:
            # SHA-256 fallback (less secure)
            hashed = hashlib.sha256(pin.encode()).hexdigest()
        PIN_FILE.write_text(hashed, encoding="utf-8")
        try:
            PIN_FILE.chmod(0o600)
        except Exception:
            pass
        audit_log.info({"event": "PIN_SET", "timestamp": datetime.now(timezone.utc).isoformat()})
        log.info("Owner PIN has been set.")

    def verify_pin(self, pin: str) -> bool:
        """Verify the provided PIN against the stored hash."""
        if not PIN_FILE.exists():
            log.warning("No PIN file found — owner auth skipped (first-run mode)")
            self._authenticated = True
            return True

        stored = PIN_FILE.read_text(encoding="utf-8").strip()

        if HAS_BCRYPT:
            valid = bcrypt.checkpw(pin.encode(), stored.encode())
        else:
            valid = hashlib.sha256(pin.encode()).hexdigest() == stored

        if valid:
            self._authenticated = True
            self._session_token = secrets.token_urlsafe(32)
            self._session_expiry = datetime.now(timezone.utc) + timedelta(hours=12)
            audit_log.info({"event": "AUTH_SUCCESS", "timestamp": datetime.now(timezone.utc).isoformat()})
            log.info("Owner authenticated successfully.")
        else:
            audit_log.warning({"event": "AUTH_FAILURE", "timestamp": datetime.now(timezone.utc).isoformat()})
            log.warning("Authentication failed — incorrect PIN.")

        return valid

    def is_authenticated(self) -> bool:
        """Check if a valid session exists."""
        if not self._authenticated:
            return False
        if self._session_expiry and datetime.now(timezone.utc) > self._session_expiry:
            self._authenticated = False
            self._session_token = None
            log.info("Session expired — re-authentication required.")
            return False
        return True

    def logout(self) -> None:
        """Invalidate the current session."""
        self._authenticated = False
        self._session_token = None
        self._session_expiry = None
        audit_log.info({"event": "LOGOUT", "timestamp": datetime.now(timezone.utc).isoformat()})

    def is_pin_set(self) -> bool:
        return PIN_FILE.exists()


class SecurityGuard:
    """
    Central security gatekeeper.
    All tool executions should pass through `check_command` and `evaluate_tool_execution`.
    """

    def __init__(self, auth: OwnerAuth):
        self._auth = auth
        self._confirmation_handler: Optional[Any] = None
        self._pending_confirmations: dict[str, dict] = {}
        self._confirm_lock = threading.Lock()

    def register_confirmation_handler(self, handler: Any) -> None:
        """Register a non-blocking confirmation handler (e.g. WebSocket / UI bridge)."""
        self._confirmation_handler = handler

    def create_pending_confirmation(
        self,
        tool_name: str,
        args: dict,
        risk_level: RiskLevel,
        timeout_sec: int = 60,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        task_id: Optional[str] = None
    ) -> tuple[str, threading.Event]:
        """Create an authenticated pending confirmation request with timeout, session, and user binding."""
        import uuid
        conf_id = f"conf_{uuid.uuid4().hex[:8]}"
        event = threading.Event()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=timeout_sec)
        risk_val = risk_level.value if hasattr(risk_level, "value") else str(risk_level)

        with self._confirm_lock:
            self._pending_confirmations[conf_id] = {
                "id": conf_id,
                "tool_name": tool_name,
                "args": mask_sensitive_data(args),
                "risk_level": risk_val,
                "event": event,
                "approved": False,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "expires_timestamp": expires_at.timestamp(),
                "timeout_sec": timeout_sec,
                "session_id": session_id,
                "user_id": user_id,
                "task_id": task_id,
                "status": "PENDING"
            }
        return conf_id, event

    def submit_confirmation(
        self,
        confirmation_id: str,
        approved: bool,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """
        Submits confirmation/denial with strict authentication, session, and expiration checks.
        Returns True if confirmation was successfully applied, False if not found, expired, or unauthorized.
        """
        with self._confirm_lock:
            conf = self._pending_confirmations.get(confirmation_id)
            if not conf:
                return False

            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts > conf.get("expires_timestamp", float("inf")):
                conf["status"] = "EXPIRED"
                conf["event"].set()
                self._pending_confirmations.pop(confirmation_id, None)
                return False

            # Strict session and user ownership validation
            expected_sid = conf.get("session_id")
            if expected_sid is not None:
                if not session_id or session_id != expected_sid:
                    return False

            expected_uid = conf.get("user_id")
            if expected_uid is not None:
                if not user_id or user_id != expected_uid:
                    return False

            conf["approved"] = approved
            conf["status"] = "APPROVED" if approved else "DENIED"
            conf["event"].set()
            return True

    def remove_confirmation(self, confirmation_id: str) -> None:
        """Purge completed or resolved confirmation from storage."""
        with self._confirm_lock:
            self._pending_confirmations.pop(confirmation_id, None)

    def cleanup_expired_confirmations(self) -> int:
        """Sweep and purge all expired or finished confirmations from pending storage."""
        now_ts = datetime.now(timezone.utc).timestamp()
        removed = 0
        with self._confirm_lock:
            stale_ids = [
                cid for cid, c in self._pending_confirmations.items()
                if now_ts > c.get("expires_timestamp", float("inf")) or c["event"].is_set()
            ]
            for cid in stale_ids:
                self._pending_confirmations.pop(cid, None)
                removed += 1
        return removed

    def get_pending_confirmations(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> list[dict]:
        """List active pending non-expired confirmations, optionally filtered by user_id and session_id."""
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._confirm_lock:
            results = []
            for c in self._pending_confirmations.values():
                if c["event"].is_set() or now_ts > c.get("expires_timestamp", float("inf")):
                    continue
                if user_id is not None and c.get("user_id") != user_id:
                    continue
                if session_id is not None and c.get("session_id") != session_id:
                    continue
                results.append({k: v for k, v in c.items() if k != "event"})
            return results


    def assess_command_risk(self, command: str) -> RiskLevel:
        """Evaluate the risk level of a shell command."""
        cmd_lower = command.lower().strip()
        for keyword, risk in DANGEROUS_COMMANDS.items():
            if keyword in cmd_lower:
                return risk
        return RiskLevel.SAFE

    def check_command(self, command: str, interactive: bool = True) -> tuple[bool, str]:
        """
        Gate a shell command through the security policy.

        Returns:
            (allowed: bool, reason: str)
        """
        risk = self.assess_command_risk(command)

        if risk == RiskLevel.SAFE:
            audit_log.info({
                "event": "COMMAND_ALLOWED",
                "command": command,
                "risk": risk,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return True, "Command is safe."

        # Log the attempt
        audit_log.warning({
            "event": "SENSITIVE_COMMAND_ATTEMPTED",
            "command": command,
            "risk": risk,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        print(f"\n{'='*60}")
        print(f"  ⚠️  JARVIS SECURITY ALERT — Risk Level: {risk}")
        print(f"{'='*60}")
        print(f"  Command: {command}")
        print(f"  This action could modify or damage the system.")

        # Protected Critical Windows Processes - never allow terminating them
        CRITICAL_PROCESSES = ["explorer.exe", "dwm.exe", "lsass.exe", "csrss.exe", "smss.exe", "services.exe", "wininit.exe"]
        if any(proc in cmd_lower for proc in CRITICAL_PROCESSES) and ("kill" in cmd_lower or "stop" in cmd_lower):
            audit_log.error({
                "event": "CRITICAL_PROCESS_KILL_BLOCKED",
                "command": command,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return False, "Command blocked: Cannot terminate critical Windows operating system processes."

        if interactive:
            try:
                approval = input("  Do you authorize this action? (yes/no): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                approval = "no"

            if approval in ("yes", "y"):
                audit_log.info({
                    "event": "SENSITIVE_COMMAND_APPROVED",
                    "command": command,
                    "risk": risk,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return True, "Owner approved."
            else:
                audit_log.info({
                    "event": "SENSITIVE_COMMAND_DENIED",
                    "command": command,
                    "risk": risk,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return False, "Owner denied execution."
        else:
            # In Unattended / Scheduled mode — strictly quarantine and block destructive/high-risk commands
            audit_log.warning({
                "event": "UNATTENDED_HIGH_RISK_BLOCKED",
                "command": command,
                "risk": risk,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return False, f"Unattended Safety Guard: High-risk command blocked ({risk}) because owner is away."

    def evaluate_tool_execution(
        self,
        tool_name: str,
        args: dict,
        declared_risk: RiskLevel = RiskLevel.READ_ONLY,
        interactive: bool = True
    ) -> tuple[bool, RiskLevel, bool, str]:
        """
        Unified Single Policy Decision Point for EVERY tool execution.
        Returns:
            (allowed: bool, effective_risk: RiskLevel, requires_confirmation: bool, reason: str)
        """
        effective_risk = declared_risk
        
        # Check command risk if tool runs a shell or script command
        if "command" in args and isinstance(args["command"], str):
            cmd_risk = self.assess_command_risk(args["command"])
            risk_ranks = {
                RiskLevel.READ_ONLY: 0,
                RiskLevel.LOW_RISK: 1,
                RiskLevel.MODERATE_RISK: 2,
                RiskLevel.HIGH_RISK: 3,
                RiskLevel.CRITICAL: 4
            }
            if risk_ranks.get(cmd_risk, 0) > risk_ranks.get(effective_risk, 0):
                effective_risk = cmd_risk

        # Everyday tool risk adjustments
        t_low = tool_name.lower()
        if t_low == "control_windows_setting":
            setting_name = str(args.get("setting", "")).lower()
            if setting_name in ("empty_recycle_bin", "clear_recycle_bin"):
                effective_risk = RiskLevel.HIGH_RISK
            elif setting_name in ("lock_workstation", "lock_pc", "lock_screen"):
                if effective_risk not in (RiskLevel.HIGH_RISK, RiskLevel.CRITICAL):
                    effective_risk = RiskLevel.MODERATE_RISK
            else:
                effective_risk = RiskLevel.LOW_RISK
        elif t_low in ("smart_organize_folder", "undo_folder_organization"):
            if effective_risk not in (RiskLevel.HIGH_RISK, RiskLevel.CRITICAL):
                effective_risk = RiskLevel.MODERATE_RISK
        elif t_low == "create_reminder_or_timer":
            if effective_risk not in (RiskLevel.MODERATE_RISK, RiskLevel.HIGH_RISK, RiskLevel.CRITICAL):
                effective_risk = RiskLevel.LOW_RISK
        elif t_low == "manage_personal_notes_and_todos":
            action = str(args.get("action", "")).lower()
            if action in ("add", "complete", "delete"):
                effective_risk = RiskLevel.LOW_RISK
            else:
                effective_risk = RiskLevel.READ_ONLY
        elif t_low == "smart_clipboard_assistant":
            action = str(args.get("action", "")).lower()
            if action == "write":
                effective_risk = RiskLevel.LOW_RISK
            else:
                effective_risk = RiskLevel.READ_ONLY
        elif t_low == "read_and_summarize_webpage":
            effective_risk = RiskLevel.READ_ONLY

        requires_confirmation = effective_risk in (RiskLevel.HIGH_RISK, RiskLevel.CRITICAL)

        # Protected Critical Windows Processes - never allow terminating them
        if "command" in args and isinstance(args["command"], str):
            cmd_lower = args["command"].lower()
            CRITICAL_PROCESSES = ["explorer.exe", "dwm.exe", "lsass.exe", "csrss.exe", "smss.exe", "services.exe", "wininit.exe"]
            if any(proc in cmd_lower for proc in CRITICAL_PROCESSES) and ("kill" in cmd_lower or "stop" in cmd_lower):
                audit_log.error({
                    "event": "CRITICAL_PROCESS_KILL_BLOCKED",
                    "tool": tool_name,
                    "command": mask_sensitive_data(args["command"]),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return False, RiskLevel.CRITICAL, False, "Blocked: Cannot terminate critical Windows operating system processes."

        if not requires_confirmation:
            audit_log.info({
                "event": "TOOL_PERMISSION_GRANTED",
                "tool": tool_name,
                "risk": effective_risk,
                "args": mask_sensitive_data(args),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return True, effective_risk, False, f"Permission granted for {effective_risk.value} action."

        if not interactive:
            audit_log.warning({
                "event": "UNATTENDED_RISKY_TOOL_BLOCKED",
                "tool": tool_name,
                "risk": effective_risk,
                "args": mask_sensitive_data(args),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return False, effective_risk, True, f"Blocked: Action requires interactive confirmation (Risk: {effective_risk.value})."

        # 1. Check non-blocking custom confirmation handler (UI / WebSocket bridge)
        if self._confirmation_handler:
            try:
                approved, reason = self._confirmation_handler(tool_name, args, effective_risk)
                event_name = "RISKY_TOOL_APPROVED" if approved else "RISKY_TOOL_DENIED"
                audit_log.info({
                    "event": event_name,
                    "tool": tool_name,
                    "risk": effective_risk,
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return approved, effective_risk, True, reason
            except Exception as e:
                log.warning(f"[SecurityGuard] Custom confirmation handler failed: {e}")

        # 2. Terminal CLI Fallback
        print(f"\n{'='*60}")
        print(f"  ⚠️  JARVIS SECURITY CONFIRMATION REQUIRED")
        print(f"{'='*60}")
        print(f"  Tool: {tool_name}")
        print(f"  Risk Level: {effective_risk.value}")
        print(f"  Parameters: {mask_sensitive_data(args)}")
        try:
            approval = input("  Do you authorize this action? (yes/no): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            approval = "no"

        if approval in ("yes", "y"):
            audit_log.info({
                "event": "RISKY_TOOL_APPROVED",
                "tool": tool_name,
                "risk": effective_risk,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return True, effective_risk, True, "Owner approved execution."
        else:
            audit_log.info({
                "event": "RISKY_TOOL_DENIED",
                "tool": tool_name,
                "risk": effective_risk,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return False, effective_risk, True, "Owner denied execution."

    def log_tool_execution(self, tool_name: str, args: dict, result_summary: str) -> None:
        """Record a tool execution in the audit log with sensitive data masked."""
        audit_log.info({
            "event": "TOOL_EXECUTED",
            "tool": tool_name,
            "args": mask_sensitive_data(args),
            "result_summary": str(result_summary)[:200],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def log_file_access(self, action: str, path: str, allowed: bool) -> None:
        """Record file system access events."""
        audit_log.info({
            "event": f"FILE_{action.upper()}",
            "path": path,
            "allowed": allowed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


# ─── Singleton Instances ──────────────────────────────────────────────────────
encryption   = EncryptionEngine()
owner_auth   = OwnerAuth()
guard        = SecurityGuard(owner_auth)
