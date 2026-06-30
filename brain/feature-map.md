# Project Brain — Feature Map

This document maps system capabilities to their respective files and lines.

---

## 1. Feature: Zero-Latency Local Execution
* **Core Logic**:fuzzy regex match and command execution.
* **Files**:
  * [intent_classifier.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/brain/intent_classifier.py)
  * [brain.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/brain/brain.py#L200-L233)

---

## 2. Feature: System Gating and Risk Audits
* **Core Logic**:Command checking and logging.
* **Files**:
  * [security.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/security.py)
  * [security_agent.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/agents/security_agent.py)

---

## 3. Feature: Custom Tool Generation (Refiner)
* **Core Logic**:Repetitive logs scan and custom python script generation.
* **Files**:
  * [refiner_agent.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/agents/refiner_agent.py)
  * [tool_router.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/brain/tool_router.py#L139-L171)

---

## 4. Feature: Voice Continuous Loop
* **Core Logic**:Wake-word detection and asynchronous STT/TTS channels.
* **Files**:
  * [voice_manager.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/voice_manager.py)
  * [voice.py](file:///d:/Home/H.W.%20OR%20Self/Jarvis/core/voice.py)
