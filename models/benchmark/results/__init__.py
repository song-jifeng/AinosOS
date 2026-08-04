"""AinosOS Model Benchmark Results System.

Provides templates, comparison tools, report generation, and storage
for model benchmark results.
"""

from .template import (
    BenchmarkType,
    HardwareType,
    PrecisionType,
    ResultStatus,
    BenchmarkMetadata,
    LatencyResult,
    ThroughputResult,
    MemoryResult,
    BenchmarkResult,
    ComparisonResult,
    ResultSummary,
    BenchmarkResultTemplate,
    ResultCollection,
    DEFAULT_TEMPLATES,
)
from .comparison import (
    ModelComparator,
    RegressionDetector,
    ResultFormatter,
    calculate_percentiles,
    calculate_confidence_interval,
    detect_outliers,
    normalize_scores,
)
from .report_generator import (
    ReportGenerator,
    ReportSection,
    ReportTemplate,
    BUILTIN_TEMPLATES,
)
from .storage import (
    ResultStorage,
    ResultCache,
    ResultArchive,
    generate_result_id,
    result_file_path,
    ensure_storage_dir,
    validate_result_file,
)

__all__ = [
    # Enums
    "BenchmarkType",
    "HardwareType",
    "PrecisionType",
    "ResultStatus",
    # Dataclasses
    "BenchmarkMetadata",
    "LatencyResult",
    "ThroughputResult",
    "MemoryResult",
    "BenchmarkResult",
    "ComparisonResult",
    "ResultSummary",
    # Template classes
    "BenchmarkResultTemplate",
    "ResultCollection",
    "DEFAULT_TEMPLATES",
    # Comparison
    "ModelComparator",
    "RegressionDetector",
    "ResultFormatter",
    "calculate_percentiles",
    "calculate_confidence_interval",
    "detect_outliers",
    "normalize_scores",
    # Report generation
    "ReportGenerator",
    "ReportSection",
    "ReportTemplate",
    "BUILTIN_TEMPLATES",
    # Storage
    "ResultStorage",
    "ResultCache",
    "ResultArchive",
    "generate_result_id",
    "result_file_path",
    "ensure_storage_dir",
    "validate_result_file",
]