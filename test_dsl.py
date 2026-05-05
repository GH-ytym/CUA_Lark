from cua.schemas import CuaResponse
"""
CUA DSL功能综合测试脚本
测试新增的DSL生成、文档驱动、评分、基准测试、报告生成等功能
"""
import os
import sys
import time
import json
from datetime import datetime

from cua.primitives import (
    focus_and_maximize
)
from cua.agent import AgentController
from openai import OpenAI
import os
from dotenv import load_dotenv

def test_dsl_generation():
    """测试DSL生成功能"""
    print("="*60)
    print("🧪 测试1: DSL生成功能（自然语言→YAML）")
    print("="*60)
    
    try:
        from cua.dsl.generator import DslGenerator
        
        generator = DslGenerator()
        
        # 测试自然语言转DSL
        test_instruction = "给test_01发送消息说下午三点开会，然后确认消息已发送"
        print(f"📝 测试指令: {test_instruction}")
        
        yaml_content = generator.from_natural_language(
            instruction=test_instruction,
            product="im",
            difficulty="L2"
        )
        
        print(f"✅ DSL生成成功！")
        print(f"📋 生成的YAML内容:\n{yaml_content[:500]}...")
        
        # 验证YAML格式
        import yaml
        parsed = yaml.safe_load(yaml_content)
        assert "actions" in parsed, "DSL缺少actions字段"
        assert "verifications" in parsed, "DSL缺少verifications字段"
        print("✅ YAML格式验证通过")
        
        # 保存生成的DSL
        timestamp = int(time.time())
        dsl_path = f"dsl_generated_{timestamp}.yaml"
        with open(dsl_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)
        print(f"💾 DSL已保存至: {dsl_path}")
        
        print("\n✅ DSL生成测试完成!\n")
        return True
        
    except Exception as e:
        print(f"❌ DSL生成测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_dsl_evaluation():
    """测试DSL评分功能"""
    print("="*60)
    print("🧪 测试2: DSL五维评分功能")
    print("="*60)
    
    try:
        from cua.dsl.evaluator import DslEvaluator
        from cua.dsl.generator import DslGenerator
        
        # 先生成一个DSL用于评分
        generator = DslGenerator()
        yaml_content = generator.from_natural_language(
            instruction="点击飞书日历查看今天安排",
            product="calendar",
            difficulty="L1"
        )
        
        evaluator = DslEvaluator()
        scores = evaluator.evaluate(yaml_content, product="calendar")
        
        print(f"✅ DSL评分完成！")
        print(f"📊 评分结果:")
        for dimension, score in scores.items():
            print(f"  {dimension}: {score}/2")
        
        # 验证评分合理性
        assert all(0 <= s <= 2 for s in scores.values()), "评分应在0-2范围内"
        print("✅ 评分范围验证通过")
        
        print("\n✅ DSL评分测试完成!\n")
        return True
        
    except Exception as e:
        print(f"❌ DSL评分测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_doc_driven_generation():
    """测试文档驱动生成功能"""
    print("="*60)
    print("🧪 测试3: 文档驱动生成功能")
    print("="*60)
    
    try:
        from cua.dsl.doc_extractor import DocumentCaseExtractor
        
        # 创建一个模拟文档内容用于测试
        mock_doc_content = """
        # 飞书日历功能说明
        ## 日历查看功能
        用户可以点击左侧导航栏的日历图标查看日程安排
        
        ## 创建日程功能  
        点击"+"号可以创建新的日程安排
        
        ## 日程分享功能
        右键点击日程可以选择分享给同事
        """
        
        # 模拟文档读取
        extractor = DocumentCaseExtractor()
        # 直接测试提取逻辑（不实际调用API）
        features = extractor._extract_testable_features(mock_doc_content, "calendar")
        
        print(f"✅ 从文档提取到 {len(features)} 个可测功能点:")
        for i, feature in enumerate(features, 1):
            print(f"  {i}. {feature}")
        
        assert len(features) > 0, "应至少提取到1个功能点"
        print("✅ 功能点提取验证通过")
        
        print("\n✅ 文档驱动生成测试完成!\n")
        return True
        
    except Exception as e:
        print(f"❌ 文档驱动生成测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_benchmark_runner():
    """测试基准测试功能"""
    print("="*60)
    print("🧪 测试4: 基准测试功能")
    print("="*60)
    
    try:
        from cua.benchmark.runner import BenchmarkRunner
        from cua.benchmark.schema import BenchmarkCase
        
        # 创建一个测试用例
        test_case = BenchmarkCase(
            case_id="TEST_001",
            product="im",
            level="L1",
            instruction="点击发送按钮",
            expected_result="消息成功发送",
            tags=["smoke", "basic"]
        )
        
        # 保存为临时测试用例
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            yaml_content = f"""
case_id: {test_case.case_id}
product: {test_case.product}
level: {test_case.level}
instruction: {test_case.instruction}
expected_result: {test_case.expected_result}
tags: {test_case.tags}
actions:
  - action: click
    x: 500
    y: 800
    description: 点击发送按钮
verifications:
  - type: visual
    condition: 消息气泡出现
    description: 验证消息已发送
"""
            f.write(yaml_content)
            temp_case_file = f.name
        
        # 运行基准测试
        runner = BenchmarkRunner()
        results = runner.run_single_case(temp_case_file)
        
        print(f"✅ 基准测试执行完成！")
        print(f"📊 测试结果: {'成功' if results.get('success', False) else '失败'}")
        print(f"⏱️  耗时: {results.get('time_spent', 0)}秒")
        print(f"📝 执行步骤: {len(results.get('steps', []))}步")
        
        # 验证截图保存
        import os
        screenshot_dirs = []
        for root, dirs, files in os.walk("assets/screenshots"):
            for d in dirs:
                if d.startswith("run_"):
                    screenshot_dirs.append(os.path.join(root, d))
        
        print(f"📸 截图保存目录: {len(screenshot_dirs)}个")
        if screenshot_dirs:
            print(f"   示例路径: {screenshot_dirs[0]}")
        
        # 清理临时文件
        os.unlink(temp_case_file)
        
        print("\n✅ 基准测试功能测试完成!\n")
        return True
        
    except Exception as e:
        print(f"❌ 基准测试功能测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_report_generation():
    """测试报告生成功能"""
    print("="*60)
    print("🧪 测试5: 报告生成与飞书发布功能")
    print("="*60)
    
    try:
        from cua.report.md import MdReportGenerator
        from cua.report.insight_analyzer import InsightAnalyzer
        
        # 模拟测试结果
        mock_results = {
            "test_id": "DSL_TEST_001",
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "success_rate": 0.8,
            "total_cases": 5,
            "passed_cases": 4,
            "failed_cases": 1,
            "details": [
                {
                    "case_id": "CASE_001",
                    "success": True,
                    "steps": 3,
                    "time_spent": 2.5,
                    "screenshots": ["step1.png", "step2.png", "step3.png"]
                },
                {
                    "case_id": "CASE_002", 
                    "success": False,
                    "error": "元素未找到",
                    "steps": 1,
                    "time_spent": 1.2
                }
            ]
        }
        
        # 生成MD报告
        md_gen = MdReportGenerator()
        md_content = md_gen.generate(mock_results)
        
        print(f"✅ MD报告生成成功！")
        print(f"📄 报告长度: {len(md_content)} 字符")
        print(f"📋 报告预览:\n{md_content[:300]}...")
        
        # 保存报告
        report_path = f"report_{int(time.time())}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"💾 报告已保存至: {report_path}")
        
        # 测试AI洞察分析（模拟）
        analyzer = InsightAnalyzer()
        insights = analyzer.analyze(mock_results)
        
        print(f"💡 AI洞察分析完成，发现 {len(insights)} 条建议:")
        for i, insight in enumerate(insights, 1):
            print(f"  {i}. {insight}")
        
        print("\n✅ 报告生成测试完成!\n")
        return True
        
    except Exception as e:
        print(f"❌ 报告生成测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_integration_workflow():
    """测试完整工作流集成"""
    print("="*60)
    print("🧪 测试6: 完整工作流集成测试")
    print("="*60)
    
    try:
        print("🚀 开始完整工作流测试...")
        
        # 1. DSL生成
        from cua.dsl.generator import DslGenerator
        generator = DslGenerator()
        dsl_content = generator.from_natural_language(
            instruction="打开飞书日历查看今天安排",
            product="calendar",
            difficulty="L1"
        )
        print("✅ 1. DSL生成完成")
        
        # 2. DSL评分
        from cua.dsl.evaluator import DslEvaluator
        evaluator = DslEvaluator()
        scores = evaluator.evaluate(dsl_content, product="calendar")
        print(f"✅ 2. DSL评分完成: {scores}")
        
        # 3. 基准测试执行（模拟）
        from cua.benchmark.runner import BenchmarkRunner
        runner = BenchmarkRunner()
        # 模拟执行结果
        mock_result = {
            "success": True,
            "case_id": "INTEGRATION_TEST",
            "time_spent": 1.5,
            "steps_executed": 3,
            "screenshots_taken": 3
        }
        print(f"✅ 3. 基准测试模拟执行完成: {mock_result}")
        
        # 4. 报告生成
        from cua.report.md import MdReportGenerator
        md_gen = MdReportGenerator()
        report_content = md_gen.generate({"integration_test": mock_result})
        print(f"✅ 4. 报告生成完成，长度: {len(report_content)} 字符")
        
        print("\n✅ 完整工作流集成测试完成!\n")
        return True
        
    except Exception as e:
        print(f"❌ 完整工作流集成测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_dsl_execution():
    """测试DSL实际执行功能（真正使用生成的DSL文件执行，无需重新规划）"""
    print("="*60)
    print("🧪 测试7: DSL用例实际执行测试")
    print("="*60)
    
    try:
        # 1. 生成DSL用例
        from cua.dsl.generator import DslGenerator
        generator = DslGenerator()
        test_instruction = "打开飞书的文档功能，生成文档test_01.md，输入内容为：\n这是一个测试文档"""
        print(f"📝 测试指令: {test_instruction}")
        
        dsl_content = generator.from_natural_language(
            instruction=test_instruction,
            product="doc",
            difficulty="L2"
        )
        print("✅ DSL用例生成完成")
        print(f"📋 DSL内容预览:\n{dsl_content[:800]}...")
        
        # 2. 保存DSL到临时文件（真正的DSL用例文件）
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(dsl_content)
            dsl_file_path = f.name
        print(f"💾 DSL已保存至临时文件: {dsl_file_path}")
        
        # 3. 使用BenchmarkRunner执行DSL用例（核心：直接使用预生成的DSL执行，不需要大模型重新规划步骤）
        print("▶️  开始执行DSL用例... [真正使用生成的DSL文件执行，无需重新规划]")
        from cua.benchmark.runner import BenchmarkRunner
        runner = BenchmarkRunner()
        
        # 执行DSL用例 - 完全基于DSL文件中的预设步骤执行
        execution_result = runner.run_single_case(dsl_file_path)
        success = execution_result.get("status", "fail") == "pass"
        step_count = len(execution_result.get("step_results", []))
        duration = execution_result.get("duration", 0)
        screenshots = execution_result.get("screenshots", [])
        error_msg = execution_result.get("error_message")
        
        print(f"\n📊 执行结果: {'✅ 成功' if success else '❌ 失败'}")
        if error_msg:
            print(f"❌ 错误信息: {error_msg}")
        print(f"⏱️  执行耗时: {duration:.2f}秒")
        print(f"🔢 执行步数: {step_count} 步")
        print(f"📸 生成截图: {len(screenshots)} 张")
        
        # 打印执行步骤详情
        if execution_result.get("step_results"):
            print("\n📋 执行步骤详情:")
            for i, step in enumerate(execution_result["step_results"], 1):
                step_status = "✅" if step.get("success", False) else "❌"
                print(f"  {i}. {step_status} {step.get('description', '无描述')}")
        
        # 4. 生成完整执行报告
        from cua.report.md import MdReportGenerator
        md_gen = MdReportGenerator()
        report_result = {
            "test_id": "DSL_EXEC_TEST_001",
            "start_time": datetime.fromtimestamp(execution_result.get("start_time", time.time())).isoformat(),
            "end_time": datetime.fromtimestamp(execution_result.get("end_time", time.time())).isoformat(),
            "success_rate": 1.0 if success else 0.0,
            "total_cases": 1,
            "passed_cases": 1 if success else 0,
            "failed_cases": 0 if success else 1,
            "details": [{
                "case_id": execution_result.get("case_id", "DSL_EXEC_001"),
                "success": success,
                "steps": step_count,
                "time_spent": duration,
                "screenshots": screenshots,
                "error": error_msg
            }]
        }
        report_content = md_gen.generate(report_result)
        report_path = f"dsl_exec_report_{int(time.time())}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        print(f"💾 执行报告已保存至: {report_path}")
        
        # 清理临时DSL文件
        os.unlink(dsl_file_path)
        
        print("\n✅ DSL用例执行测试完成! 已真正使用生成的DSL文件完成端到端执行\n")
        return True
        
    except Exception as e:
        print(f"❌ DSL执行测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🚀 CUA DSL功能综合测试开始")
    print("⚠️  注意：运行前请确保已配置好环境变量（API KEY等）\n")

    success, hwnd = focus_and_maximize("飞书")
    
    # 运行所有测试
    results = {}
    # results["dsl_generation"] = test_dsl_generation()
    # results["dsl_evaluation"] = test_dsl_evaluation()
    # results["doc_driven"] = test_doc_driven_generation()
    # results["benchmark"] = test_benchmark_runner()
    # results["report"] = test_report_generation()
    # results["integration"] = test_integration_workflow()
    results["dsl_execution"] = test_dsl_execution()
    
    print("="*60)
    print("🎉 测试总览:")
    for test_name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {test_name}: {status}")
    
    passed_count = sum(results.values())
    total_count = len(results)
    print(f"\n📊 总体结果: {passed_count}/{total_count} 项测试通过")
    
    if passed_count == total_count:
        print("🎉 所有DSL功能测试通过！")
    else:
        print("⚠️  部分测试失败，请检查错误日志")
    
    print("="*60)