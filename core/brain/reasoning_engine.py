"""
JARVIS Brain — Reasoning Engine
Owns the Gemini LLM client, chat session management, model fallback,
and retry logic with exponential backoff.
"""

import time
import asyncio
from typing import Optional, Iterator, Callable, Any, Dict, List
import os

from core.logger import log, error_log
from core.config import (
    get_api_key, get_model_name, get_groq_api_key, 
    get_openai_api_key, get_ollama_host, get_primary_engine, get_groq_model
)


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

class FauxOpenAIClient:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.chat = self.Chat(self)

    class Chat:
        def __init__(self, outer):
            self.outer = outer
            self.completions = self.Completions(outer)

        class Completions:
            def __init__(self, outer):
                self.outer = outer

            def create(self, model: str, messages: list, temperature: float = 0.4, tools: Optional[list] = None, max_tokens: Optional[int] = None, **kwargs):
                import requests
                import json
                headers = {"Content-Type": "application/json"}
                if self.outer.api_key and self.outer.api_key != "ollama":
                    headers["Authorization"] = f"Bearer {self.outer.api_key}"
                
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if tools:
                    payload["tools"] = tools
                if max_tokens:
                    payload["max_tokens"] = max_tokens

                url = self.outer.base_url.rstrip("/") + "/chat/completions"
                response = requests.post(url, json=payload, headers=headers, timeout=30)
                if response.status_code >= 400:
                    raise RuntimeError(f"Groq API error {response.status_code}: {response.text}")
                data = response.json()

                class FauxResponseChoiceMessage:
                    def __init__(self, msg_dict):
                        self.content = msg_dict.get("content")
                        self.role = msg_dict.get("role", "assistant")
                        t_calls = msg_dict.get("tool_calls")
                        if t_calls:
                            class FauxToolCallFunction:
                                def __init__(self, tc_func):
                                    self.name = tc_func.get("name")
                                    args = tc_func.get("arguments")
                                    self.arguments = json.dumps(args) if isinstance(args, (dict, list)) else str(args or "{}")
                            class FauxToolCall:
                                def __init__(self, tc_dict):
                                    self.id = tc_dict.get("id")
                                    self.type = tc_dict.get("type", "function")
                                    self.function = FauxToolCallFunction(tc_dict.get("function", {}))
                            self.tool_calls = [FauxToolCall(tc) for tc in t_calls]
                        else:
                            self.tool_calls = None

                class FauxResponseChoice:
                    def __init__(self, choice_dict):
                        self.message = FauxResponseChoiceMessage(choice_dict.get("message", {}))

                class FauxResponse:
                    def __init__(self, resp_dict):
                        self.choices = [FauxResponseChoice(c) for c in resp_dict.get("choices", [])]

                return FauxResponse(data)

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

        self._tool_router = None
        self._tools  = []
        self._system_prompt = ""
        self._session_chats: dict[str, Any] = {}
        self._session_histories: dict[str, list[dict]] = {}
        
        self.primary_engine = get_primary_engine()
        self.groq_model = get_groq_model()

        if self.is_offline:
            self._current_provider = "ollama"
        elif self.primary_engine == "groq" and self.groq_key:
            self._current_provider = "groq"
        else:
            self._current_provider = "gemini" if self._client else "fallback"

        log.info(f"ReasoningEngine initialized (Primary: {self._current_provider}, Model: {self._model_name}, Offline: {self.is_offline})")

    def _make_session_key(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
        sid = session_id or "default"
        uid = user_id or "default"
        return f"{uid}:{sid}"

    def set_tool_router(self, tool_router) -> None:
        """Attach the authoritative ToolRouter instance to enforce unified execution."""
        self._tool_router = tool_router

    @property
    def client(self):
        return self._client

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def chat(self):
        return self._session_chats.get("default:default")

    @property
    def _chat(self):
        return self._session_chats.get("default:default")

    @_chat.setter
    def _chat(self, value):
        self._session_chats["default:default"] = value

    @property
    def _conversation_history(self) -> list[dict]:
        return self._session_histories.setdefault("default:default", [])

    @_conversation_history.setter
    def _conversation_history(self, val: list[dict]):
        self._session_histories["default:default"] = val

    # ─── Chat Session ─────────────────────────────────────────────────────────

    def create_chat_session(
        self,
        system_prompt: str,
        tools: list,
        model_name: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        self._system_prompt = system_prompt
        self._tools = tools
        key = self._make_session_key(session_id, user_id)
        self._session_histories[key] = []
        model = model_name or self._model_name

        chat = None
        if self._client:
            try:
                chat = self._client.chats.create(
                    model=model,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.4,
                        tools=tools,
                    ),
                )
                self._current_provider = "gemini"
                log.info(f"Chat session created for [{key}] with model: {model}, {len(tools)} tools")
            except Exception as e:
                error_log.error(f"Failed to create chat session with {model}: {e}")
                self._current_provider = "fallback"

        self._session_chats[key] = chat
        return chat

    def reset_session(
        self,
        system_prompt: str,
        tools: list,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        try:
            key = self._make_session_key(session_id, user_id)
            self.create_chat_session(system_prompt, tools, session_id=session_id, user_id=user_id)
            log.info(f"Chat session reset for [{key}].")
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

    def _execute_fallback_with_tools(self, client, model_name: str, messages: list, session_key: str = "default:default") -> str:
        import json
        openai_tools = [self._callable_to_openai_schema(f) for f in self._tools] if self._tools else None
        
        for _ in range(15): # Max iterations
            kwargs = {"model": model_name, "messages": messages, "temperature": 0.4, "max_tokens": 800}
            if openai_tools:
                kwargs["tools"] = openai_tools
                
            try:
                res = client.chat.completions.create(**kwargs)
            except Exception as e:
                # If Groq validation fails (e.g. hallucinated tool, OTPM, rate limit), retry without tools and smaller max_tokens
                error_str = str(e)
                is_tool_err = "tool_use_failed" in error_str or "invalid_request_error" in error_str or "attempted to call tool" in error_str
                is_rate_limit = "429" in error_str or "rate_limit" in error_str or "tokens" in error_str or "OTPM" in error_str or "Request too large" in error_str
                if (is_tool_err or is_rate_limit) and ("tools" in kwargs or kwargs.get("max_tokens", 800) > 400):
                    log.warning(f"Groq API issue ({error_str[:60]}). Retrying with trimmed parameters...")
                    kwargs.pop("tools", None)
                    kwargs["max_tokens"] = 400
                    time.sleep(2)
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
                    except Exception:
                        args = {}
                        
                    if self._tool_router:
                        tool_res = self._tool_router.execute_tool(name=func_name, args=args, interactive=False)
                        result = tool_res.output if tool_res.success else f"Error: {tool_res.error}"
                    else:
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
                self._session_histories.setdefault(session_key, []).append({"role": "assistant", "content": msg.content or ""})
                return str(msg.content or "")
                
        return "Error: Maximum tool call iterations reached."

    def _clean_last_chat_turn(self, raw_message: str, chat: Optional[Any] = None):
        """Reset the text of the last user message in Gemini history to be the raw (non-RAG) message."""
        target_chat = chat or self._session_chats.get("default:default")
        if not target_chat:
            return
        try:
            for hist in [getattr(target_chat, "_comprehensive_history", []), getattr(target_chat, "_curated_history", [])]:
                for content in reversed(hist):
                    if getattr(content, "role", None) == "user":
                        parts = getattr(content, "parts", [])
                        # Skip tool function response turns
                        if any(getattr(p, "function_response", None) is not None for p in parts):
                            continue
                        for part in parts:
                            if hasattr(part, "text") and part.text is not None and not getattr(part, "function_response", None) and not getattr(part, "inline_data", None):
                                part.text = raw_message
                                break
                            elif isinstance(part, dict) and "text" in part:
                                part["text"] = raw_message
                                break
                        break
        except Exception as e:
            log.warning(f"Failed to clean last chat turn in Gemini history: {e}")

    def _fallback_generate(
        self,
        message: str,
        raw_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        key = self._make_session_key(session_id, user_id)
        history = self._session_histories.setdefault(key, [])
        raw_msg = (raw_message or message)[:1200]
        history.append({"role": "user", "content": raw_msg})
        if len(history) > 6:
            self._session_histories[key] = history[-6:]
            history = self._session_histories[key]
        
        # If model name isn't a known ollama model, default to llama3.2
        ollama_model = self._model_name if self._model_name not in ["gemini-2.0-flash", "gemini-1.5-flash-latest"] else "llama3.2"
        
        # Ensure system prompt and turns don't blow up token limits for fast fallback models
        sys_prompt = self._system_prompt[:2500] if len(self._system_prompt) > 2500 else self._system_prompt
        messages = [{"role": "system", "content": sys_prompt}]
        for turn in history[:-1]:
            content = turn.get("content", "")
            if len(content) > 1200:
                turn_copy = dict(turn)
                turn_copy["content"] = content[:1200] + "..."
                messages.append(turn_copy)
            else:
                messages.append(turn)
        messages.append({"role": "user", "content": message[:2500]})

        def get_client(api_key, base_url=None):
            if HAS_OPENAI:
                return openai.OpenAI(api_key=api_key, base_url=base_url)
            else:
                return FauxOpenAIClient(api_key=api_key, base_url=base_url or "https://api.openai.com/v1")

        # Strict Three-Tier Fallback Chain:
        # Tier 1: Gemini (handled by primary caller, we are in fallback loop now)

        # Tier 2: Groq (High-speed Cloud Fallback)
        if self.groq_key and not self.is_offline:
            try:
                client = get_client(self.groq_key, "https://api.groq.com/openai/v1")
                log.info("Serving via Groq Fallback (Tier 2) with Tools")
                return self._execute_fallback_with_tools(client, self.groq_model, messages, session_key=key)
            except Exception as e:
                log.warning(f"Groq fallback failed: {e}")


        # Tier 2.5: OpenAI (Secondary Cloud Fallback)
        if self.openai_key and not self.is_offline:
            try:
                client = get_client(self.openai_key)
                log.info("Serving via OpenAI Fallback (Tier 2.5) with Tools")
                return self._execute_fallback_with_tools(client, "gpt-4o-mini", messages, session_key=key)
            except Exception as e:
                log.warning(f"OpenAI fallback failed: {e}")

        # Tier 3: Local Ollama (Tertiary local fallback)
        # Attempt local Ollama if offline, or if all cloud routes failed/are unconfigured.
        if self.ollama_host:
            try:
                client = get_client("ollama", f"{self.ollama_host}/v1")
                log.info("Serving via Ollama Fallback (Tier 3) with Tools")
                return self._execute_fallback_with_tools(client, ollama_model, messages, session_key=key)
            except Exception as e:
                log.warning(f"Ollama fallback failed: {e}")
                if self.is_offline:
                    return f"Offline Engine Error: Make sure Ollama is running and the model '{ollama_model}' is pulled! Error: {e}"

        return "Sir, we have exhausted all fallback routes (Gemini & Groq) and local Ollama is offline or unconfigured."

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Direct text completion without conversational history or function tools.
        Used for planning, DAG generation, structured extraction, and summarization.
        """
        if self._current_provider == "gemini" and self._client:
            try:
                config = None
                if system_prompt:
                    config = types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.2)
                res = self._client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=config
                )
                if res and res.text:
                    return res.text
            except Exception as e:
                log.warning(f"Gemini generate_text failed: {e}. Falling back to text completion...")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Try Groq text completion without tools
        if self.groq_key and not self.is_offline:
            try:
                client = FauxOpenAIClient(api_key=self.groq_key, base_url="https://api.groq.com/openai/v1") if not HAS_OPENAI else openai.OpenAI(api_key=self.groq_key, base_url="https://api.groq.com/openai/v1")
                res = client.chat.completions.create(model=self.groq_model, messages=messages, temperature=0.2)
                if res and res.choices and res.choices[0].message:
                    return str(res.choices[0].message.content or "")
            except Exception as e:
                log.warning(f"Groq generate_text failed: {e}")

        # Fallback to general fallback
        return self._fallback_generate(prompt)

    # ─── Send with Retry ──────────────────────────────────────────────────────

    def send_message(
        self,
        message: str,
        raw_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        raw_msg = raw_message or message
        key = self._make_session_key(session_id, user_id)
        chat = self._session_chats.get(key)
        if chat is None and self._client:
            chat = self.create_chat_session(self._system_prompt, self._tools, session_id=session_id, user_id=user_id)

        history = self._session_histories.setdefault(key, [])

        if self._current_provider == "gemini" and chat:
            delay = self.BACKOFF_BASE
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = chat.send_message(message)
                    self._clean_last_chat_turn(raw_msg, chat=chat)
                    history.append({"role": "user", "content": raw_msg})
                    history.append({"role": "assistant", "content": response.text})
                    return response.text or "[JARVIS returned an empty response]"
                except Exception as e:
                    error_msg = str(e)
                    is_rate_limit = any(kw in error_msg for kw in ("429", "RESOURCE_EXHAUSTED", "Quota exceeded", "rate limit"))
                    is_service_error = any(kw in error_msg for kw in ("503", "UNAVAILABLE", "high demand", "Server Error", "400", "INVALID_ARGUMENT", "deadline"))

                    if "GenerateRequestsPerDay" in error_msg or (is_rate_limit and attempt >= self.MAX_RETRIES - 1) or is_service_error:
                        log.warning(f"Gemini API unavailable/error ({error_msg[:80]}). Switching to fallback provider.")
                        self._current_provider = "fallback"
                        return self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)

                    if is_rate_limit:
                        log.warning(f"Rate limit hit (attempt {attempt+1}/{self.MAX_RETRIES}). Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                        delay *= self.BACKOFF_BASE
                        continue

                    error_log.error(f"ReasoningEngine error: {error_msg}. Switching to fallback.")
                    self._current_provider = "fallback"
                    return self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)
        else:
            return self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)

    # ─── Streaming ────────────────────────────────────────────────────────────

    def stream_message(
        self,
        message: str,
        system_prompt: str,
        raw_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Iterator[str]:
        raw_msg = raw_message or message
        key = self._make_session_key(session_id, user_id)
        chat = self._session_chats.get(key)
        if chat is None and self._client:
            chat = self.create_chat_session(system_prompt, self._tools, session_id=session_id, user_id=user_id)

        history = self._session_histories.setdefault(key, [])

        if self._current_provider in ("fallback", "ollama") or not self._client:
            yield self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)
            return

        delay = self.BACKOFF_BASE
        for attempt in range(self.MAX_RETRIES):
            try:
                full_response = ""
                if chat:
                    response = chat.send_message_stream(message)
                    for chunk in response:
                        if chunk.text:
                            full_response += chunk.text
                            yield chunk.text
                    self._clean_last_chat_turn(raw_msg, chat=chat)
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
                
                history.append({"role": "user", "content": raw_msg})
                history.append({"role": "assistant", "content": full_response})
                return
            except Exception as e:
                error_msg = str(e)
                is_rate_limit = any(kw in error_msg for kw in ("429", "RESOURCE_EXHAUSTED", "Quota exceeded", "rate limit"))
                
                if "GenerateRequestsPerDay" in error_msg or (is_rate_limit and attempt >= self.MAX_RETRIES - 1):
                    log.warning("Gemini daily limit or sustained rate limit hit during streaming. Switching to fallback provider.")
                    self._current_provider = "fallback"
                    yield self._fallback_generate(message, raw_message=raw_msg, session_id=session_id, user_id=user_id)
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
