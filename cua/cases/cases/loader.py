import json
import os
from .schema import TestCase

class TestCaseLoader:
    @staticmethod
    def load_from_file(file_path: str) -> TestCase:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Test case file not found: {file_path}")
            
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        return TestCase.from_dict(data)
