from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import time
import uuid

class MemoryType(str, Enum):
    """记忆类型枚举"""
    ACTION = "action"           # 操作动作记忆
    OBSERVATION = "observation" # 屏幕观察结果记忆
    GOAL = "goal"               # 任务目标记忆
    EXPERIENCE = "experience"   # 经验教训记忆
    FAILURE = "failure"         # 失败案例记忆
    SUCCESS = "success"         # 成功案例记忆

@dataclass
class MemoryItem:
    """记忆条目数据结构"""
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType = MemoryType.ACTION
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5  # 重要性分数 0-1，越高越重要
    embedding: Optional[List[float]] = None  # 向量嵌入，用于语义检索
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "context": self.context,
            "importance": self.importance,
            "embedding": self.embedding
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryItem":
        """从字典加载记忆条目"""
        data["memory_type"] = MemoryType(data["memory_type"])
        return cls(**data)
