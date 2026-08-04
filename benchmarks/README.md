# Ainos Performance Benchmark Suite

Comprehensive performance benchmarking framework for micro-benchmarks, kernel-level benchmarks, AI inference benchmarks, and SDK performance comparisons.

## Features

- **Micro-benchmarks**: Matrix multiplication, memory bandwidth, cache latency, vector operations, TCP throughput, JSON parsing
- **Kernel benchmarks**: Syscall latency, context switching, IPC throughput, memory allocation
- **AI benchmarks**: Inference latency/throughput, embedding speed, vector search latency, model loading
- **SDK benchmarks**: Multi-language SDK latency, throughput, and memory comparisons
- **Reporting**: HTML/JSON reports with charts, trend lines, and comparative analysis
- **Results storage**: SQLite-backed persistence with historical tracking
- **Configuration**: YAML-based benchmark parameters
- **Charts**: Performance trend charts, comparison bar charts, distribution plots

## Quick Start

```bash
# Install the package
pip install -e .

# Run all benchmarks
ainos-bench run all

# Run specific benchmark category
ainos-bench run micro
ainos-bench run kernel
ainos-bench run ai
ainos-bench run sdk

# Generate report
ainos-bench report --format html
ainos-bench report --format json
```

## Directory Structure

```
benchmarks/
├── __init__.py           # Package init, common types, errors
├── runner.py             # Benchmark runner and CLI
├── config.yaml           # Benchmark configuration
├── setup.py              # Package setup
├── pyproject.toml        # Project configuration
├── README.md             # This file
├── micro/                # Micro-benchmarks
│   ├── matrix_mul.py     # Matrix multiplication performance
│   ├── memory_bandwidth.py # Memory bandwidth measurement
│   ├── cache_latency.py  # Cache latency probing
│   ├── vector_ops.py     # Vector/SIMD operations
│   ├── tcp_throughput.py # TCP network throughput
│   └── json_parse.py     # JSON parsing performance
├── kernel/               # Kernel benchmarks
│   ├── syscall_latency.py # System call latency
│   ├── context_switch.py  # Context switching overhead
│   ├── ipc_throughput.py  # IPC throughput
│   └── memory_alloc.py    # Memory allocation performance
├── ai/                   # AI benchmarks
│   ├── inference_latency.py  # Model inference latency
│   ├── inference_throughput.py # Inference throughput
│   ├── embedding_speed.py    # Embedding generation speed
│   ├── search_latency.py     # Vector search latency
│   └── model_load.py         # Model loading time
├── sdk/                  # SDK benchmarks
│   ├── sdk_latency.py    # SDK latency comparison
│   ├── sdk_throughput.py # SDK throughput comparison
│   └── sdk_memory.py     # SDK memory usage
├── reports/              # Report generation
│   ├── report_generator.py # Base report generator
│   ├── html_report.py      # HTML report generator
│   ├── json_report.py      # JSON report generator
│   └── chart.py            # Chart generation
├── data/                 # Data persistence
│   ├── results_store.py  # SQLite results store
│   ├── comparison.py     # Results comparison
│   └── history.py        # Historical tracking
└── tests/                # Unit tests
    ├── test_runner.py
    └── conftest.py
```

## Configuration

All benchmark parameters are configured in `config.yaml`. Categories include:

- **Global settings**: Timeout, iterations, log level
- **Statistics**: Percentiles, confidence intervals, outlier detection
- **Micro-benchmarks**: Matrix sizes, buffer sizes, operations
- **Kernel benchmarks**: Syscalls, thread counts, IPC methods
- **AI benchmarks**: Model types, batch sizes, precision
- **SDK benchmarks**: SDK types, concurrent requests, memory tracking
- **Reports**: Output format, chart style, theme
- **Storage**: Database path, retention policy, export formats

## Statistics

The suite provides comprehensive statistical analysis:

- **Mean, median, mode** for central tendency
- **Standard deviation, variance** for dispersion
- **Percentiles** (50th, 75th, 90th, 95th, 99th, 99.9th)
- **Confidence intervals** (95% by default)
- **Outlier detection** (Z-score method)
- **Min/max/range** for extreme values
- **Coefficient of variation** for relative variability

## Adding New Benchmarks

1. Create a new benchmark class in the appropriate subpackage
2. Inherit from `BaseBenchmark` (defined in `runner.py`)
3. Implement `run()` returning a `BenchmarkResult`
4. Register the benchmark in the `__init__.py`
5. Add configuration in `config.yaml`

Example:

```python
from benchmarks.runner import BaseBenchmark, BenchmarkResult

class MyBenchmark(BaseBenchmark):
    def __init__(self, config: dict | None = None) -> None:
        super().__init__("my_benchmark", config)

    def run(self, iterations: int = 100) -> BenchmarkResult:
        # Benchmark implementation
        ...
        return BenchmarkResult(
            name=self.name,
            metrics={"latency_ms": 1.23},
            raw_data=[...],
            metadata={...}
        )
```

## License

MIT License - see LICENSE file for details.

## Performance Tips

- Run benchmarks on an idle system for consistent results
- Use `--warmup` to stabilize CPU caches and JIT compilers
- Disable CPU frequency scaling for reproducible results
- Isolate benchmark cores with `taskset` on Linux
- Use `--iterations` to trade speed for statistical accuracy
- Compare results within the same hardware and OS configuration