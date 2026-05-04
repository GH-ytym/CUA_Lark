from typing import List, Dict, Any
import yaml
from pathlib import Path

class DocumentCaseExtractor:
    """从文档中提取可测试功能点并生成DSL用例"""
    
    def __init__(self, lark_api_key: str = None):
        self.lark_api_key = lark_api_key
    
    def extract_from_url(self, doc_url: str, levels: List[str] = ["L1", "L2"]) -> List[Dict[str, Any]]:
        """从飞书文档URL提取功能点"""
        # 这里简化实现，实际项目中会调用飞书API解析文档内容
        mock_features = self._extract_testable_features("mock document content", levels)
        return self._generate_dsl_cases(mock_features)
    
    def _extract_testable_features(self, doc_content: str, product: str, levels: List[str] = ["L1", "L2"]) -> List[Dict[str, Any]]:
        """从文档内容中提取可测试的功能点
        Args:
            doc_content: 文档文本内容
            product: 产品名称（im/calendar/doc等）
            levels: 提取的功能点等级，默认L1(核心)、L2(重要)
        """
        # 简化实现，返回模拟的功能点
        return [
            {
                "id": "FEAT_001",
                "name": "发送消息功能",
                "description": "用户可以给其他用户发送文本消息",
                "level": "L1",
                "preconditions": ["用户已登录飞书", "存在联系人test_01"],
                "steps": ["打开聊天窗口", "输入消息内容", "点击发送按钮"],
                "expected": "消息发送成功，出现在聊天记录中"
            },
            {
                "id": "FEAT_002",
                "name": "消息已读状态",
                "description": "消息发送后可以查看对方是否已读",
                "level": "L2",
                "preconditions": ["用户已发送消息给test_01"],
                "steps": ["查看消息状态"],
                "expected": "显示已读/未读状态正确"
            }
        ]
    
    def _generate_dsl_cases(self, features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将功能点转换为DSL用例格式"""
        dsl_cases = []
        for feat in features:
            dsl_case = {
                "case_id": f"CASE_{feat['id']}",
                "product": "im",
                "name": feat["name"],
                "description": feat["description"],
                "preconditions": feat["preconditions"],
                "actions": [
                    {"type": "click", "target": f"{step}", "description": step} 
                    for step in feat["steps"]
                ],
                "verifications": [
                    {"type": "ui_check", "target": "聊天记录", "expected": feat["expected"]}
                ],
                "checkpoints": [{"step": len(feat["steps"]), "description": "验证操作结果"}]
            }
            dsl_cases.append(dsl_case)
        return dsl_cases
    
    def save_to_yaml(self, dsl_cases: List[Dict[str, Any]], output_path: str):
        """将生成的DSL用例保存为YAML文件"""
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump_all(dsl_cases, f, allow_unicode=True, sort_keys=False)
