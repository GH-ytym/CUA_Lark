import json
import os
from datetime import datetime

class ReportGenerator:
    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        self.report_file = os.path.join(run_dir, "final_report.json")

    def generate_report(self, test_case, passed: bool, total_steps: int, time_spent: float, fail_reason: str = None):
        report_data = {
            "generated_at": datetime.now().isoformat(),
            "task_id": getattr(test_case, 'task_id', 'unknown'),
            "task_name": getattr(test_case, 'task_name', 'unknown'),
            "result": "PASS" if passed else "FAIL",
            "total_steps": total_steps,
            "time_spent_seconds": round(time_spent, 2),
            "fail_reason": fail_reason or ""
        }
        
        with open(self.report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
            
        return self.report_file
