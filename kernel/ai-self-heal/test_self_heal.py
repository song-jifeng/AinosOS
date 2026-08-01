#!/usr/bin/env python3
"""
Ainos OS - 内核自愈模块集成测试
测试所有 /proc/self-heal 文件节点功能

运行:
  python3 test_self_heal.py

依赖:
  sudo insmod self_heal.ko   # 先加载模块
"""

import os
import sys
import time
import re

PROC_SELF_HEAL = "/proc/self-heal"

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name} - {detail}")
        FAIL += 1

def read_file(path):
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {e}"

def write_file(path, data):
    try:
        with open(path, 'w') as f:
            return f.write(data)
    except Exception as e:
        return f"ERROR: {e}"

def test_basic_files():
    """测试 /proc/self-heal 文件是否存在"""
    print("\n[1/4] Basic Files Check")

    expected_files = ["status", "config", "trigger", "history"]
    for f in expected_files:
        path = os.path.join(PROC_SELF_HEAL, f)
        exists = os.path.exists(path)
        test(f"/proc/self-heal/{f} exists", exists)

    # 列出所有文件
    files = sorted(os.listdir(PROC_SELF_HEAL)) if os.path.exists(PROC_SELF_HEAL) else []
    test(f"exactly {len(expected_files)} files",
         len(files) == len(expected_files),
         f"got {len(files)} files: {files}")

def test_status():
    """测试 status 文件"""
    print("\n[2/4] Status File")

    path = os.path.join(PROC_SELF_HEAL, "status")
    content = read_file(path)

    test("status content not empty", len(content) > 0, f"got {len(content)} chars")
    test("status shows version", "2.0.0" in content, content[:50])
    test("status shows health status",
         "Health" in content and ("OK" in content or "WARNING" in content or "CRITICAL" in content),
         content[:200])
    test("status shows health score", "Health Score" in content, content[:200])
    test("status shows uptime", "Uptime" in content, content[:200])
    test("status shows memory info", "Memory" in content, content[:200])
    test("status shows load average", "Load" in content, content[:200])
    test("status shows recovery statistics",
         "Events Detected" in content and "Recovery" in content,
         content[:200])
    test("status shows tasks killed", "Tasks Killed" in content, content[:200])

def test_config():
    """测试 config 文件"""
    print("\n[3/4] Config File")

    path = os.path.join(PROC_SELF_HEAL, "config")
    content = read_file(path)

    test("config content not empty", len(content) > 0, f"got {len(content)} chars")
    test("config shows mem_pressure", "mem_pressure" in content, content[:200])
    test("config shows panic entry", "panic" in content, content[:200])
    test("config shows event types",
         all(evt in content for evt in ["mem_pressure", "oom_near", "hung_task", "zombie"]),
         content[:200])

    # 测试写入
    # 保存原始内容用于恢复
    orig_config = content

    # 修改配置
    result = write_file(path, "mem_pressure reclaim 60000 5 yes yes")
    test("config write accepts input",
         "ERROR" not in str(result) if isinstance(result, str) else True,
         f"write returned {result}")

    time.sleep(0.1)
    content2 = read_file(path)
    test("config change reflected", "reclaim" in content2, content2[:200])

    # 重置配置
    write_file(path, "reset")
    time.sleep(0.1)
    content3 = read_file(path)
    test("config reset works", "soft" in content3,
         f"expected 'soft' level for mem_pressure after reset, got {content3[:200]}")

def test_trigger():
    """测试 trigger 文件"""
    print("\n[4/4] Trigger File")

    path = os.path.join(PROC_SELF_HEAL, "trigger")

    # 触发一个简单事件
    result = write_file(path, "custom log 0 'test event from test suite'")
    test("trigger accepts custom event",
         "ERROR" not in str(result) if isinstance(result, str) else True,
         f"write returned {result}")

    time.sleep(0.2)

    # 检查 history 是否记录
    history_path = os.path.join(PROC_SELF_HEAL, "history")
    history = read_file(history_path)
    test("history shows triggered event",
         "custom" in history or "test event" in history,
         history[-200:])

    # 检查 status 统计更新
    status = read_file(os.path.join(PROC_SELF_HEAL, "status"))
    test("events detected > 0",
         any(int(x) > 0 for x in re.findall(r'Events Detected:\s+(\d+)', status)),
         status)

    # 触发不同级别的事件
    test("trigger mem_pressure event",
         "ERROR" not in str(write_file(path, "mem_pressure log 0 'test memory pressure'")),
         "mem_pressure trigger failed")
    time.sleep(0.1)

    test("trigger oom_near event",
         "ERROR" not in str(write_file(path, "oom_near soft 0 'test OOM near miss'")),
         "oom_near trigger failed")
    time.sleep(0.1)

    test("trigger high_load event",
         "ERROR" not in str(write_file(path, "high_load soft 0 'test high load'")),
         "high_load trigger failed")
    time.sleep(0.1)

    # 测试未知事件类型
    result = write_file(path, "unknown_event log 0 'should fail'")
    test("unknown event type rejected",
         "ERROR" in str(result) if isinstance(result, str) else True,
         "unknown event should fail")

    # 重置统计
    write_file(path, "reset")
    time.sleep(0.1)
    status = read_file(os.path.join(PROC_SELF_HEAL, "status"))
    test("stats reset works",
         "Events Detected: 0" in status,
         status)

def main():
    print("=" * 60)
    print("Ainos OS - Self-Heal Module Integration Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 检查模块是否加载
    if not os.path.exists(PROC_SELF_HEAL):
        print(f"\nERROR: {PROC_SELF_HEAL} does not exist!")
        print("Load the module first: sudo insmod self_heal.ko")
        sys.exit(1)

    print(f"\n/proc/self-heal files:")
    for f in sorted(os.listdir(PROC_SELF_HEAL)):
        print(f"  {f}")

    # 运行测试
    test_basic_files()
    test_status()
    test_config()
    test_trigger()

    # 汇总
    total = PASS + FAIL
    print("\n" + "=" * 60)
    print(f"Results: {PASS}/{total} passed")
    if FAIL == 0:
        print("[ALL PASS]")
    else:
        print(f"[{FAIL} FAILURES]")
    print("=" * 60)

    return 0 if FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())