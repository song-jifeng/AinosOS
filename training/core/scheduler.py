"""
Learning rate scheduler module for the Ainos training framework.

Provides implementations of common learning rate scheduling strategies
including cosine, linear, warmup, and polynomial schedules.
"""

from __future__ import annotations

import logging
import math
import warnings
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import torch
from torch.optim.lr_scheduler import _LRScheduler
from torch.optim.optimizer import Optimizer

logger = logging.getLogger(__name__)


class LRSchedulerBase(ABC):
    """Abstract base class for learning rate schedulers."""

    @abstractmethod
    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        raise NotImplementedError

    @abstractmethod
    def __repr__(self) -> str:
        """Return a string representation of the scheduler."""
        raise NotImplementedError


class ConstantLR(LRSchedulerBase):
    """Constant learning rate schedule.

    Args:
        lr: The constant learning rate value.
    """

    def __init__(self, lr: float = 1e-4) -> None:
        """Initialize the constant schedule.

        Args:
            lr: The constant learning rate value.
        """
        self._lr = lr

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate (constant regardless of step).

        Args:
            step: Current step number (unused).
            total_steps: Total number of steps (unused).

        Returns:
            The constant learning rate.
        """
        return self._lr

    def __repr__(self) -> str:
        return f"ConstantLR(lr={self._lr})"


class LinearLR(LRSchedulerBase):
    """Linear learning rate schedule.

    Linearly decays the learning rate from `warmup_lr` to `min_lr`.

    Args:
        warmup_lr: Initial learning rate after warmup.
        min_lr: Minimum learning rate at the end of training.
    """

    def __init__(self, warmup_lr: float = 1e-4, min_lr: float = 0.0) -> None:
        """Initialize the linear schedule.

        Args:
            warmup_lr: Initial learning rate after warmup.
            min_lr: Minimum learning rate at the end of training.
        """
        self._warmup_lr = warmup_lr
        self._min_lr = min_lr

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        if total_steps == 0:
            return self._warmup_lr

        progress = step / total_steps
        return self._warmup_lr + (self._min_lr - self._warmup_lr) * progress

    def __repr__(self) -> str:
        return f"LinearLR(warmup_lr={self._warmup_lr}, min_lr={self._min_lr})"


class CosineLR(LRSchedulerBase):
    """Cosine annealing learning rate schedule.

    Decays the learning rate following a cosine curve from `warmup_lr` to `min_lr`.

    Args:
        warmup_lr: Initial learning rate after warmup.
        min_lr: Minimum learning rate at the end of training.
        cycle_length: Length of one cosine cycle as fraction of total steps.
            If 1.0, one full cycle. If 0.5, half a cycle (cosine decay).
        last_cycle: If True, the last cycle has the full period.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        min_lr: float = 0.0,
        cycle_length: float = 1.0,
        last_cycle: bool = False,
    ) -> None:
        """Initialize the cosine schedule.

        Args:
            warmup_lr: Initial learning rate after warmup.
            min_lr: Minimum learning rate at the end of training.
            cycle_length: Length of one cosine cycle.
            last_cycle: If True, last cycle has full period.
        """
        self._warmup_lr = warmup_lr
        self._min_lr = min_lr
        self._cycle_length = cycle_length
        self._last_cycle = last_cycle

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        if total_steps == 0:
            return self._warmup_lr

        progress = step / total_steps
        if self._last_cycle:
            progress = min(progress, 1.0)
        else:
            progress = min(progress / self._cycle_length, 1.0)

        cosine_decay = 0.5 * (1.0 + math.cos(math.pi * progress))
        return self._min_lr + (self._warmup_lr - self._min_lr) * cosine_decay

    def __repr__(self) -> str:
        return (
            f"CosineLR(warmup_lr={self._warmup_lr}, min_lr={self._min_lr}, "
            f"cycle_length={self._cycle_length})"
        )


class PolynomialLR(LRSchedulerBase):
    """Polynomial learning rate schedule.

    Decays the learning rate following a polynomial curve.

    Args:
        warmup_lr: Initial learning rate after warmup.
        min_lr: Minimum learning rate at the end of decay.
        power: Power of the polynomial. Default: 2.0 (quadratic).
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        min_lr: float = 0.0,
        power: float = 2.0,
    ) -> None:
        """Initialize the polynomial schedule.

        Args:
            warmup_lr: Initial learning rate after warmup.
            min_lr: Minimum learning rate at the end of decay.
            power: Power of the polynomial.
        """
        self._warmup_lr = warmup_lr
        self._min_lr = min_lr
        self._power = power

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        if total_steps == 0:
            return self._warmup_lr

        progress = min(step / total_steps, 1.0)
        return self._min_lr + (self._warmup_lr - self._min_lr) * (1.0 - progress) ** self._power

    def __repr__(self) -> str:
        return (
            f"PolynomialLR(warmup_lr={self._warmup_lr}, min_lr={self._min_lr}, "
            f"power={self._power})"
        )


class ExponentialLR(LRSchedulerBase):
    """Exponential learning rate schedule.

    Decays the learning rate exponentially.

    Args:
        warmup_lr: Initial learning rate after warmup.
        gamma: Multiplicative factor of learning rate decay. Default: 0.95.
    """

    def __init__(self, warmup_lr: float = 1e-4, gamma: float = 0.95) -> None:
        """Initialize the exponential schedule.

        Args:
            warmup_lr: Initial learning rate after warmup.
            gamma: Multiplicative factor of learning rate decay.
        """
        self._warmup_lr = warmup_lr
        self._gamma = gamma

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        return self._warmup_lr * (self._gamma ** step)

    def __repr__(self) -> str:
        return f"ExponentialLR(warmup_lr={self._warmup_lr}, gamma={self._gamma})"


class WarmupLR(LRSchedulerBase):
    """Warmup learning rate schedule.

    Linearly increases the learning rate from 0 to `warmup_lr` over `warmup_steps`.

    Args:
        warmup_lr: Target learning rate after warmup.
        warmup_steps: Number of warmup steps.
    """

    def __init__(self, warmup_lr: float = 1e-4, warmup_steps: int = 1000) -> None:
        """Initialize the warmup schedule.

        Args:
            warmup_lr: Target learning rate after warmup.
            warmup_steps: Number of warmup steps.
        """
        self._warmup_lr = warmup_lr
        self._warmup_steps = warmup_steps

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps (unused).

        Returns:
            The learning rate at the given step.
        """
        if step >= self._warmup_steps:
            return self._warmup_lr
        return self._warmup_lr * (step / max(1, self._warmup_steps))

    def __repr__(self) -> str:
        return f"WarmupLR(warmup_lr={self._warmup_lr}, warmup_steps={self._warmup_steps})"


class WarmupCosineLR(LRSchedulerBase):
    """Cosine schedule with linear warmup.

    Linearly increases from 0 to `warmup_lr` over `warmup_steps`, then follows
    a cosine decay to `min_lr`.

    Args:
        warmup_lr: Peak learning rate after warmup.
        min_lr: Minimum learning rate.
        warmup_steps: Number of warmup steps.
        total_steps: Total number of training steps.
        cycle_length: Fraction of remaining steps for one cosine cycle.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        min_lr: float = 0.0,
        warmup_steps: int = 1000,
        total_steps: int = 10000,
        cycle_length: float = 1.0,
    ) -> None:
        """Initialize the warmup cosine schedule.

        Args:
            warmup_lr: Peak learning rate after warmup.
            min_lr: Minimum learning rate.
            warmup_steps: Number of warmup steps.
            total_steps: Total number of training steps.
            cycle_length: Fraction of remaining steps for one cosine cycle.
        """
        self._warmup_lr = warmup_lr
        self._min_lr = min_lr
        self._warmup_steps = warmup_steps
        self._total_steps = total_steps
        self._cycle_length = cycle_length

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        total = total_steps if total_steps > 0 else self._total_steps

        # Warmup phase
        if step < self._warmup_steps:
            return self._warmup_lr * (step / max(1, self._warmup_steps))

        # Cosine decay phase
        decay_steps = total - self._warmup_steps
        decay_step = step - self._warmup_steps
        if decay_steps <= 0:
            return self._warmup_lr

        progress = min(decay_step / (decay_steps * self._cycle_length), 1.0)
        cosine_decay = 0.5 * (1.0 + math.cos(math.pi * progress))

        return self._min_lr + (self._warmup_lr - self._min_lr) * cosine_decay

    def __repr__(self) -> str:
        return (
            f"WarmupCosineLR(warmup_lr={self._warmup_lr}, min_lr={self._min_lr}, "
            f"warmup_steps={self._warmup_steps})"
        )


class WarmupLinearLR(LRSchedulerBase):
    """Linear schedule with linear warmup.

    Linearly increases from 0 to `warmup_lr` over `warmup_steps`, then linearly
    decays to `min_lr`.

    Args:
        warmup_lr: Peak learning rate after warmup.
        min_lr: Minimum learning rate.
        warmup_steps: Number of warmup steps.
        total_steps: Total number of training steps.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        min_lr: float = 0.0,
        warmup_steps: int = 1000,
        total_steps: int = 10000,
    ) -> None:
        """Initialize the warmup linear schedule.

        Args:
            warmup_lr: Peak learning rate after warmup.
            min_lr: Minimum learning rate.
            warmup_steps: Number of warmup steps.
            total_steps: Total number of training steps.
        """
        self._warmup_lr = warmup_lr
        self._min_lr = min_lr
        self._warmup_steps = warmup_steps
        self._total_steps = total_steps

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        total = total_steps if total_steps > 0 else self._total_steps

        # Warmup phase
        if step < self._warmup_steps:
            return self._warmup_lr * (step / max(1, self._warmup_steps))

        # Linear decay phase
        decay_steps = total - self._warmup_steps
        decay_step = step - self._warmup_steps
        if decay_steps <= 0:
            return self._warmup_lr

        progress = min(decay_step / decay_steps, 1.0)
        return self._warmup_lr + (self._min_lr - self._warmup_lr) * progress

    def __repr__(self) -> str:
        return (
            f"WarmupLinearLR(warmup_lr={self._warmup_lr}, min_lr={self._min_lr}, "
            f"warmup_steps={self._warmup_steps})"
        )


class WarmupPolynomialLR(LRSchedulerBase):
    """Polynomial schedule with linear warmup.

    Args:
        warmup_lr: Peak learning rate after warmup.
        min_lr: Minimum learning rate.
        warmup_steps: Number of warmup steps.
        total_steps: Total number of training steps.
        power: Power of the polynomial.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        min_lr: float = 0.0,
        warmup_steps: int = 1000,
        total_steps: int = 10000,
        power: float = 2.0,
    ) -> None:
        """Initialize the warmup polynomial schedule.

        Args:
            warmup_lr: Peak learning rate after warmup.
            min_lr: Minimum learning rate.
            warmup_steps: Number of warmup steps.
            total_steps: Total number of training steps.
            power: Power of the polynomial.
        """
        self._warmup_lr = warmup_lr
        self._min_lr = min_lr
        self._warmup_steps = warmup_steps
        self._total_steps = total_steps
        self._power = power

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        total = total_steps if total_steps > 0 else self._total_steps

        if step < self._warmup_steps:
            return self._warmup_lr * (step / max(1, self._warmup_steps))

        decay_steps = total - self._warmup_steps
        decay_step = step - self._warmup_steps
        if decay_steps <= 0:
            return self._warmup_lr

        progress = min(decay_step / decay_steps, 1.0)
        return self._min_lr + (self._warmup_lr - self._min_lr) * (1.0 - progress) ** self._power

    def __repr__(self) -> str:
        return (
            f"WarmupPolynomialLR(warmup_lr={self._warmup_lr}, min_lr={self._min_lr}, "
            f"power={self._power})"
        )


class WarmupExponentialLR(LRSchedulerBase):
    """Exponential schedule with linear warmup.

    Args:
        warmup_lr: Peak learning rate after warmup.
        warmup_steps: Number of warmup steps.
        gamma: Multiplicative factor of learning rate decay.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        warmup_steps: int = 1000,
        gamma: float = 0.95,
    ) -> None:
        """Initialize the warmup exponential schedule.

        Args:
            warmup_lr: Peak learning rate after warmup.
            warmup_steps: Number of warmup steps.
            gamma: Multiplicative factor of learning rate decay.
        """
        self._warmup_lr = warmup_lr
        self._warmup_steps = warmup_steps
        self._gamma = gamma

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        if step < self._warmup_steps:
            return self._warmup_lr * (step / max(1, self._warmup_steps))
        decay_step = step - self._warmup_steps
        return self._warmup_lr * (self._gamma ** decay_step)

    def __repr__(self) -> str:
        return (
            f"WarmupExponentialLR(warmup_lr={self._warmup_lr}, "
            f"warmup_steps={self._warmup_steps}, gamma={self._gamma})"
        )


class CosineAnnealingWarmRestarts(LRSchedulerBase):
    """Cosine annealing with warm restarts.

    Args:
        warmup_lr: Peak learning rate.
        min_lr: Minimum learning rate.
        t_0: Number of steps for the first restart.
        t_mult: Factor to increase the cycle length after each restart.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        min_lr: float = 0.0,
        t_0: int = 10000,
        t_mult: int = 2,
    ) -> None:
        """Initialize cosine annealing with warm restarts.

        Args:
            warmup_lr: Peak learning rate.
            min_lr: Minimum learning rate.
            t_0: Number of steps for the first restart.
            t_mult: Factor to increase the cycle length after each restart.
        """
        self._warmup_lr = warmup_lr
        self._min_lr = min_lr
        self._t_0 = t_0
        self._t_mult = t_mult

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        # Find which cycle and position within cycle
        t_cur = step
        t_i = self._t_0
        while t_cur >= t_i:
            t_cur -= t_i
            t_i *= self._t_mult

        cosine_decay = 0.5 * (1.0 + math.cos(math.pi * t_cur / t_i))
        return self._min_lr + (self._warmup_lr - self._min_lr) * cosine_decay

    def __repr__(self) -> str:
        return (
            f"CosineAnnealingWarmRestarts(warmup_lr={self._warmup_lr}, "
            f"min_lr={self._min_lr}, t_0={self._t_0}, t_mult={self._t_mult})"
        )


class InverseSquareRootLR(LRSchedulerBase):
    """Inverse square root learning rate schedule.

    Often used for Transformer training.

    Args:
        warmup_lr: Peak learning rate.
        warmup_steps: Number of warmup steps.
        coefficient: Scaling coefficient.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        warmup_steps: int = 4000,
        coefficient: float = 1.0,
    ) -> None:
        """Initialize the inverse square root schedule.

        Args:
            warmup_lr: Peak learning rate.
            warmup_steps: Number of warmup steps.
            coefficient: Scaling coefficient.
        """
        self._warmup_lr = warmup_lr
        self._warmup_steps = warmup_steps
        self._coefficient = coefficient

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        step = max(step, 1)
        warmup = self._warmup_steps
        arg1 = step ** -0.5
        arg2 = step * (warmup ** -1.5)
        return self._warmup_lr * self._coefficient * min(arg1, arg2)

    def __repr__(self) -> str:
        return (
            f"InverseSquareRootLR(warmup_lr={self._warmup_lr}, "
            f"warmup_steps={self._warmup_steps})"
        )


class ReduceLROnPlateau(LRSchedulerBase):
    """Reduce learning rate when a metric has stopped improving.

    Args:
        warmup_lr: Initial learning rate.
        factor: Factor to reduce the learning rate by.
        patience: Number of epochs with no improvement after which lr is reduced.
        threshold: Threshold for measuring improvement.
        min_lr: Minimum learning rate.
        cooldown: Number of epochs to wait before resuming normal operation.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        factor: float = 0.1,
        patience: int = 10,
        threshold: float = 1e-4,
        min_lr: float = 0.0,
        cooldown: int = 0,
    ) -> None:
        """Initialize the ReduceLROnPlateau schedule.

        Args:
            warmup_lr: Initial learning rate.
            factor: Factor to reduce the learning rate by.
            patience: Number of epochs with no improvement.
            threshold: Threshold for measuring improvement.
            min_lr: Minimum learning rate.
            cooldown: Number of epochs to wait before resuming.
        """
        self._warmup_lr = warmup_lr
        self._factor = factor
        self._patience = patience
        self._threshold = threshold
        self._min_lr = min_lr
        self._cooldown = cooldown
        self._current_lr = warmup_lr
        self._num_bad_epochs = 0
        self._cooldown_counter = 0
        self._best = float("inf")
        self._mode_worse = 1.0  # 1.0 for minimizing, -1.0 for maximizing

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the current learning rate.

        Args:
            step: Current step number (unused).
            total_steps: Total number of steps (unused).

        Returns:
            The current learning rate.
        """
        return self._current_lr

    def step_metric(self, metric: float, mode: str = "min") -> float:
        """Step based on a metric value.

        Args:
            metric: The metric value to evaluate.
            mode: 'min' or 'max' - whether lower or higher is better.

        Returns:
            The current learning rate after potential reduction.
        """
        if mode == "min":
            self._mode_worse = 1.0
        elif mode == "max":
            self._mode_worse = -1.0
        else:
            raise ValueError(f"Mode must be 'min' or 'max', got {mode}")

        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            return self._current_lr

        if metric * self._mode_worse < self._best - self._threshold:
            self._best = metric
            self._num_bad_epochs = 0
        else:
            self._num_bad_epochs += 1

        if self._num_bad_epochs > self._patience:
            self._current_lr = max(self._current_lr * self._factor, self._min_lr)
            self._cooldown_counter = self._cooldown
            self._num_bad_epochs = 0

        return self._current_lr

    def reset(self) -> None:
        """Reset the scheduler state."""
        self._current_lr = self._warmup_lr
        self._num_bad_epochs = 0
        self._cooldown_counter = 0
        self._best = float("inf")

    def __repr__(self) -> str:
        return (
            f"ReduceLROnPlateau(warmup_lr={self._warmup_lr}, "
            f"factor={self._factor}, patience={self._patience})"
        )


# Registry of available schedulers
SCHEDULER_REGISTRY: Dict[str, type] = {
    "constant": ConstantLR,
    "linear": LinearLR,
    "cosine": CosineLR,
    "polynomial": PolynomialLR,
    "exponential": ExponentialLR,
    "warmup": WarmupLR,
    "warmup_cosine": WarmupCosineLR,
    "warmup_linear": WarmupLinearLR,
    "warmup_polynomial": WarmupPolynomialLR,
    "warmup_exponential": WarmupExponentialLR,
    "cosine_warm_restarts": CosineAnnealingWarmRestarts,
    "inverse_sqrt": InverseSquareRootLR,
    "reduce_on_plateau": ReduceLROnPlateau,
}


class SchedulerWrapper:
    """Wrapper that integrates a LRSchedulerBase with a PyTorch Optimizer.

    This wraps a learning rate schedule function and applies it to an optimizer.
    """

    def __init__(
        self,
        optimizer: Optimizer,
        scheduler: LRSchedulerBase,
        total_steps: int,
        last_step: int = -1,
    ) -> None:
        """Initialize the scheduler wrapper.

        Args:
            optimizer: The PyTorch optimizer.
            scheduler: The learning rate schedule.
            total_steps: Total number of training steps.
            last_step: The last step index.
        """
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.total_steps = total_steps
        self.last_step = last_step
        self._step_count = 0

    def step(self) -> None:
        """Step the scheduler and update the optimizer's learning rate."""
        self._step_count += 1
        self.last_step = self._step_count

        new_lr = self.scheduler.get_lr(self._step_count, self.total_steps)

        for param_group in self.optimizer.param_groups:
            param_group["lr"] = new_lr

    def get_lr(self) -> float:
        """Get the current learning rate.

        Returns:
            The current learning rate.
        """
        if self.optimizer.param_groups:
            return self.optimizer.param_groups[0]["lr"]
        return 0.0

    def state_dict(self) -> Dict[str, Any]:
        """Get the scheduler state dictionary.

        Returns:
            State dictionary for serialization.
        """
        return {
            "step_count": self._step_count,
            "last_step": self.last_step,
            "total_steps": self.total_steps,
            "scheduler_type": type(self.scheduler).__name__,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        """Load the scheduler state from a dictionary.

        Args:
            state_dict: State dictionary to load.
        """
        self._step_count = state_dict.get("step_count", 0)
        self.last_step = state_dict.get("last_step", -1)


def build_scheduler(
    optimizer: Optimizer,
    scheduler_name: str = "cosine",
    warmup_lr: float = 1e-4,
    min_lr: float = 0.0,
    warmup_steps: int = 0,
    total_steps: int = 10000,
    **kwargs: Any,
) -> SchedulerWrapper:
    """Build a learning rate scheduler.

    Args:
        optimizer: The optimizer to schedule.
        scheduler_name: Name of the scheduler ('constant', 'linear', 'cosine',
            'polynomial', 'exponential', 'warmup', 'warmup_cosine',
            'warmup_linear', 'warmup_polynomial', 'warmup_exponential',
            'cosine_warm_restarts', 'inverse_sqrt', 'reduce_on_plateau').
        warmup_lr: Peak learning rate (after warmup).
        min_lr: Minimum learning rate.
        warmup_steps: Number of warmup steps.
        total_steps: Total number of training steps.
        **kwargs: Additional scheduler-specific arguments.

    Returns:
        A SchedulerWrapper wrapping the optimizer.

    Raises:
        ValueError: If the scheduler name is not recognized.
    """
    scheduler_name = scheduler_name.lower().replace("-", "_")

    if scheduler_name not in SCHEDULER_REGISTRY:
        raise ValueError(
            f"Unknown scheduler: '{scheduler_name}'. "
            f"Available: {list(SCHEDULER_REGISTRY.keys())}"
        )

    # Determine if we need to create a warmup variant
    if warmup_steps > 0 and scheduler_name in ("linear", "cosine", "polynomial", "exponential"):
        # Use warmup variant
        warmup_name = f"warmup_{scheduler_name}"
        if warmup_name in SCHEDULER_REGISTRY:
            scheduler_cls = SCHEDULER_REGISTRY[warmup_name]
            scheduler = scheduler_cls(
                warmup_lr=warmup_lr,
                min_lr=min_lr,
                warmup_steps=warmup_steps,
                total_steps=total_steps,
                **kwargs,
            )
        else:
            scheduler = SCHEDULER_REGISTRY[scheduler_name](
                warmup_lr=warmup_lr, min_lr=min_lr, **kwargs
            )
            # Wrap with warmup manually
            if warmup_steps > 0:
                warmup_sched = WarmupLR(warmup_lr, warmup_steps)
                chain = ChainedScheduler([warmup_sched, scheduler])
                return SchedulerWrapper(optimizer, chain, total_steps)
    else:
        scheduler_cls = SCHEDULER_REGISTRY[scheduler_name]
        scheduler = scheduler_cls(
            warmup_lr=warmup_lr,
            min_lr=min_lr,
            warmup_steps=warmup_steps,
            **kwargs,
        )

    return SchedulerWrapper(optimizer, scheduler, total_steps)


class ChainedScheduler(LRSchedulerBase):
    """Chain multiple schedulers together.

    Each scheduler runs for its portion of the training steps.

    Args:
        schedulers: List of schedulers to chain.
    """

    def __init__(self, schedulers: List[LRSchedulerBase]) -> None:
        """Initialize the chained scheduler.

        Args:
            schedulers: List of schedulers to chain.
        """
        if not schedulers:
            raise ValueError("At least one scheduler is required.")

        self._schedulers = schedulers

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        The active scheduler is determined by the step position.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        # Use the last scheduler for the full range
        return self._schedulers[-1].get_lr(step, total_steps)

    def __repr__(self) -> str:
        return f"ChainedScheduler({self._schedulers})"


class MultiStepLR(LRSchedulerBase):
    """Multi-step learning rate schedule.

    Decays the learning rate by gamma at specified milestones.

    Args:
        warmup_lr: Initial learning rate.
        milestones: List of step indices where to decay.
        gamma: Multiplicative factor of learning rate decay.
    """

    def __init__(
        self,
        warmup_lr: float = 1e-4,
        milestones: Optional[List[int]] = None,
        gamma: float = 0.1,
    ) -> None:
        """Initialize the multi-step schedule.

        Args:
            warmup_lr: Initial learning rate.
            milestones: Steps at which to decay the learning rate.
            gamma: Decay factor.
        """
        self._warmup_lr = warmup_lr
        self._milestones = sorted(milestones) if milestones else []
        self._gamma = gamma

    def get_lr(self, step: int, total_steps: int) -> float:
        """Get the learning rate at a given step.

        Args:
            step: Current step number.
            total_steps: Total number of steps.

        Returns:
            The learning rate at the given step.
        """
        lr = self._warmup_lr
        for milestone in self._milestones:
            if step >= milestone:
                lr *= self._gamma
        return lr

    def __repr__(self) -> str:
        return f"MultiStepLR(warmup_lr={self._warmup_lr}, milestones={self._milestones}, gamma={self._gamma})"


SCHEDULER_REGISTRY["multi_step"] = MultiStepLR
SCHEDULER_REGISTRY["chained"] = ChainedScheduler