"""
DSL评估器模块
对生成的DSL进行五维度评分：UI准确性、可执行性、可验证性、难度评级、完整性
"""
from typing import Dict, Any, List
import json


class DslEvaluator:
    """DSL评估器 - 对DSL质量进行五维度评分"""
    
    def __init__(self):
        # 评分标准定义
        self.scoring_criteria = {
            "ui_accuracy": {
                "name": "UI准确性",
                "description": "UI提示词是否准确描述了界面元素和布局",
                "weight": 0.25,
                "max_score": 2
            },
            "executability": {
                "name": "可执行性", 
                "description": "动作序列是否可按顺序执行，无逻辑冲突或依赖问题",
                "weight": 0.25,
                "max_score": 2
            },
            "verifiability": {
                "name": "可验证性",
                "description": "验证点是否能客观判断任务是否成功完成",
                "weight": 0.20,
                "max_score": 2
            },
            "difficulty": {
                "name": "难度评级",
                "description": "难度等级是否与实际步骤复杂度匹配",
                "weight": 0.15,
                "max_score": 2
            },
            "completeness": {
                "name": "完整性",
                "description": "是否包含所有必要字段，无缺失关键信息",
                "weight": 0.15,
                "max_score": 2
            }
        }
    
    def evaluate(self, dsl_content: str, product: str = "im") -> Dict[str, int]:
        """
        对DSL内容进行五维度评分
        :param dsl_content: YAML格式的DSL内容
        :param product: 产品线，用于针对性评估
        :return: 评分字典，如 {"ui_accuracy": 2, "executability": 1, ...}
        """
        try:
            import yaml
            dsl_data = yaml.safe_load(dsl_content)
        except Exception as e:
            raise ValueError(f"DSL内容格式错误，无法解析: {str(e)}")
        
        scores = {}
        
        # 1. UI准确性评分
        scores["ui_accuracy"] = self._evaluate_ui_accuracy(dsl_data, product)
        
        # 2. 可执行性评分  
        scores["executability"] = self._evaluate_executability(dsl_data)
        
        # 3. 可验证性评分
        scores["verifiability"] = self._evaluate_verifiability(dsl_data)
        
        # 4. 难度评级评分
        scores["difficulty"] = self._evaluate_difficulty_rating(dsl_data)
        
        # 5. 完整性评分
        scores["completeness"] = self._evaluate_completeness(dsl_data)
        
        return scores
    
    def _evaluate_ui_accuracy(self, dsl_data: Dict[str, Any], product: str) -> int:
        """评估UI准确性（0-2分）"""
        context = dsl_data.get("context", {})
        ui_hints = context.get("ui_hints", [])
        
        if not ui_hints:
            return 0  # 无UI提示词，准确性差
        
        # 检查UI提示词是否包含产品特异性信息
        product_related_hints = [hint for hint in ui_hints if product.lower() in hint.lower()]
        
        if len(product_related_hints) == 0:
            return 0  # 无产品相关提示，准确性差
        
        # 检查提示词是否具体（包含坐标、元素类型等）
        specific_hints = [hint for hint in ui_hints if any(keyword in hint.lower() for keyword in ["左侧", "顶部", "按钮", "输入框", "导航栏"])]
        
        if len(specific_hints) >= 2:
            return 2  # 具体且相关
        elif len(specific_hints) >= 1:
            return 1  # 有一定具体性
        else:
            return 1  # 有产品相关但不够具体
    
    def _evaluate_executability(self, dsl_data: Dict[str, Any]) -> int:
        """评估可执行性（0-2分）"""
        actions = dsl_data.get("actions", [])
        
        if not actions:
            return 0  # 无动作，不可执行
        
        # 检查动作格式是否正确
        valid_actions = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            if "action" not in action:
                continue
            # 检查必要字段
            action_type = action["action"].upper()
            if action_type == "CLICK":
                if "x" not in action or "y" not in action:
                    continue
            elif action_type == "INPUT":
                if "text" not in action:
                    continue
            valid_actions.append(action)
        
        if len(valid_actions) == 0:
            return 0  # 无有效动作
        
        if len(valid_actions) == len(actions):
            return 2  # 所有动作都有效
        elif len(valid_actions) >= len(actions) * 0.8:
            return 1  # 大部分动作有效
        else:
            return 0  # 有效动作太少
    
    def _evaluate_verifiability(self, dsl_data: Dict[str, Any]) -> int:
        """评估可验证性（0-2分）"""
        verifications = dsl_data.get("verifications", [])
        
        if not verifications:
            return 0  # 无验证点，无法验证
        
        # 检查验证点是否具体可衡量
        specific_verifications = []
        for v in verifications:
            if not isinstance(v, dict):
                continue
            # CLI验证需要command和assertion
            if v.get("type") == "cli":
                if v.get("command") and v.get("assertion"):
                    specific_verifications.append(v)
            # 视觉验证需要condition
            elif v.get("type") == "visual":
                if v.get("condition"):
                    specific_verifications.append(v)
        
        if len(specific_verifications) >= 2:
            return 2  # 多个具体验证点
        elif len(specific_verifications) >= 1:
            return 1  # 有具体验证点
        else:
            return 0  # 验证点不具体
    
    def _evaluate_difficulty_rating(self, dsl_data: Dict[str, Any]) -> int:
        """评估难度评级（0-2分）"""
        meta = dsl_data.get("meta", {})
        expected_difficulty = meta.get("difficulty", "L1")
        actions = dsl_data.get("actions", [])
        
        # 根据动作数量评估难度
        action_count = len(actions)
        if expected_difficulty == "L1":
            if action_count <= 3:
                return 2  # 难度匹配
            elif action_count <= 5:
                return 1  # 略复杂但仍属L1
            else:
                return 0  # 过于复杂，难度评级偏低
        elif expected_difficulty == "L2":
            if 3 <= action_count <= 7:
                return 2  # 难度匹配
            elif action_count <= 10 or action_count >= 2:
                return 1  # 基本匹配
            else:
                return 0  # 难度过高或过低
        elif expected_difficulty == "L3":
            if action_count >= 5:
                return 2  # 难度匹配
            elif action_count >= 3:
                return 1  # 有一定复杂度
            else:
                return 0  # 过于简单，难度评级过高
        
        return 1  # 默认中等
    
    def _evaluate_completeness(self, dsl_data: Dict[str, Any]) -> int:
        """评估完整性（0-2分）"""
        required_fields = ["meta", "actions", "verifications", "checkpoints"]
        missing_fields = [field for field in required_fields if field not in dsl_data]
        
        if missing_fields:
            return 0  # 缺少必要字段
        
        # 检查meta字段完整性
        meta = dsl_data["meta"]
        meta_required = ["product", "difficulty", "source_instruction"]
        missing_meta = [field for field in meta_required if field not in meta]
        
        if missing_meta:
            return 1  # 基本完整但有缺失
        
        # 检查context字段（可选但推荐）
        context = dsl_data.get("context", {})
        has_preconditions = "pre_conditions" in context and len(context["pre_conditions"]) > 0
        has_ui_hints = "ui_hints" in context and len(context["ui_hints"]) > 0
        
        if has_preconditions and has_ui_hints:
            return 2  # 非常完整
        elif has_preconditions or has_ui_hints:
            return 1  # 基本完整
        else:
            return 1  # 核心完整但缺少上下文信息
    
    def get_detailed_evaluation(self, dsl_content: str, product: str = "im") -> Dict[str, Any]:
        """获取详细评估报告"""
        scores = self.evaluate(dsl_content, product)
        
        # 计算加权总分
        weighted_score = 0
        for dim, score in scores.items():
            weight = self.scoring_criteria[dim]["weight"]
            weighted_score += score * weight
            
        # 生成评价
        if weighted_score >= 1.6:
            level = "优秀"
        elif weighted_score >= 1.0:
            level = "良好" 
        elif weighted_score >= 0.6:
            level = "一般"
        else:
            level = "较差"
        
        return {
            "scores": scores,
            "weighted_score": round(weighted_score, 2),
            "overall_level": level,
            "evaluation_details": {
                dim: {
                    "name": self.scoring_criteria[dim]["name"],
                    "description": self.scoring_criteria[dim]["description"],
                    "score": score,
                    "max_score": self.scoring_criteria[dim]["max_score"]
                } for dim, score in scores.items()
            }
        }