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
        self.used_memory_ids = []
        self.written_memory_ids = []
        self.memory_scope = {}
        
    def run(
        self,
        current_goal: str,
        max_steps: int = 15,
        memory_scope: dict[str, Any] | None = None,
        fallback_context: dict[str, Any] | None = None,
    ) -> bool:
        self.step_count = 0
        self.action_summary = []
        self.used_memory_ids = []
        self.written_memory_ids = []
        self.memory_scope = memory_scope or {}
        fallback_context = fallback_context or {}
        
        # 初始截屏
        b64_img = capture_screen_base64()
        self.logger.save_screenshot(b64_img, self.step_count)
        
        messages = ContextBuilder.build_initial_messages(current_goal)
        prompt_memories = global_memory.get_recent_memories(10, scope=self.memory_scope)
        self.used_memory_ids = [memory.memory_id for memory in prompt_memories]
        memory_prompt = global_memory.format_for_prompt(10, scope=self.memory_scope)
        if b64_img:
            messages[-1]["content"] = [
                {"type": "text", "text": f"{current_goal}\n\n{memory_prompt}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
            ]
        
        # 记录任务目标记忆
        goal_memory = global_memory.add_memory(
            memory_type=MemoryType.GOAL,
            content=f"开始执行任务: {current_goal}",
            context={
                **self.memory_scope,
                **fallback_context,
                "used_memory_ids": self.used_memory_ids,
            },
            importance=0.8
        )
        self.written_memory_ids.append(goal_memory.memory_id)
            
        while self.step_count < max_steps:
            self.step_count += 1
            logging.info(f"--- Step {self.step_count} ---")
            
            # 1. 脑: 推理
            model_reply = self.llm_request(messages)
            
            # 解析动作组为 dict 列表
            actions = parse_action_json(model_reply)
                
            # 3. 手: 执行解析出的动作列表字典
            res = execute_parsed_actions(actions)
            
            # 记录动作记忆
            for action in res["executed_actions"]:
                action_memory = global_memory.add_memory(
                    memory_type=MemoryType.ACTION,
                    content=action,
                    context={
                        **self.memory_scope,
                        **fallback_context,
                        "success": res["success"],
                        "step": self.step_count,
                    },
                    importance=0.6
                )
                self.written_memory_ids.append(action_memory.memory_id)
            
            # 如果执行失败，记录失败记忆
            if not res["success"]:
                failure_memory = global_memory.add_memory(
                    memory_type=MemoryType.FAILURE,
                    content=f"动作执行失败: {res.get('error', '未知错误')}",
                    context={
                        **self.memory_scope,
                        **fallback_context,
                        "actions": actions,
                        "step": self.step_count,
                    },
                    importance=0.9
                )
                self.written_memory_ids.append(failure_memory.memory_id)
            
            # 4. 眼: 等待并反馈
            time.sleep(1.0)
            b64_img = capture_screen_base64()
            
            # 记录观察结果记忆
            if b64_img:
                observation_memory = global_memory.add_memory(
                    memory_type=MemoryType.OBSERVATION,
                    content="获取当前屏幕截图",
                    context={
                        **self.memory_scope,
                        **fallback_context,
                        "has_image": True,
                        "step": self.step_count,
                    },
                    importance=0.4
                )
                self.written_memory_ids.append(observation_memory.memory_id)
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
                # 记录任务成功记忆
                success_memory = global_memory.add_memory(
                    memory_type=MemoryType.SUCCESS,
                    content=f"任务完成: {current_goal}",
                    context={
                        **self.memory_scope,
                        **fallback_context,
                        "steps": self.step_count,
                        "actions": self.action_summary,
                    },
                    importance=0.9
                )
                self.written_memory_ids.append(success_memory.memory_id)
                return True

        logging.warning("达到了最大循环步数限制。")
        return False
