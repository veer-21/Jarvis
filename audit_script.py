import os
import re
import subprocess

TARGET_DIRS = ["core", "tools", "api", "ui"]
SEARCH_PATTERNS = ["TODO", "FIXME", "pass", "NotImplementedError", "mock", "stub", "dummy", "time.sleep"]

def search_files():
    matches = []
    base_dir = r"d:\Home\H.W. OR Self\Jarvis"
    for d in TARGET_DIRS:
        target_path = os.path.join(base_dir, d)
        if not os.path.exists(target_path): continue
        for root, _, files in os.walk(target_path):
            for file in files:
                if not file.endswith(".py"): continue
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        for pattern in SEARCH_PATTERNS:
                            if re.search(r'\b' + pattern + r'\b', line):
                                matches.append(f"{os.path.relpath(path, base_dir)}:{i+1}: {line.strip()}")
                                break
    return matches

with open(r"d:\Home\H.W. OR Self\Jarvis\audit_output.txt", "w", encoding="utf-8") as out:
    out.write("--- STUBS AND MOCKS ---\n")
    for m in search_files():
        out.write(m + "\n")

    out.write("\n--- PYTEST -v ---\n")
    try:
        res = subprocess.run([r"d:\Home\H.W. OR Self\Jarvis\venv\Scripts\python.exe", "-m", "pytest", "test_goal_executor.py", "-v"], cwd=r"d:\Home\H.W. OR Self\Jarvis", capture_output=True, text=True)
        out.write(res.stdout + "\n")
        out.write(res.stderr + "\n")
    except Exception as e:
        out.write(f"Error running pytest: {e}\n")

    out.write("\n--- PYTEST -q ---\n")
    try:
        res = subprocess.run([r"d:\Home\H.W. OR Self\Jarvis\venv\Scripts\python.exe", "-m", "pytest", "-q"], cwd=r"d:\Home\H.W. OR Self\Jarvis", capture_output=True, text=True)
        out.write(res.stdout + "\n")
        out.write(res.stderr + "\n")
    except Exception as e:
        out.write(f"Error running pytest: {e}\n")

    out.write("\n--- COVERAGE ---\n")
    try:
        res = subprocess.run([r"d:\Home\H.W. OR Self\Jarvis\venv\Scripts\python.exe", "-m", "pytest", "--cov=core/brain/goal_executor.py", "--cov=core/agents/operator_agent.py"], cwd=r"d:\Home\H.W. OR Self\Jarvis", capture_output=True, text=True)
        out.write(res.stdout + "\n")
        out.write(res.stderr + "\n")
    except Exception as e:
        out.write("pytest-cov might not be installed.\n")
