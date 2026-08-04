"""
AI 智能路由模块
==============

基于强化学习和多目标优化的智能路由算法，支持动态路由选择、
负载均衡和故障自愈。
"""

import time
import math
import random
import heapq
import logging
import ipaddress
from typing import Optional, Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict


logger = logging.getLogger(__name__)


class RouteMetric(Enum):
    """路由度量"""
    HOP_COUNT = "hop_count"
    LATENCY = "latency"
    BANDWIDTH = "bandwidth"
    LOSS_RATE = "loss_rate"
    JITTER = "jitter"
    LOAD = "load"
    RELIABILITY = "reliability"
    COST = "cost"
    ENERGY = "energy"
    COMPOSITE = "composite"


@dataclass
class RouteEntry:
    """路由条目"""
    destination: str
    gateway: str
    interface: str = ""
    metric: int = 0
    metric_type: RouteMetric = RouteMetric.HOP_COUNT
    prefixlen: int = 32
    protocol: str = "static"
    age: float = 0.0
    weight: float = 1.0
    learned_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    use_count: int = 0
    is_active: bool = True
    is_backup: bool = False
    rtt: float = 0.0
    bandwidth: float = 0.0
    loss_rate: float = 0.0
    load: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def cost(self) -> float:
        """计算综合成本"""
        return self.metric / max(self.weight, 0.1)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.learned_at

    def touch(self) -> None:
        """更新使用时间"""
        self.last_used = time.time()
        self.use_count += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "destination": f"{self.destination}/{self.prefixlen}",
            "gateway": self.gateway,
            "interface": self.interface,
            "metric": self.metric,
            "metric_type": self.metric_type.value,
            "protocol": self.protocol,
            "age": self.age_seconds,
            "use_count": self.use_count,
            "is_active": self.is_active,
            "is_backup": self.is_backup,
            "rtt": self.rtt,
            "bandwidth": self.bandwidth,
            "loss_rate": self.loss_rate,
            "load": self.load,
        }


@dataclass
class RoutingTable:
    """路由表"""
    entries: List[RouteEntry] = field(default_factory=list)
    max_entries: int = 10000
    version: int = 0

    def add_entry(self, entry: RouteEntry) -> bool:
        """添加路由条目"""
        if len(self.entries) >= self.max_entries:
            return False
        self.entries.append(entry)
        self.version += 1
        return True

    def remove_entry(self, destination: str, prefixlen: int = 32,
                     gateway: Optional[str] = None) -> bool:
        """删除路由条目"""
        for i, entry in enumerate(self.entries):
            if entry.destination == destination and entry.prefixlen == prefixlen:
                if gateway is None or entry.gateway == gateway:
                    del self.entries[i]
                    self.version += 1
                    return True
        return False

    def find_best(self, destination: str) -> Optional[RouteEntry]:
        """查找最佳路由"""
        # 精确匹配优先，然后最长前缀匹配
        dst_ip = ipaddress.IPv4Address(destination) if ":" not in destination else None
        best = None
        best_prefix = -1
        best_cost = float("inf")

        for entry in self.entries:
            if not entry.is_active:
                continue

            try:
                network = ipaddress.IPv4Network(f"{entry.destination}/{entry.prefixlen}", strict=False)
                if dst_ip in network:
                    if entry.prefixlen > best_prefix or (entry.prefixlen == best_prefix and entry.cost < best_cost):
                        best = entry
                        best_prefix = entry.prefixlen
                        best_cost = entry.cost
            except ValueError:
                if entry.destination == destination:
                    if entry.cost < best_cost:
                        best = entry
                        best_cost = entry.cost

        return best

    def find_all(self, destination: str) -> List[RouteEntry]:
        """查找所有匹配的路由"""
        dst_ip = ipaddress.IPv4Address(destination) if ":" not in destination else None
        matches = []

        for entry in self.entries:
            if not entry.is_active:
                continue
            try:
                network = ipaddress.IPv4Network(f"{entry.destination}/{entry.prefixlen}", strict=False)
                if dst_ip in network:
                    matches.append(entry)
            except ValueError:
                if entry.destination == destination:
                    matches.append(entry)

        matches.sort(key=lambda e: (-e.prefixlen, e.cost))
        return matches

    def get_default(self) -> Optional[RouteEntry]:
        """获取默认路由"""
        for entry in self.entries:
            if entry.destination == "0.0.0.0" and entry.prefixlen == 0:
                return entry
        return None

    def get_active_entries(self) -> List[RouteEntry]:
        return [e for e in self.entries if e.is_active]

    def get_backup_entries(self) -> List[RouteEntry]:
        return [e for e in self.entries if e.is_backup]

    def clear(self) -> None:
        self.entries.clear()
        self.version += 1

    def __len__(self) -> int:
        return len(self.entries)


class SmartRouter:
    """AI 智能路由器"""

    def __init__(self, algorithm: str = "reinforcement",
                 update_interval: float = 30.0,
                 max_paths: int = 5) -> None:
        self.algorithm = algorithm
        self.update_interval = update_interval
        self.max_paths = max_paths
        self._routing_table = RoutingTable()
        self._topology: Dict[str, Set[str]] = defaultdict(set)
        self._link_metrics: Dict[Tuple[str, str], Dict[str, float]] = {}
        self._path_history: Dict[Tuple[str, str], List[float]] = defaultdict(list)
        self._q_table: Dict[str, float] = {}
        self._exploration_rate: float = 0.1
        self._learning_rate: float = 0.01
        self._discount_factor: float = 0.9
        self._last_update: float = 0.0
        self._is_running: bool = False
        self._stats: Dict[str, Any] = {
            "route_decisions": 0,
            "reroutes": 0,
            "failover_events": 0,
            "avg_path_cost": 0.0,
            "best_path_cost": float("inf"),
            "worst_path_cost": 0.0,
            "convergence_time": 0.0,
        }

    @property
    def routing_table(self) -> RoutingTable:
        return self._routing_table

    @property
    def route_count(self) -> int:
        return len(self._routing_table)

    async def start(self) -> None:
        """启动智能路由器"""
        self._is_running = True
        logger.info(f"智能路由器已启动 (algorithm={self.algorithm})")

    async def stop(self) -> None:
        """停止智能路由器"""
        self._is_running = False
        logger.info("智能路由器已停止")

    def add_route(self, destination: str, gateway: str, prefixlen: int = 32,
                  interface: str = "", metric: int = 0,
                  metric_type: RouteMetric = RouteMetric.HOP_COUNT,
                  protocol: str = "static") -> bool:
        """添加路由

        Args:
            destination: 目标网络/主机
            gateway: 下一跳网关
            prefixlen: 前缀长度
            interface: 接口名称
            metric: 度量值
            metric_type: 度量类型
            protocol: 路由协议

        Returns:
            是否成功添加
        """
        entry = RouteEntry(
            destination=destination,
            gateway=gateway,
            interface=interface,
            metric=metric,
            metric_type=metric_type,
            prefixlen=prefixlen,
            protocol=protocol,
        )
        result = self._routing_table.add_entry(entry)

        # 更新拓扑
        self._topology[destination].add(gateway)

        if result:
            logger.info(f"添加路由: {destination}/{prefixlen} -> {gateway} ({protocol})")
        return result

    def remove_route(self, destination: str, prefixlen: int = 32,
                     gateway: Optional[str] = None) -> bool:
        """删除路由"""
        return self._routing_table.remove_entry(destination, prefixlen, gateway)

    def find_route(self, destination: str) -> Optional[RouteEntry]:
        """查找最佳路由"""
        self._stats["route_decisions"] += 1
        entry = self._routing_table.find_best(destination)
        if entry:
            entry.touch()
        return entry

    def find_all_paths(self, destination: str) -> List[RouteEntry]:
        """查找所有路径"""
        return self._routing_table.find_all(destination)

    def get_optimal_path(self, source: str, destination: str) -> List[RouteEntry]:
        """获取最优路径

        Args:
            source: 源节点
            destination: 目标节点

        Returns:
            路径上的路由条目列表
        """
        if self.algorithm == "dijkstra":
            return self._dijkstra_path(source, destination)
        elif self.algorithm == "reinforcement":
            return self._reinforcement_path(source, destination)
        elif self.algorithm == "load_balancing":
            return self._load_balanced_path(source, destination)
        else:
            return self._dijkstra_path(source, destination)

    def _dijkstra_path(self, source: str, destination: str) -> List[RouteEntry]:
        """Dijkstra 最短路径算法"""
        # 构建图
        graph: Dict[str, Dict[str, float]] = defaultdict(dict)
        for entry in self._routing_table.entries:
            if entry.is_active:
                graph[entry.destination][entry.gateway] = entry.cost
                graph[entry.gateway][entry.destination] = entry.cost

        if source not in graph or destination not in graph:
            logger.warning(f"路径不存在: {source} -> {destination}")
            return []

        # Dijkstra
        distances = {node: float("inf") for node in graph}
        previous = {node: None for node in graph}
        distances[source] = 0
        pq = [(0, source)]

        while pq:
            current_dist, current = heapq.heappop(pq)
            if current_dist > distances[current]:
                continue
            if current == destination:
                break
            for neighbor, weight in graph[current].items():
                distance = current_dist + weight
                if distance < distances[neighbor]:
                    distances[neighbor] = distance
                    previous[neighbor] = current
                    heapq.heappush(pq, (distance, neighbor))

        # 重建路径
        path = []
        current = destination
        while current is not None:
            entry = self._routing_table.find_best(current)
            if entry:
                path.append(entry)
            current = previous.get(current)
        path.reverse()

        return path

    def _reinforcement_path(self, source: str, destination: str) -> List[RouteEntry]:
        """基于强化学习的路径选择"""
        paths = self.find_all_paths(destination)
        if not paths:
            return []

        # epsilon-greedy 选择
        if random.random() < self._exploration_rate:
            selected = random.choice(paths)
        else:
            # 选择 Q 值最高的路径
            best_path = None
            best_q = float("-inf")
            for path in paths[:self.max_paths]:
                state = f"{source}:{destination}:{path.gateway}"
                q_value = self._q_table.get(state, 0.0)
                if q_value > best_q:
                    best_q = q_value
                    best_path = path
            selected = best_path or paths[0]

        # 衰减探索率
        self._exploration_rate = max(0.01, self._exploration_rate * 0.999)

        return [selected] if selected else []

    def _load_balanced_path(self, source: str, destination: str) -> List[RouteEntry]:
        """负载均衡路径选择"""
        paths = self.find_all_paths(destination)[:self.max_paths]
        if not paths:
            return []

        # 选择负载最低的路径
        selected = min(paths, key=lambda p: p.load)
        return [selected]

    def update_link_metrics(self, src: str, dst: str, metrics: Dict[str, float]) -> None:
        """更新链路指标

        Args:
            src: 源节点
            dst: 目标节点
            metrics: 指标字典 (rtt, bandwidth, loss_rate, jitter, load)
        """
        self._link_metrics[(src, dst)] = metrics
        self._link_metrics[(dst, src)] = metrics

        # 更新路径历史
        key = (src, dst)
        path_cost = metrics.get("rtt", 0) + metrics.get("loss_rate", 0) * 1000
        self._path_history[key].append(path_cost)
        if len(self._path_history[key]) > 100:
            self._path_history[key].pop(0)

        # 更新相关路由的成本
        self._update_route_costs(src, dst, metrics)

    def _update_route_costs(self, src: str, dst: str, metrics: Dict[str, float]) -> None:
        """根据链路指标更新路由成本"""
        for entry in self._routing_table.entries:
            if entry.gateway == dst or entry.destination == dst:
                # 计算综合指标
                rtt = metrics.get("rtt", 0)
                loss = metrics.get("loss_rate", 0)
                bw = metrics.get("bandwidth", 1e9)
                load = metrics.get("load", 0)

                cost = rtt + loss * 100 + (1 - bw / 1e9) * 10 + load * 5
                entry.metric = int(cost)
                entry.rtt = rtt
                entry.bandwidth = bw
                entry.loss_rate = loss
                entry.load = load

    def detect_failure(self, destination: str) -> bool:
        """检测路由故障

        Args:
            destination: 目标地址

        Returns:
            是否检测到故障
        """
        entry = self._routing_table.find_best(destination)
        if not entry:
            return True

        # 检查指标是否异常
        if entry.loss_rate > 0.5 or entry.rtt > 10.0:
            return True
        if entry.age_seconds > 3600 and entry.use_count == 0:
            return True

        return False

    def handle_failure(self, destination: str) -> Optional[RouteEntry]:
        """处理路由故障，切换到备份路由

        Args:
            destination: 目标地址

        Returns:
            切换后的路由条目
        """
        self._stats["failover_events"] += 1

        # 标记故障路由
        failed = self._routing_table.find_best(destination)
        if failed:
            failed.is_active = False

        # 查找备份路由
        all_routes = self._routing_table.find_all(destination)
        backup = None
        for route in all_routes:
            if route.is_active and not route.is_backup:
                backup = route
                break

        if not backup:
            for route in all_routes:
                if route.is_backup and route.is_active:
                    backup = route
                    break

        if backup:
            backup.touch()
            logger.info(f"路由故障切换: {destination} -> {backup.gateway}")
            self._stats["reroutes"] += 1
            return backup

        logger.warning(f"无可用备份路由: {destination}")
        return None

    def balance_load(self) -> int:
        """负载均衡，重路由部分流量

        Returns:
            重路由的流数量
        """
        rerouted = 0
        entries = self._routing_table.get_active_entries()

        for entry in entries:
            if entry.load > 0.8:
                # 负载过高，尝试切换到其他路径
                alt_paths = [e for e in entries
                             if e.destination == entry.destination
                             and e.gateway != entry.gateway
                             and e.load < 0.6]
                if alt_paths:
                    best_alt = min(alt_paths, key=lambda e: e.load)
                    entry.is_active = False
                    best_alt.is_active = True
                    best_alt.touch()
                    rerouted += 1
                    logger.debug(f"负载均衡: {entry.gateway} -> {best_alt.gateway}")

        if rerouted > 0:
            self._stats["reroutes"] += rerouted

        return rerouted

    def get_topology(self) -> Dict[str, List[str]]:
        """获取网络拓扑"""
        return {k: list(v) for k, v in self._topology.items()}

    def get_path_history(self, src: str, dst: str) -> List[float]:
        """获取路径历史"""
        return self._path_history.get((src, dst), [])

    def get_convergence_time(self) -> float:
        """获取路由收敛时间"""
        return self._stats["convergence_time"]

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "algorithm": self.algorithm,
            "update_interval": self.update_interval,
            "max_paths": self.max_paths,
            "route_count": self.route_count,
            "active_routes": len(self._routing_table.get_active_entries()),
            "backup_routes": len(self._routing_table.get_backup_entries()),
            "topology_size": sum(len(v) for v in self._topology.values()),
            "q_table_size": len(self._q_table),
            "exploration_rate": self._exploration_rate,
            "is_running": self._is_running,
        }

    def reset(self) -> None:
        """重置路由器"""
        self._routing_table.clear()
        self._topology.clear()
        self._link_metrics.clear()
        self._path_history.clear()
        self._q_table.clear()
        self._exploration_rate = 0.1
        self._last_update = 0.0
        self._stats = {
            "route_decisions": 0,
            "reroutes": 0,
            "failover_events": 0,
            "avg_path_cost": 0.0,
            "best_path_cost": float("inf"),
            "worst_path_cost": 0.0,
            "convergence_time": 0.0,
        }
        logger.info("智能路由器已重置")