#!/usr/bin/env python3
"""
Ainos OS - GGUF 模型下载器
从 HuggingFace Hub 下载 GGUF 格式模型，支持断点续传和进度显示

用法:
  python download_model.py --model Qwen/Qwen2.5-0.5B-Instruct-GGUF --quantization q4_0
  python download_model.py --model repoid/modelname --output ./models --list
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, List, Dict

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
HF_BASE = "https://huggingface.co"

# 常用 GGUF 模型清单
KNOWN_MODELS = {
    "qwen2.5-0.5b": {
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "files": {
            "q4_0": "qwen2.5-0.5b-instruct-q4_0.gguf",
            "q4_k_m": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "q8_0": "qwen2.5-0.5b-instruct-q8_0.gguf",
        },
        "description": "Qwen2.5 0.5B Instruct - 轻量级中文模型",
    },
    "phi-3-mini": {
        "repo": "microsoft/Phi-3-mini-4k-instruct-gguf",
        "files": {
            "q4_0": "Phi-3-mini-4k-instruct-q4.gguf",
            "q4_k_m": "Phi-3-mini-4k-instruct-q4_k_m.gguf",
        },
        "description": "Phi-3 Mini 4K - 微软小模型，英文优秀",
    },
    "llama-3.2-1b": {
        "repo": "huggingface/llama-3.2-1b-gguf",
        "files": {
            "q4_0": "llama-3.2-1b-q4_0.gguf",
            "q8_0": "llama-3.2-1b-q8_0.gguf",
        },
        "description": "Llama 3.2 1B - 超轻量英文模型",
    },
}


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f}MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f}GB"


def download_file(url: str, dest: Path, expected_sha256: Optional[str] = None) -> bool:
    """下载文件，支持断点续传"""
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 检查文件是否已存在且完整
    if dest.exists() and expected_sha256:
        if verify_sha256(dest, expected_sha256):
            print(f"  ✓ 文件已存在且校验通过: {dest.name}")
            return True

    mode = "ab" if dest.exists() else "wb"
    existing_size = dest.stat().st_size if dest.exists() else 0
    headers = {"Range": f"bytes={existing_size}-"} if existing_size > 0 else {}

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 416:  # Range not satisfiable
            print(f"  ✓ 文件已完整下载: {dest.name}")
            return True
        print(f"  ✗ HTTP 错误 {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"  ✗ 网络错误: {e.reason}")
        return False

    total = existing_size + int(resp.headers.get("Content-Length", 0))
    if total == 0:
        total = resp.headers.get("Content-Length", 0)

    print(f"  大小: {format_size(total)} | 下载中...")

    downloaded = existing_size
    last_update = time.time()
    last_bytes = downloaded

    with open(dest, mode) as f:
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)

            now = time.time()
            if now - last_update > 0.5:
                elapsed = now - last_update
                speed = (downloaded - last_bytes) / elapsed / 1024 / 1024
                pct = downloaded / total * 100 if total > 0 else 0
                print(f"  \r  {format_size(downloaded)} / {format_size(total)} ({pct:.1f}%) | {speed:.1f} MB/s", end="")
                sys.stdout.flush()
                last_update = now
                last_bytes = downloaded

    print()
    print(f"  ✓ 下载完成: {dest.name}")

    if expected_sha256:
        if verify_sha256(dest, expected_sha256):
            print(f"  ✓ SHA256 校验通过")
            return True
        else:
            print(f"  ✗ SHA256 校验失败")
            return False

    return True


def verify_sha256(filepath: Path, expected: str) -> bool:
    """验证文件 SHA256"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest() == expected.lower()


def list_models():
    """列出支持的模型"""
    print("\n可用的预配置模型:")
    print("=" * 70)
    for key, info in KNOWN_MODELS.items():
        print(f"\n  {key}: {info['description']}")
        print(f"    仓库: {info['repo']}")
        for q, fname in info["files"].items():
            local = MODELS_DIR / fname
            status = "✓" if local.exists() else " "
            print(f"    [{status}] {q:10s} → {fname}")
    print()

    # 扫描已有模型
    if MODELS_DIR.exists():
        models = list(MODELS_DIR.glob("*.gguf")) + list(MODELS_DIR.glob("*.ggml"))
        if models:
            print(f"\n本地已有 {len(models)} 个模型:")
            for m in sorted(models):
                size = format_size(m.stat().st_size)
                print(f"  • {m.name} ({size})")


def main():
    parser = argparse.ArgumentParser(description="Ainos OS - GGUF 模型下载器")
    parser.add_argument("--model", type=str, help="模型名称或 HuggingFace repo (如 Qwen/Qwen2.5-0.5B-Instruct-GGUF)")
    parser.add_argument("--quantization", type=str, default="q4_0", help="量化格式 (q4_0, q4_k_m, q8_0)")
    parser.add_argument("--output", type=str, default=str(MODELS_DIR), help="模型输出目录")
    parser.add_argument("--list", action="store_true", help="列出可用模型")
    parser.add_argument("--known", type=str, help="使用预配置模型名称 (如 qwen2.5-0.5b)")
    args = parser.parse_args()

    if args.list:
        list_models()
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 使用预配置模型
    if args.known:
        if args.known not in KNOWN_MODELS:
            print(f"未知模型: {args.known}")
            print(f"可用: {', '.join(KNOWN_MODELS.keys())}")
            sys.exit(1)
        info = KNOWN_MODELS[args.known]
        repo = info["repo"]
        fname = info["files"].get(args.quantization)
        if not fname:
            print(f"量化格式 {args.quantization} 不适用，可用: {', '.join(info['files'].keys())}")
            sys.exit(1)
        url = f"{HF_BASE}/{repo}/resolve/main/{fname}"
        dest = output_dir / fname
        print(f"下载 {args.known} ({args.quantization})")
        print(f"  仓库: {repo}")
        print(f"  文件: {fname}")
        download_file(url, dest)
        return

    # 直接指定 repo
    if args.model:
        repo = args.model
        # 尝试从最后一段路径推断文件名
        fname = f"{repo.split('/')[-1]}-{args.quantization}.gguf"
        url = f"{HF_BASE}/{repo}/resolve/main/{fname}"
        dest = output_dir / fname
        print(f"下载 {repo}")
        print(f"  文件: {fname}")
        download_file(url, dest)

        # 更新模型清单
        manifest = output_dir / "model_manifest.json"
        if manifest.exists():
            with open(manifest) as f:
            data = json.load(f)
        else:
            data = {"models": []}
        data["models"].append({
            "name": fname,
            "source": repo,
            "quantization": args.quantization,
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": str(dest),
        })
        with open(manifest, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  ✓ 已更新模型清单: {manifest}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()