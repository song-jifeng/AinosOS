# 自定义模型教程

## 概述

AinosOS 支持多种模型格式，本文档介绍如何准备、转换和优化自定义模型，以便在 AinosOS 上运行。

## 支持的模型格式

| 格式 | 扩展名 | 说明 | 支持程度 |
|------|--------|------|---------|
| GGUF | .gguf | 推荐格式，支持量化 | 完整支持 |
| GGML | .ggml | 旧格式，已弃用 | 兼容模式 |
| SafeTensors | .safetensors | HuggingFace 格式 | 需转换 |
| PyTorch | .bin/.pt | PyTorch 格式 | 需转换 |
| ONNX | .onnx | 开放神经网络格式 | 实验性支持 |

## 1. 模型格式说明

### GGUF 格式

GGUF (GPT-Generated Unified Format) 是 AinosOS 推荐使用的模型格式，具有以下特点：

- **自包含**: 模型权重、配置和 Tokenizer 在同一文件中
- **支持量化**: 内置多种量化方案
- **版本控制**: 格式版本管理，向前兼容
- **元数据**: 支持丰富的元数据信息

GGUF 文件结构：

```
+------------------+
| GGUF Header      |  # 魔数 "GGUF" + 版本号
+------------------+
| Tensor Info      |  # 张量名称、类型、维度、偏移量
+------------------+
| Metadata KV      |  # 模型元数据（名称、架构、参数等）
+------------------+
| Tokenizer Data   |  # Tokenizer 词汇表和配置
+------------------+
| Tensor Data      |  # 量化后的权重数据
+------------------+
```

### 模型架构支持

| 架构 | 支持情况 | 说明 |
|------|---------|------|
| LLaMA | 完整支持 | LLaMA, LLaMA 2, LLaMA 3, LLaMA 3.1 |
| Mistral | 完整支持 | Mistral v0.1, v0.2, v0.3 |
| Mixtral | 完整支持 | Mixtral 8x7B, 8x22B |
| Qwen2 | 完整支持 | Qwen 2, Qwen 2.5 |
| DeepSeek | 完整支持 | DeepSeek V2, Coder V2 |
| Phi-3 | 完整支持 | Phi-3 Mini, Small, Medium, Vision |
| Gemma | 完整支持 | Gemma 1, Gemma 2 |
| Yi | 完整支持 | Yi 1.5 |
| Falcon | 支持 | Falcon 7B, 40B, 180B |
| GPT-NeoX | 支持 | GPT-NeoX, Pythia |
| StableLM | 支持 | StableLM 2, 3 |
| BLOOM | 实验性 | BLOOM 176B |
| Command-R | 实验性 | Command-R, Command-R+ |

## 2. 模型转换指南

### 安装转换工具

```bash
# 安装 AinosOS 模型转换工具
pip install ainos-model-tools

# 或从源码安装
git clone https://github.com/ainos/ainos-model-tools.git
cd ainos-model-tools
pip install -e .
```

### 从 HuggingFace 转换

```python
from ainos_model_tools import convert_hf_to_gguf

# 基本转换
convert_hf_to_gguf(
    model_path="/path/to/huggingface/model",
    output_path="/models/my-model.gguf",
    architecture="llama"  # 模型架构
)

# 带量化转换
convert_hf_to_gguf(
    model_path="/path/to/huggingface/model",
    output_path="/models/my-model-q4_k_m.gguf",
    architecture="llama",
    quantization="Q4_K_M",  # 指定量化类型
    metadata={
        "name": "My Custom Model",
        "description": "A custom fine-tuned model",
        "version": "1.0.0",
        "author": "My Team"
    }
)
```

### 命令行转换

```bash
# 基本转换
ainos-convert \
    --input /path/to/huggingface/model \
    --output /models/my-model.gguf \
    --architecture llama

# 带量化转换
ainos-convert \
    --input /path/to/huggingface/model \
    --output /models/my-model-q4_k_m.gguf \
    --architecture llama \
    --quantization Q4_K_M \
    --model-name "My Custom Model" \
    --model-version "1.0.0"

# 从 SafeTensors 转换
ainos-convert \
    --input /path/to/model.safetensors \
    --output /models/my-model.gguf \
    --format safetensors \
    --architecture mistral

# 从 PyTorch checkpoint 转换
ainos-convert \
    --input /path/to/pytorch_model.bin \
    --output /models/my-model.gguf \
    --format pytorch \
    --architecture qwen2
```

### 批量转换脚本

```python
#!/usr/bin/env python3
"""批量转换 HuggingFace 模型到 GGUF 格式"""

import os
import glob
from ainos_model_tools import convert_hf_to_gguf

def batch_convert_hf_models(input_dir, output_dir, architectures=None):
    """批量转换 HuggingFace 模型"""
    
    if architectures is None:
        architectures = {
            "llama": "llama",
            "mistral": "mistral",
            "qwen2": "qwen2",
            "phi3": "phi3",
            "gemma2": "gemma2",
        }
    
    # 扫描模型目录
    model_dirs = glob.glob(os.path.join(input_dir, "*"))
    
    for model_dir in model_dirs:
        if not os.path.isdir(model_dir):
            continue
        
        model_name = os.path.basename(model_dir)
        print(f"处理模型: {model_name}")
        
        # 检测架构
        config_path = os.path.join(model_dir, "config.json")
        if not os.path.exists(config_path):
            print(f"  跳过: 无 config.json")
            continue
        
        import json
        with open(config_path) as f:
            config = json.load(f)
        
        arch = config.get("model_type", "").lower()
        if arch not in architectures:
            print(f"  不支持的架构: {arch}")
            continue
        
        # 输出路径
        output_path = os.path.join(output_dir, f"{model_name}.gguf")
        
        try:
            convert_hf_to_gguf(
                model_path=model_dir,
                output_path=output_path,
                architecture=architectures[arch],
                metadata={
                    "name": model_name,
                    "source": "huggingface",
                    "original_architecture": arch
                }
            )
            print(f"  转换成功: {output_path}")
        except Exception as e:
            print(f"  转换失败: {e}")

# 使用示例
batch_convert_hf_models(
    input_dir="/data/hf_models",
    output_dir="/models/gguf"
)
```

## 3. 量化方法

### 量化类型对比

| 量化类型 | 位宽 | 模型大小比 | 质量损失 | 推荐场景 |
|---------|------|-----------|---------|---------|
| FP32 | 32-bit | 1x | 无 | 基准测试 |
| FP16 | 16-bit | 0.5x | 几乎无 | 高质量推理 |
| Q8_0 | 8-bit | 0.5x | 极小 | 质量优先 |
| Q6_K | 6-bit | 0.38x | 小 | 平衡质量 |
| Q5_K_M | 5-bit | 0.33x | 小 | 推荐 |
| Q5_0 | 5-bit | 0.33x | 小 | 速度优先 |
| Q4_K_M | 4-bit | 0.28x | 中等 | 通用推荐 |
| Q4_K_S | 4-bit | 0.25x | 中等 | 小模型 |
| Q4_0 | 4-bit | 0.25x | 中等 | 速度优先 |
| Q3_K_M | 3-bit | 0.21x | 较大 | 内存受限 |
| Q3_K_S | 3-bit | 0.19x | 较大 | 极简 |
| Q2_K | 2-bit | 0.15x | 大 | 极端内存受限 |
| IQ4_NL | 4-bit | 0.25x | 中等 | 非线性量化 |
| IQ3_XXS | 3-bit | 0.18x | 大 | 极小模型 |

### 使用命令行量化

```bash
# 量化已有 GGUF 模型
ainos-quantize \
    --input /models/my-model-f16.gguf \
    --output /models/my-model-q4_k_m.gguf \
    --type Q4_K_M

# 批量量化
for type in Q8_0 Q6_K Q5_K_M Q4_K_M Q3_K_M Q2_K; do
    ainos-quantize \
        --input /models/my-model-f16.gguf \
        --output /models/my-model-${type,,}.gguf \
        --type $type
done

# 仅量化部分层
ainos-quantize \
    --input /models/my-model.gguf \
    --output /models/my-model-mixed.gguf \
    --type Q4_K_M \
    --output-hidden-layers q8_0  # 输出层用更高精度
```

### 使用 Python 量化

```python
from ainos_model_tools import quantize_model

# 基本量化
quantize_model(
    input_path="/models/my-model-f16.gguf",
    output_path="/models/my-model-q4_k_m.gguf",
    quantization_type="Q4_K_M"
)

# 高级量化配置
quantize_model(
    input_path="/models/my-model-f16.gguf",
    output_path="/models/my-model-q4_k_m.gguf",
    quantization_type="Q4_K_M",
    num_threads=8,           # 并行线程数
    allow_requantize=True,    # 允许重新量化（从已量化模型）
    pure=True,               # 纯量化模式
    output_tensor_type="q8_0"  # 输出张量类型
)

# 自定义量化映射
from ainos_model_tools import QuantizationConfig

config = QuantizationConfig(
    default_type="Q4_K_M",
    layer_overrides={
        "token_embd.weight": "Q8_0",     # 嵌入层用高精度
        "output_norm.weight": "Q8_0",    # 归一化层用高精度
        "output.weight": "Q8_0",         # 输出层用高精度
        "blk.0.attn_q.weight": "Q5_K_M", # 第一层注意力用高精度
        "blk.1.attn_q.weight": "Q5_K_M",
    }
)

quantize_model(
    input_path="/models/my-model-f16.gguf",
    output_path="/models/my-model-custom.gguf",
    quantization_config=config
)
```

### 混合精度量化

```python
class MixedPrecisionQuantizer:
    """混合精度量化器"""
    
    def __init__(self, base_type="Q4_K_M"):
        self.base_type = base_type
        self.overrides = {}
    
    def set_attention_precision(self, precision="Q6_K"):
        """设置注意力层精度"""
        layer_names = [
            "attn_q", "attn_k", "attn_v", "attn_output"
        ]
        for name in layer_names:
            self.overrides[f"blk.*.{name}.weight"] = precision
    
    def set_ffn_precision(self, precision="Q4_K_M"):
        """设置前馈网络层精度"""
        layer_names = [
            "ffn_gate", "ffn_down", "ffn_up"
        ]
        for name in layer_names:
            self.overrides[f"blk.*.{name}.weight"] = precision
    
    def set_first_last_precision(self, precision="Q8_0"):
        """设置首尾层精度"""
        # 第一层
        self.overrides["blk.0.*.weight"] = precision
        # 最后一层
        self.overrides["blk.-1.*.weight"] = precision
        self.overrides["token_embd.weight"] = precision
        self.overrides["output_norm.weight"] = precision
        self.overrides["output.weight"] = precision
    
    def quantize(self, input_path, output_path):
        """执行混合精度量化"""
        config = QuantizationConfig(
            default_type=self.base_type,
            layer_overrides=self.overrides
        )
        quantize_model(input_path, output_path, quantization_config=config)

# 使用示例
quantizer = MixedPrecisionQuantizer(base_type="Q4_K_M")
quantizer.set_attention_precision("Q6_K")
quantizer.set_first_last_precision("Q8_0")
quantizer.quantize(
    "/models/model-f16.gguf",
    "/models/model-mixed.gguf"
)
```

## 4. 性能调优

### 模型性能基准测试

```python
from ainos_model_tools import benchmark_model
import time

def test_model_performance(model_path, quantization_types):
    """测试不同量化类型的性能"""
    
    for qtype in quantization_types:
        print(f"\n测试量化: {qtype}")
        
        # 量化模型
        quantized_path = f"/models/test-{qtype.lower()}.gguf"
        quantize_model(model_path, quantized_path, qtype)
        
        # 加载模型
        client = AinosClient()
        client.connect()
        model = client.load_model(quantized_path)
        
        # 测试推理性能
        prompt = "What is artificial intelligence? Please explain in detail."
        
        times = []
        tokens_counts = []
        for _ in range(10):
            start = time.time()
            result = client.inference(
                model.model_id, prompt, max_tokens=256
            )
            elapsed = time.time() - start
            times.append(elapsed)
            tokens_counts.append(result.tokens_generated)
        
        avg_time = sum(times) / len(times)
        avg_tokens = sum(tokens_counts) / len(tokens_counts)
        tokens_per_sec = avg_tokens / avg_time
        
        print(f"  平均耗时: {avg_time*1000:.0f}ms")
        print(f"  平均 Token: {avg_tokens:.0f}")
        print(f"  速度: {tokens_per_sec:.1f} tokens/s")
        print(f"  模型大小: {model.size_bytes / 1024**3:.1f} GB")
        
        client.unload_model(model.model_id)
        client.disconnect()

# 使用示例
test_model_performance(
    "/models/llama-3.1-8b-f16.gguf",
    ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"]
)
```

### 推理参数优化

```python
def optimize_inference_params(client, model_id):
    """优化推理参数"""
    
    prompt = "Explain quantum computing in simple terms."
    best_config = None
    best_speed = 0
    
    # 测试不同的参数组合
    configs = [
        {"num_threads": 4, "batch_size": 1},
        {"num_threads": 8, "batch_size": 1},
        {"num_threads": 4, "batch_size": 8},
        {"num_threads": 8, "batch_size": 8},
        {"num_threads": 8, "batch_size": 32},
        {"num_threads": 16, "batch_size": 8},
    ]
    
    for config in configs:
        print(f"测试配置: {config}")
        
        # 重新创建上下文
        ctx = client.create_context(
            model_id=model_id,
            batch_size=config["batch_size"]
        )
        
        times = []
        for _ in range(5):
            start = time.time()
            result = client.inference(
                model_id, prompt,
                context_id=ctx.context_id,
                num_threads=config["num_threads"],
                max_tokens=128
            )
            times.append(result.inference_time_ms)
        
        avg_time = sum(times) / len(times)
        speed = 128 / (avg_time / 1000) if avg_time > 0 else 0
        
        print(f"  平均延迟: {avg_time:.0f}ms, 速度: {speed:.1f} tokens/s")
        
        if speed > best_speed:
            best_speed = speed
            best_config = config
        
        ctx.close()
    
    print(f"\n最佳配置: {best_config}")
    print(f"最佳速度: {best_speed:.1f} tokens/s")
    return best_config
```

### 内存优化

```python
def optimize_memory_usage(client, model_id):
    """优化内存使用"""
    
    # 测试不同上下文大小的内存使用
    for context_size in [1024, 2048, 4096, 8192]:
        # 创建上下文
        ctx = client.create_context(
            model_id=model_id,
            context_size=context_size
        )
        
        # 获取模型信息
        info = client.get_model_info(model_id)
        
        print(f"上下文大小: {context_size}")
        print(f"  模型内存: {info.memory_usage_mb:.0f} MB")
        
        # 估计 KV 缓存大小
        kv_cache_mb = context_size * 2 * 0.5  # 粗略估计
        print(f"  KV 缓存估计: {kv_cache_mb:.0f} MB")
        print(f"  总计估计: {info.memory_usage_mb + kv_cache_mb:.0f} MB")
        
        ctx.close()
    
    # 选择 KV 缓存类型
    cache_types = ["auto", "fp16", "q8_0", "q4_0"]
    for cache_type in cache_types:
        ctx = client.create_context(
            model_id=model_id,
            context_size=4096,
            kv_cache_type=cache_type
        )
        print(f"KV 缓存类型 {cache_type}: OK")
        ctx.close()
```

### 部署性能检查清单

```python
def performance_checklist(client, model_id):
    """性能检查清单"""
    
    checks = []
    
    # 1. 检查推理速度
    result = client.inference(model_id, "Hello", max_tokens=100)
    speed = result.tokens_per_second
    checks.append(("推理速度", speed > 20, f"{speed:.1f} tokens/s"))
    
    # 2. 检查首 Token 延迟
    import time
    start = time.time()
    for token in client.inference(model_id, "Hello", stream=True, max_tokens=1):
        ttft = time.time() - start
        break
    checks.append(("首Token延迟", ttft < 0.5, f"{ttft*1000:.0f}ms"))
    
    # 3. 检查内存使用
    info = client.get_model_info(model_id)
    checks.append(("内存使用", info.memory_usage_mb < 16384, f"{info.memory_usage_mb:.0f}MB"))
    
    # 4. 检查批处理性能
    prompts = ["Hello"] * 8
    start = time.time()
    results = client.batch_inference(model_id, prompts, max_tokens=50)
    batch_time = time.time() - start
    total_tokens = sum(r.tokens_generated for r in results)
    checks.append(("批处理吞吐", total_tokens/batch_time > 50, f"{total_tokens/batch_time:.1f} tokens/s"))
    
    # 打印结果
    print("性能检查结果:")
    print("-" * 50)
    all_pass = True
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}: {detail}")
    
    print("-" * 50)
    print(f"总体: {'全部通过' if all_pass else '需要优化'}")
    
    return all_pass
```

## 5. 模型验证

### 验证模型完整性

```python
from ainos_model_tools import validate_model

def verify_model(filepath):
    """验证模型文件完整性"""
    
    print(f"验证模型: {filepath}")
    
    # 基本验证
    result = validate_model(filepath)
    
    print(f"  格式: {result.format}")
    print(f"  架构: {result.architecture}")
    print(f"  参数: {result.parameters}")
    print(f"  量化: {result.quantization}")
    print(f"  上下文长度: {result.context_length}")
    print(f"  文件大小: {result.file_size_gb:.2f} GB")
    print(f"  张量数: {result.tensor_count}")
    print(f"  元数据项: {result.metadata_count}")
    print(f"  校验和: {'匹配' if result.checksum_valid else '不匹配'}")
    
    if result.warnings:
        print("  警告:")
        for w in result.warnings:
            print(f"    - {w}")
    
    if result.errors:
        print("  错误:")
        for e in result.errors:
            print(f"    - {e}")
    
    return result.is_valid
```

### 测试模型推理

```python
def test_model_inference(model_path):
    """测试模型推理质量"""
    
    client = AinosClient()
    client.connect()
    
    # 加载模型
    model = client.load_model(model_path)
    print(f"加载模型: {model.name}")
    
    # 测试用例
    test_cases = [
        "Hello, how are you?",
        "What is 2+2?",
        "Write a haiku about AI.",
        "Translate 'hello' to Chinese.",
        "What is the capital of France?",
    ]
    
    print("\n测试推理:")
    for prompt in test_cases:
        result = client.inference(
            model.model_id, prompt, max_tokens=100, temperature=0.7
        )
        print(f"\n输入: {prompt}")
        print(f"输出: {result.output[:100]}...")
        print(f"耗时: {result.inference_time_ms:.0f}ms")
    
    client.unload_model(model.model_id)
    client.disconnect()
```

## 常见问题

### 1. 转换失败

**问题**: `RuntimeError: Unsupported model architecture`

**解决方案**:
- 确认模型架构在支持列表中
- 更新 ainos-model-tools 到最新版本
- 手动指定架构参数

### 2. 量化后质量下降

**问题**: 量化后模型输出质量明显下降

**解决方案**:
- 使用更高精度的量化（Q5_K_M 或 Q6_K）
- 使用混合精度量化（注意力层用高精度）
- 避免从已量化模型再次量化

### 3. 加载失败

**问题**: `Error: Model file is corrupted`

**解决方案**:
- 重新下载模型文件
- 检查文件校验和
- 使用 `validate_model` 检查文件完整性

### 4. 内存不足

**问题**: `Out of memory when loading model`

**解决方案**:
- 使用更低精度的量化
- 使用 `--low-memory` 模式
- 使用 mmap 加载模型
- 增加系统 swap 空间