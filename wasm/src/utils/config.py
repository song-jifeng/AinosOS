"""Configuration management for the WebAssembly runtime.

This module provides configuration classes for all components of the
WebAssembly runtime, allowing fine-grained control over behavior.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class WasmConfig:
    """Core WebAssembly configuration."""
    max_pages: int = 65536
    max_memory_size: int = 65536 * 65536  # 4GB
    max_table_size: int = 10000000
    max_func_locals: int = 50000
    max_function_params: int = 1000
    max_function_results: int = 1000
    max_globals: int = 1000000
    max_exports: int = 100000
    max_imports: int = 100000
    max_initialized_data_segments: int = 100000
    max_data_segments: int = 100000
    max_element_segments: int = 100000
    max_br_table_size: int = 1000000
    max_control_flow_stack: int = 1000000
    max_function_size: int = 128 * 1024 * 1024  # 128MB
    max_module_size: int = 1024 * 1024 * 1024  # 1GB
    enable_multi_value: bool = True
    enable_bulk_memory: bool = True
    enable_reference_types: bool = True
    enable_simd: bool = True
    enable_tail_call: bool = True
    enable_extended_const: bool = True
    enable_sign_ext: bool = True
    enable_mutable_globals: bool = True
    enable_nontrapping_float_to_int: bool = True
    enable_exception_handling: bool = False
    enable_threads: bool = False
    enable_memory64: bool = False


@dataclass
class RuntimeConfig:
    """Runtime execution configuration."""
    max_stack_height: int = 1000000
    max_call_depth: int = 100000
    max_memory_pages: int = 65536
    trap_on_overflow: bool = True
    trap_on_division_by_zero: bool = True
    trap_on_invalid_conversion: bool = True
    trap_on_out_of_bounds: bool = True
    trap_on_uninitialized: bool = True
    trap_on_indirect_call_mismatch: bool = True
    trap_on_table_overflow: bool = True
    deterministic_execution: bool = False
    enable_instruction_counting: bool = False
    max_instructions: int = 0  # 0 = unlimited
    preserve_stack_trace: bool = True
    trace_execution: bool = False


@dataclass
class CompilerConfig:
    """JIT/AOT compiler configuration."""
    enable_jit: bool = True
    enable_optimization: bool = True
    optimization_level: int = 2  # 0-3
    enable_inlining: bool = True
    enable_constant_folding: bool = True
    enable_dead_code_elimination: bool = True
    enable_loop_unrolling: bool = False
    enable_vectorization: bool = True
    max_inline_size: int = 100
    max_loop_unroll_count: int = 4
    enable_stack_to_register: bool = True
    enable_peephole: bool = True
    enable_cse: bool = True  # Common subexpression elimination
    enable_lvn: bool = True  # Local value numbering
    cache_compiled_code: bool = True
    max_cache_size: int = 100


@dataclass
class WASIConfig:
    """WASI (WebAssembly System Interface) configuration."""
    enable_wasi: bool = True
    enable_wasi_unstable: bool = True
    enable_wasi_snapshot_preview1: bool = True
    fs_root: str = "/"
    allowed_dirs: List[str] = field(default_factory=lambda: ["/"])
    allowed_env_vars: List[str] = field(default_factory=list)
    allow_network: bool = False
    allow_clock: bool = True
    allow_random: bool = True
    allow_stdio: bool = True
    allow_fs_operations: bool = True
    allow_process_operations: bool = False
    enable_stdout: bool = True
    enable_stderr: bool = True
    enable_stdin: bool = True
    args: List[str] = field(default_factory=list)
    env_vars: Dict[str, str] = field(default_factory=dict)


@dataclass
class AinosConfig:
    """AinosOS-specific configuration for AI inference."""
    enable_inference: bool = True
    enable_tensor_ops: bool = True
    enable_model_loading: bool = True
    default_tensor_type: str = "f32"
    max_tensor_elements: int = 100000000
    max_tensor_dimensions: int = 8
    max_model_size: int = 1024 * 1024 * 1024  # 1GB
    enable_gpu_acceleration: bool = False
    enable_quantization: bool = True
    default_quantization: str = "none"  # none, int8, fp16
    inference_timeout_ms: int = 30000
    model_cache_dir: str = "/tmp/ainos_models"
    enable_batch_processing: bool = True
    max_batch_size: int = 64


@dataclass
class GlobalConfig:
    """Global runtime configuration combining all sub-configurations."""
    wasm: WasmConfig = field(default_factory=WasmConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    compiler: CompilerConfig = field(default_factory=CompilerConfig)
    wasi: WASIConfig = field(default_factory=WASIConfig)
    ainos: AinosConfig = field(default_factory=AinosConfig)

    @classmethod
    def default(cls) -> "GlobalConfig":
        """Create a default configuration instance."""
        return cls()

    @classmethod
    def minimal(cls) -> "GlobalConfig":
        """Create a minimal configuration for constrained environments."""
        config = cls()
        config.wasm.enable_simd = False
        config.wasm.enable_tail_call = False
        config.wasm.enable_exception_handling = False
        config.compiler.enable_jit = False
        config.compiler.enable_optimization = False
        config.wasi.enable_wasi = False
        config.ainos.enable_inference = False
        return config

    @classmethod
    def from_dict(cls, config_dict: Dict) -> "GlobalConfig":
        """Create a configuration from a dictionary.

        Args:
            config_dict: Dictionary with configuration values.
                Keys can be nested with dot notation (e.g., 'wasm.max_pages').

        Returns:
            A new GlobalConfig instance with the specified overrides.
        """
        config = cls.default()
        for key, value in config_dict.items():
            if "." in key:
                section, sub_key = key.split(".", 1)
                if hasattr(config, section):
                    subsection = getattr(config, section)
                    if hasattr(subsection, sub_key):
                        setattr(subsection, sub_key, value)
            else:
                if hasattr(config, key):
                    setattr(config, key, value)
        return config

    def to_dict(self) -> Dict:
        """Convert the configuration to a dictionary."""
        return {
            "wasm": {
                k: v for k, v in self.wasm.__dict__.items()
                if not k.startswith("_")
            },
            "runtime": {
                k: v for k, v in self.runtime.__dict__.items()
                if not k.startswith("_")
            },
            "compiler": {
                k: v for k, v in self.compiler.__dict__.items()
                if not k.startswith("_")
            },
            "wasi": {
                k: v for k, v in self.wasi.__dict__.items()
                if not k.startswith("_")
            },
            "ainos": {
                k: v for k, v in self.ainos.__dict__.items()
                if not k.startswith("_")
            },
        }


# Global configuration instance
_CONFIG: Optional[GlobalConfig] = None


def get_config() -> GlobalConfig:
    """Get the global configuration instance.

    Returns:
        The current global configuration, creating a default one if needed.
    """
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = GlobalConfig.default()
    return _CONFIG


def set_config(config: GlobalConfig) -> None:
    """Set the global configuration instance.

    Args:
        config: The configuration to use.
    """
    global _CONFIG
    _CONFIG = config


def reset_config() -> None:
    """Reset the global configuration to default."""
    global _CONFIG
    _CONFIG = GlobalConfig.default()