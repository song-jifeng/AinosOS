#!/usr/bin/env python3
"""
Ainos OS - Windows 系统托盘
通过系统托盘图标管理 ai-daemon 进程

用法:
  python ainos_tray.py
  python ainos_tray.py --start    # 启动守护进程并打开托盘
  python ainos_tray.py --stop     # 停止守护进程
"""

import argparse
import os
import subprocess
import sys
import time
import json
import socket
import threading
from pathlib import Path
from datetime import datetime

# 尝试导入 pystray（可选）
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

DAEMON_DIR = Path(__file__).resolve().parent.parent
DAEMON_EXE = DAEMON_DIR / "system-services" / "ai-daemon" / "target" / "release" / "ai-daemon.exe"
CONFIG_PATH = DAEMON_DIR / "configs" / "ai-daemon.toml"
LOG_DIR = DAEMON_DIR / "logs"
TRAY_LOG = LOG_DIR / "tray.log"

LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(TRAY_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check_daemon() -> bool:
    """检查守护进程是否在运行"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("127.0.0.1", 9500))
        s.sendall(b'{"type":"Status"}\n')
        resp = s.recv(4096)
        s.close()
        return len(resp) > 0
    except Exception:
        return False


def get_daemon_status() -> dict:
    """获取守护进程状态"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(("127.0.0.1", 9500))
        s.sendall(b'{"type":"Status"}\n')
        resp = s.recv(8192)
        s.close()
        return json.loads(resp.decode("utf-8").strip())
    except Exception as e:
        return {"error": str(e)}


def start_daemon():
    """启动守护进程"""
    if check_daemon():
        log("守护进程已在运行")
        return True

    if not DAEMON_EXE.exists():
        log(f"未找到守护进程: {DAEMON_EXE}")
        log("请先编译: cd system-services/ai-daemon && cargo build --release")
        return False

    try:
        proc = subprocess.Popen(
            [str(DAEMON_EXE), "-c", str(CONFIG_PATH), "-v"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(DAEMON_DIR),
        )
        log(f"守护进程已启动 (PID: {proc.pid})")
        time.sleep(1)
        return True
    except Exception as e:
        log(f"启动失败: {e}")
        return False


def stop_daemon():
    """停止守护进程"""
    if not check_daemon():
        log("守护进程未运行")
        return True

    try:
        subprocess.run(["taskkill", "/F", "/IM", "ai-daemon.exe"],
                      capture_output=True, timeout=10)
        log("守护进程已停止")
        return True
    except subprocess.TimeoutExpired:
        log("停止超时")
        return False
    except Exception as e:
        log(f"停止失败: {e}")
        return False


def create_tray_icon():
    """创建系统托盘图标"""
    if not HAS_TRAY:
        log("未安装 pystray，请安装: pip install pystray pillow")
        return None

    # 创建图标（16x16 绿色/红色圆点）
    def create_image(color):
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 13, 13], fill=color)
        return img

    running = check_daemon()
    icon_color = "#00cc44" if running else "#cc4444"
    icon = pystray.Icon(
        "ainos",
        create_image(icon_color),
        f"Ainos OS {'运行中' if running else '已停止'}",
    )

    # 构建菜单
    def on_start(icon, item):
        start_daemon()
        icon.icon = create_image("#00cc44")
        icon.title = "Ainos OS 运行中"
        icon.update_menu()

    def on_stop(icon, item):
        stop_daemon()
        icon.icon = create_image("#cc4444")
        icon.title = "Ainos OS 已停止"
        icon.update_menu()

    def on_status(icon, item):
        status = get_daemon_status()
        if "error" in status:
            log(f"状态查询失败: {status['error']}")
        else:
            log(f"状态: 运行中, 请求数={status.get('total_requests', '?')}")

    def on_web(icon, item):
        import webbrowser
        webbrowser.open("http://127.0.0.1:9501")

    def on_quit(icon, item):
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("启动守护进程", on_start, enabled=lambda: not check_daemon()),
        pystray.MenuItem("停止守护进程", on_stop, enabled=check_daemon),
        pystray.MenuItem("查看状态", on_status),
        pystray.MenuItem("打开 Web 面板", on_web),
        pystray.MenuItem("退出", on_quit),
    )

    return icon


def main():
    parser = argparse.ArgumentParser(description="Ainos OS 系统托盘")
    parser.add_argument("--start", action="store_true", help="启动守护进程")
    parser.add_argument("--stop", action="store_true", help="停止守护进程")
    parser.add_argument("--status", action="store_true", help="查看状态")
    args = parser.parse_args()

    if args.start:
        start_daemon()
        return

    if args.stop:
        stop_daemon()
        return

    if args.status:
        running = check_daemon()
        if running:
            status = get_daemon_status()
            print(f"状态: 运行中")
            print(f"  请求数: {status.get('total_requests', 0)}")
            print(f"  模型已加载: {status.get('models_loaded', 0)}")
            print(f"  运行时间: {status.get('uptime', 0)}s")
        else:
            print("状态: 未运行")
        return

    # 启动系统托盘
    icon = create_tray_icon()
    if icon:
        log("系统托盘已启动")
        icon.run()
    else:
        print("请安装 pystray: pip install pystray pillow")
        print("或者使用 --start/--stop/--status 管理守护进程")


if __name__ == "__main__":
    main()