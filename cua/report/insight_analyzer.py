"""
AI洞察分析器
使用大模型分析测试执行结果，生成改进建议
"""
from typing import Dict, Any, List
from ..models.llm_client import post_chat_completion


class InsightAnalyzer:
    """AI洞察分析器"""
    
    def __init__(self, llm_request_func=None):
        self.llm_request = llm_request_func or post_chat_completion
        self.analysis_prompt = """
        你是飞书自动化测试分析专家。请分析以下测试执行结果，生成有价值的洞察和改进建议。

        【测试结果数据】
        {test_results_json}

        【分析维度】
        1. 执行成功率分析：识别成功率高低的模式
        2. 失败原因分析：归纳常见失败类型和根本原因
        3. 性能瓶颈分析：识别耗时较长的操作类型
        4. 改进建议：针对发现的问题提出具体优化方案

        【输出格式】
        请返回JSON格式，字段说明：
        - success_patterns: 成功率高的用例特征
        - failure_patterns: 常见失败模式及原因
        - performance_issues: 性能瓶颈分析
        - improvement_suggestions: 具体改进建议
        - risk_warnings: 潜在风险预警

        不要返回其他任何内容。
        """
    
    def analyze(self, test_results: Dict[str, Any]) -> List[str]:
        """
        分析测试结果，生成洞察建议
        :param test_results: 测试执行结果
        :return: 洞察建议列表
        """
        import json
        prompt = self.analysis_prompt.format(test_results_json=json.dumps(test_results, ensure_ascii=False, indent=2))
        
        try:
            response = self.llm_request([
                {"role": "user", "content": prompt}
            ])
            
            # 解析返回的JSON
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                analysis_data = json.loads(json_match.group(1))
                
                suggestions = []
                for key, value in analysis_data.items():
                    if isinstance(value, list):
                        suggestions.extend([str(item) for item in value])
                    elif isinstance(value, str):
                        suggestions.append(value)
                    elif isinstance(value, dict):
                        suggestions.append(json.dumps(value, ensure_ascii=False))
                
                return suggestions
            else:
                # 如果不是JSON格式，直接返回原始内容
                return [response[:200] + "..." if len(response) > 200 else response]
                
        except Exception as e:
            return [f"分析失败: {str(e)}"]