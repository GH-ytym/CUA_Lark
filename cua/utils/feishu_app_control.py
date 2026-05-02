"""
飞书应用控制工具（严格对齐参考项目实现）
"""
import win32gui
import win32con
import win32process
import time
from typing import Tuple, Optional


def focus_and_maximize(app_identifier: str = "飞书", match_by: str = "title") -> Tuple[bool, Optional[int]]:
    """
    将指定应用窗口强制置顶并最大化（原有功能，保留对外接口）
    :param app_identifier: 应用识别标识
    :param match_by: 匹配方式：title/process_name/class_name
    :return: (是否成功, 窗口句柄)
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
        
        # 恢复窗口
        if win32gui.IsIconic(target_hwnd):
            win32gui.SendMessage(target_hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
            time.sleep(0.2)
        
        # 前置窗口
        win32gui.SetForegroundWindow(target_hwnd)
        win32gui.BringWindowToTop(target_hwnd)
        
        # 置顶然后取消置顶
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
        
        # 最大化
        win32gui.ShowWindow(target_hwnd, win32con.SW_MAXIMIZE)
        time.sleep(0.3)
        
        # 验证焦点
        if win32gui.GetForegroundWindow() != target_hwnd:
            return False, target_hwnd
            
        return True, target_hwnd
    except Exception as e:
        return False, None


def is_foreground_window(hwnd: int) -> bool:
    """检查窗口是否在前台"""
    return win32gui.GetForegroundWindow() == hwnd


def get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """获取窗口客户区坐标"""
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        left, top = win32gui.ClientToScreen(hwnd, (left, top))
        right, bottom = win32gui.ClientToScreen(hwnd, (right, bottom))
        return left, top, right, bottom
    except Exception:
        return None


# 兼容原有接口
activate_feishu = focus_and_maximize
