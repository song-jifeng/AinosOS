"""
命名空间隔离模块 - Linux namespace isolation for Ainos containers.

支持以下命名空间类型:
- PID: 进程隔离
- Network: 网络栈隔离
- Mount: 挂载点隔离
- UTS: 主机名隔离
- IPC: 进程间通信隔离
- User: 用户 ID 隔离
- CGroup: cgroup 隔离
"""

import ctypes
import ctypes.util
import os
import logging
from enum import Enum, auto
from pathlib import Path
from typing import ClassVar, Optional

logger = logging.getLogger(__name__)


class NamespaceType(Enum):
    """Linux namespace types supported by the runtime."""

    PID = auto()
    NETWORK = auto()
    MOUNT = auto()
    UTS = auto()
    IPC = auto()
    USER = auto()
    CGROUP = auto()

    @property
    def clone_flag(self) -> int:
        """Return the corresponding clone(2) flag for this namespace type."""
        flags: dict[NamespaceType, int] = {
            NamespaceType.PID: 0x20000000,      # CLONE_NEWPID
            NamespaceType.NETWORK: 0x40000000,  # CLONE_NEWNET
            NamespaceType.MOUNT: 0x00020000,    # CLONE_NEWNS
            NamespaceType.UTS: 0x04000000,      # CLONE_NEWUTS
            NamespaceType.IPC: 0x08000000,      # CLONE_NEWIPC
            NamespaceType.USER: 0x10000000,     # CLONE_NEWUSER
            NamespaceType.CGROUP: 0x02000000,   # CLONE_NEWCGROUP
        }
        return flags[self]

    @property
    def ns_name(self) -> str:
        """Return the namespace name as used in /proc/<pid>/ns/."""
        names: dict[NamespaceType, str] = {
            NamespaceType.PID: "pid",
            NamespaceType.NETWORK: "net",
            NamespaceType.MOUNT: "mnt",
            NamespaceType.UTS: "uts",
            NamespaceType.IPC: "ipc",
            NamespaceType.USER: "user",
            NamespaceType.CGROUP: "cgroup",
        }
        return names[self]


class NamespaceError(RuntimeError):
    """Raised when a namespace operation fails."""

    def __init__(self, message: str, ns_type: Optional[NamespaceType] = None) -> None:
        self.ns_type = ns_type
        super().__init__(f"Namespace{'[' + ns_type.name + '] ' if ns_type else ' '}{message}")


class NamespaceHandle:
    """
    A handle to an existing Linux namespace.

    Wraps a file descriptor referencing a namespace in /proc/<pid>/ns/.
    """

    def __init__(self, path: str, ns_type: NamespaceType) -> None:
        self.path = path
        self.ns_type = ns_type
        self._fd: Optional[int] = None

    def open(self) -> None:
        """Open the namespace file descriptor."""
        if self._fd is not None:
            return
        try:
            fd = os.open(self.path, os.O_RDONLY)
            self._fd = fd
        except OSError as e:
            raise NamespaceError(
                f"Failed to open namespace {self.path}: {e}", self.ns_type
            ) from e

    def close(self) -> None:
        """Close the namespace file descriptor if open."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError as e:
                logger.warning("Error closing namespace fd: %s", e)
            finally:
                self._fd = None

    def __enter__(self) -> "NamespaceHandle":
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class NamespaceManager:
    """
    Manages Linux namespace creation and joining for container isolation.

    Provides methods to create namespaces, enter existing ones, and
    configure the isolation level for a container.
    """

    # Linux syscall numbers (x86_64)
    _SYS_setns: ClassVar[int] = 308
    _SYS_unshare: ClassVar[int] = 272
    _SYS_clone: ClassVar[int] = 56

    def __init__(self, container_id: str) -> None:
        self.container_id = container_id
        self._active_namespaces: dict[NamespaceType, NamespaceHandle] = {}
        self._supported_types: list[NamespaceType] = list(NamespaceType)

    @staticmethod
    def _check_cap_sys_admin() -> bool:
        """Check if the process has CAP_SYS_ADMIN (required for namespace ops)."""
        try:
            return os.geteuid() == 0
        except Exception:
            return False

    @staticmethod
    def _nsenter_syscall(fd: int) -> None:
        """
        Call setns(2) to join an existing namespace.

        Args:
            fd: File descriptor referencing the namespace.

        Raises:
            NamespaceError: If the setns call fails.
        """
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        result = libc.syscall(NamespaceManager._SYS_setns, ctypes.c_int(fd), ctypes.c_int(0))
        if result != 0:
            errno = ctypes.get_errno()
            raise NamespaceError(
                f"setns failed (errno={errno}): {os.strerror(errno)}"
            )

    @staticmethod
    def _unshare_syscall(flags: int) -> None:
        """
        Call unshare(2) to create new namespaces for the current process.

        Args:
            flags: Bitwise OR of CLONE_NEW* flags.

        Raises:
            NamespaceError: If the unshare call fails.
        """
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        result = libc.syscall(NamespaceManager._SYS_unshare, ctypes.c_int(flags))
        if result != 0:
            errno = ctypes.get_errno()
            raise NamespaceError(
                f"unshare failed (errno={errno}): {os.strerror(errno)}"
            )

    def create_namespaces(self, types: list[NamespaceType]) -> None:
        """
        Create new namespaces for the current process using unshare(2).

        Args:
            types: List of namespace types to create.

        Raises:
            NamespaceError: If creation fails or required privileges are missing.
        """
        if not self._check_cap_sys_admin():
            raise NamespaceError(
                "Creating namespaces requires CAP_SYS_ADMIN or root privileges"
            )

        flags = 0
        for ns_type in types:
            flags |= ns_type.clone_flag
            logger.debug(
                "Creating namespace %s for container %s",
                ns_type.name, self.container_id,
            )

        self._unshare_syscall(flags)
        logger.info(
            "Created namespaces %s for container %s",
            [t.name for t in types], self.container_id,
        )

    def join_namespace(self, pid: int, ns_type: NamespaceType) -> None:
        """
        Join an existing namespace of a target process.

        Args:
            pid: Process ID of the target process.
            ns_type: Type of namespace to join.

        Raises:
            NamespaceError: If the namespace path does not exist or setns fails.
        """
        ns_path = f"/proc/{pid}/ns/{ns_type.ns_name}"
        if not os.path.exists(ns_path):
            raise NamespaceError(
                f"Namespace path {ns_path} does not exist", ns_type
            )

        handle = NamespaceHandle(ns_path, ns_type)
        with handle:
            self._nsenter_syscall(handle._fd)  # type: ignore[arg-type]
            self._active_namespaces[ns_type] = handle

        logger.debug(
            "Joined namespace %s (pid=%d) for container %s",
            ns_type.name, pid, self.container_id,
        )

    def join_all_namespaces(self, pid: int) -> None:
        """
        Join all available namespaces of a target process.

        Args:
            pid: Process ID of the target process.

        Raises:
            NamespaceError: If any namespace join fails.
        """
        for ns_type in self._supported_types:
            try:
                self.join_namespace(pid, ns_type)
            except NamespaceError as e:
                logger.warning(
                    "Could not join namespace %s for pid %d: %s",
                    ns_type.name, pid, e,
                )

    def get_self_namespace(self, ns_type: NamespaceType) -> Optional[str]:
        """
        Get the inode of the current process's namespace.

        Args:
            ns_type: Type of namespace to inspect.

        Returns:
            The namespace inode as a string, or None if unavailable.
        """
        ns_path = f"/proc/self/ns/{ns_type.ns_name}"
        try:
            return os.readlink(ns_path)
        except OSError as e:
            logger.error("Cannot read namespace %s: %s", ns_path, e)
            return None

    def get_container_namespaces(self, pid: int) -> dict[str, str]:
        """
        Get all namespace inodes for a given process.

        Args:
            pid: Process ID to inspect.

        Returns:
            Dictionary mapping namespace type names to their inodes.
        """
        namespaces: dict[str, str] = {}
        for ns_type in self._supported_types:
            ns_path = f"/proc/{pid}/ns/{ns_type.ns_name}"
            try:
                inode = os.readlink(ns_path)
                namespaces[ns_type.name.lower()] = inode
            except OSError:
                continue
        return namespaces

    def is_in_same_namespace(self, pid: int, ns_type: NamespaceType) -> bool:
        """
        Check if the current process is in the same namespace as the target process.

        Args:
            pid: Target process ID.
            ns_type: Namespace type to compare.

        Returns:
            True if both processes share the same namespace.
        """
        self_ns = self.get_self_namespace(ns_type)
        if self_ns is None:
            return False
        target_ns_path = f"/proc/{pid}/ns/{ns_type.ns_name}"
        try:
            target_ns = os.readlink(target_ns_path)
            return self_ns == target_ns
        except OSError:
            return False

    def cleanup(self) -> None:
        """Close all active namespace handles."""
        for ns_type, handle in self._active_namespaces.items():
            logger.debug("Cleaning up namespace %s for container %s", ns_type.name, self.container_id)
            handle.close()
        self._active_namespaces.clear()

    @staticmethod
    def get_current_ns_inodes() -> dict[str, str]:
        """
        Get namespace inodes for the current process.

        Returns:
            Dict mapping namespace type names to their inode strings.
        """
        inodes: dict[str, str] = {}
        base = "/proc/self/ns/"
        for entry in os.listdir(base):
            try:
                link = os.readlink(os.path.join(base, entry))
                inodes[entry] = link
            except OSError:
                continue
        return inodes

    @staticmethod
    def get_namespace_for_pid(pid: int, ns_type: NamespaceType) -> Optional[str]:
        """
        Resolve a namespace inode for a given PID.

        Args:
            pid: Process ID.
            ns_type: Namespace type.

        Returns:
            Inode string or None if inaccessible.
        """
        path = f"/proc/{pid}/ns/{ns_type.ns_name}"
        try:
            return os.readlink(path)
        except OSError:
            return None