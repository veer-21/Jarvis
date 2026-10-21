"""
JARVIS — Memory Agent
Background agent for intelligent memory operations:
auto-summarization, importance scoring, and proactive context preparation.
"""

from core.logger import log
from core.agents.base_agent import BaseAgent, AgentMessage, AgentResponse, AgentRole


class MemoryAgent(BaseAgent):
    """
    Memory Agent — handles background memory operations.
    Decides what to remember vs forget, auto-summarizes conversations,
    and prepares proactive context for upcoming interactions.
    """

    # Auto-summarize after this many unsummarized turns
    SUMMARIZE_THRESHOLD = 20

    def __init__(self, memory=None, brain_send=None):
        super().__init__("memory", AgentRole.MEMORY)
        self._memory = memory
        self._brain_send = brain_send  # Function to call LLM for summarization
        self._unsummarized_turns: dict[tuple[str, Optional[str]], int] = {}

    def set_memory(self, memory) -> None:
        self._memory = memory

    def set_brain_sender(self, fn) -> None:
        self._brain_send = fn

    def process(self, message: AgentMessage) -> AgentResponse:
        """
        Process memory-related requests.

        Supported actions (via metadata["action"]):
            - "store": Store content in long-term memory
            - "retrieve": Retrieve relevant memories
            - "summarize": Create an episodic summary
            - "check_summarize": Check if auto-summarization is needed
            - "update_project_brain": Update persistent project memory files in 'brain/'
        """
        action = message.metadata.get("action", "retrieve")

        if action == "store":
            return self._handle_store(message)
        elif action == "retrieve":
            return self._handle_retrieve(message)
        elif action == "summarize":
            return self._handle_summarize(message)
        elif action == "check_summarize":
            return self._check_auto_summarize(message)
        elif action == "update_project_brain":
            return self._handle_project_brain_update(message)
        else:
            return AgentResponse(
                success=False,
                content=f"Unknown memory action: {action}",
                agent=self.name,
                error=f"Unknown action: {action}",
            )

    def _handle_project_brain_update(self, message: AgentMessage) -> AgentResponse:
        """Update the Project Brain markdown files from recent task memories."""
        from core.logger import error_log
        from datetime import datetime
        
        if not self._memory:
            return AgentResponse(success=False, content="No memory system attached", agent=self.name)
        if not self._brain_send:
            return AgentResponse(success=False, content="No brain send handler configured", agent=self.name)

        user_id = message.user_id
        is_system = getattr(message, "system_authorized", False)
        if not user_id and not is_system:
            return AgentResponse(
                success=False,
                content="Project Brain update requires verified user ownership or explicit system authorization.",
                agent=self.name,
                error="UNAUTHORIZED_MISSING_OWNER"
            )

        try:
            # 1. Fetch recent task results from task memory scoped to owner
            tasks = self._memory.retrieve_memories("Task", category="task", top_k=10, user_id=user_id, allow_system_scope=is_system)
            if not tasks:
                return AgentResponse(
                    success=True,
                    content="No recent tasks found in memory to process.",
                    agent=self.name
                )

            task_logs = "\n".join([f"- {t['content']}" for t in tasks])

            # 2. Query LLM to identify updates
            prompt = (
                "You are the JARVIS Memory Agent. Analyze the following recent task execution history and identify if we should update our persistent project memory files in the 'brain/' directory:\n\n"
                f"[RECENT TASK HISTORY]\n{task_logs}\n\n"
                "Focus on three aspects:\n"
                "1. DECISIONS: Any new engineering/architectural decisions made (e.g. database choice, library additions).\n"
                "2. PATTERNS: New implementation patterns or workflow styles that were established.\n"
                "3. MISTAKES: Errors, bugs, or pitfalls that were resolved and should be avoided in the future.\n\n"
                "Provide the output as a valid JSON object with keys 'decisions', 'patterns', and 'mistakes'. Each value should be a bulleted list of findings to append to the respective file, or empty string if nothing new was identified.\n\n"
                "Example output format:\n"
                "{\n"
                "  \"decisions\": \"- Decision: Added libraries X and Y to support Z\",\n"
                "  \"patterns\": \"- Pattern: Use decorator @verify for API routes\",\n"
                "  \"mistakes\": \"- Problem: Connection timeout\\n  Cause: Missing keep-alive headers\\n  Fix: Set timeout=60\"\n"
                "}"
            )

            res = self._brain_send(prompt)
            
            # Clean and parse JSON
            import json
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', res, re.DOTALL)
            if json_match:
                res = json_match.group(1)
            else:
                res = res.strip()
                
            updates = json.loads(res)
            
            import os
            from pathlib import Path
            project_brain_dir = Path(os.getcwd()) / "brain"
            if not project_brain_dir.exists():
                project_brain_dir.mkdir(parents=True, exist_ok=True)
                
            updated_files = []
            
            for file_key, filename in [("decisions", "decisions.md"), ("patterns", "patterns.md"), ("mistakes", "mistakes.md")]:
                content_to_append = updates.get(file_key, "").strip()
                if content_to_append:
                    file_path = project_brain_dir / filename
                    # Ensure file exists, then append
                    mode = "a" if file_path.exists() else "w"
                    prefix = "\n\n" if file_path.exists() else ""
                    with open(file_path, mode, encoding="utf-8") as f:
                        f.write(f"{prefix}## Added via Auto-Update ({datetime.now().strftime('%Y-%m-%d')})\n\n{content_to_append}\n")
                    updated_files.append(filename)
                    
            # If files were updated, refresh master-memory.md
            if updated_files:
                master_path = project_brain_dir / "master-memory.md"
                if master_path.exists():
                    with open(master_path, "a", encoding="utf-8") as f:
                        f.write(f"\n\n*Last auto-update run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
                
                return AgentResponse(
                    success=True,
                    content=f"Successfully updated Project Brain files: {', '.join(updated_files)}",
                    agent=self.name
                )
            
            return AgentResponse(
                success=True,
                content="Task history analyzed; no new decisions, patterns, or mistakes identified.",
                agent=self.name
            )

        except Exception as e:
            error_log.error(f"Project Brain update failed: {e}")
            return AgentResponse(
                success=False,
                content=f"Project Brain update failed: {e}",
                agent=self.name,
                error=str(e)
            )

    def _handle_store(self, message: AgentMessage) -> AgentResponse:
        """Store content in memory scoped to authenticated owner (P0-1, P0-3)."""
        if not self._memory:
            return AgentResponse(success=False, content="No memory system", agent=self.name)

        user_id = message.user_id
        is_system = getattr(message, "system_authorized", False)
        if not user_id and not is_system:
            return AgentResponse(
                success=False,
                content="Memory store requires verified user ownership.",
                agent=self.name,
                error="UNAUTHORIZED_MISSING_OWNER"
            )

        category = message.metadata.get("category", "knowledge")
        doc_id = self._memory.store_memory(message.content, category=category, user_id=user_id)
        return AgentResponse(
            success=True,
            content=f"Stored in {category} memory",
            agent=self.name,
            metadata={"doc_id": doc_id},
        )

    def _handle_retrieve(self, message: AgentMessage) -> AgentResponse:
        """Retrieve relevant memories strictly scoped to owner (P0-1, P0-3)."""
        if not self._memory:
            return AgentResponse(success=False, content="No memory system", agent=self.name)

        user_id = message.user_id
        session_id = message.session_id
        is_system = getattr(message, "system_authorized", False)
        if not user_id and not is_system:
            return AgentResponse(
                success=False,
                content="",
                agent=self.name,
                error="UNAUTHORIZED_MISSING_OWNER"
            )

        memories = self._memory.retrieve_memories(
            message.content,
            top_k=message.metadata.get("top_k", 5),
            user_id=user_id,
            allow_system_scope=is_system,
        )
        context = self._memory.build_context_snippet(
            message.content,
            user_id=user_id,
            session_id=session_id,
            allow_system_scope=is_system,
        )
        return AgentResponse(
            success=True,
            content=context,
            agent=self.name,
            metadata={"count": len(memories), "memories": memories},
        )

    def _handle_summarize(self, message: AgentMessage) -> AgentResponse:
        """Create an episodic summary from recent conversation scoped to owner (P0-1, P0-3, P1-3)."""
        if not self._memory:
            return AgentResponse(success=False, content="No memory system", agent=self.name)

        user_id = message.user_id
        session_id = message.session_id
        is_system = getattr(message, "system_authorized", False)
        if not user_id and not is_system:
            return AgentResponse(
                success=False,
                content="Episodic summary requires verified user ownership.",
                agent=self.name,
                error="UNAUTHORIZED_MISSING_OWNER"
            )

        summary = message.content
        if not summary and self._brain_send:
            # Auto-generate summary from recent conversation scoped to owner
            recent = self._memory.conversations.get_context_string(
                n=self.SUMMARIZE_THRESHOLD,
                session_id=session_id,
                user_id=user_id,
                allow_system_scope=is_system,
            )
            if recent:
                prompt = (
                    "Summarize this conversation in 2-3 sentences. "
                    "Focus on key decisions, facts learned, and actions taken:\n\n"
                    f"{recent}"
                )
                try:
                    summary = self._brain_send(prompt)
                except Exception as e:
                    key = (user_id, session_id)
                    turns = self._unsummarized_turns.get(key, self.SUMMARIZE_THRESHOLD)
                    summary = f"Conversation block ({turns} turns)"

        if summary:
            self._memory.create_episode_summary(summary, user_id=user_id, session_id=session_id)
            if user_id:
                self._unsummarized_turns[(user_id, session_id)] = 0
            return AgentResponse(success=True, content=summary, agent=self.name)

        return AgentResponse(success=False, content="Nothing to summarize", agent=self.name)

    def _check_auto_summarize(self, message: AgentMessage) -> AgentResponse:
        """Check if enough unsummarized turns have accumulated for caller (P1-3)."""
        user_id = message.user_id
        session_id = message.session_id
        is_system = getattr(message, "system_authorized", False)

        if not user_id and not is_system:
            return AgentResponse(
                success=False,
                content="Missing verified user identity for auto-summarization.",
                agent=self.name,
                error="UNAUTHORIZED_MISSING_OWNER"
            )

        key = (user_id, session_id)
        self._unsummarized_turns[key] = self._unsummarized_turns.get(key, 0) + 1
        count = self._unsummarized_turns[key]

        if count >= self.SUMMARIZE_THRESHOLD:
            summ_msg = AgentMessage(
                sender=self.name,
                recipient=self.name,
                content="",
                user_id=user_id,
                session_id=session_id,
                system_authorized=is_system,
                metadata={"action": "summarize", "user_id": user_id, "session_id": session_id},
            )
            res = self._handle_summarize(summ_msg)
            if res.success:
                self._unsummarized_turns[key] = 0
            return res

        return AgentResponse(
            success=True,
            content=f"Turns since last summary: {count}",
            agent=self.name,
            metadata={"turns": count, "user_id": user_id, "session_id": session_id},
        )

    def handle_event(self, event: AgentMessage) -> None:
        """Track conversation events for auto-summarization scoped to owner (P1-3)."""
        if event.metadata.get("type") == "conversation_turn":
            u_id = event.user_id
            s_id = event.session_id
            if u_id:
                key = (u_id, s_id)
                self._unsummarized_turns[key] = self._unsummarized_turns.get(key, 0) + 1
