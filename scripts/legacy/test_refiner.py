import os
from dotenv import load_dotenv

# Ensure we use Gemini for the Refiner agent to write the Python code
# Llama 3.2 is too small to write complex tool code reliably
os.environ["JARVIS_OFFLINE"] = "0"

load_dotenv()

from core.memory import JarvisMemory
from core.brain.brain import Brain
from core.agents.base_agent import AgentMessage

print("Initializing JARVIS Memory...")
memory = JarvisMemory()

print("Initializing JARVIS Brain & Refiner Agent...")
# Initialize the brain with memory
brain = Brain(memory=memory)

print("\nInjecting repetitive task patterns into memory...")
# We add a repetitive fake task that the user "ran" multiple times
fake_task = "Task executed: Checked the current weather in New York and fetched the current CPU usage."

for _ in range(3):
    brain.memory_manager.store_task_result(
        task="Check weather and system load", 
        result=fake_task
    )

print("Memory injected!\n")

print("\nTriggering the Refiner Agent to optimize workflows...")
print("The Agent is now reading memory and writing custom Python code. Please wait...")

# Strip tools so the fallback model doesn't try to call them, forcing it to write raw code.
brain.reasoning._tools = []

# Create the message to trigger the Refiner Agent
msg = AgentMessage(sender="user", recipient="refiner", content="optimize")
result = brain._refiner.process(msg)

print("\n" + "="*50)
if result.success:
    print(f"✅ SUCCESS: {result.content}")
    print("\nCheck the 'tools/custom' directory to see the new tool JARVIS just wrote for himself!")
else:
    print(f"❌ FAILED: {result.content}")
print("="*50)
