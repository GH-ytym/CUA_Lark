from typing import List, Dict, Any, Optional
import os
import time
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from .schema import BenchmarkCase, BenchmarkResult, CaseStatus
from ..agent.loop_runner import AgentLoopRunner
from ..report.logger import RunLogger

class BenchmarkRunner:
    """Benchmark运行器，支持用例过滤、批量执行、结果汇总"""
    
    def __init__(self, cases_dir: str = "benchmark_cases", output_dir: str = "benchmark_output"):
        self.cases_dir = Path(cases_dir)
        self.output_dir = Path(output_dir)
        # 加载环境变量和LLM配置
        load_dotenv()
        self.client = OpenAI(
            api_key=os.getenv("CUA_MODEL_API_KEY"),
            base_url=os.getenv("CUA_MODEL_API_BASE")
        )
        self.model_name = os.getenv("CUA_MODEL_NAME", "ep-20260423222752-9tcpw")
        self._init_dirs()
    
    def _llm_request_func(self, messages) -> str:
        """LLM请求函数，复用test_cua中的实现"""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            max_tokens=2000,
            temperature=0.0
        )
        return response.choices[0].message.content.strip()
    
    def _init_dirs(self):
        """初始化目录结构"""
        self.cases_dir.mkdir(exist_ok=True, parents=True)
        self.output_dir.mkdir(exist_ok=True, parents=True)
    
    def load_cases(self, 
                  product: Optional[str] = None,
                  level: Optional[str] = None,
                  tags: Optional[List[str]] = None,
                  case_ids: Optional[List[str]] = None) -> List[BenchmarkCase]:
        """加载并过滤测试用例"""
        all_cases = []
        for yaml_file in self.cases_dir.glob("**/*.yaml"):
            case = BenchmarkCase.from_yaml(str(yaml_file))
            all_cases.append(case)
        
        # 过滤条件
        filtered = all_cases
        if product:
            filtered = [c for c in filtered if c.product == product]
        if level:
            filtered = [c for c in filtered if c.level == level]
        if tags:
            filtered = [c for c in filtered if any(tag in c.tags for tag in tags)]
        if case_ids:
            filtered = [c for c in filtered if c.case_id in case_ids]
        
        return filtered
    
    def run_case(self, case: BenchmarkCase, run_id: str) -> BenchmarkResult:
        """运行单个测试用例（使用AgentLoopRunner，对齐test_cua的执行逻辑）"""
        start_time = time.time()
        case_output_dir = self.output_dir / run_id / case.case_id
        case_output_dir.mkdir(exist_ok=True, parents=True)
        
        try:
            # 从DSL中提取执行目标，优先级：meta.source_instruction > instruction > description > name
            execute_goal = case.name
            if case.description:
                execute_goal = case.description
            if case.instruction:
                execute_goal = case.instruction
            if case.meta and 'source_instruction' in case.meta:
                execute_goal = case.meta['source_instruction']
            
            print(f"▶️  执行用例 [{case.case_id}]: {execute_goal}")
            
            # 初始化AgentLoopRunner，和test_cua使用完全相同的逻辑（参数对齐）
            logger = RunLogger(
                f"benchmark_{run_id}",
                execute_goal
            )
            runner = AgentLoopRunner(logger, self._llm_request_func)
            
            # 执行用例，最多10步
            success = runner.run(
                current_goal=execute_goal,
                max_steps=10
            )
            
            status = CaseStatus.PASS if success else CaseStatus.FAIL
            error_msg = None if success else "执行未完成或步骤失败"
            step_count = runner.step_count
            action_summary = runner.action_summary
            
        except Exception as e:
            status = CaseStatus.FAIL
            error_msg = str(e)
            step_count = 0
            action_summary = []
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 收集截图
        screenshots = [str(p) for p in case_output_dir.glob("**/*.png")]
        
        # 构造步骤结果
        step_results = [
            {"step": i+1, "description": action, "success": True} 
            for i, action in enumerate(action_summary)
        ]
        
        return BenchmarkResult(
            case_id=case.case_id,
            status=status,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            error_message=error_msg,
            screenshots=screenshots,
            step_results=step_results
        )
    
    def run(self, 
            product: Optional[str] = None,
            level: Optional[str] = None,
            tags: Optional[List[str]] = None,
            case_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """运行符合条件的所有用例"""
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        cases = self.load_cases(product, level, tags, case_ids)
        
        results = []
        pass_count = 0
        fail_count = 0
        
        for case in cases:
            result = self.run_case(case, run_id)
            results.append(result)
            if result.status == CaseStatus.PASS:
                pass_count += 1
            else:
                fail_count += 1
        
        # 保存汇总结果
        summary = {
            "run_id": run_id,
            "start_time": time.time(),
            "end_time": time.time(),
            "total_cases": len(cases),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "pass_rate": pass_count / len(cases) if cases else 0,
            "results": [r.to_dict() for r in results]
        }
        
        summary_path = self.output_dir / run_id / "summary.yaml"
        with open(summary_path, "w", encoding="utf-8") as f:
            yaml.dump(summary, f, allow_unicode=True, sort_keys=False)
        
        return summary
    
    def run_single_case(self, case_file_path: str) -> Dict[str, Any]:
        """运行单个YAML用例文件"""
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        case = BenchmarkCase.from_yaml(case_file_path)
        result = self.run_case(case, run_id)
        return result.to_dict()
