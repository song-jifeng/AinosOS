# 插件开发教程

## 概述

AinosOS 插件系统允许开发者扩展 AI 推理引擎的功能。插件可以拦截推理流程、添加自定义处理逻辑、集成外部服务等。

## 插件架构

```
+------------------------------------------+
|              AinosOS 核心                 |
+------------------------------------------+
|           插件管理器 (Plugin Manager)      |
+------------+------------+----------------+
| 预处理器   | 过滤器     | 后处理器        |
| (PreProcessor)| (Filter) | (PostProcessor)|
+------------+------------+----------------+
|           插件实例 (Plugin Instance)      |
+------------------------------------------+
|    插件 A    |    插件 B    |    插件 C    |
+-------------+-------------+-------------+
```

## 1. 插件 API

### 插件接口

```c
#include <ainos/plugin.h>

// 插件信息结构体
typedef struct ainos_plugin_info {
    const char* name;             // 插件名称
    const char* version;          // 插件版本
    const char* description;      // 插件描述
    const char* author;           // 作者
    const char* license;          // 许可证
    uint32_t api_version;         // API 版本
} ainos_plugin_info_t;

// 插件上下文
typedef struct ainos_plugin_ctx {
    void* plugin_data;            // 插件私有数据
    ainos_plugin_config_t config; // 插件配置
    ainos_logger_t* logger;       // 日志接口
    ainos_plugin_api_t* api;      // 核心 API
} ainos_plugin_ctx_t;

// 插件生命周期回调
typedef struct ainos_plugin_callbacks {
    // 必需回调
    int (*on_load)(ainos_plugin_ctx_t* ctx);
    int (*on_unload)(ainos_plugin_ctx_t* ctx);
    
    // 可选回调
    int (*on_init)(ainos_plugin_ctx_t* ctx);
    int (*on_config_change)(ainos_plugin_ctx_t* ctx, 
                            const ainos_plugin_config_t* old_config,
                            const ainos_plugin_config_t* new_config);
    int (*on_inference_start)(ainos_plugin_ctx_t* ctx, 
                              ainos_inference_request_t* request);
    int (*on_inference_end)(ainos_plugin_ctx_t* ctx, 
                            ainos_inference_request_t* request,
                            ainos_inference_response_t* response);
    int (*on_token_generated)(ainos_plugin_ctx_t* ctx,
                              const char* token,
                              ainos_inference_request_t* request);
    int (*on_error)(ainos_plugin_ctx_t* ctx, 
                    int error_code, const char* error_message);
} ainos_plugin_callbacks_t;

// 插件注册宏
#define AINOS_PLUGIN_DEFINE(info, callbacks) \
    ainos_plugin_info_t ainos_plugin_info = info; \
    ainos_plugin_callbacks_t ainos_plugin_callbacks = callbacks;
```

### Python 插件 API

```python
from ainos.plugin import BasePlugin, PluginContext

class MyPlugin(BasePlugin):
    """自定义插件基类"""
    
    def __init__(self):
        super().__init__()
        self.name = "my-plugin"
        self.version = "1.0.0"
        self.description = "My custom plugin"
    
    def on_load(self, ctx: PluginContext) -> int:
        """插件加载时调用"""
        return 0
    
    def on_unload(self, ctx: PluginContext) -> int:
        """插件卸载时调用"""
        return 0
    
    def on_init(self, ctx: PluginContext) -> int:
        """插件初始化时调用"""
        return 0
    
    def on_inference_start(self, ctx: PluginContext, request: dict) -> int:
        """推理开始时调用"""
        return 0
    
    def on_inference_end(self, ctx: PluginContext, request: dict, response: dict) -> int:
        """推理结束时调用"""
        return 0
    
    def on_token_generated(self, ctx: PluginContext, token: str, request: dict) -> int:
        """生成每个 Token 时调用"""
        return 0
    
    def on_config_change(self, ctx: PluginContext, old_config: dict, new_config: dict) -> int:
        """配置变更时调用"""
        return 0
```

## 2. 插件生命周期

### 生命周期状态机

```
[未加载] --加载--> [已加载] --初始化--> [已初始化] --启用--> [已启用]
                                                              |
[已启用] --开始推理--> [推理中] --完成--> [已启用]
[已启用] --禁用--> [已禁用]
[已启用/已禁用] --卸载--> [已卸载]
```

### 生命周期回调流程

```python
from ainos.plugin import BasePlugin, PluginContext
import logging

class LifecyclePlugin(BasePlugin):
    """生命周期演示插件"""
    
    def on_load(self, ctx: PluginContext) -> int:
        """插件加载时调用
        用途：解析配置、分配资源
        返回：0 成功，非零失败
        """
        self.logger = logging.getLogger(self.name)
        self.logger.info(f"插件 {self.name} 加载中")
        
        # 读取配置
        self.threshold = ctx.config.get("threshold", 0.5)
        self.enabled_features = ctx.config.get("features", [])
        
        # 分配资源
        self.cache = {}
        self.stats = {"processed": 0, "errors": 0}
        
        self.logger.info(f"插件 {self.name} 加载完成")
        return 0
    
    def on_init(self, ctx: PluginContext) -> int:
        """插件初始化时调用
        用途：建立连接、注册钩子
        """
        self.logger.info("初始化插件")
        
        # 注册钩子
        ctx.register_hook("pre_inference", self.pre_inference_hook)
        ctx.register_hook("post_inference", self.post_inference_hook)
        
        # 连接外部服务
        if "redis" in self.enabled_features:
            self.redis_client = ctx.connect_redis(
                host=ctx.config.get("redis_host", "localhost"),
                port=ctx.config.get("redis_port", 6379)
            )
        
        return 0
    
    def on_config_change(self, ctx: PluginContext, old_config: dict, new_config: dict) -> int:
        """配置变更时调用
        用途：热更新配置
        """
        changed_keys = set(old_config.keys()) ^ set(new_config.keys())
        for key in old_config:
            if old_config.get(key) != new_config.get(key):
                changed_keys.add(key)
        
        self.logger.info(f"配置变更: {changed_keys}")
        
        # 更新配置
        self.threshold = new_config.get("threshold", 0.5)
        self.enabled_features = new_config.get("features", [])
        
        return 0
    
    def on_unload(self, ctx: PluginContext) -> int:
        """插件卸载时调用
        用途：释放资源、关闭连接
        """
        self.logger.info("卸载插件")
        
        # 释放资源
        self.cache.clear()
        
        # 关闭连接
        if hasattr(self, 'redis_client'):
            self.redis_client.close()
        
        # 保存统计
        self._save_stats()
        
        return 0
```

## 3. 钩子系统

### 钩子类型

| 钩子名称 | 触发时机 | 参数 | 可修改请求 |
|---------|---------|------|-----------|
| pre_inference | 推理开始前 | request | 是 |
| post_inference | 推理结束后 | request, response | 是 |
| pre_token_generate | 生成每个 Token 前 | request, token | 是 |
| post_token_generate | 生成每个 Token 后 | request, token | 否 |
| pre_model_load | 模型加载前 | model_path, params | 是 |
| post_model_load | 模型加载后 | model_info | 否 |
| pre_model_unload | 模型卸载前 | model_id | 否 |
| post_model_unload | 模型卸载后 | model_id | 否 |
| on_error | 错误发生时 | error_code, message | 否 |
| on_request | 收到请求时 | request | 是 |
| on_response | 发送响应前 | response | 是 |

### 注册和触发钩子

```python
from ainos.plugin import BasePlugin, PluginContext, hook

class HookDemoPlugin(BasePlugin):
    """钩子系统演示插件"""
    
    def on_init(self, ctx: PluginContext) -> int:
        # 注册钩子
        ctx.register_hook("pre_inference", self.validate_request)
        ctx.register_hook("pre_inference", self.add_context)
        ctx.register_hook("post_inference", self.log_response)
        ctx.register_hook("on_error", self.handle_error)
        ctx.register_hook("pre_token_generate", self.filter_tokens)
        
        # 注册条件钩子（仅在特定条件下触发）
        ctx.register_hook(
            "pre_inference",
            self.check_rate_limit,
            priority=100,  # 高优先级，先执行
            condition=lambda req: req.get("user_id") is not None
        )
        
        return 0
    
    @hook(priority=10)
    def validate_request(self, ctx: PluginContext, request: dict) -> int:
        """验证请求参数"""
        required_fields = ["model_id", "prompt"]
        for field in required_fields:
            if field not in request:
                ctx.logger.error(f"缺少必需字段: {field}")
                return -1  # 返回非零值阻止推理
        
        # 验证 prompt 长度
        if len(request["prompt"]) > ctx.config.get("max_prompt_length", 4096):
            ctx.logger.warning("Prompt 过长，将被截断")
            request["prompt"] = request["prompt"][:4096]
        
        return 0
    
    @hook(priority=20)
    def add_context(self, ctx: PluginContext, request: dict) -> int:
        """添加额外上下文"""
        # 添加系统提示
        system_prompt = ctx.config.get("system_prompt", "")
        if system_prompt:
            request["prompt"] = f"{system_prompt}\n\n{request['prompt']}"
        
        # 添加用户信息
        if "user_id" in request:
            request["prompt"] = f"[User: {request['user_id']}]\n{request['prompt']}"
        
        return 0
    
    @hook(priority=5)
    def check_rate_limit(self, ctx: PluginContext, request: dict) -> int:
        """检查速率限制"""
        import time
        
        user_id = request.get("user_id")
        if not user_id:
            return 0
        
        # 获取用户的请求计数
        current_time = time.time()
        window = ctx.config.get("rate_limit_window", 60)  # 60 秒窗口
        max_requests = ctx.config.get("rate_limit", 100)  # 100 次
        
        # 清理过期记录
        self._requests = getattr(self, '_requests', {})
        if user_id not in self._requests:
            self._requests[user_id] = []
        
        self._requests[user_id] = [
            t for t in self._requests[user_id]
            if current_time - t < window
        ]
        
        # 检查限制
        if len(self._requests[user_id]) >= max_requests:
            ctx.logger.warning(f"用户 {user_id} 超过速率限制")
            return -1  # 拒绝请求
        
        self._requests[user_id].append(current_time)
        return 0
    
    @hook
    def log_response(self, ctx: PluginContext, request: dict, response: dict) -> int:
        """记录响应"""
        ctx.logger.info(
            f"推理完成: "
            f"prompt={len(request['prompt'])} chars, "
            f"output={len(response.get('output', ''))} chars, "
            f"time={response.get('inference_time_ms', 0):.0f}ms"
        )
        
        # 更新统计
        self._stats = getattr(self, '_stats', {"total_requests": 0, "total_tokens": 0})
        self._stats["total_requests"] += 1
        self._stats["total_tokens"] += response.get("tokens_generated", 0)
        
        return 0
    
    @hook
    def handle_error(self, ctx: PluginContext, error_code: int, error_message: str) -> int:
        """处理错误"""
        ctx.logger.error(f"错误 [{error_code}]: {error_message}")
        
        # 错误计数
        self._errors = getattr(self, '_errors', 0)
        self._errors += 1
        
        # 某些错误自动重试
        retryable_codes = [-5, -6]  # 超时和连接错误
        if error_code in retryable_codes:
            ctx.logger.info("错误可重试")
        
        return 0
    
    @hook
    def filter_tokens(self, ctx: PluginContext, token: str, request: dict) -> int:
        """过滤敏感 Token"""
        # 敏感词过滤
        sensitive_words = ctx.config.get("sensitive_words", [])
        for word in sensitive_words:
            if word in token:
                ctx.logger.warning(f"过滤敏感词: {word}")
                token = token.replace(word, "***")
                return 1  # 返回 1 表示修改了 Token
        
        # 重复 Token 过滤
        if hasattr(self, '_last_token') and token == self._last_token:
            # 连续相同 Token 超过 10 次则跳过
            self._repeat_count = getattr(self, '_repeat_count', 0) + 1
            if self._repeat_count > 10:
                ctx.logger.warning("检测到重复 Token，跳过")
                self._repeat_count = 0
                return -1  # 跳过此 Token
        else:
            self._repeat_count = 0
        
        self._last_token = token
        return 0
```

## 4. 示例插件

### 示例 1: 日志记录插件

```python
from ainos.plugin import BasePlugin, PluginContext
import json
import time
import os

class LoggingPlugin(BasePlugin):
    """推理日志记录插件"""
    
    def __init__(self):
        super().__init__()
        self.name = "logging-plugin"
        self.version = "1.0.0"
        self.description = "记录所有推理请求和响应"
    
    def on_load(self, ctx: PluginContext) -> int:
        self.log_dir = ctx.config.get("log_dir", "/var/log/ainos/plugins")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(
            self.log_dir, 
            f"inference_{time.strftime('%Y%m%d')}.log"
        )
        self._log_count = 0
        return 0
    
    def on_inference_start(self, ctx: PluginContext, request: dict) -> int:
        # 记录请求开始
        log_entry = {
            "timestamp": time.time(),
            "event": "inference_start",
            "request_id": request.get("id"),
            "model": request.get("model_id"),
            "prompt_length": len(request.get("prompt", "")),
            "params": {
                "temperature": request.get("temperature"),
                "max_tokens": request.get("max_tokens"),
                "top_p": request.get("top_p")
            }
        }
        self._write_log(log_entry)
        return 0
    
    def on_inference_end(self, ctx: PluginContext, request: dict, response: dict) -> int:
        # 记录请求结束
        log_entry = {
            "timestamp": time.time(),
            "event": "inference_end",
            "request_id": request.get("id"),
            "tokens_generated": response.get("tokens_generated"),
            "inference_time_ms": response.get("inference_time_ms"),
            "tokens_per_second": response.get("tokens_per_second"),
            "finish_reason": response.get("finish_reason")
        }
        self._write_log(log_entry)
        self._log_count += 1
        return 0
    
    def on_token_generated(self, ctx: PluginContext, token: str, request: dict) -> int:
        # 记录每个 Token（可选，会大量产生日志）
        if ctx.config.get("log_tokens", False):
            log_entry = {
                "timestamp": time.time(),
                "event": "token_generated",
                "request_id": request.get("id"),
                "token": repr(token)
            }
            self._write_log(log_entry)
        return 0
    
    def _write_log(self, entry: dict):
        """写入日志"""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def on_unload(self, ctx: PluginContext) -> int:
        ctx.logger.info(f"日志插件卸载，共记录 {self._log_count} 条推理")
        return 0
```

### 示例 2: 内容安全插件

```python
from ainos.plugin import BasePlugin, PluginContext
import re

class ContentSafetyPlugin(BasePlugin):
    """内容安全过滤插件"""
    
    def __init__(self):
        super().__init__()
        self.name = "content-safety"
        self.version = "1.0.0"
        self.description = "过滤不安全的内容"
    
    def on_load(self, ctx: PluginContext) -> int:
        # 加载敏感词列表
        self.sensitive_patterns = []
        word_list = ctx.config.get("sensitive_words", [])
        for word in word_list:
            self.sensitive_patterns.append(re.compile(re.escape(word), re.IGNORECASE))
        
        # 加载正则规则
        regex_rules = ctx.config.get("regex_rules", [])
        for rule in regex_rules:
            self.sensitive_patterns.append(re.compile(rule, re.IGNORECASE))
        
        self.block_action = ctx.config.get("block_action", "filter")  # filter/block/replace
        self.replacement = ctx.config.get("replacement", "***")
        
        ctx.logger.info(f"内容安全插件已加载，{len(self.sensitive_patterns)} 条规则")
        return 0
    
    def on_inference_start(self, ctx: PluginContext, request: dict) -> int:
        """检查输入内容"""
        prompt = request.get("prompt", "")
        
        for pattern in self.sensitive_patterns:
            if pattern.search(prompt):
                ctx.logger.warning(f"检测到敏感内容: {pattern.pattern}")
                
                if self.block_action == "block":
                    ctx.logger.info("阻止请求")
                    return -1  # 阻止推理
                elif self.block_action == "filter":
                    # 过滤敏感词
                    request["prompt"] = pattern.sub(self.replacement, prompt)
                    ctx.logger.info("过滤敏感词")
        
        return 0
    
    def on_token_generated(self, ctx: PluginContext, token: str, request: dict) -> int:
        """检查输出 Token"""
        for pattern in self.sensitive_patterns:
            if pattern.search(token):
                ctx.logger.warning(f"输出包含敏感内容: {token}")
                
                if self.block_action == "block":
                    return -1  # 停止生成
                elif self.block_action == "filter":
                    token = pattern.sub(self.replacement, token)
                    return 1  # 修改 Token
        
        return 0
    
    def on_config_change(self, ctx: PluginContext, old_config: dict, new_config: dict) -> int:
        """热更新规则"""
        # 重新加载配置
        self.on_load(ctx)
        return 0
```

### 示例 3: 缓存插件

```python
from ainos.plugin import BasePlugin, PluginContext
import hashlib
import json
import time

class CachePlugin(BasePlugin):
    """推理结果缓存插件"""
    
    def __init__(self):
        super().__init__()
        self.name = "cache-plugin"
        self.version = "1.0.0"
        self.description = "缓存推理结果，提高重复请求的响应速度"
    
    def on_load(self, ctx: PluginContext) -> int:
        self.cache = {}
        self.max_size = ctx.config.get("max_cache_size", 1000)
        self.ttl = ctx.config.get("cache_ttl", 300)  # 5 分钟
        self.hit_count = 0
        self.miss_count = 0
        return 0
    
    def _make_cache_key(self, request: dict) -> str:
        """生成缓存键"""
        key_data = {
            "model_id": request.get("model_id"),
            "prompt": request.get("prompt"),
            "temperature": request.get("temperature", 0.7),
            "max_tokens": request.get("max_tokens", 512),
            "top_p": request.get("top_p", 0.9)
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def on_inference_start(self, ctx: PluginContext, request: dict) -> int:
        """检查缓存"""
        if not ctx.config.get("enabled", True):
            return 0
        
        cache_key = self._make_cache_key(request)
        
        # 检查缓存
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            
            # 检查 TTL
            if time.time() - entry["timestamp"] < self.ttl:
                ctx.logger.info("缓存命中")
                self.hit_count += 1
                
                # 设置缓存结果，让框架直接返回
                request["_cached_response"] = entry["response"]
                return 1  # 返回 1 表示使用缓存
        
        # 保存缓存键供后续使用
        request["_cache_key"] = cache_key
        self.miss_count += 1
        return 0
    
    def on_inference_end(self, ctx: PluginContext, request: dict, response: dict) -> int:
        """保存结果到缓存"""
        cache_key = request.get("_cache_key")
        if not cache_key or not ctx.config.get("enabled", True):
            return 0
        
        # 只缓存成功的响应
        if response.get("finish_reason") != "error":
            # 管理缓存大小
            if len(self.cache) >= self.max_size:
                # 删除最旧的条目
                oldest_key = min(self.cache.keys(), 
                                key=lambda k: self.cache[k]["timestamp"])
                del self.cache[oldest_key]
            
            self.cache[cache_key] = {
                "response": response,
                "timestamp": time.time()
            }
        
        return 0
    
    def on_unload(self, ctx: PluginContext) -> int:
        total = self.hit_count + self.miss_count
        if total > 0:
            hit_rate = self.hit_count / total * 100
            ctx.logger.info(
                f"缓存统计: 命中 {self.hit_count}, "
                f"未命中 {self.miss_count}, "
                f"命中率 {hit_rate:.1f}%"
            )
        self.cache.clear()
        return 0
```

### 示例 4: 提示词优化插件

```python
from ainos.plugin import BasePlugin, PluginContext

class PromptOptimizerPlugin(BasePlugin):
    """提示词优化插件"""
    
    def __init__(self):
        super().__init__()
        self.name = "prompt-optimizer"
        self.version = "1.0.0"
        self.description = "自动优化提示词以提高推理质量"
    
    def on_load(self, ctx: PluginContext) -> int:
        self.max_prompt_length = ctx.config.get("max_prompt_length", 4096)
        self.enable_auto_format = ctx.config.get("enable_auto_format", True)
        self.enable_template = ctx.config.get("enable_template", False)
        self.templates = ctx.config.get("templates", {})
        return 0
    
    def on_inference_start(self, ctx: PluginContext, request: dict) -> int:
        prompt = request.get("prompt", "")
        
        # 1. 自动格式化
        if self.enable_auto_format:
            prompt = self._auto_format(prompt)
        
        # 2. 应用模板
        if self.enable_template:
            template_name = request.get("template", "default")
            if template_name in self.templates:
                prompt = self.templates[template_name].format(prompt=prompt)
        
        # 3. 截断过长的提示词
        if len(prompt) > self.max_prompt_length:
            prompt = prompt[:self.max_prompt_length]
        
        request["prompt"] = prompt
        return 0
    
    def _auto_format(self, prompt: str) -> str:
        """自动格式化提示词"""
        prompt = prompt.strip()
        
        # 确保以标点结尾
        if prompt and prompt[-1] not in ".!?；。！？":
            prompt += "。"
        
        # 添加换行
        if len(prompt) > 200:
            import textwrap
            prompt = textwrap.fill(prompt, width=80)
        
        # 确保首字母大写（英文）
        if prompt and prompt[0].isalpha():
            prompt = prompt[0].upper() + prompt[1:]
        
        return prompt
```

## 5. 插件配置

### 插件配置文件

```yaml
# /etc/ainos/plugins/logging-plugin.yaml
name: logging-plugin
enabled: true
version: "1.0.0"
config:
  log_dir: "/var/log/ainos/plugins"
  log_tokens: false
  log_level: "info"
```

### 加载插件

```python
# 在 AinosOS 配置中启用插件
plugins:
  enabled: true
  directory: "/etc/ainos/plugins"
  auto_load: true
```

## 6. 调试插件

```python
from ainos.plugin import BasePlugin, PluginContext

class DebugPlugin(BasePlugin):
    """调试插件"""
    
    def on_load(self, ctx: PluginContext) -> int:
        ctx.logger.set_level("debug")
        return 0
    
    def on_inference_start(self, ctx: PluginContext, request: dict) -> int:
        ctx.logger.debug(f"请求详情: {request}")
        return 0
```

## 部署建议

1. **性能影响**: 插件会增加推理延迟，合理使用钩子
2. **错误处理**: 确保插件不会使主服务崩溃
3. **资源管理**: 及时释放插件资源
4. **配置管理**: 使用配置文件管理插件行为
5. **日志记录**: 适当记录插件运行日志
6. **版本兼容**: 注意插件 API 版本兼容性