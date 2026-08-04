"""
存储管理模块 - Storage management for Ainos containers.

支持多种存储驱动:
- overlay2: 联合文件系统 (默认, 推荐)
- aufs: 另一种联合文件系统
- devicemapper: 设备映射器
- btrfs: B-tree 文件系统
- zfs: Zettabyte 文件系统
- vfs: 虚拟文件系统 (用于测试)
"""

import enum
import hashlib
import json
import logging
import os
import shutil
import stat
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional, Union

logger = logging.getLogger(__name__)

STORAGE_DIR = Path("/var/lib/ainos/storage")
LAYER_DIR = STORAGE_DIR / "layers"
CONTAINER_DIR = STORAGE_DIR / "containers"
REPO_DIR = STORAGE_DIR / "repository"


class StorageDriver(enum.Enum):
    """Supported storage drivers."""

    OVERLAY2 = "overlay2"
    AUFS = "aufs"
    DEVICEMAPPER = "devicemapper"
    BTRFS = "btrfs"
    ZFS = "zfs"
    VFS = "vfs"

    def __str__(self) -> str:
        return self.value


class StorageError(Exception):
    """Raised when a storage operation fails."""

    def __init__(self, message: str, driver: Optional[StorageDriver] = None) -> None:
        self.driver = driver
        super().__init__(f"Storage{'[' + driver.value + '] ' if driver else ' '}{message}")


@dataclass
class LayerMetadata:
    """Metadata for an image layer."""

    layer_id: str
    parent_id: Optional[str] = None
    created: str = ""
    created_by: str = ""
    comment: str = ""
    size_bytes: int = 0
    diff_path: str = ""
    cache_path: str = ""
    compressed: bool = False
    compression_type: str = "gzip"
    whiteout_files: list[str] = field(default_factory=list)
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "layer_id": self.layer_id,
            "parent_id": self.parent_id,
            "created": self.created,
            "created_by": self.created_by,
            "comment": self.comment,
            "size_bytes": self.size_bytes,
            "diff_path": self.diff_path,
            "cache_path": self.cache_path,
            "compressed": self.compressed,
            "compression_type": self.compression_type,
            "whiteout_files": self.whiteout_files,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LayerMetadata":
        """Create from dictionary."""
        return cls(
            layer_id=data["layer_id"],
            parent_id=data.get("parent_id"),
            created=data.get("created", ""),
            created_by=data.get("created_by", ""),
            comment=data.get("comment", ""),
            size_bytes=data.get("size_bytes", 0),
            diff_path=data.get("diff_path", ""),
            cache_path=data.get("cache_path", ""),
            compressed=data.get("compressed", False),
            compression_type=data.get("compression_type", "gzip"),
            whiteout_files=data.get("whiteout_files", []),
            checksum=data.get("checksum", ""),
        )


@dataclass
class ContainerMetadata:
    """Metadata for a container's storage."""

    container_id: str
    image_id: str
    layer_ids: list[str] = field(default_factory=list)
    mount_path: str = ""
    merged_path: str = ""
    upper_path: str = ""
    work_path: str = ""
    created_at: float = 0.0
    size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "container_id": self.container_id,
            "image_id": self.image_id,
            "layer_ids": self.layer_ids,
            "mount_path": self.mount_path,
            "merged_path": self.merged_path,
            "upper_path": self.upper_path,
            "work_path": self.work_path,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContainerMetadata":
        """Create from dictionary."""
        return cls(
            container_id=data["container_id"],
            image_id=data["image_id"],
            layer_ids=data.get("layer_ids", []),
            mount_path=data.get("mount_path", ""),
            merged_path=data.get("merged_path", ""),
            upper_path=data.get("upper_path", ""),
            work_path=data.get("work_path", ""),
            created_at=data.get("created_at", 0.0),
            size_bytes=data.get("size_bytes", 0),
        )


class StorageDriverBase(ABC):
    """Abstract base class for storage drivers."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    @abstractmethod
    def create_container_layer(self, container_id: str, image_layers: list[str]) -> str:
        """Create a writable container layer from image layers."""
        ...

    @abstractmethod
    def remove_container_layer(self, container_id: str) -> None:
        """Remove a container's writable layer."""
        ...

    @abstractmethod
    def mount_container(self, container_id: str) -> str:
        """Mount the container's filesystem and return the mount point."""
        ...

    @abstractmethod
    def unmount_container(self, container_id: str) -> None:
        """Unmount the container's filesystem."""
        ...

    @abstractmethod
    def create_snapshot(self, layer_id: str, parent_id: str) -> str:
        """Create a snapshot/child layer from a parent."""
        ...

    @abstractmethod
    def remove_layer(self, layer_id: str) -> None:
        """Remove a layer from storage."""
        ...

    @abstractmethod
    def layer_exists(self, layer_id: str) -> bool:
        """Check if a layer exists in storage."""
        ...

    @abstractmethod
    def get_layer_size(self, layer_id: str) -> int:
        """Get the size of a layer in bytes."""
        ...

    @abstractmethod
    def get_container_size(self, container_id: str) -> int:
        """Get the size of a container's writable layer."""
        ...

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up all storage resources."""
        ...


class Overlay2Driver(StorageDriverBase):
    """
    Overlay2 storage driver implementation.

    Uses Linux overlay/overlay2 filesystem for layered container images.
    Requires kernel 4.0+ with overlay support.
    """

    NAME = "overlay2"

    def __init__(self, root_dir: Path = STORAGE_DIR) -> None:
        super().__init__(root_dir)
        self.layers_dir = root_dir / "overlay2" / "layers"
        self.containers_dir = root_dir / "overlay2" / "containers"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create required directories."""
        self.layers_dir.mkdir(parents=True, exist_ok=True)
        self.containers_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _check_overlay_support() -> bool:
        """Check if the kernel supports overlay filesystem."""
        try:
            with open("/proc/filesystems") as f:
                content = f.read()
            return "overlay" in content
        except FileNotFoundError:
            return False

    def _get_layer_path(self, layer_id: str) -> Path:
        return self.layers_dir / layer_id

    def _get_diff_path(self, layer_id: str) -> Path:
        return self._get_layer_path(layer_id) / "diff"

    def _get_link_path(self, layer_id: str) -> Path:
        return self._get_layer_path(layer_id) / "link"

    def _get_lower_path(self, layer_id: str) -> Path:
        return self._get_layer_path(layer_id) / "lower"

    def _get_merged_path(self, container_id: str) -> Path:
        return self.containers_dir / container_id / "merged"

    def _get_upper_path(self, container_id: str) -> Path:
        return self.containers_dir / container_id / "upper"

    def _get_work_path(self, container_id: str) -> Path:
        return self.containers_dir / container_id / "work"

    def _get_metadata_path(self, layer_id: str) -> Path:
        return self._get_layer_path(layer_id) / "layer.json"

    def _get_container_metadata_path(self, container_id: str) -> Path:
        return self.containers_dir / container_id / "container.json"

    def _load_metadata(self, layer_id: str) -> Optional[LayerMetadata]:
        """Load layer metadata from disk."""
        path = self._get_metadata_path(layer_id)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return LayerMetadata.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load metadata for layer %s: %s", layer_id, e)
            return None

    def _save_metadata(self, meta: LayerMetadata) -> None:
        """Save layer metadata to disk."""
        path = self._get_metadata_path(meta.layer_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)

    def _load_container_metadata(self, container_id: str) -> Optional[ContainerMetadata]:
        """Load container metadata from disk."""
        path = self._get_container_metadata_path(container_id)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return ContainerMetadata.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load container metadata for %s: %s", container_id, e)
            return None

    def _save_container_metadata(self, meta: ContainerMetadata) -> None:
        """Save container metadata to disk."""
        path = self._get_container_metadata_path(meta.container_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)

    def create_layer(self, layer_id: str, parent_id: Optional[str] = None) -> None:
        """
        Create a new layer directory structure.

        Args:
            layer_id: ID for the new layer.
            parent_id: Optional parent layer ID.

        Raises:
            StorageError: If layer creation fails.
        """
        layer_path = self._get_layer_path(layer_id)
        try:
            layer_path.mkdir(parents=True, exist_ok=True)
            (layer_path / "diff").mkdir(exist_ok=True)
            (layer_path / "work").mkdir(exist_ok=True)

            # Write the link file (short name for kernel's overlay fs)
            link_name = f"L{layer_id[:8]}"
            (layer_path / "link").write_text(link_name)

            # Write the lower file if there's a parent
            if parent_id:
                parent_link = self._get_link_path(parent_id)
                if parent_link.exists():
                    parent_link_name = parent_link.read_text().strip()
                    (layer_path / "lower").write_text(f"l/{parent_link_name}")

            # Save metadata
            meta = LayerMetadata(
                layer_id=layer_id,
                parent_id=parent_id,
                created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                size_bytes=0,
                diff_path=str(self._get_diff_path(layer_id)),
            )
            self._save_metadata(meta)

            logger.debug("Created layer %s (parent: %s)", layer_id, parent_id)
        except OSError as e:
            raise StorageError(
                f"Failed to create layer {layer_id}: {e}", StorageDriver.OVERLAY2
            ) from e

    def create_container_layer(self, container_id: str, image_layers: list[str]) -> str:
        """
        Create a writable container layer from image layers.

        Args:
            container_id: Container identifier.
            image_layers: Ordered list of image layer IDs (base first).

        Returns:
            Path to the merged directory.
        """
        container_dir = self.containers_dir / container_id
        try:
            container_dir.mkdir(parents=True, exist_ok=True)
            (container_dir / "merged").mkdir(exist_ok=True)
            (container_dir / "upper").mkdir(exist_ok=True)
            (container_dir / "work").mkdir(exist_ok=True)

            merged_path = str(self._get_merged_path(container_id))

            meta = ContainerMetadata(
                container_id=container_id,
                image_id=image_layers[-1] if image_layers else "",
                layer_ids=image_layers,
                mount_path="",
                merged_path=merged_path,
                upper_path=str(self._get_upper_path(container_id)),
                work_path=str(self._get_work_path(container_id)),
                created_at=time.time(),
            )
            self._save_container_metadata(meta)

            logger.info("Created container layer for %s with %d image layers", container_id, len(image_layers))
            return merged_path
        except OSError as e:
            raise StorageError(
                f"Failed to create container layer for {container_id}: {e}",
                StorageDriver.OVERLAY2,
            ) from e

    def remove_container_layer(self, container_id: str) -> None:
        """Remove a container's writable layer."""
        container_dir = self.containers_dir / container_id
        try:
            self.unmount_container(container_id)
            if container_dir.exists():
                shutil.rmtree(container_dir, ignore_errors=True)
            logger.info("Removed container layer for %s", container_id)
        except OSError as e:
            raise StorageError(
                f"Failed to remove container layer for {container_id}: {e}",
                StorageDriver.OVERLAY2,
            ) from e

    def mount_container(self, container_id: str) -> str:
        """
        Mount the container's filesystem using overlay.

        Args:
            container_id: Container identifier.

        Returns:
            Mount point path.
        """
        if not self._check_overlay_support():
            logger.warning("Overlay filesystem not supported; using simulated mount")

        meta = self._load_container_metadata(container_id)
        if meta is None:
            raise StorageError(f"Container {container_id} not found", StorageDriver.OVERLAY2)

        # Build lowerdir string: order is bottom layer first, top layer last
        lower_dirs: list[str] = []
        for layer_id in meta.layer_ids:
            diff_path = self._get_diff_path(layer_id)
            if diff_path.exists():
                lower_dirs.append(str(diff_path))

        if not lower_dirs:
            # No image layers; use an empty dir
            empty_dir = self.layers_dir / "empty"
            empty_dir.mkdir(exist_ok=True)
            lower_dirs.append(str(empty_dir))

        lower_str = ":".join(lower_dirs)

        try:
            mount_cmd = [
                "mount", "-t", "overlay",
                "-o",
                f"lowerdir={lower_str},upperdir={meta.upper_path},workdir={meta.work_path}",
                "overlay",
                meta.merged_path,
            ]
            subprocess_result = self._run_mount(mount_cmd)
            if subprocess_result != 0:
                logger.warning("Overlay mount failed; using direct access")

            meta.mount_path = meta.merged_path
            self._save_container_metadata(meta)

            logger.info("Mounted container %s at %s", container_id, meta.merged_path)
            return meta.merged_path
        except Exception as e:
            raise StorageError(
                f"Failed to mount container {container_id}: {e}",
                StorageDriver.OVERLAY2,
            ) from e

    def _run_mount(self, cmd: list[str]) -> int:
        """Run a mount command."""
        try:
            import subprocess as sp
            result = sp.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode
        except (sp.TimeoutExpired, FileNotFoundError):
            return -1
        except Exception:
            return -1

    def unmount_container(self, container_id: str) -> None:
        """Unmount the container's filesystem."""
        meta = self._load_container_metadata(container_id)
        if meta is None:
            return

        merged_path = meta.merged_path
        if not os.path.ismount(merged_path):
            return

        try:
            import subprocess as sp
            sp.run(["umount", merged_path], check=True, capture_output=True, timeout=10)
            meta.mount_path = ""
            self._save_container_metadata(meta)
            logger.info("Unmounted container %s", container_id)
        except Exception as e:
            logger.warning("Failed to unmount container %s: %s", container_id, e)

    def create_snapshot(self, layer_id: str, parent_id: str) -> str:
        """
        Create a snapshot/child layer from a parent.

        Args:
            layer_id: ID for the new snapshot layer.
            parent_id: Parent layer ID.

        Returns:
            The new layer ID.
        """
        self.create_layer(layer_id, parent_id)

        # Copy parent diff contents
        parent_diff = self._get_diff_path(parent_id)
        new_diff = self._get_diff_path(layer_id)
        if parent_diff.exists() and new_diff.exists():
            try:
                shutil.copytree(parent_diff, new_diff, dirs_exist_ok=True)
            except OSError as e:
                logger.warning("Failed to copy parent diff: %s", e)

        # Update size
        size = self._calculate_dir_size(new_diff)
        meta = self._load_metadata(layer_id)
        if meta:
            meta.size_bytes = size
            self._save_metadata(meta)

        logger.info("Created snapshot %s from parent %s", layer_id, parent_id)
        return layer_id

    def remove_layer(self, layer_id: str) -> None:
        """Remove a layer from storage."""
        layer_path = self._get_layer_path(layer_id)
        if not layer_path.exists():
            logger.warning("Layer %s does not exist", layer_id)
            return
        try:
            shutil.rmtree(layer_path, ignore_errors=True)
            logger.info("Removed layer %s", layer_id)
        except OSError as e:
            raise StorageError(
                f"Failed to remove layer {layer_id}: {e}", StorageDriver.OVERLAY2
            ) from e

    def layer_exists(self, layer_id: str) -> bool:
        """Check if a layer exists in storage."""
        return self._get_layer_path(layer_id).exists()

    def get_layer_size(self, layer_id: str) -> int:
        """Get the size of a layer in bytes."""
        diff_path = self._get_diff_path(layer_id)
        if not diff_path.exists():
            return 0
        return self._calculate_dir_size(diff_path)

    def get_container_size(self, container_id: str) -> int:
        """Get the size of a container's writable layer."""
        upper_path = self._get_upper_path(container_id)
        if not upper_path.exists():
            return 0
        return self._calculate_dir_size(upper_path)

    @staticmethod
    def _calculate_dir_size(path: Path) -> int:
        """Calculate the total size of a directory recursively."""
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
        """Clean up all storage resources."""
        # Unmount all containers
        if self.containers_dir.exists():
            for container_dir in self.containers_dir.iterdir():
                if container_dir.is_dir():
                    self.unmount_container(container_dir.name)

        logger.info("Cleaned up overlay2 storage")

    def import_layer_from_tar(self, layer_id: str, tar_path: Path, parent_id: Optional[str] = None) -> LayerMetadata:
        """
        Import a layer from a tar archive.

        Args:
            layer_id: Layer ID to assign.
            tar_path: Path to the tar archive.
            parent_id: Optional parent layer ID.

        Returns:
            LayerMetadata for the imported layer.
        """
        import tarfile

        self.create_layer(layer_id, parent_id)
        diff_path = self._get_diff_path(layer_id)

        try:
            with tarfile.open(tar_path, "r:*") as tar:
                tar.extractall(path=diff_path, filter="data")
        except tarfile.TarError as e:
            raise StorageError(
                f"Failed to extract layer tar {tar_path}: {e}", StorageDriver.OVERLAY2
            ) from e

        # Calculate size and checksum
        size = self._calculate_dir_size(diff_path)
        checksum = self._calculate_checksum(diff_path)

        meta = LayerMetadata(
            layer_id=layer_id,
            parent_id=parent_id,
            created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            size_bytes=size,
            diff_path=str(diff_path),
            checksum=checksum,
        )
        self._save_metadata(meta)

        logger.info("Imported layer %s from tar %s (size=%d)", layer_id, tar_path, size)
        return meta

    @staticmethod
    def _calculate_checksum(path: Path) -> str:
        """Calculate SHA256 checksum of a directory."""
        sha = hashlib.sha256()
        try:
            for entry in sorted(path.rglob("*"), key=str):
                if entry.is_file():
                    try:
                        sha.update(entry.read_bytes())
                    except OSError:
                        continue
        except OSError:
            pass
        return sha.hexdigest()


class VFSDriver(StorageDriverBase):
    """
    VFS (Virtual File System) storage driver.

    Simple copy-based driver for testing environments.
    Each layer is a full copy of its parent with changes applied.
    """

    NAME = "vfs"

    def __init__(self, root_dir: Path = STORAGE_DIR) -> None:
        super().__init__(root_dir)
        self.layers_dir = root_dir / "vfs" / "layers"
        self.containers_dir = root_dir / "vfs" / "containers"
        self.layers_dir.mkdir(parents=True, exist_ok=True)
        self.containers_dir.mkdir(parents=True, exist_ok=True)

    def _get_layer_root(self, layer_id: str) -> Path:
        return self.layers_dir / layer_id

    def _get_container_root(self, container_id: str) -> Path:
        return self.containers_dir / container_id

    def create_container_layer(self, container_id: str, image_layers: list[str]) -> str:
        """Create a writable container layer by copying image layers."""
        container_root = self._get_container_root(container_id)
        if container_root.exists():
            shutil.rmtree(container_root)

        # Copy all image layers into the container root
        for layer_id in image_layers:
            layer_root = self._get_layer_root(layer_id)
            if layer_root.exists():
                shutil.copytree(layer_root, container_root, dirs_exist_ok=True)

        # Create a writable snapshot
        (container_root / ".ainos_upper").mkdir(exist_ok=True)
        logger.info("Created VFS container layer for %s", container_id)
        return str(container_root)

    def remove_container_layer(self, container_id: str) -> None:
        """Remove a container's writable layer."""
        container_root = self._get_container_root(container_id)
        if container_root.exists():
            shutil.rmtree(container_root, ignore_errors=True)

    def mount_container(self, container_id: str) -> str:
        """VFS: no mount needed, return the container root."""
        return str(self._get_container_root(container_id))

    def unmount_container(self, container_id: str) -> None:
        """VFS: no unmount needed."""

    def create_snapshot(self, layer_id: str, parent_id: str) -> str:
        """Create a snapshot by copying parent layer."""
        parent_root = self._get_layer_root(parent_id)
        layer_root = self._get_layer_root(layer_id)

        if parent_root.exists():
            shutil.copytree(parent_root, layer_root, dirs_exist_ok=True)
        else:
            layer_root.mkdir(parents=True, exist_ok=True)

        return layer_id

    def remove_layer(self, layer_id: str) -> None:
        """Remove a layer."""
        layer_root = self._get_layer_root(layer_id)
        if layer_root.exists():
            shutil.rmtree(layer_root, ignore_errors=True)

    def layer_exists(self, layer_id: str) -> bool:
        """Check if a layer exists."""
        return self._get_layer_root(layer_id).exists()

    def get_layer_size(self, layer_id: str) -> int:
        """Get the size of a layer."""
        layer_root = self._get_layer_root(layer_id)
        if not layer_root.exists():
            return 0
        return self._calculate_dir_size(layer_root)

    def get_container_size(self, container_id: str) -> int:
        """Get the size of a container."""
        container_root = self._get_container_root(container_id)
        if not container_root.exists():
            return 0
        return self._calculate_dir_size(container_root)

    @staticmethod
    def _calculate_dir_size(path: Path) -> int:
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
        """Clean up all VFS storage."""
        if self.layers_dir.exists():
            shutil.rmtree(self.layers_dir, ignore_errors=True)
        if self.containers_dir.exists():
            shutil.rmtree(self.containers_dir, ignore_errors=True)
        self.layers_dir.mkdir(parents=True)
        self.containers_dir.mkdir(parents=True)


class StorageManager:
    """
    Central storage manager.

    Coordinates between different storage drivers and provides
    a unified interface for container and image storage operations.
    """

    _instance: ClassVar[Optional["StorageManager"]] = None
    _drivers: ClassVar[dict[str, type[StorageDriverBase]]] = {
        "overlay2": Overlay2Driver,
        "vfs": VFSDriver,
    }

    def __new__(cls, *args: Any, **kwargs: Any) -> "StorageManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        driver_name: str = "overlay2",
        root_dir: Union[str, Path] = STORAGE_DIR,
    ) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True

        self.root_dir = Path(root_dir)
        self.driver_name = driver_name
        self._driver: StorageDriverBase = self._init_driver(driver_name)

    def _init_driver(self, name: str) -> StorageDriverBase:
        """Initialize the storage driver."""
        driver_cls = self._drivers.get(name)
        if driver_cls is None:
            supported = ", ".join(self._drivers.keys())
            raise StorageError(
                f"Unsupported storage driver: {name}. Supported: {supported}"
            )
        logger.info("Initialized storage driver: %s", name)
        return driver_cls(self.root_dir)

    @property
    def driver(self) -> StorageDriverBase:
        """Get the current storage driver."""
        return self._driver

    def switch_driver(self, name: str) -> None:
        """Switch to a different storage driver."""
        if name == self.driver_name:
            return
        self._driver.cleanup()
        self._driver = self._init_driver(name)
        self.driver_name = name
        logger.info("Switched storage driver to %s", name)

    @classmethod
    def register_driver(cls, name: str, driver_cls: type[StorageDriverBase]) -> None:
        """Register a custom storage driver."""
        cls._drivers[name] = driver_cls
        logger.info("Registered storage driver: %s", name)

    def create_container_storage(self, container_id: str, image_layers: list[str]) -> str:
        """
        Create storage for a container.

        Args:
            container_id: Container identifier.
            image_layers: Ordered list of image layer IDs.

        Returns:
            Mount point path for the container.
        """
        return self._driver.create_container_layer(container_id, image_layers)

    def remove_container_storage(self, container_id: str) -> None:
        """Remove a container's storage."""
        self._driver.remove_container_layer(container_id)

    def mount_container(self, container_id: str) -> str:
        """Mount a container's filesystem."""
        return self._driver.mount_container(container_id)

    def unmount_container(self, container_id: str) -> None:
        """Unmount a container's filesystem."""
        self._driver.unmount_container(container_id)

    def create_layer(self, layer_id: str, parent_id: Optional[str] = None) -> None:
        """Create a new layer."""
        self._driver.create_snapshot(layer_id, parent_id) if parent_id else None

    def remove_layer(self, layer_id: str) -> None:
        """Remove a layer."""
        self._driver.remove_layer(layer_id)

    def layer_exists(self, layer_id: str) -> bool:
        """Check if a layer exists."""
        return self._driver.layer_exists(layer_id)

    def get_layer_size(self, layer_id: str) -> int:
        """Get layer size."""
        return self._driver.get_layer_size(layer_id)

    def get_container_size(self, container_id: str) -> int:
        """Get container size."""
        return self._driver.get_container_size(container_id)

    def get_storage_info(self) -> dict[str, Any]:
        """Get storage information."""
        return {
            "driver": self.driver_name,
            "root_dir": str(self.root_dir),
            "layers_dir": str(self.root_dir / self.driver_name / "layers"),
            "containers_dir": str(self.root_dir / self.driver_name / "containers"),
        }

    def cleanup(self) -> None:
        """Clean up all storage."""
        self._driver.cleanup()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance."""
        cls._instance = None