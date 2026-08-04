# AinosOS 配置指南

## 概述

AinosOS 使用 YAML 格式的配置文件，支持通过配置文件、环境变量和命令行参数三种方式进行配置。配置优先级：命令行参数 > 环境变量 > 配置文件 > 默认值。

## 配置文件位置

### 默认路径

| 平台 | 配置文件路径 |
|------|------------|
| Linux | /etc/ainos/config.yaml |
| Windows | C:\ProgramData\Ainos\config.yaml |
| macOS | /usr/local/etc/ainos/config.yaml |
| 自定义 | 通过 --config 参数指定 |

### 配置加载顺序

1. 编译时的默认配置
2. 默认路径的配置文件（如果存在）
3. --config 参数指定的配置文件
4. 环境变量覆盖
5. 命令行参数覆盖

## 配置文件格式

### 完整配置示例

```yaml
# ============================================
# AinosOS 全局配置
# ============================================

# 服务配置
server:
  host: "0.0.0.0"              # 监听地址
  port: 9500                    # 监听端口
  socket: "/tmp/ainos.ipc"     # Unix Socket 路径（可选）
  workers: 4                    # 工作进程数
  max_connections: 1024         # 最大连接数
  backlog: 128                  # 连接队列大小
  shutdown_timeout: 30          # 关闭超时（秒）

# 日志配置
logging:
  level: "info"                 # 日志级别: trace/debug/info/warn/error
  format: "json"                # 日志格式: text/json
  output: "stdout"              # 输出目标: stdout/file/both
  file: "/var/log/ainos/ainos.log"  # 日志文件路径
  max_size: 100                 # 单个日志文件最大大小（MB）
  max_files: 10                 # 日志文件最大数量
  max_age: 30                   # 日志保留天数
  compress: true                # 是否压缩旧日志

# AI 推理引擎配置
inference:
  engine: "auto"                # 推理引擎: auto/cpu/cuda/vulkan/metal
  device: "auto"                # 设备选择: auto/cpu/gpu
  gpu_devices: [0]             # GPU 设备列表
  gpu_layers: 0                 # GPU 加速层数（0 为全部 CPU）
  gpu_memory_limit: 0           # GPU 内存限制（字节，0 为不限制）
  num_threads: 4                # 推理线程数
  batch_size: 64                # 批处理大小
  context_size: 8192            # 默认上下文大小
  max_tokens: 2048              # 默认最大生成 Token 数
  temperature: 0.7              # 默认温度参数
  top_p: 0.9                    # 默认 Top-P 参数
  top_k: 40                     # 默认 Top-K 参数
  repeat_penalty: 1.1           # 默认重复惩罚
  use_mmap: true                # 使用内存映射加载模型
  use_mlock: false              # 锁定内存防止交换
  low_memory: false             # 低内存模式
  flash_attention: true         # 启用 Flash Attention
  tensor_parallel: 1            # 张量并行度
  pipeline_parallel: 1          # 流水线并行度

# 模型管理配置
models:
  auto_load: false              # 启动时自动加载模型
  auto_load_path: ""            # 自动加载的模型路径
  model_dir: "/models"          # 模型文件目录
  cache_dir: "/var/cache/ainos" # 缓存目录
  download_dir: "/tmp/ainos_download" # 下载临时目录
  default_quantization: "Q4_K_M" # 默认量化类型
  max_loaded_models: 5          # 最大同时加载模型数
  unload_idle_after: 3600       # 空闲模型自动卸载时间（秒）

# 内存管理配置
memory:
  kv_cache_size: 512           # KV 缓存大小（MB）
  kv_cache_type: "auto"        # KV 缓存类型: auto/fp16/q8_0/q4_0
  use_hugepage: false           # 使用大页内存
  hugepage_size: 2              # 大页大小（MB）
  memory_limit: 0               # 总内存限制（字节，0 为不限制）
  swap_limit: 0                 # 交换内存限制（字节，0 为不限制）
  allocator: "default"          # 内存分配器: default/jemalloc/tcmalloc

# 网络配置
network:
  tls_enabled: false            # 启用 TLS 加密
  tls_cert: ""                  # TLS 证书路径
  tls_key: ""                   # TLS 私钥路径
  tls_ca: ""                    # TLS CA 证书路径
  tls_verify_client: false      # 验证客户端证书
  proxy_protocol: false         # 启用 Proxy Protocol
  keepalive: true               # 启用 TCP Keepalive
  keepalive_idle: 300           # Keepalive 空闲时间（秒）
  keepalive_interval: 60        # Keepalive 间隔（秒）
  keepalive_count: 5            # Keepalive 重试次数

# 认证配置
auth:
  enabled: true                 # 启用认证
  method: "jwt"                 # 认证方式: jwt/api_key/none
  jwt_secret: ""                # JWT 密钥（留空自动生成）
  jwt_algorithm: "HS256"        # JWT 算法: HS256/HS384/HS512/RS256
  jwt_expiry: 86400             # JWT 过期时间（秒）
  api_key_file: ""              # API Key 文件路径
  rate_limit_enabled: true      # 启用速率限制
  rate_limit: 100               # 默认速率限制（请求/分钟）
  rate_limit_burst: 200         # 速率限制突发值

# 会话管理配置
session:
  enabled: true                 # 启用会话管理
  ttl: 3600                     # 会话 TTL（秒）
  max_sessions: 1000            # 最大会话数
  store_type: "memory"          # 会话存储类型: memory/redis/file
  redis_url: ""                 # Redis 连接 URL（store_type=redis 时使用）

# 上下文管理配置
context:
  max_contexts: 100             # 最大上下文数
  default_ttl: 3600             # 默认上下文 TTL（秒）
  store_type: "memory"          # 上下文存储类型: memory/redis/file
  redis_url: ""                 # Redis 连接 URL
  cleanup_interval: 300         # 清理间隔（秒）

# 监控和指标配置
monitoring:
  metrics_enabled: true         # 启用指标收集
  metrics_port: 9090            # 指标 HTTP 端口（Prometheus）
  metrics_path: "/metrics"      # 指标路径
  health_check_path: "/health"  # 健康检查路径
  profiling_enabled: false      # 启用性能分析
  profiling_port: 6060          # 性能分析端口
  tracing_enabled: false        # 启用分布式追踪
  tracing_endpoint: ""          # 追踪端点

# 缓存配置
cache:
  enabled: true                 # 启用缓存
  type: "memory"                # 缓存类型: memory/redis
  memory_size: 256              # 内存缓存大小（MB）
  redis_url: ""                 # Redis 连接 URL
  ttl: 300                      # 缓存 TTL（秒）
  max_entries: 10000            # 最大缓存条目数

# 插件配置
plugins:
  enabled: false                # 启用插件系统
  directory: "/etc/ainos/plugins" # 插件目录
  auto_load: true               # 自动加载插件
  allow_remote: false           # 允许远程插件
  timeout: 30                   # 插件执行超时（秒）

# 集群配置
cluster:
  enabled: false                # 启用集群模式
  node_name: "node-1"           # 节点名称
  node_role: "worker"           # 节点角色: leader/worker/standalone
  discovery: "static"           # 发现方式: static/dns/consul/etcd
  peers: []                     # 对等节点列表
  consul_url: ""                # Consul 地址
  etcd_url: ""                  # etcd 地址
  heartbeat_interval: 5         # 心跳间隔（秒）
  heartbeat_timeout: 15         # 心跳超时（秒）

# 代理配置
proxy:
  enabled: false                # 启用代理
  http_proxy: ""                # HTTP 代理
  https_proxy: ""               # HTTPS 代理
  no_proxy: ""                  # 不使用代理的地址
  socks_proxy: ""               # SOCKS 代理
```

## 配置项详细说明

### 服务配置 (server)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| host | string | "0.0.0.0" | 监听地址，设为 127.0.0.1 仅本地访问 |
| port | int | 9500 | 监听端口，0-65535 |
| socket | string | "" | Unix Domain Socket 路径，优先级高于 host:port |
| workers | int | 4 | 工作进程数，一般设为 CPU 核心数 |
| max_connections | int | 1024 | 最大并发连接数 |
| backlog | int | 128 | TCP 连接队列大小 |
| shutdown_timeout | int | 30 | 优雅关闭等待时间（秒） |

### 日志配置 (logging)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| level | string | "info" | 日志级别: trace(0), debug(1), info(2), warn(3), error(4) |
| format | string | "json" | json 格式适合日志收集系统，text 适合人类阅读 |
| output | string | "stdout" | stdout 输出到控制台，file 输出到文件 |
| file | string | "" | 日志文件路径，output 为 file 或 both 时有效 |
| max_size | int | 100 | 日志轮转大小（MB） |
| max_files | int | 10 | 保留的日志文件数 |
| max_age | int | 30 | 日志保留天数 |
| compress | bool | true | 是否 gzip 压缩轮转的日志文件 |

### 推理配置 (inference)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| engine | string | "auto" | auto 自动选择，cpu 强制 CPU，cuda/vulkan/metal 对应 GPU 后端 |
| device | string | "auto" | auto 自动选择最佳设备 |
| gpu_devices | array | [0] | 指定使用的 GPU 设备 ID |
| gpu_layers | int | 0 | GPU 加速的 Transformer 层数，-1 表示全部 |
| gpu_memory_limit | int | 0 | GPU 内存使用上限（字节） |
| num_threads | int | 4 | CPU 推理线程数 |
| batch_size | int | 64 | 批处理推理的最大批大小 |
| context_size | int | 8192 | 默认推理上下文长度 |
| max_tokens | int | 2048 | 默认最大生成 Token 数 |
| use_mmap | bool | true | 通过 mmap 加载模型，减少内存使用 |
| use_mlock | bool | false | 锁定模型内存，防止被交换到磁盘 |
| flash_attention | bool | true | 使用 Flash Attention 算法加速推理 |
| tensor_parallel | int | 1 | 张量并行度，多 GPU 时使用 |
| pipeline_parallel | int | 1 | 流水线并行度，多 GPU 时使用 |

### 模型配置 (models)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| model_dir | string | "/models" | 模型文件搜索目录 |
| cache_dir | string | "/var/cache/ainos" | 模型缓存目录 |
| default_quantization | string | "Q4_K_M" | 加载模型时的默认量化类型 |
| max_loaded_models | int | 5 | 同时加载的最大模型数 |
| unload_idle_after | int | 3600 | 模型空闲多久后自动卸载（秒） |

### 内存配置 (memory)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| kv_cache_size | int | 512 | KV 缓存大小（MB），影响可处理的上下文长度 |
| kv_cache_type | string | "auto" | KV 缓存数据类型，影响内存使用和精度 |
| use_hugepage | bool | false | 使用大页内存提升性能（需要系统配置） |
| memory_limit | int | 0 | 进程总内存上限（字节） |
| allocator | string | "default" | 内存分配器选择 |

### 网络配置 (network)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| tls_enabled | bool | false | 启用 TLS 加密通信 |
| tls_cert | string | "" | TLS 证书文件路径（PEM 格式） |
| tls_key | string | "" | TLS 私钥文件路径 |
| keepalive | bool | true | 启用 TCP Keepalive 检测死连接 |

### 认证配置 (auth)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| enabled | bool | true | 启用认证，生产环境建议开启 |
| method | string | "jwt" | jwt 使用 JWT Token，api_key 使用 API Key |
| jwt_secret | string | "" | JWT 签名密钥，留空启动时自动生成 |
| jwt_expiry | int | 86400 | JWT Token 过期时间（秒），24 小时 |
| rate_limit_enabled | bool | true | 启用速率限制防止滥用 |

## 环境变量

### 通用环境变量

```bash
# 服务器配置
export AINOS_HOST="0.0.0.0"
export AINOS_PORT="9500"
export AINOS_SOCKET="/tmp/ainos.ipc"
export AINOS_WORKERS="4"
export AINOS_MAX_CONNECTIONS="1024"

# 日志配置
export AINOS_LOG_LEVEL="info"
export AINOS_LOG_FILE="/var/log/ainos/ainos.log"
export AINOS_LOG_FORMAT="json"

# 推理配置
export AINOS_INFERENCE_ENGINE="auto"
export AINOS_GPU_DEVICES="0"
export AINOS_GPU_LAYERS="32"
export AINOS_NUM_THREADS="8"
export AINOS_CONTEXT_SIZE="8192"
export AINOS_BATCH_SIZE="64"
export AINOS_USE_MMAP="true"
export AINOS_FLASH_ATTENTION="true"

# 模型配置
export AINOS_MODEL_DIR="/models"
export AINOS_CACHE_DIR="/var/cache/ainos"
export AINOS_DEFAULT_QUANTIZATION="Q4_K_M"
export AINOS_MAX_LOADED_MODELS="5"

# 内存配置
export AINOS_KV_CACHE_SIZE="512"
export AINOS_MEMORY_LIMIT="0"
export AINOS_USE_HUGEPAGE="false"

# 认证配置
export AINOS_AUTH_ENABLED="true"
export AINOS_AUTH_METHOD="jwt"
export AINOS_JWT_SECRET="your-secret-key"
export AINOS_API_KEY_FILE="/etc/ainos/api_keys.txt"

# 监控配置
export AINOS_METRICS_ENABLED="true"
export AINOS_METRICS_PORT="9090"

# 缓存配置
export AINOS_CACHE_ENABLED="true"
export AINOS_CACHE_TYPE="memory"
export AINOS_CACHE_MEMORY_SIZE="256"

# 代理配置
export AINOS_HTTP_PROXY="http://proxy:8080"
export AINOS_HTTPS_PROXY="http://proxy:8080"
export AINOS_NO_PROXY="localhost,127.0.0.1"
```

### 环境变量命名规则

环境变量名格式为 `AINOS_{SECTION}_{KEY}`，使用大写字母，层级用下划线分隔：

```
AINOS_server_port     -> server.port
AINOS_logging_level   -> logging.level
AINOS_inference_engine -> inference.engine
AINOS_auth_jwt_secret -> auth.jwt_secret
```

## 配置示例场景

### 场景 1: 最小配置（本地开发）

```yaml
server:
  host: "127.0.0.1"
  port: 9500

logging:
  level: "debug"
  format: "text"

inference:
  engine: "cpu"
  num_threads: 4
  context_size: 2048

auth:
  enabled: false
```

### 场景 2: 生产环境（单 GPU）

```yaml
server:
  host: "0.0.0.0"
  port: 9500
  workers: 8
  max_connections: 1024

logging:
  level: "info"
  format: "json"
  output: "file"
  file: "/var/log/ainos/ainos.log"
  max_size: 100
  max_files: 10

inference:
  engine: "cuda"
  gpu_devices: [0]
  gpu_layers: 32
  num_threads: 8
  batch_size: 64
  context_size: 8192
  flash_attention: true

models:
  model_dir: "/models"
  default_quantization: "Q4_K_M"
  max_loaded_models: 3

auth:
  enabled: true
  method: "jwt"
  jwt_expiry: 86400
  rate_limit_enabled: true
  rate_limit: 100

monitoring:
  metrics_enabled: true
  metrics_port: 9090
```

### 场景 3: 多 GPU 集群部署

```yaml
server:
  host: "0.0.0.0"
  port: 9500
  workers: 16

inference:
  engine: "cuda"
  gpu_devices: [0, 1, 2, 3]
  gpu_layers: -1
  tensor_parallel: 4
  flash_attention: true
  use_mmap: true

models:
  model_dir: "/shared/models"
  default_quantization: "Q4_K_M"

memory:
  kv_cache_size: 1024
  use_hugepage: true

auth:
  enabled: true
  method: "jwt"
  jwt_secret: "production-secret-key-change-me"
  rate_limit: 500

cluster:
  enabled: true
  node_name: "gpu-node-1"
  node_role: "worker"
  discovery: "static"
  peers:
    - "192.168.1.10:9500"
    - "192.168.1.11:9500"
    - "192.168.1.12:9500"

monitoring:
  metrics_enabled: true
  metrics_port: 9090
  tracing_enabled: true
  tracing_endpoint: "http://jaeger:14268/api/traces"
```

### 场景 4: 低内存部署（树莓派 / 低端设备）

```yaml
server:
  host: "127.0.0.1"
  port: 9500
  workers: 2

logging:
  level: "warn"

inference:
  engine: "cpu"
  num_threads: 2
  context_size: 1024
  batch_size: 8
  use_mmap: true
  low_memory: true
  flash_attention: false

models:
  model_dir: "/models"
  default_quantization: "Q2_K"
  max_loaded_models: 1

memory:
  kv_cache_size: 128
  kv_cache_type: "q4_0"

auth:
  enabled: false
```

### 场景 5: macOS 开发环境

```yaml
server:
  host: "127.0.0.1"
  port: 9500

logging:
  level: "debug"
  format: "text"
  output: "stdout"

inference:
  engine: "metal"
  num_threads: 4
  context_size: 4096
  flash_attention: true

models:
  model_dir: "/Users/username/models"
  default_quantization: "Q4_K_M"

auth:
  enabled: false
```

## 配置验证

### 验证配置文件

```bash
# 检查配置文件语法
ainosd --config /etc/ainos/config.yaml --check

# 或使用 yamllint
yamllint /etc/ainos/config.yaml
```

### 查看当前配置

```bash
# 查看当前运行配置
ainosctl config show

# 查看特定配置项
ainosctl config get inference.engine
ainosctl config get server.port

# 导出配置到文件
ainosctl config dump > /tmp/config_backup.yaml
```

### 动态修改配置

```bash
# 运行时修改配置（部分配置支持热加载）
ainosctl config set inference.num_threads 8
ainosctl config set logging.level debug

# 重载配置文件
ainosctl config reload
```

## 配置最佳实践

1. **安全相关**:
   - 生产环境始终启用认证
   - JWT 密钥使用强随机字符串
   - 启用 TLS 加密网络通信
   - 设置合理的速率限制

2. **性能相关**:
   - workers 数设为 CPU 核心数
   - 根据可用内存选择合适的量化类型
   - 启用 Flash Attention 加速推理
   - 使用 mmap 加载大模型

3. **监控相关**:
   - 启用指标收集用于监控
   - 设置合理的日志级别
   - 配置日志轮转避免磁盘占满

4. **部署相关**:
   - 使用配置文件管理不同环境配置
   - 敏感信息通过环境变量传入
   - 配置文件纳入版本控制
   - 使用配置验证 CI 检查