"""
统一坐标转换工具类（严格对齐参考项目实现，彻底解决坐标偏移问题）
封装所有坐标系转换、DPI适配、多显示器补偿逻辑
"""
import win32gui
import win32api
import win32con
import ctypes
from typing import Tuple, Optional

# Windows API 常量
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
MONITOR_DEFAULTTONEAREST = 2

# 加载User32.dll
user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()  # 进程设置DPI感知，避免被系统虚拟化
except Exception:
    pass


class CoordinateConverter:
    """统一坐标转换器，封装所有坐标相关计算逻辑"""
    
    def __init__(self, hwnd: Optional[int] = None):
        """
        初始化坐标转换器
        :param hwnd: 目标窗口句柄，不传则处理全局屏幕坐标
        """
        self.hwnd = hwnd
        self._dpi_scale = None
        self._monitor_info = None
        self._window_rect = None
        
        if hwnd:
            self.refresh_window_info()
    
    def refresh_window_info(self) -> None:
        """刷新窗口和显示器信息，窗口位置变化后调用"""
        if not self.hwnd:
            return
            
        # 获取窗口客户区屏幕坐标
        client_left, client_top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        client_right, client_bottom = win32gui.ClientToScreen(self.hwnd, win32gui.GetClientRect(self.hwnd)[2:])
        self._window_rect = (client_left, client_top, client_right, client_bottom)
        
        # 获取窗口所在显示器信息
        monitor = win32api.MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST)
        self._monitor_info = win32api.GetMonitorInfo(monitor)
        
        # 获取该显示器的DPI
        hdc = user32.GetDC(self.hwnd)
        dpi_x = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(self.hwnd, hdc)
        self._dpi_scale = dpi_x / 96.0
    
    @property
    def dpi_scale(self) -> float:
        """获取DPI缩放系数，1.0=100%, 1.25=125%等"""
        if not self._dpi_scale:
            # 全局DPI
            hdc = user32.GetDC(0)
            dpi_x = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            self._dpi_scale = dpi_x / 96.0
        return self._dpi_scale
    
    @property
    def window_client_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口客户区在屏幕上的绝对坐标 (left, top, right, bottom)"""
        return self._window_rect
    
    @property
    def monitor_work_area(self) -> Tuple[int, int, int, int]:
        """获取窗口所在显示器的工作区坐标，支持多显示器偏移"""
        if self._monitor_info:
            return self._monitor_info["Work"]
        # 默认主显示器
        return (0, 0, win32api.GetSystemMetrics(SM_CXSCREEN), win32api.GetSystemMetrics(SM_CYSCREEN))
    
    def client_to_screen(self, x: int, y: int) -> Tuple[int, int]:
        """窗口客户区坐标转屏幕绝对坐标"""
        if not self.hwnd:
            return (x, y)
        return win32gui.ClientToScreen(self.hwnd, (x, y))
    
    def screen_to_client(self, x: int, y: int) -> Tuple[int, int]:
        """屏幕绝对坐标转窗口客户区坐标"""
        if not self.hwnd:
            return (x, y)
        return win32gui.ScreenToClient(self.hwnd, (x, y))

    @staticmethod
    def get_virtual_screen_rect() -> Tuple[int, int, int, int]:
        """获取虚拟桌面范围，支持多显示器和负坐标。"""
        left = win32api.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = win32api.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        return (left, top, left + width, top + height)

    @classmethod
    def get_virtual_screen_capture_region(cls) -> Tuple[int, int, int, int]:
        """获取虚拟桌面的截图区域，格式为(left, top, width, height)。"""
        left, top, right, bottom = cls.get_virtual_screen_rect()
        return (left, top, right - left, bottom - top)
    
    def logical_to_physical(self, x: int, y: int) -> Tuple[int, int]:
        """逻辑坐标（适配DPI前）转物理像素坐标"""
        return (int(round(x * self.dpi_scale)), int(round(y * self.dpi_scale)))
    
    def physical_to_logical(self, x: int, y: int) -> Tuple[int, int]:
        """物理像素坐标转逻辑坐标"""
        return (int(round(x / self.dpi_scale)), int(round(y / self.dpi_scale)))
    
    def screenshot_coord_to_screen(
        self,
        screenshot_x: int,
        screenshot_y: int,
        screenshot_original_size: Tuple[int, int],
        capture_region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Tuple[int, int]:
        """
        截图上的坐标转换为实际屏幕点击坐标（解决截图缩放导致的偏移）
        :param screenshot_x: 截图上的x坐标
        :param screenshot_y: 截图上的y坐标
        :param screenshot_original_size: 截图的原始尺寸 (width, height)
        :return: 实际屏幕坐标
        """
        screenshot_width, screenshot_height = screenshot_original_size
        if screenshot_width <= 0 or screenshot_height <= 0:
            raise ValueError(f"无效的截图尺寸: {screenshot_original_size}")

        if capture_region is not None:
            region_left, region_top, region_width, region_height = capture_region
        else:
            # 当前项目默认发送给模型的是整张虚拟桌面截图，因此默认按全屏区域换算。
            # 如果后续要支持窗口局部截图，调用方应显式传入 capture_region。
            region_left, region_top, region_width, region_height = self.get_virtual_screen_capture_region()

        if region_width <= 0 or region_height <= 0:
            raise ValueError(f"无效的截图区域: {(region_left, region_top, region_width, region_height)}")

        scale_x = region_width / screenshot_width
        scale_y = region_height / screenshot_height
        screen_x = region_left + int(round(screenshot_x * scale_x))
        screen_y = region_top + int(round(screenshot_y * scale_y))
        return (screen_x, screen_y)
    
    def get_window_capture_region(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口截图区域，格式为(left, top, width, height)，用于mss/PIL截图"""
        if not self.hwnd or not self._window_rect:
            return None
        left, top, right, bottom = self._window_rect
        return (left, top, right - left, bottom - top)
    
    def validate_screen_coordinate(self, x: int, y: int) -> bool:
        """验证坐标是否在屏幕范围内"""
        left, top, right, bottom = self.get_virtual_screen_rect()
        return left <= x < right and top <= y < bottom


# 全局快捷方法
def get_system_dpi_scale() -> float:
    """获取系统全局DPI缩放系数"""
    return CoordinateConverter().dpi_scale

def convert_screenshot_coord_to_screen(
    x: int,
    y: int,
    screenshot_size: Tuple[int, int],
    hwnd: Optional[int] = None,
    capture_region: Optional[Tuple[int, int, int, int]] = None,
) -> Tuple[int, int]:
    """
    快捷转换：截图坐标转屏幕坐标
    :param x: 截图x坐标
    :param y: 截图y坐标
    :param screenshot_size: 截图尺寸 (width, height)
    :param hwnd: 目标窗口句柄，全屏截图不传
    :param capture_region: 实际截图区域 (left, top, width, height)
    :return: 实际屏幕坐标
    """
    converter = CoordinateConverter(hwnd)
    return converter.screenshot_coord_to_screen(x, y, screenshot_size, capture_region=capture_region)
