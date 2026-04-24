"""
CUA (Computer-Use Agent) 视觉操作模块
提供飞书桌面端视觉操作的触发规则、动作原语和安全控制能力
"""

# 导出触发规则相关
from .trigger_rules import (
    LarkCliError,
    CuaAbortReason,
    CuaConfig,
    TriggerRuleEvaluator
)

# 导出动作原语相关
from .primitives import (
    # DPI缩放相关
    get_system_dpi_scale,
    set_dpi_scale_factor,
    get_dpi_scale_factor,
    
    # 窗口操作相关
    focus_and_maximize,
    verify_window_focus,
    
    # 用户活动检测
    detect_user_activity,
    reset_user_activity_flag,
    enable_user_activity_detection,
    
    # 基础动作原语
    safe_click,
    safe_input,
    safe_scroll,
    safe_hotkey,
    capture_screenshot,
    
    # 状态管理
    save_state_for_backtrack
)

__version__ = "1.1.0"
__all__ = [
    # 触发规则
    "LarkCliError",
    "CuaAbortReason",
    "CuaConfig",
    "TriggerRuleEvaluator",
    
    # 工具方法
    "get_system_dpi_scale",
    "set_dpi_scale_factor",
    "get_dpi_scale_factor",
    "focus_and_maximize",
    "verify_window_focus",
    "detect_user_activity",
    "reset_user_activity_flag",
    "enable_user_activity_detection",
    
    # 动作原语
    "safe_click",
    "safe_input",
    "safe_scroll",
    "safe_hotkey",
    "capture_screenshot",
    "save_state_for_backtrack",
]
