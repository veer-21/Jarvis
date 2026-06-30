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
    SAFE        = "SAFE"
    LOW         = "LOW"
    MEDIUM      = "MEDIUM"
    HIGH        = "HIGH"
    CRITICAL    = "CRITICAL"


# ─── Dangerous Action Registry ────────────────────────────────────────────────
DANGEROUS_COMMANDS: dict[str, RiskLevel] = {
    # Critical — always require confirmation
    "del":        RiskLevel.CRITICAL,
    "rm":         RiskLevel.CRITICAL,
    "rmdir":      RiskLevel.CRITICAL,
    "format":     RiskLevel.CRITICAL,
    "fdisk":      RiskLevel.CRITICAL,
    "diskpart":   RiskLevel.CRITICAL,
    "shutdown":   RiskLevel.HIGH,
    "restart":    RiskLevel.HIGH,
    "reg":        RiskLevel.HIGH,
    "regedit":    RiskLevel.HIGH,
    "netsh":      RiskLevel.HIGH,
    "powercfg":   RiskLevel.HIGH,
    "cipher":     RiskLevel.HIGH,
    "bcdedit":    RiskLevel.CRITICAL,
    "attrib":     RiskLevel.MEDIUM,
    "icacls":     RiskLevel.MEDIUM,
    "takeown":    RiskLevel.HIGH,
    "sfc":        RiskLevel.MEDIUM,
    "wmic":       RiskLevel.HIGH,
    "taskkill":   RiskLevel.MEDIUM,
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


# ─── Security Guard ───────────────────────────────────────────────────────────
class SecurityGuard:
    """
    Central security gatekeeper.
    All tool executions should pass through `check_command` before running.
    """

    def __init__(self, auth: OwnerAuth):
        self._auth = auth

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
            # In API/non-interactive mode — always block high-risk commands
            return False, f"Command blocked (risk={risk}) — requires interactive confirmation."

    def log_tool_execution(self, tool_name: str, args: dict, result_summary: str) -> None:
        """Record a tool execution in the audit log."""
        audit_log.info({
            "event": "TOOL_EXECUTED",
            "tool": tool_name,
            "args": args,
            "result_summary": result_summary[:200],  # Truncate long results
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
