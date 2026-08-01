#!/usr/bin/env python3
"""
Ainos AI Terminal - AI 增强型终端
====================================
在终端中直接使用 AI 能力，无需离开命令行。

用法:
  ai "写一个 Python 快速排序"     # 代码生成
  ai --chat "今天天气怎么样?"       # 对话模式
  ai --search "如何配置网络"       # 语义搜索
  ai --ask "这个文件有什么问题?"    # 文件分析
"""

import argparse
import json
import os
import sys
import socket
import subprocess
from pathlib import Path

SOCKET_PATH = "/var/run/ainos/ai-daemon.sock"
CACHE_DIR = Path.home() / ".ainos" / "cache"
CONFIG_FILE = Path.home() / ".ainos" / "config.json"

def init_config():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w") as f:
            json.dump({"default_model": "local", "temperature": 0.7, "max_tokens": 2048}, f)

def load_config():
    init_config()
    with open(CONFIG_FILE) as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def query_ai(prompt, mode="infer"):
    """向 AI 守护进程发送请求"""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return None

    config = load_config()
    request = {
        "type": "Inference",
        "model": config.get("default_model", "default"),
        "prompt": prompt,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 2048),
    }

    try:
        sock.sendall((json.dumps(request) + "\n").encode())
        response = sock.recv(65536).decode()
        result = json.loads(response)
        sock.close()
        return result
    except (socket.timeout, json.JSONDecodeError) as e:
        sock.close()
        return {"type": "Error", "message": str(e)}

def infer(prompt, stream=False):
    """执行推理"""
    result = query_ai(prompt)
    if result is None:
        # AI 守护进程不可用，回退到本地模拟
        print(f"[AI 离线模式]")
        print(f"[提示]: {prompt}")
        print(f"[响应]: AI 守护进程未运行，请启动: sudo systemctl start ai-daemon")
        return

    if result.get("type") == "InferenceResponse":
        print(result["output"])
        if result.get("tokens_generated"):
            print(f"\n--- {result['tokens_generated']} tokens, {result['source']}, {result['inference_ms']}ms ---")
    elif result.get("type") == "Error":
        print(f"错误: {result['message']}")

def chat_mode():
    """交互式对话模式"""
    print("Ainos AI Chat (输入 /exit 退出, /clear 清屏, /save 保存)")
    print("=" * 50)
    history = []

    while True:
        try:
            prompt = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not prompt:
            continue
        if prompt == "/exit":
            break
        if prompt == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue
        if prompt == "/save":
            save_chat(history)
            continue

        history.append({"role": "user", "content": prompt})
        result = query_ai(prompt)
        if result and result.get("type") == "InferenceResponse":
            print(f"AI  > {result['output']}")
            history.append({"role": "assistant", "content": result['output']})
        else:
            print(f"AI  > [无法连接 AI 守护进程]")

def save_chat(history):
    """保存对话历史"""
    timestamp = os.popen("date +%Y%m%d_%H%M%S").read().strip()
    path = CACHE_DIR / f"chat_{timestamp}.json"
    with open(path, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"对话已保存: {path}")

def main():
    parser = argparse.ArgumentParser(description="Ainos AI Terminal")
    parser.add_argument("prompt", nargs="*", help="提示词")
    parser.add_argument("--chat", "-c", action="store_true", help="对话模式")
    parser.add_argument("--search", "-s", help="语义搜索")
    parser.add_argument("--file", "-f", help="分析文件")
    parser.add_argument("--config", action="store_true", help="配置设置")

    args = parser.parse_args()

    if args.config:
        config = load_config()
        for k, v in config.items():
            print(f"  {k} = {v}")
        print("\n配置存储在:", CONFIG_FILE)
        return

    if args.chat:
        chat_mode()
        return

    if args.search:
        prompt = f"搜索: {args.search}"
        infer(prompt)
        return

    if args.file:
        try:
            with open(args.file) as f:
                content = f.read()
            prompt = f"分析以下文件 (路径: {args.file}):\n```\n{content[:4000]}\n```\n请分析这个文件的内容和用途。"
            infer(prompt)
        except FileNotFoundError:
            print(f"文件未找到: {args.file}")
        return

    if args.prompt:
        prompt = " ".join(args.prompt)
        infer(prompt)
        return

    # 交互模式
    chat_mode()

if __name__ == "__main__":
    main()