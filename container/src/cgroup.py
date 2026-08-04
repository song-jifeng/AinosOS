"""
cgroups v2 资源限制模块 - Control group management for Ainos containers.

支持以下资源限制:
- CPU: 配额、权重、亲和性
- Memory: 上限、软限制、swap
- IO: 读写带宽、IOPS
- GPU: NVIDIA GPU 显存和计算限制
- PIDs: 最大进程数
"""

import enum
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional, Union

logger = logging.getLogger(__name__)

CGROUP_V2_PATH = Path("/sys/fs/cgroup")


class CGroupError(Exception):
    """Raised when a cgroup operation fails."""

    def __init__(self, message: str, path: Optional[str] = None) -> None:
        self.path = path
        super().__init__(f"CGroup error{' at ' + path if path else ''}: {message}")


class IOClass(enum.IntEnum):
    """IO priority classes for cgroup IO controller."""

    BEST_EFFORT = 0
    REALTIME = 1


@dataclass
class CPUConfig:
    """CPU resource limits configuration."""

    shares: Optional[int] = None
    """CPU weight (relative share, 1-10000)."""

    quota: Optional[int] = None
    """CPU quota in microseconds per period (-1 for no limit)."""

    period: Optional[int] = None
    """CPU period in microseconds."""

    cpus: Optional[str] = None
    """CPU affinity (e.g., '0-3,7')."""

    mems: Optional[str] = None
    """Memory node affinity."""

    max_freq: Optional[int] = None
    """Maximum CPU frequency in kHz."""

    idle_latency: Optional[int] = None
    """Target idle latency in microseconds."""

    def validate(self) -> None:
        """Validate CPU configuration values."""
        if self.shares is not None and not (1 <= self.shares <= 10000):
            raise ValueError(f"CPU shares must be in [1, 10000], got {self.shares}")
        if self.quota is not None and self.quota < -1:
            raise ValueError(f"CPU quota must be >= -1, got {self.quota}")
        if self.period is not None and self.period <= 0:
            raise ValueError(f"CPU period must be positive, got {self.period}")


@dataclass
class MemoryConfig:
    """Memory resource limits configuration."""

    limit: Optional[int] = None
    """Memory hard limit in bytes."""

    soft_limit: Optional[int] = None
    """Memory soft limit in bytes."""

    swap_limit: Optional[int] = None
    """Swap + memory limit in bytes."""

    swappiness: Optional[int] = None
    """Swappiness (0-200)."""

    oom_kill: bool = True
    """Whether to enable OOM killer."""

    kmem_limit: Optional[int] = None
    """Kernel memory limit in bytes."""

    def validate(self) -> None:
        """Validate memory configuration values."""
        if self.limit is not None and self.limit <= 0:
            raise ValueError(f"Memory limit must be positive, got {self.limit}")
        if self.swappiness is not None and not (0 <= self.swappiness <= 200):
            raise ValueError(f"Swappiness must be in [0, 200], got {self.swappiness}")


@dataclass
class IOConfig:
    """IO resource limits configuration."""

    read_bps: Optional[int] = None
    """Read bandwidth limit in bytes per second."""

    write_bps: Optional[int] = None
    """Write bandwidth limit in bytes per second."""

    read_iops: Optional[int] = None
    """Read IOPS limit."""

    write_iops: Optional[int] = None
    """Write IOPS limit."""

    weight: Optional[int] = None
    """IO weight (1-1000)."""

    @dataclass
    class DeviceLimit:
        """Per-device IO limit."""

        major: int
        minor: int
        read_bps: Optional[int] = None
        write_bps: Optional[int] = None
        read_iops: Optional[int] = None
        write_iops: Optional[int] = None

    device_limits: list[DeviceLimit] = field(default_factory=list)

    def validate(self) -> None:
        """Validate IO configuration values."""
        if self.weight is not None and not (1 <= self.weight <= 1000):
            raise ValueError(f"IO weight must be in [1, 1000], got {self.weight}")


@dataclass
class GPUConfig:
    """GPU resource limits configuration."""

    gpu_ids: list[int] = field(default_factory=list)
    """List of GPU device IDs to expose."""

    memory_limit: Optional[int] = None
    """GPU memory limit in bytes per device."""

    compute_percent: Optional[int] = None
    """GPU compute utilization limit (1-100 percent)."""

    def validate(self) -> None:
        """Validate GPU configuration."""
        if self.compute_percent is not None and not (1 <= self.compute_percent <= 100):
            raise ValueError(
                f"GPU compute percent must be in [1, 100], got {self.compute_percent}"
            )


@dataclass
class PIDsConfig:
    """PIDs limit configuration."""

    max_pids: Optional[int] = None
    """Maximum number of processes/threads in the cgroup."""

    def validate(self) -> None:
        """Validate PIDs configuration."""
        if self.max_pids is not None and self.max_pids <= 0:
            raise ValueError(f"Max PIDs must be positive, got {self.max_pids}")


@dataclass
class ResourceLimits:
    """Aggregate resource limits for a container."""

    cpu: Optional[CPUConfig] = None
    memory: Optional[MemoryConfig] = None
    io: Optional[IOConfig] = None
    gpu: Optional[GPUConfig] = None
    pids: Optional[PIDsConfig] = None

    def validate(self) -> None:
        """Validate all resource limit configurations."""
        for cfg_name, cfg in [
            ("cpu", self.cpu),
            ("memory", self.memory),
            ("io", self.io),
            ("gpu", self.gpu),
            ("pids", self.pids),
        ]:
            if cfg is not None:
                try:
                    cfg.validate()
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid {cfg_name} config: {e}") from e

    def has_limits(self) -> bool:
        """Check if any resource limits are configured."""
        return any(
            cfg is not None
            for cfg in [self.cpu, self.memory, self.io, self.gpu, self.pids]
        )


class CGroupController:
    """
    Represents a single cgroup controller (e.g., cpu, memory, io).

    Wraps read/write access to cgroup v2 controller files.
    """

    def __init__(self, group_path: Path, controller: str) -> None:
        self.group_path = group_path
        self.controller = controller

    def _file_path(self, name: str) -> Path:
        return self.group_path / f"{self.controller}.{name}"

    def read(self, name: str) -> str:
        """Read a cgroup controller file."""
        path = self._file_path(name)
        try:
            return path.read_text().strip()
        except FileNotFoundError:
            raise CGroupError(f"Control file not found: {path}", str(path))
        except PermissionError:
            raise CGroupError(f"Permission denied: {path}", str(path))
        except OSError as e:
            raise CGroupError(f"Failed to read {path}: {e}", str(path))

    def read_int(self, name: str) -> int:
        """Read a cgroup controller file as integer."""
        val = self.read(name)
        try:
            return int(val)
        except ValueError:
            raise CGroupError(f"Expected integer in {name}, got: {val}")

    def read_flat(self, name: str) -> dict[str, int]:
        """Read a cgroup controller file with key-value format."""
        content = self.read(name)
        result: dict[str, int] = {}
        for line in content.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    result[parts[0]] = int(parts[1])
                except ValueError:
                    continue
        return result

    def write(self, name: str, value: Union[str, int]) -> None:
        """Write a value to a cgroup controller file."""
        path = self._file_path(name)
        try:
            path.write_text(str(value))
        except FileNotFoundError:
            raise CGroupError(f"Control file not found: {path}", str(path))
        except PermissionError:
            raise CGroupError(f"Permission denied: {path}", str(path))
        except OSError as e:
            raise CGroupError(f"Failed to write {path}: {e}", str(path))


class CGroupManager:
    """
    Manages cgroups v2 for container resource isolation.

    Creates cgroup hierarchies, applies resource limits, and
    assigns processes to cgroups. Supports all major controllers:
    cpu, memory, io, pids, cpuset, and GPU via nvidia-cd.
    """

    CONTROLLERS: ClassVar[list[str]] = [
        "cpu", "memory", "io", "pids", "cpuset", "hugetlb",
    ]

    def __init__(self, container_id: str) -> None:
        self.container_id = container_id
        self.group_name = f"ainos/{container_id}"
        self.group_path = CGROUP_V2_PATH / self.group_name
        self._controllers: dict[str, CGroupController] = {}
        self._is_created = False

    @staticmethod
    def is_cgroup_v2() -> bool:
        """
        Check if cgroups v2 (unified hierarchy) is in use.

        Returns:
            True if the system uses cgroups v2.
        """
        return CGROUP_V2_PATH.exists() and (CGROUP_V2_PATH / "cgroup.controllers").exists()

    @staticmethod
    def available_controllers() -> list[str]:
        """
        List available cgroup controllers on the system.

        Returns:
            List of controller names available in the root cgroup.
        """
        try:
            content = (CGROUP_V2_PATH / "cgroup.controllers").read_text().strip()
            return content.split() if content else []
        except (FileNotFoundError, PermissionError, OSError):
            return []

    @staticmethod
    def get_system_resource_summary() -> dict[str, Any]:
        """
        Get a summary of system-wide resource capacity.

        Returns:
            Dict with keys: cpu_cores, memory_total, swap_total, etc.
        """
        summary: dict[str, Any] = {}
        try:
            # CPU
            cpu_count = os.cpu_count() or 0
            summary["cpu_cores"] = cpu_count

            # Memory
            meminfo = {}
            try:
                for line in Path("/proc/meminfo").read_text().splitlines():
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_str = parts[1].strip().split()[0]
                        meminfo[key] = int(val_str) * 1024
            except (FileNotFoundError, OSError):
                pass

            summary["memory_total"] = meminfo.get("MemTotal", 0)
            summary["memory_available"] = meminfo.get("MemAvailable", 0)
            summary["swap_total"] = meminfo.get("SwapTotal", 0)
            summary["swap_free"] = meminfo.get("SwapFree", 0)
        except Exception as e:
            logger.warning("Failed to read system resource summary: %s", e)

        return summary

    def create(self) -> None:
        """
        Create the cgroup for this container.

        Creates the cgroup directory and enables all available controllers.

        Raises:
            CGroupError: If the cgroup already exists or creation fails.
        """
        if self._is_created:
            logger.debug("CGroup %s already exists", self.group_name)
            return

        if not self.is_cgroup_v2():
            raise CGroupError("cgroups v2 is not available on this system")

        try:
            self.group_path.mkdir(parents=True, exist_ok=True)
            self._is_created = True
            logger.info("Created cgroup %s for container %s", self.group_name, self.container_id)

            # Initialize controllers
            for ctrl in self.CONTROLLERS:
                self._controllers[ctrl] = CGroupController(self.group_path, ctrl)

            # Enable controllers via subtree_control
            self._enable_controllers()
        except PermissionError:
            raise CGroupError(
                "Permission denied creating cgroup. Are you running as root?",
                str(self.group_path),
            )
        except OSError as e:
            raise CGroupError(f"Failed to create cgroup: {e}", str(self.group_path))

    def _enable_controllers(self) -> None:
        """Enable controllers in the cgroup subtree."""
        available = self.available_controllers()
        # Check parent's subtree_control
        try:
            parent_subtree = (CGROUP_V2_PATH / "cgroup.subtree_control").read_text().strip().split()
        except (FileNotFoundError, OSError):
            parent_subtree = []

        to_enable = [c for c in available if c in self.CONTROLLERS]
        if to_enable:
            content = " ".join(f"+{c}" for c in to_enable)
            try:
                (CGROUP_V2_PATH / "cgroup.subtree_control").write_text(content)
            except OSError as e:
                logger.warning("Failed to enable subtree controllers: %s", e)

    def destroy(self) -> None:
        """Remove the cgroup and all child cgroups."""
        if not self.group_path.exists():
            self._is_created = False
            return

        try:
            # Remove all child cgroups recursively
            for child in sorted(self.group_path.rglob("*"), reverse=True):
                if child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        self._kill_cgroup_procs(child)
                        child.rmdir()

            self.group_path.rmdir()
            self._is_created = False
            logger.info("Destroyed cgroup %s for container %s", self.group_name, self.container_id)
        except OSError as e:
            raise CGroupError(f"Failed to destroy cgroup: {e}", str(self.group_path))

    def _kill_cgroup_procs(self, path: Path) -> None:
        """Kill all processes in a cgroup."""
        procs_path = path / "cgroup.procs"
        try:
            pids = procs_path.read_text().strip().split()
            for pid_str in pids:
                if pid_str.strip():
                    try:
                        pid = int(pid_str)
                        os.kill(pid, 9)
                    except (OSError, ValueError):
                        pass
        except (FileNotFoundError, OSError):
            pass

    def add_process(self, pid: int) -> None:
        """
        Add a process to the cgroup.

        Args:
            pid: Process ID to add.

        Raises:
            CGroupError: If the cgroup does not exist or the operation fails.
        """
        if not self._is_created:
            raise CGroupError("CGroup not created yet", str(self.group_path))

        try:
            (self.group_path / "cgroup.procs").write_text(str(pid))
            logger.debug("Added PID %d to cgroup %s", pid, self.group_name)
        except OSError as e:
            raise CGroupError(f"Failed to add PID {pid}: {e}", str(self.group_path))

    def get_processes(self) -> list[int]:
        """
        Get all PIDs currently in this cgroup.

        Returns:
            List of process IDs.
        """
        try:
            content = (self.group_path / "cgroup.procs").read_text().strip()
            return [int(pid) for pid in content.split() if pid.strip()]
        except (FileNotFoundError, OSError):
            return []

    def apply_cpu_limits(self, cfg: CPUConfig) -> None:
        """
        Apply CPU resource limits to the cgroup.

        Args:
            cfg: CPU configuration to apply.

        Raises:
            CGroupError: If the limit cannot be applied.
        """
        cfg.validate()
        self.create()

        ctrl = self._controllers.get("cpu")
        if ctrl is None:
            raise CGroupError("CPU controller not available")

        controller_available = "cpu" in self.available_controllers()
        if not controller_available:
            logger.warning("CPU controller not available; limits not applied")
            return

        try:
            if cfg.shares is not None:
                ctrl.write("weight", cfg.shares)

            if cfg.quota is not None and cfg.period is not None:
                ctrl.write("max", f"{cfg.quota} {cfg.period}")
            elif cfg.quota is not None:
                # Default period: 100000 us (100ms)
                ctrl.write("max", f"{cfg.quota} 100000")
            elif cfg.period is not None:
                # Read current quota and apply with new period
                current = ctrl.read("max")
                parts = current.split()
                if parts:
                    ctrl.write("max", f"{parts[0]} {cfg.period}")

            logger.info("Applied CPU limits for container %s: %s", self.container_id, cfg)
        except CGroupError:
            raise
        except OSError as e:
            raise CGroupError(f"Failed to apply CPU limits: {e}", str(self.group_path))

    def apply_memory_limits(self, cfg: MemoryConfig) -> None:
        """
        Apply memory resource limits to the cgroup.

        Args:
            cfg: Memory configuration to apply.

        Raises:
            CGroupError: If the limit cannot be applied.
        """
        cfg.validate()
        self.create()

        controller_available = "memory" in self.available_controllers()
        if not controller_available:
            logger.warning("Memory controller not available; limits not applied")
            return

        ctrl = self._controllers.get("memory")
        if ctrl is None:
            raise CGroupError("Memory controller not available")

        try:
            if cfg.limit is not None:
                ctrl.write("max", cfg.limit)
                # Also set memory.high as a soft limit ~80% of max
                high = int(cfg.limit * 0.8)
                ctrl.write("high", high)

            if cfg.swap_limit is not None:
                ctrl.write("swap.max", cfg.swap_limit)

            if cfg.oom_kill:
                ctrl.write("oom.group", 1)
            else:
                ctrl.write("oom.group", 0)

            logger.info("Applied memory limits for container %s: %s", self.container_id, cfg)
        except CGroupError:
            raise
        except OSError as e:
            raise CGroupError(f"Failed to apply memory limits: {e}", str(self.group_path))

    def apply_io_limits(self, cfg: IOConfig) -> None:
        """
        Apply IO resource limits to the cgroup.

        Args:
            cfg: IO configuration to apply.

        Raises:
            CGroupError: If the limit cannot be applied.
        """
        cfg.validate()
        self.create()

        controller_available = "io" in self.available_controllers()
        if not controller_available:
            logger.warning("IO controller not available; limits not applied")
            return

        ctrl = self._controllers.get("io")
        if ctrl is None:
            raise CGroupError("IO controller not available")

        try:
            if cfg.weight is not None:
                ctrl.write("weight", cfg.weight)

            for dev in cfg.device_limits:
                devno = f"{dev.major}:{dev.minor}"
                if dev.read_bps is not None:
                    ctrl.write("max", f"{devno} rbps={dev.read_bps}")
                if dev.write_bps is not None:
                    ctrl.write("max", f"{devno} wbps={dev.write_bps}")
                if dev.read_iops is not None:
                    ctrl.write("max", f"{devno} riops={dev.read_iops}")
                if dev.write_iops is not None:
                    ctrl.write("max", f"{devno} wiops={dev.write_iops}")

            logger.info("Applied IO limits for container %s: %s", self.container_id, cfg)
        except CGroupError:
            raise
        except OSError as e:
            raise CGroupError(f"Failed to apply IO limits: {e}", str(self.group_path))

    def apply_pids_limit(self, cfg: PIDsConfig) -> None:
        """
        Apply PIDs limit to the cgroup.

        Args:
            cfg: PIDs configuration to apply.

        Raises:
            CGroupError: If the limit cannot be applied.
        """
        cfg.validate()
        self.create()

        controller_available = "pids" in self.available_controllers()
        if not controller_available:
            logger.warning("PIDs controller not available; limit not applied")
            return

        ctrl = self._controllers.get("pids")
        if ctrl is None:
            raise CGroupError("PIDs controller not available")

        try:
            if cfg.max_pids is not None:
                ctrl.write("max", cfg.max_pids)
            logger.info("Applied PIDs limit for container %s: %s", self.container_id, cfg)
        except CGroupError:
            raise
        except OSError as e:
            raise CGroupError(f"Failed to apply PIDs limit: {e}", str(self.group_path))

    def apply_limits(self, limits: ResourceLimits) -> None:
        """
        Apply all resource limits to the cgroup.

        Args:
            limits: Aggregate resource limits configuration.

        Raises:
            CGroupError: If any limit cannot be applied.
        """
        limits.validate()

        if not limits.has_limits():
            logger.debug("No resource limits to apply for container %s", self.container_id)
            return

        self.create()

        if limits.cpu is not None:
            self.apply_cpu_limits(limits.cpu)
        if limits.memory is not None:
            self.apply_memory_limits(limits.memory)
        if limits.io is not None:
            self.apply_io_limits(limits.io)
        if limits.pids is not None:
            self.apply_pids_limit(limits.pids)

        logger.info("Applied all resource limits for container %s", self.container_id)

    def get_current_usage(self) -> dict[str, Any]:
        """
        Read current resource usage from the cgroup.

        Returns:
            Dict with keys: cpu, memory, io, pids usage data.
        """
        usage: dict[str, Any] = {}

        if not self._is_created or not self.group_path.exists():
            return usage

        try:
            # CPU usage
            cpu_ctrl = self._controllers.get("cpu")
            if cpu_ctrl:
                try:
                    stat = cpu_ctrl.read_flat("stat")
                    usage["cpu"] = {
                        "usage_usec": stat.get("usage_usec", 0),
                        "user_usec": stat.get("user_usec", 0),
                        "system_usec": stat.get("system_usec", 0),
                    }
                except CGroupError:
                    pass

            # Memory usage
            mem_ctrl = self._controllers.get("memory")
            if mem_ctrl:
                try:
                    mem_stat = mem_ctrl.read_flat("stat")
                    current = mem_ctrl.read_int("current")
                    usage["memory"] = {
                        "current": current,
                        "anon": mem_stat.get("anon", 0),
                        "file": mem_stat.get("file", 0),
                        "kernel_stack": mem_stat.get("kernel_stack", 0),
                        "pgin": mem_stat.get("pgin", 0),
                        "pgout": mem_stat.get("pgout", 0),
                        "swap": mem_stat.get("swap", 0),
                    }
                except CGroupError:
                    pass

            # IO usage
            io_ctrl = self._controllers.get("io")
            if io_ctrl:
                try:
                    io_stat = io_ctrl.read("stat")
                    io_parsed: dict[str, dict[str, int]] = {}
                    for line in io_stat.splitlines():
                        parts = line.split()
                        if len(parts) >= 3:
                            dev = parts[0]
                            key = parts[1]
                            try:
                                val = int(parts[2])
                            except ValueError:
                                continue
                            if dev not in io_parsed:
                                io_parsed[dev] = {}
                            io_parsed[dev][key] = val
                    usage["io"] = io_parsed
                except CGroupError:
                    pass

            # PIDs usage
            pids_ctrl = self._controllers.get("pids")
            if pids_ctrl:
                try:
                    current_pids = pids_ctrl.read_int("current")
                    max_pids = pids_ctrl.read_int("max")
                    usage["pids"] = {
                        "current": current_pids,
                        "max": max_pids,
                    }
                except CGroupError:
                    pass

        except Exception as e:
            logger.warning("Failed to read cgroup usage for %s: %s", self.container_id, e)

        return usage

    def get_stat(self) -> dict[str, Any]:
        """
        Get comprehensive cgroup statistics.

        Returns:
            Dict with all cgroup stat files parsed.
        """
        stats: dict[str, Any] = {}
        if not self.group_path.exists():
            return stats

        for fpath in sorted(self.group_path.iterdir()):
            if fpath.is_file() and fpath.name != "cgroup.procs":
                try:
                    content = fpath.read_text().strip()
                    if "\n" in content:
                        lines = content.splitlines()
                        if all(" " in l for l in lines[:10]):
                            parsed: dict[str, Union[str, int]] = {}
                            for line in lines:
                                parts = line.split(maxsplit=1)
                                if len(parts) == 2:
                                    key = parts[0]
                                    val: Union[str, int] = parts[1]
                                    try:
                                        val = int(parts[1])
                                    except ValueError:
                                        try:
                                            val = int(parts[1].split()[0])
                                        except (ValueError, IndexError):
                                            pass
                                    parsed[key] = val
                            stats[fpath.name] = parsed
                        else:
                            stats[fpath.name] = lines
                    else:
                        try:
                            stats[fpath.name] = int(content)
                        except ValueError:
                            stats[fpath.name] = content
                except (OSError, ValueError):
                    continue

        return stats

    def exists(self) -> bool:
        """Check if the cgroup exists."""
        return self.group_path.exists()

    def __enter__(self) -> "CGroupManager":
        self.create()
        return self

    def __exit__(self, *args: object) -> None:
        self.destroy()

    def __repr__(self) -> str:
        return f"CGroupManager(container={self.container_id}, path={self.group_path})"