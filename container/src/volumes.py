"""
数据卷管理模块 - Volume management for Ainos containers.

支持:
- 本地卷 (host directory)
- 命名卷 (managed by runtime)
- 绑定挂载卷
- 卷驱动扩展
- 卷快照和备份
"""

import json
import logging
import os
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Optional, Union

logger = logging.getLogger(__name__)

VOLUME_DIR = Path("/var/lib/ainos/volumes")


class VolumeError(Exception):
    """Raised when a volume operation fails."""

    def __init__(self, message: str, volume_name: Optional[str] = None) -> None:
        self.volume_name = volume_name
        super().__init__(f"Volume{' ' + volume_name if volume_name else ''}: {message}")


class VolumeDriver(ABC):
    """Abstract base class for volume drivers."""

    @abstractmethod
    def create(self, name: str, opts: Optional[dict[str, str]] = None) -> str:
        """Create a volume and return its mount point."""
        ...

    @abstractmethod
    def remove(self, name: str) -> None:
        """Remove a volume."""
        ...

    @abstractmethod
    def exists(self, name: str) -> bool:
        """Check if a volume exists."""
        ...

    @abstractmethod
    def path(self, name: str) -> str:
        """Get the volume's mount point path."""
        ...

    @abstractmethod
    def list(self) -> list[str]:
        """List all volumes managed by this driver."""
        ...


class LocalVolumeDriver(VolumeDriver):
    """Local filesystem volume driver."""

    def __init__(self, base_dir: Path = VOLUME_DIR) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _volume_path(self, name: str) -> Path:
        # Sanitize name
        safe_name = name.replace("/", "_").replace("..", "_")
        return self.base_dir / safe_name

    def _metadata_path(self, name: str) -> Path:
        return self._volume_path(name) / "_volume.json"

    def create(self, name: str, opts: Optional[dict[str, str]] = None) -> str:
        vol_path = self._volume_path(name)
        if vol_path.exists():
            logger.warning("Volume %s already exists at %s", name, vol_path)
            return str(vol_path)

        try:
            vol_path.mkdir(parents=True, exist_ok=True)

            # Save metadata
            metadata = {
                "name": name,
                "driver": "local",
                "created_at": datetime.utcnow().isoformat(),
                "mountpoint": str(vol_path),
                "options": opts or {},
                "labels": {},
            }
            with open(self._metadata_path(name), "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info("Created local volume %s at %s", name, vol_path)
            return str(vol_path)
        except OSError as e:
            raise VolumeError(f"Failed to create volume: {e}", name) from e

    def remove(self, name: str) -> None:
        vol_path = self._volume_path(name)
        if not vol_path.exists():
            raise VolumeError(f"Volume not found", name)

        try:
            shutil.rmtree(vol_path, ignore_errors=True)
            logger.info("Removed volume %s", name)
        except OSError as e:
            raise VolumeError(f"Failed to remove volume: {e}", name) from e

    def exists(self, name: str) -> bool:
        return self._volume_path(name).exists()

    def path(self, name: str) -> str:
        vol_path = self._volume_path(name)
        if not vol_path.exists():
            raise VolumeError(f"Volume not found", name)
        return str(vol_path)

    def list(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return [
            d.name for d in self.base_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ]

    def get_metadata(self, name: str) -> dict[str, Any]:
        """Get volume metadata."""
        meta_path = self._metadata_path(name)
        if not meta_path.exists():
            return {}
        try:
            with open(meta_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}


@dataclass
class VolumeMount:
    """Describes how a volume is mounted into a container."""

    name: str
    mount_path: str
    read_only: bool = False
    propagation: str = "private"
    driver: str = "local"
    options: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate volume mount configuration."""
        if not self.name:
            raise ValueError("Volume name must not be empty")
        if not self.mount_path:
            raise ValueError("Mount path must not be empty")
        if not self.mount_path.startswith("/"):
            raise ValueError(f"Mount path must be absolute: {self.mount_path}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "mount_path": self.mount_path,
            "read_only": self.read_only,
            "propagation": self.propagation,
            "driver": self.driver,
            "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VolumeMount":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            mount_path=data["mount_path"],
            read_only=data.get("read_only", False),
            propagation=data.get("propagation", "private"),
            driver=data.get("driver", "local"),
            options=data.get("options", {}),
        )


@dataclass
class VolumeSnapshot:
    """Represents a snapshot of a volume."""

    name: str
    snapshot_id: str
    created_at: str
    size_bytes: int
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VolumeSnapshot":
        return cls(
            name=data["name"],
            snapshot_id=data["snapshot_id"],
            created_at=data["created_at"],
            size_bytes=data.get("size_bytes", 0),
            path=data["path"],
        )


class VolumeManager:
    """
    Central volume manager.

    Handles volume lifecycle (create, remove, mount, snapshot)
    and coordinates between volume drivers.
    """

    _instance: ClassVar[Optional["VolumeManager"]] = None
    _drivers: ClassVar[dict[str, type[VolumeDriver]]] = {
        "local": LocalVolumeDriver,
    }

    def __new__(cls, *args: Any, **kwargs: Any) -> "VolumeManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, base_dir: Union[str, Path] = VOLUME_DIR) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._driver_instances: dict[str, VolumeDriver] = {
            "local": LocalVolumeDriver(self.base_dir),
        }
        self._snapshots_dir = self.base_dir / "_snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

    def _get_driver(self, driver_name: str = "local") -> VolumeDriver:
        """Get or create a volume driver instance."""
        if driver_name not in self._driver_instances:
            driver_cls = self._drivers.get(driver_name)
            if driver_cls is None:
                supported = ", ".join(self._drivers.keys())
                raise VolumeError(
                    f"Unsupported volume driver: {driver_name}. Supported: {supported}"
                )
            self._driver_instances[driver_name] = driver_cls(self.base_dir)
        return self._driver_instances[driver_name]

    @classmethod
    def register_driver(cls, name: str, driver_cls: type[VolumeDriver]) -> None:
        """Register a custom volume driver."""
        cls._drivers[name] = driver_cls
        logger.info("Registered volume driver: %s", name)

    def create_volume(self, name: str, driver: str = "local", opts: Optional[dict[str, str]] = None) -> str:
        """
        Create a named volume.

        Args:
            name: Volume name.
            driver: Volume driver to use.
            opts: Driver-specific options.

        Returns:
            Mount point path for the volume.

        Raises:
            VolumeError: If creation fails.
        """
        driver_instance = self._get_driver(driver)
        return driver_instance.create(name, opts)

    def remove_volume(self, name: str, driver: str = "local") -> None:
        """
        Remove a named volume.

        Args:
            name: Volume name to remove.
            driver: Volume driver to use.

        Raises:
            VolumeError: If removal fails or volume not found.
        """
        driver_instance = self._get_driver(driver)
        driver_instance.remove(name)

    def volume_exists(self, name: str, driver: str = "local") -> bool:
        """Check if a volume exists."""
        driver_instance = self._get_driver(driver)
        return driver_instance.exists(name)

    def volume_path(self, name: str, driver: str = "local") -> str:
        """Get the filesystem path of a volume."""
        driver_instance = self._get_driver(driver)
        return driver_instance.path(name)

    def list_volumes(self, driver: str = "local") -> list[str]:
        """List all volumes."""
        driver_instance = self._get_driver(driver)
        return driver_instance.list()

    def list_all_volumes(self) -> dict[str, list[str]]:
        """List volumes from all drivers."""
        result: dict[str, list[str]] = {}
        for driver_name in self._drivers:
            try:
                driver_instance = self._get_driver(driver_name)
                result[driver_name] = driver_instance.list()
            except Exception as e:
                logger.warning("Failed to list volumes for driver %s: %s", driver_name, e)
                result[driver_name] = []
        return result

    def prune_volumes(self, keep: Optional[list[str]] = None) -> int:
        """
        Remove unused volumes.

        Args:
            keep: List of volume names to keep.

        Returns:
            Number of volumes removed.
        """
        keep_set = set(keep or [])
        removed = 0

        for driver_name in self._drivers:
            try:
                driver_instance = self._get_driver(driver_name)
                for vol_name in driver_instance.list():
                    if vol_name not in keep_set:
                        try:
                            driver_instance.remove(vol_name)
                            removed += 1
                        except Exception as e:
                            logger.warning("Failed to prune volume %s: %s", vol_name, e)
            except Exception as e:
                logger.warning("Failed to prune volumes for driver %s: %s", driver_name, e)

        if removed:
            logger.info("Pruned %d volumes", removed)
        return removed

    def create_snapshot(self, volume_name: str, snapshot_id: Optional[str] = None) -> VolumeSnapshot:
        """
        Create a snapshot of a volume.

        Args:
            volume_name: Name of the volume to snapshot.
            snapshot_id: Optional snapshot ID (auto-generated if not provided).

        Returns:
            VolumeSnapshot object.

        Raises:
            VolumeError: If snapshot creation fails.
        """
        vol_path = self.volume_path(volume_name)
        if not vol_path:
            raise VolumeError(f"Volume {volume_name} not found", volume_name)

        snap_id = snapshot_id or f"{volume_name}-snap-{int(time.time())}"
        snap_path = self._snapshots_dir / snap_id

        try:
            shutil.copytree(vol_path, snap_path, dirs_exist_ok=True)
            size = self._dir_size(snap_path)

            snapshot = VolumeSnapshot(
                name=volume_name,
                snapshot_id=snap_id,
                created_at=datetime.utcnow().isoformat(),
                size_bytes=size,
                path=str(snap_path),
            )

            # Save snapshot metadata
            with open(snap_path / "_snapshot.json", "w") as f:
                json.dump(snapshot.to_dict(), f, indent=2)

            logger.info("Created snapshot %s for volume %s (size=%d)", snap_id, volume_name, size)
            return snapshot
        except OSError as e:
            raise VolumeError(f"Failed to create snapshot: {e}", volume_name) from e

    def restore_snapshot(self, snapshot_id: str, target_volume: str) -> None:
        """
        Restore a volume from a snapshot.

        Args:
            snapshot_id: ID of the snapshot to restore.
            target_volume: Name of the target volume.

        Raises:
            VolumeError: If restore fails.
        """
        snap_path = self._snapshots_dir / snapshot_id
        if not snap_path.exists():
            raise VolumeError(f"Snapshot {snapshot_id} not found")

        # Recreate target volume
        vol_path = Path(self.volume_path(target_volume))
        if vol_path.exists():
            shutil.rmtree(vol_path, ignore_errors=True)
        vol_path.mkdir(parents=True, exist_ok=True)

        # Copy snapshot contents
        for item in snap_path.iterdir():
            if item.name != "_snapshot.json":
                if item.is_dir():
                    shutil.copytree(item, vol_path / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, vol_path / item.name)

        logger.info("Restored snapshot %s to volume %s", snapshot_id, target_volume)

    def list_snapshots(self, volume_name: Optional[str] = None) -> list[VolumeSnapshot]:
        """List all snapshots, optionally filtered by volume name."""
        if not self._snapshots_dir.exists():
            return []

        snapshots: list[VolumeSnapshot] = []
        for snap_dir in self._snapshots_dir.iterdir():
            if snap_dir.is_dir():
                meta_path = snap_dir / "_snapshot.json"
                if meta_path.exists():
                    try:
                        with open(meta_path) as f:
                            data = json.load(f)
                        snap = VolumeSnapshot.from_dict(data)
                        if volume_name is None or snap.name == volume_name:
                            snapshots.append(snap)
                    except (json.JSONDecodeError, OSError):
                        continue

        return sorted(snapshots, key=lambda s: s.created_at, reverse=True)

    def delete_snapshot(self, snapshot_id: str) -> None:
        """Delete a snapshot."""
        snap_path = self._snapshots_dir / snapshot_id
        if not snap_path.exists():
            raise VolumeError(f"Snapshot {snapshot_id} not found")
        try:
            shutil.rmtree(snap_path, ignore_errors=True)
            logger.info("Deleted snapshot %s", snapshot_id)
        except OSError as e:
            raise VolumeError(f"Failed to delete snapshot: {e}") from e

    def backup_volume(self, volume_name: str, backup_path: Union[str, Path]) -> Path:
        """
        Backup a volume to a tar archive.

        Args:
            volume_name: Name of the volume to backup.
            backup_path: Destination path for the backup file.

        Returns:
            Path to the created backup archive.
        """
        import tarfile

        vol_path = Path(self.volume_path(volume_name))
        backup_path = Path(backup_path)

        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(vol_path, arcname=volume_name)

            size = backup_path.stat().st_size
            logger.info("Backed up volume %s to %s (size=%d)", volume_name, backup_path, size)
            return backup_path
        except (tarfile.TarError, OSError) as e:
            raise VolumeError(f"Failed to backup volume {volume_name}: {e}", volume_name) from e

    def restore_backup(self, backup_path: Union[str, Path], volume_name: str) -> None:
        """
        Restore a volume from a tar archive.

        Args:
            backup_path: Path to the backup archive.
            volume_name: Name of the target volume.
        """
        import tarfile

        backup_path = Path(backup_path)
        if not backup_path.exists():
            raise VolumeError(f"Backup file not found: {backup_path}")

        vol_path = Path(self.volume_path(volume_name))
        if vol_path.exists():
            shutil.rmtree(vol_path, ignore_errors=True)
        vol_path.mkdir(parents=True, exist_ok=True)

        try:
            with tarfile.open(backup_path, "r:gz") as tar:
                tar.extractall(path=str(vol_path.parent), filter="data")
            logger.info("Restored volume %s from backup %s", volume_name, backup_path)
        except (tarfile.TarError, OSError) as e:
            raise VolumeError(f"Failed to restore backup: {e}") from e

    def get_volume_info(self, name: str) -> dict[str, Any]:
        """Get detailed information about a volume."""
        info: dict[str, Any] = {
            "name": name,
            "exists": False,
            "driver": "local",
            "path": "",
            "size": 0,
            "created_at": "",
        }

        try:
            path = self.volume_path(name)
            info["path"] = path
            info["exists"] = True
            info["size"] = self._dir_size(Path(path))

            # Try to get metadata
            driver = self._get_driver("local")
            if isinstance(driver, LocalVolumeDriver):
                meta = driver.get_metadata(name)
                info["created_at"] = meta.get("created_at", "")
                info["labels"] = meta.get("labels", {})
        except VolumeError:
            pass

        return info

    @staticmethod
    def _dir_size(path: Path) -> int:
        """Calculate directory size recursively."""
        total = 0
        try:
            for entry in path.rglob("*"):
                if entry.is_file() or entry.is_symlink():
                    try:
                        total += entry.lstat().st_size
                    except OSError:
                        continue
        except OSError:
            pass
        return total

    def cleanup(self) -> None:
        """Clean up volume resources."""
        logger.info("Cleaned up volume manager")

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance."""
        cls._instance = None