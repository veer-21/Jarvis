"""
JARVIS Import Validation Script
Run: python test_imports.py
Checks that all modules import cleanly without errors.
"""

import sys
import os
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

results = []

def check(label, fn):
    try:
        fn()
        results.append(("PASS", label))
    except Exception as e:
        results.append(("FAIL", label, str(e)))

# Core modules
check("dotenv",            lambda: __import__("dotenv"))
check("core.logger",       lambda: __import__("core.logger",    fromlist=["log"]))
check("core.config",       lambda: __import__("core.config",    fromlist=["get_api_key"]))
check("core.prompts.core_prompt",lambda: __import__("core.prompts.core_prompt", fromlist=["CORE_PROMPT"]))
check("core.security",     lambda: __import__("core.security",  fromlist=["guard"]))
check("core.memory",       lambda: __import__("core.memory",    fromlist=["JarvisMemory"]))
check("core.planner",      lambda: __import__("core.planner",   fromlist=["JarvisPlanner"]))

# Tools
check("tools.system_tools",    lambda: __import__("tools.system_tools",    fromlist=["execute_command"]))
check("tools.file_tools",      lambda: __import__("tools.file_tools",      fromlist=["read_file"]))
check("tools.web_tools",       lambda: __import__("tools.web_tools",       fromlist=["web_search"]))
check("tools.automation_tools",lambda: __import__("tools.automation_tools",fromlist=["open_application"]))
check("tools.browser_tools",   lambda: __import__("tools.browser_tools",   fromlist=["open_url"]))

# API
check("api.models",   lambda: __import__("api.models",   fromlist=["ChatRequest"]))
check("api.auth",     lambda: __import__("api.auth",     fromlist=["create_access_token"]))
check("api.server",   lambda: __import__("api.server",   fromlist=["app"]))

# Optional heavy deps (warn but don't fail)
check("google.genai", lambda: __import__("google.genai"))
check("fastapi",      lambda: __import__("fastapi"))
check("pydantic",     lambda: __import__("pydantic"))
check("cryptography", lambda: __import__("cryptography"))
check("requests",     lambda: __import__("requests"))

# Print results
print("\n" + "="*55)
print("  JARVIS Import Validation Report")
print("="*55)
passes = fails = 0
for r in results:
    status = r[0]
    label  = r[1]
    error  = r[2] if len(r) > 2 else ""
    icon   = "✅" if status == "PASS" else "❌"
    print(f"  {icon} {label:<35} {error[:60] if error else ''}")
    if status == "PASS": passes += 1
    else: fails += 1

print("="*55)
print(f"  {passes} passed  |  {fails} failed")
print("="*55)
sys.exit(0 if fails == 0 else 1)
