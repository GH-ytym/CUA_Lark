"""
DSL生成器模块
将自然语言指令转换为结构化的YAML DSL测试用例
"""
import json
import re
from typing import Dict, Any, Optional
from pydantic import BaseModel


class DslGenerator:
    """DSL生成器 - 将自然语言转换为YAML DSL"""
    
    def __init__(self):
        # UI提示词模板，用于帮助VLM更准确识别界面元素
        self.ui_hints_template = {
            "im": [
                "飞书IM界面左侧导航栏包含：消息、通讯录、日历、文档、云盘、工作台等图标",
                "聊天界面顶部显示聊天对象名称，下方是消息列表，底部是输入框",
                "输入框左侧是表情、文件、语音等按钮，右侧是发送按钮"
            ],
            "calendar": [
                "日历界面左侧是日程列表，右侧是日历网格视图",
                "顶部有年月选择器、今日按钮、新建日程按钮",
                "日程事件以彩色块状显示在对应日期格子中"
            ],
            "docs": [
                "文档界面顶部是菜单栏，左侧是文档树，中央是编辑区域",
                "编辑区域上方有格式工具栏，包含字体、样式、插入等选项",
                "右上角有分享、协作、历史版本等按钮"
            ]
        }
        
        # CLI验证模板，用于结构化验证执行结果
        self.cli_verifications_template = {
            "send_message": {
                "command": "im_message",
                "params": {"keyword": "<<MESSAGE_CONTENT>>", "sender": "<<SENDER>>"},
                "assertion": "exists"
            },
            "create_calendar": {
                "command": "calendar_event",
                "params": {"title": "<<EVENT_TITLE>>", "date": "<<EVENT_DATE>>"},
                "assertion": "exists"
            },
            "create_doc": {
                "command": "drive_doc",
                "params": {"title": "<<DOC_TITLE>>", "owner": "<<OWNER>>"},
                "assertion": "exists"
            }
        }
    
    def from_natural_language(self, instruction: str, product: str = "im", difficulty: str = "L1") -> str:
        """
        将自然语言指令转换为YAML DSL
        :param instruction: 自然语言指令，如"给张三发送消息说下午三点开会"
        :param product: 产品线，如im/docs/calendar/mail
        :param difficulty: 难度等级，如L1/L2/L3
        :return: YAML格式的DSL内容
        """
        # 1. 解析指令意图
        parsed_intent = self._parse_instruction(instruction)
        
        # 2. 生成UI提示词
        ui_hints = self._generate_ui_hints(product, parsed_intent)
        
        # 3. 生成动作序列
        actions = self._generate_actions(parsed_intent, product)
        
        # 4. 生成验证点
        verifications = self._generate_verifications(parsed_intent, product)
        
        # 5. 生成检查点
        checkpoints = self._generate_checkpoints(parsed_intent, product)
        
        # 6. 组装为YAML DSL
        dsl_yaml = self._assemble_dsl(
            instruction=instruction,
            product=product,
            difficulty=difficulty,
            ui_hints=ui_hints,
            actions=actions,
            verifications=verifications,
            checkpoints=checkpoints
        )
        
        return dsl_yaml
    
    def _parse_instruction(self, instruction: str) -> Dict[str, Any]:
        """解析自然语言指令，提取关键信息"""
        # 简单的关键词匹配解析（实际项目中可以用LLM解析）
        instruction_lower = instruction.lower()
        
        # 提取动作类型
        if any(word in instruction_lower for word in ["发送", "发消息", "说"]):
            action_type = "send_message"
        elif any(word in instruction_lower for word in ["点击", "打开", "查看"]):
            action_type = "click_element"
        elif any(word in instruction_lower for word in ["输入", "填写", "搜索"]):
            action_type = "input_text"
        else:
            action_type = "general"
        
        # 提取目标对象
        target_match = re.search(r"(张三|李四|王五|日历|文档|消息|搜索|设置)", instruction)
        target = target_match.group(1) if target_match else "unknown"
        
        # 提取具体内容
        content_match = re.search(r'(?:说|告诉|内容是)[\'""]([^\'""]+)[\'""]|说\s+(.+?)(?:\s|$)', instruction)
        content = content_match.group(1) if content_match else ""
        
        return {
            "action_type": action_type,
            "target": target,
            "content": content,
            "raw_instruction": instruction
        }
    
    def _generate_ui_hints(self, product: str, parsed_intent: Dict[str, Any]) -> list:
        """生成UI提示词，帮助VLM更准确识别界面元素"""
        hints = self.ui_hints_template.get(product, [])
        
        # 根据具体意图添加针对性提示
        if parsed_intent["action_type"] == "send_message":
            hints.append("当前任务是发送消息，重点关注聊天输入框和发送按钮")
        elif parsed_intent["action_type"] == "click_element":
            hints.append(f"当前任务是点击{parsed_intent['target']}，请找到对应的界面元素")
        elif parsed_intent["action_type"] == "input_text":
            hints.append("当前任务是输入文本，需要找到合适的输入框")
            
        return hints
    
    def _generate_actions(self, parsed_intent: Dict[str, Any], product: str) -> list:
        """生成动作序列"""
        actions = []
        
        if parsed_intent["action_type"] == "send_message":
            # 示例：给张三发消息
            actions = [
                {
                    "action": "click",
                    "description": f"点击联系人列表中的'{parsed_intent['target']}'",
                    "x": 100,  # VLM识别的坐标
                    "y": 200,
                    "confidence": 0.95
                },
                {
                    "action": "input",
                    "description": f"在输入框输入内容: {parsed_intent['content']}",
                    "text": parsed_intent["content"],
                    "confidence": 0.98
                },
                {
                    "action": "click",
                    "description": "点击发送按钮",
                    "x": 800,
                    "y": 600,
                    "confidence": 0.96
                }
            ]
        elif parsed_intent["action_type"] == "click_element":
            actions = [
                {
                    "action": "click",
                    "description": f"点击{parsed_intent['target']}元素",
                    "x": 150,  # VLM识别的坐标
                    "y": 300,
                    "confidence": 0.92
                }
            ]
        elif parsed_intent["action_type"] == "input_text":
            actions = [
                {
                    "action": "click",
                    "description": "激活输入框",
                    "x": 400,
                    "y": 400,
                    "confidence": 0.90
                },
                {
                    "action": "input",
                    "description": f"输入文本: {parsed_intent['content']}",
                    "text": parsed_intent["content"],
                    "confidence": 0.97
                }
            ]
        
        return actions
    
    def _generate_verifications(self, parsed_intent: Dict[str, Any], product: str) -> list:
        """生成CLI验证点"""
        verifications = []
        
        if parsed_intent["action_type"] == "send_message":
            verifications = [
                {
                    "type": "cli",
                    "command": "im_message",
                    "params": {
                        "keyword": parsed_intent["content"],
                        "recipient": parsed_intent["target"]
                    },
                    "assertion": "exists",
                    "description": f"验证消息'{parsed_intent['content']}'是否已发送给{parsed_intent['target']}"
                },
                {
                    "type": "visual",
                    "condition": f"消息气泡包含'{parsed_intent['content']}'",
                    "description": "验证界面上是否显示已发送的消息"
                }
            ]
        elif parsed_intent["action_type"] == "click_element":
            verifications = [
                {
                    "type": "visual",
                    "condition": f"界面跳转到{parsed_intent['target']}页面",
                    "description": f"验证点击{parsed_intent['target']}后是否成功跳转"
                }
            ]
        
        return verifications
    
    def _generate_checkpoints(self, parsed_intent: Dict[str, Any], product: str) -> list:
        """生成检查点"""
        checkpoints = []
        
        if parsed_intent["action_type"] == "send_message":
            checkpoints = [
                {
                    "name": "消息发送成功",
                    "condition": f"消息'{parsed_intent['content']}'出现在聊天记录中",
                    "screenshot": True,
                    "description": "确认消息已成功发送并显示在聊天记录中"
                },
                {
                    "name": "对方已读状态",
                    "condition": "消息状态变为已读",
                    "screenshot": True,
                    "description": "可选检查点：确认对方已阅读消息"
                }
            ]
        elif parsed_intent["action_type"] == "click_element":
            checkpoints = [
                {
                    "name": "页面跳转成功",
                    "condition": f"当前页面为{parsed_intent['target']}界面",
                    "screenshot": True,
                    "description": f"确认点击{parsed_intent['target']}后成功跳转到目标页面"
                }
            ]
        
        return checkpoints
    
    def _assemble_dsl(self, instruction: str, product: str, difficulty: str, 
                     ui_hints: list, actions: list, verifications: list, checkpoints: list) -> str:
        """组装为YAML DSL格式"""
        import yaml
        
        dsl_data = {
            "meta": {
                "version": "1.0",
                "product": product,
                "difficulty": difficulty,
                "generated_at": "__TIMESTAMP__",
                "source_instruction": instruction
            },
            "context": {
                "ui_hints": ui_hints,
                "pre_conditions": [
                    f"飞书{product}界面已打开",
                    "网络连接正常",
                    "目标元素可访问"
                ]
            },
            "actions": actions,
            "verifications": verifications,
            "checkpoints": checkpoints,
            "post_conditions": [
                "任务目标达成",
                "界面状态符合预期"
            ]
        }
        
        # 生成YAML内容
        yaml_content = yaml.dump(dsl_data, default_flow_style=False, allow_unicode=True, indent=2)
        
        # 替换时间戳占位符
        import time
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        yaml_content = yaml_content.replace("__TIMESTAMP__", timestamp)
        
        return yaml_content