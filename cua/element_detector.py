"""
UI元素检测模块
基于视觉大模型(VLM)实现界面元素的自动检测、分类与属性提取
支持5种核心UI元素类型：按钮/输入框/图片/文本标签/链接
支持异常场景：模糊/遮挡/重叠等复杂情况
"""
import openai
import json
import time
import os
import logging
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from .schemas import (
    ElementType, ElementQuality, BoundingBox,
    DetectedElement, ElementDetectionResult
)
from .vision_io import capture_screen_as_base64
from .perception.screen_capture import capture_screen_base64

logger = logging.getLogger(__name__)

VALID_ELEMENT_TYPES = {e.value for e in ElementType}
VALID_QUALITY_TAGS = {q.value for q in ElementQuality}

DETECTION_SYSTEM_PROMPT = """你是一个专业的UI界面元素检测器。你的任务是分析截图，识别出界面上的所有可交互和不可交互的UI元素，并返回结构化的检测结果。

【坐标体系】
- 使用0-1000的比例坐标系，左上角(0,0)，右下角(1000,1000)
- x=0最左，x=1000最右，y=0最上，y=1000最下
- 所有位置和尺寸都必须使用0-1000的比例坐标

【元素类型定义】
- button: 可点击的按钮（含图标按钮、悬浮按钮）
- input: 可输入文本的输入框（含搜索框、文本域、带placeholder的空输入框）
- image: 图片、头像、缩略图等视觉内容区域
- text: 纯文本标签、标题、说明文字等不可交互的文字区域
- link: 可点击的链接或导航项（含侧边栏菜单项、标签页）
- icon: 小图标、状态指示器等（通常小于30x30比例单位）
- checkbox: 复选框、单选框、开关切换
- dropdown: 下拉选择框
- tab: 标签页切换按钮
- dialog: 弹窗、对话框、模态窗口
- unknown: 无法确定类型的元素

【元素质量标签】
- clear: 元素清晰可见，无遮挡无模糊
- blurred: 元素模糊不清（如动画中间帧、失焦）
- occluded: 元素被其他窗口/弹窗部分遮挡
- overlapped: 元素与其他元素重叠，边界不明确
- partial: 元素只有部分可见（如在屏幕边缘被截断）

【检测规则】
1. 优先检测可交互元素（按钮、输入框、链接、复选框等）
2. 每个元素必须给出精确的边界框(x, y, width, height)
3. 提取元素上的文本内容（按钮文字、输入框placeholder、链接文本等）
4. 标记不可交互的纯展示元素 is_interactive=false
5. 评估每个元素的识别置信度(0-1)
6. 对于模糊/遮挡/重叠的元素，标记quality字段并降低置信度
7. 给每个元素一个语义化的alias（如"搜索按钮"、"用户名输入框"）
8. 检测界面整体是否存在异常情况

【输出格式】
必须严格返回以下JSON格式，不要有任何其他内容：
{
  "scene_description": "当前界面的整体描述",
  "elements": [
    {
      "element_type": "button",
      "bbox": {"x": 100, "y": 200, "width": 150, "height": 40},
      "text_content": "发送",
      "confidence": 0.95,
      "quality": "clear",
      "is_interactive": true,
      "attributes": {"disabled": false},
      "alias": "发送消息按钮"
    }
  ],
  "has_anomaly": false,
  "anomaly_details": null
}
"""


class ElementDetector:
    """
    UI元素检测器
    基于视觉大模型实现界面元素的自动检测与分类
    """

    DEFAULT_API_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DEFAULT_MODEL: str = "doubao-vision-pro-32k"
    DEFAULT_MAX_TOKENS: int = 2000
    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.5

    def __init__(
        self,
        api_url: str = None,
        api_key: str = None,
        model: str = None,
        confidence_threshold: float = None,
    ):
        load_dotenv()

        self.api_url = api_url or os.getenv("BASE_URL", os.getenv("CUA_MODEL_API_BASE", self.DEFAULT_API_URL))
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", os.getenv("CUA_MODEL_API_KEY", ""))
        self.model = model or os.getenv("MODEL_NAME", os.getenv("CUA_MODEL_NAME", self.DEFAULT_MODEL))
        self.confidence_threshold = confidence_threshold or float(
            os.getenv("ELEMENT_CONFIDENCE_THRESHOLD", str(self.DEFAULT_CONFIDENCE_THRESHOLD))
        )

        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.api_url
        )

    def _validate_element(self, raw: dict) -> Optional[DetectedElement]:
        """
        校验并规范化单个元素数据，对异常字段做容错处理
        """
        try:
            element_type_str = raw.get("element_type", "unknown").lower()
            if element_type_str not in VALID_ELEMENT_TYPES:
                element_type_str = "unknown"
            raw["element_type"] = element_type_str

            quality_str = raw.get("quality", "clear").lower()
            if quality_str not in VALID_QUALITY_TAGS:
                quality_str = "clear"
            raw["quality"] = quality_str

            bbox_raw = raw.get("bbox", {})
            if not isinstance(bbox_raw, dict):
                bbox_raw = {}
            bbox = BoundingBox(
                x=max(0, min(1000, int(bbox_raw.get("x", 0)))),
                y=max(0, min(1000, int(bbox_raw.get("y", 0)))),
                width=max(1, min(1000, int(bbox_raw.get("width", 50)))),
                height=max(1, min(1000, int(bbox_raw.get("height", 50)))),
            )
            raw["bbox"] = bbox

            confidence = float(raw.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            raw["confidence"] = confidence

            if quality_str != "clear" and confidence > 0.9:
                confidence = min(confidence, 0.75)
                raw["confidence"] = confidence

            raw.setdefault("text_content", None)
            raw.setdefault("is_interactive", True)
            raw.setdefault("attributes", {})
            raw.setdefault("alias", None)

            return DetectedElement(**raw)

        except Exception as e:
            logger.warning(f"元素数据校验失败，跳过: {e}, 原始数据: {raw}")
            return None

    def _deduplicate_elements(self, elements: List[DetectedElement]) -> List[DetectedElement]:
        """
        去除重叠度过高的重复元素（IoU>0.7且类型相同视为重复）
        """
        if len(elements) <= 1:
            return elements

        result = []
        for elem in elements:
            is_dup = False
            for existing in result:
                if elem.element_type != existing.element_type:
                    continue
                iou = self._compute_iou(elem.bbox, existing.bbox)
                if iou > 0.7:
                    is_dup = True
                    break
            if not is_dup:
                result.append(elem)
        return result

    @staticmethod
    def _compute_iou(box_a: BoundingBox, box_b: BoundingBox) -> float:
        """
        计算两个边界框的IoU(交并比)
        """
        x1 = max(box_a.x, box_b.x)
        y1 = max(box_a.y, box_b.y)
        x2 = min(box_a.x + box_a.width, box_b.x + box_b.width)
        y2 = min(box_a.y + box_a.height, box_b.y + box_b.height)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        union = box_a.area + box_b.area - intersection
        if union <= 0:
            return 0.0
        return intersection / union

    def _parse_vlm_response(self, content: str) -> ElementDetectionResult:
        """
        解析VLM返回的JSON内容，校验并构建ElementDetectionResult
        """
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"VLM返回内容JSON解析失败: {e}")
            return ElementDetectionResult(
                elements=[],
                scene_description="解析失败",
                has_anomaly=True,
                anomaly_details=f"JSON解析错误: {str(e)}"
            )

        raw_elements = data.get("elements", [])
        if not isinstance(raw_elements, list):
            raw_elements = []

        validated = []
        for raw in raw_elements:
            if not isinstance(raw, dict):
                continue
            elem = self._validate_element(raw)
            if elem and elem.confidence >= self.confidence_threshold:
                validated.append(elem)

        validated = self._deduplicate_elements(validated)

        has_anomaly = bool(data.get("has_anomaly", False))
        anomaly_details = data.get("anomaly_details")

        anomalous_count = sum(1 for e in validated if e.quality != ElementQuality.CLEAR)
        if anomalous_count > 0 and not has_anomaly:
            has_anomaly = True
            anomaly_details = anomaly_details or f"检测到{anomalous_count}个质量异常元素"

        scene_desc = data.get("scene_description", "")

        return ElementDetectionResult(
            elements=validated,
            scene_description=scene_desc,
            total_elements=len(validated),
            has_anomaly=has_anomaly,
            anomaly_details=anomaly_details,
        )

    def detect_from_base64(
        self,
        base64_img: str,
        target_types: Optional[List[ElementType]] = None,
        focus_query: Optional[str] = None,
    ) -> ElementDetectionResult:
        """
        从Base64编码的截图中检测UI元素
        :param base64_img: Base64编码的截图（支持带或不带data URI前缀）
        :param target_types: 可选，只检测指定类型的元素
        :param focus_query: 可选，聚焦查询关键词，如"搜索框"会让VLM更关注相关元素
        :return: 元素检测结果
        """
        start_time = time.time()

        if not self.api_key:
            return ElementDetectionResult(
                elements=[],
                has_anomaly=True,
                anomaly_details="API密钥未配置"
            )

        user_prompt = DETECTION_SYSTEM_PROMPT

        if target_types:
            type_names = ", ".join(t.value for t in target_types)
            user_prompt += f"\n\n【重点检测】请优先检测以下类型的元素：{type_names}"

        if focus_query:
            user_prompt += f"\n\n【聚焦查询】用户正在寻找：{focus_query}，请确保相关元素被检测到并给出精确坐标"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": base64_img}}
                        ]
                    }
                ],
                max_tokens=self.DEFAULT_MAX_TOKENS,
                temperature=0.0
            )

            content = response.choices[0].message.content.strip()
            logger.info(f"[ElementDetector] VLM原始返回:\n{content[:500]}...")

            result = self._parse_vlm_response(content)

        except openai.APIError as e:
            logger.error(f"VLM API调用失败: {e}")
            return ElementDetectionResult(
                elements=[],
                has_anomaly=True,
                anomaly_details=f"API调用失败: {str(e)}"
            )
        except Exception as e:
            logger.error(f"元素检测异常: {e}")
            return ElementDetectionResult(
                elements=[],
                has_anomaly=True,
                anomaly_details=f"检测异常: {str(e)}"
            )

        elapsed_ms = int((time.time() - start_time) * 1000)
        result.processing_time_ms = elapsed_ms

        logger.info(
            f"[ElementDetector] 检测完成: {result.total_elements}个元素, "
            f"耗时{elapsed_ms}ms, 异常={result.has_anomaly}"
        )

        return result

    def detect_from_screen(
        self,
        target_types: Optional[List[ElementType]] = None,
        focus_query: Optional[str] = None,
    ) -> ElementDetectionResult:
        """
        实时截取屏幕并检测UI元素
        :param target_types: 可选，只检测指定类型的元素
        :param focus_query: 可选，聚焦查询关键词
        :return: 元素检测结果
        """
        base64_img = capture_screen_as_base64()
        if not base64_img:
            return ElementDetectionResult(
                elements=[],
                has_anomaly=True,
                anomaly_details="截图失败"
            )
        return self.detect_from_base64(base64_img, target_types, focus_query)

    def find_element(
        self,
        query: str,
        element_type: Optional[ElementType] = None,
        min_confidence: float = 0.6,
    ) -> Optional[DetectedElement]:
        """
        查找最匹配的单个元素
        :param query: 查询描述，如"搜索框"、"发送按钮"
        :param element_type: 可选，限定元素类型
        :param min_confidence: 最低置信度阈值
        :return: 匹配度最高的元素，未找到返回None
        """
        result = self.detect_from_screen(focus_query=query)

        candidates = result.elements
        if element_type:
            candidates = [e for e in candidates if e.element_type == element_type]
        candidates = [e for e in candidates if e.confidence >= min_confidence]

        if not candidates:
            return None

        text_matched = [e for e in candidates if e.text_content and query.lower() in e.text_content.lower()]
        alias_matched = [e for e in candidates if e.alias and query.lower() in e.alias.lower()]

        for pool in [text_matched, alias_matched, candidates]:
            if pool:
                return max(pool, key=lambda e: e.confidence)

        return None

    def find_all_elements(
        self,
        element_type: Optional[ElementType] = None,
        min_confidence: float = 0.5,
    ) -> List[DetectedElement]:
        """
        查找所有匹配的元素
        :param element_type: 可选，限定元素类型
        :param min_confidence: 最低置信度阈值
        :return: 匹配的元素列表
        """
        result = self.detect_from_screen(target_types=[element_type] if element_type else None)

        candidates = result.elements
        if element_type:
            candidates = [e for e in candidates if e.element_type == element_type]
        candidates = [e for e in candidates if e.confidence >= min_confidence]

        return sorted(candidates, key=lambda e: e.confidence, reverse=True)
