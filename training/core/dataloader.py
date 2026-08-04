"""
DataLoader implementation for the Ainos training framework.

Provides batching, shuffling, collation, and multi-worker data loading.
"""

from __future__ import annotations

import math
import random
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import numpy as np
import torch

from .dataset import Dataset


def default_collate(batch: List[Any]) -> Any:
    """Default collate function that batches samples.

    Args:
        batch: List of samples from the dataset.

    Returns:
        Batched samples.

    Raises:
        TypeError: If the batch cannot be collated.
    """
    if not batch:
        return {}

    elem = batch[0]

    if isinstance(elem, torch.Tensor):
        return torch.stack(batch, dim=0)

    elif isinstance(elem, (int, float, bool)):
        return torch.tensor(batch)

    elif isinstance(elem, str):
        return batch

    elif isinstance(elem, np.ndarray):
        return torch.from_numpy(np.stack(batch, axis=0))

    elif isinstance(elem, dict):
        return {key: default_collate([d[key] for d in batch]) for key in elem}

    elif isinstance(elem, (list, tuple)):
        transposed = list(zip(*batch))
        return [default_collate(items) for items in transposed]

    elif elem is None:
        return None

    else:
        try:
            return torch.tensor(batch)
        except (TypeError, ValueError):
            return batch


def collate_with_padding(
    batch: List[Dict[str, Any]],
    padding_value: int = 0,
    max_length: Optional[int] = None,
    pad_to_multiple_of: Optional[int] = None,
) -> Dict[str, torch.Tensor]:
    """Collate a batch of tokenized sequences with padding.

    Args:
        batch: List of tokenized samples with 'input_ids' and optionally 'attention_mask'.
        padding_value: Value to use for padding.
        max_length: Maximum length to pad to (None for longest in batch).
        pad_to_multiple_of: Pad to a multiple of this value.

    Returns:
        Dictionary of batched tensors.
    """
    input_ids = [item["input_ids"] for item in batch]
    attention_masks = [
        item.get("attention_mask", torch.ones_like(item["input_ids"]))
        for item in batch
    ]
    labels = [item.get("labels") for item in batch]

    # Determine max length
    lengths = [ids.size(-1) for ids in input_ids]
    if max_length is not None:
        pad_length = max_length
    else:
        pad_length = max(lengths)

    if pad_to_multiple_of is not None:
        pad_length = math.ceil(pad_length / pad_to_multiple_of) * pad_to_multiple_of

    # Pad input_ids
    padded_ids = torch.full(
        (len(batch), pad_length), padding_value, dtype=input_ids[0].dtype
    )
    padded_masks = torch.zeros(
        (len(batch), pad_length), dtype=attention_masks[0].dtype
    )

    for i, ids in enumerate(input_ids):
        seq_len = ids.size(-1)
        padded_ids[i, :seq_len] = ids
        padded_masks[i, :seq_len] = attention_masks[i]

    result: Dict[str, torch.Tensor] = {
        "input_ids": padded_ids,
        "attention_mask": padded_masks,
    }

    if labels[0] is not None:
        padded_labels = torch.full(
            (len(batch), pad_length), -100, dtype=labels[0].dtype
        )
        for i, lbl in enumerate(labels):
            seq_len = lbl.size(-1)
            padded_labels[i, :seq_len] = lbl
        result["labels"] = padded_labels

    return result


def collate_with_bert_padding(batch: List[Any]) -> Dict[str, torch.Tensor]:
    """Collate function for BERT-style models.

    Handles input_ids, attention_mask, token_type_ids, and labels.

    Args:
        batch: List of samples from the dataset.

    Returns:
        Batched tensors.
    """
    elem = batch[0]
    if isinstance(elem, dict):
        return collate_with_padding(batch)  # type: ignore

    # Assume batch is list of (input_ids, attention_mask, labels) tuples
    input_ids = [item[0] for item in batch]
    attention_masks = [item[1] for item in batch]
    labels = [item[2] for item in batch] if len(batch[0]) > 2 else None

    max_len = max(ids.size(-1) for ids in input_ids)
    batch_size = len(batch)

    padded_ids = torch.zeros(batch_size, max_len, dtype=input_ids[0].dtype)
    padded_masks = torch.zeros(batch_size, max_len, dtype=attention_masks[0].dtype)

    for i, ids in enumerate(input_ids):
        seq_len = ids.size(-1)
        padded_ids[i, :seq_len] = ids
        padded_masks[i, :seq_len] = attention_masks[i]

    result: Dict[str, torch.Tensor] = {
        "input_ids": padded_ids,
        "attention_mask": padded_masks,
    }

    if labels is not None:
        padded_labels = torch.full(
            (batch_size, max_len), -100, dtype=labels[0].dtype
        )
        for i, lbl in enumerate(labels):
            seq_len = lbl.size(-1)
            padded_labels[i, :seq_len] = lbl
        result["labels"] = padded_labels

    return result


class DataLoader:
    """DataLoader for batching and iterating over datasets.

    Supports automatic batching, shuffling, collation, and multi-worker
    data loading via PyTorch's DataLoader.
    """

    def __init__(
        self,
        dataset: Dataset,
        batch_size: int = 1,
        shuffle: bool = False,
        sampler: Optional[Any] = None,
        batch_sampler: Optional[Any] = None,
        num_workers: int = 0,
        collate_fn: Optional[Callable] = None,
        pin_memory: bool = False,
        drop_last: bool = False,
        timeout: float = 0.0,
        worker_init_fn: Optional[Callable] = None,
        prefetch_factor: int = 2,
        persistent_workers: bool = False,
        seed: int = 42,
    ) -> None:
        """Initialize the DataLoader.

        Args:
            dataset: The dataset to load data from.
            batch_size: Number of samples per batch.
            shuffle: Whether to shuffle the data at each epoch.
            sampler: Custom sampler for indexing.
            batch_sampler: Custom batch-level sampler.
            num_workers: Number of subprocesses for data loading.
            collate_fn: Function to collate samples into a batch.
            pin_memory: Whether to pin memory for faster GPU transfer.
            drop_last: Drop the last incomplete batch.
            timeout: Timeout for data loading (seconds).
            worker_init_fn: Function to initialize worker processes.
            prefetch_factor: Number of batches to prefetch per worker.
            persistent_workers: Keep workers alive between epochs.
            seed: Random seed for reproducibility.
        """
        self._dataset = dataset
        self._batch_size = batch_size
        self._shuffle = shuffle
        self._num_workers = num_workers
        self._pin_memory = pin_memory
        self._drop_last = drop_last
        self._timeout = timeout
        self._worker_init_fn = worker_init_fn
        self._prefetch_factor = prefetch_factor
        self._persistent_workers = persistent_workers
        self._seed = seed
        self._rng = random.Random(seed)

        # Sampler
        if sampler is not None:
            self._sampler = sampler
        elif batch_sampler is not None:
            self._sampler = batch_sampler
        else:
            self._sampler = None

        # Collate function
        if collate_fn is not None:
            self._collate_fn = collate_fn
        else:
            self._collate_fn = default_collate

        # Build torch DataLoader for multi-worker scenarios
        self._torch_loader: Optional[torch.utils.data.DataLoader] = None
        self._use_torch = num_workers > 0 or pin_memory

        if self._use_torch:
            self._build_torch_loader()

    def _build_torch_loader(self) -> None:
        """Build PyTorch DataLoader for multi-worker support."""
        torch_dataset = _TorchAdapter(self._dataset)

        self._torch_loader = torch.utils.data.DataLoader(
            torch_dataset,
            batch_size=self._batch_size,
            shuffle=self._shuffle if self._sampler is None else False,
            sampler=self._sampler if not isinstance(self._sampler, torch.utils.data.Sampler) else None,
            num_workers=self._num_workers,
            collate_fn=self._collate_fn,
            pin_memory=self._pin_memory,
            drop_last=self._drop_last,
            timeout=self._timeout,
            worker_init_fn=self._worker_init_fn,
            prefetch_factor=self._prefetch_factor if self._num_workers > 0 else None,
            persistent_workers=self._persistent_workers,
        )

    @property
    def dataset(self) -> Dataset:
        """Get the underlying dataset."""
        return self._dataset

    @property
    def batch_size(self) -> int:
        """Get the batch size."""
        return self._batch_size

    def __len__(self) -> int:
        """Get the number of batches."""
        if self._torch_loader is not None:
            return len(self._torch_loader)
        total = len(self._dataset)
        if self._drop_last:
            return total // self._batch_size
        return (total + self._batch_size - 1) // self._batch_size

    def __iter__(self) -> Iterator[Any]:
        """Iterate over batches."""
        if self._torch_loader is not None:
            yield from self._torch_loader
        else:
            yield from self._iter_batches()

    def _iter_batches(self) -> Iterator[Any]:
        """Generate batches without multiprocessing."""
        indices = list(range(len(self._dataset)))

        if self._shuffle:
            self._rng.shuffle(indices)

        if self._sampler is not None:
            if hasattr(self._sampler, "__iter__"):
                indices = list(iter(self._sampler))
            else:
                indices = list(self._sampler)

        for i in range(0, len(indices), self._batch_size):
            batch_indices = indices[i : i + self._batch_size]
            if self._drop_last and len(batch_indices) < self._batch_size:
                break
            batch = [self._dataset[idx] for idx in batch_indices]
            yield self._collate_fn(batch)

    def set_epoch(self, epoch: int) -> None:
        """Set the epoch for the sampler (for distributed training).

        Args:
            epoch: Current epoch number.
        """
        if hasattr(self._sampler, "set_epoch"):
            self._sampler.set_epoch(epoch)
        self._seed = self._seed + epoch


class _TorchAdapter(torch.utils.data.Dataset):
    """Adapter to wrap our Dataset for PyTorch's DataLoader."""

    def __init__(self, dataset: Dataset) -> None:
        """Initialize the adapter.

        Args:
            dataset: The dataset to wrap.
        """
        self._dataset = dataset

    def __len__(self) -> int:
        return len(self._dataset)

    def __getitem__(self, index: int) -> Any:
        return self._dataset[index]