# AI 优化网络栈 (Ainos Network Stack)

基于人工智能优化的高性能网络协议栈，支持 TCP/UDP/IP 协议、HTTP/WebSocket 应用层协议、网络监控与分析、以及 AI 驱动的流量预测、拥塞控制、智能路由和异常检测。

## 特性

### 协议实现
- **TCP**: 完整的 TCP 协议实现，包括连接管理、拥塞控制（CUBIC/BBR/Vegas/RL）、重传机制和状态机
- **UDP**: 数据报收发、多播支持、广播功能
- **IP**: IPv4 数据包封装、分片重组、路由表管理
- **DNS**: 完整的 DNS 解析器，支持 A/AAAA/CNAME/MX/NS/TXT/PTR 记录查询和缓存
- **HTTP**: HTTP/1.1 客户端/服务器，支持连接池、重定向、中间件路由
- **WebSocket**: RFC 6455 兼容的客户端/服务器，支持文本/二进制消息、分片、Ping/Pong

### AI 优化
- **流量预测**: 支持 LSTM、GRU、ARIMA、Holt-Winters、移动平均、集成模型等多种预测算法
- **拥塞控制**: 自适应拥塞控制，支持 CUBIC、BBR、Vegas、强化学习等算法
- **智能路由**: 基于 Dijkstra、强化学习和负载均衡的智能路径选择
- **异常检测**: 支持 Isolation Forest、One-Class SVM、LSTM 自编码器和统计方法

### 监控分析
- **网络抓包**: 实时数据包捕获、pcap 文件读写、BPF 过滤器
- **流量分析**: 协议分布、Top Talkers、Top Flows、带宽使用分析
- **异常检测**: 基于规则和统计的实时异常检测（流量突增、端口扫描、SYN Flood 等）
- **仪表盘**: 实时网络仪表盘，支持多种可视化组件

### 网络工具
- **Ping**: ICMP Echo 延迟测试，带统计输出
- **Traceroute**: 路由追踪，支持多跳探测
- **Iperf**: 带宽测试，支持 TCP/UDP 模式
- **Nmap**: 端口扫描，支持 TCP Connect/SYN/UDP 扫描
- **Proxy**: HTTP 代理和 SOCKS5 代理服务器

## 安装

```bash
# 基础安装
pip install ainos-network

# 安装 AI 依赖
pip install ainos-network[ai]

# 安装监控依赖
pip install ainos-network[monitor]

# 安装开发依赖
pip install ainos-network[dev]

# 从源码安装
git clone https://github.com/ainos/network.git
cd network
pip install -e .
```

## 快速开始

### 使用网络栈

```python
import asyncio
from src.stack import NetworkStack

async def main():
    # 创建网络栈
    stack = NetworkStack()
    
    # 初始化
    await stack.initialize()
    
    # 启动
    await stack.start()
    
    # 执行 Ping
    result = await stack.ping("8.8.8.8")
    print(f"Ping 结果: {result}")
    
    # DNS 解析
    ips = await stack.resolve_dns("example.com", "A")
    print(f"DNS 解析: {ips}")
    
    # 端口扫描
    scan_result = await stack.port_scan("192.168.1.1", "1-100")
    print(f"开放端口: {scan_result.open_count}")
    
    # 获取状态
    status = stack.get_status()
    print(f"网络栈状态: {status}")
    
    # 停止
    await stack.stop()

asyncio.run(main())
```

### 启动 HTTP 服务器

```python
import asyncio
from src.protocol.http import HTTPServer, HTTPResponse

async def main():
    server = HTTPServer(host="0.0.0.0", port=8080)
    
    @server.get("/")
    async def index(request):
        return HTTPResponse(body=b"Hello, World!")
    
    await server.start()
    await asyncio.Event().wait()

asyncio.run(main())
```

### WebSocket 聊天服务器

```python
import asyncio
from src.protocol.websocket import WebSocketServer

async def main():
    server = WebSocketServer(host="0.0.0.0", port=8765)
    
    @server.on_message
    async def on_message(ws, conn_id, message):
        await server.broadcast(f"User {conn_id}: {message}")
    
    await server.start()
    await asyncio.Event().wait()

asyncio.run(main())
```

### 流量监控

```python
import asyncio
from src.monitor.analyzer import TrafficAnalyzer

async def main():
    analyzer = TrafficAnalyzer()
    
    # 模拟流量分析
    analyzer.analyze_packet(
        src_ip="192.168.1.1",
        dst_ip="10.0.0.1",
        protocol="TCP",
        length=100,
    )
    
    # 获取统计
    stats = analyzer.get_statistics()
    print(f"总数据包: {stats['total_packets']}")
    print(f"协议分布: {stats['protocol_distribution']}")

asyncio.run(main())
```

## 目录结构

```
network/
├── src/
│   ├── __init__.py          # 包入口
│   ├── stack.py              # 网络栈主类
│   ├── protocol/             # 协议实现
│   │   ├── tcp.py            # TCP 协议
│   │   ├── udp.py            # UDP 协议
│   │   ├── ip.py             # IP 协议
│   │   ├── dns.py            # DNS 解析器
│   │   ├── http.py           # HTTP/1.1 + HTTP/2
│   │   └── websocket.py      # WebSocket
│   ├── monitor/              # 监控模块
│   │   ├── capture.py        # 网络抓包
│   │   ├── analyzer.py       # 流量分析
│   │   ├── anomally.py       # 异常检测
│   │   └── dashboard.py      # 网络仪表盘
│   ├── ai/                   # AI 模块
│   │   ├── traffic_pred.py   # 流量预测
│   │   ├── congestion.py     # 拥塞控制优化
│   │   ├── routing.py        # 智能路由
│   │   └── anomaly_detector.py # AI 异常检测
│   ├── tools/                # 网络工具
│   │   ├── ping.py           # ICMP Ping
│   │   ├── traceroute.py     # 路由追踪
│   │   ├── iperf.py          # 带宽测试
│   │   ├── nmap.py           # 端口扫描
│   │   └── proxy.py          # 代理服务器
│   └── utils/                # 工具函数
│       ├── packet.py         # 数据包构造
│       ├── checksum.py       # 校验和计算
│       └── config.py         # 配置管理
├── tests/                    # 单元测试
├── examples/                 # 示例代码
├── setup.py                  # 安装脚本
├── pyproject.toml            # 项目配置
└── README.md                 # 本文件
```

## 配置

支持 YAML 和 JSON 格式的配置文件：

```yaml
# config.yaml
network:
  host: "0.0.0.0"
  port: 0
  mtu: 1500
  dns_servers:
    - "8.8.8.8"
    - "114.114.114.114"

ai:
  traffic_pred_enabled: true
  traffic_pred_model: "lstm"
  congestion_control_enabled: true
  routing_enabled: true
  anomaly_detection_enabled: true

monitor:
  capture_enabled: true
  dashboard_enabled: true
  dashboard_port: 9090
```

```python
from src.utils.config import ConfigManager

config = ConfigManager()
config.load_from_file("config.yaml")
network_config = config.network
```

## 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_tcp.py -v

# 带覆盖率报告
pytest --cov=src --cov-report=html
```

## 运行示例

```bash
# HTTP 服务器
python examples/http_server.py

# WebSocket 聊天服务器
python examples/chat_server.py

# 流量监控
python examples/traffic_monitor.py
```

## 系统要求

- Python 3.9+
- 操作系统: Linux, macOS, Windows
- 依赖: numpy, pyyaml

## 许可证

MIT License

## 贡献

欢迎提交 Pull Request 或创建 Issue。

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request