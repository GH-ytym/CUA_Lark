"""Lightweight CUA agent exports with lazy loading for optional modules."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .context_builder import ContextBuilder


_LAZY_EXPORTS = {
    "AgentLoopRunner": ("cua.agent.loop_runner", "AgentLoopRunner"),
    "AgentController": ("cua.agent.controller", "AgentController"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'cua.agent' has no attribute {name!r}")
    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = ["ContextBuilder", "AgentLoopRunner", "AgentController"]
