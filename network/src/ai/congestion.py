"""
AI 拥塞控制优化模块
==================

基于强化学习和自适应算法的拥塞控制优化，动态调整拥塞窗口、
发送速率和退避策略以最大化网络吞吐量。
"""

import time
import math
import random
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto


logger = logging.getLogger(__name__)


class CCAlgorithm(Enum):
    """拥塞控制算法"""
    CUBIC = "cubic"
    BBR = "bbr"
    VEGAS = "vegas"
    ADAPTIVE = "adaptive"
    REINFORCEMENT = "reinforcement"
    HYBRID = "hybrid"


class CCZone(Enum):
    """拥塞控制区域"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SEVERE = "severe"


@dataclass
class NetworkMetrics:
    """网络指标"""
    rtt: float = 0.0
    rtt_min: float = float("inf")
    rtt_max: float = 0.0
    bandwidth: float = 0.0
    throughput: float = 0.0
    loss_rate: float = 0.0
    jitter: float = 0.0
    packet_rate: float = 0.0
    retransmit_rate: float = 0.0
    window_size: int = 0
    congestion_window: int = 0
    ssthresh: int = 65535
    in_flight: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def zone(self) -> CCZone:
        """根据指标判断拥塞区域"""
        if self.loss_rate > 0.1 or self.rtt > self.rtt_min * 5:
            return CCZone.SEVERE
        elif self.loss_rate > 0.05 or self.rtt > self.rtt_min * 3:
            return CCZone.HIGH
        elif self.loss_rate > 0.01 or self.rtt > self.rtt_min * 2:
            return CCZone.MEDIUM
        return CCZone.LOW

    @property
    def goodput(self) -> float:
        """有效吞吐量 (排除重传)"""
        return self.throughput * (1 - self.retransmit_rate)


@dataclass
class CCAction:
    """拥塞控制动作"""
    cwnd_change: int = 0
    rate_change: float = 0.0
    ssthresh_change: int = 0
    backoff: bool = False
    fast_retransmit: bool = False
    slow_start: bool = False
    pacing_rate: float = 0.0
    description: str = ""

    def __str__(self) -> str:
        parts = []
        if self.cwnd_change != 0:
            parts.append(f"cwnd={'+' if self.cwnd_change > 0 else ''}{self.cwnd_change}")
        if self.backoff:
            parts.append("backoff")
        if self.fast_retransmit:
            parts.append("fast_retransmit")
        if self.slow_start:
            parts.append("slow_start")
        if self.pacing_rate > 0:
            parts.append(f"pacing={self.pacing_rate:.1f}")
        return f"CCAction({', '.join(parts)})"


class CongestionOptimizer:
    """AI 拥塞控制优化器"""

    def __init__(self, algorithm: CCAlgorithm = CCAlgorithm.ADAPTIVE,
                 update_interval: float = 0.1,
                 sensitivity: float = 0.5) -> None:
        self.algorithm = algorithm
        self.update_interval = update_interval
        self.sensitivity = sensitivity
        self._metrics_history: List[NetworkMetrics] = []
        self._max_history: int = 1000
        self._current_metrics = NetworkMetrics()
        self._actions_taken: List[CCAction] = []
        self._max_actions: int = 100
        self._last_update: float = 0.0
        self._alpha: float = 0.125
        self._beta: float = 0.25
        self._min_cwnd: int = 1
        self._max_cwnd: int = 65535 * 2
        self._min_rate: float = 1000.0
        self._max_rate: float = 1e9
        self._rtt_samples: List[float] = []
        self._throughput_samples: List[float] = []
        self._loss_samples: List[float] = []
        self._learning_rate: float = 0.01
        self._exploration_rate: float = 0.1
        self._q_table: Dict[str, float] = {}
        self._stats: Dict[str, Any] = {
            "actions_taken": 0,
            "backoffs": 0,
            "fast_retransmits": 0,
            "slow_starts": 0,
            "avg_throughput": 0.0,
            "avg_loss_rate": 0.0,
            "avg_rtt": 0.0,
        }

    @property
    def current_metrics(self) -> NetworkMetrics:
        return self._current_metrics

    def update_metrics(self, metrics: NetworkMetrics) -> None:
        """更新网络指标

        Args:
            metrics: 当前网络指标
        """
        self._current_metrics = metrics
        self._metrics_history.append(metrics)
        if len(self._metrics_history) > self._max_history:
            self._metrics_history.pop(0)

        self._rtt_samples.append(metrics.rtt)
        self._throughput_samples.append(metrics.throughput)
        self._loss_samples.append(metrics.loss_rate)

        if len(self._rtt_samples) > 100:
            self._rtt_samples.pop(0)
            self._throughput_samples.pop(0)
            self._loss_samples.pop(0)

        # 更新统计
        n = self._stats["actions_taken"] + 1
        self._stats["avg_throughput"] = (self._stats["avg_throughput"] * (n - 1) + metrics.throughput) / n
        self._stats["avg_loss_rate"] = (self._stats["avg_loss_rate"] * (n - 1) + metrics.loss_rate) / n
        self._stats["avg_rtt"] = (self._stats["avg_rtt"] * (n - 1) + metrics.rtt) / n

    def get_optimized_action(self) -> CCAction:
        """获取优化后的拥塞控制动作

        Returns:
            拥塞控制动作
        """
        now = time.time()
        if now - self._last_update < self.update_interval:
            return CCAction(description="skip")

        self._last_update = now
        metrics = self._current_metrics

        if self.algorithm == CCAlgorithm.CUBIC:
            action = self._cubic_algorithm(metrics)
        elif self.algorithm == CCAlgorithm.BBR:
            action = self._bbr_algorithm(metrics)
        elif self.algorithm == CCAlgorithm.VEGAS:
            action = self._vegas_algorithm(metrics)
        elif self.algorithm == CCAlgorithm.REINFORCEMENT:
            action = self._reinforcement_algorithm(metrics)
        elif self.algorithm == CCAlgorithm.HYBRID:
            action = self._hybrid_algorithm(metrics)
        else:
            action = self._adaptive_algorithm(metrics)

        self._actions_taken.append(action)
        if len(self._actions_taken) > self._max_actions:
            self._actions_taken.pop(0)

        self._stats["actions_taken"] += 1
        if action.backoff:
            self._stats["backoffs"] += 1
        if action.fast_retransmit:
            self._stats["fast_retransmits"] += 1
        if action.slow_start:
            self._stats["slow_starts"] += 1

        logger.debug(f"拥塞控制动作: {action}")
        return action

    def _cubic_algorithm(self, metrics: NetworkMetrics) -> CCAction:
        """CUBIC 拥塞控制算法"""
        cwnd = metrics.congestion_window or 1
        ssthresh = metrics.ssthresh

        if metrics.loss_rate > 0.02:
            # 检测到丢包，乘法减小
            new_ssthresh = max(int(cwnd * 0.7), 2)
            new_cwnd = max(int(cwnd * 0.5), 1)
            return CCAction(
                cwnd_change=new_cwnd - cwnd,
                ssthresh_change=new_ssthresh - ssthresh,
                backoff=True,
                description="CUBIC: loss detected, multiplicative decrease",
            )
        elif metrics.rtt > metrics.rtt_min * 2:
            # RTT 增加，谨慎增长
            new_cwnd = cwnd + 1
            return CCAction(
                cwnd_change=1,
                description="CUBIC: RTT increased, slow growth",
            )
        else:
            # 正常增长（CUBIC 曲线）
            k = math.pow(cwnd * (metrics.rtt / max(metrics.rtt_min, 0.001)), 1/3)
            new_cwnd = cwnd + max(1, int(cwnd * 0.1))
            return CCAction(
                cwnd_change=new_cwnd - cwnd,
                description="CUBIC: normal growth",
            )

    def _bbr_algorithm(self, metrics: NetworkMetrics) -> CCAction:
        """BBR 拥塞控制算法"""
        bw = max(metrics.bandwidth, metrics.throughput, 1000.0)
        rtt = max(metrics.rtt, 0.001)
        bdp = bw * rtt  # 带宽时延积

        cwnd = metrics.congestion_window or int(bdp)

        if metrics.loss_rate > 0.05:
            # 丢包严重，降低 pacing
            pacing = bw * 0.8
            new_cwnd = max(int(bdp * 0.8), 1)
            return CCAction(
                cwnd_change=new_cwnd - cwnd,
                pacing_rate=pacing,
                description="BBR: high loss, reduce pacing",
            )
        elif metrics.rtt > metrics.rtt_min * 1.25:
            # RTT 增加，排空缓冲区
            pacing = bw * 0.9
            return CCAction(
                pacing_rate=pacing,
                description="BBR: RTT inflated, drain buffer",
            )
        else:
            # 探测带宽
            pacing = bw * 1.25
            new_cwnd = max(cwnd + 1, int(bdp * 1.25))
            return CCAction(
                cwnd_change=new_cwnd - cwnd,
                pacing_rate=pacing,
                description="BBR: probe bandwidth",
            )

    def _vegas_algorithm(self, metrics: NetworkMetrics) -> CCAction:
        """Vegas 拥塞控制算法"""
        cwnd = metrics.congestion_window or 1
        base_rtt = metrics.rtt_min
        current_rtt = max(metrics.rtt, 0.001)

        if base_rtt == float("inf"):
            return CCAction(description="Vegas: no RTT baseline")

        expected_rate = cwnd / base_rtt
        actual_rate = cwnd / current_rtt
        diff = (expected_rate - actual_rate) * base_rtt

        if diff < 1:
            # 带宽未充分利用，增加窗口
            new_cwnd = cwnd + 1
            return CCAction(
                cwnd_change=1,
                description=f"Vegas: underutilized (diff={diff:.2f})",
            )
        elif diff > 3:
            # 拥塞，减少窗口
            new_cwnd = max(cwnd - 1, 1)
            return CCAction(
                cwnd_change=-1,
                description=f"Vegas: congestion (diff={diff:.2f})",
            )
        else:
            # 保持窗口
            return CCAction(description=f"Vegas: stable (diff={diff:.2f})")

    def _reinforcement_algorithm(self, metrics: NetworkMetrics) -> CCAction:
        """基于强化学习的拥塞控制"""
        # 状态编码
        state = self._encode_state(metrics)

        # epsilon-greedy 探索
        if random.random() < self._exploration_rate:
            action_idx = random.randint(0, 4)
        else:
            action_idx = self._best_action(state)

        # 动作映射
        actions = [
            CCAction(cwnd_change=1, description="RL: increase cwnd"),
            CCAction(cwnd_change=-1, description="RL: decrease cwnd"),
            CCAction(backoff=True, cwnd_change=-5, description="RL: backoff"),
            CCAction(fast_retransmit=True, description="RL: fast retransmit"),
            CCAction(slow_start=True, cwnd_change=10, description="RL: slow start"),
        ]

        action = actions[action_idx]

        # 计算奖励并更新 Q 表
        reward = self._compute_reward(metrics)
        self._update_q_table(state, action_idx, reward)

        # 衰减探索率
        self._exploration_rate = max(0.01, self._exploration_rate * 0.999)

        return action

    def _encode_state(self, metrics: NetworkMetrics) -> str:
        """将网络状态编码为离散状态"""
        loss_level = 0 if metrics.loss_rate < 0.01 else (1 if metrics.loss_rate < 0.05 else 2)
        rtt_level = 0 if metrics.rtt < metrics.rtt_min * 1.5 else (1 if metrics.rtt < metrics.rtt_min * 3 else 2)
        bw_level = 0 if metrics.throughput < 1e6 else (1 if metrics.throughput < 1e8 else 2)

        return f"{loss_level},{rtt_level},{bw_level}"

    def _best_action(self, state: str) -> int:
        """获取最佳动作"""
        best_action = 0
        best_value = float("-inf")
        for i in range(5):
            q_key = f"{state}:{i}"
            value = self._q_table.get(q_key, 0.0)
            if value > best_value:
                best_value = value
                best_action = i
        return best_action

    def _compute_reward(self, metrics: NetworkMetrics) -> float:
        """计算奖励值"""
        # 基于吞吐量、延迟和丢包率的奖励
        throughput_reward = math.log(metrics.throughput + 1) / 20
        latency_penalty = -math.log(metrics.rtt / max(metrics.rtt_min, 0.001) + 1)
        loss_penalty = -metrics.loss_rate * 10
        return throughput_reward + latency_penalty + loss_penalty

    def _update_q_table(self, state: str, action: int, reward: float) -> None:
        """更新 Q 表"""
        q_key = f"{state}:{action}"
        current_q = self._q_table.get(q_key, 0.0)

        # 获取下一状态的最大 Q 值
        next_state = state
        next_max_q = max(
            self._q_table.get(f"{next_state}:{i}", 0.0) for i in range(5)
        )

        # Q-learning 更新
        gamma = 0.9
        new_q = current_q + self._learning_rate * (reward + gamma * next_max_q - current_q)
        self._q_table[q_key] = new_q

    def _adaptive_algorithm(self, metrics: NetworkMetrics) -> CCAction:
        """自适应拥塞控制"""
        zone = metrics.zone
        cwnd = metrics.congestion_window or 1

        if zone == CCZone.SEVERE:
            new_cwnd = max(cwnd // 2, 1)
            return CCAction(
                cwnd_change=new_cwnd - cwnd,
                backoff=True,
                description="Adaptive: severe congestion, halve cwnd",
            )
        elif zone == CCZone.HIGH:
            new_cwnd = max(int(cwnd * 0.7), 1)
            return CCAction(
                cwnd_change=new_cwnd - cwnd,
                description="Adaptive: high congestion, reduce 30%",
            )
        elif zone == CCZone.MEDIUM:
            new_cwnd = cwnd + 1
            return CCAction(
                cwnd_change=1,
                description="Adaptive: medium congestion, slow growth",
            )
        else:
            new_cwnd = cwnd + max(1, int(cwnd * 0.1))
            return CCAction(
                cwnd_change=new_cwnd - cwnd,
                description="Adaptive: low congestion, normal growth",
            )

    def _hybrid_algorithm(self, metrics: NetworkMetrics) -> CCAction:
        """混合拥塞控制"""
        # 根据当前状况选择最佳算法
        if metrics.loss_rate > 0.05:
            return self._adaptive_algorithm(metrics)
        elif metrics.rtt > metrics.rtt_min * 2:
            return self._vegas_algorithm(metrics)
        else:
            return self._bbr_algorithm(metrics)

    def get_optimal_cwnd(self) -> int:
        """获取最优拥塞窗口大小"""
        action = self.get_optimized_action()
        return self._current_metrics.congestion_window + action.cwnd_change

    def get_optimal_rate(self) -> float:
        """获取最优发送速率"""
        metrics = self._current_metrics
        action = self.get_optimized_action()

        if action.pacing_rate > 0:
            return action.pacing_rate

        rtt = max(metrics.rtt, 0.001)
        cwnd = max(metrics.congestion_window + action.cwnd_change, 1)
        rate = (cwnd * 1460) / rtt * 8  # bps
        return min(max(rate, self._min_rate), self._max_rate)

    def should_backoff(self) -> bool:
        """判断是否需要退避"""
        metrics = self._current_metrics
        return (
            metrics.loss_rate > 0.05
            or metrics.zone == CCZone.SEVERE
            or metrics.rtt > metrics.rtt_min * 4
        )

    def should_fast_retransmit(self) -> bool:
        """判断是否需要快速重传"""
        metrics = self._current_metrics
        return metrics.loss_rate > 0.02 or metrics.retransmit_rate > 0.05

    def get_metrics_summary(self) -> Dict[str, Any]:
        """获取指标摘要"""
        if not self._metrics_history:
            return {}

        recent = self._metrics_history[-min(100, len(self._metrics_history)):]
        return {
            "current_rtt": self._current_metrics.rtt,
            "current_throughput": self._current_metrics.throughput,
            "current_loss_rate": self._current_metrics.loss_rate,
            "current_zone": self._current_metrics.zone.value,
            "avg_rtt": sum(m.rtt for m in recent) / len(recent),
            "avg_throughput": sum(m.throughput for m in recent) / len(recent),
            "avg_loss_rate": sum(m.loss_rate for m in recent) / len(recent),
            "min_rtt": min(m.rtt for m in recent),
            "max_throughput": max(m.throughput for m in recent),
            "rtt_samples": len(self._rtt_samples),
            "throughput_samples": len(self._throughput_samples),
        }

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "algorithm": self.algorithm.value,
            "sensitivity": self.sensitivity,
            "update_interval": self.update_interval,
            "exploration_rate": self._exploration_rate,
            "q_table_size": len(self._q_table),
            "metrics_history_size": len(self._metrics_history),
            "current_zone": self._current_metrics.zone.value if self._current_metrics else "unknown",
            "recent_actions": [str(a) for a in self._actions_taken[-10:]],
        }

    def reset(self) -> None:
        """重置优化器"""
        self._metrics_history.clear()
        self._actions_taken.clear()
        self._current_metrics = NetworkMetrics()
        self._rtt_samples.clear()
        self._throughput_samples.clear()
        self._loss_samples.clear()
        self._q_table.clear()
        self._exploration_rate = 0.1
        self._last_update = 0.0
        self._stats = {
            "actions_taken": 0,
            "backoffs": 0,
            "fast_retransmits": 0,
            "slow_starts": 0,
            "avg_throughput": 0.0,
            "avg_loss_rate": 0.0,
            "avg_rtt": 0.0,
        }
        logger.info("拥塞控制优化器已重置")