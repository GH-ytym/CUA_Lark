from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import yaml
from pathlib import Path

class CasePriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"

class CaseStatus(str, Enum):
    NOT_RUN = "not_run"
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"

@dataclass
class BenchmarkCase:
    """Benchmark测试用例结构"""
    case_id: str
    product: str
    name: str = ""
    description: str = ""
    instruction: Optional[str] = None
    expected_result: Optional[str] = None
    priority: CasePriority = CasePriority.P1
    tags: List[str] = field(default_factory=list)
    level: str = "L2"
    preconditions: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    verifications: List[Dict[str, Any]] = field(default_factory=list)
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    post_conditions: List[Dict[str, Any]] = field(default_factory=list)
    expected_duration: int = 60  # 预计执行时间秒
    
    @classmethod
    def from_yaml(cls, yaml_path: str) -> "BenchmarkCase":
        """从YAML文件加载用例，自动补全必填字段"""
        import time
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        # 自动补全必填字段，兼容生成的DSL格式
        if "case_id" not in data:
            # 从meta提取或自动生成
            if "meta" in data and "source_instruction" in data["meta"]:
                data["case_id"] = f"DSL_{int(time.time())}"
            else:
                data["case_id"] = f"AUTO_{int(time.time())}"
        
        if "product" not in data:
            # 从meta提取或使用默认值
            if "meta" in data and "product" in data["meta"]:
                data["product"] = data["meta"]["product"]
            else:
                data["product"] = "unknown"
        
        if "name" not in data or not data["name"]:
            data["name"] = data.get("instruction", data.get("description", "未命名用例"))
        
        if "description" not in data or not data["description"]:
            data["description"] = data.get("instruction", data.get("name", "无描述"))
        
        return cls(**data)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "case_id": self.case_id,
            "name": self.name,
            "product": self.product,
            "description": self.description,
            "priority": self.priority.value,
            "tags": self.tags,
            "level": self.level,
            "preconditions": self.preconditions,
            "actions": self.actions,
            "verifications": self.verifications,
            "checkpoints": self.checkpoints,
            "expected_duration": self.expected_duration
        }

@dataclass
class BenchmarkResult:
    """Benchmark执行结果"""
    case_id: str
    status: CaseStatus
    start_time: float
    end_time: float
    duration: float
    error_message: Optional[str] = None
    screenshots: List[str] = field(default_factory=list)
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    ai_analysis: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "error_message": self.error_message,
            "screenshots": self.screenshots,
            "step_results": self.step_results,
            "ai_analysis": self.ai_analysis
        }
