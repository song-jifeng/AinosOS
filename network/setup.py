"""
AI 优化网络栈
=============

基于人工智能优化的高性能网络协议栈，支持 TCP/UDP/IP 协议、
HTTP/WebSocket 应用层协议、网络监控与分析、以及 AI 驱动的
流量预测、拥塞控制、智能路由和异常检测。

功能:
- TCP 协议：连接管理、拥塞控制、重传机制
- UDP 协议：数据报收发、多播支持
- HTTP 客户端/服务器：HTTP/1.1 + HTTP/2
- WebSocket 客户端/服务器
- DNS 解析器
- 网络抓包和分析 (pcap)
- AI 流量预测 (LSTM/ARIMA/Holt-Winters)
- AI 拥塞控制优化 (CUBIC/BBR/Vegas/RL)
- AI 智能路由 (Dijkstra/强化学习/负载均衡)
- AI 异常检测 (Isolation Forest/统计)
- 网络工具：Ping, Traceroute, Iperf, Nmap, 代理
- 网络仪表盘
"""

from setuptools import setup, find_packages


with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()


setup(
    name="ainos-network",
    version="2.1.0",
    author="Ainos Network Team",
    author_email="dev@ainos.network",
    description="AI-Optimized Network Stack",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ainos/network",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.9",
    install_requires=[
        "numpy>=1.21.0",
        "pyyaml>=6.0",
        "pycryptodome>=3.10",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21",
            "pytest-cov>=4.0",
            "flake8>=6.0",
            "mypy>=1.0",
            "black>=23.0",
        ],
        "ai": [
            "tensorflow>=2.10",
            "scikit-learn>=1.2",
            "statsmodels>=0.13",
        ],
        "monitor": [
            "scapy>=2.5",
            "psutil>=5.9",
            "matplotlib>=3.5",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: System :: Networking",
        "Topic :: System :: Networking :: Monitoring",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    entry_points={
        "console_scripts": [
            "ainos-net=src.cli:main",
        ],
    },
    project_urls={
        "Documentation": "https://docs.ainos.network",
        "Source": "https://github.com/ainos/network",
        "Tracker": "https://github.com/ainos/network/issues",
    },
)