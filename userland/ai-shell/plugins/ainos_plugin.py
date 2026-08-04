"""
AinosOS integration plugin for Ainos Shell.

Provides integration with AinosOS:
- Model management (list, download, remove models)
- Model inference (run prompts locally)
- Model status monitoring
- Resource usage tracking
- AinosOS API client
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import typing as t
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..src.plugins import Plugin, PluginInfo, HookType, PluginContext
from ..src.utils import AnsiCode, colorize, human_readable_size


@dataclass
class ModelInfo:
    """AinosOS model information."""
    name: str = ""
    path: str = ""
    size: int = 0
    format: str = "gguf"
    quant: str = ""
    loaded: bool = False
    context_length: int = 4096
    description: str = ""
    modified: str = ""

    @property
    def size_str(self) -> str:
        return human_readable_size(self.size)

    @property
    def filename(self) -> str:
        return os.path.basename(self.path) if self.path else self.name

    def __repr__(self) -> str:
        return f"Model({self.name}, {self.size_str})"


@dataclass
class InferenceResult:
    """Result of a model inference."""
    text: str = ""
    tokens_used: int = 0
    tokens_per_second: float = 0.0
    duration: float = 0.0
    model: str = ""
    success: bool = False
    error: str = ""

    def __repr__(self) -> str:
        if self.success:
            return f"Inference({self.tokens_used} tokens, {self.tokens_per_second:.1f} t/s)"
        return f"Inference(error={self.error})"


class AinosPlugin(Plugin):
    """AinosOS integration plugin."""

    info = PluginInfo(
        name="ainos",
        version="1.0.0",
        description="AinosOS integration - model management and inference",
        author="Ainos Team",
        tags=["ainos", "model", "inference", "ai"],
        priority=40,
    )

    def __init__(self, context: t.Optional[PluginContext] = None) -> None:
        super().__init__(context)
        self._models: t.List[ModelInfo] = []
        self._loaded_model: t.Optional[ModelInfo] = None
        self._inference_process: t.Any = None
        self._ainos_home = os.environ.get("AINOS_HOME", os.path.expanduser("~/.ainos"))

    def initialize(self) -> None:
        """Initialize the plugin."""
        self.set_config("models_dir", os.path.join(self._ainos_home, "models"))
        self.set_config("default_model", "")
        self.set_config("context_length", 4096)
        self.set_config("gpu_layers", 0)

    @property
    def models(self) -> t.List[ModelInfo]:
        """Get available models."""
        self._scan_models()
        return self._models

    def _scan_models(self) -> None:
        """Scan for available models."""
        models_dir = self.get_config("models_dir", os.path.join(self._ainos_home, "models"))
        if not os.path.isdir(models_dir):
            return

        self._models = []
        for filename in os.listdir(models_dir):
            if filename.endswith((".gguf", ".bin", ".pt", ".pth")):
                full_path = os.path.join(models_dir, filename)
                try:
                    st = os.stat(full_path)
                    # Parse model name from filename
                    name = os.path.splitext(filename)[0]
                    quant = ""
                    context_length = 4096

                    # Try to extract quantization info
                    parts = name.split("-")
                    for part in parts:
                        if part.upper() in ("Q2_K", "Q3_K", "Q4_K", "Q5_K", "Q6_K", "Q8_K", "FP16", "FP32"):
                            quant = part.upper()
                            break

                    self._models.append(ModelInfo(
                        name=name,
                        path=full_path,
                        size=st.st_size,
                        format="gguf" if filename.endswith(".gguf") else "pytorch",
                        quant=quant,
                        context_length=context_length,
                        modified=datetime.fromtimestamp(st.st_mtime).isoformat(),
                    ))
                except (OSError, ValueError):
                    continue

    def load_model(self, model_name: str) -> bool:
        """Load a model for inference."""
        model = self._find_model(model_name)
        if model is None:
            return False

        # Try to use llama.cpp or similar backend
        backend_path = self._find_backend()
        if backend_path:
            try:
                cmd = [
                    backend_path,
                    "-m", model.path,
                    "--ctx-size", str(self.get_config("context_length", 4096)),
                    "--n-gpu-layers", str(self.get_config("gpu_layers", 0)),
                    "--server",
                    "--port", "8080",
                ]
                self._inference_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                model.loaded = True
                self._loaded_model = model
                time.sleep(1)  # Wait for server to start
                return True
            except (FileNotFoundError, subprocess.SubprocessError):
                pass

        return False

    def unload_model(self) -> bool:
        """Unload the current model."""
        if self._inference_process:
            self._inference_process.terminate()
            self._inference_process.wait(timeout=5)
            self._inference_process = None

        if self._loaded_model:
            self._loaded_model.loaded = False
            self._loaded_model = None

        return True

    def infer(self, prompt: str, max_tokens: int = 256,
              temperature: float = 0.7, model: str = "") -> InferenceResult:
        """Run inference on a prompt."""
        if not self._loaded_model:
            return InferenceResult(success=False, error="No model loaded")

        import httpx
        start_time = time.time()

        try:
            response = httpx.post(
                "http://localhost:8080/completion",
                json={
                    "prompt": prompt,
                    "n_predict": max_tokens,
                    "temperature": temperature,
                    "stop": ["</s>", "User:", "Assistant:"],
                },
                timeout=60,
            )

            if response.status_code == 200:
                data = response.json()
                duration = time.time() - start_time
                tokens = data.get("tokens_predicted", 0)
                return InferenceResult(
                    text=data.get("content", ""),
                    tokens_used=tokens,
                    tokens_per_second=tokens / duration if duration > 0 else 0,
                    duration=duration,
                    model=self._loaded_model.name,
                    success=True,
                )
            else:
                return InferenceResult(
                    success=False,
                    error=f"HTTP {response.status_code}: {response.text}",
                )
        except Exception as e:
            return InferenceResult(success=False, error=str(e))

    def _find_model(self, name: str) -> t.Optional[ModelInfo]:
        """Find a model by name."""
        self._scan_models()
        for model in self._models:
            if model.name == name or model.filename == name:
                return model
        return None

    def _find_backend(self) -> t.Optional[str]:
        """Find the inference backend executable."""
        # Look for common backends
        candidates = [
            "llama-server",
            "llama-cli",
            "llama.cpp",
            "llama-cpp-server",
            "main",
        ]

        # Check in AinosOS paths
        ainos_bin = os.path.join(self._ainos_home, "bin")
        extra_paths = [
            ainos_bin,
            "/usr/local/bin",
            os.path.expanduser("~/.local/bin"),
        ]

        for directory in extra_paths:
            if os.path.isdir(directory):
                for candidate in candidates:
                    full = os.path.join(directory, candidate)
                    if os.path.isfile(full) and os.access(full, os.X_OK):
                        return full

        # Check PATH
        for candidate in candidates:
            import shutil
            found = shutil.which(candidate)
            if found:
                return found

        # Check for python-based backends
        python = sys.executable
        if python:
            scripts = [
                os.path.join(os.path.dirname(python), "llama-cpp-server"),
                os.path.join(os.path.dirname(python), "llama-cpp"),
            ]
            for script in scripts:
                if os.path.isfile(script) and os.access(script, os.X_OK):
                    return script

        return None

    def download_model(self, model_name: str, source: str = "huggingface") -> bool:
        """Download a model from a source."""
        models_dir = self.get_config("models_dir", os.path.join(self._ainos_home, "models"))
        os.makedirs(models_dir, exist_ok=True)

        if source == "huggingface":
            try:
                # Try huggingface-hub
                import subprocess
                cmd = [
                    sys.executable, "-m", "huggingface_hub", "download",
                    model_name,
                    "--local-dir", models_dir,
                    "--local-dir-use-symlinks", "False",
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    self._scan_models()
                    return True
                return False
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        return False

    def get_model_info(self, model_name: str) -> t.Optional[ModelInfo]:
        """Get detailed info about a model."""
        return self._find_model(model_name)

    def get_inference_stats(self) -> dict:
        """Get inference statistics."""
        return {
            "model_loaded": self._loaded_model is not None,
            "model_name": self._loaded_model.name if self._loaded_model else "",
            "available_models": len(self._models),
            "models_dir": self.get_config("models_dir", ""),
        }

    def get_shortcuts(self) -> t.Dict[str, str]:
        """Get AinosOS command shortcuts."""
        return {
            "amodels": "ainos models list",
            "aload": "ainos model load",
            "aunload": "ainos model unload",
            "ainfer": "ainos infer",
            "adl": "ainos model download",
        }

    def activate(self) -> None:
        """Activate the plugin."""
        super().activate()
        self._scan_models()
        from ..src.config import set_alias
        for shortcut, command in self.get_shortcuts().items():
            set_alias(shortcut, command)

    def deactivate(self) -> None:
        """Deactivate the plugin."""
        super().deactivate()
        self.unload_model()
        from ..src.config import unset_alias
        for shortcut in self.get_shortcuts().keys():
            unset_alias(shortcut)

    def __repr__(self) -> str:
        models = len(self._models)
        loaded = self._loaded_model.name if self._loaded_model else "none"
        return f"AinosPlugin(models={models}, loaded={loaded})"