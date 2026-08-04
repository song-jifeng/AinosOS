"""
Dataset management module for the Ainos training framework.

Provides dataset loading, processing, and management for various data formats
including JSON, CSV, Parquet, and HuggingFace datasets.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import random
import sys
import warnings
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
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
    Union,
)

import numpy as np
import torch

logger = logging.getLogger(__name__)


class DatasetError(Exception):
    """Base exception for dataset-related errors."""

    pass


class DatasetNotFoundError(DatasetError):
    """Raised when a dataset file is not found."""

    pass


class DatasetFormatError(DatasetError):
    """Raised when a dataset file has an invalid format."""

    pass


@dataclass
class DatasetConfig:
    """Configuration for dataset loading.

    Attributes:
        path: Path to the dataset file or directory.
        format: Data format ('json', 'jsonl', 'csv', 'parquet', 'huggingface').
        split: Dataset split ('train', 'val', 'test').
        shuffle: Whether to shuffle the dataset.
        seed: Random seed for shuffling.
        max_samples: Maximum number of samples to load (None for all).
        cache_dir: Directory for caching downloaded datasets.
        num_workers: Number of workers for data loading.
        prefetch_factor: Number of batches to prefetch per worker.
        persistent_workers: Whether workers persist between epochs.
    """

    path: str = ""
    format: str = "json"
    split: str = "train"
    shuffle: bool = True
    seed: int = 42
    max_samples: Optional[int] = None
    cache_dir: Optional[str] = None
    num_workers: int = 0
    prefetch_factor: int = 2
    persistent_workers: bool = False


class Dataset(ABC):
    """Abstract base class for datasets.

    Provides a unified interface for loading data from various sources.
    Subclasses must implement __len__ and __getitem__.
    """

    def __init__(
        self,
        config: Optional[DatasetConfig] = None,
        transform: Optional[Callable] = None,
        target_transform: Optional[Callable] = None,
    ) -> None:
        """Initialize the dataset.

        Args:
            config: Dataset configuration.
            transform: Transform to apply to input features.
            target_transform: Transform to apply to targets.
        """
        self.config = config or DatasetConfig()
        self.transform = transform
        self.target_transform = target_transform
        self._data: List[Any] = []
        self._indices: List[int] = []
        self._rng = random.Random(self.config.seed)

    @abstractmethod
    def __len__(self) -> int:
        """Return the number of samples in the dataset.

        Returns:
            Number of samples.
        """
        raise NotImplementedError

    @abstractmethod
    def __getitem__(self, index: int) -> Any:
        """Get a sample by index.

        Args:
            index: Sample index.

        Returns:
            The sample at the given index.
        """
        raise NotImplementedError

    def __iter__(self) -> Iterator[Any]:
        """Iterate over the dataset.

        Yields:
            Each sample in the dataset.
        """
        for i in range(len(self)):
            yield self[i]

    def __add__(self, other: Dataset) -> ConcatDataset:
        """Concatenate two datasets.

        Args:
            other: Another dataset to concatenate.

        Returns:
            A ConcatDataset containing both datasets.
        """
        return ConcatDataset([self, other])

    def __getitems__(self, indices: List[int]) -> List[Any]:
        """Get multiple samples by indices.

        Args:
            indices: List of sample indices.

        Returns:
            List of samples at the given indices.
        """
        return [self[i] for i in indices]

    def __contains__(self, item: Any) -> bool:
        """Check if an item is in the dataset.

        Args:
            item: The item to check.

        Returns:
            True if the item is in the dataset.
        """
        return item in self._data

    @property
    def num_samples(self) -> int:
        """Get the number of samples."""
        return len(self)

    @property
    def shape(self) -> Optional[Tuple[int, ...]]:
        """Get the shape of a sample, if available.

        Returns:
            Shape tuple, or None if not determinable.
        """
        try:
            sample = self[0]
            if isinstance(sample, torch.Tensor):
                return sample.shape
            if isinstance(sample, np.ndarray):
                return sample.shape
            if isinstance(sample, dict):
                return {k: v.shape if hasattr(v, "shape") else None for k, v in sample.items()}  # type: ignore
        except (IndexError, KeyError, TypeError):
            pass
        return None

    def get_labels(self) -> List[Any]:
        """Get all unique labels in the dataset.

        Returns:
            List of unique labels.
        """
        labels: set = set()
        for sample in self:
            if isinstance(sample, dict) and "label" in sample:
                labels.add(sample["label"])
            elif isinstance(sample, (list, tuple)) and len(sample) >= 2:
                labels.add(sample[1])
        return sorted(labels)

    def split(
        self,
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
        seed: Optional[int] = None,
    ) -> Tuple[Subset, Subset, Subset]:
        """Split the dataset into train/val/test subsets.

        Args:
            train_ratio: Proportion for training.
            val_ratio: Proportion for validation.
            test_ratio: Proportion for testing.
            seed: Random seed for reproducibility.

        Returns:
            Tuple of (train_dataset, val_dataset, test_dataset).

        Raises:
            ValueError: If the ratios don't sum to 1.0.
        """
        if abs(train_ratio + val_ratio + test_ratio - 1.0) > 1e-10:
            raise ValueError(
                f"Ratios must sum to 1.0, got {train_ratio + val_ratio + test_ratio}"
            )

        total = len(self)
        lengths = [
            int(train_ratio * total),
            int(val_ratio * total),
            total - int(train_ratio * total) - int(val_ratio * total),
        ]

        rng = random.Random(seed if seed is not None else self.config.seed)
        indices = list(range(total))
        rng.shuffle(indices)

        subsets = []
        start = 0
        for length in lengths:
            if length == 0:
                subsets.append(Subset(self, []))
            else:
                subsets.append(Subset(self, indices[start : start + length]))
            start += length

        return tuple(subsets)  # type: ignore

    def select(self, indices: List[int]) -> Subset:
        """Select a subset of the dataset by indices.

        Args:
            indices: List of indices to select.

        Returns:
            A Subset containing the selected indices.
        """
        return Subset(self, indices)

    def shuffle(self, seed: Optional[int] = None) -> None:
        """Shuffle the dataset in-place.

        Args:
            seed: Random seed for shuffling.
        """
        seed = seed if seed is not None else self.config.seed
        self._rng = random.Random(seed)
        self._indices = list(range(len(self)))
        self._rng.shuffle(self._indices)

    def map(
        self,
        function: Callable[[Any], Any],
        with_indices: bool = False,
    ) -> MappedDataset:
        """Apply a function to each sample in the dataset.

        Args:
            function: The function to apply.
            with_indices: If True, the function receives (index, sample).

        Returns:
            A MappedDataset wrapping the original dataset.
        """
        return MappedDataset(self, function, with_indices)

    def filter(self, predicate: Callable[[Any], bool]) -> FilteredDataset:
        """Filter samples based on a predicate.

        Args:
            predicate: A function that takes a sample and returns True/False.

        Returns:
            A FilteredDataset containing only matching samples.
        """
        return FilteredDataset(self, predicate)

    def batch(self, batch_size: int) -> BatchedDataset:
        """Batch samples into groups.

        Args:
            batch_size: Number of samples per batch.

        Returns:
            A BatchedDataset.
        """
        return BatchedDataset(self, batch_size)

    @staticmethod
    def from_file(
        path: Union[str, Path],
        format: Optional[str] = None,
        **kwargs: Any,
    ) -> Dataset:
        """Load a dataset from a file.

        Args:
            path: Path to the dataset file.
            format: Data format. If None, inferred from extension.
            **kwargs: Additional arguments passed to the dataset constructor.

        Returns:
            A loaded dataset.

        Raises:
            DatasetFormatError: If the format is not supported or cannot be inferred.
            DatasetNotFoundError: If the file does not exist.
        """
        path = Path(path)
        if not path.exists():
            raise DatasetNotFoundError(f"Dataset file not found: {path}")

        if format is None:
            ext = path.suffix.lower()
            format_map = {
                ".json": "json",
                ".jsonl": "jsonl",
                ".csv": "csv",
                ".tsv": "csv",
                ".parquet": "parquet",
                ".arrow": "huggingface",
            }
            format = format_map.get(ext)
            if format is None:
                raise DatasetFormatError(
                    f"Cannot infer format from extension '{ext}'. "
                    f"Supported: {list(format_map.keys())}"
                )

        if format == "json":
            return JsonDataset(str(path), **kwargs)
        elif format == "jsonl":
            return JsonlDataset(str(path), **kwargs)
        elif format == "csv":
            return CsvDataset(str(path), **kwargs)
        elif format == "parquet":
            return ParquetDataset(str(path), **kwargs)
        elif format == "huggingface":
            return HuggingFaceDataset(str(path), **kwargs)
        else:
            raise DatasetFormatError(f"Unsupported format: {format}")

    @staticmethod
    def from_huggingface(
        name: str,
        split: str = "train",
        **kwargs: Any,
    ) -> HuggingFaceDataset:
        """Load a dataset from HuggingFace Datasets.

        Args:
            name: Dataset name on HuggingFace Hub.
            split: Dataset split to load.
            **kwargs: Additional arguments passed to the dataset constructor.

        Returns:
            A HuggingFaceDataset.
        """
        return HuggingFaceDataset(name, split=split, **kwargs)

    @staticmethod
    def from_dict(data: Dict[str, List[Any]]) -> DictDataset:
        """Create a dataset from a dictionary of lists.

        Args:
            data: Dictionary mapping column names to lists of values.

        Returns:
            A DictDataset.
        """
        return DictDataset(data)

    @staticmethod
    def from_list(data: List[Any]) -> ListDataset:
        """Create a dataset from a list of samples.

        Args:
            data: List of samples.

        Returns:
            A ListDataset.
        """
        return ListDataset(data)

    @staticmethod
    def chain(datasets: List[Dataset]) -> ConcatDataset:
        """Chain multiple datasets together.

        Args:
            datasets: List of datasets to chain.

        Returns:
            A ConcatDataset.
        """
        return ConcatDataset(datasets)


class ListDataset(Dataset):
    """Dataset wrapping a list of samples."""

    def __init__(
        self,
        data: List[Any],
        transform: Optional[Callable] = None,
        target_transform: Optional[Callable] = None,
    ) -> None:
        """Initialize the list dataset.

        Args:
            data: List of samples.
            transform: Transform to apply to input features.
            target_transform: Transform to apply to targets.
        """
        super().__init__(
            DatasetConfig(), transform=transform, target_transform=target_transform
        )
        self._data = data

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int) -> Any:
        sample = self._data[index]
        if self.transform is not None:
            sample = self.transform(sample)
        return sample

    def __setitem__(self, index: int, value: Any) -> None:
        self._data[index] = value

    def append(self, item: Any) -> None:
        """Append a sample to the dataset.

        Args:
            item: Sample to append.
        """
        self._data.append(item)

    def extend(self, items: List[Any]) -> None:
        """Extend the dataset with a list of samples.

        Args:
            items: List of samples to add.
        """
        self._data.extend(items)


class DictDataset(Dataset):
    """Dataset created from a dictionary of column arrays."""

    def __init__(
        self,
        data: Dict[str, List[Any]],
        transform: Optional[Callable] = None,
    ) -> None:
        """Initialize the dict dataset.

        Args:
            data: Dictionary mapping column names to lists of values.
            transform: Optional transform to apply.

        Raises:
            ValueError: If the column lists have different lengths.
        """
        super().__init__(DatasetConfig(), transform=transform)
        self._data = data

        lengths = [len(v) for v in data.values()]
        if len(set(lengths)) > 1:
            raise ValueError(
                f"All columns must have the same length, got lengths: {lengths}"
            )
        self._length = lengths[0] if lengths else 0
        self._keys = list(data.keys())

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, index: int) -> Dict[str, Any]:
        sample = {key: self._data[key][index] for key in self._keys}
        if self.transform is not None:
            sample = self.transform(sample)
        return sample

    @property
    def columns(self) -> List[str]:
        """Get the column names."""
        return self._keys


class Subset(Dataset):
    """A subset of a dataset at specified indices."""

    def __init__(
        self,
        dataset: Dataset,
        indices: List[int],
    ) -> None:
        """Initialize the subset.

        Args:
            dataset: The original dataset.
            indices: Indices to include in the subset.
        """
        super().__init__(dataset.config)
        self._dataset = dataset
        self._indices = indices

    def __len__(self) -> int:
        return len(self._indices)

    def __getitem__(self, index: int) -> Any:
        return self._dataset[self._indices[index]]

    @property
    def dataset(self) -> Dataset:
        """Get the original dataset."""
        return self._dataset

    @property
    def indices(self) -> List[int]:
        """Get the indices of the subset."""
        return self._indices


class ConcatDataset(Dataset):
    """Dataset that concatenates multiple datasets."""

    def __init__(self, datasets: List[Dataset]) -> None:
        """Initialize the concatenated dataset.

        Args:
            datasets: List of datasets to concatenate.

        Raises:
            ValueError: If the datasets list is empty.
        """
        if not datasets:
            raise ValueError("At least one dataset is required.")
        super().__init__(datasets[0].config)
        self._datasets = datasets
        self._cumulative_sizes: List[int] = []
        total = 0
        for ds in datasets:
            total += len(ds)
            self._cumulative_sizes.append(total)

    def __len__(self) -> int:
        return self._cumulative_sizes[-1] if self._cumulative_sizes else 0

    def __getitem__(self, index: int) -> Any:
        if index < 0:
            index = len(self) + index
        dataset_idx = 0
        while index >= self._cumulative_sizes[dataset_idx]:
            dataset_idx += 1
        offset = self._cumulative_sizes[dataset_idx - 1] if dataset_idx > 0 else 0
        return self._datasets[dataset_idx][index - offset]

    @property
    def datasets(self) -> List[Dataset]:
        """Get the list of datasets."""
        return self._datasets

    @property
    def cumulative_sizes(self) -> List[int]:
        """Get the cumulative sizes."""
        return self._cumulative_sizes


class MappedDataset(Dataset):
    """Dataset that applies a function to each sample."""

    def __init__(
        self,
        dataset: Dataset,
        function: Callable[[Any], Any],
        with_indices: bool = False,
    ) -> None:
        """Initialize the mapped dataset.

        Args:
            dataset: The original dataset.
            function: The function to apply.
            with_indices: If True, the function receives (index, sample).
        """
        super().__init__(dataset.config)
        self._dataset = dataset
        self._function = function
        self._with_indices = with_indices

    def __len__(self) -> int:
        return len(self._dataset)

    def __getitem__(self, index: int) -> Any:
        sample = self._dataset[index]
        if self._with_indices:
            return self._function(index, sample)
        return self._function(sample)


class FilteredDataset(Dataset):
    """Dataset that filters samples based on a predicate."""

    def __init__(
        self,
        dataset: Dataset,
        predicate: Callable[[Any], bool],
    ) -> None:
        """Initialize the filtered dataset.

        Args:
            dataset: The original dataset.
            predicate: A function that takes a sample and returns True/False.
        """
        super().__init__(dataset.config)
        self._dataset = dataset
        self._indices = [
            i for i in range(len(dataset)) if predicate(dataset[i])
        ]

    def __len__(self) -> int:
        return len(self._indices)

    def __getitem__(self, index: int) -> Any:
        return self._dataset[self._indices[index]]


class BatchedDataset(Dataset):
    """Dataset that groups samples into fixed-size batches."""

    def __init__(
        self,
        dataset: Dataset,
        batch_size: int,
        drop_last: bool = False,
    ) -> None:
        """Initialize the batched dataset.

        Args:
            dataset: The original dataset.
            batch_size: Number of samples per batch.
            drop_last: If True, drop the last incomplete batch.
        """
        super().__init__(dataset.config)
        self._dataset = dataset
        self._batch_size = batch_size
        self._drop_last = drop_last

        total = len(dataset)
        self._num_batches = (
            total // batch_size if drop_last else math.ceil(total / batch_size)
        )

    def __len__(self) -> int:
        return self._num_batches

    def __getitem__(self, index: int) -> List[Any]:
        start = index * self._batch_size
        end = min(start + self._batch_size, len(self._dataset))
        return [self._dataset[i] for i in range(start, end)]


class JsonDataset(Dataset):
    """Dataset loaded from a JSON file.

    Supports both JSON arrays and JSONL (one JSON object per line).
    """

    def __init__(
        self,
        path: str,
        key: Optional[str] = None,
        transform: Optional[Callable] = None,
        max_samples: Optional[int] = None,
    ) -> None:
        """Initialize the JSON dataset.

        Args:
            path: Path to the JSON file.
            key: If the JSON is a dict, extract samples from this key.
            transform: Optional transform to apply.
            max_samples: Maximum number of samples to load.

        Raises:
            DatasetFormatError: If the JSON file is malformed.
        """
        super().__init__(
            DatasetConfig(path=path, format="json", max_samples=max_samples),
            transform=transform,
        )
        self._load_json(path, key, max_samples)

    def _load_json(self, path: str, key: Optional[str], max_samples: Optional[int]) -> None:
        """Load data from a JSON file.

        Args:
            path: Path to the JSON file.
            key: Key to extract samples from.
            max_samples: Maximum number of samples to load.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise DatasetFormatError(f"Invalid JSON file: {path}. Error: {e}")

        if isinstance(data, dict) and key is not None:
            data = data.get(key, data)
        elif isinstance(data, dict) and key is None:
            # Try common keys
            for possible_key in ["data", "samples", "instances", "items", "examples"]:
                if possible_key in data:
                    data = data[possible_key]
                    logger.info(f"Auto-detected data key: '{possible_key}'")
                    break

        if not isinstance(data, list):
            raise DatasetFormatError(
                f"JSON data must be a list or a dict with a list value. "
                f"Got type: {type(data).__name__}"
            )

        self._data = data[:max_samples] if max_samples is not None else data
        logger.info(f"Loaded {len(self._data)} samples from {path}")

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int) -> Any:
        sample = self._data[index]
        if self.transform is not None:
            sample = self.transform(sample)
        return sample


class JsonlDataset(Dataset):
    """Dataset loaded from a JSONL file (one JSON object per line)."""

    def __init__(
        self,
        path: str,
        transform: Optional[Callable] = None,
        max_samples: Optional[int] = None,
    ) -> None:
        """Initialize the JSONL dataset.

        Args:
            path: Path to the JSONL file.
            transform: Optional transform to apply.
            max_samples: Maximum number of samples to load.

        Raises:
            DatasetFormatError: If the file is malformed.
        """
        super().__init__(
            DatasetConfig(path=path, format="jsonl", max_samples=max_samples),
            transform=transform,
        )
        self._load_jsonl(path, max_samples)

    def _load_jsonl(self, path: str, max_samples: Optional[int]) -> None:
        """Load data from a JSONL file.

        Args:
            path: Path to the JSONL file.
            max_samples: Maximum number of samples to load.
        """
        self._data = []
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    self._data.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise DatasetFormatError(
                        f"Invalid JSON on line {i + 1} in {path}: {e}"
                    )
                if max_samples is not None and len(self._data) >= max_samples:
                    break

        logger.info(f"Loaded {len(self._data)} samples from {path}")

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int) -> Any:
        sample = self._data[index]
        if self.transform is not None:
            sample = self.transform(sample)
        return sample


class CsvDataset(Dataset):
    """Dataset loaded from a CSV file."""

    def __init__(
        self,
        path: str,
        delimiter: str = ",",
        has_header: bool = True,
        columns: Optional[List[str]] = None,
        label_column: Optional[str] = None,
        transform: Optional[Callable] = None,
        max_samples: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> None:
        """Initialize the CSV dataset.

        Args:
            path: Path to the CSV file.
            delimiter: Field delimiter.
            has_header: Whether the CSV has a header row.
            columns: Column names (required if no header).
            label_column: Name of the label column.
            transform: Optional transform to apply.
            max_samples: Maximum number of samples to load.
            encoding: File encoding.
        """
        super().__init__(
            DatasetConfig(path=path, format="csv", max_samples=max_samples),
            transform=transform,
        )
        self._delimiter = delimiter
        self._has_header = has_header
        self._label_column = label_column
        self._load_csv(path, columns, max_samples, encoding)

    def _load_csv(
        self,
        path: str,
        columns: Optional[List[str]],
        max_samples: Optional[int],
        encoding: str,
    ) -> None:
        """Load data from a CSV file.

        Args:
            path: Path to the CSV file.
            columns: Column names.
            max_samples: Maximum number of samples to load.
            encoding: File encoding.
        """
        self._data = []
        self._fieldnames: List[str] = []

        with open(path, "r", encoding=encoding) as f:
            reader = csv.reader(f, delimiter=self._delimiter)

            if self._has_header:
                header = next(reader)
                self._fieldnames = header
            elif columns is not None:
                self._fieldnames = columns
            else:
                raise DatasetFormatError(
                    "CSV file has no header and no columns specified."
                )

            for i, row in enumerate(reader):
                if len(row) != len(self._fieldnames):
                    logger.warning(
                        f"Skipping row {i + 1}: expected {len(self._fieldnames)} "
                        f"columns, got {len(row)}"
                    )
                    continue

                sample = {
                    name: self._parse_value(value)
                    for name, value in zip(self._fieldnames, row)
                }

                if self._label_column and self._label_column in sample:
                    sample["label"] = sample[self._label_column]

                self._data.append(sample)

                if max_samples is not None and len(self._data) >= max_samples:
                    break

        logger.info(f"Loaded {len(self._data)} samples from {path}")

    @staticmethod
    def _parse_value(value: str) -> Any:
        """Parse a CSV string value to the appropriate type.

        Args:
            value: String value to parse.

        Returns:
            Parsed value (int, float, or str).
        """
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int) -> Any:
        sample = self._data[index].copy()
        if self.transform is not None:
            sample = self.transform(sample)
        return sample

    @property
    def fieldnames(self) -> List[str]:
        """Get the field names (columns) of the CSV."""
        return self._fieldnames


class ParquetDataset(Dataset):
    """Dataset loaded from a Parquet file."""

    def __init__(
        self,
        path: str,
        columns: Optional[List[str]] = None,
        transform: Optional[Callable] = None,
        max_samples: Optional[int] = None,
    ) -> None:
        """Initialize the Parquet dataset.

        Args:
            path: Path to the Parquet file.
            columns: Columns to load (None for all).
            transform: Optional transform to apply.
            max_samples: Maximum number of samples to load.

        Raises:
            ImportError: If pyarrow or pandas is not installed.
        """
        super().__init__(
            DatasetConfig(path=path, format="parquet", max_samples=max_samples),
            transform=transform,
        )
        self._load_parquet(path, columns, max_samples)

    def _load_parquet(
        self,
        path: str,
        columns: Optional[List[str]],
        max_samples: Optional[int],
    ) -> None:
        """Load data from a Parquet file.

        Args:
            path: Path to the Parquet file.
            columns: Columns to load.
            max_samples: Maximum number of samples to load.
        """
        try:
            import pyarrow.parquet as pq
        except ImportError:
            raise ImportError(
                "pyarrow is required for Parquet dataset support. "
                "Install with: pip install pyarrow"
            )

        try:
            table = pq.read_table(path, columns=columns)
        except Exception as e:
            raise DatasetFormatError(f"Failed to read Parquet file {path}: {e}")

        # Convert to list of dicts
        self._data = []
        num_rows = len(table)
        num_cols = len(table.column_names)

        for i in range(num_rows):
            if max_samples is not None and len(self._data) >= max_samples:
                break
            sample = {
                col: table.column(col)[i].as_py()
                for col in table.column_names
            }
            self._data.append(sample)

        logger.info(f"Loaded {len(self._data)} samples from {path} "
                    f"({num_rows} total rows, {num_cols} columns)")

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int) -> Any:
        sample = self._data[index]
        if self.transform is not None:
            sample = self.transform(sample)
        return sample


class HuggingFaceDataset(Dataset):
    """Dataset loaded from HuggingFace Datasets."""

    def __init__(
        self,
        name: str,
        split: str = "train",
        subset: Optional[str] = None,
        transform: Optional[Callable] = None,
        max_samples: Optional[int] = None,
        cache_dir: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the HuggingFace dataset.

        Args:
            name: Dataset name on HuggingFace Hub.
            split: Dataset split to load.
            subset: Optional subset/configuration name.
            transform: Optional transform to apply.
            max_samples: Maximum number of samples to load.
            cache_dir: Cache directory for downloaded datasets.
            **kwargs: Additional arguments passed to load_dataset.

        Raises:
            ImportError: If datasets is not installed.
        """
        config = DatasetConfig(
            path=name,
            format="huggingface",
            split=split,
            max_samples=max_samples,
            cache_dir=cache_dir,
        )
        super().__init__(config, transform=transform)

        self._name = name
        self._split = split
        self._subset = subset
        self._load_huggingface(max_samples, cache_dir, **kwargs)

    def _load_huggingface(
        self, max_samples: Optional[int], cache_dir: Optional[str], **kwargs: Any
    ) -> None:
        """Load data from HuggingFace datasets.

        Args:
            max_samples: Maximum number of samples to load.
            cache_dir: Cache directory.
            **kwargs: Additional arguments.
        """
        try:
            from datasets import load_dataset
        except ImportError:
            raise ImportError(
                "datasets library is required for HuggingFace dataset support. "
                "Install with: pip install datasets"
            )

        try:
            dataset_kwargs: Dict[str, Any] = {
                "cache_dir": cache_dir,
                **kwargs,
            }
            if self._subset is not None:
                dataset_kwargs["name"] = self._subset

            hf_dataset = load_dataset(self._name, split=self._split, **dataset_kwargs)

            if max_samples is not None:
                hf_dataset = hf_dataset.select(range(min(max_samples, len(hf_dataset))))

            self._hf_dataset = hf_dataset
            self._data = [dict(sample) for sample in hf_dataset]

        except Exception as e:
            raise DatasetError(f"Failed to load HuggingFace dataset '{self._name}': {e}")

        logger.info(f"Loaded {len(self._data)} samples from HuggingFace dataset "
                    f"'{self._name}' (split: {self._split})")

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int) -> Any:
        sample = self._data[index]
        if self.transform is not None:
            sample = self.transform(sample)
        return sample

    @property
    def features(self) -> Optional[List[str]]:
        """Get the feature names of the dataset."""
        if hasattr(self, "_hf_dataset") and self._hf_dataset is not None:
            return list(self._hf_dataset.features.keys())
        return list(self._data[0].keys()) if self._data else None

    @property
    def huggingface_dataset(self) -> Any:
        """Get the underlying HuggingFace dataset object."""
        return self._hf_dataset


class TensorDataset(Dataset):
    """Dataset wrapping tensors.

    Each sample is a tuple of tensors at the same index across all tensors.
    """

    def __init__(self, *tensors: torch.Tensor) -> None:
        """Initialize the tensor dataset.

        Args:
            *tensors: Tensors to wrap. All must have the same size in the first dimension.

        Raises:
            ValueError: If tensors have mismatched sizes.
        """
        super().__init__(DatasetConfig())
        if not tensors:
            raise ValueError("At least one tensor is required.")

        self._tensors = tensors
        sizes = [t.size(0) for t in tensors]
        if len(set(sizes)) > 1:
            raise ValueError(
                f"All tensors must have the same size in dimension 0, "
                f"got sizes: {sizes}"
            )

    def __len__(self) -> int:
        return self._tensors[0].size(0)

    def __getitem__(self, index: int) -> Tuple[torch.Tensor, ...]:
        return tuple(tensor[index] for tensor in self._tensors)

    @property
    def tensors(self) -> Tuple[torch.Tensor, ...]:
        """Get the underlying tensors."""
        return self._tensors


class RandomDataset(Dataset):
    """Dataset that generates random data for testing purposes."""

    def __init__(
        self,
        length: int,
        input_shape: Tuple[int, ...] = (3, 224, 224),
        num_classes: int = 10,
        input_dtype: torch.dtype = torch.float32,
        label_dtype: torch.dtype = torch.long,
        seed: int = 42,
    ) -> None:
        """Initialize the random dataset.

        Args:
            length: Number of samples.
            input_shape: Shape of the input tensors.
            num_classes: Number of classes for labels.
            input_dtype: Data type of inputs.
            label_dtype: Data type of labels.
            seed: Random seed.
        """
        super().__init__(DatasetConfig(seed=seed))
        self._length = length
        self._input_shape = input_shape
        self._num_classes = num_classes
        self._input_dtype = input_dtype
        self._label_dtype = label_dtype
        self._rng = torch.Generator().manual_seed(seed)

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, index: int) -> Tuple[torch.Tensor, torch.Tensor]:
        x = torch.randn(*self._input_shape, generator=self._rng, dtype=self._input_dtype)
        y = torch.randint(
            0, self._num_classes, (1,), generator=self._rng, dtype=self._label_dtype
        ).squeeze()
        return x, y


class IterableDataset(Dataset):
    """Dataset that yields samples from an iterable.

    This is useful for streaming data or data that cannot fit in memory.
    """

    def __init__(
        self,
        iterable: Any,
        approximate_length: Optional[int] = None,
        transform: Optional[Callable] = None,
    ) -> None:
        """Initialize the iterable dataset.

        Args:
            iterable: An iterable that yields samples.
            approximate_length: Approximate length (for progress reporting).
            transform: Optional transform to apply.
        """
        super().__init__(DatasetConfig(), transform=transform)
        self._iterable = iterable
        self._approx_length = approximate_length

    def __len__(self) -> int:
        if self._approx_length is not None:
            return self._approx_length
        raise TypeError("IterableDataset has no defined length.")

    def __getitem__(self, index: int) -> Any:
        # IterableDatasets don't support random access
        raise TypeError("IterableDataset does not support indexing. Use iteration instead.")

    def __iter__(self) -> Iterator[Any]:
        for sample in self._iterable:
            if self.transform is not None:
                sample = self.transform(sample)
            yield sample


class DataLoader:
    """DataLoader for batching and iterating over datasets.

    This is a lightweight alternative to PyTorch's DataLoader with additional
    features like automatic batching, shuffling, and collation.
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

        # Sampler logic
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
            self._collate_fn = self._default_collate

        # Build torch DataLoader
        self._torch_dataloader: Optional[torch.utils.data.DataLoader] = None
        self._use_torch = num_workers > 0 or pin_memory

        if self._use_torch:
            self._build_torch_dataloader()

    def _build_torch_dataloader(self) -> None:
        """Build a PyTorch DataLoader for multi-worker loading."""
        # Convert our Dataset to a torch Dataset
        torch_dataset = _TorchDatasetAdapter(self._dataset)

        self._torch_dataloader = torch.utils.data.DataLoader(
            torch_dataset,
            batch_size=self._batch_size,
            shuffle=self._shuffle if self._sampler is None else False,
            sampler=self._sampler,
            num_workers=self._num_workers,
            collate_fn=self._collate_fn,
            pin_memory=self._pin_memory,
            drop_last=self._drop_last,
            timeout=self._timeout,
            worker_init_fn=self._worker_init_fn,
            prefetch_factor=self._prefetch_factor if self._num_workers > 0 else None,
            persistent_workers=self._persistent_workers,
        )

    @staticmethod
    def _default_collate(batch: List[Any]) -> Any:
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

        elif isinstance(elem, (int, float)):
            return torch.tensor(batch)

        elif isinstance(elem, str):
            return batch

        elif isinstance(elem, np.ndarray):
            return torch.from_numpy(np.stack(batch, axis=0))

        elif isinstance(elem, dict):
            return {
                key: DataLoader._default_collate([d[key] for d in batch])
                for key in elem
            }

        elif isinstance(elem, (list, tuple)):
            transposed = list(zip(*batch))
            return [DataLoader._default_collate(items) for items in transposed]

        elif elem is None:
            return None

        else:
            try:
                return torch.tensor(batch)
            except (TypeError, ValueError):
                return batch

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
        if self._use_torch and self._torch_dataloader is not None:
            return len(self._torch_dataloader)
        total = len(self._dataset)
        if self._drop_last:
            return total // self._batch_size
        return (total + self._batch_size - 1) // self._batch_size

    def __iter__(self) -> Iterator[Any]:
        """Iterate over batches."""
        if self._use_torch and self._torch_dataloader is not None:
            yield from self._torch_dataloader
        else:
            yield from self._iter_batches()

    def _iter_batches(self) -> Iterator[Any]:
        """Generate batches without multiprocessing.

        Yields:
            Collated batches.
        """
        indices = list(range(len(self._dataset)))

        if self._shuffle:
            self._rng.shuffle(indices)

        if self._sampler is not None:
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


class _TorchDatasetAdapter(torch.utils.data.Dataset):
    """Adapter to wrap our Dataset for use with PyTorch's DataLoader."""

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