from typing import List, Optional, Dict, Any
import json
import os
import time
from pathlib import Path
from .schema import MemoryItem, MemoryType

class MemoryManager:
    """记忆管理器，负责记忆的存储、检索、持久化"""
    
    def __init__(self, storage_path: str | None = None):
        self.memories: List[MemoryItem] = []
        self.storage_path = Path(storage_path or os.getenv("CUA_MEMORY_PATH", "cua_memory.json"))
        # 自动加载已有的记忆
        self._load_from_disk()
    
    def add_memory(self, 
                  memory_type: MemoryType,
                  content: str,
                  context: Dict[str, Any] = None,
                  importance: float = 0.5,
                  embedding: List[float] = None) -> MemoryItem:
        """添加一条新记忆"""
        memory = MemoryItem(
            memory_type=memory_type,
            content=content,
            context=context or {},
            importance=importance,
            embedding=embedding
        )
        self.memories.append(memory)
        # 自动保存到磁盘
        self._save_to_disk()
        return memory
    
    def get_recent_memories(
        self,
        limit: int = 10,
        memory_type: Optional[MemoryType] = None,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """获取最近的记忆"""
        filtered = self.memories
        if memory_type:
            filtered = [m for m in filtered if m.memory_type == memory_type]
        if scope:
            filtered = [m for m in filtered if self._matches_scope(m.context, scope)]
        
        # 按时间倒序
        sorted_memories = sorted(filtered, key=lambda x: x.timestamp, reverse=True)
        return sorted_memories[:limit]
    
    def search_by_content(self, query: str, limit: int = 5) -> List[MemoryItem]:
        """按内容关键词搜索记忆（简化实现，实际项目可改用向量检索）"""
        results = []
        query_lower = query.lower()
        for memory in self.memories:
            if query_lower in memory.content.lower() or query_lower in str(memory.context).lower():
                results.append(memory)
        
        # 按重要性和时间排序
        results = sorted(results, key=lambda x: (x.importance, x.timestamp), reverse=True)
        return results[:limit]
    
    def get_action_history(self, limit: int = 20, scope: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """获取历史动作记录，用于上下文构建"""
        action_memories = self.get_recent_memories(limit, MemoryType.ACTION, scope=scope)
        return [
            {
                "action": m.content,
                "timestamp": m.timestamp,
                "success": m.context.get("success", False)
            }
            for m in action_memories
        ]
    
    def get_failure_cases(
        self,
        task_type: str = None,
        limit: int = 5,
        scope: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """获取失败案例记忆，用于避免重复犯错"""
        failures = self.get_recent_memories(limit, MemoryType.FAILURE, scope=scope)
        if task_type:
            failures = [f for f in failures if f.context.get("task_type") == task_type]
        return failures
    
    def clear(self):
        """清空所有记忆"""
        self.memories = []
        self._save_to_disk()
    
    def _save_to_disk(self):
        """将记忆持久化到磁盘"""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = [m.to_dict() for m in self.memories]
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"CUA memory save failed: {str(e)}")
    
    def _load_from_disk(self):
        """从磁盘加载记忆"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.memories = [MemoryItem.from_dict(item) for item in data]
                print(f"Loaded {len(self.memories)} CUA memories")
            except Exception as e:
                print(f"CUA memory load failed: {str(e)}")
                self.memories = []
    
    def format_for_prompt(self, max_memories: int = 10, scope: Optional[Dict[str, Any]] = None) -> str:
        """将记忆格式化为LLM提示词中的上下文"""
        recent = self.get_recent_memories(max_memories, scope=scope)
        if not recent:
            return "无历史记忆"
        
        memory_text = "历史记忆（最近执行的动作和观察结果）:\n"
        for i, mem in enumerate(recent, 1):
            time_str = f"[{int(time.time() - mem.timestamp)}秒前]"
            memory_text += f"{i}. {time_str} [{mem.memory_type.value}] {mem.content}"
            if mem.context.get("error"):
                memory_text += f" (错误: {mem.context['error']})"
            memory_text += "\n"
        
        return memory_text

    @staticmethod
    def _matches_scope(context: Dict[str, Any], scope: Dict[str, Any]) -> bool:
        """Return whether one memory context belongs to the requested scope."""
        for key in ("session_id", "app_name", "capability_id"):
            expected = str(scope.get(key, "") or "").strip()
            if not expected:
                continue
            actual = str(context.get(key, "") or "").strip()
            if actual != expected:
                return False
        return True

# 全局记忆管理器实例
global_memory = MemoryManager()
