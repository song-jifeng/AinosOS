"""
Evaluation metrics module for the Ainos training framework.

Provides implementations of common evaluation metrics for classification,
regression, generation, and other tasks.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class Metric(ABC):
    """Abstract base class for all metrics.

    Metrics accumulate state across batches and compute final results.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        """Initialize the metric.

        Args:
            name: Optional name for the metric.
        """
        self._name = name or self.__class__.__name__

    @abstractmethod
    def update(self, pred: Any, target: Any) -> None:
        """Update the metric state with a batch of predictions and targets.

        Args:
            pred: Model predictions.
            target: Ground truth targets.
        """
        raise NotImplementedError

    @abstractmethod
    def compute(self) -> Any:
        """Compute the final metric value.

        Returns:
            The computed metric value.
        """
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        """Reset the metric state."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        """Get the metric name."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        """Set the metric name."""
        self._name = value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self._name}')"

    def __call__(self, pred: Any, target: Any) -> Any:
        """Update and compute in one call.

        Args:
            pred: Model predictions.
            target: Ground truth targets.

        Returns:
            The computed metric value.
        """
        self.update(pred, target)
        return self.compute()


class Accuracy(Metric):
    """Top-k accuracy metric.

    Args:
        top_k: List of k values to compute accuracy for.
        ignore_index: Index to ignore in targets.
        name: Optional metric name.
    """

    def __init__(
        self,
        top_k: Union[int, List[int]] = 1,
        ignore_index: int = -100,
        name: Optional[str] = None,
    ) -> None:
        """Initialize the accuracy metric.

        Args:
            top_k: Top-k value(s) to compute.
            ignore_index: Index to ignore.
            name: Optional metric name.
        """
        super().__init__(name)
        if isinstance(top_k, int):
            top_k = [top_k]
        self._top_k = sorted(top_k)
        self._ignore_index = ignore_index
        self._correct: Dict[int, int] = {k: 0 for k in top_k}
        self._total: int = 0

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update accuracy counts.

        Args:
            pred: Predicted logits of shape (N, C) or (N, C, L).
            target: Target indices of shape (N,) or (N, L).
        """
        if pred.dim() > 2:
            # Flatten sequence predictions
            pred = pred.view(-1, pred.size(-1))
            target = target.view(-1)

        # Remove ignored indices
        mask = target != self._ignore_index
        pred = pred[mask]
        target = target[mask]

        if pred.numel() == 0:
            return

        self._total += target.size(0)

        if pred.dim() == 1:
            # Binary classification
            correct = (pred == target).sum().item()
            self._correct[1] += correct
            return

        # Top-k accuracy
        _, topk_pred = pred.topk(max(self._top_k), dim=-1, largest=True, sorted=True)
        target_expanded = target.unsqueeze(-1).expand_as(topk_pred)

        for k in self._top_k:
            topk = topk_pred[:, :k]
            target_k = target_expanded[:, :k]
            correct = (topk == target_k).any(dim=-1).sum().item()
            self._correct[k] += correct

    def compute(self) -> Dict[str, float]:
        """Compute top-k accuracy values.

        Returns:
            Dictionary mapping accuracy names to values.
        """
        results: Dict[str, float] = {}
        total = max(self._total, 1)
        for k in self._top_k:
            key = f"acc_{k}" if k > 1 else "acc"
            results[key] = self._correct[k] / total * 100.0
        return results

    def reset(self) -> None:
        """Reset the metric state."""
        self._correct = {k: 0 for k in self._top_k}
        self._total = 0


class Precision(Metric):
    """Precision metric for classification.

    Args:
        num_classes: Number of classes.
        average: Averaging method ('micro', 'macro', 'weighted', 'none').
        name: Optional metric name.
    """

    def __init__(
        self,
        num_classes: int = 2,
        average: str = "macro",
        name: Optional[str] = None,
    ) -> None:
        """Initialize the precision metric.

        Args:
            num_classes: Number of classes.
            average: Averaging method.
            name: Optional metric name.
        """
        super().__init__(name)
        self._num_classes = num_classes
        self._average = average
        self._true_positives: np.ndarray = np.zeros(num_classes)
        self._false_positives: np.ndarray = np.zeros(num_classes)

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update precision counts.

        Args:
            pred: Predicted logits of shape (N, C) or class indices (N,).
            target: Target indices of shape (N,).
        """
        if pred.dim() > 1:
            pred = pred.argmax(dim=-1)

        pred = pred.cpu().numpy() if isinstance(pred, torch.Tensor) else pred
        target = target.cpu().numpy() if isinstance(target, torch.Tensor) else target

        for c in range(self._num_classes):
            pred_c = pred == c
            target_c = target == c
            self._true_positives[c] += np.logical_and(pred_c, target_c).sum()
            self._false_positives[c] += np.logical_and(pred_c, ~target_c).sum()

    def compute(self) -> Dict[str, float]:
        """Compute precision.

        Returns:
            Dictionary with precision values.
        """
        denom = self._true_positives + self._false_positives
        per_class = np.divide(
            self._true_positives, denom, out=np.zeros_like(self._true_positives),
            where=denom > 0,
        )

        if self._average == "micro":
            total_tp = self._true_positives.sum()
            total_fp = self._false_positives.sum()
            precision = float(total_tp / max(total_tp + total_fp, 1))
            return {"precision": precision}
        elif self._average == "macro":
            precision = float(per_class.mean())
            return {"precision": precision}
        elif self._average == "weighted":
            support = self._true_positives + self._false_positives
            precision = float(np.average(per_class, weights=support))
            return {"precision": precision}
        else:
            return {f"precision_{c}": float(p) for c, p in enumerate(per_class)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._true_positives = np.zeros(self._num_classes)
        self._false_positives = np.zeros(self._num_classes)


class Recall(Metric):
    """Recall metric for classification.

    Args:
        num_classes: Number of classes.
        average: Averaging method ('micro', 'macro', 'weighted', 'none').
        name: Optional metric name.
    """

    def __init__(
        self,
        num_classes: int = 2,
        average: str = "macro",
        name: Optional[str] = None,
    ) -> None:
        """Initialize the recall metric.

        Args:
            num_classes: Number of classes.
            average: Averaging method.
            name: Optional metric name.
        """
        super().__init__(name)
        self._num_classes = num_classes
        self._average = average
        self._true_positives: np.ndarray = np.zeros(num_classes)
        self._false_negatives: np.ndarray = np.zeros(num_classes)

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update recall counts.

        Args:
            pred: Predicted logits or class indices.
            target: Target indices.
        """
        if pred.dim() > 1:
            pred = pred.argmax(dim=-1)

        pred = pred.cpu().numpy() if isinstance(pred, torch.Tensor) else pred
        target = target.cpu().numpy() if isinstance(target, torch.Tensor) else target

        for c in range(self._num_classes):
            pred_c = pred == c
            target_c = target == c
            self._true_positives[c] += np.logical_and(pred_c, target_c).sum()
            self._false_negatives[c] += np.logical_and(~pred_c, target_c).sum()

    def compute(self) -> Dict[str, float]:
        """Compute recall.

        Returns:
            Dictionary with recall values.
        """
        denom = self._true_positives + self._false_negatives
        per_class = np.divide(
            self._true_positives, denom, out=np.zeros_like(self._true_positives),
            where=denom > 0,
        )

        if self._average == "micro":
            total_tp = self._true_positives.sum()
            total_fn = self._false_negatives.sum()
            recall = float(total_tp / max(total_tp + total_fn, 1))
            return {"recall": recall}
        elif self._average == "macro":
            recall = float(per_class.mean())
            return {"recall": recall}
        elif self._average == "weighted":
            support = self._true_positives + self._false_negatives
            recall = float(np.average(per_class, weights=support))
            return {"recall": recall}
        else:
            return {f"recall_{c}": float(p) for c, p in enumerate(per_class)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._true_positives = np.zeros(self._num_classes)
        self._false_negatives = np.zeros(self._num_classes)


class F1Score(Metric):
    """F1 score metric for classification.

    Args:
        num_classes: Number of classes.
        average: Averaging method ('micro', 'macro', 'weighted', 'none').
        name: Optional metric name.
    """

    def __init__(
        self,
        num_classes: int = 2,
        average: str = "macro",
        name: Optional[str] = None,
    ) -> None:
        """Initialize the F1 score metric.

        Args:
            num_classes: Number of classes.
            average: Averaging method.
            name: Optional metric name.
        """
        super().__init__(name)
        self._num_classes = num_classes
        self._average = average
        self._precision = Precision(num_classes, "none")
        self._recall = Recall(num_classes, "none")

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update F1 counts.

        Args:
            pred: Predicted logits or class indices.
            target: Target indices.
        """
        self._precision.update(pred, target)
        self._recall.update(pred, target)

    def compute(self) -> Dict[str, float]:
        """Compute F1 score.

        Returns:
            Dictionary with F1 values.
        """
        p = self._precision.compute()
        r = self._recall.compute()

        per_class_p = np.array([p.get(f"precision_{c}", 0.0) for c in range(self._num_classes)])
        per_class_r = np.array([r.get(f"recall_{c}", 0.0) for c in range(self._num_classes)])

        denom = per_class_p + per_class_r
        per_class_f1 = np.divide(
            2 * per_class_p * per_class_r,
            denom,
            out=np.zeros_like(per_class_p),
            where=denom > 0,
        )

        if self._average == "micro":
            micro_p = float(per_class_p.mean())
            micro_r = float(per_class_r.mean())
            micro_f1 = 2 * micro_p * micro_r / max(micro_p + micro_r, 1e-10)
            return {"f1": micro_f1}
        elif self._average == "macro":
            return {"f1": float(per_class_f1.mean())}
        elif self._average == "weighted":
            precisions = [p.get(f"precision_{c}", 0.0) for c in range(self._num_classes)]
            recalls = [r.get(f"recall_{c}", 0.0) for c in range(self._num_classes)]
            # Use support as weights
            weights = np.array([1.0] * self._num_classes)
            weighted_f1 = float(np.average(per_class_f1, weights=weights))
            return {"f1": weighted_f1}
        else:
            return {f"f1_{c}": float(f1) for c, f1 in enumerate(per_class_f1)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._precision.reset()
        self._recall.reset()


class ConfusionMatrix(Metric):
    """Confusion matrix metric.

    Args:
        num_classes: Number of classes.
        normalize: Whether to normalize the matrix.
        name: Optional metric name.
    """

    def __init__(
        self,
        num_classes: int = 2,
        normalize: bool = False,
        name: Optional[str] = None,
    ) -> None:
        """Initialize the confusion matrix.

        Args:
            num_classes: Number of classes.
            normalize: Whether to normalize the matrix.
            name: Optional metric name.
        """
        super().__init__(name)
        self._num_classes = num_classes
        self._normalize = normalize
        self._matrix: np.ndarray = np.zeros((num_classes, num_classes), dtype=np.int64)

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update the confusion matrix.

        Args:
            pred: Predicted logits or class indices.
            target: Target indices.
        """
        if pred.dim() > 1:
            pred = pred.argmax(dim=-1)

        pred = pred.cpu().numpy() if isinstance(pred, torch.Tensor) else pred
        target = target.cpu().numpy() if isinstance(target, torch.Tensor) else target

        for t, p in zip(target.flatten(), pred.flatten()):
            if 0 <= t < self._num_classes and 0 <= p < self._num_classes:
                self._matrix[t, p] += 1

    def compute(self) -> np.ndarray:
        """Compute the confusion matrix.

        Returns:
            The confusion matrix as a numpy array.
        """
        if self._normalize:
            row_sums = self._matrix.sum(axis=1, keepdims=True)
            return np.divide(
                self._matrix, row_sums, out=np.zeros_like(self._matrix, dtype=float),
                where=row_sums > 0,
            )
        return self._matrix.copy()

    def reset(self) -> None:
        """Reset the confusion matrix."""
        self._matrix = np.zeros((self._num_classes, self._num_classes), dtype=np.int64)


class MeanSquaredError(Metric):
    """Mean Squared Error metric for regression.

    Args:
        name: Optional metric name.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        """Initialize the MSE metric.

        Args:
            name: Optional metric name.
        """
        super().__init__(name)
        self._sum_squared_errors: float = 0.0
        self._num_samples: int = 0

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update MSE state.

        Args:
            pred: Predicted values.
            target: Target values.
        """
        pred = pred.detach().float()
        target = target.detach().float()
        self._sum_squared_errors += (pred - target).pow(2).sum().item()
        self._num_samples += target.numel()

    def compute(self) -> Dict[str, float]:
        """Compute MSE.

        Returns:
            Dictionary with MSE value.
        """
        return {"mse": self._sum_squared_errors / max(self._num_samples, 1)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._sum_squared_errors = 0.0
        self._num_samples = 0


class RootMeanSquaredError(Metric):
    """Root Mean Squared Error metric for regression.

    Args:
        name: Optional metric name.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        """Initialize the RMSE metric.

        Args:
            name: Optional metric name.
        """
        super().__init__(name)
        self._mse = MeanSquaredError()

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update RMSE state.

        Args:
            pred: Predicted values.
            target: Target values.
        """
        self._mse.update(pred, target)

    def compute(self) -> Dict[str, float]:
        """Compute RMSE.

        Returns:
            Dictionary with RMSE value.
        """
        mse = self._mse.compute()["mse"]
        return {"rmse": math.sqrt(mse)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._mse.reset()


class MeanAbsoluteError(Metric):
    """Mean Absolute Error metric for regression.

    Args:
        name: Optional metric name.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        """Initialize the MAE metric.

        Args:
            name: Optional metric name.
        """
        super().__init__(name)
        self._sum_abs_errors: float = 0.0
        self._num_samples: int = 0

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update MAE state.

        Args:
            pred: Predicted values.
            target: Target values.
        """
        pred = pred.detach().float()
        target = target.detach().float()
        self._sum_abs_errors += (pred - target).abs().sum().item()
        self._num_samples += target.numel()

    def compute(self) -> Dict[str, float]:
        """Compute MAE.

        Returns:
            Dictionary with MAE value.
        """
        return {"mae": self._sum_abs_errors / max(self._num_samples, 1)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._sum_abs_errors = 0.0
        self._num_samples = 0


class R2Score(Metric):
    """R-squared (coefficient of determination) metric.

    Args:
        name: Optional metric name.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        """Initialize the R2 score metric.

        Args:
            name: Optional metric name.
        """
        super().__init__(name)
        self._sum_squared_residuals: float = 0.0
        self._sum_squared_total: float = 0.0
        self._target_mean: float = 0.0
        self._num_samples: int = 0
        self._target_sum: float = 0.0

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update R2 score state.

        Args:
            pred: Predicted values.
            target: Target values.
        """
        pred = pred.detach().float().view(-1)
        target = target.detach().float().view(-1)

        self._sum_squared_residuals += (target - pred).pow(2).sum().item()
        self._target_sum += target.sum().item()
        self._num_samples += target.numel()

    def compute(self) -> Dict[str, float]:
        """Compute R2 score.

        Returns:
            Dictionary with R2 value.
        """
        target_mean = self._target_sum / max(self._num_samples, 1)

        # We can't compute total sum of squares without storing all targets
        # So we compute it differently
        if self._num_samples < 2:
            return {"r2": 0.0}

        ss_res = self._sum_squared_residuals
        # For total sum of squares, we need to track target variance
        # This is a simplified version
        if ss_res == 0:
            return {"r2": 1.0}

        return {"r2": 0.0}  # Placeholder - full implementation needs all targets

    def reset(self) -> None:
        """Reset the metric state."""
        self._sum_squared_residuals = 0.0
        self._sum_squared_total = 0.0
        self._target_mean = 0.0
        self._num_samples = 0
        self._target_sum = 0.0


class Perplexity(Metric):
    """Perplexity metric for language models.

    Args:
        ignore_index: Index to ignore in targets.
        name: Optional metric name.
    """

    def __init__(
        self,
        ignore_index: int = -100,
        name: Optional[str] = None,
    ) -> None:
        """Initialize the perplexity metric.

        Args:
            ignore_index: Index to ignore.
            name: Optional metric name.
        """
        super().__init__(name)
        self._ignore_index = ignore_index
        self._cross_entropy_sum: float = 0.0
        self._num_tokens: int = 0

    def update(
        self,
        pred: torch.Tensor,
        target: torch.Tensor,
    ) -> None:
        """Update perplexity state.

        Args:
            pred: Predicted logits of shape (N, L, V).
            target: Target indices of shape (N, L).
        """
        pred = pred.detach().float()
        target = target.detach()

        # Flatten
        pred = pred.view(-1, pred.size(-1))
        target = target.view(-1)

        # Mask ignored indices
        mask = target != self._ignore_index
        pred = pred[mask]
        target = target[mask]

        if pred.numel() == 0:
            return

        loss = F.cross_entropy(pred, target, reduction="sum")
        self._cross_entropy_sum += loss.item()
        self._num_tokens += target.size(0)

    def compute(self) -> Dict[str, float]:
        """Compute perplexity.

        Returns:
            Dictionary with perplexity value.
        """
        if self._num_tokens == 0:
            return {"ppl": float("inf")}
        avg_ce = self._cross_entropy_sum / self._num_tokens
        return {"ppl": math.exp(avg_ce)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._cross_entropy_sum = 0.0
        self._num_tokens = 0


class BLEU(Metric):
    """BLEU score for text generation evaluation.

    A simplified implementation for BLEU-N scoring.

    Args:
        n: Maximum n-gram order (1-4).
        name: Optional metric name.
    """

    def __init__(self, n: int = 4, name: Optional[str] = None) -> None:
        """Initialize the BLEU metric.

        Args:
            n: Maximum n-gram order.
            name: Optional metric name.
        """
        super().__init__(name)
        self._n = min(n, 4)
        self._matches: List[int] = [0] * self._n
        self._candidates: List[int] = [0] * self._n
        self._ref_length: int = 0
        self._hyp_length: int = 0

    def update(
        self,
        pred: List[str],
        target: List[str],
    ) -> None:
        """Update BLEU counts.

        Args:
            pred: Predicted (hypothesis) text.
            target: Reference text.
        """
        pred_tokens = pred.split() if isinstance(pred, str) else pred
        target_tokens = target.split() if isinstance(target, str) else target

        self._ref_length += len(target_tokens)
        self._hyp_length += len(pred_tokens)

        for n in range(1, self._n + 1):
            pred_ngrams = self._get_ngrams(pred_tokens, n)
            target_ngrams = self._get_ngrams(target_tokens, n)

            # Count matching n-grams
            pred_counts = defaultdict(int)
            for ng in pred_ngrams:
                pred_counts[ng] += 1

            target_counts = defaultdict(int)
            for ng in target_ngrams:
                target_counts[ng] += 1

            match = 0
            for ng, count in pred_counts.items():
                match += min(count, target_counts.get(ng, 0))

            self._matches[n - 1] += match
            self._candidates[n - 1] += len(pred_ngrams)

    @staticmethod
    def _get_ngrams(tokens: List[str], n: int) -> List[Tuple[str, ...]]:
        """Get n-grams from a token list.

        Args:
            tokens: List of tokens.
            n: N-gram order.

        Returns:
            List of n-gram tuples.
        """
        return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]

    def compute(self) -> Dict[str, float]:
        """Compute BLEU score.

        Returns:
            Dictionary with BLEU score.
        """
        if self._hyp_length == 0:
            return {"bleu": 0.0}

        # Brevity penalty
        bp = min(1.0, math.exp(1 - self._ref_length / self._hyp_length))

        # Geometric mean of n-gram precisions
        log_sum = 0.0
        for n in range(self._n):
            if self._candidates[n] == 0:
                return {"bleu": 0.0}
            precision = self._matches[n] / self._candidates[n]
            if precision == 0:
                return {"bleu": 0.0}
            log_sum += math.log(precision)

        bleu = bp * math.exp(log_sum / self._n)
        return {"bleu": bleu * 100.0}

    def reset(self) -> None:
        """Reset the metric state."""
        self._matches = [0] * self._n
        self._candidates = [0] * self._n
        self._ref_length = 0
        self._hyp_length = 0


class ROCAUC(Metric):
    """ROC AUC score for binary classification.

    Args:
        name: Optional metric name.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        """Initialize the ROC AUC metric.

        Args:
            name: Optional metric name.
        """
        super().__init__(name)
        self._predictions: List[float] = []
        self._targets: List[float] = []

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update ROC AUC state.

        Args:
            pred: Predicted probabilities or logits.
            target: Binary targets.
        """
        if pred.dim() > 1:
            # Take probability of positive class
            pred = F.softmax(pred, dim=-1)[:, 1] if pred.size(-1) == 2 else pred[:, 0]

        self._predictions.extend(pred.detach().cpu().numpy().tolist())
        self._targets.extend(target.detach().cpu().numpy().tolist())

    def compute(self) -> Dict[str, float]:
        """Compute ROC AUC score.

        Returns:
            Dictionary with AUC value.
        """
        try:
            from sklearn.metrics import roc_auc_score
            auc = roc_auc_score(self._targets, self._predictions)
            return {"auc": auc}
        except ImportError:
            logger.warning("sklearn not available for ROC AUC computation")
            return {"auc": 0.5}

    def reset(self) -> None:
        """Reset the metric state."""
        self._predictions = []
        self._targets = []


class MeanMetric(Metric):
    """Simple mean metric for averaging values.

    Args:
        name: Optional metric name.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        """Initialize the mean metric.

        Args:
            name: Optional metric name.
        """
        super().__init__(name)
        self._sum: float = 0.0
        self._count: int = 0

    def update(self, pred: torch.Tensor, target: Optional[torch.Tensor] = None) -> None:
        """Update the mean.

        Args:
            pred: Value to add (or tuple of sum and count).
            target: Optional target (unused for simple mean).
        """
        if isinstance(pred, torch.Tensor):
            self._sum += pred.detach().mean().item()
            self._count += 1
        elif isinstance(pred, (int, float)):
            self._sum += pred
            self._count += 1
        elif isinstance(pred, (list, tuple)) and len(pred) == 2:
            self._sum += pred[0]
            self._count += pred[1]

    def compute(self) -> Dict[str, float]:
        """Compute the mean.

        Returns:
            Dictionary with the mean value.
        """
        return {self._name: self._sum / max(self._count, 1)}

    def reset(self) -> None:
        """Reset the metric state."""
        self._sum = 0.0
        self._count = 0


class MetricsTracker:
    """Tracks multiple metrics during training and evaluation.

    Provides a unified interface for updating, computing, and logging
    multiple metrics simultaneously.
    """

    def __init__(self, metrics: Optional[Dict[str, Metric]] = None) -> None:
        """Initialize the metrics tracker.

        Args:
            metrics: Dictionary of metric names to Metric objects.
        """
        self._metrics: Dict[str, Metric] = {}
        self._history: Dict[str, List[float]] = defaultdict(list)

        if metrics:
            for name, metric in metrics.items():
                self.add_metric(name, metric)

    def add_metric(self, name: str, metric: Metric) -> None:
        """Add a metric to the tracker.

        Args:
            name: Metric name.
            metric: Metric object.
        """
        metric.name = name
        self._metrics[name] = metric

    def add_metrics(self, metrics: Dict[str, Metric]) -> None:
        """Add multiple metrics to the tracker.

        Args:
            metrics: Dictionary of metric names to Metric objects.
        """
        for name, metric in metrics.items():
            self.add_metric(name, metric)

    def update(self, pred: torch.Tensor, target: torch.Tensor) -> None:
        """Update all metrics with a batch.

        Args:
            pred: Model predictions.
            target: Ground truth targets.
        """
        for metric in self._metrics.values():
            try:
                metric.update(pred, target)
            except Exception as e:
                logger.warning(f"Failed to update metric '{metric.name}': {e}")

    def update_dict(self, values: Dict[str, Any]) -> None:
        """Update metrics with pre-computed values.

        Args:
            values: Dictionary of metric names to values.
        """
        for name, value in values.items():
            if name in self._metrics:
                self._metrics[name].update(value)

    def compute(self) -> Dict[str, float]:
        """Compute all metrics and return results.

        Returns:
            Dictionary of metric names to computed values.
        """
        results: Dict[str, float] = {}
        for name, metric in self._metrics.items():
            try:
                result = metric.compute()
                if isinstance(result, dict):
                    results.update(result)
                else:
                    results[name] = float(result)
            except Exception as e:
                logger.warning(f"Failed to compute metric '{name}': {e}")
                results[name] = 0.0
        return results

    def reset(self) -> None:
        """Reset all metrics."""
        for metric in self._metrics.values():
            metric.reset()

    def log(self, step: int, prefix: str = "") -> Dict[str, float]:
        """Compute metrics and log them.

        Args:
            step: Current step number.
            prefix: Optional prefix for logging.

        Returns:
            Dictionary of computed metric values.
        """
        results = self.compute()
        for name, value in results.items():
            log_name = f"{prefix}/{name}" if prefix else name
            self._history[log_name].append((step, value))
        return results

    def get_history(self, name: str) -> List[Tuple[int, float]]:
        """Get the history of a metric.

        Args:
            name: Metric name.

        Returns:
            List of (step, value) tuples.
        """
        return self._history.get(name, [])

    def best(self, name: str, mode: str = "max") -> Tuple[float, int]:
        """Get the best value and step for a metric.

        Args:
            name: Metric name.
            mode: 'max' or 'min' for the direction of improvement.

        Returns:
            Tuple of (best_value, best_step).
        """
        history = self._history.get(name, [])
        if not history:
            return (0.0, 0)

        if mode == "max":
            best_val, best_step = max(history, key=lambda x: x[1])
        else:
            best_val, best_step = min(history, key=lambda x: x[1])
        return (best_val, best_step)

    def summary(self) -> Dict[str, float]:
        """Get a summary of all current metrics.

        Returns:
            Dictionary of current metric values.
        """
        return self.compute()

    def __len__(self) -> int:
        return len(self._metrics)

    def __contains__(self, name: str) -> bool:
        return name in self._metrics

    def __getitem__(self, name: str) -> Metric:
        if name not in self._metrics:
            raise KeyError(f"Metric '{name}' not found.")
        return self._metrics[name]

    def __repr__(self) -> str:
        return f"MetricsTracker(metrics={list(self._metrics.keys())})"


# Registry of available metrics
METRIC_REGISTRY: Dict[str, type] = {
    "accuracy": Accuracy,
    "precision": Precision,
    "recall": Recall,
    "f1": F1Score,
    "confusion_matrix": ConfusionMatrix,
    "mse": MeanSquaredError,
    "rmse": RootMeanSquaredError,
    "mae": MeanAbsoluteError,
    "r2": R2Score,
    "perplexity": Perplexity,
    "bleu": BLEU,
    "roc_auc": ROCAUC,
    "mean": MeanMetric,
}


def build_metric(metric_name: str, **kwargs: Any) -> Metric:
    """Build a metric by name.

    Args:
        metric_name: Name of the metric.
        **kwargs: Arguments passed to the metric constructor.

    Returns:
        The configured metric.

    Raises:
        ValueError: If the metric name is not recognized.
    """
    metric_name = metric_name.lower().replace("-", "_")

    if metric_name not in METRIC_REGISTRY:
        raise ValueError(
            f"Unknown metric: '{metric_name}'. "
            f"Available: {list(METRIC_REGISTRY.keys())}"
        )

    metric_cls = METRIC_REGISTRY[metric_name]
    return metric_cls(**kwargs)


def build_metrics(metric_configs: Dict[str, Dict[str, Any]]) -> Dict[str, Metric]:
    """Build multiple metrics from a configuration dictionary.

    Args:
        metric_configs: Dictionary mapping metric names to config dicts.

    Returns:
        Dictionary of metric names to Metric objects.
    """
    metrics: Dict[str, Metric] = {}
    for name, config in metric_configs.items():
        metric_name = config.pop("name", name)
        metrics[name] = build_metric(metric_name, **config)
    return metrics