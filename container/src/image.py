"""
镜像管理模块 - Image management for Ainos containers.

支持:
- OCI 镜像格式
- 镜像拉取/推送
- 镜像构建
- 镜像层管理
- 镜像标签和版本管理
- 镜像导出/导入
"""

import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

IMAGE_DIR = Path("/var/lib/ainos/images")


class ImageError(Exception):
    """Raised when an image operation fails."""
    def __init__(self, message: str, image_ref: Optional[str] = None) -> None:
        self.image_ref = image_ref
        super().__init__(f"Image{' ' + image_ref if image_ref else ''}: {message}")


@dataclass
class ImageLayer:
    """
    Represents a single layer in a container image.

    Each layer is a tar archive containing filesystem changes.
    """

    layer_id: str
    diff_id: str = ""
    parent_id: Optional[str] = None
    created: str = ""
    created_by: str = ""
    comment: str = ""
    size_bytes: int = 0
    compressed_size: int = 0
    digest: str = ""
    media_type: str = "application/vnd.oci.image.layer.v1.tar+gzip"
    urls: list[str] = field(default_factory=list)

    @property
    def short_id(self) -> str:
        return self.layer_id[:12] if len(self.layer_id) > 12 else self.layer_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "diff_id": self.diff_id,
            "parent_id": self.parent_id,
            "created": self.created,
            "created_by": self.created_by,
            "comment": self.comment,
            "size_bytes": self.size_bytes,
            "compressed_size": self.compressed_size,
            "digest": self.digest,
            "media_type": self.media_type,
            "urls": self.urls,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageLayer":
        return cls(
            layer_id=data.get("layer_id", data.get("digest", "")),
            diff_id=data.get("diff_id", ""),
            parent_id=data.get("parent_id"),
            created=data.get("created", ""),
            created_by=data.get("created_by", ""),
            comment=data.get("comment", ""),
            size_bytes=data.get("size_bytes", 0),
            compressed_size=data.get("compressed_size", 0),
            digest=data.get("digest", ""),
            media_type=data.get("media_type", "application/vnd.oci.image.layer.v1.tar+gzip"),
            urls=data.get("urls", []),
        )


@dataclass
class ImageConfig:
    """
    Container image configuration.

    Contains the image's configuration including environment,
    working directory, entrypoint, and user.
    """

    user: str = ""
    env: list[str] = field(default_factory=lambda: [
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    ])
    entrypoint: list[str] = field(default_factory=list)
    cmd: list[str] = field(default_factory=list)
    working_dir: str = "/"
    labels: dict[str, str] = field(default_factory=dict)
    exposed_ports: dict[str, dict[str, Any]] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)
    stop_signal: str = "SIGTERM"
    args_escaped: bool = True
    architecture: str = "amd64"
    os: str = "linux"
    created: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "Env": self.env,
            "Cmd": self.cmd,
            "WorkingDir": self.working_dir,
            "Labels": self.labels,
            "StopSignal": self.stop_signal,
            "ArgsEscaped": self.args_escaped,
            "architecture": self.architecture,
            "os": self.os,
        }
        if self.user:
            result["User"] = self.user
        if self.entrypoint:
            result["Entrypoint"] = self.entrypoint
        if self.exposed_ports:
            result["ExposedPorts"] = {p: {} for p in self.exposed_ports}
        if self.volumes:
            result["Volumes"] = {v: {} for v in self.volumes}
        if self.created:
            result["created"] = self.created
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageConfig":
        if "config" in data:
            data = data["config"]
        return cls(
            user=data.get("User", ""),
            env=data.get("Env", ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]),
            entrypoint=data.get("Entrypoint", []),
            cmd=data.get("Cmd", []),
            working_dir=data.get("WorkingDir", "/"),
            labels=data.get("Labels", {}),
            exposed_ports=data.get("ExposedPorts", {}),
            volumes=list(data.get("Volumes", {}).keys()),
            stop_signal=data.get("StopSignal", "SIGTERM"),
            args_escaped=data.get("ArgsEscaped", True),
            architecture=data.get("architecture", "amd64"),
            os=data.get("os", "linux"),
            created=data.get("created", ""),
        )


@dataclass
class ImageManifest:
    """
    OCI Image Manifest.

    References the image configuration and layers that compose the image.
    """

    schema_version: int = 2
    media_type: str = "application/vnd.oci.image.manifest.v1+json"
    config_digest: str = ""
    config_size: int = 0
    config_media_type: str = "application/vnd.oci.image.config.v1+json"
    layers: list[ImageLayer] = field(default_factory=list)
    annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "mediaType": self.media_type,
            "config": {
                "mediaType": self.config_media_type,
                "size": self.config_size,
                "digest": self.config_digest,
            },
            "layers": [
                {
                    "mediaType": l.media_type,
                    "size": l.compressed_size or l.size_bytes,
                    "digest": l.digest or l.layer_id,
                    "urls": l.urls if l.urls else None,
                }
                for l in self.layers
            ],
            "annotations": self.annotations if self.annotations else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageManifest":
        config = data.get("config", {})
        layers = []
        for l_data in data.get("layers", []):
            layer = ImageLayer(
                layer_id=l_data.get("digest", ""),
                digest=l_data.get("digest", ""),
                media_type=l_data.get("mediaType", "application/vnd.oci.image.layer.v1.tar+gzip"),
                compressed_size=l_data.get("size", 0),
                urls=l_data.get("urls", []),
            )
            layers.append(layer)
        return cls(
            schema_version=data.get("schemaVersion", 2),
            media_type=data.get("mediaType", "application/vnd.oci.image.manifest.v1+json"),
            config_digest=config.get("digest", ""),
            config_size=config.get("size", 0),
            config_media_type=config.get("mediaType", "application/vnd.oci.image.config.v1+json"),
            layers=layers,
            annotations=data.get("annotations", {}),
        )


@dataclass
class ImageIndex:
    """OCI Image Index (for multi-architecture images)."""
    schema_version: int = 2
    media_type: str = "application/vnd.oci.image.index.v1+json"
    manifests: list[dict[str, Any]] = field(default_factory=list)
    annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "mediaType": self.media_type,
            "manifests": self.manifests,
            "annotations": self.annotations if self.annotations else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageIndex":
        return cls(
            schema_version=data.get("schemaVersion", 2),
            media_type=data.get("mediaType", "application/vnd.oci.image.index.v1+json"),
            manifests=data.get("manifests", []),
            annotations=data.get("annotations", {}),
        )


@dataclass
class Image:
    """
    Complete container image representation.

    Combines manifest, config, and layers into a single image object.
    """

    name: str = ""
    tag: str = "latest"
    manifest: ImageManifest = field(default_factory=ImageManifest)
    config: ImageConfig = field(default_factory=ImageConfig)
    layers: list[ImageLayer] = field(default_factory=list)
    digest: str = ""
    size: int = 0
    created_at: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def reference(self) -> str:
        """Full image reference (name:tag)."""
        return f"{self.name}:{self.tag}"

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    @property
    def total_size(self) -> int:
        return sum(l.size_bytes for l in self.layers) + self.manifest.config_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tag": self.tag,
            "reference": self.reference,
            "digest": self.digest,
            "size": self.size,
            "created_at": self.created_at,
            "labels": self.labels,
            "layer_count": self.layer_count,
            "config": self.config.to_dict(),
            "manifest": self.manifest.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Image":
        return cls(
            name=data.get("name", ""),
            tag=data.get("tag", "latest"),
            manifest=ImageManifest.from_dict(data.get("manifest", {})),
            config=ImageConfig.from_dict(data.get("config", {})),
            digest=data.get("digest", ""),
            size=data.get("size", 0),
            created_at=data.get("created_at", ""),
            labels=data.get("labels", {}),
        )


class ImageManager:
    """
    Central image manager.

    Handles image lifecycle including pulling, pushing, building,
    tagging, and layer management.
    """

    def __init__(self, image_dir: Union[str, Path] = IMAGE_DIR) -> None:
        self.image_dir = Path(image_dir)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self._images: dict[str, Image] = {}
        self._load_images()

    def _image_path(self, name: str, tag: str) -> Path:
        return self.image_dir / name / tag

    def _layers_path(self) -> Path:
        return self.image_dir / "_layers"

    def _load_images(self) -> None:
        """Load all images from the image directory."""
        if not self.image_dir.exists():
            return

        for name_dir in self.image_dir.iterdir():
            if not name_dir.is_dir() or name_dir.name.startswith("_"):
                continue
            for tag_dir in name_dir.iterdir():
                if not tag_dir.is_dir():
                    continue
                manifest_path = tag_dir / "manifest.json"
                config_path = tag_dir / "config.json"
                if manifest_path.exists() and config_path.exists():
                    try:
                        manifest = ImageManifest.from_dict(json.loads(manifest_path.read_text()))
                        config = ImageConfig.from_dict(json.loads(config_path.read_text()))
                        image = Image(
                            name=name_dir.name,
                            tag=tag_dir.name,
                            manifest=manifest,
                            config=config,
                        )
                        key = image.reference
                        self._images[key] = image
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning("Failed to load image %s:%s: %s", name_dir.name, tag_dir.name, e)

        logger.debug("Loaded %d images", len(self._images))

    def list_images(self, name_filter: Optional[str] = None) -> list[Image]:
        """List all images, optionally filtered by name."""
        images = list(self._images.values())
        if name_filter:
            images = [img for img in images if name_filter in img.name]
        return sorted(images, key=lambda x: x.reference)

    def get_image(self, name: str, tag: str = "latest") -> Optional[Image]:
        """Get an image by name and tag."""
        return self._images.get(f"{name}:{tag}")

    def image_exists(self, name: str, tag: str = "latest") -> bool:
        """Check if an image exists."""
        return f"{name}:{tag}" in self._images

    def remove_image(self, name: str, tag: str = "latest") -> None:
        """Remove an image and its layers."""
        key = f"{name}:{tag}"
        if key not in self._images:
            raise ImageError(f"Image not found: {key}", key)

        image = self._images[key]
        image_path = self._image_path(name, tag)

        # Remove image directory
        if image_path.exists():
            shutil.rmtree(image_path, ignore_errors=True)

        # Clean up orphaned layers
        self._cleanup_layers()

        del self._images[key]
        logger.info("Removed image %s:%s", name, tag)

    def tag_image(self, source_name: str, source_tag: str,
                  target_name: str, target_tag: str = "latest") -> None:
        """Tag an existing image with a new name:tag."""
        key = f"{source_name}:{source_tag}"
        if key not in self._images:
            raise ImageError(f"Image not found: {key}", key)

        source_img = self._images[key]
        new_key = f"{target_name}:{target_tag}"

        # Create a shallow copy
        new_img = Image(
            name=target_name,
            tag=target_tag,
            manifest=source_img.manifest,
            config=source_img.config,
            layers=list(source_img.layers),
            digest=source_img.digest,
            size=source_img.size,
            created_at=source_img.created_at,
            labels=dict(source_img.labels),
        )
        self._images[new_key] = new_img

        # Save tag
        target_path = self._image_path(target_name, target_tag)
        target_path.mkdir(parents=True, exist_ok=True)
        with open(target_path / "manifest.json", "w") as f:
            json.dump(new_img.manifest.to_dict(), f, indent=2)
        with open(target_path / "config.json", "w") as f:
            json.dump(new_img.config.to_dict(), f, indent=2)

        logger.info("Tagged image %s -> %s:%s", key, target_name, target_tag)

    def prune_images(self) -> int:
        """Remove unused images (no tags)."""
        # Check for orphaned image directories
        removed = 0
        for name_dir in self.image_dir.iterdir():
            if not name_dir.is_dir() or name_dir.name.startswith("_"):
                continue
            for tag_dir in name_dir.iterdir():
                if not tag_dir.is_dir():
                    continue
                key = f"{name_dir.name}:{tag_dir.name}"
                if key not in self._images:
                    shutil.rmtree(tag_dir, ignore_errors=True)
                    removed += 1

        if removed:
            logger.info("Pruned %d orphaned images", removed)
        return removed

    def _cleanup_layers(self) -> None:
        """Remove orphaned layers not referenced by any image."""
        layers_dir = self._layers_path()
        if not layers_dir.exists():
            return

        referenced_layers: set[str] = set()
        for image in self._images.values():
            for layer in image.layers:
                referenced_layers.add(layer.layer_id)

        for layer_dir in layers_dir.iterdir():
            if layer_dir.is_dir() and layer_dir.name not in referenced_layers:
                shutil.rmtree(layer_dir, ignore_errors=True)
                logger.debug("Removed orphaned layer: %s", layer_dir.name)

    def pull_image(self, reference: str, registry_client: Optional[Any] = None) -> Image:
        """
        Pull an image from a registry.

        Args:
            reference: Image reference (e.g., "ubuntu:22.04" or "registry.example.com/ubuntu:22.04").
            registry_client: Registry client for pulling.

        Returns:
            The pulled Image object.

        Raises:
            ImageError: If pulling fails.
        """
        if registry_client is None:
            # Use default registry client
            from src.registry import RegistryClient
            registry_client = RegistryClient()

        try:
            image = registry_client.pull(reference)
            self._images[image.reference] = image

            # Save to local storage
            image_path = self._image_path(image.name, image.tag)
            image_path.mkdir(parents=True, exist_ok=True)
            with open(image_path / "manifest.json", "w") as f:
                json.dump(image.manifest.to_dict(), f, indent=2)
            with open(image_path / "config.json", "w") as f:
                json.dump(image.config.to_dict(), f, indent=2)

            logger.info("Pulled image %s", reference)
            return image
        except Exception as e:
            raise ImageError(f"Failed to pull image {reference}: {e}", reference) from e

    def push_image(self, name: str, tag: str = "latest",
                   registry_client: Optional[Any] = None) -> None:
        """Push an image to a registry."""
        key = f"{name}:{tag}"
        if key not in self._images:
            raise ImageError(f"Image not found: {key}", key)

        if registry_client is None:
            from src.registry import RegistryClient
            registry_client = RegistryClient()

        try:
            registry_client.push(self._images[key])
            logger.info("Pushed image %s:%s", name, tag)
        except Exception as e:
            raise ImageError(f"Failed to push image {name}:{tag}: {e}", key) from e

    def build_image(self, name: str, tag: str = "latest",
                    base_image: Optional[str] = None,
                    commands: Optional[list[tuple[str, ...]]] = None,
                    layers_dir: Optional[Path] = None) -> Image:
        """
        Build a new image from layers or base image.

        Args:
            name: Image name.
            tag: Image tag.
            base_image: Optional base image reference.
            commands: Optional list of build commands.
            layers_dir: Optional directory containing layer tarballs.

        Returns:
            The built Image object.
        """
        image = Image(name=name, tag=tag, created_at=datetime.utcnow().isoformat())

        # If base image specified, start from it
        if base_image:
            base = self.get_image(*base_image.split(":"))
            if base is None:
                raise ImageError(f"Base image not found: {base_image}", base_image)
            image.layers = list(base.layers)
            image.config = ImageConfig(
                env=list(base.config.env),
                entrypoint=list(base.config.entrypoint),
                cmd=list(base.config.cmd),
                working_dir=base.config.working_dir,
                labels=dict(base.config.labels),
            )

        # Process custom layers
        if layers_dir and layers_dir.exists():
            for layer_tar in sorted(layers_dir.glob("*.tar*")):
                layer_id = hashlib.sha256(layer_tar.read_bytes()).hexdigest()
                size = layer_tar.stat().st_size
                layer = ImageLayer(
                    layer_id=layer_id,
                    diff_id=layer_id,
                    size_bytes=size,
                    compressed_size=size,
                    digest=f"sha256:{layer_id}",
                    created=datetime.utcnow().isoformat(),
                )
                image.layers.append(layer)

        # Build manifest
        config_bytes = json.dumps(image.config.to_dict()).encode()
        config_digest = f"sha256:{hashlib.sha256(config_bytes).hexdigest()}"

        image.manifest = ImageManifest(
            config_digest=config_digest,
            config_size=len(config_bytes),
            layers=image.layers,
            annotations={
                "org.opencontainers.image.created": image.created_at,
                "org.opencontainers.image.version": tag,
            },
        )
        image.digest = hashlib.sha256(
            json.dumps(image.manifest.to_dict()).encode()
        ).hexdigest()
        image.size = image.total_size

        # Save
        image_path = self._image_path(name, tag)
        image_path.mkdir(parents=True, exist_ok=True)
        with open(image_path / "manifest.json", "w") as f:
            json.dump(image.manifest.to_dict(), f, indent=2)
        with open(image_path / "config.json", "w") as f:
            json.dump(image.config.to_dict(), f, indent=2)

        self._images[image.reference] = image
        logger.info("Built image %s:%s (%d layers, %d bytes)", name, tag, len(image.layers), image.size)
        return image

    def export_image(self, name: str, tag: str, output_path: Union[str, Path]) -> Path:
        """
        Export an image as a tar archive.

        Args:
            name: Image name.
            tag: Image tag.
            output_path: Destination path for the tar archive.

        Returns:
            Path to the exported archive.
        """
        output_path = Path(output_path)
        image = self.get_image(name, tag)
        if image is None:
            raise ImageError(f"Image not found: {name}:{tag}", f"{name}:{tag}")

        try:
            with tarfile.open(output_path, "w:gz") as tar:
                # Save manifest
                manifest_bytes = json.dumps(image.manifest.to_dict()).encode()
                tarinfo = tarfile.TarInfo(name="manifest.json")
                tarinfo.size = len(manifest_bytes)
                tar.addfile(tarinfo, io.BytesIO(manifest_bytes))

                # Save config
                config_bytes = json.dumps(image.config.to_dict()).encode()
                tarinfo = tarfile.TarInfo(name="config.json")
                tarinfo.size = len(config_bytes)
                tar.addfile(tarinfo, io.BytesIO(config_bytes))

                # Save layers
                layers_dir = self._layers_path()
                for i, layer in enumerate(image.layers):
                    layer_path = layers_dir / layer.layer_id / "layer.tar"
                    if layer_path.exists():
                        tar.add(str(layer_path), arcname=f"layers/{i}.tar")

            logger.info("Exported image %s:%s to %s", name, tag, output_path)
            return output_path
        except (tarfile.TarError, OSError) as e:
            raise ImageError(f"Failed to export image: {e}", f"{name}:{tag}") from e

    def import_image(self, archive_path: Union[str, Path]) -> Image:
        """
        Import an image from a tar archive.

        Args:
            archive_path: Path to the image archive.

        Returns:
            The imported Image object.
        """
        import io

        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise ImageError(f"Archive not found: {archive_path}")

        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                manifest_data = json.loads(tar.extractfile("manifest.json").read())
                config_data = json.loads(tar.extractfile("config.json").read())

                # Extract layers
                layers_dir = self._layers_path()
                for member in tar.getmembers():
                    if member.name.startswith("layers/"):
                        layer_file = tar.extractfile(member)
                        if layer_file:
                            layer_data = layer_file.read()
                            layer_id = hashlib.sha256(layer_data).hexdigest()
                            layer_path = layers_dir / layer_id
                            layer_path.mkdir(parents=True, exist_ok=True)
                            (layer_path / "layer.tar").write_bytes(layer_data)

            manifest = ImageManifest.from_dict(manifest_data)
            config = ImageConfig.from_dict(config_data)

            # Determine name and tag from labels or use defaults
            name = config.labels.get("org.opencontainers.image.name", "imported")
            tag = config.labels.get("org.opencontainers.image.version", "latest")

            image = Image(
                name=name,
                tag=tag,
                manifest=manifest,
                config=config,
                created_at=config.created or datetime.utcnow().isoformat(),
            )

            # Save
            image_path = self._image_path(name, tag)
            image_path.mkdir(parents=True, exist_ok=True)
            with open(image_path / "manifest.json", "w") as f:
                json.dump(manifest.to_dict(), f, indent=2)
            with open(image_path / "config.json", "w") as f:
                json.dump(config.to_dict(), f, indent=2)

            self._images[image.reference] = image
            logger.info("Imported image from %s as %s:%s", archive_path, name, tag)
            return image

        except (tarfile.TarError, json.JSONDecodeError, OSError, KeyError) as e:
            raise ImageError(f"Failed to import image from {archive_path}: {e}") from e

    def get_image_layers(self, name: str, tag: str = "latest") -> list[ImageLayer]:
        """Get the layers of an image."""
        image = self.get_image(name, tag)
        if image is None:
            raise ImageError(f"Image not found: {name}:{tag}", f"{name}:{tag}")
        return image.layers

    def get_image_info(self, name: str, tag: str = "latest") -> dict[str, Any]:
        """Get detailed information about an image."""
        image = self.get_image(name, tag)
        if image is None:
            raise ImageError(f"Image not found: {name}:{tag}", f"{name}:{tag}")

        return {
            "name": image.name,
            "tag": image.tag,
            "reference": image.reference,
            "digest": image.digest,
            "size": image.size,
            "total_size": image.total_size,
            "layer_count": image.layer_count,
            "created_at": image.created_at,
            "labels": image.labels,
            "config": {
                "entrypoint": image.config.entrypoint,
                "cmd": image.config.cmd,
                "working_dir": image.config.working_dir,
                "user": image.config.user,
                "env_count": len(image.config.env),
                "exposed_ports": list(image.config.exposed_ports.keys()),
                "volumes": image.config.volumes,
            },
            "layers": [
                {
                    "id": l.short_id,
                    "size": l.size_bytes,
                    "created": l.created,
                    "command": l.created_by,
                }
                for l in image.layers
            ],
        }

    def cleanup(self) -> None:
        """Clean up image resources."""
        self._images.clear()
        logger.info("Cleaned up image manager")