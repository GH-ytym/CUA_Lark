"""
记忆功能测试脚本
验证记忆功能是否正常工作
"""
import os
import time
from cua.memory import global_memory, MemoryType, MemoryManager

def test_memory_basic():
    """测试基础记忆功能"""
    print("="*60)
    print("🧪 测试1: 基础记忆功能")
    print("="*60)
    
    # 清空现有记忆
    global_memory.clear()
    print("✅ 记忆已清空")
    
    # 添加测试记忆
    mem1 = global_memory.add_memory(
        memory_type=MemoryType.ACTION,
        content="点击了发送按钮",
        context={"x": 100, "y": 200, "success": True},
        importance=0.6
    )
    
    mem2 = global_memory.add_memory(
        memory_type=MemoryType.OBSERVATION,
        content="看到消息已发送成功",
        context={"has_image": True},
        importance=0.4
    )
    
    mem3 = global_memory.add_memory(
        memory_type=MemoryType.FAILURE,
        content="点击输入框失败，元素未找到",
        context={"error": "元素未找到"},
        importance=0.9
    )
    
    print(f"✅ 添加了3条测试记忆")
    
    # 测试获取最近记忆
    recent = global_memory.get_recent_memories(2)
    print(f"✅ 获取最近2条记忆: {len(recent)}条")
    for i, mem in enumerate(recent, 1):
        print(f"  {i}. [{mem.memory_type.value}] {mem.content}")
    
    # 测试搜索记忆
    search_result = global_memory.search_by_content("失败")
    print(f"\n✅ 搜索'失败'得到 {len(search_result)} 条结果")
    for i, mem in enumerate(search_result, 1):
        print(f"  {i}. [{mem.memory_type.value}] {mem.content} (重要性: {mem.importance})")
    
    # 测试格式化为提示词
    prompt_text = global_memory.format_for_prompt(5)
    print(f"\n✅ 格式化为提示词成功，长度: {len(prompt_text)}字符")
    print(f"提示词预览:\n{prompt_text[:300]}...")
    
    return True

def test_memory_persistence():
    """测试记忆持久化功能"""
    print("\n" + "="*60)
    print("🧪 测试2: 记忆持久化功能")
    print("="*60)
    
    # 创建新的记忆管理器实例，会自动加载刚才保存的记忆
    new_manager = MemoryManager("cua_memory.json")
    print(f"✅ 从磁盘加载了 {len(new_manager.memories)} 条记忆")
    
    # 验证记忆内容
    assert len(new_manager.memories) == 3, "记忆数量不一致"
    print("✅ 记忆持久化验证通过")
    
    return True

def test_memory_in_execution():
    """测试记忆在执行流程中的集成"""
    print("\n" + "="*60)
    print("🧪 测试3: 记忆功能集成验证")
    print("="*60)
    
    # 测试记忆功能已经集成到AgentLoopRunner
    from cua.agent.loop_runner import AgentLoopRunner
    from cua.report.logger import RunLogger
    
    # 模拟LLM请求函数
    def mock_llm_request(messages):
        # 检查是否包含记忆上下文
        has_memory = any("历史记忆" in str(m["content"]) for m in messages)
        if has_memory:
            print("✅ LLM请求中已包含记忆上下文")
        else:
            print("❌ LLM请求中未包含记忆上下文")
            return '[{"action": "DONE"}]'
        return '[{"action": "click", "x": 100, "y": 200, "description": "点击测试"}, {"action": "DONE"}]'
    
    # 初始化运行器
    logger = RunLogger("memory_test", "测试记忆功能")
    runner = AgentLoopRunner(logger, mock_llm_request)
    
    # 运行测试任务
    result = runner.run("测试记忆功能是否正常", max_steps=2)
    print(f"✅ 任务执行结果: {'成功' if result else '失败'}")
    
    # 检查是否生成了新的记忆
    new_memories = global_memory.get_recent_memories(10)
    print(f"✅ 执行后记忆数量: {len(new_memories)}条")
    
    # 检查是否有任务目标记忆
    goal_memories = [m for m in new_memories if m.memory_type == MemoryType.GOAL]
    assert len(goal_memories) > 0, "未记录任务目标记忆"
    print("✅ 任务目标记忆已记录")
    
    # 检查是否有动作记忆
    action_memories = [m for m in new_memories if m.memory_type == MemoryType.ACTION]
    assert len(action_memories) > 0, "未记录动作记忆"
    print("✅ 动作执行记忆已记录")
    
    # 检查是否有成功记忆
    success_memories = [m for m in new_memories if m.memory_type == MemoryType.SUCCESS]
    assert len(success_memories) > 0, "未记录任务成功记忆"
    print("✅ 任务成功记忆已记录")
    
    return True

if __name__ == "__main__":
    print("🚀 CUA记忆功能测试开始\n")
    
    success_count = 0
    total_tests = 3
    
    try:
        if test_memory_basic():
            success_count += 1
    except Exception as e:
        print(f"❌ 基础记忆功能测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
    
    try:
        if test_memory_persistence():
            success_count += 1
    except Exception as e:
        print(f"❌ 记忆持久化测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
    
    try:
        if test_memory_in_execution():
            success_count += 1
    except Exception as e:
        print(f"❌ 记忆集成测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)
    print("🎉 测试总览:")
    print(f"  基础记忆功能: {'✅ 通过' if success_count >= 1 else '❌ 失败'}")
    print(f"  记忆持久化: {'✅ 通过' if success_count >= 2 else '❌ 失败'}")
    print(f"  记忆集成: {'✅ 通过' if success_count >= 3 else '❌ 失败'}")
    print(f"\n📊 总体结果: {success_count}/{total_tests} 项测试通过")
    
    if success_count == total_tests:
        print("🎉 所有记忆功能测试通过！")
    else:
        print("⚠️  部分测试失败，请检查错误日志")
    print("="*60)
    
    # 清理测试文件
    if os.path.exists("cua_memory.json"):
        os.remove("cua_memory.json")
        print("\n✅ 测试记忆文件已清理")
