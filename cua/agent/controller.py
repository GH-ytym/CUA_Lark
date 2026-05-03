import time
import logging
from ..cases.cases.loader import TestCaseLoader
from ..cases.cases.schema import TestCase
from ..report.logger import RunLogger
from ..report.report_generator import ReportGenerator
from .loop_runner import AgentLoopRunner

class AgentController:
    def __init__(self, llm_request_func: callable):
        self.llm_request_func = llm_request_func
        
    def run_test_case(self, case_file: str) -> str:
        case = TestCaseLoader.load_from_file(case_file)
        logger = RunLogger(case.task_id, case.task_name)
        report_gen = ReportGenerator(logger.get_run_dir())
        
        logging.info(f"Start running case: {case.task_name} at {logger.get_run_dir()}")
        start_time = time.time()
        
        # 构建初始目标
        current_goal = f"任务：{case.intent}. 参数：{case.params}"
        
        # 初始化循环执行器并运行
        runner = AgentLoopRunner(logger, self.llm_request_func)
        try:
            finished = runner.run(current_goal)
        except Exception as e:
            logging.error(f"Agent loop failed: {e}")
            finished = False
            
        time_spent = time.time() - start_time
        
        # TODO: 集成 Verifier
        # passed = IMVerifier().verify(case.expected_result, {"screenshot": "TODO"})
        passed = finished # 临时
        
        report_file = report_gen.generate_report(
            case, passed, runner.step_count, time_spent, 
            fail_reason=None if passed else "Agent did not finish gracefully"
        )
        
        logging.info(f"Test finished. Report generated at {report_file}")
        return report_file
