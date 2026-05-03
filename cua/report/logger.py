import os
import json
from datetime import datetime
import base64

class RunLogger:
    def __init__(self, task_id: str, task_name: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(
            os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 
            "runs", 
            f"{timestamp}_{task_id}"
        )
        os.makedirs(self.run_dir, exist_ok=True)
        self.steps_file = os.path.join(self.run_dir, "steps.jsonl")

    def get_run_dir(self):
        return self.run_dir

    def log_step(self, step_data: dict):
        step_data["timestamp"] = datetime.now().isoformat()
        with open(self.steps_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(step_data, ensure_ascii=False) + "\n")

    def save_screenshot(self, b64_img: str, step_id: int) -> str:
        if not b64_img:
            return ""
        img_path = os.path.join(self.run_dir, f"step_{step_id}.jpg")
        try:
            img_data = base64.b64decode(b64_img)
            with open(img_path, "wb") as f:
                f.write(img_data)
            return img_path
        except Exception as e:
            print(f"Failed to save screenshot: {e}")
            return ""
