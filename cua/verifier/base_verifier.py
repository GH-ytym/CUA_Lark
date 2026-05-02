from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseVerifier(ABC):
    """验证器抽象基类，所有验证器都需要继承此类"""
    @abstractmethod
    def verify(self, expected_result: Any, context: Dict[str, Any]) -> bool:
        """
        验证操作结果是否符合预期
        :param expected_result: 预期结果，可以是字符串、结构体等
        :param context: 上下文信息，包含截图、执行历史等
        :return: 验证通过返回True，失败返回False
        """
        pass
