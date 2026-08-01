#!/usr/bin/env python3
"""
Ainos OS - AI KILL 模块集成测试
测试所有 /proc/ai-kill 文件节点功能

运行:
  python3 test_ai_kill.py
"""

import os
import sys
import time
import re

PROC_AI_KILL = "/proc/ai-kill"
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
    print("\n[1/5] Basic Files Check")
    expected = ["scores", "config", "stats", "history", "behavior"]
    for f in expected:
        path = os.path.join(PROC_AI_KILL, f)
        exists = os.path.exists(path)
        test(f"/proc/ai-kill/{f} exists", exists)

    files = sorted(os.listdir(PROC_AI_KILL)) if os.path.exists(PROC_AI_KILL) else []
    test(f"exactly {len(expected)} files", len(files) == len(expected),
         f"got {len(files)}: {files}")

def test_scores():
    print("\n[2/5] Scores File")
    content = read_file(os.path.join(PROC_AI_KILL, "scores"))
    test("scores content not empty", len(content) > 0, f"{len(content)} chars")
    test("scores has header", "PID" in content and "COMM" in content, content[:100])
    test("scores has dimensions", "CPU" in content and "MEM" in content and "TOTAL" in content,
         content[:100])

def test_config():
    print("\n[3/5] Config File")
    content = read_file(os.path.join(PROC_AI_KILL, "config"))
    test("config not empty", len(content) > 0, f"{len(content)} chars")
    test("config shows enabled", "enabled" in content, content[:200])
    test("config shows thresholds", "thresholds" in content, content[:200])
    test("config shows weights", "cpu" in content and "mem" in content, content[:200])

    # Test write
    result = write_file(os.path.join(PROC_AI_KILL, "config"), "threshold 30 50 70")
    test("config write threshold", "ERROR" not in str(result) if isinstance(result, str) else True)
    time.sleep(0.1)
    c2 = read_file(os.path.join(PROC_AI_KILL, "config"))
    test("threshold change reflected", "30 / 50 / 70" in c2, c2)

    # Test weight write
    write_file(os.path.join(PROC_AI_KILL, "config"), "weight mem 30")
    time.sleep(0.1)
    c3 = read_file(os.path.join(PROC_AI_KILL, "config"))
    test("weight change reflected", "mem" in c3 and "30" in c3, c3)

    # Reset
    write_file(os.path.join(PROC_AI_KILL, "config"), "reset")
    time.sleep(0.1)
    c4 = read_file(os.path.join(PROC_AI_KILL, "config"))
    test("config reset works", "40 / 60 / 80" in c4, c4)

def test_stats():
    print("\n[4/5] Stats File")
    content = read_file(os.path.join(PROC_AI_KILL, "stats"))
    test("stats not empty", len(content) > 0, f"{len(content)} chars")
    test("stats shows scan count", "scans_total" in content, content[:200])
    test("stats shows kill count", "actions_kill" in content, content[:200])
    test("stats shows whitelist hits", "whitelist_hits" in content, content[:200])

def test_history_and_behavior():
    print("\n[5/5] History & Behavior Files")
    h = read_file(os.path.join(PROC_AI_KILL, "history"))
    test("history file readable", "No kill history" in h or "PID" in h, h[:100])

    b = read_file(os.path.join(PROC_AI_KILL, "behavior"))
    test("behavior file readable", len(b) > 0, f"{len(b)} chars")
    test("behavior shows PID header", "PID" in b, b[:100])

def main():
    print("=" * 60)
    print("Ainos OS - AI KILL Module Integration Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not os.path.exists(PROC_AI_KILL):
        print(f"\nERROR: {PROC_AI_KILL} does not exist!")
        print("Load the module first: sudo insmod ai_kill.ko")
        sys.exit(1)

    print(f"\n/proc/ai-kill files:")
    for f in sorted(os.listdir(PROC_AI_KILL)):
        print(f"  {f}")

    test_basic_files()
    test_scores()
    test_config()
    test_stats()
    test_history_and_behavior()

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