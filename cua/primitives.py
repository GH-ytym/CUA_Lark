import pyautogui
import win32gui
import win32con
import win32process
import pyperclip
from typing import Dict, Optional, Tuple
import time
import os

pyautogui.FAILSAFE = True

_user_activity_detected: bool = False


def detect_user_activity() -> bool:
    global _user_activity_detected
    return _user_activity_detected


def reset_user_activity_flag() -> None:
    global _user_activity_detected
    _user_activity_detected = False


def is_foreground_window(hwnd: int) -> bool:
    return win32gui.GetForegroundWindow() == hwnd


def focus_and_maximize(app_identifier: str = "飞书", match_by: str = "title") -> Tuple[bool, Optional[int]]:
    """
    将指定应用窗口强制置顶并最大化（使用Win32 API实现）
    :param app_identifier: 应用识别标识
    :param match_by: 匹配方式：title(窗口标题), process_name(进程名), class_name(窗口类名)
    :return: (操作成功返回True，失败返回False, 匹配到的窗口句柄)
    """
    target_hwnd = None
    
    def window_enum_callback(hwnd, extra):
        nonlocal target_hwnd
        if win32gui.IsWindowVisible(hwnd):
            try:
                if match_by == "title":
                    window_title = win32gui.GetWindowText(hwnd)
                    if app_identifier in window_title:
                        target_hwnd = hwnd
                        return False
                elif match_by == "class_name":
                    class_name = win32gui.GetClassName(hwnd)
                    if app_identifier == class_name:
                        target_hwnd = hwnd
                        return False
                elif match_by == "process_name":
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    handle = win32process.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
                    exe_path = win32process.GetModuleFileNameEx(handle, 0)
                    exe_name = os.path.basename(exe_path)
                    if app_identifier.lower() == exe_name.lower():
                        target_hwnd = hwnd
                        return False
            except Exception:
                pass
        return True
    
    try:
        win32gui.EnumWindows(window_enum_callback, None)
        
        if not target_hwnd:
            return False, None
        
        if win32gui.IsIconic(target_hwnd):
            win32gui.SendMessage(target_hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
            time.sleep(0.2)
        
        win32gui.SetForegroundWindow(target_hwnd)
        win32gui.BringWindowToTop(target_hwnd)
        
        win32gui.SetWindowPos(
            target_hwnd,
            win32con.HWND_TOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
        time.sleep(0.1)
        win32gui.SetWindowPos(
            target_hwnd,
            win32con.HWND_NOTOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
        
        win32gui.ShowWindow(target_hwnd, win32con.SW_MAXIMIZE)
        time.sleep(0.3)
        
        if not is_foreground_window(target_hwnd):
            return False, target_hwnd
            
        return True, target_hwnd
    except Exception:
        return False, None


def verify_window_focus(expected_hwnd: int) -> bool:
    return is_foreground_window(expected_hwnd)


def safe_click(x: int, y: int, clicks: int = 1, interval: float = 0.2,
               expected_hwnd: Optional[int] = None) -> bool:
    """
    安全点击方法，使用比例坐标(0-1000)体系，对齐成熟方案
    VLM输出比例坐标，执行时通过pyautogui.size()换算为绝对屏幕坐标
    :param x: 比例横坐标（0-1000范围，基于屏幕宽度的比例）
    :param y: 比例纵坐标（0-1000范围，基于屏幕高度的比例）
    :param clicks: 点击次数，默认1次
    :param interval: 多次点击之间的间隔时间，默认0.2秒
    :param expected_hwnd: 预期操作的窗口句柄，提供会先验证窗口焦点
    :return: 操作成功返回True
    """
    try:
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，点击操作取消")
            
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，点击操作取消")
        
        screen_width, screen_height = pyautogui.size()
        real_x = int(x * screen_width / 1000)
        real_y = int(y * screen_height / 1000)
        
        pyautogui.click(x=real_x, y=real_y, clicks=clicks, interval=interval)
        time.sleep(0.1)
        
        return True
    except Exception as e:
        raise RuntimeError(f"点击操作失败: {str(e)}") from e


def safe_double_click(x: int, y: int,
                      expected_hwnd: Optional[int] = None) -> bool:
    """
    安全双击方法，使用比例坐标(0-1000)体系
    :param x: 比例横坐标（0-1000范围）
    :param y: 比例纵坐标（0-1000范围）
    :param expected_hwnd: 预期操作的窗口句柄
    :return: 操作成功返回True
    """
    try:
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，双击操作取消")
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，双击操作取消")
        
        screen_width, screen_height = pyautogui.size()
        real_x = int(x * screen_width / 1000)
        real_y = int(y * screen_height / 1000)
        
        pyautogui.doubleClick(x=real_x, y=real_y)
        time.sleep(0.1)
        
        return True
    except Exception as e:
        raise RuntimeError(f"双击操作失败: {str(e)}") from e


def safe_move(x: int, y: int,
              expected_hwnd: Optional[int] = None) -> bool:
    """
    安全移动鼠标方法，使用比例坐标(0-1000)体系
    :param x: 比例横坐标（0-1000范围）
    :param y: 比例纵坐标（0-1000范围）
    :param expected_hwnd: 预期操作的窗口句柄
    :return: 操作成功返回True
    """
    try:
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，移动操作取消")
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，移动操作取消")
        
        screen_width, screen_height = pyautogui.size()
        real_x = int(x * screen_width / 1000)
        real_y = int(y * screen_height / 1000)
        
        pyautogui.moveTo(x=real_x, y=real_y, duration=0.25)
        time.sleep(0.1)
        
        return True
    except Exception as e:
        raise RuntimeError(f"移动操作失败: {str(e)}") from e


def safe_input(text: str, expected_hwnd: Optional[int] = None) -> bool:
    """
    安全输入中文文本，使用剪贴板复制粘贴方式避免乱码
    :param text: 需要输入的文本内容
    :param expected_hwnd: 预期操作的窗口句柄
    :return: 操作成功返回True
    """
    if not text:
        return True
    
    try:
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，输入操作取消")
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，输入操作取消")
        
        original_clipboard = pyperclip.paste()
        
        try:
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.2)
            return True
        finally:
            pyperclip.copy(original_clipboard)
            
    except Exception as e:
        raise RuntimeError(f"文本输入失败: {str(e)}") from e


def safe_press(key: str, expected_hwnd: Optional[int] = None) -> bool:
    """
    安全按下按键
    :param key: 按键名称，如 enter, esc, tab, backspace
    :param expected_hwnd: 预期操作的窗口句柄
    :return: 操作成功返回True
    """
    try:
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，按键操作取消")
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，按键操作取消")
        
        pyautogui.press(key.lower())
        time.sleep(0.1)
        
        return True
    except Exception as e:
        raise RuntimeError(f"按键操作失败: {str(e)}") from e


def safe_scroll(clicks: int, direction: str = "down", expected_hwnd: Optional[int] = None) -> bool:
    """
    安全滚动鼠标滚轮
    :param clicks: 滚动次数
    :param direction: 滚动方向：up/down
    :param expected_hwnd: 预期操作的窗口句柄
    :return: 操作成功返回True
    """
    try:
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，滚动操作取消")
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，滚动操作取消")
            
        scroll_amount = clicks if direction == "up" else -clicks
        pyautogui.scroll(scroll_amount)
        time.sleep(0.2)
        
        return True
    except Exception as e:
        raise RuntimeError(f"滚动操作失败: {str(e)}") from e


def safe_hotkey(*keys: str, expected_hwnd: Optional[int] = None) -> bool:
    """
    安全按下快捷键组合
    :param keys: 快捷键组合，如('ctrl', 'c')
    :param expected_hwnd: 预期操作的窗口句柄
    :return: 操作成功返回True
    """
    try:
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，快捷键操作取消")
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，快捷键操作取消")
            
        pyautogui.hotkey(*keys)
        time.sleep(0.2)
        
        return True
    except Exception as e:
        raise RuntimeError(f"快捷键操作失败: {str(e)}") from e


def save_state_for_backtrack(current_state: Dict) -> Dict:
    """
    保存当前状态用于回溯，使用copy()防止引用污染
    :param current_state: 当前状态字典
    :return: 拷贝后的状态字典
    """
    try:
        return current_state.copy()
    except Exception as e:
        raise RuntimeError(f"状态保存失败: {str(e)}") from e
