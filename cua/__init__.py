"""
CUA (Computer-Use Agent) 视觉操作模块
提供飞书桌面端视觉操作的触发规则、动作原语和安全控制能力
坐标体系：统一使用比例坐标(0-1000)，对齐成熟方案
"""

from .trigger_rules import (
    LarkCliError,
    CuaAbortReason,
    CuaConfig,
    TriggerRuleEvaluator
)

from .schemas import (
    CuaRequest,
    VlmResponse,
    CuaResponse,
    CuaDiagnosisReport,
    CuaFixPlan,
    ElementType,
    ElementQuality,
    BoundingBox,
    DetectedElement,
    ElementDetectionResult
)

from .vision_io import (
    capture_screen_as_base64
)

from .primitives import (
    focus_and_maximize,
    verify_window_focus,
    detect_user_activity,
    reset_user_activity_flag,
    safe_click,
    safe_double_click,
    safe_move,
    safe_input,
    safe_press,
    safe_scroll,
    safe_hotkey,
    save_state_for_backtrack
)

# executor模块已移除，使用AgentLoopRunner替代

from .perception.screen_capture import (
    capture_screen_base64,
    build_marker_base64,
    save_screenshot_with_marker
)

from .models.llm_client import (
    fetch_model_list,
    test_model_connection,
    post_chat_completion
)

from .operators.action_executor import (
    parse_action_json,
    execute_parsed_actions,
    execute_actions_from_text
)

from .utils.feishu_app_control import (
    activate_feishu,
    is_foreground_window,
    get_window_rect
)

from .element_detector import (
    ElementDetector
)

# DSL相关模块
from .dsl.generator import (
    DslGenerator
)

from .dsl.evaluator import (
    DslEvaluator
)

from .dsl.doc_extractor import (
    DocumentCaseExtractor
)
# 基准测试模块
from .benchmark import (
    BenchmarkRunner,
    BenchmarkCase,
    BenchmarkResult
)

# 记忆功能模块
from .memory import (
    MemoryType,
    MemoryItem,
    MemoryManager,
    global_memory
)

from .report.md import (
    MdReportGenerator
)

from .report.insight_analyzer import (
    InsightAnalyzer
)

__version__ = "3.0.0"
__all__ = [
    "LarkCliError",
    "CuaAbortReason",
    "CuaConfig",
    "TriggerRuleEvaluator",
    "CuaRequest",
    "VlmResponse",
    "CuaResponse",
    "CuaDiagnosisReport",
    "CuaFixPlan",
    "capture_screen_as_base64",
    "focus_and_maximize",
    "verify_window_focus",
    "detect_user_activity",
    "reset_user_activity_flag",
    "safe_click",
    "safe_double_click",
    "safe_move",
    "safe_input",
    "safe_press",
    "safe_scroll",
    "safe_hotkey",
    "save_state_for_backtrack",
    "capture_screen_base64",
    "build_marker_base64",
    "save_screenshot_with_marker",
    "fetch_model_list",
    "test_model_connection",
    "post_chat_completion",
    "parse_action_json",
    "execute_parsed_actions",
    "execute_actions_from_text",
    "activate_feishu",
    "is_foreground_window",
    "get_window_rect",

    "ElementType",
    "ElementQuality",
    "BoundingBox",
    "DetectedElement",
    "ElementDetectionResult",
    "ElementDetector",
    
    # DSL相关导出
    "DslGenerator",
    "DslEvaluator",
    "DocumentCaseExtractor",
    "BenchmarkRunner",
    "BenchmarkCase", 
    "BenchmarkResult",
    "MemoryType",
    "MemoryItem",
    "MemoryManager",
    "global_memory",
    "MdReportGenerator",
    "InsightAnalyzer",
]
