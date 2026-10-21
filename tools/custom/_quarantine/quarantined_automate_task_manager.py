def automate_task_manager():
    """
    Automates the task of checking the weather and system load, 
    then writes and saves a Python file for the task manager on the desktop.
    
    Returns:
        str: A message indicating the completion of the task.
    """
    import os
    import psutil
    import requests
    import subprocess

    # Check weather in New York
    weather_response = requests.get('http://wttr.in/New+York?format=3')
    weather = weather_response.text

    # Get current CPU usage
    cpu_usage = psutil.cpu_percent()

    # Create a folder on the desktop for the task manager
    desktop_path = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
    task_manager_folder = os.path.join(desktop_path, 'task_manager')
    if not os.path.exists(task_manager_folder):
        os.makedirs(task_manager_folder)

    # Write task manager code to a file
    task_manager_code = f"""
import psutil
import requests

def check_weather():
    weather_response = requests.get('http://wttr.in/New+York?format=3')
    return weather_response.text

def check_system_load():
    return psutil.cpu_percent()

print("Weather:", check_weather())
print("System Load:", check_system_load())
"""
    with open(os.path.join(task_manager_folder, 'task.py'), 'w') as file:
        file.write(task_manager_code)

    # Close the text editor
    subprocess.run(['taskkill', '/im', 'notepad.exe'])

    return "Task manager automation complete."