"""
JARVIS Memory System (v2.0 — Tiered Architecture)
Implements persistent, semantic, encrypted memory using ChromaDB.
Falls back to a JSON-based store if ChromaDB is not installed.

Memory Types:
  - Semantic Memory   : Long-term knowledge, facts, preferences (ChromaDB/JSON)
  - Episodic Memory   : Summarized interaction episodes (not raw turns)
  - Task Memory       : Execution plans, results, learned shortcuts
  - Conversation Store: Raw turn-by-turn dialogue (sliding window, not vector-indexed)

Key improvements over v1:
  - No longer stores every conversation turn >30 chars as long-term memory
  - Memory importance scoring prevents pollution
  - Auto-pruning of low-value memories
  - Episodic summaries instead of raw turn mirroring
"""

import os
import json
import uuid
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.logger import log, error_log
from core.security import encryption

# ─── ChromaDB (optional) ──────────────────────────────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMA = True
    log.info("ChromaDB available — semantic vector memory enabled.")
except ImportError:
    HAS_CHROMA = False
    log.warning("ChromaDB not installed — using JSON fallback memory. Run: pip install chromadb")

# ─── Paths ───────────────────────────────────────────────────────────────────
MEMORY_DIR = Path(__file__).parent.parent / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR  = MEMORY_DIR / "chroma"
JSON_STORE  = MEMORY_DIR / "memory_fallback.json"
CONVO_STORE = MEMORY_DIR / "conversations.json"
EPISODE_STORE = MEMORY_DIR / "episodes.json"

# Shared persistent Chroma client initialized early at import time
_GLOBAL_CHROMA_CLIENT = None
if HAS_CHROMA:
    try:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _GLOBAL_CHROMA_CLIENT = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    except Exception as _ce:
        log.warning(f"Early Chroma client init skipped: {_ce}")


# ─── Memory Importance Scoring ────────────────────────────────────────────────

# Keywords that indicate a memory is worth storing long-term
_IMPORTANCE_KEYWORDS = {
    "prefer", "always", "never", "remember", "my name", "i like", "i hate",
    "i want", "i need", "important", "favorite", "password", "key",
    "setting", "config", "schedule", "workflow", "automate", "save",
    "don't forget", "note that", "keep in mind", "fyi",
}

def score_importance(content: str, role: str = "user") -> float:
    """
    Score how important a piece of content is for long-term storage.
    Returns 0.0 (skip) to 1.0 (definitely store).

    Only user messages can trigger long-term storage.
    Assistant responses are stored only as part of episodic summaries.
    """
    if role != "user":
        return 0.0

    content_lower = content.lower()
    score = 0.0

    # Length bonus — very short messages are rarely important
    if len(content) < 30:
        score -= 0.3
    elif len(content) > 200:
        score += 0.1

    # Keyword matching — multiple keywords stack (capped)
    keyword_boost = 0.0
    for kw in _IMPORTANCE_KEYWORDS:
        if kw in content_lower:
            keyword_boost += 0.3
    score += min(keyword_boost, 0.6)  # Cap at 0.6

    # Question marks reduce importance (questions aren't facts to remember)
    if content.count("?") > 0:
        score -= 0.2

    # Commands/greetings are low value
    low_value_patterns = ["hi", "hello", "hey", "thanks", "ok", "yes", "no",
                          "what", "how", "why", "when", "where", "who"]
    first_word = content_lower.split()[0] if content_lower.split() else ""
    if first_word in low_value_patterns and len(content) < 80:
        score -= 0.3

    return max(0.0, min(1.0, score))


# Threshold: only store memories scoring above this
IMPORTANCE_THRESHOLD = 0.3


# ─── JSON Fallback Store ──────────────────────────────────────────────────────
class JSONMemoryStore:
    """Simple JSON-backed key-value memory store used when ChromaDB is absent."""

    def __init__(self, filepath: Path):
        self._path = filepath
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, doc_id: str, content: str, metadata: dict) -> None:
        self._data[doc_id] = {
            "content": content,
            "metadata": metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def search(self, query: str, top_k: int = 5, category: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False) -> list[dict]:
        """Simple keyword search (not semantic) as fallback. Filters strictly by user_id and category (P0-1, P0-2, P1-5)."""
        if not user_id and not allow_system_scope:
            return []

        query_lower = query.lower()
        results = []
        import re
        try:
            pattern = re.compile(rf"\b{re.escape(query_lower)}\b")
        except:
            pattern = None

        for doc_id, entry in self._data.items():
            meta = entry.get("metadata", {})
            if not allow_system_scope:
                doc_owner = meta.get("user_id")
                if not doc_owner or doc_owner != user_id:
                    continue
            elif user_id is not None:
                if meta.get("user_id") != user_id:
                    continue
            if category and meta.get("category") != category:
                continue
            
            content_lower = entry["content"].lower()
            if pattern:
                if pattern.search(content_lower):
                    results.append({"id": doc_id, **entry})
            else:
                if query_lower in content_lower:
                    results.append({"id": doc_id, **entry})
                    
        # Return most recent matches up to top_k
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results[:top_k]

    def get(self, doc_id: str, user_id: Optional[str] = None, allow_system_scope: bool = False) -> Optional[dict]:
        """Retrieve entry by ID, strictly enforcing owner verification (P1-2). Fails closed if missing owner without allow_system_scope."""
        if doc_id not in self._data:
            return None
        entry = self._data[doc_id]
        if not allow_system_scope:
            if not user_id:
                return None
            doc_owner = entry.get("metadata", {}).get("user_id")
            if not doc_owner or doc_owner != user_id:
                return None
        elif user_id is not None:
            if entry.get("metadata", {}).get("user_id") != user_id:
                return None
        return entry

    def delete(self, doc_id: str, user_id: Optional[str] = None, allow_system_scope: bool = False) -> bool:
        """Delete entry if owner matches (P0-2, P1-5). Fails closed if user_id is missing without allow_system_scope."""
        if doc_id not in self._data:
            return False
        if not allow_system_scope:
            if not user_id:
                return False
            meta = self._data[doc_id].get("metadata", {})
            doc_owner = meta.get("user_id")
            if not doc_owner or doc_owner != user_id:
                return False
        self._data.pop(doc_id, None)
        self._save()
        return True

    def clear(self, user_id: Optional[str] = None, allow_system_scope: bool = False) -> None:
        """Clear entries, strictly scoped to user_id (P1-2). Fails closed if user_id is missing and allow_system_scope is False."""
        if not user_id and not allow_system_scope:
            log.warning("Rejecting JSONMemoryStore.clear: missing user_id without explicit system scope.")
            return

        if user_id is not None:
            self._data = {
                k: v for k, v in self._data.items()
                if v.get("metadata", {}).get("user_id") != user_id
            }
        elif allow_system_scope:
            self._data = {}
        self._save()

    def all_by_category(self, category: str, user_id: Optional[str] = None, allow_system_scope: bool = False) -> list[dict]:
        """Return all memories in a category scoped to owner (P1-2). Fails closed if user_id is missing without allow_system_scope."""
        if not user_id and not allow_system_scope:
            return []
        return [
            {"id": k, **v}
            for k, v in self._data.items()
            if v.get("metadata", {}).get("category") == category
            and (
                (allow_system_scope and (user_id is None or v.get("metadata", {}).get("user_id") == user_id))
                or (not allow_system_scope and v.get("metadata", {}).get("user_id") == user_id)
            )
        ]

    def count(self, user_id: Optional[str] = None, allow_system_scope: bool = False) -> int:
        if not user_id and not allow_system_scope:
            return 0
        if user_id is not None:
            return len([k for k, v in self._data.items() if v.get("metadata", {}).get("user_id") == user_id])
        return len(self._data)


# ─── Conversation Store ───────────────────────────────────────────────────────
class ConversationStore:
    """
    Stores conversation turns as an ordered list.
    Provides the sliding context window sent to the LLM.
    """

    MAX_TURNS = 100  # Maximum turns stored before oldest are pruned

    def __init__(self, file_path: Optional[Path] = None):
        self._path = Path(file_path) if file_path else CONVO_STORE
        self._turns: list[dict] = self._load()

    def _load(self) -> list:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._turns, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add_turn(
        self,
        role: str,
        content: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add a conversation turn. Role is 'user' or 'assistant'."""
        turn = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            if not session_id and "session_id" in metadata:
                session_id = metadata["session_id"]
            if not user_id and "user_id" in metadata:
                user_id = metadata["user_id"]
            turn["metadata"] = metadata
        if session_id:
            turn["session_id"] = session_id
        if user_id:
            turn["user_id"] = user_id
        self._turns.append(turn)
        # Prune old turns
        if len(self._turns) > self.MAX_TURNS:
            self._turns = self._turns[-self.MAX_TURNS:]
        self._save()

    def get_recent(self, n: int = 20, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False, limit: Optional[int] = None) -> list[dict]:
        """Return the last n turns, strictly filtered by owner and session (P1-2). Fails closed if user_id is missing without allow_system_scope."""
        if limit is not None:
            n = limit
        if not user_id and not allow_system_scope:
            return []
        matching = self._turns
        if not allow_system_scope:
            matching = [t for t in matching if t.get("user_id") == user_id]
        elif user_id is not None:
            matching = [t for t in matching if t.get("user_id") == user_id]
        if session_id is not None:
            matching = [t for t in matching if t.get("session_id") == session_id]
        return matching[-n:]

    def get_context_string(self, n: int = 10, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False, limit: Optional[int] = None) -> str:
        """Format recent conversation as a readable string for LLM context injection. Fails closed if user_id is missing without allow_system_scope."""
        if limit is not None:
            n = limit
        if not user_id and not allow_system_scope:
            return ""
        recent = self.get_recent(n, session_id=session_id, user_id=user_id, allow_system_scope=allow_system_scope)
        if not recent:
            return ""
        lines = []
        for turn in recent:
            role_label = "User" if turn["role"] == "user" else "JARVIS"
            lines.append(f"{role_label}: {turn['content']}")
        return "\n".join(lines)

    def get_unsummarized_turns(self, since_index: int = 0, user_id: Optional[str] = None, session_id: Optional[str] = None, allow_system_scope: bool = False, limit: Optional[int] = None) -> list[dict]:
        """Get turns that haven't been summarized into episodes yet, scoped to owner (P1-2). Fails closed without owner."""
        if not user_id and not allow_system_scope:
            return []
        matching = self._turns[since_index:]
        if not allow_system_scope:
            matching = [t for t in matching if t.get("user_id") == user_id]
        elif user_id is not None:
            matching = [t for t in matching if t.get("user_id") == user_id]
        if session_id is not None:
            matching = [t for t in matching if t.get("session_id") == session_id]
        if limit is not None:
            return matching[:limit]
        return matching

    def clear(self, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False) -> None:
        """Clear conversation turns, strictly scoped to user and session (P1-2). Fails closed if user_id is missing and allow_system_scope is False."""
        if not user_id and not allow_system_scope:
            log.warning("Rejecting ConversationStore.clear: missing user_id without explicit system scope.")
            return

        if user_id is not None:
            self._turns = [
                t for t in self._turns
                if not (
                    t.get("user_id") == user_id
                    and (session_id is None or t.get("session_id") == session_id)
                )
            ]
        elif allow_system_scope:
            if session_id is not None:
                self._turns = [t for t in self._turns if t.get("session_id") != session_id]
            else:
                self._turns = []
        self._save()

    def count(self, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False) -> int:
        if not user_id and not allow_system_scope:
            return 0
        matching = self._turns
        if not allow_system_scope:
            matching = [t for t in matching if t.get("user_id") == user_id]
        elif user_id is not None:
            matching = [t for t in matching if t.get("user_id") == user_id]
        if session_id is not None:
            matching = [t for t in matching if t.get("session_id") == session_id]
        return len(matching)


# ─── Episodic Memory ──────────────────────────────────────────────────────────
class EpisodicMemory:
    """
    Stores summarized interaction episodes instead of raw conversation turns.
    An episode is a condensed summary of a multi-turn interaction block.
    """

    MAX_EPISODES = 200

    def __init__(self, file_path: Optional[Path] = None):
        self._path = Path(file_path) if file_path else EPISODE_STORE
        self._episodes: list[dict] = self._load()
        self._last_summarized_index = 0  # Track which turns have been summarized

    def _load(self) -> list:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._episodes, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add_episode(self, summary: str, metadata: Optional[dict] = None, user_id: Optional[str] = None, session_id: Optional[str] = None) -> None:
        """Store an episode summary with explicit owner and session tags (P0-2)."""
        if isinstance(metadata, dict):
            meta = metadata.copy()
        elif isinstance(metadata, list):
            meta = {"steps": metadata}
        else:
            meta = {}
        if user_id:
            meta["user_id"] = user_id
        if session_id:
            meta["session_id"] = session_id
        self._episodes.append({
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": meta,
        })
        # Prune old episodes
        if len(self._episodes) > self.MAX_EPISODES:
            self._episodes = self._episodes[-self.MAX_EPISODES:]
        self._save()
        log.info(f"Episode stored (user={user_id}, session={session_id}): {summary[:80]}...")

    def get_recent(self, n: int = 10, user_id: Optional[str] = None, session_id: Optional[str] = None, allow_system_scope: bool = False, limit: Optional[int] = None) -> list[dict]:
        """Return the most recent episodes, filtered by owner and session (P0-1, P0-2, P1-5)."""
        if limit is not None:
            n = limit
        if not user_id and not allow_system_scope:
            return []
        matching = self._episodes
        if not allow_system_scope:
            matching = [ep for ep in matching if ep.get("metadata", {}).get("user_id") == user_id]
        elif user_id is not None:
            matching = [ep for ep in matching if ep.get("metadata", {}).get("user_id") == user_id]
        if session_id is not None:
            matching = [ep for ep in matching if ep.get("metadata", {}).get("session_id") == session_id]
        return matching[-n:]

    def search(self, query: str, top_k: int = 5, user_id: Optional[str] = None, session_id: Optional[str] = None, allow_system_scope: bool = False) -> list[dict]:
        """Keyword search across episodes, filtered by owner and session (P0-1, P0-2, P1-5)."""
        if not user_id and not allow_system_scope:
            return []
        query_lower = query.lower()
        matches = []
        for ep in self._episodes:
            ep_meta = ep.get("metadata", {})
            if not allow_system_scope:
                if ep_meta.get("user_id") != user_id:
                    continue
            elif user_id is not None and ep_meta.get("user_id") != user_id:
                continue
            if session_id is not None and ep_meta.get("session_id") != session_id:
                continue
            if query_lower in ep["summary"].lower():
                matches.append(ep)
        return matches[-top_k:]

    def count(self, user_id: Optional[str] = None, session_id: Optional[str] = None, allow_system_scope: bool = False) -> int:
        if not user_id and not allow_system_scope:
            return 0
        return len(self.get_recent(n=self.MAX_EPISODES, user_id=user_id, session_id=session_id, allow_system_scope=allow_system_scope))

    def clear(self, user_id: Optional[str] = None, session_id: Optional[str] = None, allow_system_scope: bool = False) -> None:
        """Clear episodes, strictly scoped to user and session (P1-2). Fails closed if user_id is missing without allow_system_scope."""
        if not user_id and not allow_system_scope:
            log.warning("Rejecting EpisodicMemory.clear: missing user_id without explicit system scope.")
            return

        if user_id is not None:
            self._episodes = [
                ep for ep in self._episodes
                if not (
                    ep.get("metadata", {}).get("user_id") == user_id
                    and (session_id is None or ep.get("metadata", {}).get("session_id") == session_id)
                )
            ]
        elif allow_system_scope:
            if session_id is not None:
                self._episodes = [ep for ep in self._episodes if ep.get("metadata", {}).get("session_id") != session_id]
            else:
                self._episodes = []
        self._save()


# ─── Main Memory System ───────────────────────────────────────────────────────
class JarvisMemory:
    """
    Primary JARVIS memory system (v2.0 — Tiered Architecture).
    Uses ChromaDB for semantic vector retrieval when available,
    otherwise falls back to JSON keyword search.

    Key behavior changes from v1:
    - Conversation turns are NO LONGER mirrored to long-term memory automatically
    - Only high-importance user messages are stored (scored by importance)
    - Episodic summaries replace raw turn storage
    """

    CATEGORIES = ("conversation", "preference", "task", "knowledge", "workflow")

    def __init__(self):
        log.info("Initializing JARVIS Memory System v2.0...")
        self._json_store    = JSONMemoryStore(JSON_STORE)
        self.conversations  = ConversationStore()
        self.episodes       = EpisodicMemory()
        self._chroma_client = None
        self._collection    = None
        
        # Cache preferences in-memory
        self._cached_preferences = {}
        self._pref_lock = threading.Lock()

        if HAS_CHROMA:
            self._init_chroma()

        # Warm start preference cache
        self._init_pref_cache()

        log.info(
            f"Memory system ready — "
            f"{'ChromaDB (semantic)' if self._collection else 'JSON (keyword)'} backend active. "
            f"Stored memories: {self._json_store.count(allow_system_scope=True)} | "
            f"Episodes: {self.episodes.count(allow_system_scope=True)}"
        )

    def _init_chroma(self) -> None:
        """Initialize ChromaDB persistent client and memory collection."""
        try:
            global _GLOBAL_CHROMA_CLIENT
            if _GLOBAL_CHROMA_CLIENT is None:
                CHROMA_DIR.mkdir(parents=True, exist_ok=True)
                _GLOBAL_CHROMA_CLIENT = chromadb.PersistentClient(
                    path=str(CHROMA_DIR),
                    settings=Settings(anonymized_telemetry=False),
                )
            self._chroma_client = _GLOBAL_CHROMA_CLIENT
            
            # Setup ONNX runtime optimized MiniLM-L6-v2 model for single-digit ms embedding latency
            try:
                from chromadb.utils.embedding_functions import ONNXMiniLM_L6_v2
                self._embedding_fn = ONNXMiniLM_L6_v2()
                log.info("Loaded ONNXMiniLM_L6_v2 embedding function successfully.")
            except Exception as ef_err:
                log.warning(f"Could not load ONNXMiniLM_L6_v2: {ef_err}. Falling back to default embedder.")
                try:
                    from chromadb.utils import embedding_functions
                    self._embedding_fn = embedding_functions.DefaultEmbeddingFunction()
                except Exception as ef_err_2:
                    log.warning(f"Could not load DefaultEmbeddingFunction: {ef_err_2}. Using None.")
                    self._embedding_fn = None

            self._collection = self._chroma_client.get_or_create_collection(
                name="jarvis_memory",
                metadata={"hnsw:space": "cosine"},
                embedding_function=self._embedding_fn,
            )
            try:
                doc_count = self._collection.count()
                log.info(f"ChromaDB collection loaded. Documents: {doc_count}")
            except Exception:
                log.info("ChromaDB collection loaded.")
        except Exception as e:
            error_log.error(f"ChromaDB initialization failed: {e}")
            self._chroma_client = None
            self._collection = None

    def _init_pref_cache(self) -> None:
        """Start a background thread to pre-populate the preference cache."""
        self._pref_warm_flag = False
        def _worker():
            try:
                # Query user preferences (without blocking the initialization thread)
                # Use allow_system_scope=True for internal maintenance cache warming
                prefs = self.retrieve_memories("User preference", top_k=50, category="preference", allow_system_scope=True)
                cached = {}
                for p in prefs:
                    if "preference — " in p["content"]:
                        parts = p["content"].split("preference — ", 1)[1].split(":", 1)
                        if len(parts) == 2:
                            u_id = p.get("metadata", {}).get("user_id")
                            pref_k = parts[0].strip()
                            pref_v = parts[1].strip()
                            if u_id:
                                cached[f"{u_id}:{pref_k}"] = pref_v
                            else:
                                cached[pref_k] = pref_v
                with self._pref_lock:
                    for k, v in cached.items():
                        if k not in self._cached_preferences:
                            self._cached_preferences[k] = v
                log.info(f"[JarvisMemory] Pre-fetched {len(cached)} user preferences into cache.")
            except Exception as e:
                error_log.error(f"Failed to pre-populate preference cache: {e}")
            finally:
                self._pref_warm_flag = True
                
        threading.Thread(target=_worker, daemon=True).start()

    @property
    def is_warm(self) -> bool:
        """Returns True if the database/preference cache has been warmed up."""
        if not HAS_CHROMA:
            return True
        with self._pref_lock:
            return hasattr(self, '_pref_warm_flag') and self._pref_warm_flag

    # ─── Store ───────────────────────────────────────────────────────────────

    def store_memory(
        self,
        content: str,
        category: str = "knowledge",
        metadata: Optional[dict] = None,
        encrypt: bool = False,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Store a new memory entry with explicit owner metadata (P0-2).

        Args:
            content:  The text to remember.
            category: One of CATEGORIES.
            metadata: Optional dict of extra metadata.
            encrypt:  If True, encrypt content before storing.
            user_id:  Optional user identifier who owns this memory.

        Returns:
            The unique memory ID.
        """
        if category not in self.CATEGORIES:
            category = "knowledge"

        doc_id = str(uuid.uuid4())
        stored_content = encryption.encrypt(content) if encrypt else content

        meta = {
            "category":  category,
            "encrypted": str(encrypt),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }
        if user_id:
            meta["user_id"] = user_id
        elif metadata and "user_id" in metadata:
            meta["user_id"] = metadata["user_id"]

        # Store in ChromaDB if available
        if self._collection:
            try:
                self._collection.add(
                    ids=[doc_id],
                    documents=[stored_content],
                    metadatas=[meta],
                )
            except Exception as e:
                error_log.error(f"ChromaDB store failed: {e}")

        # Always mirror in JSON store as backup
        self._json_store.add(doc_id, stored_content, meta)
        log.info(f"Memory stored [{category}] (user={meta.get('user_id')}): {content[:80]}...")
        return doc_id

    def store_preference(self, key: str, value: str, user_id: Optional[str] = None) -> None:
        """Store or update an owner preference with user ownership (P0-2)."""
        cache_key = f"{user_id}:{key}" if user_id else key
        with self._pref_lock:
            self._cached_preferences[cache_key] = value

        # Use a deterministic ID so we can overwrite preferences per user
        doc_id = f"pref_{user_id}_{key}" if user_id else f"pref_{key}"
        meta = {
            "category":  "preference",
            "key":       key,
            "encrypted": "False",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if user_id:
            meta["user_id"] = user_id
        content = f"User preference — {key}: {value}"

        # Remove old entry if it exists
        if self._collection:
            try:
                self._collection.delete(ids=[doc_id])
            except Exception:
                pass

        self._json_store.delete(doc_id, user_id=user_id)

        # Store fresh
        if self._collection:
            try:
                self._collection.add(ids=[doc_id], documents=[content], metadatas=[meta])
            except Exception as e:
                error_log.error(f"ChromaDB preference store failed: {e}")
        self._json_store.add(doc_id, content, meta)
        log.info(f"Preference saved (user={user_id}): {key} = {value}")

    # ─── Retrieve ─────────────────────────────────────────────────────────────

    def retrieve_memories(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        user_id: Optional[str] = None,
        allow_system_scope: bool = False,
    ) -> list[dict]:
        """
        Semantically retrieve the most relevant memories for a query, strictly filtered by user ownership (P0-1, P0-2, P1-5).
        Fails closed (returns []) if user_id is missing and not allow_system_scope.

        Returns a list of dicts: [{id, content, metadata, distance}, ...]
        """
        if not user_id and not allow_system_scope:
            return []

        if self._collection:
            try:
                if not allow_system_scope:
                    if category:
                        where = {"$and": [{"category": category}, {"user_id": user_id}]}
                    else:
                        where = {"user_id": user_id}
                else:
                    if category and user_id:
                        where = {"$and": [{"category": category}, {"user_id": user_id}]}
                    elif user_id:
                        where = {"user_id": user_id}
                    elif category:
                        where = {"category": category}
                    else:
                        where = None

                results = self._collection.query(
                    query_texts=[query],
                    n_results=min(top_k, max(1, self._collection.count())),
                    where=where,
                )
                memories = []
                for i, doc_id in enumerate(results["ids"][0]):
                    doc      = results["documents"][0][i]
                    meta     = results["metadatas"][0][i]
                    distance = results["distances"][0][i] if "distances" in results else 0.0

                    # Decrypt if needed
                    if meta.get("encrypted") == "True":
                        try:
                            doc = encryption.decrypt(doc)
                        except Exception:
                            doc = "[encrypted — decryption failed]"

                    memories.append({
                        "id":       doc_id,
                        "content":  doc,
                        "metadata": meta,
                        "distance": distance,
                    })
                return memories
            except Exception as e:
                error_log.error(f"ChromaDB query failed: {e}")

        # JSON fallback
        raw = self._json_store.search(query, top_k=top_k, category=category, user_id=user_id, allow_system_scope=allow_system_scope)
        return [{"id": r["id"], "content": r["content"], "metadata": r["metadata"], "distance": 0.5} for r in raw]

    def get_preference(self, key: str, user_id: Optional[str] = None, allow_system_scope: bool = False) -> Optional[str]:
        """Retrieve a stored preference by key (checks cache first) for a specific user (P0-1, P0-2, P1-5)."""
        if not user_id and not allow_system_scope:
            return None
        cache_key = f"{user_id}:{key}" if user_id else key
        with self._pref_lock:
            if cache_key in self._cached_preferences:
                return self._cached_preferences[cache_key]

        # Cache miss fallback
        results = self.retrieve_memories(f"User preference — {key}", top_k=3, category="preference", user_id=user_id, allow_system_scope=allow_system_scope)
        for r in results:
            if f"preference — {key}:" in r["content"].lower():
                parts = r["content"].split(":", 1)
                val = parts[-1].strip() if len(parts) > 1 else None
                if val is not None:
                    # Update cache
                    with self._pref_lock:
                        self._cached_preferences[cache_key] = val
                    return val
        return None

    def build_context_snippet(
        self,
        query: str,
        max_memories: int = 5,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        allow_system_scope: bool = False,
    ) -> str:
        """
        Build a concise memory context string to inject into the LLM prompt.
        Combines relevant long-term memories with recent episodic summaries, strictly scoped to user_id (P0-1, P0-2, P1-5).
        Fails closed if user_id is missing and allow_system_scope is False.
        """
        if not user_id and not allow_system_scope:
            return ""

        # Clean query to check for generic greetings or short strings
        q_clean = query.strip().lower().replace("jarvis", "").replace(".", "").replace("!", "").replace(",", "").strip()
        greetings = {"hi", "hello", "hii", "hey", "yo", "sup", "good morning", "good afternoon", "good evening", "greetings"}
        
        if q_clean in greetings or len(q_clean) < 4:
            log.debug(f"[Memory] Greeting/short query '{query}' detected. Skipping context retrieval to prevent hallucination.")
            return ""

        parts = []

        # Long-term semantic memories scoped to owner
        memories = self.retrieve_memories(query, top_k=max_memories, user_id=user_id, allow_system_scope=allow_system_scope)
        
        # Filter memories by strict similarity threshold (HNSW cosine distance <= 0.55)
        # Closer to 0.0 is more similar; 0.55 filters out low-relevance matches.
        valid_memories = [m for m in memories if m.get("distance", 1.0) <= 0.55]
        
        if valid_memories:
            lines = ["[JARVIS MEMORY — Relevant knowledge]"]
            for m in valid_memories:
                cat = m["metadata"].get("category", "?")
                lines.append(f"  [{cat}] {m['content'][:200]}")
            parts.append("\n".join(lines))

        # Recent episodic context scoped to owner and session
        recent_episodes = self.episodes.search(query, top_k=3, user_id=user_id, session_id=session_id, allow_system_scope=allow_system_scope)
        if recent_episodes:
            ep_lines = ["[JARVIS EPISODES — Recent interaction summaries]"]
            for ep in recent_episodes:
                ep_lines.append(f"  {ep['summary'][:200]}")
            parts.append("\n".join(ep_lines))

        return "\n\n".join(parts)

    # ─── Conversation (v2: NO automatic long-term mirroring) ──────────────────

    def add_conversation_turn(self, role: str, content: str, session_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
        """
        Log a conversation turn.

        v2 change: Only stores to the conversation sliding window.
        High-importance user messages are separately scored and stored.
        Raw turns are NO LONGER auto-mirrored to long-term memory.
        """
        self.conversations.add_turn(role, content, session_id=session_id, user_id=user_id)

        # Only store genuinely important user messages in long-term memory
        importance = score_importance(content, role)
        if importance >= IMPORTANCE_THRESHOLD:
            meta = {"role": role, "importance": str(importance), "source": "conversation"}
            if session_id:
                meta["session_id"] = session_id
            if user_id:
                meta["user_id"] = user_id
            self.store_memory(
                content,
                category="knowledge",
                metadata=meta,
                user_id=user_id,
            )
            log.debug(f"High-importance message stored (score={importance:.2f}, user={user_id}): {content[:60]}")

    def get_recent_conversation(self, n: int = 15, session_id: Optional[str] = None, user_id: Optional[str] = None, allow_system_scope: bool = False) -> list[dict]:
        return self.conversations.get_recent(n, session_id=session_id, user_id=user_id, allow_system_scope=allow_system_scope)

    # ─── Episodic Summary ─────────────────────────────────────────────────────

    def create_episode_summary(
        self,
        summary: str,
        metadata: Optional[dict] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Store an episodic summary of a conversation block or task execution with owner and session metadata (P0-2).
        Called by the Brain/MemoryManager after a meaningful interaction block.

        Args:
            summary:    Condensed summary of the interaction.
            metadata:   Optional metadata (task name, topic, etc.)
            user_id:    Owner identity.
            session_id: Originating session identifier.
        """
        meta = metadata.copy() if metadata else {}
        if user_id:
            meta["user_id"] = user_id
        if session_id:
            meta["session_id"] = session_id
        self.episodes.add_episode(summary, meta, user_id=user_id, session_id=session_id)

        # Also store in semantic memory for cross-session retrieval within same user
        self.store_memory(
            f"Episode: {summary}",
            category="knowledge",
            metadata={"type": "episode", **meta},
            user_id=user_id,
        )

    # ─── Introspection ────────────────────────────────────────────────────────

    def stats(self, user_id: Optional[str] = None, allow_system_scope: bool = False) -> dict:
        """Return memory system statistics (P1-2). Scoped to user_id or system."""
        chroma_count = self._collection.count() if (self._collection and allow_system_scope) else 0
        return {
            "backend":            "ChromaDB" if self._collection else "JSON",
            "long_term_memories": (chroma_count if allow_system_scope else self._json_store.count(user_id=user_id, allow_system_scope=allow_system_scope)),
            "conversation_turns": self.conversations.count(user_id=user_id, allow_system_scope=allow_system_scope),
            "episodes":           self.episodes.count(user_id=user_id, allow_system_scope=allow_system_scope),
        }

    def delete_memory(
        self,
        memory_id: Optional[str] = None,
        query: Optional[str] = None,
        user_id: Optional[str] = None,
        allow_system_scope: bool = False,
    ) -> bool:
        """
        Delete a specific memory by ID or by closest query match, checking ownership (P0-2, P1-5).
        Fails closed if user_id is missing and allow_system_scope is False.
        Rejects deletion of unowned legacy records or records owned by other users.
        Returns True if a memory was deleted.
        """
        if not user_id and not allow_system_scope:
            log.warning("Rejecting memory deletion: missing user_id without explicit system scope.")
            return False

        if memory_id:
            if self._collection:
                try:
                    rec = self._collection.get(ids=[memory_id])
                    if rec and rec["ids"]:
                        meta = rec["metadatas"][0] if rec["metadatas"] else {}
                        doc_owner = meta.get("user_id")
                        if not allow_system_scope:
                            if not doc_owner or doc_owner != user_id:
                                log.warning(f"Rejecting memory deletion: ID {memory_id} owner '{doc_owner}' does not match caller '{user_id}'")
                                return False
                        elif user_id is not None and doc_owner != user_id:
                            return False
                        self._collection.delete(ids=[memory_id])
                    else:
                        pass
                except Exception as e:
                    error_log.error(f"ChromaDB delete by id failed: {e}")
            res = self._json_store.delete(memory_id, user_id=user_id, allow_system_scope=allow_system_scope)
            with self._pref_lock:
                self._cached_preferences.clear()
            if res:
                log.info(f"Deleted memory by ID: {memory_id}")
            return res

        if query:
            matches = self.retrieve_memories(query, top_k=1, user_id=user_id, allow_system_scope=allow_system_scope)
            if matches:
                # Require relevant semantic similarity threshold (distance <= 0.45) to avoid false-positive deletion of unrelated records
                match_distance = matches[0].get("distance", 0.0)
                if match_distance > 0.45:
                    log.info(f"Memory deletion by query rejected: best match distance {match_distance:.3f} exceeds 0.45 threshold.")
                    return False

                target_id = matches[0]["id"]
                target_meta = matches[0].get("metadata", {})
                target_owner = target_meta.get("user_id")
                if not allow_system_scope:
                    if not target_owner or target_owner != user_id:
                        log.warning(f"Rejecting memory deletion: matched ID {target_id} owner '{target_owner}' does not match caller '{user_id}'")
                        return False
                elif user_id is not None and target_owner != user_id:
                    return False

                if self._collection:
                    try:
                        self._collection.delete(ids=[target_id])
                    except Exception as e:
                        error_log.error(f"ChromaDB delete failed: {e}")
                res = self._json_store.delete(target_id, user_id=user_id, allow_system_scope=allow_system_scope)
                with self._pref_lock:
                    self._cached_preferences.clear()
                log.info(f"Deleted memory: {matches[0].get('content', '')[:60]} (ID: {target_id})")
                return True
        return False

    def clear_all(self, user_id: Optional[str] = None, allow_system_scope: bool = False) -> bool:
        """Clear memory. If user_id is provided, only wipes that user's memory (P0-2, P1-2). Fails closed without user_id or allow_system_scope."""
        if not user_id and not allow_system_scope:
            log.warning("Rejecting clear_all: missing user_id without explicit system scope.")
            return False

        self.conversations.clear(user_id=user_id, allow_system_scope=allow_system_scope)
        self.episodes.clear(user_id=user_id, allow_system_scope=allow_system_scope)

        if self._collection:
            try:
                if user_id is not None:
                    self._collection.delete(where={"user_id": user_id})
                elif allow_system_scope:
                    self._chroma_client.delete_collection("jarvis_memory")
                    self._collection = None
                    self._init_chroma()
            except Exception as e:
                error_log.error(f"ChromaDB clear failed: {e}")

        # JSON store
        self._json_store.clear(user_id=user_id, allow_system_scope=allow_system_scope)
        with self._pref_lock:
            if user_id:
                to_del = [k for k in self._cached_preferences if k.startswith(f"{user_id}:")]
                for k in to_del:
                    self._cached_preferences.pop(k, None)
            elif allow_system_scope:
                self._cached_preferences.clear()
        log.warning(f"Memory cleared for user={user_id or 'ALL (system authorized)'}.")
        return True
