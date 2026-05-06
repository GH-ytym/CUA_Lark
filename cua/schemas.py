from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, List, Any


class ElementType(str, Enum):
    """
    UI元素类型枚举，定义视觉识别支持的常见界面元素分类
    """
    BUTTON = "button"
    INPUT = "input"
    IMAGE = "image"
    TEXT = "text"
    LINK = "link"
    ICON = "icon"
    CHECKBOX = "checkbox"
    DROPDOWN = "dropdown"
    TAB = "tab"
    DIALOG = "dialog"
    UNKNOWN = "unknown"


class ElementQuality(str, Enum):
    """
    元素视觉质量标签，标识识别场景的复杂程度
    """
    CLEAR = "clear"
    BLURRED = "blurred"
    OCCLUDED = "occluded"
    OVERLAPPED = "overlapped"
    PARTIAL = "partial"


class BoundingBox(BaseModel):
    """
    元素边界框，使用比例坐标(0-1000)体系
    """
    x: int = Field(ge=0, le=1000, description="左上角横坐标(0-1000比例坐标)")
    y: int = Field(ge=0, le=1000, description="左上角纵坐标(0-1000比例坐标)")
    width: int = Field(ge=0, le=1000, description="宽度(0-1000比例坐标)")
    height: int = Field(ge=0, le=1000, description="高度(0-1000比例坐标)")

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @property
    def area(self) -> int:
        return self.width * self.height


class DetectedElement(BaseModel):
    """
    单个检测到的UI元素结构体
    包含元素的类型、位置、尺寸、文本内容、置信度等关键属性
    """
    element_type: ElementType = Field(description="元素类型分类")
    bbox: BoundingBox = Field(description="元素边界框(比例坐标0-1000)")
    text_content: Optional[str] = Field(None, description="元素上的文本内容，如按钮文字、输入框placeholder、链接文本等")
    confidence: float = Field(ge=0.0, le=1.0, description="识别置信度，0-1之间")
    quality: ElementQuality = Field(default=ElementQuality.CLEAR, description="元素视觉质量标签")
    is_interactive: bool = Field(default=True, description="元素是否可交互(可点击/可输入)")
    attributes: dict[str, Any] = Field(default_factory=dict, description="元素附加属性，如disabled/checked/selected等状态")
    alias: Optional[str] = Field(None, description="元素语义别名，如'搜索按钮'、'用户名输入框'等")


class ElementDetectionResult(BaseModel):
    """
    元素检测结果结构体
    一次截图识别返回的所有检测元素及元信息
    """
    elements: List[DetectedElement] = Field(default_factory=list, description="检测到的UI元素列表")
    scene_description: str = Field(default="", description="整体场景描述，如'飞书聊天主界面'")
    total_elements: int = Field(default=0, description="检测到的元素总数")
    processing_time_ms: int = Field(default=0, description="识别处理耗时(毫秒)")
    has_anomaly: bool = Field(default=False, description="是否存在异常(模糊/遮挡/重叠等)")
    anomaly_details: Optional[str] = Field(None, description="异常详情描述")


class CuaRequest(BaseModel):
    """
    CUA执行请求结构体
    上层编排服务调用CUA执行器时传入的参数结构
    """
    instruction: str = Field(description="用户的自然语言指令，清晰描述需要CUA完成的具体任务")
    app: str = Field(default="飞书", description="要操作的目标应用名称")
    task: dict[str, Any] = Field(default_factory=dict, description="任务标识：id/session/chain")
    action: dict[str, Any] = Field(default_factory=dict, description="动作摘要：id/payload")
    trigger: dict[str, Any] = Field(default_factory=dict, description="触发摘要：source/code/name/attempts/summary")
    memory: dict[str, Any] = Field(default_factory=dict, description="记忆作用域：session/app/action")


class CuaMemoryUsage(BaseModel):
    """
    CUA记忆使用摘要，返回给后端用于任务详情和调试日志透传。
    """
    scope: dict[str, Any] = Field(default_factory=dict, description="本次使用的记忆作用域")
    used: List[str] = Field(default_factory=list, description="注入prompt的记忆ID")
    written: List[str] = Field(default_factory=list, description="本次执行写入的记忆ID")
    summary: str = Field(default="", description="记忆使用摘要")


class VlmResponse(BaseModel):
    """
    视觉大模型(VLM)识别结果结构体
    截图传给大模型后返回的动作指令结构，用于指导CUA执行下一步操作
    """
    action_type: str = Field(description="动作类型：click(点击)、input(输入文本)、scroll(滚动)、hotkey(快捷键)、abort(终止执行)")
    x: Optional[int] = Field(None, description="点击坐标-横坐标，仅action_type为click时需要")
    y: Optional[int] = Field(None, description="点击坐标-纵坐标，仅action_type为click时需要")
    text: Optional[str] = Field(None, description="输入的文本内容，仅action_type为input时需要")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="模型对当前识别结果的置信度，0-1之间，值越高越可靠")


class CuaDiagnosisReport(BaseModel):
    """
    错误诊断报告结构体
    LLM分析失败截图后返回的结构化诊断结果
    """
    error_type: str = Field(description="错误分类：COORDINATE_OFFSET(坐标偏移)/INTERFACE_CHANGED(界面变化)/ELEMENT_NOT_FOUND(元素找不到)/PERMISSION_BLOCKED(权限拦截)/UNKNOWN(未知错误)")
    error_description: str = Field(description="错误详细描述，说明界面上具体的异常情况")
    root_cause: str = Field(description="根本原因分析，解释为什么操作会失败")
    confidence: float = Field(description="诊断置信度，0-1之间", ge=0.0, le=1.0)


class CuaFixPlan(BaseModel):
    """
    修复方案结构体
    基于诊断报告生成的针对性修复策略
    """
    fix_strategy: str = Field(description="修复策略：ADJUST_COORDINATE(调整坐标)/RETRY_DIRECT(直接重试)/CHANGE_ACTION(更换动作类型)/ABORT(终止执行)")
    adjust_params: dict[str, Any] = Field(default_factory=dict, description="调整参数，比如调整后的坐标{x: 100, y: 200}")
    reasoning: str = Field(description="修复方案的理由说明")
    expected_effect: str = Field(description="预期修复效果")


class CuaResponse(BaseModel):
    """
    CUA执行结果返回结构体
    CUA执行完成后返回给上层服务的结果结构
    """
    success: bool = Field(description="执行是否成功：True=全部执行完成，False=执行失败/中途终止")
    message: str = Field(description="执行结果说明：成功时返回完成信息，失败时返回具体错误原因")
    history_states: List[Any] = Field(default_factory=list, description="执行轨迹历史，记录每一步的操作、截图、识别结果等，用于问题排查和回溯")
    diagnosis_report: Optional[CuaDiagnosisReport] = Field(None, description="失败时的诊断报告，只有执行失败时有值")
    fix_plan: Optional[CuaFixPlan] = Field(None, description="失败时的修复方案，只有执行失败时有值")
    memory: Optional[CuaMemoryUsage] = Field(None, description="本次CUA执行使用和写入的记忆元数据")
