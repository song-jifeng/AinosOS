"""
Checkpoint management module for the Ainos training framework.

Provides functionality for saving and loading training checkpoints,
including model weights, optimizer state, scheduler state, and metadata.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


@dataclass
class CheckpointMetadata:
    """Metadata stored in each checkpoint.

    Attributes:
        epoch: Current epoch number.
        global_step: Global training step.
        best_metric: Best metric value achieved.
        best_metric_name: Name of the best metric.
        train_loss: Training loss at checkpoint.
        val_loss: Validation loss at checkpoint.
        learning_rate: Current learning rate.
        model_name: Name of the model architecture.
        optimizer_name: Name of the optimizer.
        scheduler_name: Name of the scheduler.
        framework_version: Version of the training framework.
        timestamp: ISO timestamp when checkpoint was saved.
        duration: Training duration in seconds up to this point.
        extra: Additional metadata.
    """

    epoch: int = 0
    global_step: int = 0
    best_metric: float = 0.0
    best_metric_name: str = ""
    train_loss: float = 0.0
    val_loss: float = 0.0
    learning_rate: float = 0.0
    model_name: str = ""
    optimizer_name: str = ""
    scheduler_name: str = ""
    framework_version: str = "0.1.0"
    timestamp: str = ""
    duration: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


class CheckpointManager:
    """Manages saving and loading of training checkpoints.

    Features:
    - Save/load model, optimizer, and scheduler states
    - Keep only the top-k best checkpoints
    - Periodic saving at regular intervals
    - Resume from the latest or best checkpoint
    - Checkpoint metadata and history tracking
    """

    def __init__(
        self,
        checkpoint_dir: Union[str, Path],
        model: nn.Module,
        optimizer: Optional[torch.optim.Optimizer] = None,
        scheduler: Optional[Any] = None,
        max_keep: int = 5,
        save_best: bool = True,
        save_optimizer: bool = True,
        save_scheduler: bool = True,
        metric_mode: str = "max",
        save_every_n_epochs: int = 0,
        save_every_n_steps: int = 0,
        keep_checkpoint_every_n_hours: float = 0.0,
        prefix: str = "checkpoint",
        include_train_state: bool = True,
    ) -> None:
        """Initialize the checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoints.
            model: The model to checkpoint.
            optimizer: The optimizer to checkpoint.
            scheduler: The scheduler to checkpoint.
            max_keep: Maximum number of checkpoints to keep.
            save_best: Whether to save the best checkpoint separately.
            save_optimizer: Whether to save optimizer state.
            save_scheduler: Whether to save scheduler state.
            metric_mode: 'max' or 'min' for determining best checkpoint.
            save_every_n_epochs: Save a checkpoint every N epochs (0 = disabled).
            save_every_n_steps: Save a checkpoint every N steps (0 = disabled).
            keep_checkpoint_every_n_hours: Keep a checkpoint every N hours.
            prefix: Prefix for checkpoint filenames.
            include_train_state: Whether to include training state (epoch, step, etc.).
        """
        self._checkpoint_dir = Path(checkpoint_dir)
        self._model = model
        self._optimizer = optimizer
        self._scheduler = scheduler
        self._max_keep = max_keep
        self._save_best = save_best
        self._save_optimizer = save_optimizer
        self._save_scheduler = save_scheduler
        self._metric_mode = metric_mode
        self._save_every_n_epochs = save_every_n_epochs
        self._save_every_n_steps = save_every_n_steps
        self._keep_checkpoint_every_n_hours = keep_checkpoint_every_n_hours
        self._prefix = prefix
        self._include_train_state = include_train_state

        # Create checkpoint directory
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # State tracking
        self._best_metric: float = float("-inf") if metric_mode == "max" else float("inf")
        self._best_epoch: int = 0
        self._checkpoint_history: List[Dict[str, Any]] = []
        self._last_save_time: float = time.time()
        self._last_kept_hour: int = 0

        # Load existing checkpoint history
        self._load_history()

        logger.info(
            f"Checkpoint manager initialized. Directory: {self._checkpoint_dir}"
        )

    def _load_history(self) -> None:
        """Load checkpoint history from the checkpoint directory."""
        history_file = self._checkpoint_dir / "checkpoint_history.json"
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._checkpoint_history = data.get("history", [])
                    self._best_metric = data.get("best_metric", self._best_metric)
                    self._best_epoch = data.get("best_epoch", 0)
                logger.info(
                    f"Loaded checkpoint history: {len(self._checkpoint_history)} entries"
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load checkpoint history: {e}")

    def _save_history(self) -> None:
        """Save checkpoint history to the checkpoint directory."""
        history_file = self._checkpoint_dir / "checkpoint_history.json"
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "history": self._checkpoint_history,
                        "best_metric": self._best_metric,
                        "best_epoch": self._best_epoch,
                    },
                    f,
                    indent=2,
                )
        except IOError as e:
            logger.warning(f"Failed to save checkpoint history: {e}")

    def save(
        self,
        epoch: int,
        global_step: int,
        metric: Optional[float] = None,
        metric_name: str = "",
        train_loss: float = 0.0,
        val_loss: float = 0.0,
        duration: float = 0.0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Save a checkpoint.

        Args:
            epoch: Current epoch number.
            global_step: Current global training step.
            metric: Current metric value (for determining best).
            metric_name: Name of the metric.
            train_loss: Current training loss.
            val_loss: Current validation loss.
            duration: Training duration in seconds.
            extra: Additional metadata.

        Returns:
            Path to the saved checkpoint file.
        """
        # Build metadata
        metadata = CheckpointMetadata(
            epoch=epoch,
            global_step=global_step,
            best_metric=self._best_metric,
            best_metric_name=metric_name,
            train_loss=train_loss,
            val_loss=val_loss,
            learning_rate=self._get_lr(),
            model_name=self._model.__class__.__name__,
            optimizer_name=self._optimizer.__class__.__name__ if self._optimizer else "",
            scheduler_name=self._scheduler.__class__.__name__ if self._scheduler else "",
            timestamp=datetime.now().isoformat(),
            duration=duration,
            extra=extra or {},
        )

        # Build state dict
        state_dict: Dict[str, Any] = {
            "metadata": asdict(metadata),
            "model_state_dict": self._model.state_dict(),
        }

        if self._save_optimizer and self._optimizer is not None:
            state_dict["optimizer_state_dict"] = self._optimizer.state_dict()

        if self._save_scheduler and self._scheduler is not None:
            if hasattr(self._scheduler, "state_dict"):
                state_dict["scheduler_state_dict"] = self._scheduler.state_dict()
            elif hasattr(self._scheduler, "state_dict"):
                state_dict["scheduler_state_dict"] = self._scheduler.state_dict()

        # Determine filename
        if metric is not None and metric_name:
            filename = f"{self._prefix}_epoch{epoch}_step{global_step}_{metric_name}{metric:.4f}.pt"
        else:
            filename = f"{self._prefix}_epoch{epoch}_step{global_step}.pt"

        filepath = self._checkpoint_dir / filename

        # Save checkpoint
        logger.info(f"Saving checkpoint to {filepath}")
        try:
            torch.save(state_dict, filepath)
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            raise

        # Save best checkpoint separately
        if metric is not None and self._save_best:
            self._update_best(metric, epoch, filepath)

        # Periodic checkpoint
        if self._save_every_n_hours > 0:
            self._save_periodic(state_dict, epoch, global_step)

        # Add to history
        history_entry = {
            "path": str(filepath),
            "epoch": epoch,
            "global_step": global_step,
            "metric": metric,
            "metric_name": metric_name,
            "timestamp": metadata.timestamp,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "filesize_mb": filepath.stat().st_size / (1024 * 1024) if filepath.exists() else 0,
        }
        self._checkpoint_history.append(history_entry)

        # Prune old checkpoints
        self._prune_checkpoints()

        # Save history
        self._save_history()

        return str(filepath)

    def _update_best(
        self, metric: float, epoch: int, filepath: Path
    ) -> None:
        """Update the best checkpoint if the current metric is better.

        Args:
            metric: Current metric value.
            epoch: Current epoch.
            filepath: Path to the current checkpoint file.
        """
        is_better = (
            metric > self._best_metric
            if self._metric_mode == "max"
            else metric < self._best_metric
        )

        if is_better:
            # Remove old best checkpoint
            old_best = self._checkpoint_dir / "best_model.pt"
            if old_best.exists():
                old_best.unlink()

            # Copy current checkpoint as best
            shutil.copy2(filepath, self._checkpoint_dir / "best_model.pt")

            # Save best model weights separately
            torch.save(
                self._model.state_dict(),
                self._checkpoint_dir / "best_model_weights.pt",
            )

            self._best_metric = metric
            self._best_epoch = epoch
            logger.info(
                f"New best model: {metric:.4f} (epoch {epoch})"
            )

    def _save_periodic(
        self, state_dict: Dict[str, Any], epoch: int, global_step: int
    ) -> None:
        """Save a periodic checkpoint (every N hours).

        Args:
            state_dict: The checkpoint state dict.
            epoch: Current epoch.
            global_step: Current global step.
        """
        current_hour = int(time.time() / 3600)
        if current_hour > self._last_kept_hour + self._keep_checkpoint_every_n_hours:
            filename = (
                f"{self._prefix}_periodic_epoch{epoch}_step{global_step}.pt"
            )
            filepath = self._checkpoint_dir / filename
            torch.save(state_dict, filepath)
            self._last_kept_hour = current_hour
            logger.info(f"Saved periodic checkpoint: {filepath}")

    def _prune_checkpoints(self) -> None:
        """Remove old checkpoints, keeping only the most recent ones."""
        if self._max_keep <= 0:
            return

        # Get all checkpoint files (excluding best and periodic)
        checkpoint_files = sorted(
            [
                p
                for p in self._checkpoint_dir.glob(f"{self._prefix}_epoch*.pt")
                if "best" not in p.stem and "periodic" not in p.stem
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        # Remove old checkpoints
        while len(checkpoint_files) > self._max_keep:
            old_file = checkpoint_files.pop()
            try:
                old_file.unlink()
                logger.info(f"Removed old checkpoint: {old_file}")
            except OSError as e:
                logger.warning(f"Failed to remove checkpoint {old_file}: {e}")

        # Update history
        kept_paths = {str(p) for p in checkpoint_files}
        if (self._checkpoint_dir / "best_model.pt").exists():
            kept_paths.add(str(self._checkpoint_dir / "best_model.pt"))

        self._checkpoint_history = [
            entry
            for entry in self._checkpoint_history
            if entry["path"] in kept_paths
        ]

    def load_latest(
        self,
        map_location: Optional[Union[str, torch.device]] = None,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """Load the latest checkpoint.

        Args:
            map_location: Device to map the checkpoint to.
            strict: Whether to strictly enforce state dict key matching.

        Returns:
            Checkpoint metadata.

        Raises:
            FileNotFoundError: If no checkpoint is found.
        """
        checkpoint_files = sorted(
            list(self._checkpoint_dir.glob(f"{self._prefix}_epoch*.pt")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not checkpoint_files:
            raise FileNotFoundError(
                f"No checkpoint found in {self._checkpoint_dir}"
            )

        return self.load(str(checkpoint_files[0]), map_location, strict)

    def load_best(
        self,
        map_location: Optional[Union[str, torch.device]] = None,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """Load the best checkpoint.

        Args:
            map_location: Device to map the checkpoint to.
            strict: Whether to strictly enforce state dict key matching.

        Returns:
            Checkpoint metadata.

        Raises:
            FileNotFoundError: If no best checkpoint is found.
        """
        best_path = self._checkpoint_dir / "best_model.pt"
        if not best_path.exists():
            # Try to find the best based on history
            if self._checkpoint_history:
                best_entry = max(
                    self._checkpoint_history,
                    key=lambda e: e.get("metric", 0.0) or 0.0,
                )
                best_path = Path(best_entry["path"])
                if not best_path.exists():
                    raise FileNotFoundError(
                        f"Best checkpoint not found at {best_path}"
                    )
            else:
                raise FileNotFoundError(
                    f"No best checkpoint found in {self._checkpoint_dir}"
                )

        return self.load(str(best_path), map_location, strict)

    def load(
        self,
        checkpoint_path: Union[str, Path],
        map_location: Optional[Union[str, torch.device]] = None,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """Load a specific checkpoint.

        Args:
            checkpoint_path: Path to the checkpoint file.
            map_location: Device to map the checkpoint to.
            strict: Whether to strictly enforce state dict key matching.

        Returns:
            Checkpoint metadata dictionary.

        Raises:
            FileNotFoundError: If the checkpoint file doesn't exist.
        """
        checkpoint_path = Path(checkpoint_path)

        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        logger.info(f"Loading checkpoint from {checkpoint_path}")

        try:
            checkpoint = torch.load(checkpoint_path, map_location=map_location)
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            raise

        # Load model state
        if "model_state_dict" in checkpoint:
            missing, unexpected = self._model.load_state_dict(
                checkpoint["model_state_dict"], strict=strict
            )
            if missing:
                logger.warning(f"Missing keys in checkpoint: {missing}")
            if unexpected:
                logger.warning(f"Unexpected keys in checkpoint: {unexpected}")

        # Load optimizer state
        if self._save_optimizer and self._optimizer is not None:
            if "optimizer_state_dict" in checkpoint:
                try:
                    self._optimizer.load_state_dict(
                        checkpoint["optimizer_state_dict"]
                    )
                except ValueError as e:
                    logger.warning(
                        f"Failed to load optimizer state: {e}. "
                        "This may be due to model/optimizer changes."
                    )

        # Load scheduler state
        if self._save_scheduler and self._scheduler is not None:
            if "scheduler_state_dict" in checkpoint:
                try:
                    if hasattr(self._scheduler, "load_state_dict"):
                        self._scheduler.load_state_dict(
                            checkpoint["scheduler_state_dict"]
                        )
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"Failed to load scheduler state: {e}"
                    )

        metadata = checkpoint.get("metadata", {})
        logger.info(
            f"Loaded checkpoint: epoch {metadata.get('epoch', '?')}, "
            f"step {metadata.get('global_step', '?')}"
        )

        return metadata

    def load_weights(
        self,
        weights_path: Union[str, Path],
        map_location: Optional[Union[str, torch.device]] = None,
        strict: bool = True,
    ) -> None:
        """Load only model weights from a checkpoint.

        Args:
            weights_path: Path to the weights file.
            map_location: Device to map the weights to.
            strict: Whether to strictly enforce state dict key matching.
        """
        weights_path = Path(weights_path)

        if not weights_path.exists():
            raise FileNotFoundError(f"Weights file not found: {weights_path}")

        logger.info(f"Loading model weights from {weights_path}")

        try:
            state_dict = torch.load(weights_path, map_location=map_location)
        except Exception as e:
            logger.error(f"Failed to load weights: {e}")
            raise

        # Handle checkpoint files that contain more than just state dict
        if "model_state_dict" in state_dict:
            state_dict = state_dict["model_state_dict"]

        missing, unexpected = self._model.load_state_dict(state_dict, strict=strict)
        if missing:
            logger.warning(f"Missing keys when loading weights: {missing}")
        if unexpected:
            logger.warning(f"Unexpected keys when loading weights: {unexpected}")

        logger.info("Model weights loaded successfully.")

    def resume_from_checkpoint(
        self,
        load_best: bool = False,
        map_location: Optional[Union[str, torch.device]] = None,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """Resume training from the latest or best checkpoint.

        Args:
            load_best: If True, load the best checkpoint; otherwise load the latest.
            map_location: Device to map the checkpoint to.
            strict: Whether to strictly enforce state dict key matching.

        Returns:
            Checkpoint metadata with epoch and step info.
        """
        try:
            if load_best:
                metadata = self.load_best(map_location, strict)
            else:
                metadata = self.load_latest(map_location, strict)
        except FileNotFoundError:
            logger.info("No checkpoint found, starting from scratch.")
            return {
                "epoch": 0,
                "global_step": 0,
                "best_metric": (
                    float("-inf") if self._metric_mode == "max" else float("inf")
                ),
            }

        # Update best metric tracking
        best_metric = metadata.get("best_metric", None)
        if best_metric is not None:
            if self._metric_mode == "max":
                self._best_metric = max(self._best_metric, best_metric)
            else:
                self._best_metric = min(self._best_metric, best_metric)

        return metadata

    def get_latest_checkpoint(self) -> Optional[str]:
        """Get the path to the latest checkpoint.

        Returns:
            Path to the latest checkpoint, or None if no checkpoints exist.
        """
        checkpoint_files = sorted(
            list(self._checkpoint_dir.glob(f"{self._prefix}_epoch*.pt")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return str(checkpoint_files[0]) if checkpoint_files else None

    def get_best_checkpoint(self) -> Optional[str]:
        """Get the path to the best checkpoint.

        Returns:
            Path to the best checkpoint, or None if it doesn't exist.
        """
        best_path = self._checkpoint_dir / "best_model.pt"
        return str(best_path) if best_path.exists() else None

    def get_checkpoint_history(self) -> List[Dict[str, Any]]:
        """Get the checkpoint history.

        Returns:
            List of checkpoint history entries.
        """
        return list(self._checkpoint_history)

    def get_best_metric(self) -> float:
        """Get the best metric value.

        Returns:
            The best metric value.
        """
        return self._best_metric

    def get_best_epoch(self) -> int:
        """Get the epoch of the best checkpoint.

        Returns:
            The best epoch number.
        """
        return self._best_epoch

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all available checkpoints.

        Returns:
            List of checkpoint info dictionaries.
        """
        checkpoints = []
        for f in sorted(
            self._checkpoint_dir.glob("*.pt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            checkpoints.append({
                "path": str(f),
                "filename": f.name,
                "size_mb": f.stat().st_size / (1024 * 1024),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return checkpoints

    def export_best_weights(self, output_path: Union[str, Path]) -> str:
        """Export the best model weights to a separate file.

        Args:
            output_path: Path to save the weights.

        Returns:
            Path to the exported weights file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        torch.save(self._model.state_dict(), output_path)
        logger.info(f"Exported best model weights to {output_path}")

        return str(output_path)

    def delete_checkpoint(self, checkpoint_path: Union[str, Path]) -> bool:
        """Delete a specific checkpoint.

        Args:
            checkpoint_path: Path to the checkpoint to delete.

        Returns:
            True if the checkpoint was deleted, False otherwise.
        """
        checkpoint_path = Path(checkpoint_path)
        if checkpoint_path.exists() and checkpoint_path.suffix == ".pt":
            checkpoint_path.unlink()
            self._checkpoint_history = [
                entry
                for entry in self._checkpoint_history
                if entry["path"] != str(checkpoint_path)
            ]
            self._save_history()
            logger.info(f"Deleted checkpoint: {checkpoint_path}")
            return True
        return False

    def clear(self, keep_best: bool = True) -> None:
        """Clear all checkpoints.

        Args:
            keep_best: Whether to keep the best checkpoint.
        """
        for f in self._checkpoint_dir.glob("*.pt"):
            if keep_best and f.name in ("best_model.pt", "best_model_weights.pt"):
                continue
            try:
                f.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {f}: {e}")

        self._checkpoint_history = []
        self._save_history()
        logger.info(f"Cleared all checkpoints (keep_best={keep_best})")

    def get_checkpoint_dir(self) -> Path:
        """Get the checkpoint directory path.

        Returns:
            Path to the checkpoint directory.
        """
        return self._checkpoint_dir

    @property
    def checkpoint_count(self) -> int:
        """Get the number of checkpoint files.

        Returns:
            Number of checkpoint files.
        """
        return len(list(self._checkpoint_dir.glob("*.pt")))

    def _get_lr(self) -> float:
        """Get the current learning rate.

        Returns:
            Current learning rate, or 0.0 if not available.
        """
        if self._optimizer is not None and self._optimizer.param_groups:
            return self._optimizer.param_groups[0].get("lr", 0.0)
        return 0.0

    def __repr__(self) -> str:
        return (
            f"CheckpointManager(dir={self._checkpoint_dir}, "
            f"max_keep={self._max_keep}, "
            f"checkpoints={self.checkpoint_count})"
        )


def save_model_weights(
    model: nn.Module,
    output_path: Union[str, Path],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Save only model weights to a file.

    Args:
        model: The model to save.
        output_path: Path to save the weights.
        metadata: Optional metadata to include.

    Returns:
        Path to the saved weights file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    state_dict: Dict[str, Any] = {"model_state_dict": model.state_dict()}
    if metadata:
        state_dict["metadata"] = metadata

    torch.save(state_dict, output_path)
    logger.info(f"Model weights saved to {output_path}")

    return str(output_path)


def load_model_weights(
    model: nn.Module,
    weights_path: Union[str, Path],
    map_location: Optional[Union[str, torch.device]] = None,
    strict: bool = True,
) -> Optional[Dict[str, Any]]:
    """Load model weights from a file.

    Args:
        model: The model to load weights into.
        weights_path: Path to the weights file.
        map_location: Device to map the weights to.
        strict: Whether to strictly enforce state dict key matching.

    Returns:
        Metadata if available, otherwise None.
    """
    weights_path = Path(weights_path)

    if not weights_path.exists():
        raise FileNotFoundError(f"Weights file not found: {weights_path}")

    try:
        checkpoint = torch.load(weights_path, map_location=map_location)
    except Exception as e:
        logger.error(f"Failed to load weights: {e}")
        raise

    if "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
        metadata = checkpoint.get("metadata")
    else:
        state_dict = checkpoint
        metadata = None

    missing, unexpected = model.load_state_dict(state_dict, strict=strict)
    if missing:
        logger.warning(f"Missing keys: {missing}")
    if unexpected:
        logger.warning(f"Unexpected keys: {unexpected}")

    logger.info(f"Model weights loaded from {weights_path}")
    return metadata


def get_checkpoint_summary(checkpoint_path: Union[str, Path]) -> Dict[str, Any]:
    """Get a summary of a checkpoint file without loading the full model.

    Args:
        checkpoint_path: Path to the checkpoint file.

    Returns:
        Dictionary with checkpoint metadata summary.

    Raises:
        FileNotFoundError: If the checkpoint file doesn't exist.
    """
    checkpoint_path = Path(checkpoint_path)

    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

    # Load only the metadata (not the full state dict)
    try:
        checkpoint = torch.load(
            checkpoint_path, map_location="cpu"
        )
    except Exception as e:
        logger.error(f"Failed to read checkpoint: {e}")
        return {"error": str(e), "path": str(checkpoint_path)}

    metadata = checkpoint.get("metadata", {})

    summary: Dict[str, Any] = {
        "path": str(checkpoint_path),
        "filename": checkpoint_path.name,
        "size_mb": checkpoint_path.stat().st_size / (1024 * 1024),
        "epoch": metadata.get("epoch", "unknown"),
        "global_step": metadata.get("global_step", "unknown"),
        "best_metric": metadata.get("best_metric", "unknown"),
        "train_loss": metadata.get("train_loss", "unknown"),
        "val_loss": metadata.get("val_loss", "unknown"),
        "learning_rate": metadata.get("learning_rate", "unknown"),
        "model_name": metadata.get("model_name", "unknown"),
        "optimizer_name": metadata.get("optimizer_name", "unknown"),
        "timestamp": metadata.get("timestamp", "unknown"),
        "has_optimizer": "optimizer_state_dict" in checkpoint,
        "has_scheduler": "scheduler_state_dict" in checkpoint,
        "state_dict_keys": list(checkpoint.get("model_state_dict", {}).keys())[:10],
    }

    return summary