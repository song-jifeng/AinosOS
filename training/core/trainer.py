"""
Main trainer module for the Ainos training framework.

Provides the core Trainer class that orchestrates the training loop,
including model training, validation, checkpointing, and logging.
"""

from __future__ import annotations

import gc
import logging
import math
import os
import signal
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)

import torch
import torch.nn as nn
from torch.optim.lr_scheduler import _LRScheduler
from torch.optim.optimizer import Optimizer

from .checkpoint import CheckpointManager
from .dataset import Dataset
from .dataloader import DataLoader
from .loss import LossBase, build_loss
from .metrics import Metric, MetricsTracker, build_metric
from .model import BaseModel, count_parameters, count_parameters_by_layer
from .optimizer import build_optimizer
from .scheduler import SchedulerWrapper, build_scheduler

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """Configuration for the training process.

    Attributes:
        output_dir: Directory for outputs (checkpoints, logs).
        experiment_name: Name of the experiment.
        seed: Random seed for reproducibility.
        device: Device to train on ('auto', 'cpu', 'cuda', 'cuda:0', etc.).
        num_epochs: Number of training epochs.
        batch_size: Training batch size per device.
        eval_batch_size: Evaluation batch size per device.
        gradient_accumulation_steps: Number of steps to accumulate gradients.
        max_grad_norm: Maximum gradient norm for clipping.
        learning_rate: Peak learning rate.
        weight_decay: Weight decay factor.
        optimizer: Optimizer name ('adamw', 'adam', 'sgd', 'lion', etc.).
        scheduler: Scheduler name ('cosine', 'linear', 'warmup_cosine', etc.).
        warmup_steps: Number of warmup steps.
        min_lr: Minimum learning rate.
        loss: Loss function name.
        label_smoothing: Label smoothing factor.
        mixed_precision: Mixed precision mode ('no', 'fp16', 'bf16').
        gradient_checkpointing: Enable gradient checkpointing.
        save_every_n_epochs: Save checkpoint every N epochs.
        save_every_n_steps: Save checkpoint every N steps.
        save_total_limit: Maximum number of checkpoints to keep.
        eval_every_n_epochs: Evaluate every N epochs.
        eval_every_n_steps: Evaluate every N steps.
        eval_at_start: Evaluate at the start of training.
        logging_steps: Log metrics every N steps.
        max_steps: Maximum number of training steps.
        early_stopping_patience: Patience for early stopping.
        early_stopping_threshold: Threshold for early stopping improvement.
        dataloader_num_workers: Number of workers for data loading.
        pin_memory: Whether to pin memory in data loading.
        resume_from_checkpoint: Resume from the latest checkpoint.
        load_best_at_start: Load the best checkpoint at start.
        metric_for_best_model: Metric to use for best model selection.
        greater_is_better: Whether higher metric values are better.
        run_name: Run name for tracking.
        tags: Tags for experiment tracking.
    """

    output_dir: str = "./outputs"
    experiment_name: str = "experiment"
    seed: int = 42
    device: str = "auto"
    num_epochs: int = 10
    batch_size: int = 32
    eval_batch_size: int = 64
    gradient_accumulation_steps: int = 1
    max_grad_norm: float = 1.0
    learning_rate: float = 1e-4
    weight_decay: float = 0.01
    optimizer: str = "adamw"
    scheduler: str = "warmup_cosine"
    warmup_steps: int = 0
    min_lr: float = 0.0
    loss: str = "cross_entropy"
    label_smoothing: float = 0.0
    mixed_precision: str = "no"
    gradient_checkpointing: bool = False
    save_every_n_epochs: int = 1
    save_every_n_steps: int = 0
    save_total_limit: int = 5
    eval_every_n_epochs: int = 1
    eval_every_n_steps: int = 0
    eval_at_start: bool = False
    logging_steps: int = 10
    max_steps: int = -1
    early_stopping_patience: int = 0
    early_stopping_threshold: float = 0.0
    dataloader_num_workers: int = 0
    pin_memory: bool = False
    resume_from_checkpoint: bool = False
    load_best_at_start: bool = False
    metric_for_best_model: str = "eval_loss"
    greater_is_better: bool = False
    run_name: str = ""
    tags: List[str] = field(default_factory=list)


class TrainerError(Exception):
    """Base exception for trainer-related errors."""

    pass


class Trainer:
    """Main trainer class for training machine learning models.

    Orchestrates the complete training loop including:
    - Model training and validation
    - Gradient accumulation and clipping
    - Mixed precision training
    - Checkpoint saving and loading
    - Metric tracking and logging
    - Learning rate scheduling
    - Early stopping
    """

    def __init__(
        self,
        model: nn.Module,
        config: TrainingConfig,
        train_dataset: Optional[Dataset] = None,
        eval_dataset: Optional[Dataset] = None,
        loss_fn: Optional[LossBase] = None,
        optimizer: Optional[Optimizer] = None,
        scheduler: Optional[SchedulerWrapper] = None,
        metrics: Optional[Dict[str, Metric]] = None,
        callbacks: Optional[List[Callback]] = None,
        collate_fn: Optional[Callable] = None,
    ) -> None:
        """Initialize the trainer.

        Args:
            model: The model to train.
            config: Training configuration.
            train_dataset: Training dataset.
            eval_dataset: Evaluation dataset.
            loss_fn: Loss function. If None, built from config.
            optimizer: Optimizer. If None, built from config.
            scheduler: Scheduler. If None, built from config.
            metrics: Dictionary of metrics to track.
            callbacks: List of training callbacks.
            collate_fn: Custom collate function for dataloader.

        Raises:
            TrainerError: If initialization fails.
        """
        self.config = config
        self.model = model

        # Setup device
        self._device = self._setup_device()
        self.model = self.model.to(self._device)

        # Setup mixed precision
        self._amp_dtype = self._setup_mixed_precision()
        self._use_amp = config.mixed_precision != "no"
        self._scaler = (
            torch.cuda.amp.GradScaler(enabled=(config.mixed_precision == "fp16"))
        )

        # Setup datasets
        self._train_dataset = train_dataset
        self._eval_dataset = eval_dataset

        # Setup loss function
        self._loss_fn = loss_fn or self._build_loss()

        # Setup optimizer
        self._optimizer = optimizer or self._build_optimizer()

        # Setup scheduler
        total_steps = self._estimate_total_steps()
        self._scheduler = scheduler or self._build_scheduler(total_steps)

        # Setup data loaders
        self._collate_fn = collate_fn
        self._train_loader: Optional[DataLoader] = None
        self._eval_loader: Optional[DataLoader] = None

        # Setup metrics
        self._metrics = MetricsTracker(metrics)
        self._setup_default_metrics()

        # Setup checkpoint manager
        self._checkpoint_manager = self._setup_checkpoint_manager()

        # Setup callbacks
        self._callbacks = callbacks or []

        # Training state
        self._epoch: int = 0
        self._global_step: int = 0
        self._best_metric: float = float("inf")
        self._best_epoch: int = 0
        self._epoch_loss: float = 0.0
        self._best_eval_loss: float = float("inf")
        self._training_start_time: float = 0.0
        self._epoch_start_time: float = 0.0
        self._should_stop: bool = False
        self._early_stopping_counter: int = 0
        self._is_training: bool = False

        # Logging
        self._log_history: List[Dict[str, Any]] = []
        self._recent_losses: List[float] = []

        # Signal handlers
        self._setup_signal_handlers()

        # Random seed
        self._set_seed()

        logger.info(
            f"Trainer initialized. Model: {model.__class__.__name__}, "
            f"Device: {self._device}, "
            f"Parameters: {count_parameters(model):,}"
        )

    def _setup_device(self) -> torch.device:
        """Set up the training device.

        Returns:
            The device to use for training.
        """
        device_str = self.config.device
        if device_str == "auto":
            if torch.cuda.is_available():
                device = torch.device("cuda:0")
                logger.info(
                    f"Using CUDA device: {torch.cuda.get_device_name(0)}"
                )
            elif torch.backends.mps.is_available():
                device = torch.device("mps")
                logger.info("Using MPS device")
            else:
                device = torch.device("cpu")
                logger.info("Using CPU device")
        else:
            device = torch.device(device_str)

        return device

    def _setup_mixed_precision(self) -> Optional[torch.dtype]:
        """Set up mixed precision training.

        Returns:
            The AMP dtype, or None if mixed precision is disabled.

        Raises:
            TrainerError: If the requested precision is not available.
        """
        mp = self.config.mixed_precision.lower()
        if mp == "no":
            return None
        elif mp == "fp16":
            if not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to FP32")
                return None
            return torch.float16
        elif mp == "bf16":
            if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
                logger.warning("BF16 not supported, falling back to FP32")
                return None
            return torch.bfloat16
        else:
            raise TrainerError(f"Unknown mixed precision mode: {mp}")

    def _build_loss(self) -> LossBase:
        """Build the loss function from config.

        Returns:
            The configured loss function.
        """
        kwargs: Dict[str, Any] = {}
        if self.config.label_smoothing > 0.0:
            kwargs["label_smoothing"] = self.config.label_smoothing

        return build_loss(self.config.loss, **kwargs)

    def _build_optimizer(self) -> Optimizer:
        """Build the optimizer from config.

        Returns:
            The configured optimizer.
        """
        return build_optimizer(
            model=self.model,
            optimizer_name=self.config.optimizer,
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )

    def _build_scheduler(self, total_steps: int) -> SchedulerWrapper:
        """Build the learning rate scheduler from config.

        Args:
            total_steps: Total number of training steps.

        Returns:
            The configured scheduler wrapper.
        """
        return build_scheduler(
            optimizer=self._optimizer,
            scheduler_name=self.config.scheduler,
            warmup_lr=self.config.learning_rate,
            min_lr=self.config.min_lr,
            warmup_steps=self.config.warmup_steps,
            total_steps=total_steps,
        )

    def _estimate_total_steps(self) -> int:
        """Estimate the total number of training steps.

        Returns:
            Estimated total steps.
        """
        if self.config.max_steps > 0:
            return self.config.max_steps

        if self._train_dataset is not None:
            steps_per_epoch = math.ceil(
                len(self._train_dataset)
                / self.config.batch_size
                / max(self.config.gradient_accumulation_steps, 1)
            )
            return steps_per_epoch * self.config.num_epochs

        return self.config.num_epochs * 1000  # Default fallback

    def _setup_default_metrics(self) -> None:
        """Set up default metrics for tracking."""
        if "loss" not in self._metrics:
            from .metrics import MeanMetric
            self._metrics.add_metric("loss", MeanMetric("loss"))

    def _setup_checkpoint_manager(self) -> CheckpointManager:
        """Set up the checkpoint manager.

        Returns:
            The configured checkpoint manager.
        """
        output_dir = Path(self.config.output_dir)
        if self.config.run_name:
            output_dir = output_dir / self.config.run_name
        output_dir = output_dir / self.config.experiment_name

        return CheckpointManager(
            checkpoint_dir=output_dir / "checkpoints",
            model=self.model,
            optimizer=self._optimizer,
            scheduler=self._scheduler,
            max_keep=self.config.save_total_limit,
            save_best=True,
            save_optimizer=True,
            save_scheduler=True,
            metric_mode="max" if self.config.greater_is_better else "min",
            save_every_n_epochs=self.config.save_every_n_epochs,
            save_every_n_steps=self.config.save_every_n_steps,
            prefix="checkpoint",
        )

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful interruption."""
        if not sys.platform.startswith("win"):
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle signals for graceful interruption.

        Args:
            signum: Signal number.
            frame: Current stack frame.
        """
        logger.info(f"Received signal {signum}. Saving checkpoint and stopping...")
        self._should_stop = True

    def _set_seed(self) -> None:
        """Set random seeds for reproducibility."""
        seed = self.config.seed
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        import random as _random
        _random.seed(seed)
        try:
            import numpy as _np
            _np.random.seed(seed)
        except ImportError:
            pass

    def _build_dataloader(
        self,
        dataset: Dataset,
        batch_size: int,
        shuffle: bool,
    ) -> DataLoader:
        """Build a DataLoader for the given dataset.

        Args:
            dataset: The dataset.
            batch_size: Batch size.
            shuffle: Whether to shuffle.

        Returns:
            The configured DataLoader.
        """
        return DataLoader(
            dataset=dataset,
            batch_size=batch_size,
            shuffle=shuffle,
            num_workers=self.config.dataloader_num_workers,
            pin_memory=self.config.pin_memory,
            collate_fn=self._collate_fn,
            drop_last=True if shuffle else False,
        )

    @property
    def train_loader(self) -> DataLoader:
        """Get the training data loader."""
        if self._train_loader is None:
            if self._train_dataset is None:
                raise TrainerError("Training dataset not provided.")
            self._train_loader = self._build_dataloader(
                self._train_dataset,
                self.config.batch_size,
                shuffle=True,
            )
        return self._train_loader

    @property
    def eval_loader(self) -> DataLoader:
        """Get the evaluation data loader."""
        if self._eval_loader is None:
            if self._eval_dataset is None:
                raise TrainerError("Evaluation dataset not provided.")
            self._eval_loader = self._build_dataloader(
                self._eval_dataset,
                self.config.eval_batch_size,
                shuffle=False,
            )
        return self._eval_loader

    @property
    def device(self) -> torch.device:
        """Get the training device."""
        return self._device

    @property
    def global_step(self) -> int:
        """Get the current global step."""
        return self._global_step

    @property
    def epoch(self) -> int:
        """Get the current epoch."""
        return self._epoch

    def train(self) -> Dict[str, Any]:
        """Run the full training loop.

        Returns:
            Dictionary with training summary.

        Raises:
            TrainerError: If training fails.
        """
        if self._is_training:
            raise TrainerError("Training is already in progress.")

        self._is_training = True
        self._should_stop = False
        self._training_start_time = time.time()

        logger.info(
            f"\n{'='*60}\n"
            f"Starting training: {self.config.experiment_name}\n"
            f"Model: {self.model.__class__.__name__}\n"
            f"Device: {self._device}\n"
            f"Epochs: {self.config.num_epochs}\n"
            f"Batch size: {self.config.batch_size}\n"
            f"Learning rate: {self.config.learning_rate}\n"
            f"Optimizer: {self.config.optimizer}\n"
            f"Scheduler: {self.config.scheduler}\n"
            f"Mixed precision: {self.config.mixed_precision}\n"
            f"Total parameters: {count_parameters(self.model):,}\n"
            f"Trainable parameters: {count_parameters(self.model, True):,}\n"
            f"{'='*60}"
        )

        # Resume from checkpoint if requested
        if self.config.resume_from_checkpoint:
            self._resume()

        # Evaluate at start if requested
        if self.config.eval_at_start:
            self._run_eval(step=0, prefix="eval")

        # Callbacks: on_train_start
        for cb in self._callbacks:
            cb.on_train_start(self)

        try:
            # Training loop
            for epoch in range(self._epoch, self.config.num_epochs):
                if self._should_stop:
                    break

                self._epoch = epoch
                self._epoch_start_time = time.time()

                # Callbacks: on_epoch_start
                for cb in self._callbacks:
                    cb.on_epoch_start(self, epoch)

                # Train for one epoch
                train_metrics = self._train_epoch()

                # Callbacks: on_epoch_end
                for cb in self._callbacks:
                    cb.on_epoch_end(self, epoch, train_metrics)

                # Evaluate
                should_eval = (
                    (epoch + 1) % self.config.eval_every_n_epochs == 0
                )
                if should_eval:
                    eval_metrics = self._run_eval(
                        step=self._global_step, prefix="eval"
                    )
                else:
                    eval_metrics = {}

                # Save checkpoint
                should_save = (
                    (epoch + 1) % self.config.save_every_n_epochs == 0
                )
                if should_save:
                    self._save_checkpoint(
                        epoch=epoch,
                        metrics={**train_metrics, **eval_metrics},
                    )

                # Check early stopping
                if self._check_early_stopping(eval_metrics):
                    logger.info(
                        f"Early stopping triggered at epoch {epoch + 1}"
                    )
                    break

                # Log epoch summary
                self._log_epoch_summary(epoch, train_metrics, eval_metrics)

            # Save final checkpoint
            if not self._should_stop:
                self._save_checkpoint(
                    epoch=self._epoch,
                    metrics={**train_metrics, **eval_metrics},
                )

        except KeyboardInterrupt:
            logger.info("Training interrupted by user.")
            self._save_checkpoint(
                epoch=self._epoch,
                metrics=self._metrics.summary(),
            )

        except Exception as e:
            logger.error(f"Training failed: {e}")
            logger.error(traceback.format_exc())
            self._save_checkpoint(
                epoch=self._epoch,
                metrics=self._metrics.summary(),
            )
            raise

        finally:
            self._is_training = False

        # Callbacks: on_train_end
        for cb in self._callbacks:
            cb.on_train_end(self)

        # Training summary
        return self._get_training_summary()

    def _train_epoch(self) -> Dict[str, float]:
        """Train for one epoch.

        Returns:
            Dictionary of training metrics.
        """
        self.model.train()
        self._metrics.reset()

        total_loss = 0.0
        num_batches = 0
        accum_loss = 0.0
        accum_steps = 0

        data_iter = iter(self.train_loader)
        num_batches_per_epoch = len(self.train_loader)

        for batch_idx, batch in enumerate(data_iter):
            if self._should_stop:
                break

            # Move batch to device
            batch = self._to_device(batch)

            # Forward pass with mixed precision
            loss = self._forward_step(batch)

            # Scale loss for gradient accumulation
            loss = loss / max(self.config.gradient_accumulation_steps, 1)
            accum_loss += loss.item()
            accum_steps += 1

            # Backward pass
            self._backward_step(loss)

            # Gradient accumulation check
            if (batch_idx + 1) % self.config.gradient_accumulation_steps == 0:
                self._optimizer_step()
                self._global_step += 1
                total_loss += accum_loss
                num_batches += 1
                accum_loss = 0.0
                accum_steps = 0

                # Logging
                if self._global_step % self.config.logging_steps == 0:
                    self._log_step(batch_idx, num_batches_per_epoch, total_loss / max(num_batches, 1))

                # Evaluation during training
                if (self.config.eval_every_n_steps > 0
                        and self._global_step % self.config.eval_every_n_steps == 0):
                    self._run_eval(step=self._global_step, prefix="eval")

                # Save checkpoint during training
                if (self.config.save_every_n_steps > 0
                        and self._global_step % self.config.save_every_n_steps == 0):
                    self._save_checkpoint(
                        epoch=self._epoch,
                        metrics={"loss": total_loss / max(num_batches, 1)},
                    )

                # Check max steps
                if 0 < self.config.max_steps <= self._global_step:
                    self._should_stop = True
                    break

        # Handle remaining gradient accumulation
        if accum_steps > 0 and not self._should_stop:
            self._optimizer_step()
            self._global_step += 1
            total_loss += accum_loss
            num_batches += 1

        avg_loss = total_loss / max(num_batches, 1)
        self._epoch_loss = avg_loss

        return {"loss": avg_loss}

    def _forward_step(self, batch: Any) -> torch.Tensor:
        """Perform a forward pass.

        Args:
            batch: The input batch.

        Returns:
            The computed loss tensor.
        """
        if self._use_amp:
            with torch.cuda.amp.autocast(dtype=self._amp_dtype):
                if isinstance(batch, dict):
                    outputs = self.model(**batch)
                    if isinstance(outputs, dict) and "loss" in outputs:
                        return outputs["loss"]
                    elif isinstance(outputs, torch.Tensor):
                        # Assume outputs are logits, need labels
                        if "labels" in batch:
                            return self._loss_fn(outputs, batch["labels"])
                        return outputs
                    else:
                        # outputs is a tuple, assume (logits, ...)
                        logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
                        if "labels" in batch:
                            return self._loss_fn(logits, batch["labels"])
                        return logits
                elif isinstance(batch, (tuple, list)):
                    outputs = self.model(*batch)
                    if isinstance(outputs, (tuple, list)):
                        logits = outputs[0]
                        labels = batch[1] if len(batch) > 1 else None
                    else:
                        logits = outputs
                        labels = None
                    if labels is not None:
                        return self._loss_fn(logits, labels)
                    return logits
                else:
                    outputs = self.model(batch)
                    return outputs
        else:
            if isinstance(batch, dict):
                outputs = self.model(**batch)
                if isinstance(outputs, dict) and "loss" in outputs:
                    return outputs["loss"]
                elif isinstance(outputs, torch.Tensor):
                    if "labels" in batch:
                        return self._loss_fn(outputs, batch["labels"])
                    return outputs
                else:
                    logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
                    if "labels" in batch:
                        return self._loss_fn(logits, batch["labels"])
                    return logits
            elif isinstance(batch, (tuple, list)):
                outputs = self.model(*batch)
                logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
                labels = batch[1] if len(batch) > 1 else None
                if labels is not None:
                    return self._loss_fn(logits, labels)
                return logits
            else:
                outputs = self.model(batch)
                return outputs

    def _backward_step(self, loss: torch.Tensor) -> None:
        """Perform a backward pass.

        Args:
            loss: The loss tensor to backpropagate.
        """
        if self._use_amp and self.config.mixed_precision == "fp16":
            self._scaler.scale(loss).backward()
        else:
            loss.backward()

    def _optimizer_step(self) -> None:
        """Perform an optimizer step with gradient clipping."""
        # Gradient clipping
        if self.config.max_grad_norm > 0:
            if self._use_amp and self.config.mixed_precision == "fp16":
                self._scaler.unscale_(self._optimizer)
            torch.nn.utils.clip_grad_norm_(
                self.model.parameters(), self.config.max_grad_norm
            )

        # Optimizer step
        if self._use_amp and self.config.mixed_precision == "fp16":
            self._scaler.step(self._optimizer)
            self._scaler.update()
        else:
            self._optimizer.step()

        # Scheduler step
        self._scheduler.step()

        # Zero gradients
        self._optimizer.zero_grad(set_to_none=True)

    def _run_eval(
        self,
        step: int,
        prefix: str = "eval",
    ) -> Dict[str, float]:
        """Run evaluation on the evaluation dataset.

        Args:
            step: Current global step.
            prefix: Prefix for metric names.

        Returns:
            Dictionary of evaluation metrics.
        """
        if self._eval_dataset is None:
            logger.warning("No evaluation dataset available.")
            return {}

        self.model.eval()
        eval_metrics = MetricsTracker()
        eval_metrics.add_metric("eval_loss", type(self._metrics["loss"])(name="eval_loss"))

        total_loss = 0.0
        num_batches = 0

        logger.info(f"Running evaluation at step {step}...")

        with torch.no_grad():
            for batch_idx, batch in enumerate(self.eval_loader):
                batch = self._to_device(batch)

                # Forward pass
                if self._use_amp:
                    with torch.cuda.amp.autocast(dtype=self._amp_dtype):
                        loss = self._compute_loss(batch)
                else:
                    loss = self._compute_loss(batch)

                total_loss += loss.item()
                num_batches += 1

                # Update metrics
                try:
                    self._update_metrics(batch, eval_metrics)
                except Exception as e:
                    logger.debug(f"Failed to update metrics: {e}")

        avg_loss = total_loss / max(num_batches, 1)
        eval_metrics.update_dict({"eval_loss": avg_loss})

        # Compute all metrics
        metrics = eval_metrics.compute()
        metrics["eval_loss"] = avg_loss

        # Track best eval loss
        if avg_loss < self._best_eval_loss:
            self._best_eval_loss = avg_loss

        # Log evaluation results
        metrics_str = " | ".join(
            f"{k}: {v:.4f}" for k, v in metrics.items()
        )
        logger.info(f"Evaluation (step {step}): {metrics_str}")

        # Log to history
        log_entry = {"step": step, "epoch": self._epoch, **metrics}
        self._log_history.append(log_entry)

        # Callbacks
        for cb in self._callbacks:
            cb.on_eval_end(self, metrics)

        # Reset model to train mode
        self.model.train()

        return metrics

    def _compute_loss(self, batch: Any) -> torch.Tensor:
        """Compute the loss for a batch.

        Args:
            batch: The input batch.

        Returns:
            The computed loss.
        """
        if isinstance(batch, dict):
            outputs = self.model(**batch)
            if isinstance(outputs, dict) and "loss" in outputs:
                return outputs["loss"]
            elif isinstance(outputs, torch.Tensor):
                if "labels" in batch:
                    return self._loss_fn(outputs, batch["labels"])
                return outputs
            else:
                logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
                if "labels" in batch:
                    return self._loss_fn(logits, batch["labels"])
                return outputs
        elif isinstance(batch, (tuple, list)):
            outputs = self.model(*batch)
            logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
            labels = batch[1] if len(batch) > 1 else None
            if labels is not None:
                return self._loss_fn(logits, labels)
            return outputs
        else:
            return self.model(batch)

    def _update_metrics(self, batch: Any, metrics: MetricsTracker) -> None:
        """Update metrics with a batch.

        Args:
            batch: The input batch.
            metrics: The metrics tracker to update.
        """
        if isinstance(batch, dict):
            outputs = self.model(**batch)
            logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
            if "labels" in batch:
                metrics.update(logits, batch["labels"])
        elif isinstance(batch, (tuple, list)):
            outputs = self.model(*batch)
            logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
            if len(batch) > 1:
                metrics.update(logits, batch[1])
        else:
            metrics.update(batch, batch)

    def _to_device(self, batch: Any) -> Any:
        """Move a batch to the training device.

        Args:
            batch: The batch to move.

        Returns:
            The batch on the correct device.
        """
        if isinstance(batch, torch.Tensor):
            return batch.to(self._device, non_blocking=self.config.pin_memory)
        elif isinstance(batch, dict):
            return {
                k: self._to_device(v) for k, v in batch.items()
            }
        elif isinstance(batch, (list, tuple)):
            return [self._to_device(item) for item in batch]
        return batch

    def _save_checkpoint(
        self,
        epoch: int,
        metrics: Dict[str, float],
    ) -> None:
        """Save a training checkpoint.

        Args:
            epoch: Current epoch.
            metrics: Current metrics.
        """
        metric_value = metrics.get(
            self.config.metric_for_best_model,
            metrics.get("eval_loss", metrics.get("loss", 0.0)),
        )
        metric_name = self.config.metric_for_best_model

        duration = time.time() - self._training_start_time

        self._checkpoint_manager.save(
            epoch=epoch,
            global_step=self._global_step,
            metric=metric_value,
            metric_name=metric_name,
            train_loss=metrics.get("loss", 0.0),
            val_loss=metrics.get("eval_loss", 0.0),
            duration=duration,
        )

    def _check_early_stopping(self, metrics: Dict[str, float]) -> bool:
        """Check if early stopping should be triggered.

        Args:
            metrics: Current evaluation metrics.

        Returns:
            True if training should stop.
        """
        if self.config.early_stopping_patience <= 0:
            return False

        if not metrics:
            return False

        metric_value = metrics.get(
            self.config.metric_for_best_model,
            metrics.get("eval_loss", None),
        )

        if metric_value is None:
            return False

        is_better = (
            metric_value > self._best_metric
            if self.config.greater_is_better
            else metric_value < self._best_metric
        )

        if is_better:
            self._best_metric = metric_value
            self._best_epoch = self._epoch
            self._early_stopping_counter = 0
        else:
            self._early_stopping_counter += 1

        return self._early_stopping_counter >= self.config.early_stopping_patience

    def _log_step(
        self, batch_idx: int, num_batches: int, current_loss: float
    ) -> None:
        """Log training progress at a step.

        Args:
            batch_idx: Current batch index.
            num_batches: Total number of batches.
            current_loss: Current average loss.
        """
        progress = batch_idx / max(num_batches, 1) * 100
        lr = self._scheduler.get_lr() if self._scheduler else self.config.learning_rate

        logger.info(
            f"Epoch {self._epoch + 1}/{self.config.num_epochs} | "
            f"Batch {batch_idx}/{num_batches} ({progress:.1f}%) | "
            f"Loss: {current_loss:.4f} | "
            f"LR: {lr:.2e} | "
            f"Step: {self._global_step}"
        )

    def _log_epoch_summary(
        self,
        epoch: int,
        train_metrics: Dict[str, float],
        eval_metrics: Dict[str, float],
    ) -> None:
        """Log a summary of the epoch.

        Args:
            epoch: Current epoch number.
            train_metrics: Training metrics.
            eval_metrics: Evaluation metrics.
        """
        epoch_time = time.time() - self._epoch_start_time
        total_time = time.time() - self._training_start_time

        summary_parts = [
            f"\n{'='*60}",
            f"Epoch {epoch + 1}/{self.config.num_epochs} Summary:",
            f"Train Loss: {train_metrics.get('loss', 0.0):.4f}",
        ]

        if eval_metrics:
            for k, v in eval_metrics.items():
                summary_parts.append(f"{k}: {v:.4f}")

        summary_parts.extend([
            f"Learning Rate: {self._scheduler.get_lr():.2e}",
            f"Epoch Time: {epoch_time:.1f}s",
            f"Total Time: {total_time:.1f}s",
            f"Best Eval Loss: {self._best_eval_loss:.4f}",
            f"{'='*60}\n",
        ])

        logger.info("\n".join(summary_parts))

    def _get_training_summary(self) -> Dict[str, Any]:
        """Get a summary of the training run.

        Returns:
            Dictionary with training summary.
        """
        total_time = time.time() - self._training_start_time

        return {
            "experiment_name": self.config.experiment_name,
            "model_name": self.model.__class__.__name__,
            "epochs_trained": self._epoch + 1,
            "global_steps": self._global_step,
            "total_time_seconds": total_time,
            "best_metric": self._best_metric,
            "best_epoch": self._best_epoch,
            "best_eval_loss": self._best_eval_loss,
            "final_train_loss": self._epoch_loss,
            "device": str(self._device),
            "mixed_precision": self.config.mixed_precision,
            "optimizer": self.config.optimizer,
            "scheduler": self.config.scheduler,
            "batch_size": self.config.batch_size,
            "learning_rate": self.config.learning_rate,
            "total_parameters": count_parameters(self.model, False),
            "trainable_parameters": count_parameters(self.model, True),
            "checkpoint_dir": str(self._checkpoint_manager.get_checkpoint_dir()),
        }

    def _resume(self) -> None:
        """Resume training from a checkpoint."""
        try:
            metadata = self._checkpoint_manager.resume_from_checkpoint(
                load_best=self.config.load_best_at_start
            )
            self._epoch = metadata.get("epoch", 0)
            self._global_step = metadata.get("global_step", 0)
            self._best_metric = metadata.get("best_metric", float("inf"))

            logger.info(
                f"Resumed training from checkpoint: "
                f"epoch={self._epoch}, step={self._global_step}"
            )
        except FileNotFoundError:
            logger.info("No checkpoint found, starting from scratch.")

    def evaluate(
        self,
        dataset: Optional[Dataset] = None,
        metrics: Optional[Dict[str, Metric]] = None,
    ) -> Dict[str, float]:
        """Evaluate the model on a dataset.

        Args:
            dataset: Dataset to evaluate on. Uses eval_dataset if None.
            metrics: Metrics to compute. Uses default metrics if None.

        Returns:
            Dictionary of evaluation metrics.
        """
        if dataset is not None:
            self._eval_dataset = dataset
            self._eval_loader = None  # Reset loader

        if self._eval_dataset is None:
            raise TrainerError("No evaluation dataset available.")

        if metrics is not None:
            saved_metrics = self._metrics
            self._metrics = MetricsTracker(metrics)

        results = self._run_eval(step=self._global_step, prefix="eval")

        if metrics is not None:
            self._metrics = saved_metrics

        return results

    def predict(
        self,
        dataset: Dataset,
        batch_size: Optional[int] = None,
    ) -> List[Any]:
        """Run inference on a dataset.

        Args:
            dataset: Dataset to run inference on.
            batch_size: Batch size for inference.

        Returns:
            List of predictions.
        """
        self.model.eval()
        loader = self._build_dataloader(
            dataset,
            batch_size or self.config.eval_batch_size,
            shuffle=False,
        )

        predictions: List[Any] = []

        with torch.no_grad():
            for batch in loader:
                batch = self._to_device(batch)

                if self._use_amp:
                    with torch.cuda.amp.autocast(dtype=self._amp_dtype):
                        outputs = self._forward_for_prediction(batch)
                else:
                    outputs = self._forward_for_prediction(batch)

                predictions.extend(self._process_predictions(outputs))

        return predictions

    def _forward_for_prediction(self, batch: Any) -> Any:
        """Forward pass for prediction.

        Args:
            batch: The input batch.

        Returns:
            Model outputs.
        """
        if isinstance(batch, dict):
            return self.model(**batch)
        elif isinstance(batch, (tuple, list)):
            return self.model(*batch)
        return self.model(batch)

    def _process_predictions(self, outputs: Any) -> List[Any]:
        """Process model outputs into predictions.

        Args:
            outputs: Raw model outputs.

        Returns:
            List of processed predictions.
        """
        if isinstance(outputs, torch.Tensor):
            return outputs.detach().cpu().tolist()
        elif isinstance(outputs, (tuple, list)):
            return [o.detach().cpu().tolist() for o in outputs]
        elif isinstance(outputs, dict):
            return {k: v.detach().cpu().tolist() for k, v in outputs.items()}
        return outputs

    def get_log_history(self) -> List[Dict[str, Any]]:
        """Get the training log history.

        Returns:
            List of log entries.
        """
        return list(self._log_history)

    def get_checkpoint_manager(self) -> CheckpointManager:
        """Get the checkpoint manager.

        Returns:
            The checkpoint manager instance.
        """
        return self._checkpoint_manager

    def get_current_lr(self) -> float:
        """Get the current learning rate.

        Returns:
            Current learning rate.
        """
        return self._scheduler.get_lr() if self._scheduler else self.config.learning_rate

    def state_dict(self) -> Dict[str, Any]:
        """Get the trainer state dictionary.

        Returns:
            State dictionary for serialization.
        """
        return {
            "epoch": self._epoch,
            "global_step": self._global_step,
            "best_metric": self._best_metric,
            "best_epoch": self._best_epoch,
            "best_eval_loss": self._best_eval_loss,
            "epoch_loss": self._epoch_loss,
            "early_stopping_counter": self._early_stopping_counter,
            "config": asdict(self.config),
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        """Load the trainer state from a dictionary.

        Args:
            state_dict: State dictionary to load.
        """
        self._epoch = state_dict.get("epoch", 0)
        self._global_step = state_dict.get("global_step", 0)
        self._best_metric = state_dict.get("best_metric", float("inf"))
        self._best_epoch = state_dict.get("best_epoch", 0)
        self._best_eval_loss = state_dict.get("best_eval_loss", float("inf"))
        self._epoch_loss = state_dict.get("epoch_loss", 0.0)
        self._early_stopping_counter = state_dict.get("early_stopping_counter", 0)

    def __repr__(self) -> str:
        return (
            f"Trainer(model={self.model.__class__.__name__}, "
            f"device={self._device}, "
            f"epoch={self._epoch}, "
            f"step={self._global_step})"
        )


class Callback:
    """Base class for training callbacks.

    Callbacks provide hooks into the training loop at various points.
    """

    def on_train_start(self, trainer: Trainer) -> None:
        """Called when training starts.

        Args:
            trainer: The trainer instance.
        """
        pass

    def on_train_end(self, trainer: Trainer) -> None:
        """Called when training ends.

        Args:
            trainer: The trainer instance.
        """
        pass

    def on_epoch_start(self, trainer: Trainer, epoch: int) -> None:
        """Called when an epoch starts.

        Args:
            trainer: The trainer instance.
            epoch: The epoch number.
        """
        pass

    def on_epoch_end(
        self, trainer: Trainer, epoch: int, metrics: Dict[str, float]
    ) -> None:
        """Called when an epoch ends.

        Args:
            trainer: The trainer instance.
            epoch: The epoch number.
            metrics: The metrics from this epoch.
        """
        pass

    def on_batch_start(
        self, trainer: Trainer, batch: Any, batch_idx: int
    ) -> None:
        """Called when a batch starts.

        Args:
            trainer: The trainer instance.
            batch: The current batch.
            batch_idx: The batch index.
        """
        pass

    def on_batch_end(
        self, trainer: Trainer, batch: Any, batch_idx: int, loss: torch.Tensor
    ) -> None:
        """Called when a batch ends.

        Args:
            trainer: The trainer instance.
            batch: The current batch.
            batch_idx: The batch index.
            loss: The loss value.
        """
        pass

    def on_eval_start(self, trainer: Trainer) -> None:
        """Called when evaluation starts.

        Args:
            trainer: The trainer instance.
        """
        pass

    def on_eval_end(self, trainer: Trainer, metrics: Dict[str, float]) -> None:
        """Called when evaluation ends.

        Args:
            trainer: The trainer instance.
            metrics: The evaluation metrics.
        """
        pass

    def on_checkpoint_save(
        self, trainer: Trainer, checkpoint_path: str
    ) -> None:
        """Called when a checkpoint is saved.

        Args:
            trainer: The trainer instance.
            checkpoint_path: Path to the saved checkpoint.
        """
        pass

    def on_log(self, trainer: Trainer, logs: Dict[str, Any]) -> None:
        """Called when logs are written.

        Args:
            trainer: The trainer instance.
            logs: The log data.
        """
        pass


class EarlyStoppingCallback(Callback):
    """Callback for early stopping.

    Args:
        patience: Number of epochs to wait for improvement.
        threshold: Minimum change to qualify as improvement.
        metric_name: Name of the metric to monitor.
        mode: 'min' or 'max' for the direction of improvement.
    """

    def __init__(
        self,
        patience: int = 10,
        threshold: float = 0.0,
        metric_name: str = "eval_loss",
        mode: str = "min",
    ) -> None:
        """Initialize the early stopping callback.

        Args:
            patience: Number of epochs to wait.
            threshold: Minimum change for improvement.
            metric_name: Metric to monitor.
            mode: 'min' or 'max'.
        """
        self.patience = patience
        self.threshold = threshold
        self.metric_name = metric_name
        self.mode = mode
        self._best_metric = float("inf") if mode == "min" else float("-inf")
        self._counter = 0

    def on_epoch_end(
        self, trainer: Trainer, epoch: int, metrics: Dict[str, float]
    ) -> None:
        """Check for early stopping.

        Args:
            trainer: The trainer instance.
            epoch: The epoch number.
            metrics: The metrics from this epoch.
        """
        if self.metric_name not in metrics:
            return

        current = metrics[self.metric_name]

        if self.mode == "min":
            improved = current < self._best_metric - self.threshold
        else:
            improved = current > self._best_metric + self.threshold

        if improved:
            self._best_metric = current
            self._counter = 0
        else:
            self._counter += 1
            if self._counter >= self.patience:
                logger.info(
                    f"Early stopping triggered after {epoch + 1} epochs. "
                    f"Best {self.metric_name}: {self._best_metric:.4f}"
                )
                trainer._should_stop = True


class ModelCheckpointCallback(Callback):
    """Callback for saving model checkpoints.

    Args:
        save_dir: Directory to save checkpoints.
        save_every_n_epochs: Save every N epochs.
        save_best: Save best model separately.
        metric_name: Metric to monitor for best model.
        mode: 'min' or 'max'.
    """

    def __init__(
        self,
        save_dir: str,
        save_every_n_epochs: int = 1,
        save_best: bool = True,
        metric_name: str = "eval_loss",
        mode: str = "min",
    ) -> None:
        """Initialize the model checkpoint callback.

        Args:
            save_dir: Directory to save checkpoints.
            save_every_n_epochs: Save interval.
            save_best: Save best model.
            metric_name: Metric to monitor.
            mode: 'min' or 'max'.
        """
        self.save_dir = Path(save_dir)
        self.save_every_n_epochs = save_every_n_epochs
        self.save_best = save_best
        self.metric_name = metric_name
        self.mode = mode
        self._best_metric = float("inf") if mode == "min" else float("-inf")

        self.save_dir.mkdir(parents=True, exist_ok=True)

    def on_epoch_end(
        self, trainer: Trainer, epoch: int, metrics: Dict[str, float]
    ) -> None:
        """Save checkpoint at epoch end.

        Args:
            trainer: The trainer instance.
            epoch: The epoch number.
            metrics: The metrics from this epoch.
        """
        if (epoch + 1) % self.save_every_n_epochs != 0:
            return

        # Save checkpoint
        checkpoint_path = self.save_dir / f"checkpoint_epoch_{epoch + 1}.pt"
        torch.save(
            {
                "epoch": epoch,
                "model_state_dict": trainer.model.state_dict(),
                "optimizer_state_dict": trainer._optimizer.state_dict(),
                "metrics": metrics,
            },
            checkpoint_path,
        )

        # Save best model
        if self.save_best and self.metric_name in metrics:
            current = metrics[self.metric_name]
            is_better = (
                current > self._best_metric
                if self.mode == "max"
                else current < self._best_metric
            )

            if is_better:
                self._best_metric = current
                best_path = self.save_dir / "best_model.pt"
                torch.save(trainer.model.state_dict(), best_path)


class LearningRateMonitor(Callback):
    """Callback for monitoring learning rate."""

    def on_epoch_end(
        self, trainer: Trainer, epoch: int, metrics: Dict[str, float]
    ) -> None:
        """Log the current learning rate.

        Args:
            trainer: The trainer instance.
            epoch: The epoch number.
            metrics: The metrics from this epoch.
        """
        lr = trainer.get_current_lr()
        logger.info(f"Learning rate at epoch {epoch + 1}: {lr:.2e}")