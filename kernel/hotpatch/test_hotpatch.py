#!/usr/bin/env python3
"""
Ainos OS - Hotpatch 模块集成测试
"""

import os, sys, time

PROC = "/proc/ai-hotpatch"
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

def test_basic():
    print("\n[1/5] Basic Files")
    expected = ["status", "patches", "hooks", "config"]
    for f in expected:
        test(f"/proc/ai-hotpatch/{f} exists", os.path.exists(os.path.join(PROC, f)))
    files = sorted(os.listdir(PROC)) if os.path.exists(PROC) else []
    test(f"exactly {len(expected)} files", len(files) == len(expected), f"{files}")

def test_status():
    print("\n[2/5] Status")
    c = read_file(os.path.join(PROC, "status"))
    test("not empty", len(c) > 0, f"{len(c)} chars")
    test("version", "2.0.0" in c, c[:50])
    test("shows patches", "Patches" in c, c[:200])
    test("shows hooks", "Hooks" in c, c[:200])
    test("shows safety", "Safety" in c, c[:200])

def test_patches():
    print("\n[3/5] Patches")
    c = read_file(os.path.join(PROC, "patches"))
    test("readable", len(c) > 0, f"{len(c)} chars")
    test("header", "Name" in c and "Target" in c, c[:100])

def test_hooks():
    print("\n[4/5] Hooks")
    c = read_file(os.path.join(PROC, "hooks"))
    test("readable", len(c) > 0, f"{len(c)} chars")
    test("header", "Function" in c and "Calls" in c, c[:100])

def test_config():
    print("\n[5/5] Config")
    c = read_file(os.path.join(PROC, "config"))
    test("readable", len(c) > 0, f"{len(c)} chars")
    test("max_patches", "max_patches" in c, c[:200])
    test("enable_patching", "enable_patching" in c, c[:200])

def main():
    print("=" * 60)
    print("Ainos OS - Hotpatch Module Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    if not os.path.exists(PROC):
        print(f"\nERROR: {PROC} does not exist!")
        sys.exit(1)
    print(f"\n/proc/ai-hotpatch files:")
    for f in sorted(os.listdir(PROC)):
        print(f"  {f}")
    test_basic()
    test_status()
    test_patches()
    test_hooks()
    test_config()
    total = PASS + FAIL
    print("\n" + "=" * 60)
    print(f"Results: {PASS}/{total} passed")
    if FAIL == 0: print("[ALL PASS]")
    else: print(f"[{FAIL} FAILURES]")
    print("=" * 60)
    return 0 if FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())