"""
Loss function module for the Ainos training framework.

Provides implementations of common loss functions and a factory function
for building losses by name.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class LossBase(nn.Module):
    """Base class for all loss functions.

    Provides common interface and utilities for loss computation.
    """

    def __init__(self, reduction: str = "mean") -> None:
        """Initialize the loss base.

        Args:
            reduction: Reduction method ('mean', 'sum', 'none').

        Raises:
            ValueError: If reduction is not recognized.
        """
        super().__init__()
        if reduction not in ("mean", "sum", "none"):
            raise ValueError(
                f"Reduction must be 'mean', 'sum', or 'none', got '{reduction}'"
            )
        self.reduction = reduction

    def forward(self, *args: Any, **kwargs: Any) -> torch.Tensor:
        """Compute the loss.

        Args:
            *args: Positional arguments for the loss computation.
            **kwargs: Keyword arguments for the loss computation.

        Returns:
            The computed loss tensor.
        """
        raise NotImplementedError

    def reduce(self, loss: torch.Tensor) -> torch.Tensor:
        """Apply reduction to the loss tensor.

        Args:
            loss: The loss tensor to reduce.

        Returns:
            The reduced loss.
        """
        if self.reduction == "mean":
            return loss.mean()
        elif self.reduction == "sum":
            return loss.sum()
        return loss


class CrossEntropyLoss(LossBase):
    """Cross-entropy loss with optional label smoothing and class weights.

    Args:
        weight: Class weights tensor.
        ignore_index: Index to ignore in the loss computation.
        reduction: Reduction method ('mean', 'sum', 'none').
        label_smoothing: Label smoothing factor (0.0 = no smoothing).
    """

    def __init__(
        self,
        weight: Optional[torch.Tensor] = None,
        ignore_index: int = -100,
        reduction: str = "mean",
        label_smoothing: float = 0.0,
    ) -> None:
        """Initialize the cross-entropy loss.

        Args:
            weight: Class weights.
            ignore_index: Index to ignore.
            reduction: Reduction method.
            label_smoothing: Label smoothing factor.
        """
        super().__init__(reduction)
        self._weight = weight
        self._ignore_index = ignore_index
        self._label_smoothing = label_smoothing

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute cross-entropy loss.

        Args:
            pred: Predicted logits of shape (N, C, ...) or (N, C).
            target: Target indices of shape (N, ...) or (N,).

        Returns:
            The computed loss.
        """
        return F.cross_entropy(
            pred,
            target,
            weight=self._weight,
            ignore_index=self._ignore_index,
            reduction=self.reduction,
            label_smoothing=self._label_smoothing,
        )


class BCELoss(LossBase):
    """Binary Cross-Entropy loss.

    Args:
            weight: Weight for each sample.
            reduction: Reduction method.
    """

    def __init__(
        self,
        weight: Optional[torch.Tensor] = None,
        reduction: str = "mean",
    ) -> None:
        """Initialize the BCE loss.

        Args:
            weight: Sample weights.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._weight = weight

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute binary cross-entropy loss.

        Args:
            pred: Predicted probabilities of shape (N, *).
            target: Binary targets of shape (N, *).

        Returns:
            The computed loss.
        """
        return F.binary_cross_entropy(
            pred, target, weight=self._weight, reduction=self.reduction
        )


class BCEWithLogitsLoss(LossBase):
    """Binary Cross-Entropy loss with sigmoid integrated.

    Args:
        weight: Weight for each sample.
        reduction: Reduction method.
        pos_weight: Positive class weight.
    """

    def __init__(
        self,
        weight: Optional[torch.Tensor] = None,
        reduction: str = "mean",
        pos_weight: Optional[torch.Tensor] = None,
    ) -> None:
        """Initialize the BCEWithLogits loss.

        Args:
            weight: Sample weights.
            reduction: Reduction method.
            pos_weight: Positive class weight.
        """
        super().__init__(reduction)
        self._weight = weight
        self._pos_weight = pos_weight

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute BCE with logits loss.

        Args:
            pred: Raw logits of shape (N, *).
            target: Binary targets of shape (N, *).

        Returns:
            The computed loss.
        """
        return F.binary_cross_entropy_with_logits(
            pred,
            target,
            weight=self._weight,
            pos_weight=self._pos_weight,
            reduction=self.reduction,
        )


class MSELoss(LossBase):
    """Mean Squared Error loss.

    Args:
        reduction: Reduction method.
    """

    def __init__(self, reduction: str = "mean") -> None:
        """Initialize the MSE loss.

        Args:
            reduction: Reduction method.
        """
        super().__init__(reduction)

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute MSE loss.

        Args:
            pred: Predicted values.
            target: Target values.

        Returns:
            The computed loss.
        """
        return F.mse_loss(pred, target, reduction=self.reduction)


class L1Loss(LossBase):
    """L1 (Mean Absolute Error) loss.

    Args:
        reduction: Reduction method.
    """

    def __init__(self, reduction: str = "mean") -> None:
        """Initialize the L1 loss.

        Args:
            reduction: Reduction method.
        """
        super().__init__(reduction)

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute L1 loss.

        Args:
            pred: Predicted values.
            target: Target values.

        Returns:
            The computed loss.
        """
        return F.l1_loss(pred, target, reduction=self.reduction)


class SmoothL1Loss(LossBase):
    """Smooth L1 loss (Huber loss).

    Args:
        reduction: Reduction method.
        beta: Threshold at which to switch from L1 to L2 loss.
    """

    def __init__(self, reduction: str = "mean", beta: float = 1.0) -> None:
        """Initialize the Smooth L1 loss.

        Args:
            reduction: Reduction method.
            beta: Threshold at which to switch from L1 to L2 loss.
        """
        super().__init__(reduction)
        self._beta = beta

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute Smooth L1 loss.

        Args:
            pred: Predicted values.
            target: Target values.

        Returns:
            The computed loss.
        """
        return F.smooth_l1_loss(pred, target, reduction=self.reduction, beta=self._beta)


class KLDivLoss(LossBase):
    """Kullback-Leibler divergence loss.

    Args:
        reduction: Reduction method.
        log_target: Whether the target is in log space.
    """

    def __init__(self, reduction: str = "batchmean", log_target: bool = False) -> None:
        """Initialize the KL divergence loss.

        Args:
            reduction: Reduction method.
            log_target: Whether the target is in log space.
        """
        super().__init__(reduction)
        self._log_target = log_target

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute KL divergence loss.

        Args:
            pred: Log-probabilities of shape (N, C).
            target: Target distribution of shape (N, C).

        Returns:
            The computed loss.
        """
        return F.kl_div(
            pred, target, reduction=self.reduction, log_target=self._log_target
        )


class NLLLoss(LossBase):
    """Negative Log-Likelihood loss.

    Args:
        weight: Class weights.
        ignore_index: Index to ignore.
        reduction: Reduction method.
    """

    def __init__(
        self,
        weight: Optional[torch.Tensor] = None,
        ignore_index: int = -100,
        reduction: str = "mean",
    ) -> None:
        """Initialize the NLL loss.

        Args:
            weight: Class weights.
            ignore_index: Index to ignore.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._weight = weight
        self._ignore_index = ignore_index

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute NLL loss.

        Args:
            pred: Log-probabilities of shape (N, C, ...).
            target: Target indices of shape (N, ...).

        Returns:
            The computed loss.
        """
        return F.nll_loss(
            pred,
            target,
            weight=self._weight,
            ignore_index=self._ignore_index,
            reduction=self.reduction,
        )


class FocalLoss(LossBase):
    """Focal Loss for imbalanced classification.

    As described in https://arxiv.org/abs/1708.02002.

    Args:
        alpha: Class weighting factor (scalar or tensor).
        gamma: Focusing parameter (higher = more focus on hard examples).
        reduction: Reduction method.
        ignore_index: Index to ignore.
    """

    def __init__(
        self,
        alpha: Optional[float] = None,
        gamma: float = 2.0,
        reduction: str = "mean",
        ignore_index: int = -100,
    ) -> None:
        """Initialize the Focal loss.

        Args:
            alpha: Class weighting factor.
            gamma: Focusing parameter.
            reduction: Reduction method.
            ignore_index: Index to ignore.
        """
        super().__init__(reduction)
        self._alpha = alpha
        self._gamma = gamma
        self._ignore_index = ignore_index

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute Focal loss.

        Args:
            pred: Predicted logits of shape (N, C).
            target: Target indices of shape (N,).

        Returns:
            The computed loss.
        """
        log_probs = F.log_softmax(pred, dim=-1)
        probs = torch.exp(log_probs)

        # Gather the probabilities of the target classes
        target_mask = target != self._ignore_index
        valid_targets = target[target_mask]

        if valid_targets.numel() == 0:
            return torch.tensor(0.0, device=pred.device, requires_grad=True)

        valid_log_probs = log_probs[target_mask]
        valid_probs = probs[target_mask]

        # Select log probabilities at target indices
        valid_log_probs = valid_log_probs.gather(
            1, valid_targets.unsqueeze(1)
        ).squeeze(1)
        valid_probs = valid_probs.gather(1, valid_targets.unsqueeze(1)).squeeze(1)

        # Compute focal weights
        focal_weight = (1 - valid_probs) ** self._gamma

        # Apply alpha weighting
        if self._alpha is not None:
            alpha_weight = torch.where(
                valid_targets == 1,
                torch.tensor(self._alpha, device=pred.device),
                torch.tensor(1 - self._alpha, device=pred.device),
            )
            focal_weight = focal_weight * alpha_weight

        loss = -focal_weight * valid_log_probs

        return self.reduce(loss)


class ContrastiveLoss(LossBase):
    """Contrastive loss for Siamese networks.

    Args:
        margin: Margin for dissimilar pairs.
        reduction: Reduction method.
    """

    def __init__(self, margin: float = 1.0, reduction: str = "mean") -> None:
        """Initialize the contrastive loss.

        Args:
            margin: Margin for dissimilar pairs.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._margin = margin

    def forward(
        self, emb1: torch.Tensor, emb2: torch.Tensor, label: torch.Tensor
    ) -> torch.Tensor:
        """Compute contrastive loss.

        Args:
            emb1: Embeddings from first branch.
            emb2: Embeddings from second branch.
            label: 1 for similar pairs, 0 for dissimilar.

        Returns:
            The computed loss.
        """
        distances = F.pairwise_distance(emb1, emb2)
        similar = label * distances.pow(2)
        dissimilar = (1 - label) * F.relu(self._margin - distances).pow(2)
        loss = similar + dissimilar
        return self.reduce(loss)


class TripletLoss(LossBase):
    """Triplet loss for metric learning.

    Args:
        margin: Margin for the triplet constraint.
        reduction: Reduction method.
    """

    def __init__(self, margin: float = 1.0, reduction: str = "mean") -> None:
        """Initialize the triplet loss.

        Args:
            margin: Margin for the triplet constraint.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._margin = margin

    def forward(
        self,
        anchor: torch.Tensor,
        positive: torch.Tensor,
        negative: torch.Tensor,
    ) -> torch.Tensor:
        """Compute triplet loss.

        Args:
            anchor: Anchor embeddings.
            positive: Positive embeddings.
            negative: Negative embeddings.

        Returns:
            The computed loss.
        """
        pos_dist = F.pairwise_distance(anchor, positive)
        neg_dist = F.pairwise_distance(anchor, negative)
        loss = F.relu(pos_dist - neg_dist + self._margin)
        return self.reduce(loss)


class InfoNCE(LossBase):
    """InfoNCE loss for contrastive learning.

    As described in https://arxiv.org/abs/1807.03748.

    Args:
        temperature: Temperature scaling factor.
        reduction: Reduction method.
    """

    def __init__(self, temperature: float = 0.07, reduction: str = "mean") -> None:
        """Initialize the InfoNCE loss.

        Args:
            temperature: Temperature scaling factor.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._temperature = temperature

    def forward(
        self,
        query: torch.Tensor,
        positive_key: torch.Tensor,
        negative_keys: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Compute InfoNCE loss.

        Args:
            query: Query embeddings of shape (N, D).
            positive_key: Positive key embeddings of shape (N, D).
            negative_keys: Negative key embeddings of shape (N, K, D) or (K, D).

        Returns:
            The computed loss.
        """
        query_norm = F.normalize(query, dim=-1)
        pos_norm = F.normalize(positive_key, dim=-1)

        # Compute similarity with positive
        pos_sim = torch.sum(query_norm * pos_norm, dim=-1) / self._temperature

        # Compute similarity with negatives
        if negative_keys is not None:
            neg_norm = F.normalize(negative_keys, dim=-1)
            if neg_norm.dim() == 2:
                # Single set of negatives
                neg_sim = torch.mm(query_norm, neg_norm.T) / self._temperature
            else:
                # Per-sample negatives
                neg_sim = torch.bmm(
                    query_norm.unsqueeze(1),
                    neg_norm.transpose(1, 2),
                ).squeeze(1) / self._temperature

            # Concatenate positive and negative similarities
            logits = torch.cat([pos_sim.unsqueeze(1), neg_sim], dim=-1)
            labels = torch.zeros(query.size(0), dtype=torch.long, device=query.device)
        else:
            # In-batch negatives
            logits = torch.mm(query_norm, pos_norm.T) / self._temperature
            labels = torch.arange(query.size(0), device=query.device)

        loss = F.cross_entropy(logits, labels, reduction=self.reduction)
        return loss


class DiceLoss(LossBase):
    """Dice loss for segmentation tasks.

    Args:
        smooth: Smoothing factor to avoid division by zero.
        reduction: Reduction method.
    """

    def __init__(self, smooth: float = 1.0, reduction: str = "mean") -> None:
        """Initialize the Dice loss.

        Args:
            smooth: Smoothing factor.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._smooth = smooth

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Compute Dice loss.

        Args:
            pred: Predicted probabilities of shape (N, C, H, W).
            target: Target mask of shape (N, H, W) or (N, C, H, W).

        Returns:
            The computed loss.
        """
        if pred.dim() == 4 and target.dim() == 3:
            # Convert target to one-hot
            target = F.one_hot(target, num_classes=pred.size(1)).permute(0, 3, 1, 2)

        pred = pred.contiguous().view(pred.size(0), -1)
        target = target.contiguous().view(target.size(0), -1)

        intersection = (pred * target).sum(dim=-1)
        cardinality = pred.sum(dim=-1) + target.sum(dim=-1)

        dice = (2.0 * intersection + self._smooth) / (cardinality + self._smooth)
        loss = 1.0 - dice
        return self.reduce(loss)


class CombinedLoss(LossBase):
    """Loss that combines multiple loss functions with weights.

    Args:
        losses: Dictionary mapping loss names to (loss_function, weight) tuples.
        reduction: Reduction method.
    """

    def __init__(
        self,
        losses: Dict[str, Tuple[LossBase, float]],
        reduction: str = "mean",
    ) -> None:
        """Initialize the combined loss.

        Args:
            losses: Dictionary mapping names to (loss_fn, weight) tuples.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._losses = nn.ModuleDict()
        self._weights: Dict[str, float] = {}

        for name, (loss_fn, weight) in losses.items():
            if isinstance(loss_fn, nn.Module):
                self._losses[name] = loss_fn
            self._weights[name] = weight

    def forward(self, **kwargs: Any) -> torch.Tensor:
        """Compute combined loss.

        Args:
            **kwargs: Keyword arguments that are passed to each loss function.
                Each loss function receives the arguments it needs.

        Returns:
            The weighted sum of all losses.
        """
        total_loss = 0.0
        for name, loss_fn in self._losses.items():
            try:
                loss = loss_fn(**kwargs)
                total_loss = total_loss + self._weights[name] * loss
            except TypeError as e:
                logger.warning(f"Loss '{name}' failed: {e}")
                continue
        return total_loss


class AdaptiveLoss(LossBase):
    """Adaptive loss that adjusts weights based on uncertainty.

    As described in https://arxiv.org/abs/1705.07115.

    Args:
        num_tasks: Number of tasks to combine.
        reduction: Reduction method.
    """

    def __init__(
        self, num_tasks: int = 2, reduction: str = "mean"
    ) -> None:
        """Initialize the adaptive loss.

        Args:
            num_tasks: Number of tasks.
            reduction: Reduction method.
        """
        super().__init__(reduction)
        self._log_vars = nn.Parameter(
            torch.zeros(num_tasks), requires_grad=True
        )

    def forward(self, losses: List[torch.Tensor]) -> torch.Tensor:
        """Compute adaptive multi-task loss.

        Args:
            losses: List of individual task losses.

        Returns:
            The weighted combination of losses.
        """
        total_loss = 0.0
        for i, loss in enumerate(losses):
            precision = torch.exp(-self._log_vars[i])
            total_loss = total_loss + precision * loss + self._log_vars[i] / 2.0
        return total_loss


# Loss registry
LOSS_REGISTRY: Dict[str, Any] = {
    "cross_entropy": CrossEntropyLoss,
    "bce": BCELoss,
    "bce_with_logits": BCEWithLogitsLoss,
    "mse": MSELoss,
    "l1": L1Loss,
    "smooth_l1": SmoothL1Loss,
    "kl_div": KLDivLoss,
    "nll": NLLLoss,
    "focal": FocalLoss,
    "contrastive": ContrastiveLoss,
    "triplet": TripletLoss,
    "info_nce": InfoNCE,
    "dice": DiceLoss,
    "combined": CombinedLoss,
    "adaptive": AdaptiveLoss,
}


def build_loss(
    loss_name: str = "cross_entropy",
    **kwargs: Any,
) -> LossBase:
    """Build a loss function by name.

    Args:
        loss_name: Name of the loss function.
        **kwargs: Arguments passed to the loss constructor.

    Returns:
        The configured loss function.

    Raises:
        ValueError: If the loss name is not recognized.
    """
    loss_name = loss_name.lower().replace("-", "_")

    if loss_name not in LOSS_REGISTRY:
        # Try to use PyTorch's built-in loss
        try:
            pytorch_loss = getattr(nn, loss_name, None)
            if pytorch_loss is not None and isinstance(pytorch_loss, type):
                return pytorch_loss(**kwargs)
        except (AttributeError, TypeError):
            pass

        raise ValueError(
            f"Unknown loss function: '{loss_name}'. "
            f"Available: {list(LOSS_REGISTRY.keys())}"
        )

    loss_cls = LOSS_REGISTRY[loss_name]
    return loss_cls(**kwargs)


def get_loss_info(loss_fn: nn.Module) -> Dict[str, Any]:
    """Get information about a loss function.

    Args:
        loss_fn: The loss function module.

    Returns:
        Dictionary with loss metadata.
    """
    info: Dict[str, Any] = {
        "type": type(loss_fn).__name__,
    }

    if hasattr(loss_fn, "reduction"):
        info["reduction"] = loss_fn.reduction

    return info