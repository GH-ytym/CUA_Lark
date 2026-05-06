from __future__ import annotations

"""
屏幕截图模块（对齐成熟方案：不做缩放，保持原始分辨率与pyautogui.size()坐标系一致）
"""
import io
import base64
import os
import time
import logging

try:
    from PIL import ImageGrab, Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

DEFAULT_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(DEFAULT_ASSETS_DIR, exist_ok=True)


def capture_screen_base64(quality=70, save_original=False):
    """
    截取全屏并转换为Base64编码（对齐成熟方案：不做缩放，保持原始分辨率）
    :param quality: JPEG压缩质量，1-100
    :param save_original: 是否同时返回PIL原始图像对象，供标记截图使用
    :return: 不带save_original返回base64字符串；带save_original返回(base64_str, screenshot_size, pil_image)元组
    """
    if not HAS_PIL:
        logging.warning("缺少 Pillow 库(pip install pillow)，无法截图。")
        return None if not save_original else None
    try:
        img = ImageGrab.grab()
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        b64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        if save_original:
            return b64_str, img.size, img
        return b64_str
    except Exception as e:
        logging.error(f"截图异常: {e}")
        return None


def build_marker_base64(original_image: Image.Image, x: int, y: int, quality: int = 70) -> str:
    """
    在原始截图上标记点击位置（红色十字+红圈），转换为Base64
    坐标体系：比例坐标(0-1000)，会在标记前换算为实际像素坐标
    :param original_image: 原始PIL截图对象
    :param x: 比例横坐标(0-1000)
    :param y: 比例纵坐标(0-1000)
    :param quality: JPEG压缩质量
    :return: 带标记的截图Base64字符串（带data URI前缀）
    """
    try:
        marked_img = original_image.copy()
        draw = ImageDraw.Draw(marked_img)
        
        img_width, img_height = marked_img.size
        pixel_x = int(x * img_width / 1000)
        pixel_y = int(y * img_height / 1000)
        
        cross_size = max(15, min(img_width, img_height) // 40)
        circle_radius = cross_size + 5
        
        draw.ellipse(
            [pixel_x - circle_radius, pixel_y - circle_radius,
             pixel_x + circle_radius, pixel_y + circle_radius],
            outline='red', width=3
        )
        draw.line([pixel_x - cross_size, pixel_y, pixel_x + cross_size, pixel_y], fill='red', width=3)
        draw.line([pixel_x, pixel_y - cross_size, pixel_x, pixel_y + cross_size], fill='red', width=3)
        
        buffer = io.BytesIO()
        marked_img.save(buffer, format="JPEG", quality=quality)
        b64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return f"data:image/jpeg;base64,{b64_str}"
    except Exception as e:
        logging.error(f"标记截图生成失败: {e}")
        return ""


def save_screenshot_with_marker(original_image: Image.Image, x: int, y: int,
                                 assets_dir: str = DEFAULT_ASSETS_DIR) -> str:
    """
    保存带点击标记的截图到本地文件
    坐标体系：比例坐标(0-1000)
    :param original_image: 原始PIL截图对象
    :param x: 比例横坐标(0-1000)
    :param y: 比例纵坐标(0-1000)
    :param assets_dir: 保存目录
    :return: 保存的文件路径
    """
    try:
        marked_img = original_image.copy()
        draw = ImageDraw.Draw(marked_img)
        
        img_width, img_height = marked_img.size
        pixel_x = int(x * img_width / 1000)
        pixel_y = int(y * img_height / 1000)
        
        cross_size = max(15, min(img_width, img_height) // 40)
        circle_radius = cross_size + 5
        
        draw.ellipse(
            [pixel_x - circle_radius, pixel_y - circle_radius,
             pixel_x + circle_radius, pixel_y + circle_radius],
            outline='red', width=3
        )
        draw.line([pixel_x - cross_size, pixel_y, pixel_x + cross_size, pixel_y], fill='red', width=3)
        draw.line([pixel_x, pixel_y - cross_size, pixel_x, pixel_y + cross_size], fill='red', width=3)
        
        timestamp = int(time.time())
        filepath = os.path.join(assets_dir, f"screenshot_{timestamp}_click_marker.png")
        marked_img.save(filepath)
        return filepath
    except Exception as e:
        logging.error(f"保存标记截图失败: {e}")
        return ""
