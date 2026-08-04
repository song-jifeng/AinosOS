"""
网络仪表盘模块
==============

提供网络监控的实时仪表盘功能，包括数据可视化、指标展示和
实时更新机制。
"""

import asyncio
import time
import json
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque
from enum import Enum


logger = logging.getLogger(__name__)


class WidgetType(Enum):
    """仪表盘组件类型"""
    CHART = "chart"
    GAUGE = "gauge"
    TABLE = "table"
    STAT = "stat"
    ALERT_LIST = "alert_list"
    TRAFFIC_MAP = "traffic_map"
    PROTOCOL_PIE = "protocol_pie"
    TIMELINE = "timeline"


@dataclass
class DashboardWidget:
    """仪表盘组件"""
    name: str = ""
    widget_type: WidgetType = WidgetType.STAT
    title: str = ""
    data: Any = None
    config: Dict[str, Any] = field(default_factory=dict)
    refresh_interval: float = 2.0
    last_update: float = 0.0

    def needs_update(self) -> bool:
        """检查是否需要更新"""
        return time.time() - self.last_update >= self.refresh_interval

    def update(self, data: Any) -> None:
        """更新组件数据"""
        self.data = data
        self.last_update = time.time()


@dataclass
class DashboardMetrics:
    """仪表盘指标"""
    timestamp: float = field(default_factory=time.time)
    packet_rate: float = 0.0
    byte_rate: float = 0.0
    throughput: float = 0.0
    active_connections: int = 0
    total_connections: int = 0
    active_flows: int = 0
    packet_loss: float = 0.0
    avg_latency: float = 0.0
    bandwidth_usage: float = 0.0
    error_rate: float = 0.0
    top_protocols: Dict[str, float] = field(default_factory=dict)
    top_talkers: List[Tuple[str, int]] = field(default_factory=list)
    recent_alerts: int = 0
    uptime: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "packet_rate": self.packet_rate,
            "byte_rate": self.byte_rate,
            "throughput": self.throughput,
            "active_connections": self.active_connections,
            "total_connections": self.total_connections,
            "active_flows": self.active_flows,
            "packet_loss": self.packet_loss,
            "avg_latency": self.avg_latency,
            "bandwidth_usage": self.bandwidth_usage,
            "error_rate": self.error_rate,
            "top_protocols": self.top_protocols,
            "top_talkers": self.top_talkers,
            "recent_alerts": self.recent_alerts,
            "uptime": self.uptime,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
        }


class NetworkDashboard:
    """网络仪表盘"""

    def __init__(self, host: str = "127.0.0.1", port: int = 9090,
                 refresh_interval: float = 2.0,
                 max_data_points: int = 1000) -> None:
        self.host = host
        self.port = port
        self.refresh_interval = refresh_interval
        self.max_data_points = max_data_points
        self._widgets: Dict[str, DashboardWidget] = {}
        self._metrics_history: List[DashboardMetrics] = []
        self._current_metrics = DashboardMetrics()
        self._data_sources: Dict[str, Callable] = {}
        self._update_callbacks: List[Callable] = []
        self._is_running: bool = False
        self._server: Optional[asyncio.AbstractServer] = None
        self._start_time: float = time.time()
        self._stats: Dict[str, int] = {
            "updates": 0,
            "widget_renders": 0,
            "api_requests": 0,
        }

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    @property
    def metrics(self) -> DashboardMetrics:
        return self._current_metrics

    def add_widget(self, name: str, widget_type: WidgetType,
                   title: str = "", config: Optional[Dict[str, Any]] = None) -> DashboardWidget:
        """添加仪表盘组件

        Args:
            name: 组件名称
            widget_type: 组件类型
            title: 显示标题
            config: 配置参数

        Returns:
            创建的组件
        """
        widget = DashboardWidget(
            name=name,
            widget_type=widget_type,
            title=title or name,
            config=config or {},
        )
        self._widgets[name] = widget
        logger.info(f"仪表盘组件已添加: {name} ({widget_type.value})")
        return widget

    def remove_widget(self, name: str) -> bool:
        """移除组件"""
        if name in self._widgets:
            del self._widgets[name]
            return True
        return False

    def get_widget(self, name: str) -> Optional[DashboardWidget]:
        return self._widgets.get(name)

    def register_data_source(self, name: str, source_func: Callable) -> None:
        """注册数据源"""
        self._data_sources[name] = source_func

    def on_update(self, callback: Callable) -> None:
        """注册更新回调"""
        self._update_callbacks.append(callback)

    def update_metrics(self, metrics: DashboardMetrics) -> None:
        """更新指标

        Args:
            metrics: 仪表盘指标
        """
        self._current_metrics = metrics
        self._metrics_history.append(metrics)
        if len(self._metrics_history) > self.max_data_points:
            self._metrics_history.pop(0)
        self._stats["updates"] += 1

    def update_widget(self, name: str, data: Any) -> None:
        """更新指定组件"""
        widget = self._widgets.get(name)
        if widget:
            widget.update(data)
            self._stats["widget_renders"] += 1

    async def start(self) -> None:
        """启动仪表盘"""
        self._is_running = True
        logger.info(f"网络仪表盘已启动: {self.host}:{self.port}")

    async def stop(self) -> None:
        """停止仪表盘"""
        self._is_running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("网络仪表盘已停止")

    async def update_loop(self) -> None:
        """指标更新循环"""
        while self._is_running:
            await self._collect_metrics()
            await self._update_widgets()
            await self._notify_callbacks()
            await asyncio.sleep(self.refresh_interval)

    async def _collect_metrics(self) -> None:
        """收集所有指标"""
        self._current_metrics.timestamp = time.time()
        self._current_metrics.uptime = self.uptime

        for name, source_func in self._data_sources.items():
            try:
                if asyncio.iscoroutinefunction(source_func):
                    data = await source_func()
                else:
                    data = source_func()

                if isinstance(data, dict):
                    for key, value in data.items():
                        if hasattr(self._current_metrics, key):
                            setattr(self._current_metrics, key, value)
            except Exception as e:
                logger.error(f"数据源 {name} 收集失败: {e}")

    async def _update_widgets(self) -> None:
        """更新所有组件"""
        for name, widget in self._widgets.items():
            if widget.needs_update():
                try:
                    data = await self._get_widget_data(widget)
                    widget.update(data)
                    self._stats["widget_renders"] += 1
                except Exception as e:
                    logger.error(f"组件 {name} 更新失败: {e}")

    async def _get_widget_data(self, widget: DashboardWidget) -> Any:
        """获取组件数据"""
        if widget.widget_type == WidgetType.STAT:
            return self._current_metrics.to_dict()
        elif widget.widget_type == WidgetType.CHART:
            return {
                "metrics_history": [
                    {
                        "timestamp": m.timestamp,
                        "packet_rate": m.packet_rate,
                        "byte_rate": m.byte_rate,
                        "throughput": m.throughput,
                        "active_connections": m.active_connections,
                    }
                    for m in self._metrics_history[-100:]
                ]
            }
        elif widget.widget_type == WidgetType.GAUGE:
            return {
                "bandwidth_usage": self._current_metrics.bandwidth_usage,
                "cpu_usage": self._current_metrics.cpu_usage,
                "memory_usage": self._current_metrics.memory_usage,
                "packet_loss": self._current_metrics.packet_loss,
            }
        elif widget.widget_type == WidgetType.TABLE:
            return {
                "top_talkers": self._current_metrics.top_talkers[:10],
                "top_protocols": self._current_metrics.top_protocols,
            }
        elif widget.widget_type == WidgetType.ALERT_LIST:
            return {
                "recent_alerts": self._current_metrics.recent_alerts,
                "total_alerts": 0,
            }
        return self._current_metrics.to_dict()

    async def _notify_callbacks(self) -> None:
        """通知所有回调"""
        for callback in self._update_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self._current_metrics)
                else:
                    callback(self._current_metrics)
            except Exception as e:
                logger.error(f"更新回调执行出错: {e}")

    def get_metrics_history(self, n: int = 60) -> List[DashboardMetrics]:
        """获取历史指标"""
        return self._metrics_history[-n:]

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """获取指标快照"""
        return self._current_metrics.to_dict()

    def get_widgets_status(self) -> Dict[str, Any]:
        """获取组件状态"""
        return {
            name: {
                "type": widget.widget_type.value,
                "title": widget.title,
                "last_update": widget.last_update,
                "has_data": widget.data is not None,
            }
            for name, widget in self._widgets.items()
        }

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "uptime": self.uptime,
            "widget_count": len(self._widgets),
            "data_sources": len(self._data_sources),
            "metrics_history_size": len(self._metrics_history),
            "is_running": self._is_running,
            "current_metrics": self._current_metrics.to_dict(),
        }