"""Benchmark result templates for AinosOS model benchmarking.

Provides dataclass definitions, template classes, and collection management
for storing and manipulating benchmark results.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BenchmarkType(str, Enum):
    """Types of benchmarks that can be run."""

    LATENCY = "latency"
    THROUGHPUT = "throughput"
    MEMORY = "memory"
    COMPREHENSIVE = "comprehensive"
    QUANTIZATION = "quantization"
    INFERENCE = "inference"
    TRAINING = "training"
    TEXT_GENERATION = "text_generation"
    EMBEDDING = "embedding"
    VISION = "vision"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"
    CUSTOM = "custom"


class HardwareType(str, Enum):
    """Hardware platforms for benchmark execution."""

    CPU = "cpu"
    CUDA = "cuda"
    ROCM = "rocm"
    METAL = "metal"
    VULKAN = "vulkan"
    OPENCL = "opencl"
    SYCL = "sycl"
    COREML = "coreml"
    DIRECTML = "directml"
    TENSORRT = "tensorrt"
    ONNX = "onnx"
    WEBGPU = "webgpu"
    WEBNN = "webnn"
    TPU = "tpu"
    NPU = "npu"
    FPGA = "fpga"
    CUSTOM = "custom"


class PrecisionType(str, Enum):
    """Precision/quantization types for model weights."""

    FP32 = "fp32"
    FP16 = "fp16"
    BF16 = "bf16"
    FP8 = "fp8"
    FP4 = "fp4"
    INT8 = "int8"
    INT4 = "int4"
    INT3 = "int3"
    INT2 = "int2"
    NF4 = "nf4"
    NF3 = "nf3"
    MIXED = "mixed"
    FLOAT32 = "float32"
    FLOAT16 = "float16"
    BRAIN_FLOAT16 = "bfloat16"
    TENSOR_FLOAT32 = "tensorfloat32"
    TF32 = "tf32"
    SPARSE = "sparse"
    CUSTOM = "custom"


class ResultStatus(str, Enum):
    """Status of a benchmark result."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ERROR = "error"
    WARNING = "warning"
    INCOMPLETE = "incomplete"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkMetadata:
    """Metadata describing a benchmark run configuration."""

    model_name: str = ""
    model_version: str = ""
    model_family: str = ""
    benchmark_type: BenchmarkType = BenchmarkType.LATENCY
    hardware_type: HardwareType = HardwareType.CPU
    precision: PrecisionType = PrecisionType.FP32
    quantization: str = ""
    framework: str = ""
    framework_version: str = ""
    batch_size: int = 1
    context_length: int = 2048
    prompt_length: int = 512
    num_tokens: int = 128
    num_runs: int = 5
    warmup_runs: int = 2
    date: str = ""
    time: str = ""
    duration_seconds: float = 0.0
    config: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    runner_version: str = ""
    commit_hash: str = ""
    environment: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.date:
            self.date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not self.time:
            self.time = datetime.now(timezone.utc).strftime("%H:%M:%S")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["benchmark_type"] = self.benchmark_type.value
        d["hardware_type"] = self.hardware_type.value
        d["precision"] = self.precision.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkMetadata:
        data = dict(data)
        if "benchmark_type" in data and isinstance(data["benchmark_type"], str):
            data["benchmark_type"] = BenchmarkType(data["benchmark_type"])
        if "hardware_type" in data and isinstance(data["hardware_type"], str):
            data["hardware_type"] = HardwareType(data["hardware_type"])
        if "precision" in data and isinstance(data["precision"], str):
            data["precision"] = PrecisionType(data["precision"])
        return cls(**data)


@dataclass
class LatencyResult:
    """Latency metrics for a benchmark run."""

    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    mean_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    std_dev_ms: float = 0.0
    prompt_processing_ms: float = 0.0
    time_to_first_token_ms: float = 0.0
    inter_token_latency_ms: float = 0.0
    decode_latency_ms: float = 0.0
    prefill_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    raw_timings_ms: list[float] = field(default_factory=list)
    unit: str = "ms"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LatencyResult:
        return cls(**data)


@dataclass
class ThroughputResult:
    """Throughput metrics for a benchmark run."""

    tokens_per_second: float = 0.0
    tokens_per_second_per_device: float = 0.0
    requests_per_second: float = 0.0
    batch_size: int = 1
    context_length: int = 2048
    prompt_tokens_processed: int = 0
    generated_tokens: int = 0
    total_tokens: int = 0
    total_time_seconds: float = 0.0
    samples_per_second: float = 0.0
    flops: float = 0.0
    flops_utilization: float = 0.0
    memory_bandwidth_gbps: float = 0.0
    num_concurrent_requests: int = 1
    unit: str = "tokens/s"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThroughputResult:
        return cls(**data)


@dataclass
class MemoryResult:
    """Memory usage metrics for a benchmark run."""

    peak_ram_mb: float = 0.0
    steady_ram_mb: float = 0.0
    peak_vram_mb: float = 0.0
    steady_vram_mb: float = 0.0
    swap_usage_mb: float = 0.0
    memory_allocated_mb: float = 0.0
    memory_reserved_mb: float = 0.0
    memory_fragmentation_pct: float = 0.0
    cache_usage_mb: float = 0.0
    activation_memory_mb: float = 0.0
    kv_cache_mb: float = 0.0
    weights_memory_mb: float = 0.0
    peak_memory_pct: float = 0.0
    average_memory_pct: float = 0.0
    memory_efficiency_pct: float = 0.0
    unit: str = "MB"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryResult:
        return cls(**data)


@dataclass
class BenchmarkResult:
    """Complete benchmark result combining metadata and performance metrics."""

    metadata: BenchmarkMetadata = field(default_factory=BenchmarkMetadata)
    latency: LatencyResult = field(default_factory=LatencyResult)
    throughput: ThroughputResult = field(default_factory=ThroughputResult)
    memory: MemoryResult = field(default_factory=MemoryResult)
    result_id: str = ""
    status: ResultStatus = ResultStatus.COMPLETED
    created_at: str = ""
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    additional_metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = generate_result_id()
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if isinstance(self.status, str):
            self.status = ResultStatus(self.status)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["metadata"]["benchmark_type"] = self.metadata.benchmark_type.value
        d["metadata"]["hardware_type"] = self.metadata.hardware_type.value
        d["metadata"]["precision"] = self.metadata.precision.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkResult:
        data = dict(data)
        if "metadata" in data and isinstance(data["metadata"], dict):
            data["metadata"] = BenchmarkMetadata.from_dict(data["metadata"])
        if "latency" in data and isinstance(data["latency"], dict):
            data["latency"] = LatencyResult.from_dict(data["latency"])
        if "throughput" in data and isinstance(data["throughput"], dict):
            data["throughput"] = ThroughputResult.from_dict(data["throughput"])
        if "memory" in data and isinstance(data["memory"], dict):
            data["memory"] = MemoryResult.from_dict(data["memory"])
        if "status" in data and isinstance(data["status"], str):
            data["status"] = ResultStatus(data["status"])
        return cls(**data)


@dataclass
class ComparisonResult:
    """Result of comparing multiple benchmark results."""

    model_name: str = ""
    results: list[BenchmarkResult] = field(default_factory=list)
    metric: str = "tokens_per_second"
    baseline_index: int = 0
    speedups: dict[str, float] = field(default_factory=dict)
    memory_reductions: dict[str, float] = field(default_factory=dict)
    rankings: dict[str, list[int]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["results"] = [r.to_dict() for r in self.results]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComparisonResult:
        data = dict(data)
        if "results" in data:
            data["results"] = [
                BenchmarkResult.from_dict(r) if isinstance(r, dict) else r
                for r in data["results"]
            ]
        return cls(**data)


@dataclass
class ResultSummary:
    """Aggregated summary of multiple benchmark results."""

    model_name: str = ""
    benchmark_type: BenchmarkType = BenchmarkType.LATENCY
    hardware_type: HardwareType = HardwareType.CPU
    precision: PrecisionType = PrecisionType.FP32
    num_results: int = 0
    mean_latency_ms: float = 0.0
    median_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    mean_throughput_tps: float = 0.0
    peak_throughput_tps: float = 0.0
    mean_peak_memory_mb: float = 0.0
    mean_steady_memory_mb: float = 0.0
    mean_score: float = 0.0
    min_score: float = 0.0
    max_score: float = 0.0
    std_dev_score: float = 0.0
    results: list[BenchmarkResult] = field(default_factory=list)
    date_range: tuple[str, str] = ("", "")
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["benchmark_type"] = self.benchmark_type.value
        d["hardware_type"] = self.hardware_type.value
        d["precision"] = self.precision.value
        d["results"] = [r.to_dict() for r in self.results]
        d["date_range"] = list(self.date_range)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResultSummary:
        data = dict(data)
        if "benchmark_type" in data and isinstance(data["benchmark_type"], str):
            data["benchmark_type"] = BenchmarkType(data["benchmark_type"])
        if "hardware_type" in data and isinstance(data["hardware_type"], str):
            data["hardware_type"] = HardwareType(data["hardware_type"])
        if "precision" in data and isinstance(data["precision"], str):
            data["precision"] = PrecisionType(data["precision"])
        if "results" in data:
            data["results"] = [
                BenchmarkResult.from_dict(r) if isinstance(r, dict) else r
                for r in data["results"]
            ]
        if "date_range" in data and isinstance(data["date_range"], list):
            data["date_range"] = tuple(data["date_range"])
        return cls(**data)


# ---------------------------------------------------------------------------
# BenchmarkResultTemplate
# ---------------------------------------------------------------------------

class BenchmarkResultTemplate:
    """Template for creating and managing benchmark results.

    Provides factory methods, validation, serialization, and merging
    of benchmark results.
    """

    def __init__(
        self,
        metadata: Optional[BenchmarkMetadata] = None,
        latency: Optional[LatencyResult] = None,
        throughput: Optional[ThroughputResult] = None,
        memory: Optional[MemoryResult] = None,
    ) -> None:
        self.metadata = metadata or BenchmarkMetadata()
        self.latency = latency or LatencyResult()
        self.throughput = throughput or ThroughputResult()
        self.memory = memory or MemoryResult()

    @classmethod
    def create_empty(cls) -> BenchmarkResultTemplate:
        """Create an empty template ready for filling in values."""
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkResultTemplate:
        """Load a template from a dictionary."""
        return cls(
            metadata=BenchmarkMetadata.from_dict(data.get("metadata", {})),
            latency=LatencyResult.from_dict(data.get("latency", {})),
            throughput=ThroughputResult.from_dict(data.get("throughput", {})),
            memory=MemoryResult.from_dict(data.get("memory", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the template to a dictionary."""
        return {
            "metadata": self.metadata.to_dict(),
            "latency": self.latency.to_dict(),
            "throughput": self.throughput.to_dict(),
            "memory": self.memory.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the template to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def validate(self) -> list[str]:
        """Validate all fields in the template.

        Returns:
            A list of validation error messages (empty if valid).
        """
        errors: list[str] = []

        if not self.metadata.model_name:
            errors.append("model_name is required in metadata")

        if self.latency.mean_ms < 0:
            errors.append("latency mean_ms cannot be negative")

        if self.latency.p50_ms < 0:
            errors.append("latency p50_ms cannot be negative")

        if self.latency.p95_ms < 0:
            errors.append("latency p95_ms cannot be negative")

        if self.latency.p99_ms < 0:
            errors.append("latency p99_ms cannot be negative")

        if self.latency.min_ms < 0:
            errors.append("latency min_ms cannot be negative")

        if self.latency.max_ms < 0:
            errors.append("latency max_ms cannot be negative")

        if self.latency.min_ms > self.latency.max_ms and self.latency.max_ms > 0:
            errors.append("latency min_ms should not exceed max_ms")

        if self.throughput.tokens_per_second < 0:
            errors.append("throughput tokens_per_second cannot be negative")

        if self.throughput.batch_size < 1:
            errors.append("throughput batch_size must be at least 1")

        if self.memory.peak_ram_mb < 0:
            errors.append("memory peak_ram_mb cannot be negative")

        if self.memory.peak_vram_mb < 0:
            errors.append("memory peak_vram_mb cannot be negative")

        if self.metadata.batch_size < 1:
            errors.append("metadata batch_size must be at least 1")

        if self.metadata.num_runs < 1:
            errors.append("metadata num_runs must be at least 1")

        return errors

    def merge(self, other: BenchmarkResultTemplate) -> BenchmarkResultTemplate:
        """Merge another template into this one, overwriting non-default values.

        Args:
            other: The template to merge from.

        Returns:
            Self for chaining.
        """
        merged = BenchmarkResultTemplate()

        # Merge metadata
        merged.metadata = BenchmarkMetadata(
            **{
                **self.metadata.to_dict(),
                **{k: v for k, v in other.metadata.to_dict().items()
                   if v != BenchmarkMetadata().to_dict().get(k)},
            }
        )

        # Merge latency
        default_latency = LatencyResult()
        merged_latency = {}
        merged_latency.update(self.latency.to_dict())
        for k, v in other.latency.to_dict().items():
            if v != default_latency.to_dict().get(k):
                merged_latency[k] = v
        merged.latency = LatencyResult(**merged_latency)

        # Merge throughput
        default_throughput = ThroughputResult()
        merged_throughput = {}
        merged_throughput.update(self.throughput.to_dict())
        for k, v in other.throughput.to_dict().items():
            if v != default_throughput.to_dict().get(k):
                merged_throughput[k] = v
        merged.throughput = ThroughputResult(**merged_throughput)

        # Merge memory
        default_memory = MemoryResult()
        merged_memory = {}
        merged_memory.update(self.memory.to_dict())
        for k, v in other.memory.to_dict().items():
            if v != default_memory.to_dict().get(k):
                merged_memory[k] = v
        merged.memory = MemoryResult(**merged_memory)

        return merged

    def build(self) -> BenchmarkResult:
        """Build a BenchmarkResult from this template."""
        return BenchmarkResult(
            metadata=self.metadata,
            latency=self.latency,
            throughput=self.throughput,
            memory=self.memory,
        )


# ---------------------------------------------------------------------------
# ResultCollection
# ---------------------------------------------------------------------------

class ResultCollection:
    """A collection of BenchmarkResult objects with filtering and aggregation."""

    def __init__(self, results: Optional[list[BenchmarkResult]] = None) -> None:
        self._results: dict[str, BenchmarkResult] = {}
        if results:
            for r in results:
                self._results[r.result_id] = r

    @property
    def results(self) -> list[BenchmarkResult]:
        """Get all results as a list."""
        return list(self._results.values())

    @property
    def count(self) -> int:
        """Get the number of results."""
        return len(self._results)

    @property
    def result_ids(self) -> list[str]:
        """Get all result IDs."""
        return list(self._results.keys())

    def add_result(self, result: BenchmarkResult) -> None:
        """Add a result to the collection."""
        self._results[result.result_id] = result

    def remove_result(self, result_id: str) -> Optional[BenchmarkResult]:
        """Remove a result by ID and return it, or None if not found."""
        return self._results.pop(result_id, None)

    def get_result(self, result_id: str) -> Optional[BenchmarkResult]:
        """Get a result by ID."""
        return self._results.get(result_id)

    def filter(
        self,
        model_name: Optional[str] = None,
        model_family: Optional[str] = None,
        benchmark_type: Optional[BenchmarkType] = None,
        hardware_type: Optional[HardwareType] = None,
        precision: Optional[PrecisionType] = None,
        status: Optional[ResultStatus] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        tags: Optional[list[str]] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
    ) -> ResultCollection:
        """Filter results by various criteria.

        Args:
            model_name: Filter by model name (substring match).
            model_family: Filter by model family.
            benchmark_type: Filter by benchmark type.
            hardware_type: Filter by hardware type.
            precision: Filter by precision type.
            status: Filter by result status.
            date_from: Filter by date >= this value (YYYY-MM-DD).
            date_to: Filter by date <= this value (YYYY-MM-DD).
            tags: Filter by tags (result must have all specified tags).
            min_score: Filter by score >= this value.
            max_score: Filter by score <= this value.

        Returns:
            A new ResultCollection with matching results.
        """
        filtered = list(self._results.values())

        if model_name:
            filtered = [
                r for r in filtered
                if model_name.lower() in r.metadata.model_name.lower()
            ]

        if model_family:
            filtered = [
                r for r in filtered
                if r.metadata.model_family.lower() == model_family.lower()
            ]

        if benchmark_type:
            filtered = [
                r for r in filtered
                if r.metadata.benchmark_type == benchmark_type
            ]

        if hardware_type:
            filtered = [
                r for r in filtered
                if r.metadata.hardware_type == hardware_type
            ]

        if precision:
            filtered = [
                r for r in filtered
                if r.metadata.precision == precision
            ]

        if status:
            filtered = [r for r in filtered if r.status == status]

        if date_from:
            filtered = [
                r for r in filtered
                if r.metadata.date >= date_from
            ]

        if date_to:
            filtered = [
                r for r in filtered
                if r.metadata.date <= date_to
            ]

        if tags:
            filtered = [
                r for r in filtered
                if all(tag in r.metadata.tags for tag in tags)
            ]

        if min_score is not None:
            filtered = [r for r in filtered if r.score >= min_score]

        if max_score is not None:
            filtered = [r for r in filtered if r.score <= max_score]

        return ResultCollection(filtered)

    def aggregate(self) -> ResultSummary:
        """Compute aggregate statistics across all results.

        Returns:
            A ResultSummary with aggregated data.
        """
        results = self.results
        if not results:
            return ResultSummary()

        latencies = [r.latency.mean_ms for r in results if r.latency.mean_ms > 0]
        throughputs = [r.throughput.tokens_per_second for r in results if r.throughput.tokens_per_second > 0]
        peak_mems = [r.memory.peak_ram_mb for r in results if r.memory.peak_ram_mb > 0]
        steady_mems = [r.memory.steady_ram_mb for r in results if r.memory.steady_ram_mb > 0]
        scores = [r.score for r in results if r.score > 0]

        import statistics as stats

        summary = ResultSummary(
            num_results=len(results),
            results=results,
        )

        if results:
            summary.model_name = results[0].metadata.model_name
            summary.benchmark_type = results[0].metadata.benchmark_type
            summary.hardware_type = results[0].metadata.hardware_type
            summary.precision = results[0].metadata.precision

        if latencies:
            summary.mean_latency_ms = stats.mean(latencies)
            summary.median_latency_ms = stats.median(latencies)
            summary.p95_latency_ms = sorted(latencies)[
                min(int(len(latencies) * 0.95), len(latencies) - 1)
            ]

        if throughputs:
            summary.mean_throughput_tps = stats.mean(throughputs)
            summary.peak_throughput_tps = max(throughputs)

        if peak_mems:
            summary.mean_peak_memory_mb = stats.mean(peak_mems)

        if steady_mems:
            summary.mean_steady_memory_mb = stats.mean(steady_mems)

        if scores:
            summary.mean_score = stats.mean(scores)
            summary.min_score = min(scores)
            summary.max_score = max(scores)
            summary.std_dev_score = stats.stdev(scores) if len(scores) > 1 else 0.0

        dates = [r.metadata.date for r in results if r.metadata.date]
        if dates:
            summary.date_range = (min(dates), max(dates))

        return summary

    def sort(
        self,
        key: str = "score",
        reverse: bool = True,
    ) -> ResultCollection:
        """Sort results by a given key.

        Args:
            key: Field to sort by. Supports dotted paths like
                 'latency.mean_ms', 'throughput.tokens_per_second',
                 'memory.peak_ram_mb', 'score', 'metadata.date'.
            reverse: Sort in descending order if True.

        Returns:
            A new sorted ResultCollection.
        """
        results = list(self._results.values())

        def _get_key(r: BenchmarkResult) -> Any:
            parts = key.split(".")
            obj: Any = r
            for part in parts:
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                elif isinstance(obj, dict):
                    obj = obj.get(part, 0)
                else:
                    return 0
            if isinstance(obj, Enum):
                return obj.value
            if isinstance(obj, str):
                return obj
            return obj if obj is not None else 0

        results.sort(key=_get_key, reverse=reverse)
        return ResultCollection(results)

    def to_dict_list(self) -> list[dict[str, Any]]:
        """Serialize all results to a list of dictionaries."""
        return [r.to_dict() for r in self.results]

    @classmethod
    def from_dict_list(cls, data: list[dict[str, Any]]) -> ResultCollection:
        """Load a collection from a list of dictionaries."""
        return cls([BenchmarkResult.from_dict(d) for d in data])

    def to_json(self, indent: int = 2) -> str:
        """Serialize the collection to a JSON string."""
        return json.dumps(self.to_dict_list(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> ResultCollection:
        """Load a collection from a JSON string."""
        return cls.from_dict_list(json.loads(json_str))

    def __len__(self) -> int:
        return self.count

    def __iter__(self):
        return iter(self.results)

    def __getitem__(self, index):
        if isinstance(index, str):
            result = self.get_result(index)
            if result is None:
                raise KeyError(f"Result not found: {index}")
            return result
        return self.results[index]

    def __repr__(self) -> str:
        return f"ResultCollection({self.count} results)"


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def generate_result_id() -> str:
    """Generate a unique result ID."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    return f"bm_{timestamp}_{unique_id}"


# ---------------------------------------------------------------------------
# Default templates for common scenarios
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATES: dict[str, BenchmarkResultTemplate] = {
    "standard_text_generation": BenchmarkResultTemplate(
        metadata=BenchmarkMetadata(
            benchmark_type=BenchmarkType.TEXT_GENERATION,
            context_length=2048,
            prompt_length=512,
            num_tokens=128,
            num_runs=5,
            warmup_runs=2,
        ),
    ),
    "low_latency": BenchmarkResultTemplate(
        metadata=BenchmarkMetadata(
            benchmark_type=BenchmarkType.LATENCY,
            context_length=1024,
            prompt_length=128,
            num_tokens=32,
            num_runs=10,
            warmup_runs=3,
        ),
    ),
    "high_throughput": BenchmarkResultTemplate(
        metadata=BenchmarkMetadata(
            benchmark_type=BenchmarkType.THROUGHPUT,
            batch_size=8,
            context_length=4096,
            prompt_length=1024,
            num_tokens=256,
            num_runs=3,
            warmup_runs=1,
        ),
    ),
    "memory_benchmark": BenchmarkResultTemplate(
        metadata=BenchmarkMetadata(
            benchmark_type=BenchmarkType.MEMORY,
            context_length=8192,
            prompt_length=1,
            num_tokens=1,
            num_runs=3,
            warmup_runs=1,
        ),
    ),
    "comprehensive": BenchmarkResultTemplate(
        metadata=BenchmarkMetadata(
            benchmark_type=BenchmarkType.COMPREHENSIVE,
            context_length=4096,
            prompt_length=512,
            num_tokens=128,
            num_runs=5,
            warmup_runs=2,
        ),
    ),
    "quantization_compare": BenchmarkResultTemplate(
        metadata=BenchmarkMetadata(
            benchmark_type=BenchmarkType.QUANTIZATION,
            context_length=2048,
            prompt_length=512,
            num_tokens=128,
            num_runs=5,
            warmup_runs=2,
        ),
    ),
}


def create_default_template(name: str = "standard") -> BenchmarkResultTemplate:
    """Get a default template by name.

    Args:
        name: Template name from DEFAULT_TEMPLATES.

    Returns:
        A copy of the default template.

    Raises:
        KeyError: If the template name is not found.
    """
    if name not in DEFAULT_TEMPLATES:
        raise KeyError(
            f"Unknown template: {name}. "
            f"Available: {list(DEFAULT_TEMPLATES.keys())}"
        )
    return DEFAULT_TEMPLATES[name]