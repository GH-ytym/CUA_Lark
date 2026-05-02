import time
import logging
from typing import Callable, Any
from ..operators.action_executor import execute_parsed_actions, parse_action_json
from ..perception.screen_capture import capture_screen_base64
from ..report.logger import RunLogger
from .context_builder import ContextBuilder

class AgentLoopRunner:
    def __init__(self, logger: RunLogger, llm_request_func: Callable):
        self.logger = logger
        self.llm_request = llm_request_func
        self.action_summary = []
        self.step_count = 0
        
    def run(self, current_goal: str, max_steps: int = 15) -> bool:
        self.step_count = 0
        self.action_summary = []
        
        # 初始截屏
        b64_img = capture_screen_base64()
        self.logger.save_screenshot(b64_img, self.step_count)
        
        messages = ContextBuilder.build_initial_messages(current_goal)
        if b64_img:
            messages[-1]["content"] = [
                {"type": "text", "text": current_goal},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
            ]
            
        while self.step_count < max_steps:
            self.step_count += 1
            logging.info(f"--- Step {self.step_count} ---")
            
            # 1. 脑: 推理
            model_reply = self.llm_request(messages)
            
            # 解析动作组为 dict 列表
            actions = parse_action_json(model_reply)
                
            # 3. 手: 执行解析出的动作列表字典
            res = execute_parsed_actions(actions)
            
            # 4. 眼: 等待并反馈
            time.sleep(1.0)
            b64_img = capture_screen_base64()
            if b64_img:
                b64_img=f"data:image/jpeg;base64,{b64_img}"
            img_path = self.logger.save_screenshot(b64_img, self.step_count)
            
            if res["success"]:
                feedback = "执行成功"
                if res["executed_actions"]:
                    self.action_summary.extend(res["executed_actions"])
            else:
                feedback = f"⚠️ 动作失败: {res['error']}"

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
                return True

        logging.warning("达到了最大循环步数限制。")
        return False
