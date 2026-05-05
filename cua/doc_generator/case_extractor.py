"""
文档驱动用例生成器（对齐参考项目实现）
从飞书云文档自动提取可测功能点，批量生成DSL测试用例
"""
import re
from typing import List, Dict, Any, Optional
from ..models.llm_client import post_chat_completion


class DocumentCaseExtractor:
    """文档案例提取器 - 从飞书文档提取可测功能点"""
    
    def __init__(self, llm_request_func=None):
        self.llm_request = llm_request_func
        self.feature_extraction_prompt = """
        你是飞书功能点提取专家。请分析以下飞书产品文档内容，提取出所有可自动化的测试功能点。
        
        【提取规则】
        1. 只提取用户可操作的功能点（如：点击、输入、查看、发送等）
        2. 忽略纯说明性内容（如：介绍、背景、原理等）
        3. 优先提取高频使用的核心功能
        4. 每个功能点要包含：操作对象、操作动作、预期结果
        
        【输出格式】
        返回JSON格式，字段说明：
        - feature_name: 功能名称
        - operation: 操作描述
        - expected_result: 预期结果
        - difficulty: 难度等级(L1/L2/L3)
        - tags: 标签数组，如["im", "message", "basic"]
        
        【示例】
        文档内容：用户可以点击左侧导航栏的日历图标查看日程安排
        输出：{"feature_name": "查看日历", "operation": "点击左侧导航栏的日历图标", "expected_result": "日历界面打开，显示当前月份日程", "difficulty": "L1", "tags": ["calendar", "view", "basic"]}
        
        文档内容：{doc_content}
        """
    
    def extract_from_document(self, doc_url_or_content: str, product: str = "im", levels: List[str] = ["L1", "L2"]) -> List[Dict[str, Any]]:
        """
        从文档提取可测功能点
        :param doc_url_or_content: 文档URL或内容
        :param product: 产品线
        :param levels: 难度等级过滤
        :return: 功能点列表
        """
        # 这里应该调用飞书API读取文档内容，为简化演示直接处理内容
        if doc_url_or_content.startswith("http"):
            # 实际项目中应通过飞书API获取文档内容
            doc_content = self._fetch_document_content(doc_url_or_content)
        else:
            doc_content = doc_url_or_content
        
        # 提取功能点
        features = self._extract_testable_features(doc_content, product, levels)
        return features
    
    def _fetch_document_content(self, doc_url: str) -> str:
        """获取飞书文档内容（实际项目中调用飞书API）"""
        # 模拟API调用
        return f"飞书{doc_url.split('/')[-1]}文档内容示例：用户可以点击左侧导航栏的图标进行相应操作"
    
    def _extract_testable_features(self, doc_content: str, product: str, levels: List[str] = ["L1", "L2"]) -> List[Dict[str, Any]]:
        """从文档内容提取可测功能点"""
        # 使用更宽松的正则表达式提取功能点（实际项目中应使用LLM）
        feature_patterns = [
            # 用户可以...实现...（最常用的模式）
            r"用户可以(.+?)\s*(?:以|来|实现|进行|完成|执行)\s*(.+?)(?:\s*[，。！!?？]|$)",
            # 点击...可以...（最常用的模式）
            r"点击(.+?)\s*(?:可以|能够|实现|支持|完成|执行)\s*(.+?)(?:\s*[，。！!?？]|$)",
            # 在...中可以...（最常用的模式）
            r"在(.+?)\s+中\s*(?:可以|支持|能够|实现|完成|执行)\s+(.+?)(?:\s*[，。！!?？]|$)",
            # 支持...功能（最常用的模式）
            r"支持(.+?)\s*(?:功能|操作|能力|服务)(?:\s*[，。！!?？]|$)",
            # 允许...操作（最常用的模式）
            r"允许(.+?)\s*(?:操作|功能|能力|执行)(?:\s*[，。！!?？]|$)",
            # 提供...功能（最常用的模式）
            r"提供(.+?)\s*(?:功能|服务|能力|操作)(?:\s*[，。！!?？]|$)",
            # 包含...功能
            r"包含(.+?)\s*(?:功能|操作|能力|服务)(?:\s*[，。！!?？]|$)",
            # 包括...功能
            r"包括(.+?)\s*(?:功能|操作|能力|服务)(?:\s*[，。！!?？]|$)",
            # 简化模式：直接提取动词+名词
            r"([点击|查看|打开|关闭|创建|发送|编辑|删除|设置|分享|搜索|切换]+)(.+?)(?:\s*[，。！!?？]|$)"
        ]
        
        features = []
        for pattern in feature_patterns:
            matches = re.findall(pattern, doc_content, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    if len(match) == 1:
                        # 只匹配到一个组，作为操作描述
                        operation = match[0].strip()
                        result = f"执行{operation}操作"
                    elif len(match) >= 2:
                        # 匹配到两个组
                        operation = match[0].strip()
                        result = match[1].strip()
                    else:
                        # 多个组，取前两个
                        operation = match[0].strip()
                        result = "".join(match[1:]).strip()
                else:
                    # 非元组，直接作为操作
                    operation = str(match).strip()
                    result = f"执行{operation}操作"
                
                # 清理操作和结果中的多余字符
                operation = operation.replace("、", "").replace("，", "").strip()
                result = result.replace("、", "").replace("，", "").strip()
                
                # 简单判断难度等级
                if any(keyword in operation for keyword in ["点击", "查看", "打开", "关闭", "切换", "选择", "搜索"]):
                    difficulty = "L1"
                elif any(keyword in operation for keyword in ["创建", "发送", "编辑", "删除", "设置", "分享", "邀请"]):
                    difficulty = "L2"
                else:
                    difficulty = "L3"
                
                if difficulty in levels:
                    features.append({
                        "feature_name": f"{operation}{result}",
                        "operation": operation,
                        "expected_result": result,
                        "difficulty": difficulty,
                        "tags": [product, "auto-generated"]
                    })
        
        return features