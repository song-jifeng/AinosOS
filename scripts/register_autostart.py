#!/usr/bin/env python3
"""
Ainos OS - 开机自启注册脚本

用法:
  python register_autostart.py              # 注册开机自启
  python register_autostart.py --remove     # 取消注册
  python register_autostart.py --check      # 检查是否已注册
"""

import argparse
import os
import sys
import platform
from pathlib import Path


def get_tray_script_path() -> str:
    """获取系统托盘脚本的绝对路径"""
    script = Path(__file__).resolve()
    return str(script.parent / "ainos_tray.py")


def register_windows():
    """注册 Windows 开机自启"""
    import winreg

    tray_script = get_tray_script_path()
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "AinosOS"

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, f'python "{tray_script}" --start')
        winreg.CloseKey(key)
        print(f"✓ 已注册开机自启: {value_name}")
        return True
    except Exception as e:
        print(f"✗ 注册失败: {e}")
        return False


def unregister_windows():
    """取消 Windows 开机自启"""
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "AinosOS"

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, value_name)
            print(f"✓ 已取消开机自启: {value_name}")
        except FileNotFoundError:
            print("未注册开机自启")
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"✗ 取消注册失败: {e}")
        return False


def check_windows():
    """检查 Windows 开机自启状态"""
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "AinosOS"

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        try:
            value, _ = winreg.QueryValueEx(key, value_name)
            winreg.CloseKey(key)
            print(f"✓ 已注册开机自启: {value}")
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            print("未注册开机自启")
            return False
    except Exception as e:
        print(f"✗ 检查失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Ainos OS 开机自启注册")
    parser.add_argument("--remove", action="store_true", help="取消注册")
    parser.add_argument("--check", action="store_true", help="检查是否已注册")
    args = parser.parse_args()

    system = platform.system()

    if system != "Windows":
        print(f"当前系统: {system}")
        print("开机自启脚本目前仅支持 Windows")
        print("Linux 请使用: sudo systemctl enable ai-daemon")
        return

    if args.check:
        check_windows()
    elif args.remove:
        unregister_windows()
    else:
        register_windows()


if __name__ == "__main__":
    main()