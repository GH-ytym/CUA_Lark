import time
import logging
from typing import Callable, Any
from ..operators.action_executor import execute_parsed_actions, parse_action_json
from ..perception.screen_capture import capture_screen_base64
from ..report.logger import RunLogger
from .context_builder import ContextBuilder
from ..memory import global_memory, MemoryType

class AgentLoopRunner:
    def __init__(self, logger: RunLogger, llm_request_func: Callable):
        self.logger = logger
        self.llm_request = llm_request_func
        self.action_summary = []
        self.step_count = 0
        
    def run(self, current_goal: str, max_steps: int = 15) -> bool:
        self.step_count = 0
        self.action_summary = []
        
        # 加载最新的本地记忆
        global_memory._load_from_disk()
        
        # 初始截屏
        b64_img = capture_screen_base64()
        self.logger.save_screenshot(b64_img, self.step_count)
        
        messages = ContextBuilder.build_initial_messages(current_goal)
        if b64_img:
            # 初始请求包含完整记忆上下文
            memory_content = global_memory.format_for_prompt(15)
            messages[-1]["content"] = [
                #{"type": "text", "text": f"{current_goal}\n\n{global_memory.format_for_prompt(10)}"},
                {"type": "text", "text": f"{current_goal}\n\n{memory_content}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
            ]
        
        # 记录任务目标记忆
        global_memory.add_memory(
            memory_type=MemoryType.GOAL,
            content=f"开始执行任务: {current_goal}",
            importance=0.8
        )
            
        while self.step_count < max_steps:
            self.step_count += 1
            logging.info(f"--- Step {self.step_count} ---")
            
            # 1. 脑: 推理
            model_reply = self.llm_request(messages)
            
            # 解析动作组为 dict 列表
            actions = parse_action_json(model_reply)
            actions, deferred_completion = self._defer_premature_completion(actions)
                
            # 3. 手: 执行解析出的动作列表字典
            res = execute_parsed_actions(actions)
            
            # 记录动作记忆
            for action in res["executed_actions"]:
                global_memory.add_memory(
                    memory_type=MemoryType.ACTION,
                    content=action,
                    context={"success": res["success"], "step": self.step_count},
                    importance=0.6
                )
            
            # 如果执行失败，记录失败记忆
            if not res["success"]:
                global_memory.add_memory(
                    memory_type=MemoryType.FAILURE,
                    content=f"动作执行失败: {res.get('error', '未知错误')}",
                    context={"actions": actions, "step": self.step_count},
                    importance=0.9
                )
            
            # 4. 眼: 等待并反馈
            time.sleep(1.0)
            b64_img = capture_screen_base64()
            
            # 记录观察结果记忆
            if b64_img:
                global_memory.add_memory(
                    memory_type=MemoryType.OBSERVATION,
                    content="获取当前屏幕截图",
                    context={"has_image": True},
                    importance=0.4
                )
            if b64_img:
                b64_img=f"data:image/jpeg;base64,{b64_img}"
            img_path = self.logger.save_screenshot(b64_img, self.step_count)
            
            if res["success"]:
                feedback = "执行成功"
                if res["executed_actions"]:
                    self.action_summary.extend(res["executed_actions"])
            else:
                feedback = f"⚠️ 动作失败: {res['error']}"
            if deferred_completion:
                feedback += "\n系统检测到本轮同时包含界面操作和完成信号，已忽略提前完成，请根据最新截图继续确认。"

            # 记录到报告
            self.logger.log_step({
                "step": self.step_count,
                "model_output": model_reply,
                "success": res["success"],
                "actions": res["executed_actions"],
                "screenshot": img_path
            })

            # 更新上下文
            messages = [messages[0]]  # 保留 System Prompt
            next_msg = ContextBuilder.build_next_step_message(current_goal, self.action_summary, feedback, b64_img)
            messages.append(next_msg)

            # 2. 判: 是否停止 (精确判断动作字典)
            is_done = any(isinstance(a, dict) and str(a.get("action", "")).upper() == "DONE" for a in actions)
            if is_done:
                self.logger.log_step({
                    "step": self.step_count, "action": "DONE", "output": model_reply
                })
                # 记录任务成功记忆
                global_memory.add_memory(
                    memory_type=MemoryType.SUCCESS,
                    content=f"任务完成: {current_goal}",
                    context={"steps": self.step_count, "actions": self.action_summary},
                    importance=0.9
                )
                return True

        logging.warning("达到了最大循环步数限制。")
        return False

    @staticmethod
    def _defer_premature_completion(actions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        """Force one screenshot verification pass after real UI actions before accepting DONE."""
        if not AgentLoopRunner._has_ui_actions(actions) or not AgentLoopRunner._has_done(actions):
            return actions, False

        filtered: list[dict[str, Any]] = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            cmd = str(action.get("action", "")).upper()
            if cmd == "DONE":
                continue
            if cmd == "REPLY" and AgentLoopRunner._looks_like_final_reply(str(action.get("text", ""))):
                continue
            filtered.append(action)
        return filtered, True

    @staticmethod
    def _has_done(actions: list[dict[str, Any]]) -> bool:
        return any(isinstance(action, dict) and str(action.get("action", "")).upper() == "DONE" for action in actions)

    @staticmethod
    def _has_ui_actions(actions: list[dict[str, Any]]) -> bool:
        ui_actions = {"CLICK", "DOUBLE_CLICK", "MOVE", "INPUT", "PRESS", "SCROLL", "HOTKEY", "WAIT"}
        return any(
            isinstance(action, dict) and str(action.get("action", "")).upper() in ui_actions
            for action in actions
        )

    @staticmethod
    def _looks_like_final_reply(text: str) -> bool:
        normalized = str(text).strip().lower()
        final_markers = (
            "已成功",
            "任务完成",
            "完成。",
            "完成",
            "已发送",
            "发送完成",
            "success",
            "done",
        )
        return any(marker in normalized for marker in final_markers)
