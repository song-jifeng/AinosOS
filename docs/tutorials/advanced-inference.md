# 高级推理教程

## 概述

本文介绍 AinosOS 的高级推理功能，包括批处理推理、流式推理、上下文管理和模型热加载。这些功能可以帮助开发者最大限度地发挥 AI 模型的性能。

## 1. 批处理推理

批处理推理允许同时处理多个输入，显著提高吞吐量。适用于需要处理大量独立请求的场景。

### 基本原理

批处理推理将多个输入打包成一个批次，利用 GPU 的并行计算能力同时处理。相比单条处理，批处理可以显著提高吞吐量。

```
单条处理: 输入1 -> 输出1 (100ms)
          输入2 -> 输出2 (100ms)
          总时间: 200ms, 吞吐量: 10 tokens/s

批处理: [输入1, 输入2] -> [输出1, 输出2] (150ms)
        总时间: 150ms, 吞吐量: 13.3 tokens/s
```

### Python 示例

```python
from ainos import AinosClient

client = AinosClient()
client.connect()

# 基本批处理
prompts = [
    "解释什么是机器学习。",
    "什么是深度学习？",
    "解释神经网络的基本原理。",
    "什么是自然语言处理？",
    "解释计算机视觉。"
]

results = client.batch_inference(
    model_id="llama-8b",
    prompts=prompts,
    max_tokens=128,
    temperature=0.7
)

for i, result in enumerate(results):
    print(f"--- 输入 {i+1}: {prompts[i][:20]}... ---")
    print(f"输出: {result.output}")
    print(f"生成 {result.tokens_generated} tokens, 耗时 {result.inference_time_ms:.0f}ms")
    print()

client.disconnect()
```

### 批处理性能调优

```python
import time
import statistics
from ainos import AinosClient

def benchmark_batch_sizes(client, model_id, prompts, max_tokens=256):
    """测试不同批处理大小的性能"""
    for batch_size in [1, 2, 4, 8, 16, 32, 64]:
        # 准备批次
        batch = prompts[:batch_size]
        
        # 预热
        for _ in range(3):
            client.batch_inference(model_id, batch, max_tokens=10)
        
        # 测试
        times = []
        for _ in range(10):
            start = time.time()
            results = client.batch_inference(
                model_id, batch, max_tokens=max_tokens
            )
            elapsed = time.time() - start
            times.append(elapsed)
        
        total_tokens = sum(r.tokens_generated for r in results)
        avg_time = statistics.mean(times)
        throughput = total_tokens / avg_time
        
        print(f"批次大小 {batch_size:2d}: "
              f"平均耗时 {avg_time*1000:6.0f}ms, "
              f"吞吐量 {throughput:5.1f} tokens/s")

# 使用示例
client = AinosClient()
client.connect()
prompts = ["What is AI?"] * 64
benchmark_batch_sizes(client, "llama-8b", prompts)
client.disconnect()
```

### 批处理配置建议

| 批次大小 | 适用场景 | 延迟影响 | 吞吐量提升 |
|---------|---------|---------|-----------|
| 1 | 实时对话 | 最低 | 基准 |
| 4 | 轻量处理 | +20% | 3x |
| 8 | 批量处理 | +40% | 5x |
| 16 | 离线处理 | +80% | 8x |
| 32 | 高吞吐 | +150% | 12x |
| 64 | 极致吞吐 | +300% | 15x |

## 2. 流式推理

流式推理允许在生成过程中逐 Token 获取输出，减少首 Token 延迟，提升用户体验。

### 基本原理

流式推理在生成每个 Token 后立即发送给客户端，而不是等待所有 Token 生成完毕。

```
同步模式: 请求 -> [全部生成] -> 响应 (首Token延迟 = 总延迟)
流式模式: 请求 -> Token1 -> Token2 -> ... -> TokenN (首Token延迟 << 总延迟)
```

### Python 示例

```python
from ainos import AinosClient
import time

client = AinosClient()
client.connect()

# 基本流式推理
print("流式推理输出:")
for token in client.inference(
    model_id="llama-8b",
    prompt="写一篇关于人工智能的短文，200字左右。",
    stream=True,
    max_tokens=512,
    temperature=0.8
):
    print(token, end="", flush=True)
print()

# 流式推理统计
def stream_with_stats(client, model_id, prompt, **kwargs):
    """流式推理并统计性能"""
    start_time = time.time()
    first_token = True
    total_tokens = 0
    full_text = []
    
    for token in client.inference(
        model_id=model_id,
        prompt=prompt,
        stream=True,
        **kwargs
    ):
        if first_token:
            ttft = time.time() - start_time  # Time to First Token
            first_token = False
        
        full_text.append(token)
        total_tokens += 1
        print(token, end="", flush=True)
    
    total_time = time.time() - start_time
    tokens_per_second = total_tokens / total_time if total_time > 0 else 0
    
    print("\n\n--- 统计 ---")
    print(f"首Token延迟: {ttft*1000:.1f}ms")
    print(f"总 Token 数: {total_tokens}")
    print(f"总耗时: {total_time:.1f}s")
    print(f"速度: {tokens_per_second:.1f} tokens/s")
    
    return "".join(full_text)

# 使用统计功能
text = stream_with_stats(
    client,
    model_id="llama-8b",
    prompt="解释量子计算的基本原理。",
    max_tokens=256,
    temperature=0.7
)

client.disconnect()
```

### 流式推理的应用场景

```python
# 1. 实时聊天应用
class ChatBot:
    def __init__(self, client, model_id):
        self.client = client
        self.model_id = model_id
        self.history = []
    
    def chat(self, message):
        """实时聊天，流式输出"""
        self.history.append({"role": "user", "content": message})
        full_response = []
        
        print("AI: ", end="", flush=True)
        for token in self.client.inference(
            model_id=self.model_id,
            prompt=self.format_prompt(),
            stream=True,
            max_tokens=1024
        ):
            print(token, end="", flush=True)
            full_response.append(token)
        
        print()
        response = "".join(full_response)
        self.history.append({"role": "assistant", "content": response})
        return response
    
    def format_prompt(self):
        """格式化对话历史"""
        formatted = ""
        for msg in self.history[-6:]:  # 保留最近6轮
            role = msg["role"]
            content = msg["content"]
            formatted += f"<{role}>\n{content}\n</{role}>\n"
        formatted += "<assistant>\n"
        return formatted

# 使用示例
client = AinosClient()
client.connect()
bot = ChatBot(client, "llama-8b")
bot.chat("你好！")
bot.chat("你能做什么？")
bot.chat("给我讲个笑话。")
client.disconnect()


# 2. 实时翻译
def real_time_translate(client, text, source_lang="en", target_lang="zh"):
    """实时翻译，流式输出"""
    prompt = f"Translate from {source_lang} to {target_lang}: {text}"
    
    print(f"翻译 ({source_lang} -> {target_lang}): ", end="", flush=True)
    translated = []
    for token in client.inference(
        model_id="llama-8b",
        prompt=prompt,
        stream=True,
        max_tokens=512,
        temperature=0.3  # 翻译使用较低温度
    ):
        print(token, end="", flush=True)
        translated.append(token)
    print()
    return "".join(translated)


# 3. 代码生成预览
def code_generate_preview(client, description, language="python"):
    """代码生成，流式输出，实时预览"""
    prompt = f"Write {language} code to {description}. Only output the code."
    
    code_lines = []
    print(f"```{language}")
    for token in client.inference(
        model_id="llama-8b",
        prompt=prompt,
        stream=True,
        max_tokens=2048,
        temperature=0.2  # 代码生成使用较低温度
    ):
        print(token, end="", flush=True)
        code_lines.append(token)
    print("\n```")
    return "".join(code_lines)
```

### 流式推理超时处理

```python
import asyncio
import time
from typing import Optional

class TimeoutStream:
    """带超时的流式推理包装器"""
    
    def __init__(self, client, model_id, prompt, timeout=30, **kwargs):
        self.client = client
        self.model_id = model_id
        self.prompt = prompt
        self.timeout = timeout
        self.kwargs = kwargs
        self.start_time = None
        self.last_token_time = None
    
    def __iter__(self):
        self.start_time = time.time()
        self.last_token_time = time.time()
        return self._stream()
    
    def _stream(self):
        for token in self.client.inference(
            model_id=self.model_id,
            prompt=self.prompt,
            stream=True,
            **self.kwargs
        ):
            # 检查总超时
            if time.time() - self.start_time > self.timeout:
                print("\n[流式推理超时]")
                break
            
            # 检查 Token 间超时（5秒无新Token）
            if time.time() - self.last_token_time > 5:
                print("\n[Token 生成超时]")
                break
            
            self.last_token_time = time.time()
            yield token

# 使用示例
client = AinosClient()
client.connect()

stream = TimeoutStream(
    client, "llama-8b", "写一篇很长的文章...",
    timeout=60, max_tokens=4096
)
for token in stream:
    print(token, end="", flush=True)

client.disconnect()
```

## 3. 上下文管理

上下文管理是高级推理的关键功能，它允许模型在多轮对话中保持一致性。

### 创建和管理上下文

```python
from ainos import AinosClient

client = AinosClient()
client.connect()
client.load_model("/models/llama-3.1-8b.q4_k_m.gguf", model_id="llama-8b")

# 创建上下文
ctx = client.create_context(
    model_id="llama-8b",
    context_size=4096,  # 上下文长度
    batch_size=32       # 批处理大小
)
print(f"上下文创建成功: {ctx.context_id}")

# 多轮对话，共享上下文
def multi_turn_chat(ctx, client, messages):
    """多轮对话，使用同一上下文"""
    for i, msg in enumerate(messages):
        print(f"\n--- 第 {i+1} 轮 ---")
        print(f"用户: {msg}")
        
        result = client.inference(
            model_id="llama-8b",
            prompt=msg,
            context_id=ctx.context_id,  # 使用同一上下文
            max_tokens=256
        )
        print(f"AI: {result.output}")
        print(f"上下文 Token 数: {ctx.get_token_count()}")

# 连续对话
messages = [
    "我的名字是张三。",
    "你还记得我的名字吗？",
    "我刚才说了什么？",
    "你能总结一下我们的对话吗？"
]
multi_turn_chat(ctx, client, messages)

# 清理上下文
ctx.close()
client.disconnect()
```

### 上下文窗口管理

```python
class ContextWindowManager:
    """上下文窗口管理器，自动管理 Token 数量"""
    
    def __init__(self, client, model_id, max_tokens=4096, reserve_tokens=512):
        self.client = client
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
        self.context = None
        self.history = []
    
    def start(self):
        """创建上下文"""
        self.context = self.client.create_context(
            model_id=self.model_id,
            context_size=self.max_tokens
        )
        return self.context
    
    def add_message(self, role, content):
        """添加消息，自动管理窗口"""
        self.history.append({"role": role, "content": content})
        self._trim_context()
    
    def _trim_context(self):
        """当上下文超过限制时，裁剪早期消息"""
        token_count = self.context.get_token_count()
        if token_count > self.max_tokens - self.reserve_tokens:
            # 移除最早的消息（保留系统提示）
            while len(self.history) > 2 and \
                  self.context.get_token_count() > self.max_tokens - self.reserve_tokens:
                removed = self.history.pop(1)  # 保留第一条（系统提示）
                print(f"上下文裁剪: 移除消息 '{removed['content'][:20]}...'")
                # 重新构建上下文
                self.context.clear()
    
    def chat(self, message):
        """对话"""
        self.add_message("user", message)
        
        full_response = []
        for token in self.client.inference(
            model_id=self.model_id,
            prompt=message,
            context_id=self.context.context_id,
            stream=True
        ):
            print(token, end="", flush=True)
            full_response.append(token)
        print()
        
        response = "".join(full_response)
        self.add_message("assistant", response)
        return response
    
    def close(self):
        """清理"""
        if self.context:
            self.context.close()

# 使用示例
client = AinosClient()
client.connect()
client.load_model("/models/llama-3.1-8b.q4_k_m.gguf", model_id="llama-8b")

manager = ContextWindowManager(client, "llama-8b", max_tokens=2048)
manager.start()

# 模拟长对话
for i in range(20):
    response = manager.chat(f"这是第 {i+1} 条消息，请回复一些内容。")
    print(f"当前 Token 数: {manager.context.get_token_count()}")

manager.close()
client.disconnect()
```

### 上下文持久化

```python
import json
import time

class PersistentContext:
    """支持持久化的上下文管理"""
    
    def __init__(self, client, model_id, context_id=None):
        self.client = client
        self.model_id = model_id
        self.context_id = context_id
        self.history = []
    
    def save(self, filepath):
        """保存上下文到文件"""
        state = {
            "model_id": self.model_id,
            "context_id": self.context_id,
            "history": self.history,
            "saved_at": time.time()
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"上下文已保存到 {filepath}")
    
    @classmethod
    def load(cls, client, filepath):
        """从文件加载上下文"""
        with open(filepath, "r", encoding="utf-8") as f:
            state = json.load(f)
        
        # 重新创建上下文
        ctx = cls(client, state["model_id"])
        ctx.context_id = state["context_id"]
        ctx.history = state["history"]
        
        # 创建新的上下文（因为旧的上线文可能已失效）
        new_ctx = client.create_context(
            model_id=ctx.model_id,
            context_id=ctx.context_id  # 尝试恢复
        )
        ctx.context = new_ctx
        return ctx

# 使用示例
client = AinosClient()
client.connect()

# 保存上下文
ctx = PersistentContext(client, "llama-8b")
ctx.save("/tmp/chat_context.json")

# 加载上下文
loaded = PersistentContext.load(client, "/tmp/chat_context.json")
print(f"恢复上下文: {loaded.context_id}")
print(f"历史消息数: {len(loaded.history)}")

client.disconnect()
```

## 4. 模型热加载

模型热加载允许在不重启服务的情况下加载、卸载和切换模型。

### 基础热加载

```python
from ainos import AinosClient
import time

client = AinosClient()
client.connect()

# 热加载模型
def hot_load_model(client, path, model_id, quantization="Q4_K_M"):
    """热加载模型"""
    start = time.time()
    model = client.load_model(
        model_path=path,
        model_id=model_id,
        quantization=quantization
    )
    elapsed = time.time() - start
    print(f"模型 {model_id} 加载完成: {elapsed:.1f}s")
    print(f"  内存占用: {model.memory_usage_mb:.0f} MB")
    return model

# 热卸载模型
def hot_unload_model(client, model_id):
    """热卸载模型"""
    start = time.time()
    client.unload_model(model_id)
    elapsed = time.time() - start
    print(f"模型 {model_id} 已卸载: {elapsed:.1f}s")

# 热切换模型
def hot_switch_model(client, old_model, new_path, new_id):
    """热切换模型"""
    print(f"正在从 {old_model} 切换到 {new_id}...")
    hot_unload_model(client, old_model)
    hot_load_model(client, new_path, new_id)
    print("模型切换完成")

# 使用示例
# 加载模型A
hot_load_model(client, "/models/llama-3.1-8b.q4_k_m.gguf", "llama-8b")

# 使用模型A推理
result = client.inference("llama-8b", "Hello with model A")
print(f"模型A: {result.output}")

# 加载模型B（不卸载A）
hot_load_model(client, "/models/qwen-2.5-7b.q4_k_m.gguf", "qwen-7b")

# 使用模型B推理
result = client.inference("qwen-7b", "Hello with model B")
print(f"模型B: {result.output}")

# 卸载模型A
hot_unload_model(client, "llama-8b")

client.disconnect()
```

### 自动模型管理

```python
class ModelManager:
    """自动模型管理器"""
    
    def __init__(self, client, max_models=3, unload_idle_after=300):
        self.client = client
        self.max_models = max_models
        self.unload_idle_after = unload_idle_after
        self.models = {}  # model_id -> {info, last_used, usage_count}
        self._start_monitor()
    
    def _start_monitor(self):
        """启动后台监控线程"""
        import threading
        def monitor():
            while True:
                self._unload_idle_models()
                time.sleep(60)
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def _unload_idle_models(self):
        """卸载空闲模型"""
        now = time.time()
        for model_id, data in list(self.models.items()):
            if now - data["last_used"] > self.unload_idle_after:
                print(f"自动卸载空闲模型: {model_id}")
                self.client.unload_model(model_id)
                del self.models[model_id]
    
    def load(self, path, model_id=None, **kwargs):
        """加载模型，自动管理数量"""
        if model_id is None:
            model_id = path.split("/")[-1].split(".")[0]
        
        # 如果已加载，直接返回
        if model_id in self.models:
            self.models[model_id]["last_used"] = time.time()
            return self.models[model_id]["info"]
        
        # 检查是否达到最大数量
        while len(self.models) >= self.max_models:
            # 卸载最久未使用的模型
            oldest = min(self.models.items(), key=lambda x: x[1]["last_used"])
            print(f"达到最大模型数，卸载: {oldest[0]}")
            self.client.unload_model(oldest[0])
            del self.models[oldest[0]]
        
        # 加载新模型
        info = self.client.load_model(path, model_id=model_id, **kwargs)
        self.models[model_id] = {
            "info": info,
            "last_used": time.time(),
            "usage_count": 0
        }
        return info
    
    def infer(self, model_id, prompt, **kwargs):
        """推理，自动更新使用时间"""
        if model_id not in self.models:
            raise ValueError(f"模型 {model_id} 未加载")
        
        self.models[model_id]["last_used"] = time.time()
        self.models[model_id]["usage_count"] += 1
        
        return self.client.inference(model_id, prompt, **kwargs)
    
    def get_stats(self):
        """获取统计信息"""
        return {
            model_id: {
                "name": data["info"].name,
                "usage_count": data["usage_count"],
                "idle_seconds": time.time() - data["last_used"],
                "memory_mb": data["info"].memory_usage_mb
            }
            for model_id, data in self.models.items()
        }

# 使用示例
client = AinosClient()
client.connect()

manager = ModelManager(client, max_models=2, unload_idle_after=60)

# 加载多个模型
manager.load("/models/llama-3.1-8b.q4_k_m.gguf", "llama-8b")
manager.load("/models/qwen-2.5-7b.q4_k_m.gguf", "qwen-7b")
manager.load("/models/phi-3-medium.q4_k_m.gguf", "phi-3")  # 会卸载最久未使用的

# 推理
result = manager.infer("llama-8b", "Hello")
print(f"结果: {result.output}")

# 查看统计
stats = manager.get_stats()
for model_id, s in stats.items():
    print(f"{model_id}: {s}")

client.disconnect()
```

### 模型热加载高级用法

```python
# 1. 异步热加载
async def async_hot_load(client, models):
    """异步加载多个模型"""
    import asyncio
    tasks = []
    for path, model_id in models:
        task = asyncio.create_task(
            client.load_model_async(path, model_id=model_id)
        )
        tasks.append((model_id, task))
    
    for model_id, task in tasks:
        model = await task
        print(f"异步加载完成: {model_id}")

# 2. 按需加载
class LazyModelLoader:
    """按需加载模型，第一次使用时才加载"""
    
    def __init__(self, client):
        self.client = client
        self._models = {}
    
    def register(self, name, path, **kwargs):
        """注册模型但不加载"""
        self._models[name] = {"path": path, "kwargs": kwargs, "loaded": False}
    
    def get(self, name):
        """获取模型，未加载时自动加载"""
        if name not in self._models:
            raise ValueError(f"未知模型: {name}")
        
        model = self._models[name]
        if not model["loaded"]:
            print(f"按需加载模型: {name}")
            model["info"] = self.client.load_model(
                model["path"], model_id=name, **model["kwargs"]
            )
            model["loaded"] = True
        
        return model["info"]
    
    def infer(self, name, prompt, **kwargs):
        """推理，自动按需加载"""
        self.get(name)
        return self.client.inference(name, prompt, **kwargs)

# 使用示例
client = AinosClient()
client.connect()

loader = LazyModelLoader(client)
loader.register("llama-8b", "/models/llama-3.1-8b.q4_k_m.gguf")
loader.register("qwen-7b", "/models/qwen-2.5-7b.q4_k_m.gguf")

# 第一次推理时自动加载
result = loader.infer("llama-8b", "Hello")
print(f"结果: {result.output}")

client.disconnect()
```

## 性能优化建议

### 1. 批处理参数调优

```python
# 根据模型大小调整批处理大小
batch_size_map = {
    "7b": 64,
    "8b": 64,
    "13b": 32,
    "34b": 16,
    "70b": 8,
    "72b": 8,
    "405b": 2
}

# 根据硬件调整批处理大小
def get_optimal_batch_size(gpu_memory_gb, model_size_b):
    """根据 GPU 内存计算最佳批处理大小"""
    # 模型需要约 0.5 bytes/parameter (Q4_K)
    memory_per_token = model_size_b * 0.5 / 1024 / 1024 / 1024  # GB
    overhead = 1.5  # 额外开销因子
    max_batch = int(gpu_memory_gb / (memory_per_token * overhead))
    return min(max(1, max_batch), 64)
```

### 2. KV 缓存优化

```python
# 根据上下文长度调整 KV 缓存
context_to_cache = {
    1024: 64,
    2048: 128,
    4096: 256,
    8192: 512,
    16384: 1024,
    32768: 2048
}

# 选择合适的 KV 缓存数据类型
# auto: 根据模型自动选择
# fp16: 高质量，高内存
# q8_0: 较好质量，中等内存
# q4_0: 可接受质量，低内存
```

### 3. 并发控制

```python
# 使用连接池处理并发请求
from concurrent.futures import ThreadPoolExecutor
import threading

class ConcurrentInferenceEngine:
    """并发推理引擎"""
    
    def __init__(self, client, max_workers=4):
        self.client = client
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
    
    def infer_batch_concurrent(self, model_id, prompts, **kwargs):
        """并发批处理推理"""
        futures = []
        for prompt in prompts:
            future = self.executor.submit(
                self.client.inference, model_id, prompt, **kwargs
            )
            futures.append(future)
        
        results = []
        for future in futures:
            results.append(future.result())
        return results

# 使用示例
client = AinosClient()
client.connect()

engine = ConcurrentInferenceEngine(client, max_workers=8)
prompts = [f"Question {i}?" for i in range(100)]
results = engine.infer_batch_concurrent("llama-8b", prompts, max_tokens=50)
print(f"处理完成: {len(results)} 个请求")

client.disconnect()
```