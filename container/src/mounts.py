"""
挂载管理模块 - Mount management for Ainos containers.

处理容器挂载点管理，包括:
- 绑定挂载
- 临时文件系统 (tmpfs)
- proc/sysfs 挂载
- 设备挂载
- 挂载传播
"""

import enum
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


class MountType(enum.Enum):
    """Types of filesystem mounts."""

    BIND = "bind"
    TMPFS = "tmpfs"
    PROC = "proc"
    SYSFS = "sysfs"
    DEVTMPFS = "devtmpfs"
    DEVPTS = "devpts"
    MQUEUE = "mqueue"
    SHM = "shm"
    CGROUP = "cgroup"
    CGROUP2 = "cgroup2"
    OVERLAY = "overlay"


class MountPropagation(enum.Enum):
    """Mount propagation modes."""

    PRIVATE = "private"
    SHARED = "shared"
    SLAVE = "slave"
    UNBINDABLE = "unbindable"

    @property
    def mount_flag(self) -> int:
        flags = {
            MountPropagation.PRIVATE: 0x00020000,      # MS_PRIVATE
            MountPropagation.SHARED: 0x10000000,       # MS_SHARED
            MountPropagation.SLAVE: 0x08000000,        # MS_SLAVE
            MountPropagation.UNBINDABLE: 0x04000000,   # MS_UNBINDABLE
        }
        return flags[self]


class MountError(Exception):
    """Raised when a mount operation fails."""

    def __init__(self, message: str, source: Optional[str] = None, target: Optional[str] = None) -> None:
        self.source = source
        self.target = target
        path_info = ""
        if source and target:
            path_info = f" ({source} -> {target})"
        elif target:
            path_info = f" (target: {target})"
        super().__init__(f"Mount error{path_info}: {message}")


@dataclass
class MountPoint:
    """Represents a single mount point in a container."""

    source: str
    target: str
    fstype: str = "none"
    options: str = ""
    mount_type: MountType = MountType.BIND
    propagation: MountPropagation = MountPropagation.PRIVATE
    read_only: bool = False
    create_target: bool = True
    copy_from_source: bool = False
    label: Optional[str] = None

    def validate(self) -> None:
        """Validate mount point configuration."""
        if not self.target:
            raise ValueError("Mount target must not be empty")
        if self.mount_type == MountType.BIND and not self.source:
            raise ValueError("Bind mount requires a source")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "source": self.source,
            "target": self.target,
            "fstype": self.fstype,
            "options": self.options,
            "mount_type": self.mount_type.value,
            "propagation": self.propagation.value,
            "read_only": self.read_only,
            "create_target": self.create_target,
            "copy_from_source": self.copy_from_source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MountPoint":
        """Create from dictionary."""
        return cls(
            source=data.get("source", ""),
            target=data["target"],
            fstype=data.get("fstype", "none"),
            options=data.get("options", ""),
            mount_type=MountType(data.get("mount_type", "bind")),
            propagation=MountPropagation(data.get("propagation", "private")),
            read_only=data.get("read_only", False),
            create_target=data.get("create_target", True),
            copy_from_source=data.get("copy_from_source", False),
        )


class MountManager:
    """
    Manages container mount points.

    Handles setting up, configuring, and tearing down all mounts
    within a container's mount namespace.
    """

    # Standard container mounts
    DEFAULT_MOUNTS: ClassVar[list[MountPoint]] = [
        MountPoint(
            source="proc",
            target="/proc",
            fstype="proc",
            mount_type=MountType.PROC,
            options="nosuid,noexec,nodev",
        ),
        MountPoint(
            source="sysfs",
            target="/sys",
            fstype="sysfs",
            mount_type=MountType.SYSFS,
            options="nosuid,noexec,nodev,ro",
        ),
        MountPoint(
            source="devtmpfs",
            target="/dev",
            fstype="devtmpfs",
            mount_type=MountType.DEVTMPFS,
            options="nosuid,noexec,strictatime,mode=755",
        ),
        MountPoint(
            source="devpts",
            target="/dev/pts",
            fstype="devpts",
            mount_type=MountType.DEVPTS,
            options="nosuid,noexec,newinstance,ptmxmode=0666,mode=620,gid=5",
        ),
        MountPoint(
            source="shm",
            target="/dev/shm",
            fstype="tmpfs",
            mount_type=MountType.SHM,
            options="nosuid,noexec,nodev,size=65536k",
        ),
        MountPoint(
            source="mqueue",
            target="/dev/mqueue",
            fstype="mqueue",
            mount_type=MountType.MQUEUE,
            options="nosuid,noexec,nodev",
        ),
    ]

    def __init__(self, container_id: str, rootfs: str) -> None:
        self.container_id = container_id
        self.rootfs = rootfs
        self._mounted: list[MountPoint] = []

    def _resolve_target(self, target: str) -> str:
        """Resolve a mount target relative to the container rootfs."""
        # Remove leading slash and join with rootfs
        clean_target = target.lstrip("/")
        return os.path.join(self.rootfs, clean_target)

    def _ensure_target_dir(self, target: str) -> None:
        """Ensure the target directory exists."""
        try:
            Path(target).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise MountError(f"Failed to create target directory {target}: {e}", target=target)

    def _run_mount(self, mount_point: MountPoint) -> None:
        """
        Execute a mount command.

        Args:
            mount_point: Configuration for the mount.

        Raises:
            MountError: If the mount command fails.
        """
        source = mount_point.source
        target = self._resolve_target(mount_point.target)

        if mount_point.create_target:
            self._ensure_target_dir(target)

        if mount_point.mount_type == MountType.BIND and mount_point.copy_from_source:
            if os.path.isdir(source) and not os.path.exists(target):
                self._ensure_target_dir(target)
            elif os.path.isfile(source):
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).touch(exist_ok=True)

        try:
            cmd = ["mount"]

            if mount_point.mount_type == MountType.BIND:
                cmd.extend(["--bind", source, target])
            elif mount_point.mount_type in (MountType.TMPFS, MountType.SHM):
                cmd.extend(["-t", "tmpfs", "-o", mount_point.options or "size=65536k", "tmpfs", target])
            elif mount_point.mount_type == MountType.PROC:
                cmd.extend(["-t", "proc", "-o", mount_point.options or "nosuid,noexec,nodev", "proc", target])
            elif mount_point.mount_type == MountType.SYSFS:
                cmd.extend(["-t", "sysfs", "-o", mount_point.options or "nosuid,noexec,nodev,ro", "sysfs", target])
            elif mount_point.mount_type == MountType.DEVTMPFS:
                cmd.extend(["-t", "devtmpfs", "-o", mount_point.options or "nosuid,strictatime,mode=755", "devtmpfs", target])
            elif mount_point.mount_type == MountType.DEVPTS:
                cmd.extend(["-t", "devpts", "-o", mount_point.options or "nosuid,noexec,newinstance,ptmxmode=0666,mode=620,gid=5", "devpts", target])
            elif mount_point.mount_type == MountType.MQUEUE:
                cmd.extend(["-t", "mqueue", "-o", mount_point.options or "nosuid,noexec,nodev", "mqueue", target])
            elif mount_point.mount_type == MountType.CGROUP:
                cmd.extend(["-t", "cgroup", "-o", mount_point.options, "cgroup", target])
            elif mount_point.mount_type == MountType.CGROUP2:
                cmd.extend(["-t", "cgroup2", "-o", mount_point.options or "nsdelegate", "cgroup2", target])
            else:
                cmd.extend(["-t", mount_point.fstype, "-o", mount_point.options, source, target])

            if mount_point.read_only and mount_point.mount_type == MountType.BIND:
                cmd = ["mount", "--bind", "-o", "remount,ro,bind", source, target]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                raise MountError(
                    f"Mount failed: {result.stderr.strip()}",
                    source=source, target=target,
                )

            # Set propagation
            if mount_point.propagation != MountPropagation.PRIVATE:
                prop_flag = mount_point.propagation.mount_flag
                subprocess.run(
                    ["mount", "--make-" + mount_point.propagation.value, target],
                    capture_output=True, timeout=5, check=False,
                )

            self._mounted.append(mount_point)
            logger.debug("Mounted %s -> %s", source, target)

        except OSError as e:
            raise MountError(
                f"System error during mount: {e}", source=source, target=target
            ) from e

    def setup_default_mounts(self) -> list[MountPoint]:
        """
        Mount the default container filesystems (proc, sysfs, dev, etc.).

        Returns:
            List of successfully mounted mount points.
        """
        mounted: list[MountPoint] = []
        for mp in self.DEFAULT_MOUNTS:
            try:
                self._run_mount(mp)
                mounted.append(mp)
            except MountError as e:
                logger.warning("Failed to mount %s: %s", mp.target, e)

        logger.info("Set up %d default mounts for container %s", len(mounted), self.container_id)
        return mounted

    def mount_bind(self, source: str, target: str, read_only: bool = False) -> MountPoint:
        """
        Create a bind mount.

        Args:
            source: Host path to bind.
            target: Container path.
            read_only: Whether to mount read-only.

        Returns:
            The created MountPoint.

        Raises:
            MountError: If the bind mount fails.
        """
        mp = MountPoint(
            source=source,
            target=target,
            mount_type=MountType.BIND,
            read_only=read_only,
            create_target=True,
        )
        mp.validate()
        self._run_mount(mp)
        return mp

    def mount_tmpfs(self, target: str, size: str = "65536k", options: str = "") -> MountPoint:
        """
        Mount a tmpfs filesystem.

        Args:
            target: Container path.
            size: Size specification (e.g., '128m', '1g').
            options: Additional mount options.

        Returns:
            The created MountPoint.
        """
        opts = f"size={size}"
        if options:
            opts = f"{opts},{options}"

        mp = MountPoint(
            source="tmpfs",
            target=target,
            fstype="tmpfs",
            mount_type=MountType.TMPFS,
            options=opts,
        )
        self._run_mount(mp)
        return mp

    def mount_individual(self, mount_point: MountPoint) -> None:
        """
        Mount a single mount point.

        Args:
            mount_point: The mount point configuration.
        """
        mount_point.validate()
        self._run_mount(mount_point)

    def mount_all(self, mount_points: list[MountPoint]) -> list[MountPoint]:
        """
        Mount multiple mount points.

        Args:
            mount_points: List of mount point configurations.

        Returns:
            List of successfully mounted mount points.
        """
        mounted: list[MountPoint] = []
        for mp in mount_points:
            try:
                self.mount_individual(mp)
                mounted.append(mp)
            except MountError as e:
                logger.warning("Failed to mount %s: %s", mp.target, e)
        return mounted

    def unmount(self, target: str) -> None:
        """
        Unmount a specific mount point.

        Args:
            target: The container mount target.
        """
        full_target = self._resolve_target(target)
        if not os.path.ismount(full_target):
            logger.debug("Not a mount point: %s", full_target)
            return

        try:
            subprocess.run(
                ["umount", "-l", full_target],
                check=True, capture_output=True, timeout=10,
            )
            logger.debug("Unmounted %s", full_target)
        except subprocess.CalledProcessError as e:
            raise MountError(f"Failed to unmount {full_target}: {e.stderr.strip()}", target=target)
        except OSError as e:
            raise MountError(f"System error during unmount: {e}", target=target)

    def unmount_all(self, reverse: bool = True) -> None:
        """
        Unmount all mounted points.

        Args:
            reverse: If True, unmount in reverse order.
        """
        mounts = reversed(self._mounted) if reverse else self._mounted
        errors = 0
        for mp in mounts:
            try:
                self.unmount(mp.target)
            except MountError as e:
                logger.warning("Error unmounting %s: %s", mp.target, e)
                errors += 1

        self._mounted.clear()
        if errors:
            logger.warning("Unmount all completed with %d errors", errors)
        else:
            logger.info("Unmounted all mounts for container %s", self.container_id)

    def make_private(self) -> None:
        """Make the rootfs mount point private to prevent propagation."""
        try:
            subprocess.run(
                ["mount", "--make-private", self.rootfs],
                check=True, capture_output=True, timeout=5,
            )
            logger.debug("Made rootfs private: %s", self.rootfs)
        except OSError as e:
            logger.warning("Failed to make rootfs private: %s", e)

    def mount_sysfs_cgroup(self) -> None:
        """Mount cgroup filesystem (cgroup v2 preferred)."""
        cgroup_target = self._resolve_target("/sys/fs/cgroup")
        self._ensure_target_dir(cgroup_target)

        if os.path.exists("/sys/fs/cgroup/cgroup.controllers"):
            # cgroup v2
            mp = MountPoint(
                source="cgroup2",
                target="/sys/fs/cgroup",
                fstype="cgroup2",
                mount_type=MountType.CGROUP2,
                options="nsdelegate,memory_recursiveprot",
            )
            self._run_mount(mp)
        else:
            # cgroup v1
            mp = MountPoint(
                source="cgroup",
                target="/sys/fs/cgroup",
                fstype="cgroup",
                mount_type=MountType.CGROUP,
                options="none,name=systemd",
            )
            self._run_mount(mp)

    def get_mount_list(self) -> list[dict[str, str]]:
        """
        Get the list of mounts for this container.

        Returns:
            List of mount info dictionaries.
        """
        mounts: list[dict[str, str]] = []
        for mp in self._mounted:
            mounts.append({
                "source": mp.source,
                "target": mp.target,
                "type": mp.mount_type.value,
                "options": mp.options,
                "read_only": str(mp.read_only),
            })
        return mounts

    def cleanup(self) -> None:
        """Clean up all mounts."""
        self.unmount_all()

    def __enter__(self) -> "MountManager":
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()