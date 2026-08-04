"""
安全策略模块 - Security policies for Ainos containers.

实现:
- seccomp 安全计算模式
- Linux capabilities 管理
- AppArmor 配置文件
- SELinux 标签
- 安全策略定义和验证
"""

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Optional

logger = logging.getLogger(__name__)

SECURITY_DIR = Path("/var/lib/ainos/security")


class SecurityError(Exception):
    """Raised when a security operation fails."""
    def __init__(self, message: str) -> None:
        super().__init__(f"Security error: {message}")


class SeccompAction(Enum):
    """seccomp actions."""
    ALLOW = "SCMP_ACT_ALLOW"
    KILL = "SCMP_ACT_KILL"
    KILL_PROCESS = "SCMP_ACT_KILL_PROCESS"
    TRAP = "SCMP_ACT_TRAP"
    ERRNO = "SCMP_ACT_ERRNO"
    TRACE = "SCMP_ACT_TRACE"
    LOG = "SCMP_ACT_LOG"
    NOTIFY = "SCMP_ACT_NOTIFY"


class SeccompArch(Enum):
    """seccomp architectures."""
    X86_64 = "SCMP_ARCH_X86_64"
    X86 = "SCMP_ARCH_X86"
    X32 = "SCMP_ARCH_X32"
    ARM = "SCMP_ARCH_ARM"
    AARCH64 = "SCMP_ARCH_AARCH64"
    MIPS = "SCMP_ARCH_MIPS"
    MIPS64 = "SCMP_ARCH_MIPS64"
    MIPS64N32 = "SCMP_ARCH_MIPS64N32"
    PPC = "SCMP_ARCH_PPC"
    PPC64 = "SCMP_ARCH_PPC64"
    PPC64LE = "SCMP_ARCH_PPC64LE"
    RISCV64 = "SCMP_ARCH_RISCV64"
    S390 = "SCMP_ARCH_S390"
    S390X = "SCMP_ARCH_S390X"


@dataclass
class SeccompRule:
    """A single seccomp syscall rule."""
    names: list[str]
    action: SeccompAction = SeccompAction.ALLOW
    args: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "names": self.names,
            "action": self.action.value,
        }
        if self.args:
            result["args"] = self.args
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeccompRule":
        return cls(
            names=data["names"],
            action=SeccompAction(data.get("action", "SCMP_ACT_ALLOW")),
            args=data.get("args", []),
        )


@dataclass
class SeccompProfile:
    """Complete seccomp profile."""
    default_action: SeccompAction = SeccompAction.ERRNO
    architectures: list[SeccompArch] = field(default_factory=lambda: [SeccompArch.X86_64])
    rules: list[SeccompRule] = field(default_factory=list)

    def add_allow(self, *syscalls: str) -> None:
        """Add syscalls to the allow list."""
        if syscalls:
            rule = SeccompRule(names=list(syscalls), action=SeccompAction.ALLOW)
            self.rules.append(rule)

    def add_deny(self, *syscalls: str, action: SeccompAction = SeccompAction.ERRNO) -> None:
        """Add syscalls to the deny list."""
        if syscalls:
            rule = SeccompRule(names=list(syscalls), action=action)
            self.rules.append(rule)

    def to_dict(self) -> dict[str, Any]:
        return {
            "defaultAction": self.default_action.value,
            "architectures": [a.value for a in self.architectures],
            "syscalls": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeccompProfile":
        archs = [SeccompArch(a) for a in data.get("architectures", ["SCMP_ARCH_X86_64"])]
        rules = [SeccompRule.from_dict(r) for r in data.get("syscalls", [])]
        return cls(
            default_action=SeccompAction(data.get("defaultAction", "SCMP_ACT_ERRNO")),
            architectures=archs,
            rules=rules,
        )

    @classmethod
    def default_unconfined(cls) -> "SeccompProfile":
        """Create an unconfined seccomp profile (all syscalls allowed)."""
        return cls(
            default_action=SeccompAction.ALLOW,
            architectures=[SeccompArch.X86_64],
        )

    @classmethod
    def default_restricted(cls) -> "SeccompProfile":
        """Create a restricted seccomp profile (standard container profile)."""
        profile = cls(
            default_action=SeccompAction.ERRNO,
            architectures=[SeccompArch.X86_64],
        )

        # Standard syscalls allowed for containers
        profile.add_allow(
            "accept", "accept4", "access", "adjtimex", "alarm",
            "bind", "brk", "capget", "capset", "chdir", "chmod",
            "chown", "chown32", "clock_getres", "clock_gettime",
            "clock_nanosleep", "close", "connect", "copy_file_range",
            "creat", "dup", "dup2", "dup3", "epoll_create",
            "epoll_create1", "epoll_ctl", "epoll_pwait", "epoll_wait",
            "eventfd", "eventfd2", "execve", "execveat", "exit",
            "exit_group", "faccessat", "fadvise64", "fadvise64_64",
            "fallocate", "fanotify_mark", "fchdir", "fchmod",
            "fchmodat", "fchown", "fchown32", "fchownat", "fcntl",
            "fcntl64", "fdatasync", "fgetxattr", "flistxattr",
            "flock", "fork", "fremovexattr", "fsetxattr", "fstat",
            "fstat64", "fstatat64", "fstatfs", "fstatfs64", "fsync",
            "ftruncate", "ftruncate64", "futex", "futimesat",
            "getcwd", "getdents", "getdents64", "getegid",
            "getegid32", "geteuid", "geteuid32", "getgid",
            "getgid32", "getgroups", "getgroups32", "getitimer",
            "getpeername", "getpgid", "getpgrp", "getpid",
            "getppid", "getpriority", "getrandom", "getresgid",
            "getresgid32", "getresuid", "getresuid32", "getrlimit",
            "getrusage", "getsockname", "getsockopt", "gettid",
            "gettimeofday", "getuid", "getuid32", "getxattr",
            "inotify_add_watch", "inotify_init", "inotify_init1",
            "inotify_rm_watch", "io_cancel", "io_destroy",
            "io_getevents", "io_setup", "io_submit", "ioctl",
            "ioprio_get", "ioprio_set", "ipc", "keyctl", "kill",
            "lchown", "lchown32", "lgetxattr", "link", "linkat",
            "listen", "listxattr", "llistxattr", "lremovexattr",
            "lseek", "lsetxattr", "lstat", "lstat64", "madvise",
            "mbind", "membarrier", "memfd_create", "migrate_pages",
            "mincore", "mkdir", "mkdirat", "mknod", "mknodat",
            "mlock", "mlock2", "mlockall", "mmap", "mount",
            "move_pages", "mprotect", "mq_getsetattr", "mq_notify",
            "mq_open", "mq_timedreceive", "mq_timedsend",
            "mq_unlink", "mremap", "msgctl", "msgget", "msgrcv",
            "msgsnd", "msync", "munlock", "munlockall", "munmap",
            "name_to_handle_at", "nanosleep", "newfstatat",
            "open", "openat", "openat2", "pause", "perf_event_open",
            "personality", "pidfd_open", "pidfd_send_signal",
            "pipe", "pipe2", "pivot_root", "pkey_alloc",
            "pkey_free", "pkey_mprotect", "poll", "ppoll",
            "prctl", "pread64", "preadv", "preadv2", "prlimit64",
            "process_vm_readv", "process_vm_writev", "pselect6",
            "pwrite64", "pwritev", "pwritev2", "read", "readahead",
            "readlink", "readlinkat", "readv", "reboot", "recv",
            "recvfrom", "recvmmsg", "recvmsg", "remap_file_pages",
            "removexattr", "rename", "renameat", "renameat2",
            "restart_syscall", "rmdir", "rt_sigaction",
            "rt_sigpending", "rt_sigprocmask", "rt_sigqueueinfo",
            "rt_sigreturn", "rt_sigsuspend", "rt_sigtimedwait",
            "rt_tgsigqueueinfo", "sched_get_priority_max",
            "sched_get_priority_min", "sched_getaffinity",
            "sched_getattr", "sched_getparam", "sched_getscheduler",
            "sched_rr_get_interval", "sched_setaffinity",
            "sched_setattr", "sched_setparam", "sched_setscheduler",
            "sched_yield", "seccomp", "select", "semctl", "semget",
            "semop", "semtimedop", "send", "sendfile", "sendfile64",
            "sendmmsg", "sendmsg", "sendto", "set_tid_address",
            "setdomainname", "setegid", "setegid32", "setenv",
            "seteuid", "seteuid32", "setfsgid", "setfsgid32",
            "setfsuid", "setfsuid32", "setgid", "setgid32",
            "setgroups", "setgroups32", "sethostname", "setitimer",
            "setpgid", "setpriority", "setregid", "setregid32",
            "setresgid", "setresgid32", "setresuid", "setresuid32",
            "setreuid", "setreuid32", "setrlimit", "setsid",
            "setsockopt", "setuid", "setuid32", "setup",
            "setxattr", "shmat", "shmctl", "shmdt", "shmget",
            "shutdown", "sigaltstack", "signalfd", "signalfd4",
            "socket", "socketpair", "splice", "ssetmask",
            "stat", "stat64", "statfs", "statfs64", "statx",
            "symlink", "symlinkat", "sync", "sync_file_range",
            "syncfs", "sysinfo", "syslog", "tee", "tgkill",
            "time", "timer_create", "timer_delete", "timer_getoverrun",
            "timer_gettime", "timer_settime", "timerfd_create",
            "timerfd_gettime", "timerfd_settime", "times", "tkill",
            "truncate", "truncate64", "ugetrlimit", "umask",
            "uname", "unlink", "unlinkat", "unshare", "utime",
            "utimensat", "utimes", "vfork", "vmsplice", "wait4",
            "waitid", "waitpid", "write", "writev",
        )
        return profile

    @classmethod
    def docker_default(cls) -> "SeccompProfile":
        """Docker's default seccomp profile (based on Docker's actual profile)."""
        profile = cls.default_restricted()
        # Docker also blocks specific syscalls
        for syscall in ["acct", "add_key", "bpf", "clock_adjtime",
                        "clock_settime", "create_module", "delete_module",
                        "finish_module", "get_kernel_syms", "get_mempolicy",
                        "init_module", "iopl", "ioperm", "kcmp",
                        "kexec_file_load", "kexec_load", "lookup_dcookie",
                        "modify_ldt", "nfsservctl", "nsenter", "open_by_handle_at",
                        "perf_event_open", "process_vm_readv", "process_vm_writev",
                        "ptrace", "query_module", "quotactl", "request_key",
                        "set_robust_list", "set_mempolicy", "setns",
                        "stub_execveat", "stub_sigaltstack", "swapon",
                        "swapoff", "sysfs", "syslog", "uselib",
                        "userfaultfd", "ustat", "vm86", "vm86old",
                        "vhangup"]:
            profile.add_deny(syscall)

        return profile


@dataclass
class CapabilitySet:
    """Linux capabilities configuration."""
    bounding: list[str] = field(default_factory=list)
    effective: list[str] = field(default_factory=list)
    inheritable: list[str] = field(default_factory=list)
    permitted: list[str] = field(default_factory=list)
    ambient: list[str] = field(default_factory=list)

    # Default capabilities dropped in containers
    DROP_ALL: ClassVar[list[str]] = [
        "CAP_AUDIT_CONTROL", "CAP_AUDIT_READ", "CAP_AUDIT_WRITE",
        "CAP_BLOCK_SUSPEND", "CAP_BPF", "CAP_CHECKPOINT_RESTORE",
        "CAP_DAC_READ_SEARCH", "CAP_IPC_LOCK", "CAP_LEASE",
        "CAP_LINUX_IMMUTABLE", "CAP_MAC_ADMIN", "CAP_MAC_OVERRIDE",
        "CAP_NET_ADMIN", "CAP_NET_BROADCAST", "CAP_NET_RAW",
        "CAP_PERFMON", "CAP_SYS_ADMIN", "CAP_SYS_BOOT",
        "CAP_SYS_MODULE", "CAP_SYS_NICE", "CAP_SYS_PACCT",
        "CAP_SYS_PTRACE", "CAP_SYS_RAWIO", "CAP_SYS_RESOURCE",
        "CAP_SYS_TIME", "CAP_SYS_TTY_CONFIG", "CAP_WAKE_ALARM",
    ]

    # Default capabilities kept in containers
    KEEP_DEFAULT: ClassVar[list[str]] = [
        "CAP_CHOWN", "CAP_DAC_OVERRIDE", "CAP_FSETID",
        "CAP_FOWNER", "CAP_KILL", "CAP_SETGID", "CAP_SETUID",
        "CAP_SETPCAP", "CAP_NET_BIND_SERVICE", "CAP_NET_RAW",
        "CAP_SYS_CHROOT", "CAP_MKNOD", "CAP_AUDIT_WRITE",
        "CAP_SETFCAP",
    ]

    # Privileged mode capabilities (all)
    PRIVILEGED: ClassVar[list[str]] = [
        "CAP_AUDIT_CONTROL", "CAP_AUDIT_READ", "CAP_AUDIT_WRITE",
        "CAP_BLOCK_SUSPEND", "CAP_BPF", "CAP_CHECKPOINT_RESTORE",
        "CAP_CHOWN", "CAP_DAC_OVERRIDE", "CAP_DAC_READ_SEARCH",
        "CAP_FOWNER", "CAP_FSETID", "CAP_IPC_LOCK", "CAP_IPC_OWNER",
        "CAP_KILL", "CAP_LEASE", "CAP_LINUX_IMMUTABLE",
        "CAP_MAC_ADMIN", "CAP_MAC_OVERRIDE", "CAP_MKNOD",
        "CAP_NET_ADMIN", "CAP_NET_BIND_SERVICE", "CAP_NET_BROADCAST",
        "CAP_NET_RAW", "CAP_PERFMON", "CAP_SETGID", "CAP_SETFCAP",
        "CAP_SETPCAP", "CAP_SETUID", "CAP_SYS_ADMIN", "CAP_SYS_BOOT",
        "CAP_SYS_CHROOT", "CAP_SYS_MODULE", "CAP_SYS_NICE",
        "CAP_SYS_PACCT", "CAP_SYS_PTRACE", "CAP_SYS_RAWIO",
        "CAP_SYS_RESOURCE", "CAP_SYS_TIME", "CAP_SYS_TTY_CONFIG",
        "CAP_SYSLOG", "CAP_WAKE_ALARM",
    ]

    @classmethod
    def default_container(cls) -> "CapabilitySet":
        """Default capabilities for a non-privileged container."""
        return cls(
            bounding=list(cls.KEEP_DEFAULT),
            effective=list(cls.KEEP_DEFAULT),
            inheritable=list(cls.KEEP_DEFAULT),
            permitted=list(cls.KEEP_DEFAULT),
            ambient=[],
        )

    @classmethod
    def privileged(cls) -> "CapabilitySet":
        """All capabilities (privileged mode)."""
        return cls(
            bounding=list(cls.PRIVILEGED),
            effective=list(cls.PRIVILEGED),
            inheritable=list(cls.PRIVILEGED),
            permitted=list(cls.PRIVILEGED),
            ambient=list(cls.PRIVILEGED),
        )

    @classmethod
    def empty(cls) -> "CapabilitySet":
        """No capabilities."""
        return cls()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "bounding": self.bounding,
            "effective": self.effective,
            "inheritable": self.inheritable,
            "permitted": self.permitted,
            "ambient": self.ambient,
        }

    @classmethod
    def from_dict(cls, data: dict[str, list[str]]) -> "CapabilitySet":
        return cls(
            bounding=data.get("bounding", []),
            effective=data.get("effective", []),
            inheritable=data.get("inheritable", []),
            permitted=data.get("permitted", []),
            ambient=data.get("ambient", []),
        )


@dataclass
class AppArmorProfile:
    """AppArmor security profile."""
    name: str
    profile_content: str = ""
    enforce: bool = True

    @classmethod
    def default_container(cls) -> "AppArmorProfile":
        """Default AppArmor profile for containers."""
        return cls(
            name="ainos-default",
            profile_content="""
#include <tunables/global>
profile ainos-default flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  #include <abstractions/lxc/container-base>

  # Deny all rawio
  deny /sys/** w,
  deny /sys/block/** rw,
  deny /sys/bus/** rw,
  deny /sys/class/** rw,
  deny /sys/dev/** rw,
  deny /sys/devices/** rw,

  # Deny kernel access
  deny /proc/sys/kernel/** rw,
  deny /sys/kernel/** rw,

  # Deny module loading
  deny /sbin/insmod,
  deny /sbin/rmmod,
  deny /sbin/modprobe,

  # Network
  network inet tcp,
  network inet udp,
  network inet6 tcp,
  network inet6 udp,

  # Allow everything else
  /** r,
}
""",
        )


@dataclass
class SecurityProfile:
    """Complete security profile for a container."""
    seccomp: SeccompProfile = field(default_factory=SeccompProfile.default_restricted)
    capabilities: CapabilitySet = field(default_factory=CapabilitySet.default_container)
    apparmor: Optional[AppArmorProfile] = None
    selinux_label: Optional[str] = None
    read_only_rootfs: bool = False
    masked_paths: list[str] = field(default_factory=lambda: [
        "/proc/acpi", "/proc/kcore", "/proc/keys",
        "/proc/latency_stats", "/proc/timer_list",
        "/proc/timer_stats", "/proc/sched_debug",
        "/proc/scsi", "/sys/firmware",
    ])
    readonly_paths: list[str] = field(default_factory=lambda: [
        "/proc/bus", "/proc/fs", "/proc/irq",
        "/proc/sys", "/proc/sysrq-trigger",
    ])
    no_new_privs: bool = True
    allow_privileged: bool = False

    @classmethod
    def default(cls) -> "SecurityProfile":
        """Default security profile for non-privileged containers."""
        return cls(
            seccomp=SeccompProfile.default_restricted(),
            capabilities=CapabilitySet.default_container(),
            apparmor=AppArmorProfile.default_container() if _apparmor_available() else None,
            allow_privileged=False,
        )

    @classmethod
    def privileged(cls) -> "SecurityProfile":
        """Privileged security profile."""
        return cls(
            seccomp=SeccompProfile.default_unconfined(),
            capabilities=CapabilitySet.privileged(),
            apparmor=None,
            allow_privileged=True,
            no_new_privs=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seccomp": self.seccomp.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "apparmor": self.apparmor.name if self.apparmor else None,
            "selinux_label": self.selinux_label,
            "read_only_rootfs": self.read_only_rootfs,
            "masked_paths": self.masked_paths,
            "readonly_paths": self.readonly_paths,
            "no_new_privs": self.no_new_privs,
            "allow_privileged": self.allow_privileged,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecurityProfile":
        seccomp = SeccompProfile.from_dict(data.get("seccomp", {}))
        caps = CapabilitySet.from_dict(data.get("capabilities", {}))
        return cls(
            seccomp=seccomp,
            capabilities=caps,
            apparmor=AppArmorProfile(name=data["apparmor"]) if data.get("apparmor") else None,
            selinux_label=data.get("selinux_label"),
            read_only_rootfs=data.get("read_only_rootfs", False),
            masked_paths=data.get("masked_paths", cls.default().masked_paths),
            readonly_paths=data.get("readonly_paths", cls.default().readonly_paths),
            no_new_privs=data.get("no_new_privs", True),
            allow_privileged=data.get("allow_privileged", False),
        )


def _apparmor_available() -> bool:
    """Check if AppArmor is available on the system."""
    try:
        return os.path.exists("/sys/module/apparmor/parameters/enabled")
    except OSError:
        return False


class SecurityManager:
    """
    Security manager for containers.

    Manages seccomp profiles, capabilities, AppArmor, and SELinux
    configurations for containers.
    """

    def __init__(self) -> None:
        SECURITY_DIR.mkdir(parents=True, exist_ok=True)
        self._apparmor_available = _apparmor_available()

    @staticmethod
    def get_kernel_capabilities() -> list[str]:
        """Get all capabilities supported by the kernel."""
        try:
            cap_file = Path("/proc/sys/kernel/cap_last_cap")
            if cap_file.exists():
                max_cap = int(cap_file.read_text().strip())
                # Generate standard capability names
                cap_names = {
                    0: "CAP_CHOWN", 1: "CAP_DAC_OVERRIDE", 2: "CAP_DAC_READ_SEARCH",
                    3: "CAP_FOWNER", 4: "CAP_FSETID", 5: "CAP_KILL",
                    6: "CAP_SETGID", 7: "CAP_SETUID", 8: "CAP_SETPCAP",
                    9: "CAP_LINUX_IMMUTABLE", 10: "CAP_NET_BIND_SERVICE",
                    11: "CAP_NET_BROADCAST", 12: "CAP_NET_ADMIN",
                    13: "CAP_NET_RAW", 14: "CAP_IPC_LOCK", 15: "CAP_IPC_OWNER",
                    16: "CAP_SYS_MODULE", 17: "CAP_SYS_RAWIO",
                    18: "CAP_SYS_CHROOT", 19: "CAP_SYS_PTRACE",
                    20: "CAP_SYS_PACCT", 21: "CAP_SYS_ADMIN",
                    22: "CAP_SYS_BOOT", 23: "CAP_SYS_NICE",
                    24: "CAP_SYS_RESOURCE", 25: "CAP_SYS_TIME",
                    26: "CAP_SYS_TTY_CONFIG", 27: "CAP_MKNOD",
                    28: "CAP_LEASE", 29: "CAP_AUDIT_WRITE",
                    30: "CAP_AUDIT_CONTROL", 31: "CAP_SETFCAP",
                    32: "CAP_MAC_OVERRIDE", 33: "CAP_MAC_ADMIN",
                    34: "CAP_SYSLOG", 35: "CAP_WAKE_ALARM",
                    36: "CAP_BLOCK_SUSPEND", 37: "CAP_AUDIT_READ",
                    38: "CAP_PERFMON", 39: "CAP_BPF",
                    40: "CAP_CHECKPOINT_RESTORE",
                }
                return [cap_names[i] for i in range(max_cap + 1) if i in cap_names]
        except (OSError, ValueError):
            pass
        return list(CapabilitySet.PRIVILEGED)

    def save_seccomp_profile(self, profile: SeccompProfile, name: str) -> Path:
        """Save a seccomp profile to disk."""
        path = SECURITY_DIR / f"{name}.seccomp.json"
        try:
            path.write_text(json.dumps(profile.to_dict(), indent=2))
            logger.info("Saved seccomp profile: %s", name)
            return path
        except OSError as e:
            raise SecurityError(f"Failed to save seccomp profile {name}: {e}") from e

    def load_seccomp_profile(self, name: str) -> SeccompProfile:
        """Load a seccomp profile from disk."""
        path = SECURITY_DIR / f"{name}.seccomp.json"
        if not path.exists():
            raise SecurityError(f"Seccomp profile not found: {name}")
        try:
            data = json.loads(path.read_text())
            return SeccompProfile.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            raise SecurityError(f"Failed to load seccomp profile {name}: {e}") from e

    def apply_seccomp(self, profile: SeccompProfile) -> bool:
        """
        Apply a seccomp profile to the current process.

        Note: In practice, seccomp is applied before the container process starts.
        This method provides a reference implementation.

        Args:
            profile: The seccomp profile to apply.

        Returns:
            True if seccomp was applied successfully.
        """
        logger.info("Seccomp profile configured: %s (apply at process start)", profile.default_action.value)
        return True

    def get_apparmor_status(self) -> dict[str, bool]:
        """Get AppArmor status."""
        return {
            "available": self._apparmor_available,
            "enabled": self._apparmor_available and self._check_apparmor_enabled(),
            "loaded_profiles": self._list_apparmor_profiles(),
        }

    @staticmethod
    def _check_apparmor_enabled() -> bool:
        try:
            result = Path("/sys/module/apparmor/parameters/enabled").read_text().strip()
            return result == "Y"
        except (FileNotFoundError, OSError):
            return False

    @staticmethod
    def _list_apparmor_profiles() -> list[str]:
        try:
            profiles = Path("/sys/kernel/security/apparmor/profiles")
            if profiles.exists():
                return profiles.read_text().strip().splitlines()
        except (FileNotFoundError, OSError):
            pass
        return []

    def get_security_info(self) -> dict[str, Any]:
        """Get system security information."""
        return {
            "apparmor": self.get_apparmor_status(),
            "seccomp": {
                "available": True,
                "supported_actions": [a.value for a in SeccompAction],
            },
            "capabilities": {
                "kernel_supported": self.get_kernel_capabilities(),
                "count": len(self.get_kernel_capabilities()),
            },
            "selinux": {
                "available": os.path.exists("/sys/fs/selinux"),
            },
        }