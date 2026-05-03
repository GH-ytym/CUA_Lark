"""
CUA模块综合测试脚本
测试两种模式：1. 单步CuaExecutor模式 2. 多步Agent模式
"""
import os
import sys
from cua.schemas import CuaResponse
from cua.primitives import (
    focus_and_maximize
)

# 2. 测试多步AgentController（复杂任务自动规划执行）
def test_multi_step_agent():

    success, hwnd = focus_and_maximize("飞书")
    if not success:
        return CuaResponse(
            success=False,
            message=f"无法找到并激活目标应用: 飞书",
            history_states=[],      
            diagnosis_report=None,
            fix_plan=None
        ) 

    print("="*60)
    print("🧪 测试2: 多步AgentController模式（复杂任务自动规划）")
    print("="*60)
    
    from cua import AgentController
    from openai import OpenAI
    import os
    from dotenv import load_dotenv
    
    # 加载环境变量
    load_dotenv()
    
    # 创建LLM客户端
    api_key = os.getenv("CUA_MODEL_API_KEY", os.getenv("CUA_MODEL_API_KEY"))
    api_url = os.getenv("CUA_MODEL_API_BASE", os.getenv("CUA_MODEL_API_BASE"))
    client = OpenAI(api_key=api_key, base_url=api_url)
    
    # 定义LLM请求函数
    def llm_request_func(messages):
        response = client.chat.completions.create(
            model=os.getenv("CUA_MODEL_NAME", "ep-20260423222752-9tcpw"),
            messages=messages,
            max_tokens=2000,
            temperature=0.0
        )
        return response.choices[0].message.content.strip()
    
    # 初始化Agent
    agent = AgentController(llm_request_func=llm_request_func)
    
    # 由于AgentController只支持run_test_case方法，我们创建一个临时测试用例
    # 这里简化处理，直接使用AgentLoopRunner进行测试
    from cua.agent.loop_runner import AgentLoopRunner
    from cua.report.logger import RunLogger
    
    print("▶️  开始执行多步任务...")
    logger = RunLogger("test_task", "打开日历测试")
    runner = AgentLoopRunner(logger, llm_request_func)
    
    try:
        result = runner.run(
            current_goal="打开飞书的消息功能，在小组发送hello world",
            max_steps=10
        )
        success = result
        step_count = runner.step_count
        time_spent = 0  # 简化处理
        action_summary = runner.action_summary
    except Exception as e:
        success = False
        step_count = 0
        time_spent = 0
        action_summary = []
        print(f"❌ 执行异常: {e}")
    
    print(f"\n📊 执行结果: {'✅ 成功' if success else '❌ 失败'}")
    print(f"🔢 执行步数: {step_count} 步")
    
    # 打印执行的动作
    if action_summary:
        print("\n📋 已执行动作:")
        for i, action in enumerate(action_summary):
            print(f"  {i+1}. {action}")
    
    print("\n✅ 多步Agent测试完成!\n")
    return success

if __name__ == "__main__":
    print("🚀 CUA模块综合测试开始")
    print("⚠️  注意：运行前请确保飞书已经打开，避免操作失败\n")
    
    # 运行测试
    #single_success = test_single_step_executor()
    multi_success = test_multi_step_agent()
    
    print("="*60)
    print("🎉 测试总览:")
    #print(f"  单步执行测试: {'✅ 通过' if single_success else '❌ 失败'}")
    print(f"  多步Agent测试: {'✅ 通过' if multi_success else '❌ 失败'}")
    #print(f"  整体结果: {'✅ 全部通过!' if multi_success else '❌ 部分测试失败'}")
    print("="*60)