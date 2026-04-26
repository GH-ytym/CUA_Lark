import mss
import mss.tools
import base64
import threading
import os
import time
from io import BytesIO
from PIL import Image, ImageGrab
from typing import Optional, Callable, Tuple, Union

# 默认截图保存目录，对齐参考项目路径
DEFAULT_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(DEFAULT_ASSETS_DIR, exist_ok=True)


def capture_screen_async(callback: Callable[[str], None] = None, save_to_file: bool = True, assets_dir: str = DEFAULT_ASSETS_DIR) -> threading.Thread:
    """
    非阻塞方式截取屏幕（完全对齐参考项目实现）
    :param callback: 截图完成后的回调函数，参数为截图文件路径
    :param save_to_file: 是否保存到本地文件，默认True
    :param assets_dir: 截图保存目录，默认项目根目录下的assets文件夹
    :return: 截图线程对象
    """
    def _capture():
        timestamp = int(time.time())
        filepath = os.path.join(assets_dir, f"screenshot_{timestamp}.png")
        # 截取全屏（和参考项目完全一致使用ImageGrab）
        screenshot = ImageGrab.grab()
        screenshot.save(filepath)
        if callback:
            callback(filepath)
    
    thread = threading.Thread(target=_capture)
    thread.start()
    return thread


def capture_screen_sync(save_to_file: bool = True, assets_dir: str = DEFAULT_ASSETS_DIR) -> str:
    """
    同步方式截取屏幕
    :param save_to_file: 是否保存到本地文件，默认True
    :param assets_dir: 截图保存目录
    :return: 截图文件路径
    """
    timestamp = int(time.time())
    filepath = os.path.join(assets_dir, f"screenshot_{timestamp}.png")
    screenshot = ImageGrab.grab()
    screenshot.save(filepath)
    return filepath


def capture_screen_as_base64(
    quality: int = 80,
    max_dimension: int = 1920,
    screenshot_path: str = None,
    return_metadata: bool = False,
) -> Union[str, Tuple[str, Tuple[int, int]]]:
    """
    截取主屏幕并转换为Base64编码的JPEG图片
    :param quality: JPEG压缩质量，1-100，默认80
    :param max_dimension: 图片最长边最大像素值，超过会等比缩放，默认1920
    :param screenshot_path: 可选，使用已有的截图文件，不填则实时截图
    :param return_metadata: 是否额外返回发送给模型的图片尺寸(width, height)
    :return: Base64字符串；若return_metadata=True，则返回(base64字符串, 图片尺寸)
    """
    try:
        if screenshot_path and os.path.exists(screenshot_path):
            # 使用已有的截图文件
            img = Image.open(screenshot_path).convert("RGB")
        else:
            # 实时截图，统一使用虚拟桌面范围，避免多显示器坐标系不一致
            img = ImageGrab.grab(all_screens=True).convert("RGB")
        
        # 等比缩放图片，限制最长边不超过max_dimension
        width, height = img.size
        if max(width, height) > max_dimension:
            scale = max_dimension / max(width, height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 压缩为JPEG格式
        img_buffer = BytesIO()
        img.save(img_buffer, format="JPEG", quality=quality, optimize=True)
        img_bytes = img_buffer.getvalue()
        
        # 转换为Base64编码，加上data URI前缀
        base64_str = base64.b64encode(img_bytes).decode("utf-8")
        result = f"data:image/jpeg;base64,{base64_str}"
        if return_metadata:
            return result, img.size
        return result
            
    except Exception as e:
        raise RuntimeError(f"截图失败: {str(e)}") from e
