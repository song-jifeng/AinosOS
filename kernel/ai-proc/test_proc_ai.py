"""
Ainos OS - /proc/ai 集成测试
测试所有 7 个文件节点的功能

运行:
  python3 test_proc_ai.py [--device /dev/ainos-proc]
"""

import os
import sys
import time
import json
import struct
import fcntl
import argparse
from pathlib import Path

PROC_AI_DIR = "/proc/ai"

# IOCTL 命令 (与 proc_ai.h 一致)
AI_PROC_IOC_MAGIC = ord('P')
AI_PROC_GET_REQUEST = 0x80045001  # _IOR('P', 1, struct)
AI_PROC_SEND_RESPONSE = 0x40045002  # _IOW('P', 2, struct)

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

def check_proc_file(filename, should_exist=True):
    path = f"{PROC_AI_DIR}/{filename}"
    exists = os.path.exists(path)
    test(f"/proc/ai/{filename} {'exists' if should_exist else 'removed'}",
         exists == should_exist,
         f"expected exists={should_exist}, got {exists}")
    return path if exists else None

def read_proc_file(path):
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {e}"

def write_proc_file(path, data):
    try:
        with open(path, 'w') as f:
            return f.write(data)
    except Exception as e:
        return f"ERROR: {e}"

def test_status():
    print("\n[1/7] /proc/ai/status - System Status")
    path = check_proc_file("status")
    if not path:
        return

    content = read_proc_file(path)
    test("status content not empty", len(content) > 0, f"got {len(content)} chars")
    test("status shows 'running'", "running" in content, content[:100])
    test("status shows version", "version" in content or "Version" in content)
    test("status shows stats", "inferences" in content.lower())

    # Test write
    write_proc_file(path, "reset stats")
    content2 = read_proc_file(path)
    test("status write works", "running" in content2)

def test_infer():
    print("\n[2/7] /proc/ai/infer - AI Inference")
    path = check_proc_file("infer")
    if not path:
        return

    # Read without write
    content = read_proc_file(path)
    test("infer read returns message", "No inference" in content or "available" in content,
         content[:100])

    # Write
    result = write_proc_file(path, "Hello, Ainos!")
    test("infer write accepts input", result is None or result > 0,
         f"write returned {result}")

    # Read after write
    time.sleep(0.1)
    content = read_proc_file(path)
    test("infer read after write", len(content) > 0, content[:100])

def test_embed():
    print("\n[3/7] /proc/ai/embed - Text Embedding")
    path = check_proc_file("embed")
    if not path:
        return

    content = read_proc_file(path)
    test("embed read returns message", len(content) > 0, content[:100])

    result = write_proc_file(path, "Embed this text")
    test("embed write accepts input", result is None or result > 0)

    time.sleep(0.1)
    content = read_proc_file(path)
    test("embed read after write", len(content) > 0, content[:100])

def test_chat():
    print("\n[4/7] /proc/ai/chat - Chat Session")
    path = check_proc_file("chat")
    if not path:
        return

    result = write_proc_file(path, "Hello, what is Ainos?")
    test("chat write accepts input", result is None or result > 0)

    time.sleep(0.1)
    content = read_proc_file(path)
    test("chat read returns response", len(content) > 0, content[:100])

def test_models():
    print("\n[5/7] /proc/ai/models - Model List")
    path = check_proc_file("models")
    if not path:
        return

    content = read_proc_file(path)
    test("models content not empty", len(content) > 0, content[:200])

def test_config():
    print("\n[6/7] /proc/ai/config - Configuration")
    path = check_proc_file("config")
    if not path:
        return

    content = read_proc_file(path)
    test("config content not empty", len(content) > 0, content[:200])
    test("config shows version", "version" in content.lower())

    # Test write
    result = write_proc_file(path, "refresh models")
    test("config write 'refresh models'", result is None or result > 0)

    result = write_proc_file(path, "reset stats")
    test("config write 'reset stats'", result is None or result > 0)

def test_stats():
    print("\n[7/7] /proc/ai/stats - Statistics")
    path = check_proc_file("stats")
    if not path:
        return

    content = read_proc_file(path)
    test("stats content not empty", len(content) > 0, content[:200])
    test("stats shows uptime", "uptime" in content.lower())
    test("stats shows counters", "infer" in content.lower() or "total" in content.lower())

def test_device():
    print("\n[Extra] /dev/ainos-proc - Misc Device")
    device_path = "/dev/ainos-proc"
    exists = os.path.exists(device_path)
    test(f"{device_path} exists", exists)
    if exists:
        try:
            fd = os.open(device_path, os.O_RDWR)
            test("device openable", True)
            os.close(fd)
        except Exception as e:
            test(f"device openable", False, str(e))

def main():
    parser = argparse.ArgumentParser(description="Ainos /proc/ai integration test")
    parser.add_argument("--device", default="/dev/ainos-proc",
                       help="Misc device path")
    parser.add_argument("--quick", action="store_true",
                       help="Skip write tests")
    args = parser.parse_args()

    print("=" * 60)
    print("Ainos OS - /proc/ai Integration Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Check if module is loaded
    if not os.path.exists(PROC_AI_DIR):
        print(f"\nERROR: {PROC_AI_DIR} does not exist!")
        print("Load the module first: sudo insmod proc_ai.ko")
        sys.exit(1)

    print(f"\n/proc/ai files:")
    for f in sorted(os.listdir(PROC_AI_DIR)):
        print(f"  {f}")

    # Run tests
    test_status()
    test_models()
    test_config()
    test_stats()
    test_device()

    if not args.quick:
        test_infer()
        test_embed()
        test_chat()

    # Summary
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