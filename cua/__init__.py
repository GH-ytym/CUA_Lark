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

from .executor import (
    CuaExecutor,
    CuaOperationException
)

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
    "CuaExecutor",
    "CuaOperationException",
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
]
