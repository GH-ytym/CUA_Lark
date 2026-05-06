"""Lightweight perception exports with optional detector dependencies."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .screen_capture import capture_screen_base64, save_screenshot_with_marker


_LAZY_EXPORTS = {
    "ElementType": ("cua.perception.element_detector", "ElementType"),
    "ElementQuality": ("cua.perception.element_detector", "ElementQuality"),
    "BoundingBox": ("cua.perception.element_detector", "BoundingBox"),
    "DetectedElement": ("cua.perception.element_detector", "DetectedElement"),
    "ElementDetectionResult": ("cua.perception.element_detector", "ElementDetectionResult"),
    "ElementDetector": ("cua.perception.element_detector", "ElementDetector"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'cua.perception' has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = ["capture_screen_base64", "save_screenshot_with_marker", *_LAZY_EXPORTS.keys()]
