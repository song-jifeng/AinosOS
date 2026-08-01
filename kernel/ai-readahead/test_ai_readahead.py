#!/usr/bin/env python3
"""
Ainos OS - AI Readahead 模块集成测试
"""

import os
import sys
import time

PROC = "/proc/ai-readahead"
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

def test_basic():
    print("\n[1/4] Basic Files")
    expected = ["status", "files", "config"]
    for f in expected:
        test(f"/proc/ai-readahead/{f} exists", os.path.exists(os.path.join(PROC, f)))
    files = sorted(os.listdir(PROC)) if os.path.exists(PROC) else []
    test(f"exactly {len(expected)} files", len(files) == len(expected), f"{files}")

def test_status():
    print("\n[2/4] Status")
    content = read_file(os.path.join(PROC, "status"))
    test("not empty", len(content) > 0, f"{len(content)} chars")
    test("version", "2.0.0" in content, content[:50])
    test("tracked files", "Tracked Files" in content, content[:200])
    test("predictions", "Predictions" in content, content[:200])
    test("windows", "Window" in content, content[:200])

def test_config():
    print("\n[3/4] Config")
    content = read_file(os.path.join(PROC, "config"))
    test("not empty", len(content) > 0, f"{len(content)} chars")
    test("max_tracked", "max_tracked_files" in content, content[:200])
    test("windows", "seq_window" in content and "random_window" in content, content[:200])

    # Test write
    rc = write_file(os.path.join(PROC, "config"), "seq_window 64")
    test("config write", "ERROR" not in str(rc) if isinstance(rc, str) else True)
    time.sleep(0.1)
    c2 = read_file(os.path.join(PROC, "config"))
    test("config change reflected", "seq_window = 64" in c2, c2)

def test_files():
    print("\n[4/4] Files")
    content = read_file(os.path.join(PROC, "files"))
    test("file readable", len(content) > 0, f"{len(content)} chars")
    test("has header", "Model" in content and "File" in content, content[:100])

def main():
    print("=" * 60)
    print("Ainos OS - AI Readahead Module Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    if not os.path.exists(PROC):
        print(f"\nERROR: {PROC} does not exist!")
        print("Load: sudo insmod ai_readahead.ko")
        sys.exit(1)
    print(f"\n/proc/ai-readahead files:")
    for f in sorted(os.listdir(PROC)):
        print(f"  {f}")
    test_basic()
    test_status()
    test_config()
    test_files()
    total = PASS + FAIL
    print("\n" + "=" * 60)
    print(f"Results: {PASS}/{total} passed")
    if FAIL == 0: print("[ALL PASS]")
    else: print(f"[{FAIL} FAILURES]")
    print("=" * 60)
    return 0 if FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())