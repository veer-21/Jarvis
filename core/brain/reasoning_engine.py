"""
JARVIS Brain — Reasoning Engine
Owns the Gemini LLM client, chat session management, model fallback,
and retry logic with exponential backoff.
"""

import time
import asyncio
from typing import Optional, Iterator, Callable
import os

from core.logger import log, error_log
from core.config import get_api_key, get_model_name, get_groq_api_key, get_openai_api_key, get_ollama_host

# ─── Gemini SDK ───────────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    log.warning("google-genai not installed. Run: pip install google-genai")

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    log.warning("openai SDK not installed. Fallback providers will be disabled.")

class ReasoningEngine:
    """
    Manages the Gemini LLM client, chat sessions, and all direct LLM calls.
    Provides retry with exponential backoff and seamless multi-provider fallback.
    """

    MAX_RETRIES  = 3
    BACKOFF_BASE = 2.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self._api_key    = api_key or get_api_key()
        self._model_name = model_name or get_model_name()
        
        self.groq_key = get_groq_api_key()
        self.openai_key = get_openai_api_key()
        self.ollama_host = get_ollama_host()

        self.is_offline = os.getenv("JARVIS_OFFLINE") == "1"

        if HAS_GEMINI and self._api_key and not self.is_offline:
            self._client = genai.Client(api_key=self._api_key)
        else:
            self._client = None

        self._chat   = None
        self._tools  = []
        self._system_prompt = ""
        self._conversation_history = []
        
        if self.is_offline:
            self._current_provider = "ollama"
        else:
            self._current_provider = "gemini" if self._client else "fallback"

        log.info(f"ReasoningEngine initialized with model: {self._model_name} (Offline: {self.is_offline})")

    @property
    def client(self):
        return self._client

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def chat(self):
        return self._chat

    # ─── Chat Session ─────────────────────────────────────────────────────────

    def create_chat_session(self, system_prompt: str, tools: list, model_name: Optional[str] = None):
        self._system_prompt = system_prompt
        self._tools = tools
        self._conversation_history = []
        model = model_name or self._model_name

        if self._client:
            try:
                self._chat = self._client.chats.create(
                    model=model,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.4,
                        tools=tools,
                    ),
                )
                self._current_provider = "gemini"
                log.info(f"Chat session created with model: {model}, {len(tools)} tools")
            except Exception as e:
                error_log.error(f"Failed to create chat session with {model}: {e}")
                self._current_provider = "fallback"
        return self._chat

    def reset_session(self, system_prompt: str, tools: list) -> str:
        try:
            self.create_chat_session(system_prompt, tools)
            log.info("Chat session reset.")
            return "Chat session reset. Previous conversation context cleared."
        except Exception as e:
            return f"Failed to reset chat: {str(e)}"

    def switch_model(self, model_name: str, system_prompt: str, tools: list) -> str:
        try:
            self.create_chat_session(system_prompt, tools, model_name=model_name)
            self._model_name = model_name
            log.info(f"Model switched to: {model_name}")
            return f"Model switched to {model_name}. Chat session reset."
        except Exception as e:
            return f"Failed to switch model: {str(e)}"

    # ─── Fallback Logic ───────────────────────────────────────────────────────

    def _callable_to_openai_schema(self, func: Callable) -> dict:
        import inspect
        sig = inspect.signature(func)
        parameters = {
            "type": "object",
            "properties": {},
            "required": []
        }
        for name, param in sig.parameters.items():
            if name in ("self", "cls"): continue
            ptype = "string"
            if param.annotation == int: ptype = "integer"
            elif param.annotation == bool: ptype = "boolean"
            elif param.annotation == float: ptype = "number"
            elif param.annotation == list: ptype = "array"
            elif param.annotation == dict: ptype = "object"
            parameters["properties"][name] = {"type": ptype, "description": f"Parameter {name}"}
            if param.default == inspect.Parameter.empty:
                parameters["required"].append(name)
                
        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": (func.__doc__ or "").strip().split("\n")[0] if func.__doc__ else "No description",
                "parameters": parameters
            }
        }

    def _execute_fallback_with_tools(self, client, model_name: str, messages: list) -> str:
        import json
        openai_tools = [self._callable_to_openai_schema(f) for f in self._tools] if self._tools else None
        
        for _ in range(15): # Max iterations
            kwargs = {"model": model_name, "messages": messages, "temperature": 0.4}
            if openai_tools:
                kwargs["tools"] = openai_tools
                
            try:
                res = client.chat.completions.create(**kwargs)
            except Exception as e:
                # If Groq validation fails (e.g. hallucinated tool), retry without tools
                error_str = str(e)
                if "tool_use_failed" in error_str or "invalid_request_error" in error_str or "attempted to call tool" in error_str:
                    log.warning("Groq tool validation failed. Retrying without tools.")
                    kwargs.pop("tools", None)
                    try:
                        res = client.chat.completions.create(**kwargs)
                    except Exception as e2:
                        return f"Error: Fallback API call failed after tool strip: {e2}"
                else:
                    return f"Error: Fallback API call failed: {e}"
                
            msg = res.choices[0].message
            
            # ─── Fix for Ollama raw JSON tool calls ───
            if not getattr(msg, "tool_calls", None) and msg.content:
                # Sometimes models output: {"name": "...", "parameters": {...}}; {"name": ...}
                import re
                content_str = msg.content.strip()
                # Check if it looks like our raw json tool calls
                if content_str.startswith('{"name":') and '"parameters":' in content_str:
                    # Try to parse it
                    faux_tool_calls = []
                    parts = content_str.split(';')
                    for i, part in enumerate(parts):
                        part = part.strip()
                        if not part: continue
                        try:
                            parsed = json.loads(part)
                            if "name" in parsed and "parameters" in parsed:
                                class FauxFunction:
                                    def __init__(self, name, arguments):
                                        self.name = name
                                        self.arguments = arguments
                                class FauxToolCall:
                                    def __init__(self, id, function):
                                        self.id = id
                                        self.function = function
                                
                                faux_tool_calls.append(FauxToolCall(
                                    id=f"call_{i}",
                                    function=FauxFunction(parsed["name"], json.dumps(parsed["parameters"]))
                                ))
                        except Exception:
                            pass
                    
                    if faux_tool_calls:
                        msg.tool_calls = faux_tool_calls
                        msg.content = ""
            # ──────────────────────────────────────────

            if hasattr(msg, "tool_calls") and msg.tool_calls:
                # Add assistant message with tool calls
                assistant_msg = {"role": "assistant", "content": msg.content or "", "tool_calls": []}
                for tc in msg.tool_calls:
                    assistant_msg["tool_calls"].append({
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })
                messages.append(assistant_msg)
                
                # Execute tools
                for tc in msg.tool_calls:
                    func_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except:
                        args = {}
                        
                    target_func = next((f for f in self._tools if f.__name__ == func_name), None)
                    if target_func:
                        try:
                            result = target_func(**args)
                        except Exception as e:
                            result = f"Error: {e}"
                    else:
                        result = f"Error: Tool '{func_name}' not found."
                        
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": func_name,
                        "content": str(result)[:2000]
                    })
            else:
                self._conversation_history.append({"role": "assistant", "content": msg.content or ""})
                return str(msg.content or "")
                
        return "Error: Maximum tool call iterations reached."

    def _clean_last_chat_turn(self, raw_message: str):
        """Reset the text of the last user message in Gemini history to be the raw (non-RAG) message."""
        if not self._chat:
            return
        try:
            # Clean comprehensive history
            h_comp = self._chat._comprehensive_history
            for content in reversed(h_comp):
                if content.role == "user":
                    if content.parts:
                        part = content.parts[0]
                        if hasattr(part, "text"):
                            part.text = raw_message
                        elif isinstance(part, dict) and "text" in part:
                            part["text"] = raw_message
                    break
                    
            # Clean curated history
            h_cur = self._chat._curated_history
            for content in reversed(h_cur):
                if content.role == "user":
                    if content.parts:
                        part = content.parts[0]
                        if hasattr(part, "text"):
                            part.text = raw_message
                        elif isinstance(part, dict) and "text" in part:
                            part["text"] = raw_message
                    break
        except Exception as e:
            log.warning(f"Failed to clean last chat turn in Gemini history: {e}")

    def _fallback_generate(self, message: str, raw_message: Optional[str] = None) -> str:
        raw_msg = raw_message or message
        self._conversation_history.append({"role": "user", "content": raw_msg})
        
        # We make a copy of history for the API call so tool loops don't pollute the main history array
        # Inject the enriched message ONLY for the very last user turn to keep history raw
        messages = [{"role": "system", "content": self._system_prompt}]
        for turn in self._conversation_history[:-1]:
            messages.append(turn)
        messages.append({"role": "user", "content": message})

        # Try Local Ollama (Llama3.2/Qwen) - Prioritize this if offline
        if self.ollama_host and (self.is_offline or not HAS_OPENAI or self._current_provider == "ollama"):
            try:
                # Use standard OpenAI client pointed at Ollama
                client = openai.OpenAI(api_key="ollama", base_url=f"{self.ollama_host}/v1")
                log.info("Serving via Ollama with Tools")
                
                # If model name isn't a known ollama model, default to llama3.2
                ollama_model = self._model_name if self._model_name not in ["gemini-2.0-flash", "gemini-1.5-flash-latest"] else "llama3.2"
                return self._execute_fallback_with_tools(client, ollama_model, messages)
            except Exception as e:
                log.warning(f"Ollama fallback failed: {e}")
                if self.is_offline:
                    return f"Offline Engine Error: Make sure Ollama is running and the model '{ollama_model}' is pulled! Error: {e}"

        if not HAS_OPENAI and not self.is_offline:
            return "Sir, we have exhausted today's API quota and no fallback providers are configured. Install 'openai' package to enable Groq/OpenAI/Ollama fallbacks."

        # 1. Try Groq (Llama 3.3)
        if self.groq_key and not self.is_offline:
            try:
                client = openai.OpenAI(api_key=self.groq_key, base_url="https://api.groq.com/openai/v1")
                log.info("Serving via Groq Fallback with Tools")
                return self._execute_fallback_with_tools(client, "llama-3.3-70b-versatile", messages)
            except Exception as e:
                log.warning(f"Groq fallback failed: {e}")

        # 2. Try OpenAI (GPT-4o-mini)
        if self.openai_key and not self.is_offline:
            try:
                client = openai.OpenAI(api_key=self.openai_key)
                log.info("Serving via OpenAI Fallback with Tools")
                return self._execute_fallback_with_tools(client, "gpt-4o-mini", messages)
            except Exception as e:
                log.warning(f"OpenAI fallback failed: {e}")
                
        return "Sir, we have exhausted today's API quota. Systems will resume when the quota resets tomorrow."

    # ─── Send with Retry ──────────────────────────────────────────────────────

    def send_message(self, message: str, raw_message: Optional[str] = None) -> str:
        raw_msg = raw_message or message
        if self._current_provider == "gemini" and self._chat:
            delay = self.BACKOFF_BASE
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = self._chat.send_message(message)
                    self._clean_last_chat_turn(raw_msg)
                    self._conversation_history.append({"role": "user", "content": raw_msg})
                    self._conversation_history.append({"role": "assistant", "content": response.text})
                    return response.text or "[JARVIS returned an empty response]"
                except Exception as e:
                    error_msg = str(e)
                    is_rate_limit = any(kw in error_msg for kw in ("429", "RESOURCE_EXHAUSTED", "Quota exceeded", "rate limit"))
                    
                    if "GenerateRequestsPerDay" in error_msg or (is_rate_limit and attempt >= self.MAX_RETRIES - 1):
                        log.warning("Gemini daily limit or sustained rate limit hit. Switching to fallback provider.")
                        self._current_provider = "fallback"
                        return self._fallback_generate(message, raw_message=raw_msg)

                    if is_rate_limit:
                        log.warning(f"Rate limit hit (attempt {attempt+1}/{self.MAX_RETRIES}). Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                        delay *= self.BACKOFF_BASE
                        continue

                    error_log.error(f"ReasoningEngine error: {error_msg}")
                    return f"Brain Error: {error_msg}"
        else:
            return self._fallback_generate(message, raw_message=raw_msg)

    # ─── Streaming ────────────────────────────────────────────────────────────

    def stream_message(self, message: str, system_prompt: str, raw_message: Optional[str] = None) -> Iterator[str]:
        raw_msg = raw_message or message
        if self._current_provider in ("fallback", "ollama") or not self._client:
            yield self._fallback_generate(message, raw_message=raw_msg)
            return

        delay = self.BACKOFF_BASE
        for attempt in range(self.MAX_RETRIES):
            try:
                full_response = ""
                if self._chat:
                    response = self._chat.send_message_stream(message)
                    for chunk in response:
                        if chunk.text:
                            full_response += chunk.text
                            yield chunk.text
                    self._clean_last_chat_turn(raw_msg)
                else:
                    response = self._client.models.generate_content_stream(
                        model=self._model_name,
                        contents=message,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.4,
                        ),
                    )
                    for chunk in response:
                        if chunk.text:
                            full_response += chunk.text
                            yield chunk.text
                
                self._conversation_history.append({"role": "user", "content": raw_msg})
                self._conversation_history.append({"role": "assistant", "content": full_response})
                return
            except Exception as e:
                error_msg = str(e)
                is_rate_limit = any(kw in error_msg for kw in ("429", "RESOURCE_EXHAUSTED", "Quota exceeded", "rate limit"))
                
                if "GenerateRequestsPerDay" in error_msg or (is_rate_limit and attempt >= self.MAX_RETRIES - 1):
                    log.warning("Gemini daily limit or sustained rate limit hit during streaming. Switching to fallback provider.")
                    self._current_provider = "fallback"
                    yield self._fallback_generate(message, raw_message=raw_msg)
                    return

                if is_rate_limit:
                    time.sleep(delay)
                    delay *= self.BACKOFF_BASE
                    continue

                error_log.error(f"Streaming error: {error_msg}")
                yield f"\n[Stream Error: {error_msg}]"
                return

    # ─── Introspection ────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "model": self._model_name,
            "provider": self._current_provider,
            "tools_count": len(self._tools),
            "has_session": self._chat is not None,
        }
