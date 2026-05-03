from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass
class ExpectedResult:
    type: str
    value: Any

@dataclass
class TestCase:
    task_id: str
    task_name: str
    module: str
    intent: str
    params: Dict[str, Any]
    expected_result: ExpectedResult
    preconditions: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TestCase':
        expected_result_data = data.get("expected_result", {})
        expected_result = ExpectedResult(
            type=expected_result_data.get("type", "unknown"),
            value=expected_result_data.get("value", "")
        )
        return cls(
            task_id=data.get("task_id", ""),
            task_name=data.get("task_name", ""),
            module=data.get("module", ""),
            intent=data.get("intent", ""),
            params=data.get("params", {}),
            expected_result=expected_result,
            preconditions=data.get("preconditions", [])
        )
