from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class LarkCliError(Enum):
    """
    飞书CLI调用错误类型，触发CUA视觉方案接管的信号量
    当飞书CLI接口调用返回以下错误时，系统将自动切换到基于视觉大模型的CUA操作模式
    """
    
    RATE_LIMIT = "rate_limit_exceeded"
    """
    接口调用频率超限
    触发场景：短时间内大量调用飞书API达到限流阈值，CLI无法继续正常工作
    接管逻辑：切换到CUA视觉操作模式，通过模拟用户手动操作完成任务，避开API限流限制
    """
    
    API_UNSUPPORTED = "api_unsupported"
    """
    接口功能不支持
    触发场景：当前需要执行的操作没有对应的飞书开放API，或者API权限不足无法调用
    接管逻辑：切换到CUA视觉操作模式，通过界面交互完成CLI无法实现的功能
    """
    
    PERMISSION_DENIED = "permission_denied"
    """
    接口权限不足
    触发场景：当前账号没有调用对应API的权限，或者Token过期/失效
    接管逻辑：切换到CUA视觉操作模式，使用已登录的桌面客户端权限完成操作
    """
    
    API_ERROR = "api_internal_error"
    """
    接口内部错误
    触发场景：飞书服务端返回未知错误，API调用连续失败超过重试次数
    接管逻辑：切换到CUA视觉操作模式，绕过故障的API接口完成任务
    """
    
    RESULT_INVALID = "result_invalid"
    """
    CLI返回结果无效
    触发场景：CLI执行成功但返回结果为空、格式错误或不符合业务预期
    接管逻辑：切换到CUA视觉操作模式，重新获取正确结果
    """
    
    USER_REQUESTED = "user_requested"
    """
    用户主动要求使用视觉操作
    触发场景：用户明确指定使用CUA模式完成任务
    接管逻辑：直接进入CUA视觉操作模式
    """
    
    HYBRID_TASK_REQUIRED = "hybrid_task_required"
    """
    混合任务需要CUA协同
    触发场景：复杂任务需要CLI和CUA配合完成（如CLI获取数据后需要CUA在界面操作）
    接管逻辑：阶段性切换到CUA模式完成对应步骤
    """


class CuaAbortReason(Enum):
    """
    CUA执行放弃原因枚举，定义CUA视觉操作模式下终止执行的触发条件
    当出现以下情况时，CUA将自动放弃当前任务，避免无效操作或错误执行
    """
    
    LOW_CONFIDENCE = "low_confidence"
    """
    界面识别置信度过低
    触发场景：视觉大模型对当前屏幕界面的识别置信度低于设定阈值，无法确定界面元素含义
    放弃逻辑：停止执行，返回人工介入请求，避免误操作
    """
    
    TIMEOUT = "operation_timeout"
    """
    操作执行超时
    触发场景：单个操作步骤执行时间超过设定阈值，或整个任务执行时间超过总时长限制
    放弃逻辑：终止任务执行，返回超时错误，避免无限等待
    """
    
    INTERFACE_CHANGED = "interface_unexpectedly_changed"
    """
    界面意外变化
    触发场景：操作过程中界面发生预期外的变化（如弹窗、跳转至未知页面），与任务规划的界面流程不符
    放弃逻辑：停止执行，重新识别界面或请求人工确认
    """
    
    MAX_RETRY_EXCEEDED = "max_retry_exceeded"
    """
    操作重试次数超限
    触发场景：同一个操作步骤连续失败超过最大重试次数，仍无法成功完成
    放弃逻辑：终止任务，返回执行失败，避免重复无效操作
    """
    
    SECURITY_RISK = "security_risk_detected"
    """
    检测到安全风险
    触发场景：操作可能涉及敏感信息（如密码输入、删除重要数据等），或识别到钓鱼/风险界面
    放弃逻辑：立即停止执行，返回安全风险警告，必须人工确认后才能继续
    """
    
    USER_INTERRUPTED = "user_interrupted"
    """
    用户主动中断执行
    触发场景：检测到用户主动操作鼠标键盘，与CUA操作产生冲突
    放弃逻辑：暂停执行，等待用户确认是否继续
    """
    
    MULTI_MONITOR_UNSUPPORTED = "multi_monitor_unsupported"
    """
    多显示器场景不支持
    触发场景：检测到多显示器环境，坐标映射存在不确定性
    放弃逻辑：提示用户切换到单显示器模式或人工介入
    """


class CuaConfig(BaseModel):
    """CUA全局可配置参数，支持动态调整无需修改代码"""
    
    # 识别置信度阈值，低于此值触发放弃
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # 单个操作最大重试次数
    max_retry_count: int = Field(default=3, ge=1, le=10)
    # 单个操作超时时间（秒）
    operation_timeout: int = Field(default=30, ge=5, le=300)
    # 整个任务最大执行时间（秒）
    task_total_timeout: int = Field(default=300, ge=60, le=3600)
    # DPI缩放系数，0表示自动检测
    dpi_scale_factor: float = Field(default=0.0, ge=0.0, le=5.0)
    # 是否启用用户操作检测
    enable_user_interrupt_detection: bool = Field(default=True)
    # 是否启用安全风险检测
    enable_security_check: bool = Field(default=True)
    # 降级策略层级：0=仅CLI, 1=CLI优先+重试, 2=CLI重试+CUA, 3=直接CUA
    fallback_strategy_level: int = Field(default=2, ge=0, le=3)
    # 敏感操作黑名单，匹配到关键词的操作将被拦截
    sensitive_operation_blacklist: list = Field(default_factory=lambda: ["password", "支付", "转账", "删除", "卸载", "格式化"])


class TriggerRuleEvaluator:
    """触发规则评估器，实现分层降级策略和规则判断"""
    
    def __init__(self, config: Optional[CuaConfig] = None):
        self.config = config or CuaConfig()
    
    def should_trigger_cua(self, cli_result: Dict[str, Any]) -> bool:
        """评估是否需要触发CUA接管"""
        # 降级策略层级判断
        if self.config.fallback_strategy_level == 0:
            return False
        if self.config.fallback_strategy_level == 3:
            return True
            
        error_code = cli_result.get("error_code")
        if error_code in [e.value for e in LarkCliError]:
            return True
            
        # CLI执行成功但结果无效判断
        if cli_result.get("success") and not cli_result.get("data"):
            return self.config.fallback_strategy_level >= 2
            
        return False
    
    def should_abort_execution(self, execution_context: Dict[str, Any]) -> Optional[CuaAbortReason]:
        """评估是否需要中止CUA执行"""
        # 置信度检查
        if execution_context.get("confidence", 1.0) < self.config.confidence_threshold:
            return CuaAbortReason.LOW_CONFIDENCE
            
        # 重试次数检查
        if execution_context.get("retry_count", 0) >= self.config.max_retry_count:
            return CuaAbortReason.MAX_RETRY_EXCEEDED
            
        # 操作超时检查
        if execution_context.get("operation_elapsed", 0) >= self.config.operation_timeout:
            return CuaAbortReason.TIMEOUT
            
        # 任务总超时检查
        if execution_context.get("task_elapsed", 0) >= self.config.task_total_timeout:
            return CuaAbortReason.TIMEOUT
            
        # 用户中断检查
        if self.config.enable_user_interrupt_detection and execution_context.get("user_interrupted"):
            return CuaAbortReason.USER_INTERRUPTED
            
        # 安全风险检查
        if self.config.enable_security_check:
            operation = str(execution_context.get("operation", "")).lower()
            if any(keyword in operation for keyword in self.config.sensitive_operation_blacklist):
                return CuaAbortReason.SECURITY_RISK
                
        return None
