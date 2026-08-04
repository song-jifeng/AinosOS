"""
Ainos Training Framework - A comprehensive AI training library.

This framework provides a complete training pipeline for deep learning models,
supporting distributed training, mixed precision, LoRA/QLoRA fine-tuning,
and experiment tracking.
"""

__version__ = "0.1.0"
__author__ = "Ainos AI"

from .core.trainer import Trainer
from .core.dataset import Dataset
from .core.dataloader import DataLoader
from .core.model import BaseModel
from .core.optimizer import build_optimizer
from .core.scheduler import build_scheduler
from .core.loss import build_loss
from .core.metrics import MetricsTracker
from .core.checkpoint import CheckpointManager

__all__ = [
    "Trainer",
    "Dataset",
    "DataLoader",
    "BaseModel",
    "build_optimizer",
    "build_scheduler",
    "build_loss",
    "MetricsTracker",
    "CheckpointManager",
]