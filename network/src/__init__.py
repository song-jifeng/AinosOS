"""
AI 优化网络栈 (AI-Optimized Network Stack)
===========================================

基于人工智能优化的高性能网络协议栈，支持 TCP/UDP/IP 协议、
HTTP/WebSocket 应用层协议、网络监控与分析、以及 AI 驱动的
流量预测、拥塞控制、智能路由和异常检测。

典型用法:
    >>> from src.stack import NetworkStack
    >>> stack = NetworkStack()
    >>> await stack.initialize()
    >>> await stack.start()
"""

from src.stack import NetworkStack
from src.version import __version__, __author__

__version__ = "2.1.0"
__author__ = "Ainos Network Team"
__all__ = ["NetworkStack"]