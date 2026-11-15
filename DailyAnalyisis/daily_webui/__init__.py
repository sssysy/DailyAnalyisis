"""
WebUI 基础设施层 - 任务管理器与 Web API 桥接
"""

from .plugin_page_bridge import PluginPageWebUIBridge
from .active_task_manager import ActiveTaskManager

__all__ = ["ActiveTaskManager", "PluginPageWebUIBridge"]
