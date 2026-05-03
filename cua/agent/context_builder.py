"""
上下文构建器，负责构建Agent对话上下文
"""
from typing import List, Dict, Any
from ..prompts.system_prompts import build_feedback_prompt, FEISHU_SYSTEM_PROMPT


class ContextBuilder:
    @staticmethod
    def build_initial_messages(task_goal: str, system_prompt: str = FEISHU_SYSTEM_PROMPT) -> List[Dict[str, Any]]:
        """
        构建初始对话上下文
        :param task_goal: 任务目标描述
        :param system_prompt: 系统提示词，默认使用飞书系统提示词
        :return: 初始消息列表
        """
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_goal}
        ]
        
    @staticmethod
    def build_next_step_message(current_goal: str, action_summary: List[str], feedback: str, b64_img: str) -> Dict[str, Any]:
        """
        构建下一步的反馈消息
        :param current_goal: 当前任务目标
        :param action_summary: 已执行步骤摘要
        :param feedback: 上一步执行反馈
        :param b64_img: 最新截图Base64（带data前缀）
        :return: 下一步消息结构体
        """
        text_prompt = build_feedback_prompt(current_goal, action_summary, feedback)
        if b64_img:
            return {
                "role": "user", 
                "content": [
                    {"type": "text", "text": text_prompt},
                    {"type": "image_url", "image_url": {"url": b64_img}}
                ]
            }
        return {"role": "user", "content": text_prompt}
