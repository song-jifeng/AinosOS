"""
Ainos SDK - Model Management Example
=====================================

Demonstrates model management operations:
- Listing models
- Loading a model
- Checking model status
- Finding models by criteria
- Unloading a model
- Batch loading multiple models

Prerequisites:
    - The Ainos daemon must be running on localhost:9500
    - A model file must exist on disk (update MODEL_PATH below)

Usage:
    python examples/model_management.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ainos import AinosClient, ModelManager, setup_logging
from ainos.errors import (
    ModelBusyError,
    ModelError,
    ModelLoadError,
    ModelNotFoundError,
)
from ainos.types import ModelInfo

# ---------------------------------------------------------------------------
# Configuration - UPDATE THESE PATHS for your environment
# ---------------------------------------------------------------------------

# Path to a model file on disk. Update this to match your setup.
MODEL_PATH: str = os.environ.get(
    "AINOS_MODEL_PATH",
    "/models/llama-3-8b.Q4_K_M.gguf",
)

# Name to give the model when loaded
MODEL_NAME: str = "example-llama"


async def main() -> None:
    """Run the model management example."""
    setup_logging(level=logging.WARNING)

    auth_token: str | None = os.environ.get("AINOS_AUTH_TOKEN")

    print("=" * 60)
    print("Ainos SDK - Model Management Example")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Connect
    # ------------------------------------------------------------------
    print("\n[1] Connecting to daemon...")

    client: AinosClient = AinosClient(
        host="127.0.0.1",
        port=9500,
        auth_token=auth_token,
    )
    await client.connect()
    print(f"    Connected: {client.connected}")

    # Get the model manager
    mgr: ModelManager = client.model_manager

    # ------------------------------------------------------------------
    # 2. List existing models
    # ------------------------------------------------------------------
    print("\n[2] Listing existing models...")

    try:
        models: list[ModelInfo] = await mgr.list_models()
        if models:
            print(f"    Found {len(models)} model(s) in registry:")
            for i, m in enumerate(models):
                print(f"      [{i + 1}] {m.name} (id={m.id})")
                print(f"           Status: {m.status}, Backend: {m.backend}")
        else:
            print("    No models in registry.")
    except Exception as exc:
        print(f"    Failed to list models: {exc}")

    # ------------------------------------------------------------------
    # 3. Check if a model is loaded
    # ------------------------------------------------------------------
    print(f"\n[3] Checking if '{MODEL_NAME}' is loaded...")

    try:
        is_loaded: bool = await mgr.is_loaded(MODEL_NAME)
        print(f"    '{MODEL_NAME}' loaded: {is_loaded}")

        if is_loaded:
            info: ModelInfo = await mgr.get_model(MODEL_NAME)
            print(f"    Model info:")
            print(f"      ID: {info.id}")
            print(f"      Path: {info.path}")
            print(f"      Backend: {info.backend}")
            print(f"      Device: {info.device}")
            print(f"      Context length: {info.context_length}")
            print(f"      Size: {info.size_bytes / 1024 / 1024:.1f} MB")
    except ModelNotFoundError:
        print(f"    Model '{MODEL_NAME}' not found in registry.")

    # ------------------------------------------------------------------
    # 4. Load a model
    # ------------------------------------------------------------------
    print(f"\n[4] Loading model '{MODEL_NAME}' from {MODEL_PATH}...")

    if not os.path.exists(MODEL_PATH):
        print(f"    WARNING: Model file not found at {MODEL_PATH}")
        print(f"    Set AINOS_MODEL_PATH to a valid model file.")
        print(f"    Skipping load example.")
        load_successful: bool = False
    else:
        try:
            info = await mgr.load_model(
                name=MODEL_NAME,
                path=MODEL_PATH,
                backend="llama.cpp",  # or "transformers", etc.
                context_length=4096,
                gpu_layers=0,  # Set to >0 for GPU offloading
                wait_ready=True,
                wait_timeout=120.0,
            )
            print(f"    Model loaded successfully!")
            print(f"      ID: {info.id}")
            print(f"      Status: {info.status}")
            print(f"      Backend: {info.backend}")
            print(f"      Device: {info.device}")
            load_successful = True
        except ModelLoadError as exc:
            print(f"    Failed to load model: {exc}")
            load_successful = False
        except FileNotFoundError:
            print(f"    Model file not found: {MODEL_PATH}")
            load_successful = False

    # ------------------------------------------------------------------
    # 5. Find models by criteria
    # ------------------------------------------------------------------
    print("\n[5] Finding models by criteria...")

    loaded_models: list[ModelInfo] = await mgr.find_model(loaded=True)
    print(f"    Loaded models: {len(loaded_models)}")

    llama_models: list[ModelInfo] = await mgr.find_model(backend="llama.cpp")
    print(f"    llama.cpp models: {len(llama_models)}")

    # ------------------------------------------------------------------
    # 6. Get model details
    # ------------------------------------------------------------------
    if load_successful:
        print(f"\n[6] Getting details for '{MODEL_NAME}'...")

        try:
            detail: ModelInfo = await mgr.get_model(MODEL_NAME)
            print(f"    Full model info:")
            print(f"      ID: {detail.id}")
            print(f"      Name: {detail.name}")
            print(f"      Path: {detail.path}")
            print(f"      Status: {detail.status}")
            print(f"      Backend: {detail.backend}")
            print(f"      Size: {detail.size_bytes} bytes")
            print(f"      Device: {detail.device}")
            print(f"      Context: {detail.context_length} tokens")
            print(f"      Loaded at: {detail.loaded_at}")
            if detail.metadata:
                for k, v in detail.metadata.items():
                    print(f"      {k}: {v}")
        except ModelNotFoundError:
            print(f"    Model not found (may have been unloaded).")

    # ------------------------------------------------------------------
    # 7. Unload the model
    # ------------------------------------------------------------------
    if load_successful:
        print(f"\n[7] Unloading '{MODEL_NAME}'...")

        try:
            success: bool = await mgr.unload_model(MODEL_NAME)
            print(f"    Unloaded: {success}")
        except ModelNotFoundError:
            print(f"    Model not found (already unloaded).")
        except ModelBusyError:
            print(f"    Model is busy, try with force=True.")
        except ModelError as exc:
            print(f"    Failed to unload: {exc}")

    # ------------------------------------------------------------------
    # 8. Refresh registry
    # ------------------------------------------------------------------
    print("\n[8] Refreshing model registry...")

    count: int = await mgr.refresh_registry()
    print(f"    Registry now has {count} model(s).")

    # ------------------------------------------------------------------
    # 9. Clean up
    # ------------------------------------------------------------------
    print("\n[9] Disconnecting...")
    await client.disconnect()
    print("    Done.")

    print("\n" + "=" * 60)
    print("Model management example completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())