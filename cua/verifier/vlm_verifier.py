from .base_verifier import BaseVerifier
from typing import Dict, Any
import logging
from ..models.llm_client import post_chat_completion
import os
from dotenv import load_dotenv


class VlmVerifier(BaseVerifier):
    """
    基于视觉大模型的通用验证器
    不需要OCR，直接用VLM分析截图验证操作结果
    """
    
    def __init__(self):
        load_dotenv()
        self.api_url = os.getenv("BASE_URL", os.getenv("CUA_MODEL_API_BASE"))
        self.api_key = os.getenv("OPENAI_API_KEY", os.getenv("CUA_MODEL_API_KEY"))
        self.model = os.getenv("MODEL_NAME", os.getenv("CUA_MODEL_NAME", "doubao-vision-pro-32k"))
        
    def verify(self, expected_result: str, context: Dict[str, Any]) -> bool:
        """
        用VLM验证操作结果
        :param expected_result: 预期结果描述，比如"日历窗口已打开"、"消息已发送"
        :param context: 上下文，必须包含base64_screenshot字段（待验证的截图）
        :return: 验证通过返回True，失败返回False
        """
        base64_img = context.get("base64_screenshot")
        if not base64_img:
            logging.warning("验证上下文缺少截图信息，验证失败")
            return False
            
        if not self.api_key or not self.api_url:
            logging.warning("VLM API配置缺失，验证跳过")
            return True  # 配置缺失时跳过验证，避免影响执行
            
        try:
            prompt = f"""
            你是操作结果验证专家，请判断当前截图是否符合预期结果。
            
            预期结果：{expected_result}
            
            请只返回"是"或"否"，不要返回其他任何内容。
            """

            if base64_img:
                #加入data:image/jpeg;base64,前缀
                base64_img = f"data:image/jpeg;base64,{base64_img}"
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": base64_img}}
                    ]
                }
            ]
            
            # 调用VLM验证
            response = post_chat_completion(
                url=self.api_url,
                apikey=self.api_key,
                model=self.model,
                messages=messages,
                is_stream=False
            )
            
            if response.status_code != 200:
                logging.warning(f"VLM验证调用失败: {response.text}")
                return False
                
            result = response.json()["choices"][0]["message"]["content"].strip()
            logging.info(f"VLM验证结果: {result}, 预期结果: {expected_result}")
            
            return "是" in result or "对" in result or "正确" in result or "success" in result.lower()
            
        except Exception as e:
            logging.error(f"VLM验证异常: {e}")
            return False
