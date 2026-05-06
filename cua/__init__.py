"""
CUA (Computer-Use Agent) public package contract.

Keep this module lightweight so backend services can import schemas, trigger
rules, and memory contracts without loading desktop-only dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .executor import CuaExecutor
from .memory import MemoryItem, MemoryManager, MemoryType, global_memory
from .schemas import (
    BoundingBox,
    CuaDiagnosisReport,
    CuaFixPlan,
    CuaMemoryUsage,
    CuaRequest,
    CuaResponse,
    DetectedElement,
    ElementDetectionResult,
    ElementQuality,
    ElementType,
    VlmResponse,
)
from .trigger_rules import CuaAbortReason, CuaConfig, LarkCliError, TriggerRuleEvaluator


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "capture_screen_as_base64": ("cua.vision_io", "capture_screen_as_base64"),
    "focus_and_maximize": ("cua.primitives", "focus_and_maximize"),
    "verify_window_focus": ("cua.primitives", "verify_window_focus"),
    "detect_user_activity": ("cua.primitives", "detect_user_activity"),
    "reset_user_activity_flag": ("cua.primitives", "reset_user_activity_flag"),
    "safe_click": ("cua.primitives", "safe_click"),
    "safe_double_click": ("cua.primitives", "safe_double_click"),
    "safe_move": ("cua.primitives", "safe_move"),
    "safe_input": ("cua.primitives", "safe_input"),
    "safe_press": ("cua.primitives", "safe_press"),
    "safe_scroll": ("cua.primitives", "safe_scroll"),
    "safe_hotkey": ("cua.primitives", "safe_hotkey"),
    "save_state_for_backtrack": ("cua.primitives", "save_state_for_backtrack"),
    "capture_screen_base64": ("cua.perception.screen_capture", "capture_screen_base64"),
    "build_marker_base64": ("cua.perception.screen_capture", "build_marker_base64"),
    "save_screenshot_with_marker": ("cua.perception.screen_capture", "save_screenshot_with_marker"),
    "fetch_model_list": ("cua.models.llm_client", "fetch_model_list"),
    "test_model_connection": ("cua.models.llm_client", "test_model_connection"),
    "post_chat_completion": ("cua.models.llm_client", "post_chat_completion"),
    "parse_action_json": ("cua.operators.action_executor", "parse_action_json"),
    "execute_parsed_actions": ("cua.operators.action_executor", "execute_parsed_actions"),
    "execute_actions_from_text": ("cua.operators.action_executor", "execute_actions_from_text"),
    "activate_feishu": ("cua.utils.feishu_app_control", "activate_feishu"),
    "is_foreground_window": ("cua.utils.feishu_app_control", "is_foreground_window"),
    "get_window_rect": ("cua.utils.feishu_app_control", "get_window_rect"),
    "ElementDetector": ("cua.element_detector", "ElementDetector"),
    "DslGenerator": ("cua.dsl.generator", "DslGenerator"),
    "DslEvaluator": ("cua.dsl.evaluator", "DslEvaluator"),
    "DocumentCaseExtractor": ("cua.dsl.doc_extractor", "DocumentCaseExtractor"),
    "BenchmarkRunner": ("cua.benchmark", "BenchmarkRunner"),
    "BenchmarkCase": ("cua.benchmark", "BenchmarkCase"),
    "BenchmarkResult": ("cua.benchmark", "BenchmarkResult"),
    "MdReportGenerator": ("cua.report.md", "MdReportGenerator"),
    "InsightAnalyzer": ("cua.report.insight_analyzer", "InsightAnalyzer"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'cua' has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__version__ = "3.0.0"

__all__ = [
    "LarkCliError",
    "CuaAbortReason",
    "CuaConfig",
    "TriggerRuleEvaluator",
    "CuaExecutor",
    "CuaRequest",
    "VlmResponse",
    "CuaResponse",
    "CuaDiagnosisReport",
    "CuaFixPlan",
    "CuaMemoryUsage",
    "MemoryType",
    "MemoryItem",
    "MemoryManager",
    "global_memory",
    "ElementType",
    "ElementQuality",
    "BoundingBox",
    "DetectedElement",
    "ElementDetectionResult",
    *_LAZY_EXPORTS.keys(),
]
