"""
Docker integration plugin for Ainos Shell.

Provides Docker management features:
- Docker command shortcuts
- Container status display
- Quick container management
- Docker compose helpers
- Image management commands
- Log viewing helpers
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import typing as t
from dataclasses import dataclass, field

from ..src.plugins import Plugin, PluginInfo, HookType, PluginContext
from ..src.utils import AnsiCode, colorize


@dataclass
class ContainerInfo:
    """Docker container information."""
    id: str = ""
    name: str = ""
    image: str = ""
    status: str = ""
    ports: str = ""
    created: str = ""
    size: str = ""
    running: bool = False
    exit_code: int = 0

    @property
    def short_id(self) -> str:
        return self.id[:12] if self.id else ""

    def __repr__(self) -> str:
        return f"Container({self.name})"


@dataclass
class ImageInfo:
    """Docker image information."""
    id: str = ""
    repository: str = ""
    tag: str = ""
    size: str = ""
    created: str = ""

    @property
    def short_id(self) -> str:
        return self.id[:12] if self.id else ""

    def __repr__(self) -> str:
        return f"Image({self.repository}:{self.tag})"


class DockerPlugin(Plugin):
    """Docker integration plugin."""

    info = PluginInfo(
        name="docker",
        version="1.0.0",
        description="Docker container and image management",
        author="Ainos Team",
        tags=["docker", "containers", "devops"],
        priority=60,
    )

    def __init__(self, context: t.Optional[PluginContext] = None) -> None:
        super().__init__(context)
        self._docker_available: t.Optional[bool] = None

    def initialize(self) -> None:
        """Initialize the plugin."""
        self.set_config("show_in_prompt", False)
        self.set_config("compose_default", "docker-compose.yml")

    @property
    def available(self) -> bool:
        """Check if Docker is available."""
        if self._docker_available is None:
            try:
                result = subprocess.run(
                    ["docker", "--version"],
                    capture_output=True, text=True, timeout=5
                )
                self._docker_available = result.returncode == 0
            except (FileNotFoundError, subprocess.SubprocessError):
                self._docker_available = False
        return self._docker_available

    def list_containers(self, all_containers: bool = False, quiet: bool = False) -> t.List[ContainerInfo]:
        """List Docker containers."""
        if not self.available:
            return []

        cmd = ["docker", "ps"]
        if all_containers:
            cmd.append("-a")

        if quiet:
            cmd.extend(["--format", "{{.ID}}"])
        else:
            cmd.extend(["--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}|{{.CreatedAt}}|{{.Size}}"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return []

            containers = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                if quiet:
                    containers.append(ContainerInfo(id=line.strip()))
                    continue

                parts = line.split("|")
                if len(parts) >= 4:
                    info = ContainerInfo(
                        id=parts[0],
                        name=parts[1],
                        image=parts[2],
                        status=parts[3],
                        ports=parts[4] if len(parts) > 4 else "",
                        created=parts[5] if len(parts) > 5 else "",
                        size=parts[6] if len(parts) > 6 else "",
                        running="Up" in parts[3] or "running" in parts[3].lower(),
                    )
                    # Extract exit code if available
                    ec_match = re.search(r"Exited \((\d+)\)", parts[3])
                    if ec_match:
                        info.exit_code = int(ec_match.group(1))
                    containers.append(info)

            return containers
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

    def list_images(self) -> t.List[ImageInfo]:
        """List Docker images."""
        if not self.available:
            return []

        cmd = ["docker", "images", "--format", "{{.ID}}|{{.Repository}}|{{.Tag}}|{{.Size}}|{{.CreatedAt}}"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return []

            images = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|")
                if len(parts) >= 3:
                    images.append(ImageInfo(
                        id=parts[0],
                        repository=parts[1],
                        tag=parts[2],
                        size=parts[3] if len(parts) > 3 else "",
                        created=parts[4] if len(parts) > 4 else "",
                    ))
            return images
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

    def container_logs(self, container_id: str, tail: int = 50, follow: bool = False) -> t.Optional[str]:
        """Get container logs."""
        if not self.available:
            return None

        cmd = ["docker", "logs", container_id]
        if tail:
            cmd.extend(["--tail", str(tail)])
        if follow:
            cmd.append("-f")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.stdout if result.returncode == 0 else None
        except subprocess.SubprocessError:
            return None

    def start_container(self, container_id: str) -> bool:
        """Start a container."""
        if not self.available:
            return False
        try:
            result = subprocess.run(
                ["docker", "start", container_id],
                capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False

    def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        """Stop a container."""
        if not self.available:
            return False
        try:
            result = subprocess.run(
                ["docker", "stop", "-t", str(timeout), container_id],
                capture_output=True, text=True, timeout=timeout + 5
            )
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False

    def restart_container(self, container_id: str) -> bool:
        """Restart a container."""
        if not self.available:
            return False
        try:
            result = subprocess.run(
                ["docker", "restart", container_id],
                capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False

    def remove_container(self, container_id: str, force: bool = False) -> bool:
        """Remove a container."""
        if not self.available:
            return False
        cmd = ["docker", "rm"]
        if force:
            cmd.append("-f")
        cmd.append(container_id)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False

    def remove_image(self, image_id: str, force: bool = False) -> bool:
        """Remove an image."""
        if not self.available:
            return False
        cmd = ["docker", "rmi"]
        if force:
            cmd.append("-f")
        cmd.append(image_id)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False

    def compose_up(self, file: str = "", detach: bool = True) -> bool:
        """Run docker-compose up."""
        if not self.available:
            return False
        cmd = ["docker-compose"]
        if file:
            cmd.extend(["-f", file])
        cmd.append("up")
        if detach:
            cmd.append("-d")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False

    def compose_down(self, file: str = "") -> bool:
        """Run docker-compose down."""
        if not self.available:
            return False
        cmd = ["docker-compose"]
        if file:
            cmd.extend(["-f", file])
        cmd.append("down")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return result.returncode == 0
        except subprocess.SubprocessError:
            return False

    def get_shortcuts(self) -> t.Dict[str, str]:
        """Get Docker command shortcuts."""
        return {
            "dps": "docker ps",
            "dpsa": "docker ps -a",
            "di": "docker images",
            "drm": "docker rm",
            "drmi": "docker rmi",
            "dstop": "docker stop",
            "dstart": "docker start",
            "drestart": "docker restart",
            "dlogs": "docker logs",
            "dexec": "docker exec -it",
            "dprune": "docker system prune -f",
            "dcup": "docker-compose up -d",
            "dcdown": "docker-compose down",
            "dcbuild": "docker-compose build",
            "dstats": "docker stats",
            "dtop": "docker top",
            "dnetwork": "docker network ls",
            "dvolume": "docker volume ls",
        }

    def activate(self) -> None:
        """Activate the plugin."""
        super().activate()
        if self.available:
            from ..src.config import set_alias
            for shortcut, command in self.get_shortcuts().items():
                set_alias(shortcut, command)

    def deactivate(self) -> None:
        """Deactivate the plugin."""
        super().deactivate()
        from ..src.config import unset_alias
        for shortcut in self.get_shortcuts().keys():
            unset_alias(shortcut)

    def __repr__(self) -> str:
        avail = "available" if self.available else "unavailable"
        return f"DockerPlugin({avail})"