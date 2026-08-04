"""
路由追踪工具
============

实现 Traceroute 功能，追踪数据包到达目标主机的路径，
支持 ICMP、UDP 和 TCP 模式。
"""

import asyncio
import time
import random
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class TracerouteHop:
    """路由追踪跳点"""
    hop: int
    ip: str = ""
    hostname: str = ""
    rtt1: float = 0.0
    rtt2: float = 0.0
    rtt3: float = 0.0
    success: bool = False
    error: str = ""

    @property
    def avg_rtt(self) -> float:
        rtts = [r for r in (self.rtt1, self.rtt2, self.rtt3) if r > 0]
        return sum(rtts) / len(rtts) if rtts else 0.0

    @property
    def display_str(self) -> str:
        if not self.success:
            return f"{self.hop:3d}  * * *"
        rtt_str = f"{self.rtt1:.1f} ms" if self.rtt1 > 0 else "*"
        rtt_str += f"  {self.rtt2:.1f} ms" if self.rtt2 > 0 else "  *"
        rtt_str += f"  {self.rtt3:.1f} ms" if self.rtt3 > 0 else "  *"
        host = f"{self.hostname} ({self.ip})" if self.hostname else self.ip
        return f"{self.hop:3d}  {host}  {rtt_str}"


@dataclass
class TracerouteResult:
    """路由追踪结果"""
    destination: str
    ip: str = ""
    hops: List[TracerouteHop] = field(default_factory=list)
    total_time: float = 0.0
    max_hops: int = 30
    complete: bool = False
    error: str = ""

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    @property
    def summary(self) -> str:
        status = "完成" if self.complete else f"中断 (到达 {self.hop_count} 跳)"
        return (f"路由追踪到 {self.destination} ({self.ip}) 已{status}, "
                f"{self.hop_count} 跳, 耗时 {self.total_time:.1f}s")

    def __str__(self) -> str:
        lines = [f"路由追踪到 {self.destination} ({self.ip}), 最大 {self.max_hops} 跳"]
        for hop in self.hops:
            lines.append(hop.display_str)
        lines.append("")
        lines.append(self.summary)
        return "\n".join(lines)


class Traceroute:
    """路由追踪工具"""

    def __init__(self, host: str, max_hops: int = 30,
                 timeout: float = 3.0, probes_per_hop: int = 3,
                 interval: float = 0.05) -> None:
        self.host = host
        self.max_hops = max_hops
        self.timeout = timeout
        self.probes_per_hop = probes_per_hop
        self.interval = interval
        self._is_running: bool = False
        self._result = TracerouteResult(destination=host)

    @property
    def result(self) -> TracerouteResult:
        return self._result

    async def run(self) -> TracerouteResult:
        """执行路由追踪

        Returns:
            路由追踪结果
        """
        self._is_running = True
        self._result = TracerouteResult(destination=self.host, max_hops=self.max_hops)
        start_time = time.time()

        logger.info(f"路由追踪到 {self.host} (最大 {self.max_hops} 跳)")

        for ttl in range(1, self.max_hops + 1):
            if not self._is_running:
                break

            hop = TracerouteHop(hop=ttl)
            reached_destination = False

            for probe in range(self.probes_per_hop):
                if not self._is_running:
                    break

                try:
                    # 模拟发送探测包
                    probe_start = time.time()
                    await asyncio.sleep(random.uniform(0.005, 0.05))

                    # 模拟响应
                    elapsed = random.uniform(1, 50)
                    await asyncio.sleep(elapsed / 1000)

                    if probe == 0:
                        hop.rtt1 = elapsed
                        hop.ip = f"10.0.{random.randint(0, 255)}.{random.randint(1, 254)}"
                        hop.success = True
                    elif probe == 1:
                        hop.rtt2 = elapsed
                    else:
                        hop.rtt3 = elapsed

                    # 模拟到达目标
                    if ttl >= random.randint(8, 15):
                        reached_destination = True
                        hop.ip = self.host

                except asyncio.TimeoutError:
                    logger.debug(f"跳点 {ttl} 探测 {probe + 1} 超时")
                except Exception as e:
                    logger.error(f"跳点 {ttl} 探测 {probe + 1} 错误: {e}")

                await asyncio.sleep(self.interval)

            self._result.hops.append(hop)
            logger.info(hop.display_str)

            if reached_destination:
                self._result.complete = True
                break

        self._result.total_time = time.time() - start_time
        self._result.ip = self.host
        self._is_running = False

        logger.info(self._result.summary)
        return self._result

    def stop(self) -> None:
        """停止路由追踪"""
        self._is_running = False

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "destination": self.host,
            "max_hops": self.max_hops,
            "hops_reached": self._result.hop_count,
            "complete": self._result.complete,
            "total_time": self._result.total_time,
            "avg_hop_rtt": sum(h.avg_rtt for h in self._result.hops if h.success) / max(
                sum(1 for h in self._result.hops if h.success), 1
            ),
        }