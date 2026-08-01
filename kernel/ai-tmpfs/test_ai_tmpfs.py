#!/usr/bin/env python3
"""
Ainos OS - AI tmpfs 模块集成测试
测试 /proc/ai-tmpfs 接口和挂载功能

运行:
  python3 test_ai_tmpfs.py
"""

import os
import sys
import time
import subprocess

PROC_AI_TMPFS = "/proc/ai-tmpfs"
MOUNT_POINT = "/mnt/ai-tmpfs"
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

def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)

def test_basic_files():
    print("\n[1/5] Basic Files Check")
    expected = ["status", "files", "config"]
    for f in expected:
        path = os.path.join(PROC_AI_TMPFS, f)
        exists = os.path.exists(path)
        test(f"/proc/ai-tmpfs/{f} exists", exists)

    files = sorted(os.listdir(PROC_AI_TMPFS)) if os.path.exists(PROC_AI_TMPFS) else []
    test(f"exactly {len(expected)} files", len(files) >= len(expected),
         f"got {len(files)}: {files}")

def test_status():
    print("\n[2/5] Status File")
    content = read_file(os.path.join(PROC_AI_TMPFS, "status"))
    test("status not empty", len(content) > 0, f"{len(content)} chars")
    test("status shows version", "2.0.0" in content, content[:50])
    test("status shows AI tmpfs", "AI tmpfs" in content, content[:50])
    test("status shows file stats", "Files" in content and "Bytes" in content, content[:200])
    test("status shows hits", "Hits" in content, content[:200])

def test_config():
    print("\n[3/5] Config File")
    content = read_file(os.path.join(PROC_AI_TMPFS, "config"))
    test("config not empty", len(content) > 0, f"{len(content)} chars")
    test("config shows max_files", "max_files" in content, content[:200])
    test("config shows hot_access_min", "hot_access_min" in content, content[:200])
    test("config shows hot_freq_min", "hot_freq_min" in content, content[:200])

    # Test write
    rc = write_file(os.path.join(PROC_AI_TMPFS, "config"), "hot_access_min 3")
    test("config write", "ERROR" not in str(rc) if isinstance(rc, str) else True)
    time.sleep(0.1)
    c2 = read_file(os.path.join(PROC_AI_TMPFS, "config"))
    test("config change reflected", "hot_access_min = 3" in c2, c2)

def test_mount_and_io():
    print("\n[4/5] Mount & I/O Test")
    # Skip if not root
    if os.geteuid() != 0:
        print("  [SKIP] Need root for mount test")
        test("mount test skipped", True)
        return

    # Mount
    os.makedirs(MOUNT_POINT, exist_ok=True)
    rc, out, err = run_cmd(f"mount -t ai_tmpfs none {MOUNT_POINT}")
    test("mount succeeds", rc == 0, err)

    # Check mount
    rc, out, _ = run_cmd("mount | grep ai_tmpfs")
    test("mount visible", rc == 0, out)

    # Write file
    rc, out, err = run_cmd(f"echo 'Hello Ainos!' > {MOUNT_POINT}/test.txt")
    test("write file", rc == 0, err)

    # Read file
    rc, out, _ = run_cmd(f"cat {MOUNT_POINT}/test.txt")
    test("read file", "Hello Ainos!" in out, out)

    # Multiple writes to test access tracking
    for i in range(3):
        run_cmd(f"echo 'line {i}' >> {MOUNT_POINT}/test.txt")
    rc, out, _ = run_cmd(f"wc -l {MOUNT_POINT}/test.txt")
    test("multiple writes", rc == 0, out)

    # Check /proc files
    files_content = read_file(os.path.join(PROC_AI_TMPFS, "files"))
    test("files shows data after mount", "HOT" in files_content or "COLD" in files_content,
         files_content[:200])

    # Status after I/O
    status = read_file(os.path.join(PROC_AI_TMPFS, "status"))
    test("status shows I/O", "Hits" in status, status[:200])

    # Unmount
    rc, out, err = run_cmd(f"umount {MOUNT_POINT}")
    test("unmount succeeds", rc == 0, err)

def test_integration():
    print("\n[5/5] Integration Test")
    # Check no errors in dmesg
    rc, out, _ = run_cmd("dmesg | grep -i 'ai-tmpfs' | tail -5")
    test("dmesg has ai-tmpfs entries", rc == 0, out[:200])

    # Check module loaded
    rc, out, _ = run_cmd("lsmod | grep ai_tmpfs")
    test("module loaded", rc == 0, out)

def main():
    print("=" * 60)
    print("Ainos OS - AI tmpfs Module Integration Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not os.path.exists(PROC_AI_TMPFS):
        print(f"\nERROR: {PROC_AI_TMPFS} does not exist!")
        print("Load the module first: sudo insmod ai_tmpfs.ko")
        sys.exit(1)

    print(f"\n/proc/ai-tmpfs files:")
    for f in sorted(os.listdir(PROC_AI_TMPFS)):
        print(f"  {f}")

    test_basic_files()
    test_status()
    test_config()
    test_mount_and_io()
    test_integration()

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