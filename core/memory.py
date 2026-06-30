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

    def search(self, query: str, top_k: int = 5, category: Optional[str] = None) -> list[dict]:
        """Simple keyword search (not semantic) as fallback."""
        query_lower = query.lower()
        results = []
        import re
        try:
            pattern = re.compile(rf"\b{re.escape(query_lower)}\b")
        except:
            pattern = None

        for doc_id, entry in self._data.items():
            if category and entry["metadata"].get("category") != category:
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

    def get(self, doc_id: str) -> Optional[dict]:
        return self._data.get(doc_id)

    def delete(self, doc_id: str) -> None:
        self._data.pop(doc_id, None)
        self._save()

    def all_by_category(self, category: str) -> list[dict]:
        return [
            {"id": k, **v}
            for k, v in self._data.items()
            if v["metadata"].get("category") == category
        ]

    def count(self) -> int:
        return len(self._data)


# ─── Conversation Store ───────────────────────────────────────────────────────
class ConversationStore:
    """
    Stores conversation turns as an ordered list.
    Provides the sliding context window sent to the LLM.
    """

    MAX_TURNS = 100  # Maximum turns stored before oldest are pruned

    def __init__(self):
        self._path = CONVO_STORE
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

    def add_turn(self, role: str, content: str) -> None:
        """Add a conversation turn. Role is 'user' or 'assistant'."""
        self._turns.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Prune old turns
        if len(self._turns) > self.MAX_TURNS:
            self._turns = self._turns[-self.MAX_TURNS:]
        self._save()

    def get_recent(self, n: int = 20) -> list[dict]:
        """Return the last n turns."""
        return self._turns[-n:]

    def get_context_string(self, n: int = 10) -> str:
        """Format recent conversation as a readable string for LLM context injection."""
        recent = self.get_recent(n)
        if not recent:
            return ""
        lines = []
        for turn in recent:
            role_label = "User" if turn["role"] == "user" else "JARVIS"
            lines.append(f"{role_label}: {turn['content']}")
        return "\n".join(lines)

    def get_unsummarized_turns(self, since_index: int = 0) -> list[dict]:
        """Get turns that haven't been summarized into episodes yet."""
        return self._turns[since_index:]

    def clear(self) -> None:
        self._turns = []
        self._save()

    def count(self) -> int:
        return len(self._turns)


# ─── Episodic Memory ──────────────────────────────────────────────────────────
class EpisodicMemory:
    """
    Stores summarized interaction episodes instead of raw conversation turns.
    An episode is a condensed summary of a multi-turn interaction block.
    """

    MAX_EPISODES = 200

    def __init__(self):
        self._path = EPISODE_STORE
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

    def add_episode(self, summary: str, metadata: Optional[dict] = None) -> None:
        """Store an episode summary."""
        self._episodes.append({
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        })
        # Prune old episodes
        if len(self._episodes) > self.MAX_EPISODES:
            self._episodes = self._episodes[-self.MAX_EPISODES:]
        self._save()
        log.info(f"Episode stored: {summary[:80]}...")

    def get_recent(self, n: int = 10) -> list[dict]:
        """Return the most recent episodes."""
        return self._episodes[-n:]

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Simple keyword search across episodes."""
        query_lower = query.lower()
        matches = [
            ep for ep in self._episodes
            if query_lower in ep["summary"].lower()
        ]
        return matches[-top_k:]

    def count(self) -> int:
        return len(self._episodes)


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

        if HAS_CHROMA:
            self._init_chroma()

        log.info(
            f"Memory system ready — "
            f"{'ChromaDB (semantic)' if self._collection else 'JSON (keyword)'} backend active. "
            f"Stored memories: {self._json_store.count()} | "
            f"Episodes: {self.episodes.count()}"
        )

    def _init_chroma(self) -> None:
        """Initialize ChromaDB persistent client and memory collection."""
        try:
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(
                path=str(CHROMA_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._chroma_client.get_or_create_collection(
                name="jarvis_memory",
                metadata={"hnsw:space": "cosine"},
            )
            log.info(f"ChromaDB collection loaded. Documents: {self._collection.count()}")
        except Exception as e:
            error_log.error(f"ChromaDB initialization failed: {e}")
            self._chroma_client = None
            self._collection = None

    # ─── Store ───────────────────────────────────────────────────────────────

    def store_memory(
        self,
        content: str,
        category: str = "knowledge",
        metadata: Optional[dict] = None,
        encrypt: bool = False,
    ) -> str:
        """
        Store a new memory entry.

        Args:
            content:  The text to remember.
            category: One of CATEGORIES.
            metadata: Optional dict of extra metadata.
            encrypt:  If True, encrypt content before storing.

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
        log.info(f"Memory stored [{category}]: {content[:80]}...")
        return doc_id

    def store_preference(self, key: str, value: str) -> None:
        """Store or update an owner preference."""
        # Use a deterministic ID so we can overwrite preferences
        doc_id = f"pref_{key}"
        meta = {
            "category":  "preference",
            "key":       key,
            "encrypted": "False",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        content = f"User preference — {key}: {value}"

        # Remove old entry if it exists
        if self._collection:
            try:
                self._collection.delete(ids=[doc_id])
            except Exception:
                pass

        self._json_store.delete(doc_id)

        # Store fresh
        if self._collection:
            try:
                self._collection.add(ids=[doc_id], documents=[content], metadatas=[meta])
            except Exception as e:
                error_log.error(f"ChromaDB preference store failed: {e}")
        self._json_store.add(doc_id, content, meta)
        log.info(f"Preference saved: {key} = {value}")

    # ─── Retrieve ─────────────────────────────────────────────────────────────

    def retrieve_memories(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantically retrieve the most relevant memories for a query.

        Returns a list of dicts: [{id, content, metadata, distance}, ...]
        """
        if self._collection:
            try:
                where = {"category": category} if category else None
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
        raw = self._json_store.search(query, top_k=top_k, category=category)
        return [{"id": r["id"], "content": r["content"], "metadata": r["metadata"], "distance": 0.5} for r in raw]

    def get_preference(self, key: str) -> Optional[str]:
        """Retrieve a stored preference by key."""
        results = self.retrieve_memories(f"User preference — {key}", top_k=3, category="preference")
        for r in results:
            if f"preference — {key}:" in r["content"].lower():
                parts = r["content"].split(":", 1)
                return parts[-1].strip() if len(parts) > 1 else None
        return None

    def build_context_snippet(self, query: str, max_memories: int = 5) -> str:
        """
        Build a concise memory context string to inject into the LLM prompt.
        Combines relevant long-term memories with recent episodic summaries.
        """
        # Skip context injection for short greetings or acknowledgements to prevent hallucination
        if len(query.strip()) < 4 or query.strip().lower() in ["hi", "hello", "hey", "ok", "yes", "no"]:
            return ""

        parts = []

        # Long-term semantic memories
        memories = self.retrieve_memories(query, top_k=max_memories)
        if memories:
            lines = ["[JARVIS MEMORY — Relevant knowledge]"]
            for m in memories:
                cat = m["metadata"].get("category", "?")
                lines.append(f"  [{cat}] {m['content'][:200]}")
            parts.append("\n".join(lines))

        # Recent episodic context
        recent_episodes = self.episodes.search(query, top_k=3)
        if recent_episodes:
            ep_lines = ["[JARVIS EPISODES — Recent interaction summaries]"]
            for ep in recent_episodes:
                ep_lines.append(f"  {ep['summary'][:200]}")
            parts.append("\n".join(ep_lines))

        return "\n\n".join(parts)

    # ─── Conversation (v2: NO automatic long-term mirroring) ──────────────────

    def add_conversation_turn(self, role: str, content: str) -> None:
        """
        Log a conversation turn.

        v2 change: Only stores to the conversation sliding window.
        High-importance user messages are separately scored and stored.
        Raw turns are NO LONGER auto-mirrored to long-term memory.
        """
        self.conversations.add_turn(role, content)

        # Only store genuinely important user messages in long-term memory
        importance = score_importance(content, role)
        if importance >= IMPORTANCE_THRESHOLD:
            self.store_memory(
                content,
                category="knowledge",
                metadata={"role": role, "importance": str(importance), "source": "conversation"},
            )
            log.debug(f"High-importance message stored (score={importance:.2f}): {content[:60]}")

    def get_recent_conversation(self, n: int = 15) -> list[dict]:
        return self.conversations.get_recent(n)

    # ─── Episodic Summary ─────────────────────────────────────────────────────

    def create_episode_summary(self, summary: str, metadata: Optional[dict] = None) -> None:
        """
        Store an episodic summary of a conversation block or task execution.
        Called by the Brain/MemoryManager after a meaningful interaction block.

        Args:
            summary:  Condensed summary of the interaction.
            metadata: Optional metadata (task name, topic, etc.)
        """
        self.episodes.add_episode(summary, metadata)

        # Also store in semantic memory for cross-session retrieval
        self.store_memory(
            f"Episode: {summary}",
            category="knowledge",
            metadata={"type": "episode", **(metadata or {})},
        )

    # ─── Introspection ────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return memory system statistics."""
        chroma_count = self._collection.count() if self._collection else 0
        return {
            "backend":            "ChromaDB" if self._collection else "JSON",
            "long_term_memories": chroma_count or self._json_store.count(),
            "conversation_turns": self.conversations.count(),
            "episodes":           self.episodes.count(),
        }

    def clear_all(self) -> None:
        """Wipe all memory. DESTRUCTIVE — requires confirmation at call site."""
        self.conversations.clear()
        self.episodes._episodes = []
        self.episodes._save()
        if self._collection:
            try:
                self._chroma_client.delete_collection("jarvis_memory")
                self._collection = None
                self._init_chroma()
            except Exception as e:
                error_log.error(f"ChromaDB clear failed: {e}")
        # Overwrite JSON store
        self._json_store._data = {}
        self._json_store._save()
        log.warning("All JARVIS memory has been cleared.")
