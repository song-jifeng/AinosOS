"""
容器运行时集成测试

测试容器生命周期管理、资源限制、网络隔离和卷挂载功能。
"""

import os
import sys
import json
import time
import uuid
import random
import string
import pytest
import threading
import subprocess
import tempfile
import shutil
import signal
from typing import List, Dict, Optional, Any, Tuple, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, PropertyMock, call
from contextlib import contextmanager


# =============================================================================
# 容器抽象层
# =============================================================================

class ContainerStatus(Enum):
    """容器状态"""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    EXITED = "exited"
    DEAD = "dead"


class ContainerHealth(Enum):
    """容器健康状态"""
    NONE = "none"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass
class ContainerConfig:
    """容器配置"""
    image: str
    name: Optional[str] = None
    command: Optional[List[str]] = None
    entrypoint: Optional[List[str]] = None
    environment: Dict[str, str] = field(default_factory=dict)
    ports: Dict[int, int] = field(default_factory=dict)  # host:container
    volumes: List[Dict[str, str]] = field(default_factory=list)
    network_mode: str = "bridge"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    cpu_set: Optional[str] = None
    privileged: bool = False
    restart_policy: str = "no"
    healthcheck: Optional[Dict[str, Any]] = None
    labels: Dict[str, str] = field(default_factory=dict)
    working_dir: Optional[str] = None
    user: Optional[str] = None
    read_only: bool = False
    sysctls: Dict[str, str] = field(default_factory=dict)
    cap_add: List[str] = field(default_factory=list)
    cap_drop: List[str] = field(default_factory=list)
    dns: List[str] = field(default_factory=list)
    extra_hosts: Dict[str, str] = field(default_factory=dict)


@dataclass
class ContainerStats:
    """容器资源统计"""
    container_id: str
    cpu_percent: float = 0.0
    memory_usage_bytes: int = 0
    memory_limit_bytes: int = 0
    memory_percent: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    block_read_bytes: int = 0
    block_write_bytes: int = 0
    pids_current: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ContainerInfo:
    """容器信息"""
    container_id: str
    name: str
    image: str
    status: ContainerStatus
    config: ContainerConfig
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    health: ContainerHealth = ContainerHealth.NONE
    ip_address: Optional[str] = None
    pid: int = 0
    exit_code: Optional[int] = None


# =============================================================================
# Mock 容器运行时
# =============================================================================

class MockContainerRuntime:
    """模拟容器运行时"""

    def __init__(self):
        self._containers: Dict[str, ContainerInfo] = {}
        self._networks: Dict[str, List[str]] = {}  # network_name -> [container_ids]
        self._images: Dict[str, int] = {}  # image_name -> count
        self._lock = threading.RLock()
        self._default_network = "bridge"

    def create_container(self, config: ContainerConfig) -> ContainerInfo:
        """创建容器"""
        with self._lock:
            container_id = self._generate_id()
            name = config.name or f"container-{container_id[:12]}"

            # 检查名称冲突
            for cid, info in self._containers.items():
                if info.name == name and info.status != ContainerStatus.EXITED:
                    raise ValueError(f"Container with name '{name}' already exists")

            # 分配 IP
            ip_address = self._allocate_ip(config.network_mode)

            info = ContainerInfo(
                container_id=container_id,
                name=name,
                image=config.image,
                status=ContainerStatus.CREATED,
                config=config,
                ip_address=ip_address,
            )
            self._containers[container_id] = info
            self._add_to_network(container_id, config.network_mode)
            self._images[config.image] = self._images.get(config.image, 0) + 1
            return info

    def start_container(self, container_id: str) -> bool:
        """启动容器"""
        with self._lock:
            info = self._get_container(container_id)
            if info.status != ContainerStatus.CREATED:
                raise RuntimeError(f"Container {container_id} is in state {info.status.value}")
            info.status = ContainerStatus.RUNNING
            info.started_at = time.time()
            info.pid = random.randint(10000, 50000)
            return True

    def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        """停止容器"""
        with self._lock:
            info = self._get_container(container_id)
            if info.status == ContainerStatus.STOPPED:
                return True
            info.status = ContainerStatus.STOPPED
            info.finished_at = time.time()
            info.exit_code = 0
            return True

    def restart_container(self, container_id: str, timeout: int = 10) -> bool:
        """重启容器"""
        self.stop_container(container_id, timeout)
        time.sleep(0.05)  # 模拟重启延迟
        self.start_container(container_id)
        return True

    def pause_container(self, container_id: str) -> bool:
        """暂停容器"""
        with self._lock:
            info = self._get_container(container_id)
            if info.status != ContainerStatus.RUNNING:
                raise RuntimeError(f"Cannot pause container in state {info.status.value}")
            info.status = ContainerStatus.PAUSED
            return True

    def unpause_container(self, container_id: str) -> bool:
        """恢复容器"""
        with self._lock:
            info = self._get_container(container_id)
            if info.status != ContainerStatus.PAUSED:
                raise RuntimeError(f"Cannot unpause container in state {info.status.value}")
            info.status = ContainerStatus.RUNNING
            return True

    def remove_container(self, container_id: str, force: bool = False) -> bool:
        """删除容器"""
        with self._lock:
            info = self._get_container(container_id)
            if info.status == ContainerStatus.RUNNING:
                if force:
                    self.stop_container(container_id)
                else:
                    raise RuntimeError("Cannot remove running container. Use force=True")
            self._remove_from_network(container_id)
            del self._containers[container_id]
            return True

    def exec_command(self, container_id: str, command: List[str]) -> Tuple[int, str]:
        """在容器中执行命令"""
        info = self._get_container(container_id)
        if info.status != ContainerStatus.RUNNING:
            raise RuntimeError(f"Container {container_id} is not running")

        # 模拟命令执行
        time.sleep(random.uniform(0.01, 0.05))
        cmd = " ".join(command)
        if cmd == "echo hello":
            return (0, "hello\n")
        elif cmd == "whoami":
            return (0, "root\n")
        elif cmd == "uname -a":
            return (0, "Linux container 5.15.0 #1 SMP x86_64 GNU/Linux\n")
        elif cmd.startswith("cat /"):
            return (0, "mock file content\n")
        elif cmd == "exit 1":
            return (1, "")
        else:
            return (0, f"Executed: {cmd}\n")

    def get_container_logs(self, container_id: str, tail: int = 100) -> List[str]:
        """获取容器日志"""
        info = self._get_container(container_id)
        logs = []
        for i in range(min(tail, 50)):
            logs.append(f"[{info.name}] Log line {i}: container {container_id[:12]} running")
        return logs

    def inspect_container(self, container_id: str) -> Dict[str, Any]:
        """检查容器详细信息"""
        info = self._get_container(container_id)
        return {
            "id": info.container_id,
            "name": info.name,
            "image": info.image,
            "status": info.status.value,
            "created": info.created_at,
            "started": info.started_at,
            "finished": info.finished_at,
            "health": info.health.value,
            "ip": info.ip_address,
            "pid": info.pid,
            "exit_code": info.exit_code,
            "config": {
                "memory": info.config.memory_limit,
                "cpu": info.config.cpu_limit,
                "network": info.config.network_mode,
                "ports": info.config.ports,
                "volumes": info.config.volumes,
                "env": info.config.environment,
            },
        }

    def list_containers(self, all: bool = False) -> List[ContainerInfo]:
        """列出容器"""
        with self._lock:
            if all:
                return list(self._containers.values())
            return [c for c in self._containers.values()
                    if c.status in (ContainerStatus.RUNNING, ContainerStatus.PAUSED)]

    def get_stats(self, container_id: str) -> ContainerStats:
        """获取容器资源统计"""
        info = self._get_container(container_id)
        return ContainerStats(
            container_id=container_id,
            cpu_percent=random.uniform(0.1, 50.0),
            memory_usage_bytes=random.randint(50 * 1024 * 1024, 500 * 1024 * 1024),
            memory_limit_bytes=self._parse_memory(info.config.memory_limit),
            memory_percent=random.uniform(1, 50),
            network_rx_bytes=random.randint(1000, 100000),
            network_tx_bytes=random.randint(1000, 100000),
            block_read_bytes=random.randint(0, 10000),
            block_write_bytes=random.randint(0, 10000),
            pids_current=random.randint(1, 50),
        )

    def create_network(self, network_name: str, driver: str = "bridge") -> bool:
        """创建网络"""
        with self._lock:
            if network_name in self._networks:
                raise ValueError(f"Network '{network_name}' already exists")
            self._networks[network_name] = []
            return True

    def remove_network(self, network_name: str) -> bool:
        """删除网络"""
        with self._lock:
            if network_name not in self._networks:
                raise ValueError(f"Network '{network_name}' not found")
            containers = self._networks[network_name]
            if containers:
                raise RuntimeError(f"Network '{network_name}' has {len(containers)} connected containers")
            del self._networks[network_name]
            return True

    def connect_to_network(self, container_id: str, network_name: str) -> bool:
        """连接容器到网络"""
        with self._lock:
            self._get_container(container_id)
            if network_name not in self._networks:
                raise ValueError(f"Network '{network_name}' not found")
            if container_id not in self._networks[network_name]:
                self._networks[network_name].append(container_id)
            return True

    def disconnect_from_network(self, container_id: str, network_name: str) -> bool:
        """断开容器与网络的连接"""
        with self._lock:
            self._get_container(container_id)
            if network_name not in self._networks:
                raise ValueError(f"Network '{network_name}' not found")
            if container_id in self._networks[network_name]:
                self._networks[network_name].remove(container_id)
            return True

    def _get_container(self, container_id: str) -> ContainerInfo:
        if container_id not in self._containers:
            raise KeyError(f"Container '{container_id}' not found")
        return self._containers[container_id]

    def _generate_id(self) -> str:
        return uuid.uuid4().hex

    def _allocate_ip(self, network_mode: str) -> str:
        if network_mode == "host":
            return "127.0.0.1"
        elif network_mode == "none":
            return None
        else:
            return f"172.17.0.{random.randint(2, 254)}"

    def _add_to_network(self, container_id: str, network_mode: str):
        if network_mode == "bridge":
            if self._default_network not in self._networks:
                self._networks[self._default_network] = []
            self._networks[self._default_network].append(container_id)

    def _remove_from_network(self, container_id: str):
        for network in self._networks.values():
            if container_id in network:
                network.remove(container_id)

    @staticmethod
    def _parse_memory(memory_str: str) -> int:
        units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
        memory_str = memory_str.lower().strip()
        if memory_str[-1].isalpha():
            number = int(memory_str[:-1])
            unit = memory_str[-1]
            return number * units.get(unit, 1)
        return int(memory_str)

    def clear(self):
        with self._lock:
            self._containers.clear()
            self._networks.clear()
            self._images.clear()


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def container_runtime():
    runtime = MockContainerRuntime()
    runtime.create_network("bridge")
    yield runtime
    runtime.clear()


@pytest.fixture
def sample_container(container_runtime):
    config = ContainerConfig(
        image="nginx:latest",
        name="test-nginx",
        ports={8080: 80},
        environment={"NGINX_HOST": "localhost"},
        memory_limit="256m",
        cpu_limit=0.5,
    )
    container = container_runtime.create_container(config)
    container_runtime.start_container(container.container_id)
    return container


# =============================================================================
# 测试用例：容器生命周期
# =============================================================================

class TestContainerLifecycle:
    """容器生命周期测试"""

    def test_create_container(self, container_runtime):
        """测试创建容器"""
        config = ContainerConfig(
            image="ubuntu:22.04",
            name="test-ubuntu",
            command=["sleep", "3600"],
        )
        container = container_runtime.create_container(config)
        assert container.container_id is not None
        assert container.name == "test-ubuntu"
        assert container.image == "ubuntu:22.04"
        assert container.status == ContainerStatus.CREATED
        assert container.ip_address is not None

    def test_create_container_duplicate_name(self, container_runtime):
        """测试创建同名容器"""
        config = ContainerConfig(image="alpine:latest", name="unique-name")
        container_runtime.create_container(config)
        with pytest.raises(ValueError, match="already exists"):
            container_runtime.create_container(config)

    def test_start_container(self, container_runtime):
        """测试启动容器"""
        container = container_runtime.create_container(
            ContainerConfig(image="nginx:latest")
        )
        result = container_runtime.start_container(container.container_id)
        assert result is True

        info = container_runtime.inspect_container(container.container_id)
        assert info["status"] == "running"
        assert info["started"] is not None
        assert info["pid"] > 0

    def test_stop_container(self, sample_container):
        """测试停止容器"""
        result = container_runtime.stop_container(sample_container.container_id)
        assert result is True

        info = container_runtime.inspect_container(sample_container.container_id)
        assert info["status"] == "stopped"

    def test_restart_container(self, sample_container):
        """测试重启容器"""
        result = container_runtime.restart_container(sample_container.container_id)
        assert result is True

        info = container_runtime.inspect_container(sample_container.container_id)
        assert info["status"] == "running"

    def test_pause_unpause_container(self, sample_container):
        """测试暂停和恢复容器"""
        result = container_runtime.pause_container(sample_container.container_id)
        assert result is True

        info = container_runtime.inspect_container(sample_container.container_id)
        assert info["status"] == "paused"

        result = container_runtime.unpause_container(sample_container.container_id)
        assert result is True

        info = container_runtime.inspect_container(sample_container.container_id)
        assert info["status"] == "running"

    def test_remove_container(self, sample_container):
        """测试删除容器"""
        container_runtime.stop_container(sample_container.container_id)
        result = container_runtime.remove_container(sample_container.container_id)
        assert result is True

        with pytest.raises(KeyError):
            container_runtime.inspect_container(sample_container.container_id)

    def test_remove_running_container_without_force(self, sample_container):
        """测试删除运行中的容器（不强制）"""
        with pytest.raises(RuntimeError, match="Cannot remove running container"):
            container_runtime.remove_container(sample_container.container_id, force=False)

    def test_remove_running_container_with_force(self, sample_container):
        """测试强制删除运行中的容器"""
        result = container_runtime.remove_container(sample_container.container_id, force=True)
        assert result is True

    def test_container_lifecycle_full(self, container_runtime):
        """测试完整生命周期"""
        config = ContainerConfig(
            image="redis:7",
            name="test-redis",
            ports={6379: 6379},
        )

        # 创建 -> 运行 -> 暂停 -> 恢复 -> 停止 -> 删除
        container = container_runtime.create_container(config)
        assert container.status == ContainerStatus.CREATED

        container_runtime.start_container(container.container_id)
        assert container_runtime.inspect_container(container.container_id)["status"] == "running"

        container_runtime.pause_container(container.container_id)
        assert container_runtime.inspect_container(container.container_id)["status"] == "paused"

        container_runtime.unpause_container(container.container_id)
        assert container_runtime.inspect_container(container.container_id)["status"] == "running"

        container_runtime.stop_container(container.container_id)
        assert container_runtime.inspect_container(container.container_id)["status"] == "stopped"

        container_runtime.remove_container(container.container_id)
        with pytest.raises(KeyError):
            container_runtime.inspect_container(container.container_id)

    def test_multiple_containers(self, container_runtime):
        """测试多个容器"""
        configs = [
            ContainerConfig(image="nginx:latest", name=f"web-{i}")
            for i in range(5)
        ]

        containers = []
        for config in configs:
            c = container_runtime.create_container(config)
            container_runtime.start_container(c.container_id)
            containers.append(c)

        running = container_runtime.list_containers()
        assert len(running) == 5

        for c in container_runtime.list_containers(all=True):
            assert c.status == ContainerStatus.RUNNING


# =============================================================================
# 测试用例：资源限制
# =============================================================================

class TestResourceLimits:
    """资源限制测试"""

    def test_memory_limit(self, container_runtime):
        """测试内存限制"""
        config = ContainerConfig(
            image="memory-test:latest",
            memory_limit="128m",
        )
        container = container_runtime.create_container(config)
        container_runtime.start_container(container.container_id)

        info = container_runtime.inspect_container(container.container_id)
        assert info["config"]["memory"] == "128m"

    def test_cpu_limit(self, container_runtime):
        """测试 CPU 限制"""
        config = ContainerConfig(
            image="cpu-test:latest",
            cpu_limit=0.75,
        )
        container = container_runtime.create_container(config)
        container_runtime.start_container(container.container_id)

        info = container_runtime.inspect_container(container.container_id)
        assert info["config"]["cpu"] == 0.75

    def test_cpu_set_affinity(self, container_runtime):
        """测试 CPU 亲和性"""
        config = ContainerConfig(
            image="cpu-pin-test:latest",
            cpu_set="0-3",
        )
        container = container_runtime.create_container(config)
        assert container.config.cpu_set == "0-3"

    def test_resource_stats(self, sample_container):
        """测试资源统计"""
        stats = container_runtime.get_stats(sample_container.container_id)
        assert stats.container_id == sample_container.container_id
        assert stats.cpu_percent >= 0
        assert stats.memory_usage_bytes > 0
        assert stats.memory_limit_bytes > 0
        assert stats.pids_current > 0
        assert stats.timestamp > 0

    def test_multiple_resource_limits(self, container_runtime):
        """测试多重资源限制组合"""
        config = ContainerConfig(
            image="limited:latest",
            memory_limit="1g",
            cpu_limit=2.0,
            cpu_set="0-1",
            pids_limit=100,
        )
        container = container_runtime.create_container(config)
        container_runtime.start_container(container.container_id)

        info = container_runtime.inspect_container(container.container_id)
        assert info["config"]["memory"] == "1g"
        assert info["config"]["cpu"] == 2.0

    def test_oom_kill_simulation(self, container_runtime):
        """测试 OOM 杀死模拟"""
        config = ContainerConfig(
            image="memory-hungry:latest",
            memory_limit="1m",  # 极小内存限制
        )
        container = container_runtime.create_container(config)
        try:
            container_runtime.start_container(container.container_id)
            info = container_runtime.inspect_container(container.container_id)
            assert info["status"] == "running"
        except RuntimeError:
            pass


# =============================================================================
# 测试用例：网络隔离
# =============================================================================

class TestNetworkIsolation:
    """网络隔离测试"""

    def test_default_network(self, container_runtime):
        """测试默认网络"""
        config = ContainerConfig(image="nginx:latest")
        container = container_runtime.create_container(config)
        assert container.ip_address is not None
        assert container.ip_address.startswith("172.17.")

    def test_host_network(self, container_runtime):
        """测试主机网络模式"""
        config = ContainerConfig(image="nginx:latest", network_mode="host")
        container = container_runtime.create_container(config)
        assert container.ip_address == "127.0.0.1"

    def test_none_network(self, container_runtime):
        """测试无网络模式"""
        config = ContainerConfig(image="nginx:latest", network_mode="none")
        container = container_runtime.create_container(config)
        assert container.ip_address is None

    def test_custom_network(self, container_runtime):
        """测试自定义网络"""
        container_runtime.create_network("my-network")
        config = ContainerConfig(image="nginx:latest", network_mode="my-network")
        container = container_runtime.create_container(config)
        assert container.ip_address is not None

    def test_network_connect_disconnect(self, container_runtime, sample_container):
        """测试网络连接和断开"""
        container_runtime.create_network("test-net")

        result = container_runtime.connect_to_network(
            sample_container.container_id, "test-net"
        )
        assert result is True

        result = container_runtime.disconnect_from_network(
            sample_container.container_id, "test-net"
        )
        assert result is True

    def test_network_isolation_between_containers(self, container_runtime):
        """测试容器间网络隔离"""
        container_runtime.create_network("isolated-net")

        config1 = ContainerConfig(image="app1:latest", network_mode="isolated-net")
        config2 = ContainerConfig(image="app2:latest", network_mode="isolated-net")

        c1 = container_runtime.create_container(config1)
        c2 = container_runtime.create_container(config2)

        info1 = container_runtime.inspect_container(c1.container_id)
        info2 = container_runtime.inspect_container(c2.container_id)

        # 同一网络内的容器
        assert info1["ip"] != info2["ip"]

    def test_port_mapping(self, container_runtime):
        """测试端口映射"""
        config = ContainerConfig(
            image="web:latest",
            ports={8080: 80, 8443: 443},
        )
        container = container_runtime.create_container(config)
        info = container_runtime.inspect_container(container.container_id)
        assert info["config"]["ports"] == {8080: 80, 8443: 443}

    def test_dns_configuration(self, container_runtime):
        """测试 DNS 配置"""
        config = ContainerConfig(
            image="dns-test:latest",
            dns=["8.8.8.8", "8.8.4.4"],
            dns_search=["example.com"],
        )
        container = container_runtime.create_container(config)
        assert container.config.dns == ["8.8.8.8", "8.8.4.4"]


# =============================================================================
# 测试用例：卷挂载
# =============================================================================

class TestVolumeMounting:
    """卷挂载测试"""

    def test_bind_mount(self, container_runtime):
        """测试绑定挂载"""
        config = ContainerConfig(
            image="app:latest",
            volumes=[{
                "type": "bind",
                "source": "/host/data",
                "target": "/container/data",
                "read_only": False,
            }],
        )
        container = container_runtime.create_container(config)
        assert len(container.config.volumes) == 1
        vol = container.config.volumes[0]
        assert vol["type"] == "bind"
        assert vol["source"] == "/host/data"
        assert vol["target"] == "/container/data"

    def test_volume_mount(self, container_runtime):
        """测试卷挂载"""
        config = ContainerConfig(
            image="db:latest",
            volumes=[{
                "type": "volume",
                "source": "db-data",
                "target": "/var/lib/data",
            }],
        )
        container = container_runtime.create_container(config)
        assert len(container.config.volumes) == 1

    def test_tmpfs_mount(self, container_runtime):
        """测试 tmpfs 挂载"""
        config = ContainerConfig(
            image="cache:latest",
            volumes=[{
                "type": "tmpfs",
                "target": "/tmp/cache",
                "tmpfs_options": "size=100m",
            }],
        )
        container = container_runtime.create_container(config)
        assert container.config.volumes[0]["type"] == "tmpfs"

    def test_multiple_volumes(self, container_runtime):
        """测试多个卷挂载"""
        config = ContainerConfig(
            image="complex:latest",
            volumes=[
                {"type": "bind", "source": "/cfg", "target": "/etc/app"},
                {"type": "volume", "source": "app-data", "target": "/var/data"},
                {"type": "tmpfs", "target": "/tmp"},
            ],
        )
        container = container_runtime.create_container(config)
        assert len(container.config.volumes) == 3

    def test_read_only_volume(self, container_runtime):
        """测试只读卷"""
        config = ContainerConfig(
            image="readonly-test:latest",
            volumes=[{
                "type": "bind",
                "source": "/host/readonly",
                "target": "/container/readonly",
                "read_only": True,
            }],
        )
        container = container_runtime.create_container(config)
        assert container.config.volumes[0]["read_only"] is True

    def test_read_only_rootfs(self, container_runtime):
        """测试只读根文件系统"""
        config = ContainerConfig(
            image="security:latest",
            read_only=True,
            volumes=[{
                "type": "tmpfs",
                "target": "/tmp",
            }],
        )
        container = container_runtime.create_container(config)
        assert container.config.read_only is True


# =============================================================================
# 测试用例：容器内执行命令
# =============================================================================

class TestContainerExec:
    """容器内命令执行测试"""

    def test_exec_simple_command(self, sample_container):
        """测试执行简单命令"""
        exit_code, output = container_runtime.exec_command(
            sample_container.container_id, ["echo", "hello"]
        )
        assert exit_code == 0
        assert "hello" in output

    def test_exec_whoami(self, sample_container):
        """测试 whoami 命令"""
        exit_code, output = container_runtime.exec_command(
            sample_container.container_id, ["whoami"]
        )
        assert exit_code == 0
        assert "root" in output

    def test_exec_exit_code(self, sample_container):
        """测试命令退出码"""
        exit_code, _ = container_runtime.exec_command(
            sample_container.container_id, ["exit", "1"]
        )
        assert exit_code == 1

    def test_exec_in_non_running_container(self, container_runtime):
        """测试在非运行容器中执行命令"""
        config = ContainerConfig(image="test:latest")
        container = container_runtime.create_container(config)
        with pytest.raises(RuntimeError, match="not running"):
            container_runtime.exec_command(container.container_id, ["echo", "test"])


# =============================================================================
# 测试用例：容器日志
# =============================================================================

class TestContainerLogs:
    """容器日志测试"""

    def test_get_container_logs(self, sample_container):
        """测试获取容器日志"""
        logs = container_runtime.get_container_logs(sample_container.container_id)
        assert len(logs) > 0
        assert all(sample_container.name in log for log in logs)

    def test_logs_tail_limit(self, sample_container):
        """测试日志行数限制"""
        logs = container_runtime.get_container_logs(
            sample_container.container_id, tail=10
        )
        assert len(logs) <= 10

    def test_logs_after_stop(self, sample_container):
        """测试停止后获取日志"""
        container_runtime.stop_container(sample_container.container_id)
        logs = container_runtime.get_container_logs(sample_container.container_id)
        assert len(logs) > 0

    def test_logs_empty_container(self, container_runtime):
        """测试空容器日志"""
        config = ContainerConfig(image="empty:latest")
        container = container_runtime.create_container(config)
        container_runtime.start_container(container.container_id)
        logs = container_runtime.get_container_logs(container.container_id)
        assert len(logs) >= 0


# =============================================================================
# 测试用例：容器健康检查
# =============================================================================

class TestContainerHealthCheck:
    """容器健康检查测试"""

    def test_health_check_configuration(self, container_runtime):
        """测试健康检查配置"""
        config = ContainerConfig(
            image="healthy-app:latest",
            healthcheck={
                "test": ["CMD", "curl", "-f", "http://localhost/health"],
                "interval": 30,
                "timeout": 10,
                "retries": 3,
                "start_period": 5,
            },
        )
        container = container_runtime.create_container(config)
        assert container.config.healthcheck is not None
        assert container.config.healthcheck["interval"] == 30

    def test_health_check_default(self, sample_container):
        """测试默认健康检查状态"""
        assert sample_container.health == ContainerHealth.NONE

    def test_health_check_transition(self, container_runtime):
        """测试健康检查状态转换"""
        config = ContainerConfig(
            image="web:latest",
            healthcheck={"test": ["CMD", "echo", "ok"]},
        )
        container = container_runtime.create_container(config)
        # 模拟健康检查过程
        container.health = ContainerHealth.STARTING
        assert container.health == ContainerHealth.STARTING

        container.health = ContainerHealth.HEALTHY
        assert container.health == ContainerHealth.HEALTHY


# =============================================================================
# 测试用例：容器安全
# =============================================================================

class TestContainerSecurity:
    """容器安全测试"""

    def test_privileged_container(self, container_runtime):
        """测试特权容器"""
        config = ContainerConfig(
            image="security-test:latest",
            privileged=True,
        )
        container = container_runtime.create_container(config)
        assert container.config.privileged is True

    def test_capabilities_add_drop(self, container_runtime):
        """测试能力添加/删除"""
        config = ContainerConfig(
            image="cap-test:latest",
            cap_add=["NET_ADMIN", "SYS_TIME"],
            cap_drop=["ALL"],
        )
        container = container_runtime.create_container(config)
        assert "NET_ADMIN" in container.config.cap_add
        assert "ALL" in container.config.cap_drop

    def test_user_namespace(self, container_runtime):
        """测试用户命名空间"""
        config = ContainerConfig(
            image="user-test:latest",
            user="1000:1000",
        )
        container = container_runtime.create_container(config)
        assert container.config.user == "1000:1000"

    def test_security_options(self, container_runtime):
        """测试安全选项"""
        config = ContainerConfig(
            image="secure:latest",
            labels={"security.apparmor": "default"},
            read_only=True,
        )
        container = container_runtime.create_container(config)
        assert container.config.labels["security.apparmor"] == "default"


# =============================================================================
# 测试用例：容器编排
# =============================================================================

class TestContainerOrchestration:
    """容器编排测试"""

    def test_compose_style_deployment(self, container_runtime):
        """测试 Compose 风格部署"""
        services = [
            ("web", ContainerConfig(image="nginx:latest", ports={80: 80})),
            ("api", ContainerConfig(image="api:latest", ports={8080: 8080},
                                    environment={"DB_HOST": "db"})),
            ("db", ContainerConfig(image="postgres:latest",
                                   environment={"POSTGRES_PASSWORD": "secret"})),
        ]

        deployed = []
        for name, config in services:
            config.name = name
            container = container_runtime.create_container(config)
            container_runtime.start_container(container.container_id)
            deployed.append(container)

        assert len(deployed) == 3
        running = container_runtime.list_containers()
        assert len(running) == 3

    def test_container_dependency(self, container_runtime):
        """测试容器依赖"""
        db_config = ContainerConfig(image="postgres:latest", name="db")
        db = container_runtime.create_container(db_config)
        container_runtime.start_container(db.container_id)

        app_config = ContainerConfig(
            image="app:latest", name="app",
            environment={"DB_HOST": db.ip_address},
        )
        app = container_runtime.create_container(app_config)
        container_runtime.start_container(app.container_id)

        info = container_runtime.inspect_container(app.container_id)
        assert "DB_HOST" in str(info["config"]["env"])

    def test_container_scaling(self, container_runtime):
        """测试容器伸缩"""
        base_config = ContainerConfig(image="worker:latest")

        # 扩容到 3 个
        workers = []
        for i in range(3):
            c = container_runtime.create_container(base_config)
            container_runtime.start_container(c.container_id)
            workers.append(c)

        assert len(container_runtime.list_containers()) == 3

        # 缩容到 1 个
        for c in workers[1:]:
            container_runtime.stop_container(c.container_id)
            container_runtime.remove_container(c.container_id)

        assert len(container_runtime.list_containers()) == 1

    def test_container_discovery(self, container_runtime):
        """测试容器发现"""
        names = ["redis", "mysql", "nginx"]
        for name in names:
            config = ContainerConfig(image=f"{name}:latest", name=name)
            container = container_runtime.create_container(config)
            container_runtime.start_container(container.container_id)

        containers = container_runtime.list_containers()
        found_names = [c.name for c in containers]
        for name in names:
            assert name in found_names


# =============================================================================
# 容器测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])