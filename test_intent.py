"""Test the IntentClassifier with various inputs."""
import sys
sys.path.insert(0, ".")

from core.brain.intent_classifier import IntentClassifier

ic = IntentClassifier()

tests = [
    # Local commands — should match
    ("open chrome",                   "open_application"),
    ("Open Notepad",                  "open_application"),
    ("open YouTube",                  "open_url"),
    ("open vs code",                  "open_application"),
    ("open calculator",               "open_application"),
    ("take a screenshot",             "take_screenshot"),
    ("what time is it",               "_local_time"),
    ("can you open chrome please",    "open_application"),
    ("hey jarvis open notepad",       "open_application"),
    ("search for python tutorials",   "open_url"),
    ("volume up",                     "press_key"),
    ("open Google",                   "open_url"),
    ("open Gmail",                    "open_url"),
    ("press enter",                   "press_key"),
    ("close chrome",                  "execute_command"),
    ("open the calculator",           "open_application"),
    ("what is the time",              "_local_time"),
    ("what's the date",               "_local_date"),
    ("screenshot",                    "take_screenshot"),
    ("system status",                 "get_system_info"),
    ("open github",                   "open_url"),

    # Complex queries — should NOT match (return None)
    ("hello how are you",             None),
    ("tell me about AI",              None),
    ("what is the meaning of life",   None),
    ("how do I install python",       None),
    ("write a python script",         None),
]

print("=" * 70)
print("IntentClassifier Test Results")
print("=" * 70)

passed = 0
failed = 0

for text, expected_tool in tests:
    result = ic.classify(text)
    actual_tool = result[0] if result else None
    ok = actual_tool == expected_tool
    
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    else:
        passed += 1
    
    print(f"  [{status}] {text:40s} => {actual_tool or 'None':20s} (expected: {expected_tool or 'None'})")

print("=" * 70)
print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")

# Test execute_local
print("\n--- Local built-in tests ---")
r1 = IntentClassifier.execute_local("_local_time", {})
print(f"  Time: {r1}")
r2 = IntentClassifier.execute_local("_local_date", {})
print(f"  Date: {r2}")

if failed > 0:
    sys.exit(1)
