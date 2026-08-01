#!/usr/bin/env python3
"""
Ainos OS 多智能体协作系统
=============================
基于 Weelink 中转平台，协调 4 个 AI 助手协同开发：
- GPT-5.6-Sol     → 首席架构师 (Lead Architect)
- DeepSeek-v4-Pro → 内核工程师 (Kernel Engineer)
- Claude-Opus-4-8 → AI Runtime 工程师 (AI Runtime Engineer)
- Qwen3.7-Plus    → 用户空间工程师 (Userland Engineer)

用法:
  python orchestrator.py --task "描述任务"           # 所有智能体协作
  python orchestrator.py --agent architect --task "任务"  # 指定智能体
  python orchestrator.py --list                      # 列出智能体
  python orchestrator.py --status                    # 查看任务状态
"""

import argparse
import json
import os
import sys
import datetime
import threading
import time
from pathlib import Path

# 修复 Windows 终端编码
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# =============================================
# 配置 - 4个AI助手的API密钥
# =============================================
AGENTS = {
    "architect": {
        "name": "GPT-5.6-Sol",
        "role": "首席架构师 (Lead Architect)",
        "api_key": "sk-KUCiQXHzvrpMMBJFArIRIH8Ird6rFDwEL6Y8PQ3PFLQMEgNN",
        "base_url": "https://api.weelinking.com/v1",
        "model": "gpt-5.6-sol",
        "color": "\033[96m",  # Cyan
        "responsibility": [
            "系统总体架构设计",
            "内核模块接口定义",
            "AI系统调用ABI设计",
            "组件集成与协调",
            "技术决策与权衡",
        ],
    },
    "kernel": {
        "name": "DeepSeek-v4-Pro",
        "role": "内核工程师 (Kernel Engineer)",
        "api_key": "sk-gd3qhcrV1L9PVdITS69lLjXaNzZcekCtPH6Lt0lWKqJoPD3f",
        "base_url": "https://api.weelinking.com/v1",
        "model": "deepseek-v4-pro",
        "color": "\033[92m",  # Green
        "responsibility": [
            "Linux内核AI模块开发",
            "AI调度器实现",
            "系统调用扩展",
            "驱动框架设计",
            "向量指令加速",
        ],
    },
    "ai-runtime": {
        "name": "Claude-Opus-4-8",
        "role": "AI Runtime工程师",
        "api_key": "sk-0ZwAUltIH3JrVl5Rz8CpARZPBlgCWVHmm32BND55lXZKPqal",
        "base_url": "https://api.weelinking.com/v1",
        "model": "claude-opus-4-8",
        "color": "\033[93m",  # Yellow
        "responsibility": [
            "GGML推理引擎集成",
            "ONNX Runtime系统服务",
            "模型管理守护进程",
            "本地/云端模型编排",
            "上下文管理子系统",
        ],
    },
    "userland": {
        "name": "Qwen3.7-Plus",
        "role": "用户空间工程师",
        "api_key": "sk-t7grcBHdfxEkG1LVq9qYkgn9Ge1LRkLVhVrMEpNWLtJdQtx5",
        "base_url": "https://api.weelinking.com/v1",
        "model": "qwen3.7-plus",
        "color": "\033[95m",  # Magenta
        "responsibility": [
            "桌面环境开发",
            "AI原生应用框架",
            "系统控制面板",
            "开发者SDK",
            "文档和示例",
        ],
    },
}

COLOR_RESET = "\033[0m"
PROJECT_ROOT = Path("D:/Ainos")
TASKS_DIR = PROJECT_ROOT / "weelink-agent" / "tasks"

# =============================================
# OpenAI兼容API调用
# =============================================
def call_ai(agent_key, messages, temperature=0.7, max_tokens=4096):
    """调用指定AI智能体"""
    agent = AGENTS[agent_key]
    import requests

    headers = {
        "Authorization": f"Bearer {agent['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": agent["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(
            f"{agent['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERROR] {agent['name']} 调用失败: {e}"


def print_agent_header(agent_key, message=""):
    """打印带颜色的智能体消息头"""
    agent = AGENTS[agent_key]
    color = agent["color"]
    header = f"{color}[{agent['name']}] {agent['role']}{COLOR_RESET}"
    border = "=" * 60
    print(f"\n{border}")
    print(f" {header}")
    if message:
        print(f" {message}")
    print(f"{border}\n")


# =============================================
# 任务管理
# =============================================
def save_task(task_id, agent_key, prompt, result):
    """保存任务结果到文件"""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    task_file = TASKS_DIR / f"{task_id}.json"
    task_data = {
        "task_id": task_id,
        "agent": agent_key,
        "agent_name": AGENTS[agent_key]["name"],
        "prompt": prompt,
        "result": result,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)
    print(f"  → 任务已保存: {task_file}")


def list_tasks():
    """列出所有已保存的任务"""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    task_files = sorted(TASKS_DIR.glob("*.json"))
    if not task_files:
        print("暂无任务记录")
        return
    print(f"\n{'='*60}")
    print(f" 任务列表 ({len(task_files)} 个)")
    print(f"{'='*60}")
    for tf in task_files:
        with open(tf, encoding="utf-8") as f:
            data = json.load(f)
        print(f"  [{data['task_id']}] {data['agent_name']} | {data['timestamp'][:19]}")
        print(f"      任务: {data['prompt'][:80]}...")


def get_task_context(task_id):
    """获取指定任务的结果作为上下文"""
    task_file = TASKS_DIR / f"{task_id}.json"
    if not task_file.exists():
        return None
    with open(task_file, encoding="utf-8") as f:
        return json.load(f)


# =============================================
# 系统提示词
# =============================================
def get_system_prompt(agent_key):
    """获取每个智能体的系统提示词"""
    agent = AGENTS[agent_key]
    responsibilities = "\n".join([f"  - {r}" for r in agent["responsibility"]])
    return f"""你是 **{agent['name']}**，担任 **Ainos OS** 项目中的 **{agent['role']}**。

Ainos OS 是一个原生支持 AI 的 Linux 操作系统，核心理念：
1. 离线优先 — 所有基础功能不依赖 AI，AI 是锦上添花
2. AI 是系统服务 — 像显卡驱动一样，AI 是系统级能力
3. 云端/本地透明切换 — 有网用大模型，离线用小模型

你的职责：
{responsibilities}

项目目录结构：
  D:/Ainos/
    ├── docs/          # 文档
    ├── kernel/        # Linux内核模块
    ├── ai-runtime/    # AI Runtime系统服务
    ├── system-services/ # 系统服务
    ├── drivers/       # 驱动
    ├── userland/      # 用户空间
    ├── scripts/       # 构建脚本
    ├── configs/       # 配置文件
    └── weelink-agent/ # 多智能体协作

回复要求：
- 给出具体、可执行的代码或配置
- 包含完整的文件路径（相对于 D:/Ainos/）
- 使用 Markdown 格式
- 代码块标注语言类型
"""


# =============================================
# 多智能体协作模式
# =============================================
def collaborative_work(task_description, involved_agents=None):
    """多智能体协作：所有或指定智能体围绕同一任务工作"""
    if involved_agents is None:
        involved_agents = list(AGENTS.keys())

    task_id = f"task-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    results = {}

    print(f"\n{'='*60}")
    print(f" 🤖 Ainos OS 多智能体协作开始")
    print(f" 任务: {task_description}")
    print(f" 参与: {', '.join(AGENTS[a]['name'] for a in involved_agents)}")
    print(f" ID: {task_id}")
    print(f"{'='*60}\n")

    # Phase 1: 每个智能体独立工作
    threads = []
    results_lock = threading.Lock()

    def worker(agent_key):
        agent = AGENTS[agent_key]
        messages = [
            {"role": "system", "content": get_system_prompt(agent_key)},
            {"role": "user", "content": task_description},
        ]
        print_agent_header(agent_key, "正在处理...")
        result = call_ai(agent_key, messages)
        with results_lock:
            results[agent_key] = result
        # 打印结果摘要
        print(f"\n{agent['color']}── {agent['name']} 输出 ({len(result)} 字) ──{COLOR_RESET}")
        # 显示前500字
        preview = result[:500] + ("..." if len(result) > 500 else "")
        print(preview)
        print()

    for agent_key in involved_agents:
        t = threading.Thread(target=worker, args=(agent_key,))
        threads.append(t)
        t.start()
        time.sleep(1)  # 错开请求避免限流

    for t in threads:
        t.join()

    # 保存所有结果
    for agent_key, result in results.items():
        save_task(f"{task_id}-{agent_key}", agent_key, task_description, result)

    # Phase 2: 首席架构师总结
    print(f"\n{'='*60}")
    print(f" 📋 首席架构师综合总结")
    print(f"{'='*60}\n")

    summary_prompt = f"""作为首席架构师，请综合所有AI助手对以下任务的输出，给出一个统一的实施方案：

任务: {task_description}

各智能体的输出摘要：
"""
    for agent_key, result in results.items():
        summary_prompt += f"\n--- {AGENTS[agent_key]['name']} ---\n{result[:1500]}\n"

    summary_prompt += "\n\n请综合以上所有建议，输出一个统一的实施方案，包含：\n1. 技术方案（采纳谁的建议、为什么）\n2. 具体实施步骤\n3. 文件变更清单\n4. 注意事项"

    messages = [
        {"role": "system", "content": get_system_prompt("architect")},
        {"role": "user", "content": summary_prompt},
    ]
    summary = call_ai("architect", messages)
    print(summary[:800] + ("..." if len(summary) > 800 else ""))

    # 保存总结
    save_task(f"{task_id}-summary", "architect", f"综合总结: {task_description}", summary)

    return results, summary


def single_agent(agent_key, task_description):
    """单个智能体执行任务"""
    agent = AGENTS[agent_key]
    task_id = f"task-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{agent_key}"

    print_agent_header(agent_key)
    messages = [
        {"role": "system", "content": get_system_prompt(agent_key)},
        {"role": "user", "content": task_description},
    ]
    result = call_ai(agent_key, messages)
    print(result)
    save_task(task_id, agent_key, task_description, result)
    return result


def list_available_models():
    """列出所有可用的智能体"""
    print(f"\n{'='*60}")
    print(f" Ainos OS AI 智能体团队")
    print(f"{'='*60}\n")
    for key, agent in AGENTS.items():
        color = agent["color"]
        print(f"  {color}{agent['name']}{COLOR_RESET}")
        print(f"  ├─ 角色: {agent['role']}")
        print(f"  ├─ 模型: {agent['model']}")
        print(f"  └─ 职责:")
        for r in agent["responsibility"]:
            print(f"      - {r}")
        print()


# =============================================
# 主入口
# =============================================
def main():
    parser = argparse.ArgumentParser(
        description="Ainos OS 多智能体协作系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python orchestrator.py --task "设计AI系统调用的接口规范"
  python orchestrator.py --agent architect --task "设计内核模块接口"
  python orchestrator.py --agent kernel --task "实现AI调度器"
  python orchestrator.py --agent ai-runtime --task "设计GGML集成方案"
  python orchestrator.py --agent userland --task "设计桌面环境框架"
  python orchestrator.py --list
  python orchestrator.py --status
  python orchestrator.py --collaborate "设计系统总体架构"
        """,
    )
    parser.add_argument("--task", "-t", help="任务描述")
    parser.add_argument("--agent", "-a", choices=list(AGENTS.keys()), help="指定智能体")
    parser.add_argument("--list", "-l", action="store_true", help="列出智能体")
    parser.add_argument("--status", "-s", action="store_true", help="查看任务状态")
    parser.add_argument("--collaborate", "-c", help="多智能体协作模式")
    parser.add_argument("--agents", nargs="+", choices=list(AGENTS.keys()), help="协作模式下参与的智能体")

    args = parser.parse_args()

    if args.list:
        list_available_models()
        return

    if args.status:
        list_tasks()
        return

    if args.collaborate:
        involved = args.agents if args.agents else None
        collaborative_work(args.collaborate, involved)
        return

    if args.task and args.agent:
        single_agent(args.agent, args.task)
        return

    if args.task:
        collaborative_work(args.task)
        return

    # 交互模式
    list_available_models()
    print("输入任务描述（或 Ctrl+C 退出）:")
    try:
        while True:
            task = input("\n> ").strip()
            if not task:
                continue
            if task.lower() in ("exit", "quit", "q"):
                break
            collaborative_work(task)
    except (KeyboardInterrupt, EOFError):
        print("\n\n再见！")


if __name__ == "__main__":
    main()