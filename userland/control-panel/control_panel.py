#!/usr/bin/env python3
"""
Ainos OS 控制面板 - 系统状态监控与 AI 管理
=============================================
用法:
  python3 control_panel.py          # 启动 TUI 界面
  python3 control_panel.py --status # 快速查看状态
  python3 control_panel.py --list   # 列出模型
"""

import json
import os
import sys
import time
import socket
import argparse
from datetime import datetime

SOCKET_PATH = "/var/run/ainos/ai-daemon.sock"

class AinosClient:
    """AI 守护进程 IPC 客户端"""

    def __init__(self, socket_path=SOCKET_PATH):
        self.socket_path = socket_path
        self.sock = None

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.connect(self.socket_path)
            return True
        except (FileNotFoundError, ConnectionRefusedError):
            return False

    def send_request(self, request):
        if not self.sock:
            if not self.connect():
                return None
        self.sock.sendall((json.dumps(request) + "\n").encode())
        response = self.sock.recv(65536).decode()
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"type": "Error", "message": "Invalid response"}

    def get_status(self):
        return self.send_request({"type": "Status"})

    def list_models(self):
        return self.send_request({"type": "ModelList"})

    def close(self):
        if self.sock:
            self.sock.close()


def show_status():
    """显示系统状态"""
    client = AinosClient()
    if not client.connect():
        print("⚠ AI 守护进程未运行")
        print("  请先启动: sudo systemctl start ai-daemon")
        return

    status = client.get_status()
    if status and status.get("type") == "StatusResponse":
        print("\n" + "=" * 50)
        print("  Ainos OS - AI 系统状态")
        print("=" * 50)
        print(f"  运行时间:    {status['uptime']} 秒")
        print(f"  已加载模型:  {status['models_loaded']}")
        print(f"  总请求数:    {status['total_requests']}")
        print(f"  网络状态:    {'在线' if status['network_available'] else '离线'}")
        print("=" * 50)
    else:
        print("⚠ 无法获取状态")

    client.close()


def show_models():
    """列出模型"""
    client = AinosClient()
    if not client.connect():
        print("⚠ AI 守护进程未运行")
        return

    models = client.list_models()
    if models and models.get("type") == "ModelListResponse":
        print("\n" + "=" * 60)
        print("  已安装模型")
        print("=" * 60)
        for m in models["models"]:
            status_str = "✓ 已加载" if m["loaded"] else " 未加载"
            print(f"  {m['name']:<40} {m['size_mb']:>6}MB  {status_str}")
        print("=" * 60)
    else:
        print("⚠ 无法获取模型列表")

    client.close()


class TUI:
    """终端 UI"""

    def __init__(self):
        self.client = AinosClient()

    def clear(self):
        os.system("cls" if os.name == "nt" else "clear")

    def print_header(self):
        print("=" * 60)
        print("  🖥  Ainos OS - AI 系统控制面板")
        print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("=" * 60)

    def print_menu(self):
        print("\n  1) 系统状态")
        print("  2) 模型管理")
        print("  3) AI 推理测试")
        print("  4) 上下文管理")
        print("  5) 实时监控")
        print("  q) 退出")
        print()

    def show_system_status(self):
        self.clear()
        self.print_header()
        print("\n  📊 系统状态\n")

        if not self.client.connect():
            print("  ⚠ AI 守护进程未运行")
            print("  请先启动: sudo systemctl start ai-daemon")
            input("\n  按回车返回...")
            return

        status = self.client.get_status()
        if status and status.get("type") == "StatusResponse":
            print(f"  运行时间:      {status['uptime']} 秒")
            print(f"  已加载模型:    {status['models_loaded']}")
            print(f"  总请求数:      {status['total_requests']}")
            print(f"  网络状态:      {'✓ 在线' if status['network_available'] else '✗ 离线'}")
            print(f"  AI 子系统版本: 0.1.0")
        else:
            print("  ⚠ 无法获取状态")

        # 尝试通过内核接口获取
        try:
            with open("/dev/ainos", "r") as f:
                print("  /dev/ainos: ✓ 可用")
        except (FileNotFoundError, PermissionError):
            print("  /dev/ainos: ⚠ 内核模块未加载")

        input("\n  按回车返回...")
        self.client.close()

    def run(self):
        if not self.client.connect():
            print("\n  ⚠ AI 守护进程未运行")
            print("  部分功能不可用")
            time.sleep(2)

        while True:
            self.clear()
            self.print_header()
            self.print_menu()

            choice = input("  请选择: ").strip()

            if choice == "1":
                self.show_system_status()
            elif choice == "2":
                show_models()
                input("\n  按回车返回...")
            elif choice == "3":
                self.run_inference_test()
            elif choice == "q":
                break
            else:
                print("  无效选择")
                time.sleep(1)

        self.client.close()
        print("\n  再见！\n")

    def run_inference_test(self):
        self.clear()
        self.print_header()
        print("\n  🤖 AI 推理测试\n")

        if not self.client.connect():
            print("  ⚠ AI 守护进程未运行")
            input("\n  按回车返回...")
            return

        prompt = input("  输入提示词: ").strip()
        if not prompt:
            prompt = "What is Ainos OS?"

        print(f"\n  发送推理请求...")
        response = self.client.send_request({
            "type": "Inference",
            "model": "default",
            "prompt": prompt,
            "temperature": 0.7,
            "max_tokens": 256,
        })

        if response and response.get("type") == "InferenceResponse":
            print(f"\n  📝 响应:")
            print(f"  {response['output']}")
            print(f"\n  Token: {response['tokens_generated']}")
            print(f"  耗时: {response['inference_ms']} ms")
            print(f"  来源: {response['source']}")
        else:
            print(f"\n  ⚠ 推理失败: {response}")

        input("\n  按回车返回...")
        self.client.close()


def main():
    parser = argparse.ArgumentParser(description="Ainos OS Control Panel")
    parser.add_argument("--status", action="store_true", help="显示系统状态")
    parser.add_argument("--list", action="store_true", help="列出模型")
    parser.add_argument("--tui", action="store_true", help="启动终端界面")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.list:
        show_models()
    else:
        tui = TUI()
        tui.run()


if __name__ == "__main__":
    main()