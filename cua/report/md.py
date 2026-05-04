"""
Markdown报告生成器
生成结构化的测试执行报告
"""
import os
import time
from typing import Dict, Any, List


class MdReportGenerator:
    """MD报告生成器"""
    
    def __init__(self):
        self.assets_dir = "assets/reports"
        os.makedirs(self.assets_dir, exist_ok=True)
    
    def generate(self, test_results: Dict[str, Any]) -> str:
        """
        生成MD格式报告
        :param test_results: 测试执行结果
        :return: MD内容字符串
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        md_content = f"""# CUA 测试执行报告

**生成时间**: {timestamp}

## 执行概览
- 测试ID: {test_results.get('test_id', 'Unknown')}
- 开始时间: {test_results.get('start_time', 'N/A')}
- 结束时间: {test_results.get('end_time', 'N/A')}
- 成功率: {test_results.get('success_rate', 0)*100:.1f}%
- 总用例数: {test_results.get('total_cases', 0)}
- 通过用例: {test_results.get('passed_cases', 0)}
- 失败用例: {test_results.get('failed_cases', 0)}

## 详细结果
"""
        
        details = test_results.get("details", [])
        for detail in details:
            case_id = detail.get("case_id", "Unknown")
            success = detail.get("success", False)
            status = "✅" if success else "❌"
            steps = detail.get("steps", 0)
            time_spent = detail.get("time_spent", 0)
            
            md_content += f"\n### {status} 用例: {case_id}\n"
            md_content += f"- 执行步数: {steps}\n"
            md_content += f"- 耗时: {time_spent}s\n"
            
            if not success:
                error_msg = detail.get("error", "Unknown error")
                md_content += f"- 错误信息: {error_msg}\n"
            
            # 添加截图链接（如果有的话）
            screenshots = detail.get("screenshots", [])
            if screenshots:
                md_content += "- 执行截图:\n"
                for i, screenshot in enumerate(screenshots, 1):
                    md_content += f"  - ![Step {i}]({screenshot})\n"
        
        return md_content
    
    def save_report(self, content: str, filename: str = None) -> str:
        """保存报告到文件"""
        if not filename:
            timestamp = int(time.time())
            filename = f"report_{timestamp}.md"
        
        filepath = os.path.join(self.assets_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        
        return filepath