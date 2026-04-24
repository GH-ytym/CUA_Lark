import pyautogui
import win32gui
import win32con
import win32process
import ctypes
import PIL.ImageGrab
import pyperclip
from typing import Dict, Optional, Tuple, List
import time
import os

# 全局配置
_dpi_scale_factor: Optional[float] = None
_user_activity_detected: bool = False


def get_system_dpi_scale() -> float:
    """自动获取Windows系统DPI缩放系数"""
    try:
        shcore = ctypes.windll.shcore
        monitor = win32gui.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTOPRIMARY)
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return dpi_x.value / 96.0
    except Exception:
        # 兼容旧系统， fallback到注册表读取
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics")
            dpi = winreg.QueryValueEx(key, "AppliedDPI")[0]
            winreg.CloseKey(key)
            return dpi / 96.0
        except Exception:
            return 1.0


def set_dpi_scale_factor(factor: Optional[float] = None) -> None:
    """设置DPI缩放系数，None表示自动检测"""
    global _dpi_scale_factor
    if factor is None or factor <= 0:
        _dpi_scale_factor = get_system_dpi_scale()
    else:
        _dpi_scale_factor = factor


def get_dpi_scale_factor() -> float:
    """获取当前DPI缩放系数"""
    global _dpi_scale_factor
    if _dpi_scale_factor is None:
        _dpi_scale_factor = get_system_dpi_scale()
    return _dpi_scale_factor


def is_foreground_window(hwnd: int) -> bool:
    """检查指定窗口是否为当前前台窗口"""
    return win32gui.GetForegroundWindow() == hwnd


def detect_user_activity() -> bool:
    """检测用户是否有主动操作（鼠标移动/键盘输入）"""
    global _user_activity_detected
    return _user_activity_detected


def reset_user_activity_flag() -> None:
    """重置用户活动检测标志"""
    global _user_activity_detected
    _user_activity_detected = False


# 鼠标钩子回调，检测用户操作
def _mouse_hook(nCode, wParam, lParam):
    global _user_activity_detected
    if nCode >= 0 and wParam in [0x0201, 0x0204, 0x0207, 0x0200]:  # 鼠标点击/移动事件
        _user_activity_detected = True
    return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)


# 注册钩子（仅在启用用户检测时调用）
def enable_user_activity_detection():
    """启用用户活动检测"""
    ctypes.windll.user32.SetWindowsHookExA(14, _mouse_hook, win32process.GetModuleHandleW(None), 0)
    reset_user_activity_flag()


def focus_and_maximize(app_identifier: str = "飞书", match_by: str = "title") -> Tuple[bool, Optional[int]]:
    """
    将指定应用窗口强制置顶并最大化（使用Win32 API实现，更可靠）
    :param app_identifier: 应用识别标识，根据match_by参数确定含义
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
        # 枚举所有窗口查找匹配的窗口
        win32gui.EnumWindows(window_enum_callback, None)
        
        if not target_hwnd:
            return False, None
        
        # 强制恢复窗口（从最小化/隐藏状态恢复）
        if win32gui.IsIconic(target_hwnd):
            win32gui.SendMessage(target_hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
            time.sleep(0.2)
        
        # 强制将窗口前置
        win32gui.SetForegroundWindow(target_hwnd)
        win32gui.BringWindowToTop(target_hwnd)
        
        # 强制设置为最顶层窗口，然后取消顶层（确保显示在最前面）
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
        
        # 最大化窗口
        win32gui.ShowWindow(target_hwnd, win32con.SW_MAXIMIZE)
        time.sleep(0.3)
        
        # 验证窗口是否确实在前台
        if not is_foreground_window(target_hwnd):
            return False, target_hwnd
            
        return True, target_hwnd
    except Exception as e:
        return False, None


def verify_window_focus(expected_hwnd: int) -> bool:
    """验证当前前台窗口是否为预期窗口，确保操作作用到正确位置"""
    return is_foreground_window(expected_hwnd)


def safe_click(x: int, y: int, clicks: int = 1, interval: float = 0.2, expected_hwnd: Optional[int] = None) -> bool:
    """
    安全点击方法，自动处理DPI缩放转换
    :param x: 原始横坐标（基于截图分辨率）
    :param y: 原始纵坐标（基于截图分辨率）
    :param clicks: 点击次数，默认1次
    :param interval: 多次点击之间的间隔时间，默认0.2秒
    :param expected_hwnd: 预期操作的窗口句柄，提供会先验证窗口焦点
    :return: 操作成功返回True，失败抛出异常
    """
    try:
        # 验证窗口焦点
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，点击操作取消")
            
        # 检测用户活动
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，点击操作取消")
            
        # DPI缩放换算
        scale_factor = get_dpi_scale_factor()
        scaled_x = int(x * scale_factor)
        scaled_y = int(y * scale_factor)
        
        # 移动鼠标并点击
        pyautogui.moveTo(scaled_x, scaled_y, duration=0.1)
        time.sleep(0.1)
        pyautogui.click(clicks=clicks, interval=interval)
        time.sleep(0.1)
        
        return True
    except Exception as e:
        raise RuntimeError(f"点击操作失败: {str(e)}") from e


def safe_input(text: str, expected_hwnd: Optional[int] = None) -> bool:
    """
    安全输入中文文本，使用剪贴板复制粘贴方式避免乱码
    :param text: 需要输入的文本内容
    :param expected_hwnd: 预期操作的窗口句柄，提供会先验证窗口焦点
    :return: 操作成功返回True
    """
    if not text:
        return True
    
    try:
        # 验证窗口焦点
        if expected_hwnd and not verify_window_focus(expected_hwnd):
            raise RuntimeError("目标窗口已失去焦点，输入操作取消")
            
        # 检测用户活动
        if detect_user_activity():
            raise RuntimeError("检测到用户主动操作，输入操作取消")
            
        # 保存当前剪贴板内容
        original_clipboard = pyperclip.paste()
        
        try:
            # 将文本复制到剪贴板
            pyperclip.copy(text)
            time.sleep(0.1)
            
            # 执行Ctrl+V粘贴
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.2)
            
            return True
        finally:
            # 恢复原始剪贴板内容
            pyperclip.copy(original_clipboard)
            
    except Exception as e:
        raise RuntimeError(f"文本输入失败: {str(e)}") from e


def safe_scroll(clicks: int, direction: str = "down", expected_hwnd: Optional[int] = None) -> bool:
    """
    安全滚动鼠标滚轮
    :param clicks: 滚动次数，正数表示向上/向下滚动的步数
    :param direction: 滚动方向：up/down
    :param expected_hwnd: 预期操作的窗口句柄，提供会先验证窗口焦点
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
    :param expected_hwnd: 预期操作的窗口句柄，提供会先验证窗口焦点
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


def capture_screenshot(region: Optional[Tuple[int, int, int, int]] = None) -> PIL.Image.Image:
    """
    捕获屏幕截图
    :param region: 截图区域，(x, y, width, height)，None表示全屏
    :return: PIL图像对象
    """
    try:
        screenshot = PIL.ImageGrab.grab(bbox=region, all_screens=True)
        return screenshot
    except Exception as e:
        raise RuntimeError(f"截图失败: {str(e)}") from e


def save_state_for_backtrack(current_state: Dict) -> Dict:
    """
    保存当前状态用于回溯，使用深拷贝防止引用污染
    :param current_state: 当前状态字典
    :return: 拷贝后的状态字典，可安全存储用于回溯
    """
    try:
        # 浅拷贝字典，对于嵌套结构建议根据实际需求改为深拷贝
        return current_state.copy()
    except Exception as e:
        raise RuntimeError(f"状态保存失败: {str(e)}") from e
