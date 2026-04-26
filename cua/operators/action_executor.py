"""
动作执行器模块（对齐成熟方案的比例坐标体系）
坐标体系：VLM/提示词输出比例坐标(0-1000)，执行时统一换算为绝对屏幕坐标
"""
import re
import json
import time
import logging
import pyautogui
from typing import List, Dict, Any

pyautogui.FAILSAFE = True
HAS_PYAUTOGUI = True

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


def parse_action_json(text: str) -> List[Dict[str, Any]]:
    """
    从大模型返回文本中可靠提取动作 JSON，统一序列化为标准动作对象字典列表
    """
    actions = []
    
    json_blocks = re.findall(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_blocks:
        try:
            parsed = json.loads(json_blocks[-1])
            if isinstance(parsed, dict): return [parsed]
            if isinstance(parsed, list): return parsed
        except Exception:
            pass
            
    array_match = re.search(r'(\[\s*\{.*?\}\s*\])', text, re.DOTALL)
    if array_match:
        try:
            parsed = json.loads(array_match.group(1))
            if isinstance(parsed, dict): return [parsed]
            if isinstance(parsed, list): return parsed
        except Exception:
            pass
            
    legacy_pattern = r"\[ACTION:\s*([^\]]+)\]|\[INPUT\](.*?)\[/INPUT\]"
    matches = list(re.finditer(legacy_pattern, text, re.DOTALL))
    for match in matches:
        if match.group(1):
            act = match.group(1).strip()
            parts = act.split(" ", 1)
            cmd = parts[0].upper()
            arg = parts[1].strip() if len(parts) > 1 else ""
            if cmd in ["CLICK", "DOUBLE_CLICK", "MOVE"]:
                try:
                    c = [int(c.strip()) for c in arg.replace(",", " ").split()]
                    if len(c) >= 2:
                        actions.append({"action": cmd, "x": c[0], "y": c[1]})
                except Exception:
                    pass
            elif cmd == "PRESS":
                actions.append({"action": "PRESS", "key": arg.lower()})
            elif cmd == "TYPE":
                actions.append({"action": "INPUT", "text": arg})
            elif cmd == "DONE":
                actions.append({"action": "DONE"})
        elif match.group(2):
            actions.append({"action": "INPUT", "text": match.group(2)})

    return actions


def execute_parsed_actions(actions: List[Dict[str, Any]], hwnd: int = None) -> Dict[str, Any]:
    """
    按规范的 JSON 动作字典列表有序执行驱动 PyAutoGUI
    坐标体系：统一使用比例坐标(0-1000)，通过 pyautogui.size() 换算为绝对屏幕坐标
    """
    res = {
        "success": False,
        "logs": "",
        "executed_actions": [],
        "error": ""
    }

    if not HAS_PYAUTOGUI:
        res["error"] = "缺少底层依赖: pyautogui 未安装，无法执行鼠标键盘操作。"
        res["logs"] = "❌ " + res["error"]
        return res
        
    if not actions:
        res["success"] = True
        res["logs"] = "ℹ️ 未解析到任何系统动作指令。"
        return res
        
    screen_width, screen_height = pyautogui.size()
    log_messages = [f"🚀 —— 开始执行标准化动作组 (分辨率: {screen_width}x{screen_height}) —— 🚀"]
    
    for act in actions:
        if not isinstance(act, dict): continue
        try:
            cmd = str(act.get("action", "")).upper()
            
            if hwnd:
                import win32gui
                if win32gui.GetForegroundWindow() != hwnd:
                    raise RuntimeError("目标窗口失去焦点，操作取消")
            
            if cmd == "CLICK":
                x, y = int(act.get("x", 0)), int(act.get("y", 0))
                real_x = int(x * screen_width / 1000)
                real_y = int(y * screen_height / 1000)
                pyautogui.click(x=real_x, y=real_y)
                log_messages.append(f"✅ 执行 -> 点击鼠标: 比例({x}, {y}) -> 绝对({real_x}, {real_y})")
                res["executed_actions"].append(f"点击 {real_x},{real_y}")
                
            elif cmd == "DOUBLE_CLICK":
                x, y = int(act.get("x", 0)), int(act.get("y", 0))
                real_x = int(x * screen_width / 1000)
                real_y = int(y * screen_height / 1000)
                pyautogui.doubleClick(x=real_x, y=real_y)
                log_messages.append(f"✅ 执行 -> 双击: 比例({x}, {y}) -> 绝对({real_x}, {real_y})")
                res["executed_actions"].append(f"双击 {real_x},{real_y}")

            elif cmd == "MOVE":
                x, y = int(act.get("x", 0)), int(act.get("y", 0))
                real_x = int(x * screen_width / 1000)
                real_y = int(y * screen_height / 1000)
                pyautogui.moveTo(x=real_x, y=real_y, duration=0.25)
                log_messages.append(f"✅ 执行 -> 移动鼠标: 比例({x}, {y}) -> 绝对({real_x}, {real_y})")
                res["executed_actions"].append(f"鼠标移动至 {real_x},{real_y}")

            elif cmd == "INPUT":
                text_input = act.get("text", "")
                if HAS_PYPERCLIP:
                    pyperclip.copy(text_input)
                    pyautogui.hotkey('ctrl', 'v')
                    display_t = text_input.replace('\n', ' ')
                    log_messages.append(f"✅ 执行 -> 剪贴板输入文字: {display_t[:30]}...")
                    res["executed_actions"].append(f"剪贴板输入内容: {display_t[:30]}")
                else:
                    pyautogui.write(text_input, interval=0.01)
                    log_messages.append(f"✅ 执行 -> 降级输入法输入: {text_input[:30]}...")
                    res["executed_actions"].append(f"键入内容: {text_input[:30]}")
                    
            elif cmd == "PRESS":
                key = str(act.get("key", "")).lower()
                pyautogui.press(key)
                log_messages.append(f"✅ 执行 -> 敲击按键: {key}")
                res["executed_actions"].append(f"敲击 {key}")
                
            elif cmd == "REPLY":
                text_msg = act.get("text", "")
                log_messages.append(f"💬 执行 -> 助手播报: {text_msg}")
                res["executed_actions"].append(f"向用户播报: {text_msg}")
                if "replies" not in res:
                    res["replies"] = []
                res["replies"].append(text_msg)
                
            elif cmd == "DONE":
                log_messages.append(f"✅ 捕获 -> [DONE] 停止执行旗标")
                
            else:
                log_messages.append(f"⚠️ 忽略未知指令: {act}")

            time.sleep(0.5)
            
        except Exception as e:
            res["success"] = False
            res["error"] = f"动作指令[{act}]执行失败: {str(e)}"
            log_messages.append(f"❌中断: {res['error']}")
            res["logs"] = "\n".join(log_messages)
            return res
            
    log_messages.append("🏁 —— 动作序列处理完毕 —— 🏁")
    res["success"] = True
    res["logs"] = "\n".join(log_messages)
    return res


def execute_actions_from_text(text: str, hwnd: int = None) -> Dict[str, Any]:
    """包装函数兼容老代码"""
    actions = parse_action_json(text)
    return execute_parsed_actions(actions, hwnd)
