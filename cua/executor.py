import openai
import copy
import time
import os
import json
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
from .schemas import CuaRequest, VlmResponse, CuaResponse, CuaDiagnosisReport, CuaFixPlan
from .vision_io import capture_screen_as_base64
from .primitives import (
    focus_and_maximize,
    safe_click,
    safe_double_click,
    safe_move,
    safe_input,
    safe_press,
    safe_scroll,
    safe_hotkey,
    reset_user_activity_flag,
)


class CuaOperationException(Exception):
    """CUA操作异常，包含完整的失败上下文信息"""
    def __init__(self, message: str, context: Dict[str, Any]):
        super().__init__(message)
        self.context = context


class CuaExecutor:
    """
    CUA执行器核心类
    实现完整的"截图-识别-动作"执行链路，对外提供统一的执行入口
    坐标体系：VLM输出比例坐标(0-1000)，执行时通过pyautogui.size()换算为绝对屏幕坐标
    
    配置优先级：构造函数传入参数 > .env文件配置 > 默认值
    """
    
    DEFAULT_API_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DEFAULT_MODEL: str = "doubao-vision-pro-32k"
    DEFAULT_MAX_TOKENS: int = 300
    DEFAULT_IMAGE_MAX_SIDE: int = 1280
    DEFAULT_IMAGE_QUALITY: int = 70
    DEFAULT_MAX_RETRY_COUNT: int = 5
    DEFAULT_RETRY_INTERVAL: float = 1.0
    DEFAULT_MAX_CLICK_REVIEW_COUNT: int = 5
    
    @staticmethod
    def get_screen_resolution() -> Tuple[int, int]:
        """获取屏幕分辨率（pyautogui.size()，DPI-aware逻辑分辨率）"""
        import pyautogui
        return pyautogui.size()
    
    @staticmethod
    def validate_coordinate(x: int, y: int) -> bool:
        """验证比例坐标是否在0-1000范围内"""
        return 0 <= x <= 1000 and 0 <= y <= 1000
    
    def __init__(self, api_url: str = None, api_key: str = None, model: str = None):
        load_dotenv()
        
        self.api_url = api_url or os.getenv("BASE_URL", os.getenv("CUA_MODEL_API_BASE", self.DEFAULT_API_URL))
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", os.getenv("CUA_MODEL_API_KEY", ""))
        self.model = model or os.getenv("MODEL_NAME", os.getenv("CUA_MODEL_NAME", self.DEFAULT_MODEL))
        self.max_tokens = int(os.getenv("VLM_MAX_TOKENS", self.DEFAULT_MAX_TOKENS))
        self.image_max_side = int(os.getenv("VLM_IMAGE_MAX_SIDE", self.DEFAULT_IMAGE_MAX_SIDE))
        self.image_quality = int(os.getenv("VLM_IMAGE_JPEG_QUALITY", self.DEFAULT_IMAGE_QUALITY))
        
        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.api_url
        )
        
        self.history_states: List[Dict[str, Any]] = []
    
    def _call_ui_tars_api(self, base64_img: str, instruction: str) -> VlmResponse:
        """
        调用视觉大模型API，识别截图并返回动作指令
        坐标体系：使用比例坐标(0-1000)，对齐成熟方案
        :param base64_img: Base64编码的截图
        :param instruction: 用户自然语言指令
        :return: 模型返回的动作指令结构体
        """
        if not self.api_key:
            raise RuntimeError("API密钥未配置，请在.env文件中设置OPENAI_API_KEY或CUA_MODEL_API_KEY")
        
        try:
            prompt = f"""
            你是桌面自动化视觉Agent。根据当前截图和用户指令，返回要执行的UI操作。
            
            坐标体系说明：
            - 屏幕坐标系为0-1000的比例坐标，左上角为(0,0)，右下角为(1000,1000)
            - x=0表示最左边，x=1000表示最右边
            - y=0表示最上边，y=1000表示最下边
            - 请根据截图中元素的位置，估算其对应的0-1000比例坐标
            - 点击要点击在目标控件中心位置
            
            必须严格返回JSON格式，不要有其他任何内容，字段说明：
            - action_type: 动作类型，只能是 click/input/scroll/hotkey/abort 其中之一
            - x: 点击的横坐标（0-1000比例坐标），仅action_type为click时需要
            - y: 点击的纵坐标（0-1000比例坐标），仅action_type为click时需要
            - text: 输入的文本内容或快捷键组合（如"ctrl+c"），仅action_type为input/hotkey时需要
            - confidence: 识别置信度，0-1之间的数字
            - reasoning: 简短的操作理由
            
            规则：
            1. 先确认当前前台是否为飞书，若不是优先执行激活飞书窗口
            2. 输入前要确保输入框已激活
            
            用户指令：{instruction}
            """
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": base64_img}}
                        ]
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.0
            )
            
            content = response.choices[0].message.content.strip()
            
            print(f"\n[CUA] 🔍 视觉模型返回原始内容:\n{content}\n")
            
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            vlm_response = VlmResponse.model_validate_json(content)
            print(f"[CUA] ✅ 解析后动作: type={vlm_response.action_type}, x={vlm_response.x}, y={vlm_response.y}, text={vlm_response.text}, 置信度={vlm_response.confidence:.2f}")
            
            return vlm_response
            
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg:
                raise RuntimeError(f"API地址错误，请检查BASE_URL配置，当前地址：{self.api_url}") from e
            elif "invalid_api_key" in error_msg or "authentication" in error_msg.lower():
                raise RuntimeError("API密钥无效，请检查OPENAI_API_KEY配置") from e
            elif "model_not_found" in error_msg:
                raise RuntimeError(f"模型不存在，请检查MODEL_NAME配置，当前模型：{self.model}") from e
            else:
                raise RuntimeError(f"调用VLM失败: {error_msg}") from e
    
    def _verify_operation_result(self, instruction: str, expected_result: str = None) -> str:
        """
        验证操作结果，截图传给LLM判断是否成功
        :param instruction: 原始操作指令
        :param expected_result: 可选，预期结果描述
        :return: 判断结果：success/failed/uncertain
        """
        base64_img = capture_screen_as_base64()
        
        if not expected_result:
            expected_result = f"完成了用户指令：{instruction}，界面出现预期的变化"
        
        verify_prompt = f"""
        你是操作验证专家，请判断当前截图是否显示操作已经成功完成。
        
        操作指令：{instruction}
        预期结果：{expected_result}
        
        请只返回三个结果中的一个：
        - "成功"：操作已经完成，界面有预期的变化/元素/提示
        - "失败"：操作明显没有完成，界面没有任何预期变化
        - "不确定"：无法明确判断是否成功
        
        不要返回其他任何内容。
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": verify_prompt},
                        {"type": "image_url", "image_url": {"url": base64_img}}
                    ]
                }
            ],
            max_tokens=10,
            temperature=0.0
        )
        
        result = response.choices[0].message.content.strip()
        print(f"[CUA] 🧐 验证模型返回结果: {result}")
        
        if "成功" in result:
            verify_result = "success"
        elif "失败" in result:
            verify_result = "failed"
        else:
            verify_result = "uncertain"
            
        print(f"[CUA] 📊 验证结论: {verify_result}")
        return verify_result

    def _review_click_action(
        self,
        marker_base64: str,
        instruction: str,
        action: VlmResponse,
    ) -> Tuple[VlmResponse, bool, str]:
        """
        在真正点击前，用带标记的截图复核坐标是否命中目标。
        坐标体系：比例坐标(0-1000)
        """
        if not marker_base64:
            return action, True, "缺少标记截图，跳过复核"

        prompt = f"""
        你是桌面自动化点击坐标复核器。给你一张已经标出红色十字/红圈点击点的截图，请判断这个点击点是否真的落在目标控件的有效点击区域中心附近。

        用户指令：{instruction}
        当前候选动作：
        - action_type: {action.action_type}
        - x: {action.x} (0-1000比例坐标)
        - y: {action.y} (0-1000比例坐标)

        规则：
        1. 只判断当前这个红色标记点是否正确。
        2. 如果标记点已经在目标控件有效区域中心附近，review_passed 返回 true，并原样返回坐标。
        3. 如果标记点明显落在错误元素、文字空白区、图标边缘或相邻控件上，review_passed 返回 false，并返回修正后的更准确中心坐标（0-1000比例坐标）。
        4. 若用户指令目标与当前点对应的界面元素不一致，必须修正坐标。

        必须严格返回JSON，不要有其他内容：
        {{
          "review_passed": true,
          "action_type": "click",
          "x": 123,
          "y": 456,
          "confidence": 0.95,
          "reasoning": "一句话说明该点是否通过复核；若未通过，说明为什么以及修正依据"
        }}
        """

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": marker_base64}}
                    ]
                }
            ],
            max_tokens=200,
            temperature=0.0
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        print(f"[CUA] 🎯 坐标复核原始返回: {content}")

        reviewed = json.loads(content)
        if reviewed.get("action_type") != "click":
            return action, False, "复核结果不是 click，已回退到原坐标"

        reviewed_x = reviewed.get("x")
        reviewed_y = reviewed.get("y")
        reviewed_confidence = reviewed.get("confidence", action.confidence)
        reviewed_reasoning = reviewed.get("reasoning", "")
        review_passed = bool(reviewed.get("review_passed", False))

        if not isinstance(reviewed_x, int) or not isinstance(reviewed_y, int):
            return action, False, "复核结果缺少有效坐标，已回退到原坐标"

        if not self.validate_coordinate(reviewed_x, reviewed_y):
            return action, False, f"复核坐标({reviewed_x}, {reviewed_y})超出0-1000范围"

        reviewed_action = action.model_copy(
            update={
                "x": reviewed_x,
                "y": reviewed_y,
                "confidence": reviewed_confidence
            }
        )

        status_text = "通过" if review_passed else "未通过"
        if (reviewed_x, reviewed_y) != (action.x, action.y):
            print(
                f"[CUA] 🎯 点击坐标复核{status_text}: ({action.x}, {action.y}) -> ({reviewed_x}, {reviewed_y})"
                f" | {reviewed_reasoning}"
            )
        else:
            print(f"[CUA] 🎯 点击坐标复核{status_text}: ({action.x}, {action.y}) | {reviewed_reasoning}")

        return reviewed_action, review_passed, reviewed_reasoning

    def _refine_click_action_until_review_passed(
        self,
        instruction: str,
        action: VlmResponse,
        original_screenshot: Optional[Image.Image],
        retry_count: int,
    ) -> VlmResponse:
        """
        循环复核点击坐标，直到模型明确通过后才允许执行。
        坐标体系：比例坐标(0-1000)
        """
        if not original_screenshot:
            return action

        from .perception.screen_capture import build_marker_base64

        current_action = action
        for review_round in range(1, self.DEFAULT_MAX_CLICK_REVIEW_COUNT + 1):
            marker_base64 = build_marker_base64(
                original_screenshot,
                current_action.x,
                current_action.y,
                quality=self.image_quality
            )
            reviewed_action, review_passed, review_reasoning = self._review_click_action(
                marker_base64=marker_base64,
                instruction=instruction,
                action=current_action,
            )

            if not self.validate_coordinate(reviewed_action.x, reviewed_action.y):
                raise RuntimeError(
                    f"复核后的点击坐标({reviewed_action.x}, {reviewed_action.y})超出0-1000范围"
                )

            self.history_states.append({
                "step": "click_coordinate_review",
                "timestamp": time.time(),
                "retry_count": retry_count,
                "review_round": review_round,
                "review_passed": review_passed,
                "reasoning": review_reasoning,
                "original_coordinate": (current_action.x, current_action.y),
                "reviewed_coordinate": (reviewed_action.x, reviewed_action.y),
                "confidence": reviewed_action.confidence
            })

            current_action = reviewed_action
            if review_passed:
                return current_action

        raise RuntimeError(
            f"点击坐标连续复核{self.DEFAULT_MAX_CLICK_REVIEW_COUNT}轮仍未通过，最后坐标: ({current_action.x}, {current_action.y})"
        )
    
    def _diagnose_failure(self, failure_base64: str, instruction: str, executed_action: VlmResponse) -> CuaDiagnosisReport:
        """
        调用LLM分析失败截图，生成结构化错误诊断报告
        """
        prompt = f"""
        你是UI自动化错误诊断专家，分析操作失败的截图，输出结构化的诊断报告。
        
        原始指令：{instruction}
        刚刚执行的动作：{executed_action.model_dump_json()}
        
        请分析截图内容，找出操作失败的原因，严格返回JSON格式，字段说明：
        - error_type: 错误类型，只能是以下值：
            COORDINATE_OFFSET: 坐标偏移，点到了错误位置
            INTERFACE_CHANGED: 界面发生了预期外的变化
            ELEMENT_NOT_FOUND: 要操作的元素找不到
            PERMISSION_BLOCKED: 有权限弹窗/拦截提示
            UNKNOWN: 未知错误
        - error_description: 详细描述界面上看到的异常情况
        - root_cause: 根本原因分析
        - confidence: 诊断置信度，0-1之间的数字
        
        不要返回其他任何内容。
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": failure_base64}}
                    ]
                }
            ],
            max_tokens=300,
            temperature=0.0
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        print(f"[CUA] 📝 诊断原始返回: {content}")
        return CuaDiagnosisReport.model_validate_json(content)
    
    def _generate_fix_plan(self, diagnosis: CuaDiagnosisReport, original_action: VlmResponse) -> CuaFixPlan:
        """
        基于诊断报告生成针对性修复方案
        """
        prompt = f"""
        你是UI自动化修复专家，根据错误诊断报告生成最优修复方案。
        
        诊断报告：{diagnosis.model_dump_json()}
        原执行动作：{original_action.model_dump_json()}
        
        请生成修复方案，严格返回JSON格式，字段说明：
        - fix_strategy: 修复策略，只能是以下值：
            ADJUST_COORDINATE: 调整坐标后重试（仅用于坐标偏移错误，坐标为0-1000比例坐标）
            RETRY_DIRECT: 直接重试（临时问题，比如弹窗刚好消失）
            CHANGE_ACTION: 更换动作类型重新识别（界面变化/元素找不到）
            ABORT: 终止执行（无法修复的问题）
        - adjust_params: 调整参数，比如ADJUST_COORDINATE时返回{{"x": 500, "y": 300}}（0-1000比例坐标）
        - reasoning: 修复方案的理由
        - expected_effect: 预期修复效果
        
        不要返回其他任何内容。
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.0
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        print(f"[CUA] 📝 修复方案原始返回: {content}")
        return CuaFixPlan.model_validate_json(content)
    
    def _execute_single_operation(
        self,
        action: VlmResponse,
        hwnd: int,
        instruction: str,
    ) -> str:
        """执行单个操作并验证结果"""
        try:
            if action.action_type == "click":
                safe_click(action.x, action.y, expected_hwnd=hwnd)
            elif action.action_type == "input":
                safe_input(action.text, expected_hwnd=hwnd)
            elif action.action_type == "scroll":
                safe_scroll(3, direction="down", expected_hwnd=hwnd)
            elif action.action_type == "hotkey":
                keys = action.text.split("+")
                safe_hotkey(*keys, expected_hwnd=hwnd)
            
            time.sleep(self.DEFAULT_RETRY_INTERVAL)
            return self._verify_operation_result(instruction)
            
        except Exception as e:
            return "failed"
    
    def run(self, request: CuaRequest, expected_result: str = None) -> CuaResponse:
        """
        CUA执行核心方法，完成完整的"截图-识别-动作-验证"链路，支持全流程重试
        坐标体系：VLM输出比例坐标(0-1000)，由primitives.safe_click换算为绝对屏幕坐标
        :param request: CUA执行请求
        :param expected_result: 自定义预期结果描述
        :return: 执行结果
        """
        try:
            self.history_states.clear()
            reset_user_activity_flag()
            
            # 1. 拉起并最大化目标应用
            success, hwnd = focus_and_maximize(request.app_name)
            if not success:
                return CuaResponse(
                    success=False,
                    message=f"无法找到并激活目标应用: {request.app_name}",
                    history_states=copy.deepcopy(self.history_states)
                )
            
            self.history_states.append({
                "step": "activate_app",
                "timestamp": time.time(),
                "app_name": request.app_name,
                "success": success,
                "hwnd": hwnd
            })
            
            screen_width, screen_height = self.get_screen_resolution()
            
            retry_context = {
                "original_instruction": request.instruction,
                "expected_result": expected_result,
                "screen_resolution": (screen_width, screen_height),
                "attempts": []
            }
            
            for retry_count in range(self.DEFAULT_MAX_RETRY_COUNT):
                attempt_info = {
                    "retry_number": retry_count + 1,
                    "timestamp": time.time()
                }
                vlm_response = None
                print(f"\n[CUA] 🔄 开始第 {retry_count + 1}/{self.DEFAULT_MAX_RETRY_COUNT} 次执行尝试")
                
                try:
                    # 2. 截图并转换为Base64
                    from .perception.screen_capture import capture_screen_base64
                    self.original_screenshot = None
                    base64_img = ""
                    try:
                        screenshot_result = capture_screen_base64(quality=70, save_original=True)
                        if screenshot_result:
                            base64_img_data, screenshot_size, self.original_screenshot = screenshot_result
                            base64_img = f"data:image/jpeg;base64,{base64_img_data}"
                    except Exception as e:
                        base64_img = capture_screen_as_base64()
                        import logging
                        logging.warning(f"新版截图失败，降级使用旧版: {e}")
                    
                    self.history_states.append({
                        "step": "capture_screen",
                        "timestamp": time.time(),
                        "retry_count": retry_count + 1,
                        "base64_length": len(base64_img)
                    })
                    
                    # 3. 调用视觉大模型API获取动作指令
                    vlm_response = self._call_ui_tars_api(base64_img, request.instruction)
                    
                    self.history_states.append({
                        "step": "vlm_inference",
                        "timestamp": time.time(),
                        "retry_count": retry_count + 1,
                        "action": vlm_response.model_dump()
                    })
                    
                    if vlm_response.action_type == "abort":
                        return CuaResponse(
                            success=False,
                            message="模型主动终止执行",
                            history_states=copy.deepcopy(self.history_states)
                        )
                    
                    # 4. 坐标验证与复核（点击动作，使用比例坐标0-1000）
                    if vlm_response.action_type == "click":
                        if vlm_response.x is None or vlm_response.y is None:
                            raise RuntimeError("点击动作缺少坐标参数")
                        
                        if not self.validate_coordinate(vlm_response.x, vlm_response.y):
                            raise RuntimeError(
                                f"点击坐标({vlm_response.x}, {vlm_response.y})超出0-1000比例范围"
                            )

                        vlm_response = self._refine_click_action_until_review_passed(
                            instruction=request.instruction,
                            action=vlm_response,
                            original_screenshot=self.original_screenshot,
                            retry_count=retry_count + 1
                        )
                        
                        print(f"[CUA] 🖱️  坐标验证通过: 比例坐标({vlm_response.x}, {vlm_response.y})")
                    
                    # 5. 执行动作
                    if vlm_response.action_type == "click":
                        if self.original_screenshot:
                            from .perception.screen_capture import save_screenshot_with_marker
                            marker_path = save_screenshot_with_marker(self.original_screenshot, vlm_response.x, vlm_response.y)
                            if marker_path:
                                print(f"[CUA] 📸 点击位置已标记并保存: {os.path.basename(marker_path)}")
                                self.history_states[-1]["click_marker_path"] = marker_path
                        
                        safe_click(vlm_response.x, vlm_response.y, expected_hwnd=hwnd)
                    
                    elif vlm_response.action_type == "input":
                        if vlm_response.text is None:
                            raise RuntimeError("输入动作缺少文本内容")
                        safe_input(vlm_response.text, expected_hwnd=hwnd)
                    
                    elif vlm_response.action_type == "scroll":
                        safe_scroll(3, direction="down", expected_hwnd=hwnd)
                    
                    elif vlm_response.action_type == "hotkey":
                        if vlm_response.text is None:
                            raise RuntimeError("快捷键动作缺少按键内容")
                        keys = vlm_response.text.split("+")
                        safe_hotkey(*keys, expected_hwnd=hwnd)
                    
                    else:
                        raise RuntimeError(f"未知的动作类型: {vlm_response.action_type}")
                    
                    # 6. 验证操作结果
                    verify_result = self._verify_operation_result(request.instruction, expected_result)
                    attempt_info["verify_result"] = verify_result
                    
                    if verify_result == "success":
                        self.history_states.append({
                            "step": "execute_success",
                            "timestamp": time.time(),
                            "action_type": vlm_response.action_type,
                            "success": True,
                            "retry_count": retry_count + 1,
                            "verify_result": verify_result
                        })
                        
                        success_msg = f"执行成功，完成动作: {vlm_response.action_type}，共尝试{retry_count + 1}次"
                        print(f"\n[CUA] ✅ {success_msg}")
                        
                        return CuaResponse(
                            success=True,
                            message=success_msg,
                            history_states=copy.deepcopy(self.history_states)
                        )
                    
                    attempt_info["message"] = f"验证结果: {verify_result}"
                    print(f"[CUA] ❌ 第{retry_count + 1}次尝试失败: {verify_result}")
                    
                except Exception as e:
                    attempt_info["message"] = f"执行失败: {str(e)}"
                    attempt_info["verify_result"] = "failed"
                    print(f"[CUA] ❌ 第{retry_count + 1}次尝试异常: {str(e)}")
            
                # 失败了，进入诊断-修复流程
                if attempt_info.get("verify_result", "failed") != "success":
                    print(f"[CUA] 🔍 启动智能错误诊断...")
                    
                    if not vlm_response:
                        print(f"[CUA] ⚠️  前期步骤失败，直接重试...")
                        continue
                    
                    failure_base64 = capture_screen_as_base64()
                    
                    diagnosis_report = self._diagnose_failure(
                        failure_base64, 
                        request.instruction, 
                        vlm_response
                    )
                    print(f"[CUA] 🩺 诊断结果: {diagnosis_report.error_type} - {diagnosis_report.error_description} (置信度: {diagnosis_report.confidence:.2f})")
                    
                    fix_plan = self._generate_fix_plan(diagnosis_report, vlm_response)
                    print(f"[CUA] 🔧 修复方案: {fix_plan.fix_strategy} - {fix_plan.reasoning}")
                    
                    attempt_info["diagnosis"] = diagnosis_report.model_dump()
                    attempt_info["fix_plan"] = fix_plan.model_dump()
                    
                    if fix_plan.fix_strategy == "ADJUST_COORDINATE" and vlm_response.action_type == "click":
                        new_x = fix_plan.adjust_params["x"]
                        new_y = fix_plan.adjust_params["y"]
                        print(f"[CUA] 🔄 调整坐标后重试: 原坐标({vlm_response.x}, {vlm_response.y}) → 新坐标({new_x}, {new_y})")
                        try:
                            safe_click(new_x, new_y, expected_hwnd=hwnd)
                            verify_result = self._verify_operation_result(request.instruction, expected_result)
                            if verify_result == "success":
                                self.history_states.append({
                                    "step": "execute_success",
                                    "timestamp": time.time(),
                                    "action_type": vlm_response.action_type,
                                    "success": True,
                                    "retry_count": retry_count + 1,
                                    "verify_result": verify_result,
                                    "fixed_coordinate": (new_x, new_y)
                                })
                                success_msg = f"执行成功，调整坐标后完成动作: {vlm_response.action_type}，共尝试{retry_count + 1}次"
                                print(f"\n[CUA] ✅ {success_msg}")
                                return CuaResponse(
                                    success=True,
                                    message=success_msg,
                                    history_states=copy.deepcopy(self.history_states)
                                )
                        except Exception as e:
                            print(f"[CUA] ❌ 调整坐标后执行失败: {str(e)}")
                        continue
                    
                    elif fix_plan.fix_strategy == "RETRY_DIRECT":
                        print(f"[CUA] 🔄 直接重试...")
                        continue
                    
                    elif fix_plan.fix_strategy == "CHANGE_ACTION":
                        print(f"[CUA] 🔄 更换动作类型重试...")
                        continue
                    
                    elif fix_plan.fix_strategy == "ABORT":
                        print(f"[CUA] 🛑 无法修复，终止执行: {fix_plan.reasoning}")
                        self.history_states.append({
                            "step": "diagnosis_abort",
                            "timestamp": time.time(),
                            "diagnosis": diagnosis_report.model_dump(),
                            "fix_plan": fix_plan.model_dump()
                        })
                        return CuaResponse(
                            success=False,
                            message=f"执行失败，诊断后无法修复: {diagnosis_report.error_description}",
                            history_states=copy.deepcopy(self.history_states),
                            diagnosis_report=diagnosis_report,
                            fix_plan=fix_plan
                        )
                
                retry_context["attempts"].append(attempt_info)
                self.history_states.append({
                    "step": "execute_attempt",
                    "timestamp": time.time(),
                    "retry_count": retry_count + 1,
                    "result": attempt_info["verify_result"],
                    "message": attempt_info["message"],
                    "diagnosis": attempt_info.get("diagnosis"),
                    "fix_plan": attempt_info.get("fix_plan")
                })
                
                if retry_count < self.DEFAULT_MAX_RETRY_COUNT - 1:
                    time.sleep(self.DEFAULT_RETRY_INTERVAL)
                    print(f"[CUA] ⏳ 等待{self.DEFAULT_RETRY_INTERVAL}秒后重试...")
            
            error_message = f"执行失败，连续重试{self.DEFAULT_MAX_RETRY_COUNT}次仍未成功"
            retry_context["final_message"] = error_message
            
            self.history_states.append({
                "step": "execution_failed",
                "timestamp": time.time(),
                "error": error_message,
                "retry_context": copy.deepcopy(retry_context)
            })
            
            print(f"\n[CUA] 💥 {error_message}")
            raise CuaOperationException(
                message=error_message,
                context=retry_context
            )
            
        except CuaOperationException as e:
            return CuaResponse(
                success=False,
                message=str(e),
                history_states=copy.deepcopy(self.history_states)
            )
            
        except Exception as e:
            return CuaResponse(
                success=False,
                message=f"执行失败: {str(e)}",
                history_states=copy.deepcopy(self.history_states)
            )
