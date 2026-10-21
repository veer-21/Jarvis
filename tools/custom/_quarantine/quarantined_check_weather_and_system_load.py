def check_weather_and_system_load(city: str = "New York") -> dict:
    """
    Checks the current weather for a specified city and the current CPU usage.
    
    Args:
        city (str): The city name for which to fetch weather. Defaults to "New York".
        
    Returns:
        dict: A dictionary containing 'weather' and 'cpu_usage' keys.
    """
    import requests
    import os
    import platform
    import subprocess
    import time

    result = {
        "weather": None,
        "cpu_usage": None,
        "errors": []
    }

    # 1. Fetch Weather
    try:
        # Using Open-Meteo API (no API key required)
        # First, geocode the city
        geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {
            "name": city,
            "count": 1
        }
        geo_response = requests.get(geocode_url, params=params, timeout=10)
        geo_response.raise_for_status()
        geo_data = geo_response.json()
        
        if not geo_data.get("results"):
            raise ValueError(f"City '{city}' not found.")
        
        location = geo_data["results"][0]
        lat = location["latitude"]
        lon = location["longitude"]
        
        # Fetch current weather
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code",
            "timezone": "auto"
        }
        weather_response = requests.get(weather_url, params=weather_params, timeout=10)
        weather_response.raise_for_status()
        weather_data = weather_response.json()
        
        current_weather = weather_data.get("current", {})
        result["weather"] = {
            "city": city,
            "temperature": current_weather.get("temperature_2m"),
            "humidity": current_weather.get("relative_humidity_2m"),
            "feels_like": current_weather.get("apparent_temperature"),
            "condition_code": current_weather.get("weather_code"),
            "time": current_weather.get("time")
        }
    except Exception as e:
        result["errors"].append(f"Weather fetch failed: {str(e)}")

    # 2. Fetch CPU Usage
    try:
        if platform.system() == "Windows":
            # Use typeperf for Windows
            cmd = ["typeperf", "\\Processor(_Total)\\% Processor Time", "-sc", "1"]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10).decode('utf-8')
            lines = output.strip().split('\n')
            if len(lines) >= 2:
                last_line = lines[-1]
                # Parse the last value which is the CPU %
                parts = last_line.split(',')
                if parts:
                    cpu_val = parts[-1].strip()
                    # Handle potential comma in number or empty string
                    if cpu_val.replace(',', '').replace('.', '').isdigit():
                        result["cpu_usage"] = float(cpu_val.replace(',', ''))
                    else:
                        # Fallback: try to find the percentage in the string
                        import re
                        match = re.search(r'([\d.]+)', cpu_val)
                        if match:
                            result["cpu_usage"] = float(match.group(1))
                        else:
                            result["cpu_usage"] = None
                            result["errors"].append(f"Failed to parse CPU usage from typeperf output: {cpu_val}")
    except Exception as e:
        result["errors"].append(f"CPU check failed: {str(e)}")

    return result