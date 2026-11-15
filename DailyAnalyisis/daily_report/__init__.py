"""
报告生成模块
包含HTML、图片、文本报告生成功能
"""

from .templates import HTMLTemplates
from .generators import ReportGenerator

__all__ = ["ReportGenerator", "HTMLTemplates"]
