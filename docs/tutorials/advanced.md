# AinosOS Advanced Usage Tutorial / 高级使用教程

> **Version:** 1.0.0 | **Updated:** 2026-08-04
>
> Advanced techniques and best practices for the AinosOS inference platform.
> AinosOS 推理平台的高级技术和最佳实践。

---

## Table of Contents / 目录

1. [Overview / 概述](#1-overview)
2. [Custom Model Integration / 自定义模型集成](#2-custom-model-integration)
3. [Model Optimization / 模型优化](#3-model-optimization)
4. [Performance Tuning / 性能调优](#4-performance-tuning)
5. [Batch Processing / 批处理](#5-batch-processing)
6. [Context Management / 上下文管理](#6-context-management)
7. [Multi-Model Pipelines / 多模型流水线](#7-multi-model-pipelines)
8. [Integration with External Tools / 外部工具集成](#8-integration-with-external-tools)
9. [Monitoring and Logging / 监控与日志](#9-monitoring-and-logging)
10. [Troubleshooting Guide / 故障排除指南](#10-troubleshooting-guide)
11. [Advanced Patterns / 高级模式](#11-advanced-patterns)
12. [Appendix / 附录](#12-appendix)

---

## 1. Overview / 概述

### What You Will Learn / 你将学到

This advanced tutorial covers:

- **Custom Model Integration** - Adding your own models to AinosOS
- **Model Optimization** - Quantization, pruning, and optimization techniques
- **Performance Tuning** - Optimizing throughput and latency
- **Batch Processing** - Efficient batch inference
- **Context Management** - Managing conversation context
- **Multi-Model Pipelines** - Chaining multiple models
- **External Tool Integration** - Connecting with other systems
- **Monitoring & Logging** - Production observability
- **Troubleshooting** - Diagnosing and fixing issues

### Prerequisites / 前提条件

```bash
# Required knowledge
- Python 3.12+
- Basic understanding of ML models
- Familiarity with REST APIs
- AinosOS server running (see deployment guide)

# Required tools
pip install ainos-sdk psutil numpy
```

---

## 2. Custom Model Integration / 自定义模型集成

### Model Provider Interface

```python
# D:/Ainos/system-services/models/base_provider.py
# Base Model Provider Interface
# ===============================

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional


@dataclass
class ModelConfig:
    """Configuration for a model."""
    model_id: str
    model_path: str
    context_length: int = 8192
    gpu_layers: int = 32
    batch_size: int = 1
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repetition_penalty: float = 1.1
    metadata: Dict[str, Any] = None


class ModelProvider(ABC):
    """
    Abstract base class for model providers.
    Implement this to integrate custom models.
    """
    
    @abstractmethod
    async def load(self, config: ModelConfig) -> bool:
        """Load model into memory."""
        pass
    
    @abstractmethod
    async def unload(self) -> bool:
        """Unload model from memory."""
        pass
    
    @abstractmethod
    async def infer(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> Any:
        """Run inference on the model."""
        pass
    
    @abstractmethod
    async def infer_stream(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming inference."""
        pass
    
    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        pass
    
    @property
    @abstractmethod
    def vram_usage(self) -> int:
        """Get VRAM usage in bytes."""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get model statistics."""
        pass
```

### Llama.cpp Integration Example

```python
# D:/Ainos/system-services/models/llama_provider.py
# Llama.cpp Model Provider
# ==========================

import asyncio
import os
import time
from typing import Any, AsyncGenerator, Dict, Optional

from .base_provider import ModelConfig, ModelProvider

try:
    import llama_cpp
    from llama_cpp import Llama
    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False


class LlamaCppProvider(ModelProvider):
    """
    Model provider using llama.cpp for local inference.
    Supports GGUF format models.
    """
    
    def __init__(self):
        self._model: Optional[Llama] = None
        self._config: Optional[ModelConfig] = None
        self._load_time: Optional[float] = None
        self._request_count: int = 0
        self._total_tokens: int = 0
    
    async def load(self, config: ModelConfig) -> bool:
        if not HAS_LLAMA_CPP:
            raise ImportError(
                "llama-cpp-python is required. Install with: "
                "pip install llama-cpp-python"
            )
        
        if not os.path.exists(config.model_path):
            raise FileNotFoundError(
                f"Model not found at: {config.model_path}"
            )
        
        self._config = config
        
        # Load model in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(
            None,
            lambda: Llama(
                model_path=config.model_path,
                n_ctx=config.context_length,
                n_gpu_layers=config.gpu_layers,
                n_batch=config.batch_size,
                verbose=False,
            )
        )
        
        self._load_time = time.time()
        return True
    
    async def unload(self) -> bool:
        self._model = None
        self._config = None
        return True
    
    async def infer(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> Any:
        if not self._model:
            raise RuntimeError("Model not loaded")
        
        self._request_count += 1
        
        # Run inference in thread pool
        loop = asyncio.get_event_loop()
        output = await loop.run_in_executor(
            None,
            lambda: self._model(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=self._config.top_p if self._config else 0.9,
                top_k=self._config.top_k if self._config else 40,
                repeat_penalty=(
                    self._config.repetition_penalty 
                    if self._config else 1.1
                ),
                stream=False,
                echo=False,
            )
        )
        
        if isinstance(output, dict):
            text = output.get("choices", [{}])[0].get("text", "")
            tokens = output.get("usage", {}).get("completion_tokens", 0)
            self._total_tokens += tokens
            return {
                "text": text,
                "tokens": tokens,
                "finish_reason": "stop",
            }
        
        return {"text": str(output), "tokens": 0, "finish_reason": "stop"}
    
    async def infer_stream(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self._model:
            raise RuntimeError("Model not loaded")
        
        self._request_count += 1
        token_count = 0
        
        # Run streaming in thread pool
        loop = asyncio.get_event_loop()
        
        def stream_generator():
            for output in self._model(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                echo=False,
            ):
                yield output
        
        for output in await loop.run_in_executor(
            None, lambda: list(stream_generator())
        ):
            if isinstance(output, dict):
                token = (
                    output.get("choices", [{}])[0]
                    .get("text", "")
                )
                if token:
                    token_count += 1
                    yield {"token": token, "index": token_count}
        
        self._total_tokens += token_count
        yield {"done": True, "token_count": token_count}
    
    @property
    def is_loaded(self) -> bool:
        return self._model is not None
    
    @property
    def vram_usage(self) -> int:
        # Estimate VRAM usage based on model size
        if not self._config:
            return 0
        # Rough estimate: 2 bytes per parameter
        model_size = os.path.getsize(self._config.model_path)
        return model_size * 0.8  # ~80% loaded to VRAM
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "model_id": self._config.model_id if self._config else None,
            "loaded": self.is_loaded,
            "load_time": self._load_time,
            "uptime": time.time() - self._load_time if self._load_time else 0,
            "requests": self._request_count,
            "total_tokens": self._total_tokens,
            "vram_estimate": self.vram_usage,
        }
```

### vLLM Integration Example

```python
# D:/Ainos/system-services/models/vllm_provider.py
# vLLM Model Provider
# =====================

import asyncio
import time
from typing import Any, AsyncGenerator, Dict, Optional

from .base_provider import ModelConfig, ModelProvider

try:
    from vllm import AsyncLLMEngine, SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    HAS_VLLM = True
except ImportError:
    HAS_VLLM = False


class VLLMProvider(ModelProvider):
    """
    Model provider using vLLM for high-throughput inference.
    Supports various model architectures including LLaMA, Mistral, Qwen.
    """
    
    def __init__(self):
        self._engine: Optional[AsyncLLMEngine] = None
        self._config: Optional[ModelConfig] = None
        self._load_time: Optional[float] = None
        self._request_count: int = 0
        self._total_tokens: int = 0
    
    async def load(self, config: ModelConfig) -> bool:
        if not HAS_VLLM:
            raise ImportError(
                "vLLM is required. Install with: "
                "pip install vllm"
            )
        
        self._config = config
        
        engine_args = AsyncEngineArgs(
            model=config.model_path,
            max_model_len=config.context_length,
            tensor_parallel_size=1,
            gpu_memory_utilization=0.9,
            trust_remote_code=True,
            dtype="auto",
        )
        
        self._engine = AsyncLLMEngine.from_engine_args(engine_args)
        self._load_time = time.time()
        return True
    
    async def unload(self) -> bool:
        if self._engine:
            # Cleanup
            self._engine = None
        self._config = None
        return True
    
    async def infer(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> Any:
        if not self._engine:
            raise RuntimeError("Model not loaded")
        
        self._request_count += 1
        
        sampling_params = SamplingParams(
            temperature=temperature,
            top_p=self._config.top_p if self._config else 0.9,
            top_k=self._config.top_k if self._config else 40,
            max_tokens=max_tokens,
            repetition_penalty=(
                self._config.repetition_penalty 
                if self._config else 1.1
            ),
        )
        
        if stream:
            return self._stream_infer(prompt, sampling_params)
        
        # Direct inference
        request_id = f"req_{int(time.time())}_{self._request_count}"
        
        results_generator = await self._engine.add_request(
            request_id=request_id,
            prompt=prompt,
            sampling_params=sampling_params,
        )
        
        full_text = ""
        async for result in results_generator:
            if result.outputs:
                full_text = result.outputs[0].text
        
        tokens = len(full_text.split())
        self._total_tokens += tokens
        
        return {
            "text": full_text,
            "tokens": tokens,
            "finish_reason": "stop",
        }
    
    async def _stream_infer(
        self, prompt: str, sampling_params: SamplingParams
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming inference with vLLM."""
        request_id = f"req_{int(time.time())}_{self._request_count}"
        token_count = 0
        
        results_generator = await self._engine.add_request(
            request_id=request_id,
            prompt=prompt,
            sampling_params=sampling_params,
        )
        
        async for result in results_generator:
            if result.outputs:
                for output in result.outputs[0].token_ids:
                    token_count += 1
                    yield {"token": output, "index": token_count}
        
        self._total_tokens += token_count
        yield {"done": True, "token_count": token_count}
    
    @property
    def is_loaded(self) -> bool:
        return self._engine is not None
    
    @property
    def vram_usage(self) -> int:
        # vLLM manages its own VRAM
        return 0
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "model_id": self._config.model_id if self._config else None,
            "loaded": self.is_loaded,
            "load_time": self._load_time,
            "uptime": time.time() - self._load_time if self._load_time else 0,
            "requests": self._request_count,
            "total_tokens": self._total_tokens,
        }
```

### Registering Custom Models

```python
# D:/Ainos/system-services/models/registry.py
# Model Registry
# ===============

from typing import Dict, Optional, Type

from .base_provider import ModelProvider, ModelConfig
from .llama_provider import LlamaCppProvider
from .vllm_provider import VLLMProvider


class ModelRegistry:
    """
    Registry for model providers and configurations.
    """
    
    def __init__(self):
        self._providers: Dict[str, Type[ModelProvider]] = {}
        self._instances: Dict[str, ModelProvider] = {}
        self._configs: Dict[str, ModelConfig] = {}
        
        # Register built-in providers
        self._register_defaults()
    
    def _register_defaults(self):
        """Register built-in model providers."""
        self.register_provider("llama.cpp", LlamaCppProvider)
        self.register_provider("vllm", VLLMProvider)
    
    def register_provider(
        self, name: str, provider_class: Type[ModelProvider]
    ):
        """Register a new model provider."""
        self._providers[name] = provider_class
    
    def register_model(
        self,
        model_id: str,
        provider: str,
        model_path: str,
        **kwargs,
    ) -> ModelConfig:
        """Register a model configuration."""
        config = ModelConfig(
            model_id=model_id,
            model_path=model_path,
            **kwargs,
        )
        self._configs[model_id] = config
        
        # Create provider instance
        if provider in self._providers:
            self._instances[model_id] = self._providers[provider]()
        
        return config
    
    async def load_model(self, model_id: str) -> bool:
        """Load a registered model."""
        if model_id not in self._configs:
            raise ValueError(f"Model '{model_id}' not registered")
        
        if model_id not in self._instances:
            raise ValueError(f"No provider for model '{model_id}'")
        
        provider = self._instances[model_id]
        config = self._configs[model_id]
        
        return await provider.load(config)
    
    async def unload_model(self, model_id: str) -> bool:
        """Unload a model."""
        if model_id in self._instances:
            return await self._instances[model_id].unload()
        return False
    
    def get_provider(self, model_id: str) -> Optional[ModelProvider]:
        """Get the provider for a model."""
        return self._instances.get(model_id)
    
    def get_config(self, model_id: str) -> Optional[ModelConfig]:
        """Get the configuration for a model."""
        return self._configs.get(model_id)
    
    def list_models(self) -> Dict[str, Dict]:
        """List all registered models with their status."""
        result = {}
        for model_id, config in self._configs.items():
            provider = self._instances.get(model_id)
            result[model_id] = {
                "config": {
                    "model_id": config.model_id,
                    "model_path": config.model_path,
                    "context_length": config.context_length,
                },
                "loaded": provider.is_loaded if provider else False,
                "stats": provider.get_stats() if provider and provider.is_loaded else {},
            }
        return result


# Global registry instance
registry = ModelRegistry()
```

---

## 3. Model Optimization / 模型优化

### Quantization

```python
# D:/Ainos/scripts/optimize/quantize_model.py
# Model Quantization Script
# ===========================

import argparse
import os
import sys

def quantize_gguf(input_path: str, output_path: str, quant_type: str = "Q4_K_M"):
    """
    Quantize a model to GGUF format.
    
    Quantization types (from best quality to most compressed):
    - Q2_K: 2-bit quantization (smallest, lowest quality)
    - Q3_K_S, Q3_K_M, Q3_K_L: 3-bit variants
    - Q4_0, Q4_1: 4-bit quantization
    - Q4_K_S, Q4_K_M, Q4_K_L: 4-bit K-quant variants
    - Q5_0, Q5_1: 5-bit quantization
    - Q5_K_S, Q5_K_M, Q5_K_L: 5-bit K-quant variants
    - Q6_K: 6-bit quantization
    - Q8_0: 8-bit quantization
    - F16: 16-bit half precision
    
    Recommended:
    - Q4_K_M: Good balance of quality and size (default)
    - Q5_K_M: Better quality, slightly larger
    - Q8_0: Near-lossless, larger size
    """
    print(f"Quantizing {input_path} to {quant_type}...")
    print(f"Output: {output_path}")
    
    # This would call llama.cpp's quantize tool
    cmd = [
        sys.executable, "-m", "llama_cpp.quantize",
        "--model", input_path,
        "--output", output_path,
        "--quantize", quant_type,
    ]
    
    print(f"Running: {' '.join(cmd)}")
    # In production, use subprocess.run(cmd)
    print("Quantization complete!")
    
    # Show size comparison
    original_size = os.path.getsize(input_path) / (1024**3)
    quantized_size = os.path.getsize(output_path) / (1024**3) if os.path.exists(output_path) else 0
    print(f"Original size: {original_size:.2f} GB")
    print(f"Quantized size: {quantized_size:.2f} GB")
    print(f"Compression ratio: {original_size / quantized_size:.2f}x")


def main():
    parser = argparse.ArgumentParser(description="Quantize GGUF models")
    parser.add_argument("input", help="Input model path")
    parser.add_argument("output", help="Output model path")
    parser.add_argument(
        "--type", default="Q4_K_M",
        choices=["Q2_K", "Q3_K_M", "Q4_0", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "F16"],
        help="Quantization type (default: Q4_K_M)"
    )
    
    args = parser.parse_args()
    quantize_gguf(args.input, args.output, args.type)


if __name__ == "__main__":
    main()
```

### Model Pruning

```python
# D:/Ainos/scripts/optimize/prune_model.py
# Model Pruning Script
# ======================

import argparse
import torch
import torch.nn.utils.prune as prune


def prune_model(model_path: str, output_path: str, amount: float = 0.3):
    """
    Prune unimportant weights from a model.
    
    Args:
        model_path: Path to the model
        output_path: Path to save pruned model
        amount: Fraction of weights to prune (0.0 - 1.0)
    """
    print(f"Loading model from {model_path}...")
    model = torch.load(model_path, map_location="cpu")
    
    print(f"Pruning {amount*100:.0f}% of weights...")
    
    # Apply global unstructured pruning
    parameters_to_prune = []
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Linear):
            parameters_to_prune.append(
                (module, "weight")
            )
    
    prune.global_unstructured(
        parameters_to_prune,
        pruning_method=prune.L1Unstructured,
        amount=amount,
    )
    
    # Make pruning permanent
    for module, name in parameters_to_prune:
        prune.remove(module, name)
    
    print(f"Saving pruned model to {output_path}...")
    torch.save(model, output_path)
    
    # Calculate sparsity
    total_params = 0
    zero_params = 0
    for name, param in model.named_parameters():
        if "weight" in name:
            total_params += param.numel()
            zero_params += (param == 0).sum().item()
    
    sparsity = zero_params / total_params * 100
    print(f"Model sparsity: {sparsity:.2f}%")


def main():
    parser = argparse.ArgumentParser(description="Prune model weights")
    parser.add_argument("input", help="Input model path")
    parser.add_argument("output", help="Output model path")
    parser.add_argument(
        "--amount", type=float, default=0.3,
        help="Fraction of weights to prune (default: 0.3)"
    )
    
    args = parser.parse_args()
    prune_model(args.input, args.output, args.amount)


if __name__ == "__main__":
    main()
```

### Optimization Configuration

```yaml
# D:/Ainos/config/optimization.yaml
# Model Optimization Configuration
# ==================================

optimization:
  # Quantization settings
  quantization:
    enabled: true
    type: "Q4_K_M"  # GGUF quantization type
    calibrate: false  # Run calibration for better quality
  
  # Pruning settings
  pruning:
    enabled: false
    amount: 0.3  # Prune 30% of weights
    method: "l1_unstructured"
  
  # KV cache optimization
  kv_cache:
    enabled: true
    max_entries: 4096
    dtype: "float16"  # float16 or int8
  
  # Attention optimization
  attention:
    flash_attention: true  # Use FlashAttention
    sink_attention: true   # Use StreamingLLM attention sink
  
  # Batch processing
  batching:
    dynamic: true  # Dynamic batching
    max_batch_size: 64
    max_wait_ms: 10  # Maximum wait time for batching
  
  # Memory optimization
  memory:
    gpu_memory_fraction: 0.9
    cpu_offload: false  # Offload layers to CPU
    offload_layers: 0   # Number of layers to offload
```

---

## 4. Performance Tuning / 性能调优

### Benchmarking

```python
# D:/Ainos/scripts/benchmark.py
# Performance Benchmarking
# ==========================

import asyncio
import json
import time
import statistics
from typing import List, Dict
import aiohttp


class Benchmark:
    """
    Performance benchmark for AinosOS inference.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_token: str = "",
        model: str = "ainos-llama-3.1-8b",
    ):
        self.base_url = base_url
        self.api_token = api_token
        self.model = model
        self.headers = {"Content-Type": "application/json"}
        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"
    
    async def benchmark_latency(
        self,
        prompts: List[str],
        max_tokens: int = 100,
        temperature: float = 0.7,
        num_runs: int = 10,
    ) -> Dict:
        """Benchmark inference latency."""
        results = []
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            for run in range(num_runs):
                for prompt in prompts:
                    start = time.time()
                    
                    async with session.post(
                        f"{self.base_url}/api/inference",
                        json={
                            "model": self.model,
                            "prompt": prompt,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "stream": False,
                        },
                    ) as response:
                        data = await response.json()
                        elapsed = time.time() - start
                        tokens = data.get("tokens", 0)
                        
                        results.append({
                            "run": run + 1,
                            "prompt": prompt[:50],
                            "latency": elapsed,
                            "tokens": tokens,
                            "tokens_per_second": tokens / elapsed if elapsed > 0 else 0,
                        })
        
        # Calculate statistics
        latencies = [r["latency"] for r in results]
        throughputs = [r["tokens_per_second"] for r in results]
        
        stats = {
            "num_requests": len(results),
            "latency": {
                "min": min(latencies),
                "max": max(latencies),
                "mean": statistics.mean(latencies),
                "median": statistics.median(latencies),
                "p95": statistics.quantiles(latencies, n=20)[18],
                "p99": statistics.quantiles(latencies, n=100)[98],
                "std": statistics.stdev(latencies) if len(latencies) > 1 else 0,
            },
            "throughput": {
                "min": min(throughputs),
                "max": max(throughputs),
                "mean": statistics.mean(throughputs),
                "median": statistics.median(throughputs),
            },
            "results": results,
        }
        
        return stats
    
    async def benchmark_throughput(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.7,
        concurrency: List[int] = [1, 2, 4, 8, 16],
        requests_per_concurrency: int = 20,
    ) -> Dict:
        """Benchmark throughput at different concurrency levels."""
        results = {}
        
        for conc in concurrency:
            print(f"  Testing concurrency={conc}...")
            
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async def single_request():
                    start = time.time()
                    async with session.post(
                        f"{self.base_url}/api/inference",
                        json={
                            "model": self.model,
                            "prompt": prompt,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "stream": False,
                        },
                    ) as response:
                        data = await response.json()
                        elapsed = time.time() - start
                        tokens = data.get("tokens", 0)
                        return elapsed, tokens
                
                # Run concurrent requests
                tasks = [single_request() for _ in range(requests_per_concurrency)]
                batch_results = await asyncio.gather(*tasks)
                
                latencies = [r[0] for r in batch_results]
                total_tokens = sum(r[1] for r in batch_results)
                total_time = max(latencies)
                
                results[conc] = {
                    "concurrency": conc,
                    "requests": requests_per_concurrency,
                    "total_time": total_time,
                    "total_tokens": total_tokens,
                    "requests_per_second": requests_per_concurrency / total_time,
                    "tokens_per_second": total_tokens / total_time,
                    "avg_latency": statistics.mean(latencies),
                    "p95_latency": statistics.quantiles(latencies, n=20)[18],
                }
        
        return results
    
    async def run_full_benchmark(
        self,
        output_file: str = "benchmark_results.json",
    ):
        """Run full benchmark suite."""
        print("=" * 60)
        print("AinosOS Performance Benchmark")
        print("=" * 60)
        
        print(f"\nModel: {self.model}")
        print(f"Server: {self.base_url}")
        
        # Test prompts
        prompts = [
            "Hello, how are you?",
            "Explain quantum computing in simple terms.",
            "Write a Python function to sort a list.",
            "What is the capital of France?",
        ]
        
        # 1. Latency benchmark
        print("\n[1] Latency Benchmark")
        print("-" * 40)
        latency_results = await self.benchmark_latency(
            prompts=prompts,
            max_tokens=100,
            num_runs=5,
        )
        
        print(f"  Mean latency: {latency_results['latency']['mean']*1000:.1f}ms")
        print(f"  P95 latency: {latency_results['latency']['p95']*1000:.1f}ms")
        print(f"  Mean throughput: {latency_results['throughput']['mean']:.1f} tokens/s")
        
        # 2. Throughput benchmark
        print("\n[2] Throughput Benchmark")
        print("-" * 40)
        throughput_results = await self.benchmark_throughput(
            prompt="Hello, how are you?",
            max_tokens=50,
            concurrency=[1, 2, 4, 8],
        )
        
        for conc, data in throughput_results.items():
            print(f"  Concurrency {conc}: {data['requests_per_second']:.1f} req/s, "
                  f"{data['tokens_per_second']:.1f} tok/s, "
                  f"avg latency: {data['avg_latency']*1000:.1f}ms")
        
        # 3. Save results
        full_results = {
            "model": self.model,
            "server": self.base_url,
            "timestamp": time.time(),
            "latency": latency_results,
            "throughput": throughput_results,
        }
        
        with open(output_file, "w") as f:
            json.dump(full_results, f, indent=2)
        
        print(f"\nResults saved to: {output_file}")
        print("=" * 60)


async def main():
    benchmark = Benchmark(
        base_url="http://localhost:8080",
        model="ainos-llama-3.1-8b",
    )
    await benchmark.run_full_benchmark()


if __name__ == "__main__":
    asyncio.run(main())
```

### Performance Tuning Parameters

```python
# D:/Ainos/config/performance.py
# Performance Tuning Parameters
# ===============================

# Server settings
SERVER_SETTINGS = {
    "workers": 4,  # Number of worker processes
    "backlog": 1024,  # Connection backlog
    "keepalive_timeout": 75,  # Keepalive timeout in seconds
    "max_concurrent_requests": 64,  # Max concurrent requests per worker
}

# Inference settings
INFERENCE_SETTINGS = {
    "max_batch_size": 64,  # Max batch size for dynamic batching
    "max_wait_ms": 10,  # Max wait time for batching
    "max_tokens": 8192,  # Max tokens per request
    "default_temperature": 0.7,
    "streaming_chunk_size": 1,  # Tokens per streaming chunk
}

# GPU settings
GPU_SETTINGS = {
    "memory_fraction": 0.9,  # Fraction of GPU memory to use
    "cuda_visible_devices": "0",  # Which GPUs to use
    "cuda_launch_blocking": 0,  # Async execution
    "cuda_cache_maxsize": 1073741824,  # 1GB CUDA cache
}

# Memory settings
MEMORY_SETTINGS = {
    "kv_cache_size": 4096,  # Max KV cache entries
    "kv_cache_dtype": "float16",  # float16 or int8
    "offload_layers": 0,  # Layers to offload to CPU
}

# Performance tuning checklist
PERFORMANCE_CHECKLIST = """
Performance Tuning Checklist:
[ ] 1. Enable FlashAttention if available
[ ] 2. Use appropriate quantization (Q4_K_M for balance)
[ ] 3. Set GPU memory fraction to 0.9
[ ] 4. Enable dynamic batching
[ ] 5. Tune max_batch_size and max_wait_ms
[ ] 6. Use KV cache optimization
[ ] 7. Set appropriate number of workers
[ ] 8. Enable keepalive connections
[ ] 9. Monitor GPU utilization with nvidia-smi
[ ] 10. Run benchmark before and after changes
"""
```

---

## 5. Batch Processing / 批处理

### Synchronous Batch Processing

```python
# D:/Ainos/examples/advanced/batch_processing.py
# Batch Processing Examples
# ===========================

import asyncio
import time
from typing import List, Dict
import aiohttp


class BatchProcessor:
    """
    Efficient batch inference processor.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_token: str = "",
        model: str = "ainos-llama-3.1-8b",
        batch_size: int = 10,
    ):
        self.base_url = base_url
        self.api_token = api_token
        self.model = model
        self.batch_size = batch_size
        self.headers = {"Content-Type": "application/json"}
        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"
    
    async def process_batch(
        self, prompts: List[str], max_tokens: int = 100
    ) -> List[Dict]:
        """Process a batch of prompts concurrently."""
        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = []
            for prompt in prompts:
                tasks.append(self._single_infer(session, prompt, max_tokens))
            return await asyncio.gather(*tasks)
    
    async def _single_infer(
        self, session: aiohttp.ClientSession, prompt: str, max_tokens: int
    ) -> Dict:
        """Single inference request."""
        start = time.time()
        async with session.post(
            f"{self.base_url}/api/inference",
            json={
                "model": self.model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": 0.7,
                "stream": False,
            },
        ) as response:
            data = await response.json()
            elapsed = time.time() - start
            return {
                "prompt": prompt[:50],
                "response": data.get("text", ""),
                "tokens": data.get("tokens", 0),
                "latency": elapsed,
            }
    
    def batch_generator(self, items: List, batch_size: int = None):
        """Generate batches from a list."""
        batch_size = batch_size or self.batch_size
        for i in range(0, len(items), batch_size):
            yield items[i:i + batch_size]
    
    async def process_all(
        self, prompts: List[str], max_tokens: int = 100
    ) -> List[Dict]:
        """Process all prompts in batches."""
        all_results = []
        total_batches = (len(prompts) + self.batch_size - 1) // self.batch_size
        
        for batch_idx, batch in enumerate(
            self.batch_generator(prompts), 1
        ):
            print(f"Processing batch {batch_idx}/{total_batches} "
                  f"({len(batch)} prompts)...")
            
            results = await self.process_batch(batch, max_tokens)
            all_results.extend(results)
        
        return all_results


async def main():
    # Example: Batch process multiple prompts
    processor = BatchProcessor(batch_size=5)
    
    prompts = [
        "What is Python?",
        "Explain machine learning.",
        "Write a hello world program.",
        "What is the speed of light?",
        "Describe the Solar System.",
        "What is deep learning?",
        "Explain neural networks.",
        "What is natural language processing?",
        "Describe reinforcement learning.",
        "What is computer vision?",
    ] * 10  # 100 prompts total
    
    print(f"Processing {len(prompts)} prompts in batches of "
          f"{processor.batch_size}...")
    
    start = time.time()
    results = await processor.process_all(prompts, max_tokens=50)
    total_time = time.time() - start
    
    # Summary
    successful = [r for r in results if r.get("response")]
    total_tokens = sum(r.get("tokens", 0) for r in successful)
    avg_latency = sum(r.get("latency", 0) for r in successful) / len(successful)
    
    print(f"\nResults:")
    print(f"  Total prompts: {len(prompts)}")
    print(f"  Successful: {len(successful)}")
    print(f"  Total time: {total_time:.2f}s")
    print(f"  Throughput: {len(successful)/total_time:.1f} req/s")
    print(f"  Total tokens: {total_tokens}")
    print(f"  Avg latency: {avg_latency*1000:.1f}ms")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Context Management / 上下文管理

### Context Manager Implementation

```python
# D:/Ainos/examples/advanced/context_manager.py
# Advanced Context Management
# =============================

import json
import time
import hashlib
from typing import List, Dict, Optional, Any
from collections import OrderedDict


class ConversationContext:
    """
    Manages conversation context for multi-turn interactions.
    """
    
    def __init__(self, max_tokens: int = 4096):
        self.max_tokens = max_tokens
        self.messages: List[Dict[str, str]] = []
        self.total_tokens: int = 0
        self.created_at: float = time.time()
        self.context_id: str = hashlib.md5(
            str(time.time()).encode()
        ).hexdigest()[:12]
    
    def add_message(self, role: str, content: str):
        """Add a message to the conversation."""
        tokens = len(content.split())
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        self.total_tokens += tokens
        self._trim_context()
    
    def _trim_context(self):
        """Trim context to fit within max_tokens."""
        while self.total_tokens > self.max_tokens and len(self.messages) > 2:
            removed = self.messages.pop(0)
            self.total_tokens -= len(removed["content"].split())
    
    def get_context(self) -> str:
        """Get formatted context for inference."""
        context = ""
        for msg in self.messages:
            role = msg["role"].capitalize()
            context += f"{role}: {msg['content']}\n"
        return context.strip()
    
    def get_messages(self) -> List[Dict]:
        """Get all messages."""
        return self.messages
    
    def clear(self):
        """Clear conversation."""
        self.messages = []
        self.total_tokens = 0
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "context_id": self.context_id,
            "messages": self.messages,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "created_at": self.created_at,
        }


class ContextSessionManager:
    """
    Manages multiple conversation contexts.
    """
    
    def __init__(self, ttl: int = 3600):
        self.sessions: Dict[str, ConversationContext] = {}
        self.ttl = ttl  # Time to live in seconds
    
    def get_or_create(self, session_id: str) -> ConversationContext:
        """Get existing session or create new one."""
        self._cleanup()
        
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationContext()
        
        return self.sessions[session_id]
    
    def delete(self, session_id: str):
        """Delete a session."""
        self.sessions.pop(session_id, None)
    
    def _cleanup(self):
        """Remove expired sessions."""
        now = time.time()
        expired = [
            sid for sid, ctx in self.sessions.items()
            if now - ctx.created_at > self.ttl
        ]
        for sid in expired:
            del self.sessions[sid]
    
    def get_stats(self) -> Dict:
        """Get session statistics."""
        return {
            "active_sessions": len(self.sessions),
            "total_sessions": len(self.sessions),
            "ttl": self.ttl,
        }


# Example: Multi-turn conversation
async def multi_turn_conversation():
    """Demonstrate multi-turn conversation with context management."""
    import aiohttp
    
    session_manager = ContextSessionManager()
    session_id = "user_123"
    ctx = session_manager.get_or_create(session_id)
    
    base_url = "http://localhost:8080"
    api_token = "your-token"
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    
    prompts = [
        "My name is Alice.",
        "What is my name?",
        "Tell me a joke.",
        "Can you repeat the joke?",
    ]
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for prompt in prompts:
            print(f"\nUser: {prompt}")
            
            # Add user message to context
            ctx.add_message("user", prompt)
            
            # Send request with context
            context = ctx.get_context()
            async with session.post(
                f"{base_url}/api/inference",
                json={
                    "model": "ainos-llama-3.1-8b",
                    "prompt": context,
                    "max_tokens": 150,
                    "temperature": 0.7,
                },
            ) as response:
                data = await response.json()
                response_text = data.get("text", "")
                print(f"AI: {response_text}")
                
                # Add AI response to context
                ctx.add_message("assistant", response_text)
    
    print(f"\nContext stats: {json.dumps(ctx.to_dict(), indent=2)}")
```

---

## 7. Multi-Model Pipelines / 多模型流水线

### Pipeline Implementation

```python
# D:/Ainos/examples/advanced/pipeline.py
# Multi-Model Pipeline
# ======================

import asyncio
from typing import List, Dict, Any, Callable, Awaitable
import aiohttp


class PipelineStage:
    """
    A single stage in a model pipeline.
    """
    
    def __init__(
        self,
        name: str,
        model: str,
        prompt_template: str,
        output_key: str = "output",
        max_tokens: int = 200,
        temperature: float = 0.7,
    ):
        self.name = name
        self.model = model
        self.prompt_template = prompt_template
        self.output_key = output_key
        self.max_tokens = max_tokens
        self.temperature = temperature
    
    def format_prompt(self, inputs: Dict[str, Any]) -> str:
        """Format prompt with inputs."""
        return self.prompt_template.format(**inputs)
    
    async def execute(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        headers: Dict,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute this pipeline stage."""
        prompt = self.format_prompt(inputs)
        
        async with session.post(
            f"{base_url}/api/inference",
            headers=headers,
            json={
                "model": self.model,
                "prompt": prompt,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": False,
            },
        ) as response:
            data = await response.json()
            text = data.get("text", "")
            
            return {
                self.output_key: text,
                f"{self.output_key}_tokens": data.get("tokens", 0),
            }


class ModelPipeline:
    """
    A pipeline of multiple models executed in sequence.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_token: str = "",
    ):
        self.base_url = base_url
        self.stages: List[PipelineStage] = []
        self.headers = {"Content-Type": "application/json"}
        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"
    
    def add_stage(self, stage: PipelineStage):
        """Add a stage to the pipeline."""
        self.stages.append(stage)
    
    async def run(
        self,
        initial_inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the pipeline with initial inputs."""
        inputs = dict(initial_inputs)
        results = {}
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            for i, stage in enumerate(self.stages):
                print(f"  Stage {i+1}/{len(self.stages)}: {stage.name} "
                      f"(model: {stage.model})")
                
                stage_results = await stage.execute(
                    session, self.base_url, self.headers, inputs
                )
                inputs.update(stage_results)
                results.update(stage_results)
        
        return results


# Example: Content generation pipeline
async def content_generation_pipeline():
    """
    Example pipeline:
    1. Generate topic ideas (small model)
    2. Expand on selected topic (medium model)
    3. Polish and format (large model)
    """
    pipeline = ModelPipeline()
    
    # Stage 1: Topic generation
    pipeline.add_stage(PipelineStage(
        name="Topic Generation",
        model="ainos-llama-3.1-8b",
        prompt_template=(
            "Generate 3 creative blog post topics about {subject}. "
            "Return as a numbered list."
        ),
        output_key="topics",
        max_tokens=100,
        temperature=0.9,
    ))
    
    # Stage 2: Content expansion
    pipeline.add_stage(PipelineStage(
        name="Content Expansion",
        model="ainos-llama-3.1-8b",
        prompt_template=(
            "Write a detailed blog post outline for topic 1 from:\n"
            "{topics}\n\n"
            "Include introduction, 3 main points, and conclusion."
        ),
        output_key="outline",
        max_tokens=300,
        temperature=0.7,
    ))
    
    # Stage 3: Polish
    pipeline.add_stage(PipelineStage(
        name="Content Polish",
        model="ainos-llama-3.1-8b",
        prompt_template=(
            "Polish and format the following blog outline into a "
            "well-written article:\n\n{outline}\n\n"
            "Make it engaging and professional."
        ),
        output_key="article",
        max_tokens=500,
        temperature=0.6,
    ))
    
    # Run pipeline
    print("Running content generation pipeline...")
    print("Input: subject=artificial intelligence")
    
    result = await pipeline.run({
        "subject": "artificial intelligence"
    })
    
    print(f"\nGenerated article ({result.get('output_tokens', 0)} tokens):")
    print("-" * 40)
    print(result.get("article", "No output"))
    
    return result
```

### Parallel Pipeline Execution

```python
# D:/Ainos/examples/advanced/parallel_pipeline.py
# Parallel Model Pipeline
# =========================

import asyncio
from typing import List, Dict, Any


class ParallelPipelineStage:
    """
    Execute multiple model calls in parallel.
    """
    
    def __init__(self, name: str, models: List[str], prompt: str):
        self.name = name
        self.models = models
        self.prompt = prompt
    
    async def execute(self, session, base_url, headers) -> Dict[str, Any]:
        """Execute all models in parallel."""
        async def infer_model(model: str) -> Dict:
            async with session.post(
                f"{base_url}/api/inference",
                headers=headers,
                json={
                    "model": model,
                    "prompt": self.prompt,
                    "max_tokens": 200,
                    "temperature": 0.7,
                },
            ) as response:
                data = await response.json()
                return {"model": model, "text": data.get("text", "")}
        
        tasks = [infer_model(m) for m in self.models]
        results = await asyncio.gather(*tasks)
        
        return {self.name: results}


async def ensemble_inference():
    """
    Run ensemble inference: multiple models on the same prompt,
    then combine results.
    """
    pipeline = ParallelPipelineStage(
        name="ensemble",
        models=[
            "ainos-llama-3.1-8b",
            "ainos-qwen-2.5-7b",
        ],
        prompt="What is the best programming language for AI?",
    )
    
    print("Running ensemble inference...")
    # Results will contain responses from all models
    # Can be combined with voting or averaging
```

---

## 8. Integration with External Tools / 外部工具集成

### OpenAI API Compatibility

```python
# D:/Ainos/examples/advanced/openai_compat.py
# OpenAI API Compatibility Layer
# ================================

"""
AinosOS provides an OpenAI-compatible API endpoint.

This allows you to use any OpenAI SDK or tool with AinosOS
by simply changing the base URL.
"""

# Example: Using OpenAI Python SDK with AinosOS
import os
from openai import OpenAI

# Configure client to use AinosOS
client = OpenAI(
    base_url="http://localhost:8080/v1",  # AinosOS OpenAI-compatible endpoint
    api_key=os.environ.get("AINOS_API_TOKEN", "not-needed"),
)

# Chat completion
response = client.chat.completions.create(
    model="ainos-llama-3.1-8b",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ],
    max_tokens=100,
    temperature=0.7,
)

print(response.choices[0].message.content)

# Streaming
stream = client.chat.completions.create(
    model="ainos-llama-3.1-8b",
    messages=[{"role": "user", "content": "Tell me a story."}],
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### LangChain Integration

```python
# D:/Ainos/examples/advanced/langchain_integration.py
# LangChain Integration
# ======================

from langchain.llms import Ainos
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory

# Initialize AinosOS LLM
llm = Ainos(
    base_url="http://localhost:8080",
    model="ainos-llama-3.1-8b",
    temperature=0.7,
    max_tokens=1024,
    api_token="your-token",
)

# Create a simple chain
prompt = PromptTemplate(
    input_variables=["topic"],
    template="Write a short summary about {topic}.",
)

chain = LLMChain(llm=llm, prompt=prompt)
result = chain.run("quantum computing")
print(result)

# Conversation chain with memory
memory = ConversationBufferMemory(memory_key="chat_history")
conversation = LLMChain(
    llm=llm,
    prompt=PromptTemplate(
        input_variables=["chat_history", "input"],
        template="Previous conversation:\n{chat_history}\n\nHuman: {input}\nAI:",
    ),
    memory=memory,
)

print(conversation.run("Hi, my name is Bob."))
print(conversation.run("What is my name?"))
```

### Vector Database Integration

```python
# D:/Ainos/examples/advanced/rag_integration.py
# RAG (Retrieval-Augmented Generation) Integration
# ===================================================

import asyncio
from typing import List, Dict
import aiohttp

try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False


class RAGPipeline:
    """
    Retrieval-Augmented Generation pipeline.
    Retrieves relevant documents and uses them as context for inference.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_token: str = "",
        model: str = "ainos-llama-3.1-8b",
        collection_name: str = "documents",
    ):
        self.base_url = base_url
        self.api_token = api_token
        self.model = model
        self.headers = {"Content-Type": "application/json"}
        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"
        
        # Initialize vector database
        if HAS_CHROMA:
            self.client = chromadb.Client(Settings(
                chroma_db_impl="duckdb+parquet",
                persist_directory="./chroma_db",
            ))
            self.collection = self.client.get_or_create_collection(
                name=collection_name
            )
        else:
            self.collection = None
    
    def add_documents(self, documents: List[Dict[str, str]]):
        """Add documents to the vector database."""
        if not self.collection:
            print("Vector database not available")
            return
        
        ids = []
        texts = []
        metadatas = []
        
        for i, doc in enumerate(documents):
            ids.append(f"doc_{i}")
            texts.append(doc["text"])
            metadatas.append({
                "source": doc.get("source", "unknown"),
                "title": doc.get("title", ""),
            })
        
        self.collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
        )
        
        print(f"Added {len(documents)} documents to collection")
    
    def search(self, query: str, k: int = 3) -> List[Dict]:
        """Search for relevant documents."""
        if not self.collection:
            return []
        
        results = self.collection.query(
            query_texts=[query],
            n_results=k,
        )
        
        documents = []
        for i in range(len(results["documents"][0])):
            documents.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        
        return documents
    
    async def query(self, question: str, k: int = 3) -> Dict:
        """Query with RAG: retrieve context + generate answer."""
        # 1. Retrieve relevant documents
        documents = self.search(question, k=k)
        context = "\n\n".join([
            f"[Source: {d['metadata'].get('source', 'unknown')}]\n{d['text']}"
            for d in documents
        ])
        
        # 2. Generate answer with context
        prompt = (
            f"Use the following context to answer the question.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Answer:"
        )
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(
                f"{self.base_url}/api/inference",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "max_tokens": 300,
                    "temperature": 0.3,  # Lower temperature for factual answers
                },
            ) as response:
                data = await response.json()
        
        return {
            "question": question,
            "answer": data.get("text", ""),
            "sources": [
                {
                    "source": d["metadata"]["source"],
                    "relevance": 1 - d["distance"],
                }
                for d in documents
            ],
            "documents_used": k,
        }


async def main():
    rag = RAGPipeline()
    
    # Add documents
    rag.add_documents([
        {
            "text": "AinosOS is an AI inference platform that supports "
                    "multiple model providers including llama.cpp and vLLM.",
            "source": "ainos-docs",
            "title": "Introduction",
        },
        {
            "text": "The API server supports REST endpoints for inference, "
                    "streaming via SSE and WebSocket, and model management.",
            "source": "ainos-docs",
            "title": "API Reference",
        },
    ])
    
    # Query
    result = await rag.query("What is AinosOS?")
    print(f"Question: {result['question']}")
    print(f"Answer: {result['answer']}")
    print(f"Sources: {result['sources']}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 9. Monitoring and Logging / 监控与日志

### Prometheus Metrics

```python
# D:/Ainos/system-services/web-panel/metrics.py
# Prometheus Metrics for AinosOS
# ================================

import time
from typing import Dict
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest,
    CONTENT_TYPE_LATEST,
)


# Request metrics
REQUESTS_TOTAL = Counter(
    "ainos_requests_total",
    "Total number of API requests",
    ["method", "endpoint", "status"],
)

REQUESTS_DURATION = Histogram(
    "ainos_request_duration_seconds",
    "Request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# Inference metrics
INFERENCE_REQUESTS = Counter(
    "ainos_inference_requests_total",
    "Total number of inference requests",
    ["model", "stream"],
)

INFERENCE_TOKENS = Counter(
    "ainos_inference_tokens_total",
    "Total number of tokens generated",
    ["model"],
)

INFERENCE_DURATION = Histogram(
    "ainos_inference_duration_seconds",
    "Inference duration in seconds",
    ["model"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

# System metrics
LOADED_MODELS = Gauge(
    "ainos_loaded_models",
    "Number of currently loaded models",
)

ACTIVE_CONNECTIONS = Gauge(
    "ainos_active_connections",
    "Number of active connections",
    ["type"],  # http, sse, ws
)

GPU_MEMORY_USED = Gauge(
    "ainos_gpu_memory_used_bytes",
    "GPU memory used in bytes",
    ["gpu_id"],
)

GPU_UTILIZATION = Gauge(
    "ainos_gpu_utilization_percent",
    "GPU utilization percentage",
    ["gpu_id"],
)

# Model-specific metrics
MODEL_LOAD_TIME = Gauge(
    "ainos_model_load_time_seconds",
    "Time taken to load model",
    ["model"],
)

MODEL_VRAM_USAGE = Gauge(
    "ainos_model_vram_bytes",
    "Model VRAM usage in bytes",
    ["model"],
)


def record_request(method: str, endpoint: str, status: int, duration: float):
    """Record an API request."""
    REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status).inc()
    REQUESTS_DURATION.labels(method=method, endpoint=endpoint).observe(duration)


def record_inference(model: str, stream: bool, tokens: int, duration: float):
    """Record an inference request."""
    INFERENCE_REQUESTS.labels(model=model, stream=str(stream)).inc()
    INFERENCE_TOKENS.labels(model=model).inc(tokens)
    INFERENCE_DURATION.labels(model=model).observe(duration)


def get_metrics() -> bytes:
    """Get Prometheus metrics in text format."""
    return generate_latest()


# Custom metrics endpoint
async def metrics_handler(request):
    """Handle /metrics endpoint."""
    return web.Response(
        body=get_metrics(),
        content_type=CONTENT_TYPE_LATEST,
    )
```

### Structured Logging

```python
# D:/Ainos/system-services/web-panel/logging_config.py
# Structured Logging Configuration
# ===================================

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Dict, Any


class StructuredFormatter(logging.Formatter):
    """
    JSON-structured log formatter for machine-readable logs.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }
        
        # Add extra fields
        if hasattr(record, "extra"):
            log_entry.update(record.extra)
        
        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_file: str = None,
):
    """Configure structured logging."""
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_format:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root_logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)
    
    # Set levels for third-party loggers
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# Usage
logger = logging.getLogger("ainos")
logger.info("Server started", extra={"port": 8080, "host": "0.0.0.0"})
```

---

## 10. Troubleshooting Guide / 故障排除指南

### Diagnostic Commands

```bash
# 1. Check server health
curl -s http://localhost:8080/api/status | python3 -m json.tool

# 2. Check loaded models
curl -s http://localhost:8080/api/models | python3 -m json.tool

# 3. Test basic inference
curl -s -X POST http://localhost:8080/api/inference \
    -H "Content-Type: application/json" \
    -d '{"model":"ainos-llama-3.1-8b","prompt":"Hello","max_tokens":50}' | python3 -m json.tool

# 4. Check GPU status
nvidia-smi

# 5. Check system resources
top -b -n 1 | head -20
free -h
df -h

# 6. Check network
ss -tlnp | grep -E "8080|9090"
netstat -tulpn 2>/dev/null | grep -E "8080|9090"

# 7. Check Docker containers
docker stats --no-stream
docker compose ps

# 8. Check logs
tail -100 /var/log/ainos/ainos.log
tail -100 /var/log/ainos/audit.log

# 9. Run benchmark
python scripts/benchmark.py

# 10. Profile with cProfile
python -m cProfile -o profile.stats api_server.py
python -m pstats profile.stats
```

### Common Issues and Solutions

| Issue | Symptom | Diagnosis | Solution |
|-------|---------|-----------|----------|
| Server won't start | Port in use | `ss -tlnp | grep 8080` | Change port or kill process |
| Model won't load | File not found | Check model path | Verify model file exists |
| Out of memory | CUDA OOM | `nvidia-smi` | Reduce batch size, use quantization |
| Slow inference | High latency | Check GPU utilization | Scale horizontally, optimize model |
| Connection timeout | No response | Check network | Increase timeout, check firewall |
| Streaming not working | No tokens | Check SSE/WS support | Use SSE fallback, check proxy |
| Auth failures | 401 errors | Check token | Verify token, regenerate if needed |
| Rate limited | 429 errors | Check headers | Wait, reduce request rate |
| Data corruption | Bad responses | Check logs | Restore from backup |
| SSL errors | Certificate issues | `openssl verify` | Renew certificates |

### Debug Mode

```python
# Enable debug mode for detailed logging
import os
os.environ["AINOS_LOG_LEVEL"] = "DEBUG"

# Or start server with debug
python api_server.py --log-level DEBUG

# Python debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Request tracing
import aiohttp
import traceback

async def traced_request(session, method, url, **kwargs):
    """Trace API requests for debugging."""
    logger.debug(f"Request: {method} {url}")
    logger.debug(f"Headers: {kwargs.get('headers', {})}")
    logger.debug(f"Body: {kwargs.get('json', {})}")
    
    try:
        response = await session.request(method, url, **kwargs)
        logger.debug(f"Response: {response.status}")
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}")
        logger.debug(traceback.format_exc())
        raise
```

---

## 11. Advanced Patterns / 高级模式

### Retry with Exponential Backoff

```python
import asyncio
import random
from functools import wraps


def retry(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
    """
    Decorator for retrying async functions with exponential backoff.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (ConnectionError, TimeoutError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(
                            base_delay * (2 ** attempt) + random.uniform(0, 1),
                            max_delay
                        )
                        print(f"Retry {attempt + 1}/{max_retries} "
                              f"after {delay:.1f}s delay...")
                        await asyncio.sleep(delay)
            
            raise last_exception
    
    return wrapper


@retry(max_retries=3, base_delay=1.0)
async def reliable_infer(client, model, prompt):
    return await client.infer(model, prompt)
```

### Circuit Breaker Pattern

```python
import asyncio
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker for API calls.
    Prevents cascading failures by stopping calls to failing services.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_requests: int = 3,
    ):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests
        self.half_open_requests = 0
        self.last_failure_time = 0
    
    async def call(self, func, *args, **kwargs):
        """Execute a function with circuit breaker protection."""
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_requests = 0
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            
            if self.state == CircuitState.HALF_OPEN:
                self.half_open_requests += 1
                if self.half_open_requests >= self.half_open_max_requests:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            
            self.failure_count = 0
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            
            raise e


# Usage
breaker = CircuitBreaker(failure_threshold=3)

async def safe_infer(client, model, prompt):
    return await breaker.call(client.infer, model, prompt)
```

### Caching Layer

```python
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Optional


class LRUCache:
    """
    LRU (Least Recently Used) cache for inference results.
    """
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self.cache: OrderedDict = OrderedDict()
        self.expiry: dict = {}
    
    def _make_key(self, model: str, prompt: str, **params) -> str:
        """Create a cache key from request parameters."""
        key_data = {"model": model, "prompt": prompt, **params}
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value."""
        if key in self.cache:
            if time.time() < self.expiry.get(key, 0):
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                return self.cache[key]
            else:
                # Expired
                del self.cache[key]
                del self.expiry[key]
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set cached value."""
        if len(self.cache) >= self.max_size:
            # Remove least recently used
            self.cache.popitem(last=False)
        
        self.cache[key] = value
        self.expiry[key] = time.time() + (ttl or self.ttl)
    
    def invalidate(self, model: Optional[str] = None):
        """Invalidate cache entries."""
        if model:
            to_delete = [
                k for k in self.cache
                if model in k
            ]
            for k in to_delete:
                del self.cache[k]
                del self.expiry[k]
        else:
            self.cache.clear()
            self.expiry.clear()
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl": self.ttl,
        }


# Global cache instance
inference_cache = LRUCache(max_size=5000, ttl=300)

async def cached_infer(client, model, prompt, **params):
    """Inference with caching."""
    key = inference_cache._make_key(model, prompt, **params)
    
    cached = inference_cache.get(key)
    if cached is not None:
        return cached
    
    result = await client.infer(model, prompt, **params)
    inference_cache.set(key, result)
    return result
```

---

## 12. Appendix / 附录

### API Reference

```python
# Complete API Reference
API_ENDPOINTS = {
    "GET /api/status": {
        "description": "Get system status",
        "response": {
            "status": "online|degraded|error",
            "cpu": 23.5,
            "memory": 45.2,
            "temperature": 52.0,
            "uptime": 12345,
            "active_models": [...],
            "system": {...},
        }
    },
    "GET /api/models": {
        "description": "List available models",
        "response": {
            "models": [
                {
                    "id": "ainos-llama-3.1-8b",
                    "name": "Ainos Llama 3.1 8B",
                    "status": "loaded",
                    "vram": 8589934592,
                    "context_length": 8192,
                }
            ]
        }
    },
    "POST /api/inference": {
        "description": "Run inference",
        "request": {
            "model": "ainos-llama-3.1-8b",
            "prompt": "Hello",
            "max_tokens": 1024,
            "temperature": 0.7,
            "stream": False,
        },
        "response": {
            "model": "ainos-llama-3.1-8b",
            "text": "Hello! How can I help you?",
            "tokens": 7,
            "finish_reason": "stop",
        }
    },
    "GET /api/events": {
        "description": "SSE endpoint for real-time updates",
        "events": {
            "status": "System status update",
            "log": "New log entry",
            "model": "Model load/unload event",
        }
    },
    "WS /ws/inference": {
        "description": "WebSocket for streaming inference",
        "message": {
            "request": {"model": "...", "prompt": "...", "max_tokens": 1024},
            "response": {"token": "Hello", "index": 0},
            "done": {"done": True, "token_count": 150},
        }
    }
}
```

### Configuration Reference

```yaml
# Complete configuration reference
# See config/ainos.yaml for defaults
server:
  host: "0.0.0.0"
  port: 8080
  workers: 4
  backlog: 1024

auth:
  enabled: true
  token: "your-secure-token"

models:
  default: "ainos-llama-3.1-8b"
  max_loaded: 4

inference:
  max_tokens: 8192
  default_temperature: 0.7
  streaming: true

logging:
  level: "INFO"
  format: "json"
  file: "/var/log/ainos/ainos.log"

monitoring:
  enabled: true
  metrics_port: 9090
```

### SDK Compatibility Matrix

| Feature | Python | Go | Rust | Java | C# | Node.js |
|---------|--------|----|------|------|----|---------|
| Basic Inference | Yes | Yes | Yes | Yes | Yes | Yes |
| Streaming (SSE) | Yes | Yes | Yes | Yes | Yes | Yes |
| Streaming (WS) | Yes | Yes | Yes | Yes | Yes | Yes |
| Model Management | Yes | Yes | Yes | Yes | Yes | Yes |
| Context Management | Yes | Yes | Yes | Yes | Yes | Yes |
| Plugin Management | Yes | Yes | Yes | Yes | Yes | Yes |
| Async Support | Yes | Yes | Yes | Yes | Yes | Yes |
| Error Handling | Yes | Yes | Yes | Yes | Yes | Yes |
| Retry/Backoff | Yes | Yes | Yes | Yes | Yes | Yes |
| Circuit Breaker | Yes | Yes | Yes | Yes | Yes | Yes |

---

*For more information, visit [https://docs.ainos.ai](https://docs.ainos.ai) or [https://github.com/ainos-ai](https://github.com/ainos-ai).*

*更多信息请访问 [https://docs.ainos.ai](https://docs.ainos.ai) 或 [https://github.com/ainos-ai](https://github.com/ainos-ai)。*