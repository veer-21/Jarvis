"""
JARVIS Tools Package
Auto-discovery registry for all tool modules.
"""

from core.logger import log


def get_tool_registry() -> dict:
    """
    Auto-discover and return all available tool functions.

    Returns:
        Dict mapping tool names to their callables.
    """
    registry = {}

    # Import all tool modules
    try:
        from tools import system_tools
        registry["execute_command"]      = system_tools.execute_command
        registry["schedule_task"]        = system_tools.schedule_task
        registry["list_scheduled_tasks"] = system_tools.list_scheduled_tasks
    except ImportError as e:
        log.warning(f"system_tools unavailable: {e}")

    try:
        from tools import file_tools
        registry["read_file"]        = file_tools.read_file
        registry["write_file"]       = file_tools.write_file
        registry["list_directory"]   = file_tools.list_directory
        registry["safe_delete_file"] = file_tools.safe_delete_file
        registry["get_file_info"]    = file_tools.get_file_info
        registry["search_in_files"]  = file_tools.search_in_files
        registry["graphify_query"]   = file_tools.graphify_query
    except ImportError as e:

        log.warning(f"file_tools unavailable: {e}")

    try:
        from tools import web_tools
        registry["web_search"]    = web_tools.web_search
        registry["fetch_webpage"] = web_tools.fetch_webpage
        registry["get_weather"]   = web_tools.get_weather
        registry["search_news"]   = web_tools.search_news
    except ImportError as e:
        log.warning(f"web_tools unavailable: {e}")

    try:
        from tools import automation_tools
        registry["open_application"]  = automation_tools.open_application
        registry["take_screenshot"]   = automation_tools.take_screenshot
        registry["analyze_screen"]    = automation_tools.analyze_screen
        registry["get_system_info"]   = automation_tools.get_system_info
        registry["press_key"]         = automation_tools.press_key
        registry["type_text"]         = automation_tools.type_text
        registry["click_mouse"]       = automation_tools.click_mouse
        registry["move_mouse"]        = automation_tools.move_mouse
        registry["scroll_mouse"]      = automation_tools.scroll_mouse
        registry["list_open_windows"] = automation_tools.list_open_windows
        registry["focus_window"]      = automation_tools.focus_window
    except ImportError as e:
        log.warning(f"automation_tools unavailable: {e}")

    try:
        from tools import browser_tools
        registry["open_url"]            = browser_tools.open_url
        registry["get_page_text"]       = browser_tools.get_page_text
        registry["browser_screenshot"]  = browser_tools.browser_screenshot
        registry["browser_click"]       = browser_tools.browser_click
        registry["browser_fill"]        = browser_tools.browser_fill
    except ImportError as e:
        log.warning(f"browser_tools unavailable: {e}")

    try:
        from tools import everyday_tools
        registry["smart_organize_folder"]            = everyday_tools.smart_organize_folder
        registry["undo_folder_organization"]         = everyday_tools.undo_folder_organization
        registry["create_reminder_or_timer"]         = everyday_tools.create_reminder_or_timer
        registry["list_and_manage_reminders"]        = everyday_tools.list_and_manage_reminders
        registry["control_windows_setting"]          = everyday_tools.control_windows_setting
        registry["summarize_local_document"]         = everyday_tools.summarize_local_document
        registry["generate_daily_briefing"]          = everyday_tools.generate_daily_briefing
        registry["manage_personal_notes_and_todos"] = everyday_tools.manage_personal_notes_and_todos
        registry["smart_clipboard_assistant"]        = everyday_tools.smart_clipboard_assistant
        registry["read_and_summarize_webpage"]       = everyday_tools.read_and_summarize_webpage
        registry["compose_and_launch_message"]       = everyday_tools.compose_and_launch_message
    except ImportError as e:
        log.warning(f"everyday_tools unavailable: {e}")

    try:
        from tools import context_tools
        registry["get_active_window_context"] = context_tools.get_active_window_context
    except ImportError as e:
        log.warning(f"context_tools unavailable: {e}")

    # ── Phase 1: Windows UI Automation (UIA) Tools ──
    try:
        from tools import uia_tools
        registry["uia_list_windows"]   = uia_tools.uia_list_windows
        registry["uia_inspect_window"] = uia_tools.uia_inspect_window
        registry["uia_click_element"]  = uia_tools.uia_click_element
        registry["uia_set_text"]       = uia_tools.uia_set_text
        registry["uia_get_text"]       = uia_tools.uia_get_text
    except ImportError as e:
        log.warning(f"uia_tools unavailable: {e}")

    # ── Phase 1: Native COM Automation Tools ──
    try:
        from tools import com_tools
        registry["com_get_running_apps"] = com_tools.com_get_running_apps
        registry["com_excel_read"]       = com_tools.com_excel_read
        registry["com_excel_write"]      = com_tools.com_excel_write
        registry["com_word_create"]      = com_tools.com_word_create
    except ImportError as e:
        log.warning(f"com_tools unavailable: {e}")

    # ── Phase 2: Sandboxed Streaming Code REPL Tools ──
    try:
        from tools import repl_tools
        registry["repl_execute_python"]     = repl_tools.repl_execute_python
        registry["repl_execute_powershell"] = repl_tools.repl_execute_powershell
        registry["repl_reset_session"]      = repl_tools.repl_reset_session
    except ImportError as e:
        log.warning(f"repl_tools unavailable: {e}")

    # ── Phase 3: Hardware Sentinel & Ambient Proactive Tools ──
    try:
        from core import sentinel
        registry["sentinel_get_hardware_status"] = sentinel.sentinel_get_hardware_status
        registry["sentinel_run_ambient_scan"]    = sentinel.sentinel_run_ambient_scan
        registry["sentinel_set_power_profile"]   = sentinel.sentinel_set_power_profile
    except ImportError as e:
        log.warning(f"sentinel unavailable: {e}")

    # ── Phase 4: The Ghost Operator Tools ──
    try:
        from tools import ghost_operator
        registry["ghost_list_targetable_windows"] = ghost_operator.ghost_list_targetable_windows
        registry["ghost_click_window"]            = ghost_operator.ghost_click_window
        registry["ghost_send_text"]               = ghost_operator.ghost_send_text
    except ImportError as e:
        log.warning(f"ghost_operator unavailable: {e}")

    # ── Phase 4: Refiner 2.0 Autonomous Evolution Tools ──
    try:
        from core.agents import refiner_agent
        registry["refiner_synthesize_custom_tool"] = refiner_agent.refiner_synthesize_custom_tool
    except ImportError as e:
        log.warning(f"refiner_agent unavailable: {e}")

    log.info(f"Tool registry: {len(registry)} tools discovered")
    return registry


def get_tool_categories() -> dict[str, list[str]]:
    """
    Return tool names organized by category.

    Returns:
        Dict mapping category names to lists of tool names.
    """
    return {
        "system":     ["execute_command", "schedule_task", "list_scheduled_tasks"],
        "file":       ["read_file", "write_file", "list_directory", "safe_delete_file",
                        "get_file_info", "search_in_files"],
        "web":        ["web_search", "fetch_webpage", "get_weather", "search_news"],
        "automation": ["open_application", "take_screenshot", "analyze_screen", "get_system_info",
                        "press_key", "type_text", "click_mouse", "move_mouse", "scroll_mouse",
                        "list_open_windows", "focus_window", "get_active_window_context"],
        "browser":    ["open_url", "get_page_text", "browser_screenshot",
                        "browser_click", "browser_fill"],
        "everyday":   ["smart_organize_folder", "undo_folder_organization", "create_reminder_or_timer",
                        "list_and_manage_reminders", "control_windows_setting", "summarize_local_document",
                        "generate_daily_briefing", "get_active_window_context",
                        "manage_personal_notes_and_todos", "smart_clipboard_assistant",
                        "read_and_summarize_webpage", "compose_and_launch_message"],
        "uia":        ["uia_list_windows", "uia_inspect_window", "uia_click_element",
                        "uia_set_text", "uia_get_text"],
        "com":        ["com_get_running_apps", "com_excel_read", "com_excel_write",
                        "com_word_create"],
        "repl":       ["repl_execute_python", "repl_execute_powershell", "repl_reset_session"],
        "sentinel":   ["sentinel_get_hardware_status", "sentinel_run_ambient_scan", "sentinel_set_power_profile"],
        "ghost":      ["ghost_list_targetable_windows", "ghost_click_window", "ghost_send_text"],
        "refiner":    ["refiner_synthesize_custom_tool"],
    }

