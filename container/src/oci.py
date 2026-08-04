"""
OCI 运行时规范模块 - OCI Runtime Specification implementation.

遵循 OCI Runtime Specification (https://github.com/opencontainers/runtime-spec)
实现容器运行时配置和状态管理。
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class OCIError(Exception):
    """Raised when an OCI operation fails."""
    def __init__(self, message: str) -> None:
        super().__init__(f"OCI error: {message}")


class HookType(Enum):
    """OCI hook types."""
    PRESTART = "prestart"
    POSTSTART = "poststart"
    POSTSTOP = "poststop"
    CREATE_RUNTIME = "createRuntime"
    CREATE_CONTAINER = "createContainer"
    START_CONTAINER = "startContainer"


@dataclass
class OCIHook:
    """OCI hook specification."""
    path: str
    args: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    timeout: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"path": self.path}
        if self.args:
            result["args"] = self.args
        if self.env:
            result["env"] = self.env
        if self.timeout is not None:
            result["timeout"] = self.timeout
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OCIHook":
        return cls(
            path=data["path"],
            args=data.get("args", []),
            env=data.get("env", []),
            timeout=data.get("timeout"),
        )


@dataclass
class Spec:
    """
    OCI Runtime Specification root object.

    Follows the OCI Runtime Spec schema for container configuration.
    """

    @dataclass
    class Root:
        path: str
        readonly: bool = False

        def to_dict(self) -> dict[str, Any]:
            return {"path": self.path, "readonly": self.readonly}

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.Root":
            return cls(path=data["path"], readonly=data.get("readonly", False))

    @dataclass
    class Process:
        terminal: bool = False
        user: "Spec.User" = field(default_factory=lambda: Spec.User())
        args: list[str] = field(default_factory=lambda: ["sh"])
        env: list[str] = field(default_factory=list)
        cwd: str = "/"
        capabilities: Optional["Spec.LinuxCapabilities"] = None
        rlimits: list["Spec.RLimit"] = field(default_factory=list)
        no_new_privileges: bool = True
        apparmor_profile: Optional[str] = None
        selinux_label: Optional[str] = None
        oom_score_adj: Optional[int] = None

        def to_dict(self) -> dict[str, Any]:
            result: dict[str, Any] = {
                "terminal": self.terminal,
                "user": self.user.to_dict(),
                "args": self.args,
                "env": self.env,
                "cwd": self.cwd,
                "noNewPrivileges": self.no_new_privileges,
            }
            if self.capabilities:
                result["capabilities"] = self.capabilities.to_dict()
            if self.rlimits:
                result["rlimits"] = [r.to_dict() for r in self.rlimits]
            if self.apparmor_profile:
                result["apparmorProfile"] = self.apparmor_profile
            if self.selinux_label:
                result["selinuxLabel"] = self.selinux_label
            if self.oom_score_adj is not None:
                result["oomScoreAdj"] = self.oom_score_adj
            return result

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.Process":
            user = Spec.User.from_dict(data.get("user", {}))
            caps = Spec.LinuxCapabilities.from_dict(data["capabilities"]) if "capabilities" in data else None
            rlimits = [Spec.RLimit.from_dict(r) for r in data.get("rlimits", [])]
            return cls(
                terminal=data.get("terminal", False),
                user=user,
                args=data.get("args", ["sh"]),
                env=data.get("env", []),
                cwd=data.get("cwd", "/"),
                capabilities=caps,
                rlimits=rlimits,
                no_new_privileges=data.get("noNewPrivileges", True),
                apparmor_profile=data.get("apparmorProfile"),
                selinux_label=data.get("selinuxLabel"),
                oom_score_adj=data.get("oomScoreAdj"),
            )

    @dataclass
    class User:
        uid: int = 0
        gid: int = 0
        umask: Optional[int] = None
        additional_gids: list[int] = field(default_factory=list)
        username: str = ""

        def to_dict(self) -> dict[str, Any]:
            result: dict[str, Any] = {"uid": self.uid, "gid": self.gid}
            if self.umask is not None:
                result["umask"] = self.umask
            if self.additional_gids:
                result["additionalGids"] = self.additional_gids
            if self.username:
                result["username"] = self.username
            return result

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.User":
            return cls(
                uid=data.get("uid", 0),
                gid=data.get("gid", 0),
                umask=data.get("umask"),
                additional_gids=data.get("additionalGids", []),
                username=data.get("username", ""),
            )

    @dataclass
    class LinuxCapabilities:
        bounding: list[str] = field(default_factory=list)
        effective: list[str] = field(default_factory=list)
        inheritable: list[str] = field(default_factory=list)
        permitted: list[str] = field(default_factory=list)
        ambient: list[str] = field(default_factory=list)

        def to_dict(self) -> dict[str, Any]:
            return {
                "bounding": self.bounding,
                "effective": self.effective,
                "inheritable": self.inheritable,
                "permitted": self.permitted,
                "ambient": self.ambient,
            }

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.LinuxCapabilities":
            return cls(
                bounding=data.get("bounding", []),
                effective=data.get("effective", []),
                inheritable=data.get("inheritable", []),
                permitted=data.get("permitted", []),
                ambient=data.get("ambient", []),
            )

    @dataclass
    class RLimit:
        type: str
        hard: int
        soft: int

        def to_dict(self) -> dict[str, Any]:
            return {"type": self.type, "hard": self.hard, "soft": self.soft}

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.RLimit":
            return cls(type=data["type"], hard=int(data["hard"]), soft=int(data["soft"]))

    @dataclass
    class Mount:
        destination: str
        source: str = ""
        type: str = ""
        options: list[str] = field(default_factory=list)

        def to_dict(self) -> dict[str, Any]:
            result: dict[str, Any] = {"destination": self.destination}
            if self.source:
                result["source"] = self.source
            if self.type:
                result["type"] = self.type
            if self.options:
                result["options"] = self.options
            return result

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.Mount":
            return cls(
                destination=data["destination"],
                source=data.get("source", ""),
                type=data.get("type", ""),
                options=data.get("options", []),
            )

    @dataclass
    class Linux:
        @dataclass
        class LinuxResources:
            @dataclass
            class CPU:
                shares: Optional[int] = None
                quota: Optional[int] = None
                period: Optional[int] = None
                cpus: Optional[str] = None
                mems: Optional[str] = None

                def to_dict(self) -> dict[str, Any]:
                    result: dict[str, Any] = {}
                    if self.shares is not None:
                        result["shares"] = self.shares
                    if self.quota is not None:
                        result["quota"] = self.quota
                    if self.period is not None:
                        result["period"] = self.period
                    if self.cpus is not None:
                        result["cpus"] = self.cpus
                    if self.mems is not None:
                        result["mems"] = self.mems
                    return result

                @classmethod
                def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux.LinuxResources.CPU":
                    return cls(
                        shares=data.get("shares"),
                        quota=data.get("quota"),
                        period=data.get("period"),
                        cpus=data.get("cpus"),
                        mems=data.get("mems"),
                    )

            @dataclass
            class Memory:
                limit: Optional[int] = None
                reservation: Optional[int] = None
                swap: Optional[int] = None
                kernel: Optional[int] = None
                kernel_tcp: Optional[int] = None
                swappiness: Optional[int] = None

                def to_dict(self) -> dict[str, Any]:
                    result: dict[str, Any] = {}
                    if self.limit is not None:
                        result["limit"] = self.limit
                    if self.reservation is not None:
                        result["reservation"] = self.reservation
                    if self.swap is not None:
                        result["swap"] = self.swap
                    if self.kernel is not None:
                        result["kernel"] = self.kernel
                    if self.kernel_tcp is not None:
                        result["kernelTCP"] = self.kernel_tcp
                    if self.swappiness is not None:
                        result["swappiness"] = self.swappiness
                    return result

                @classmethod
                def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux.LinuxResources.Memory":
                    return cls(
                        limit=data.get("limit"),
                        reservation=data.get("reservation"),
                        swap=data.get("swap"),
                        kernel=data.get("kernel"),
                        kernel_tcp=data.get("kernelTCP"),
                        swappiness=data.get("swappiness"),
                    )

            @dataclass
            class Pids:
                limit: int

                def to_dict(self) -> dict[str, Any]:
                    return {"limit": self.limit}

                @classmethod
                def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux.LinuxResources.Pids":
                    return cls(limit=data["limit"])

            cpu: Optional["Spec.Linux.LinuxResources.CPU"] = None
            memory: Optional["Spec.Linux.LinuxResources.Memory"] = None
            pids: Optional["Spec.Linux.LinuxResources.Pids"] = None

            def to_dict(self) -> dict[str, Any]:
                result: dict[str, Any] = {}
                if self.cpu:
                    result["cpu"] = self.cpu.to_dict()
                if self.memory:
                    result["memory"] = self.memory.to_dict()
                if self.pids:
                    result["pids"] = self.pids.to_dict()
                return result

            @classmethod
            def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux.LinuxResources":
                cpu = Spec.Linux.LinuxResources.CPU.from_dict(data["cpu"]) if "cpu" in data else None
                mem = Spec.Linux.LinuxResources.Memory.from_dict(data["memory"]) if "memory" in data else None
                pids = Spec.Linux.LinuxResources.Pids.from_dict(data["pids"]) if "pids" in data else None
                return cls(cpu=cpu, memory=mem, pids=pids)

        @dataclass
        class LinuxNamespace:
            type: str
            path: Optional[str] = None

            def to_dict(self) -> dict[str, Any]:
                result: dict[str, Any] = {"type": self.type}
                if self.path:
                    result["path"] = self.path
                return result

            @classmethod
            def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux.LinuxNamespace":
                return cls(type=data["type"], path=data.get("path"))

        @dataclass
        class LinuxDevice:
            path: str
            type: str
            major: int
            minor: int
            permissions: str = "rwm"
            file_mode: Optional[int] = None
            uid: Optional[int] = None
            gid: Optional[int] = None

            def to_dict(self) -> dict[str, Any]:
                result: dict[str, Any] = {
                    "path": self.path, "type": self.type,
                    "major": self.major, "minor": self.minor,
                    "permissions": self.permissions,
                }
                if self.file_mode is not None:
                    result["fileMode"] = self.file_mode
                if self.uid is not None:
                    result["uid"] = self.uid
                if self.gid is not None:
                    result["gid"] = self.gid
                return result

            @classmethod
            def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux.LinuxDevice":
                return cls(
                    path=data["path"], type=data["type"],
                    major=data["major"], minor=data["minor"],
                    permissions=data.get("permissions", "rwm"),
                    file_mode=data.get("fileMode"),
                    uid=data.get("uid"), gid=data.get("gid"),
                )

        @dataclass
        class LinuxSeccomp:
            default_action: str
            architectures: list[str] = field(default_factory=list)
            syscalls: list[dict[str, Any]] = field(default_factory=list)

            def to_dict(self) -> dict[str, Any]:
                return {
                    "defaultAction": self.default_action,
                    "architectures": self.architectures,
                    "syscalls": self.syscalls,
                }

            @classmethod
            def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux.LinuxSeccomp":
                return cls(
                    default_action=data["defaultAction"],
                    architectures=data.get("architectures", []),
                    syscalls=data.get("syscalls", []),
                )

        uid_mappings: list[dict[str, int]] = field(default_factory=list)
        gid_mappings: list[dict[str, int]] = field(default_factory=list)
        namespaces: list["Spec.Linux.LinuxNamespace"] = field(default_factory=list)
        devices: list["Spec.Linux.LinuxDevice"] = field(default_factory=list)
        resources: Optional["Spec.Linux.LinuxResources"] = None
        seccomp: Optional["Spec.Linux.LinuxSeccomp"] = None
        masked_paths: list[str] = field(default_factory=list)
        readonly_paths: list[str] = field(default_factory=list)
        cgroups_path: Optional[str] = None

        def to_dict(self) -> dict[str, Any]:
            result: dict[str, Any] = {
                "namespaces": [ns.to_dict() for ns in self.namespaces],
                "devices": [d.to_dict() for d in self.devices],
            }
            if self.uid_mappings:
                result["uidMappings"] = self.uid_mappings
            if self.gid_mappings:
                result["gidMappings"] = self.gid_mappings
            if self.resources:
                result["resources"] = self.resources.to_dict()
            if self.seccomp:
                result["seccomp"] = self.seccomp.to_dict()
            if self.masked_paths:
                result["maskedPaths"] = self.masked_paths
            if self.readonly_paths:
                result["readonlyPaths"] = self.readonly_paths
            if self.cgroups_path:
                result["cgroupsPath"] = self.cgroups_path
            return result

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.Linux":
            namespaces = [Spec.Linux.LinuxNamespace.from_dict(ns) for ns in data.get("namespaces", [])]
            devices = [Spec.Linux.LinuxDevice.from_dict(d) for d in data.get("devices", [])]
            resources = Spec.Linux.LinuxResources.from_dict(data["resources"]) if "resources" in data else None
            seccomp = Spec.Linux.LinuxSeccomp.from_dict(data["seccomp"]) if "seccomp" in data else None
            return cls(
                uid_mappings=data.get("uidMappings", []),
                gid_mappings=data.get("gidMappings", []),
                namespaces=namespaces,
                devices=devices,
                resources=resources,
                seccomp=seccomp,
                masked_paths=data.get("maskedPaths", []),
                readonly_paths=data.get("readonlyPaths", []),
                cgroups_path=data.get("cgroupsPath"),
            )

    @dataclass
    class Hooks:
        prestart: list[OCIHook] = field(default_factory=list)
        poststart: list[OCIHook] = field(default_factory=list)
        poststop: list[OCIHook] = field(default_factory=list)
        create_runtime: list[OCIHook] = field(default_factory=list)
        create_container: list[OCIHook] = field(default_factory=list)
        start_container: list[OCIHook] = field(default_factory=list)

        def to_dict(self) -> dict[str, Any]:
            result: dict[str, Any] = {}
            if self.prestart:
                result["prestart"] = [h.to_dict() for h in self.prestart]
            if self.poststart:
                result["poststart"] = [h.to_dict() for h in self.poststart]
            if self.poststop:
                result["poststop"] = [h.to_dict() for h in self.poststop]
            if self.create_runtime:
                result["createRuntime"] = [h.to_dict() for h in self.create_runtime]
            if self.create_container:
                result["createContainer"] = [h.to_dict() for h in self.create_container]
            if self.start_container:
                result["startContainer"] = [h.to_dict() for h in self.start_container]
            return result

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Spec.Hooks":
            return cls(
                prestart=[OCIHook.from_dict(h) for h in data.get("prestart", [])],
                poststart=[OCIHook.from_dict(h) for h in data.get("poststart", [])],
                poststop=[OCIHook.from_dict(h) for h in data.get("poststop", [])],
                create_runtime=[OCIHook.from_dict(h) for h in data.get("createRuntime", [])],
                create_container=[OCIHook.from_dict(h) for h in data.get("createContainer", [])],
                start_container=[OCIHook.from_dict(h) for h in data.get("startContainer", [])],
            )

    oci_version: str = "1.1.0"
    root: Root = field(default_factory=Root)
    process: Process = field(default_factory=Process)
    mounts: list[Mount] = field(default_factory=list)
    linux: Linux = field(default_factory=Linux)
    hooks: Hooks = field(default_factory=Hooks)
    hostname: str = "ainos-container"
    annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ociVersion": self.oci_version,
            "root": self.root.to_dict(),
            "process": self.process.to_dict(),
            "mounts": [m.to_dict() for m in self.mounts],
            "linux": self.linux.to_dict(),
            "hostname": self.hostname,
        }
        if self.hooks:
            hooks_dict = self.hooks.to_dict()
            if hooks_dict:
                result["hooks"] = hooks_dict
        if self.annotations:
            result["annotations"] = self.annotations
        return result

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Spec":
        return cls(
            oci_version=data.get("ociVersion", "1.1.0"),
            root=Spec.Root.from_dict(data.get("root", {"path": "/"})),
            process=Spec.Process.from_dict(data.get("process", {})),
            mounts=[Spec.Mount.from_dict(m) for m in data.get("mounts", [])],
            linux=Spec.Linux.from_dict(data.get("linux", {})),
            hooks=Spec.Hooks.from_dict(data.get("hooks", {})),
            hostname=data.get("hostname", "ainos-container"),
            annotations=data.get("annotations", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "Spec":
        """Deserialize from JSON string."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            raise OCIError(f"Failed to parse OCI spec JSON: {e}") from e

    @classmethod
    def from_file(cls, path: Path) -> "Spec":
        """Load OCI spec from a JSON file."""
        try:
            content = path.read_text()
            return cls.from_json(content)
        except (FileNotFoundError, OSError) as e:
            raise OCIError(f"Failed to read OCI spec file {path}: {e}") from e

    def save(self, path: Path) -> None:
        """Save OCI spec to a JSON file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.to_json())
        except OSError as e:
            raise OCIError(f"Failed to save OCI spec to {path}: {e}") from e


@dataclass
class ContainerState:
    """OCI container state."""
    version: str = "1.1.0"
    id: str = ""
    status: str = "created"
    pid: int = 0
    bundle: str = ""
    annotations: dict[str, str] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ociVersion": self.version,
            "id": self.id,
            "status": self.status,
            "pid": self.pid,
            "bundle": self.bundle,
        }
        if self.annotations:
            result["annotations"] = self.annotations
        if self.created_at:
            result["createdAt"] = self.created_at
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContainerState":
        return cls(
            version=data.get("ociVersion", "1.1.0"),
            id=data.get("id", ""),
            status=data.get("status", "created"),
            pid=data.get("pid", 0),
            bundle=data.get("bundle", ""),
            annotations=data.get("annotations", {}),
            created_at=data.get("createdAt", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ContainerState":
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            raise OCIError(f"Failed to parse container state: {e}") from e


class OCIRuntime:
    """
    OCI Runtime implementation.

    Manages OCI-compliant container lifecycle and state,
    providing compatibility with the OCI Runtime Specification.
    """

    def __init__(self, runtime_dir: str = "/var/lib/ainos/oci") -> None:
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._containers: dict[str, ContainerState] = {}

    def create_spec(self, container_id: str, rootfs: str,
                    process_args: Optional[list[str]] = None,
                    env: Optional[list[str]] = None,
                    hostname: Optional[str] = None,
                    resource_limits: Optional[dict[str, Any]] = None,
                    namespace_types: Optional[list[str]] = None) -> Spec:
        """
        Create an OCI specification for a container.

        Args:
            container_id: Container identifier.
            rootfs: Path to the root filesystem.
            process_args: Command and arguments.
            env: Environment variables.
            hostname: Container hostname.
            resource_limits: Resource limit configuration.
            namespace_types: Namespace types to isolate.

        Returns:
            OCI Spec object.
        """
        namespace_map = {
            "pid": "pid", "network": "network", "mount": "mount",
            "uts": "uts", "ipc": "ipc", "user": "user", "cgroup": "cgroup",
        }

        ns_types = namespace_types or ["pid", "network", "mount", "uts", "ipc"]
        namespaces = [Spec.Linux.LinuxNamespace(type=namespace_map.get(t, t)) for t in ns_types]

        # Build resources
        resources = None
        if resource_limits:
            cpu = None
            memory = None
            pids = None

            if "cpu" in resource_limits:
                cpu_data = resource_limits["cpu"]
                cpu = Spec.Linux.LinuxResources.CPU(
                    shares=cpu_data.get("shares"),
                    quota=cpu_data.get("quota"),
                    period=cpu_data.get("period"),
                    cpus=cpu_data.get("cpus"),
                )
            if "memory" in resource_limits:
                mem_data = resource_limits["memory"]
                memory = Spec.Linux.LinuxResources.Memory(
                    limit=mem_data.get("limit"),
                    reservation=mem_data.get("reservation"),
                    swap=mem_data.get("swap"),
                )
            if "pids" in resource_limits:
                pids = Spec.Linux.LinuxResources.Pids(limit=resource_limits["pids"]["limit"])

            resources = Spec.Linux.LinuxResources(cpu=cpu, memory=memory, pids=pids)

        spec = Spec(
            root=Spec.Root(path=rootfs),
            process=Spec.Process(
                args=process_args or ["/bin/sh"],
                env=env or ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
                cwd="/",
                no_new_privileges=True,
            ),
            mounts=[
                Spec.Mount(destination="/proc", source="proc", type="proc", options=["nosuid", "noexec", "nodev"]),
                Spec.Mount(destination="/sys", source="sysfs", type="sysfs", options=["nosuid", "noexec", "nodev", "ro"]),
                Spec.Mount(destination="/dev", source="devtmpfs", type="devtmpfs", options=["nosuid", "noexec", "strictatime", "mode=755"]),
                Spec.Mount(destination="/dev/pts", source="devpts", type="devpts", options=["nosuid", "noexec", "newinstance", "ptmxmode=0666", "mode=620", "gid=5"]),
                Spec.Mount(destination="/dev/shm", source="shm", type="tmpfs", options=["nosuid", "noexec", "nodev", "size=65536k"]),
                Spec.Mount(destination="/dev/mqueue", source="mqueue", type="mqueue", options=["nosuid", "noexec", "nodev"]),
            ],
            linux=Spec.Linux(
                namespaces=namespaces,
                resources=resources,
                masked_paths=[
                    "/proc/acpi", "/proc/kcore", "/proc/keys",
                    "/proc/latency_stats", "/proc/timer_list",
                    "/proc/timer_stats", "/proc/sched_debug",
                    "/proc/scsi", "/sys/firmware",
                ],
                readonly_paths=[
                    "/proc/bus", "/proc/fs", "/proc/irq",
                    "/proc/sys", "/proc/sysrq-trigger",
                ],
                cgroups_path=f"/ainos/{container_id}",
            ),
            hostname=hostname or "ainos-container",
            annotations={
                "container.id": container_id,
                "container.runtime": "ainos",
                "container.oci.version": "1.1.0",
                "created": datetime.utcnow().isoformat(),
            },
        )

        return spec

    def save_state(self, state: ContainerState) -> None:
        """Save container state to disk."""
        state_path = self.runtime_dir / f"{state.id}.json"
        try:
            state_path.write_text(state.to_json())
            self._containers[state.id] = state
        except OSError as e:
            raise OCIError(f"Failed to save state for {state.id}: {e}") from e

    def load_state(self, container_id: str) -> ContainerState:
        """Load container state from disk."""
        if container_id in self._containers:
            return self._containers[container_id]

        state_path = self.runtime_dir / f"{container_id}.json"
        if not state_path.exists():
            raise OCIError(f"Container {container_id} not found")

        try:
            state = ContainerState.from_json(state_path.read_text())
            self._containers[container_id] = state
            return state
        except (OSError, json.JSONDecodeError) as e:
            raise OCIError(f"Failed to load state for {container_id}: {e}") from e

    def delete_state(self, container_id: str) -> None:
        """Delete container state."""
        self._containers.pop(container_id, None)
        state_path = self.runtime_dir / f"{container_id}.json"
        if state_path.exists():
            try:
                state_path.unlink()
            except OSError:
                pass

    def list_containers(self) -> list[ContainerState]:
        """List all OCI containers."""
        containers: list[ContainerState] = []
        if self.runtime_dir.exists():
            for f in self.runtime_dir.iterdir():
                if f.suffix == ".json":
                    try:
                        state = ContainerState.from_json(f.read_text())
                        containers.append(state)
                    except (json.JSONDecodeError, OSError):
                        continue
        return containers