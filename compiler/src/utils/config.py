"""
AI 编译器工具链 - 配置模块
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, Any


@dataclass
class OptimizationConfig:
    """优化配置"""
    enable_constant_folding: bool = True
    enable_dead_code_elimination: bool = True
    enable_loop_invariant_hoisting: bool = True
    enable_common_subexpression_elimination: bool = True
    enable_copy_propagation: bool = True
    enable_strength_reduction: bool = True
    enable_peephole: bool = True
    enable_inlining: bool = False
    enable_tail_call: bool = False
    enable_vectorization: bool = False
    max_unroll_factor: int = 4
    inline_threshold: int = 50
    optimization_level: int = 2  # 0, 1, 2, 3


@dataclass
class AITuningConfig:
    """AI 调优配置"""
    enabled: bool = False
    use_reinforcement_learning: bool = True
    use_cost_model: bool = True
    profile_guided: bool = False
    learning_rate: float = 0.01
    exploration_rate: float = 0.1
    discount_factor: float = 0.9
    batch_size: int = 32
    hidden_layers: list[int] = field(default_factory=lambda: [64, 32])
    max_iterations: int = 1000
    convergence_threshold: float = 0.001
    model_save_path: str = ""
    dataset_path: str = ""


@dataclass
class CodeGenConfig:
    """代码生成配置"""
    target_language: str = "c"  # c, python, llvm, x86
    include_line_directives: bool = True
    include_debug_info: bool = False
    optimize_for: str = "speed"  # speed, size
    naming_convention: str = "snake_case"  # snake_case, camelCase
    generate_main: bool = True
    indent_size: int = 4
    max_line_width: int = 100


@dataclass
class CompilerConfig:
    """编译器配置"""
    source_file: str = ""
    output_file: str = "a.out"
    target: str = "c"  # c, python, llvm, x86
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    ai_tuning: AITuningConfig = field(default_factory=AITuningConfig)
    codegen: CodeGenConfig = field(default_factory=CodeGenConfig)
    verbose: bool = False
    dump_ast: bool = False
    dump_ir: bool = False
    dump_tokens: bool = False
    timing: bool = False
    check_only: bool = False
    max_errors: int = 50
    include_paths: list[str] = field(default_factory=list)
    defines: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CompilerConfig:
        """从字典创建配置"""
        config = cls()
        if "source_file" in d:
            config.source_file = d["source_file"]
        if "output_file" in d:
            config.output_file = d["output_file"]
        if "target" in d:
            config.target = d["target"]
        if "verbose" in d:
            config.verbose = bool(d["verbose"])
        if "dump_ast" in d:
            config.dump_ast = bool(d["dump_ast"])
        if "dump_ir" in d:
            config.dump_ir = bool(d["dump_ir"])
        if "dump_tokens" in d:
            config.dump_tokens = bool(d["dump_tokens"])
        if "timing" in d:
            config.timing = bool(d["timing"])
        if "check_only" in d:
            config.check_only = bool(d["check_only"])
        if "max_errors" in d:
            config.max_errors = int(d["max_errors"])
        if "include_paths" in d:
            config.include_paths = list(d["include_paths"])
        if "defines" in d:
            config.defines = dict(d["defines"])
        if "optimization" in d and isinstance(d["optimization"], dict):
            for key, val in d["optimization"].items():
                if hasattr(config.optimization, key):
                    setattr(config.optimization, key, val)
        if "ai_tuning" in d and isinstance(d["ai_tuning"], dict):
            for key, val in d["ai_tuning"].items():
                if hasattr(config.ai_tuning, key):
                    setattr(config.ai_tuning, key, val)
        if "codegen" in d and isinstance(d["codegen"], dict):
            for key, val in d["codegen"].items():
                if hasattr(config.codegen, key):
                    setattr(config.codegen, key, val)
        return config

    @classmethod
    def from_json(cls, path: str) -> CompilerConfig:
        """从 JSON 文件加载配置"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    def to_json(self, path: str) -> None:
        """保存配置到 JSON 文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def get_optimization_passes(self) -> list[str]:
        """根据配置返回启用的优化 pass 列表"""
        passes = []
        if self.optimization.enable_constant_folding:
            passes.append("constant_folding")
        if self.optimization.enable_dead_code_elimination:
            passes.append("dead_code_elimination")
        if self.optimization.enable_loop_invariant_hoisting:
            passes.append("loop_invariant_hoisting")
        if self.optimization.enable_common_subexpression_elimination:
            passes.append("cse")
        if self.optimization.enable_copy_propagation:
            passes.append("copy_propagation")
        if self.optimization.enable_strength_reduction:
            passes.append("strength_reduction")
        if self.optimization.enable_peephole:
            passes.append("peephole")
        if self.optimization.enable_inlining:
            passes.append("inlining")
        if self.optimization.enable_tail_call:
            passes.append("tail_call")
        if self.optimization.enable_vectorization:
            passes.append("vectorization")
        return passes

    def validate(self) -> list[str]:
        """验证配置有效性，返回错误列表"""
        errors = []
        valid_targets = {"c", "python", "llvm", "x86"}
        if self.target not in valid_targets:
            errors.append(f"Invalid target '{self.target}'. Must be one of: {', '.join(sorted(valid_targets))}")
        if self.optimization.optimization_level < 0 or self.optimization.optimization_level > 3:
            errors.append(f"Invalid optimization level {self.optimization.optimization_level}. Must be 0-3.")
        if self.codegen.optimize_for not in ("speed", "size"):
            errors.append(f"Invalid optimize_for '{self.codegen.optimize_for}'. Must be 'speed' or 'size'.")
        if self.optimization.max_unroll_factor < 0:
            errors.append("max_unroll_factor must be non-negative.")
        if self.optimization.inline_threshold < 0:
            errors.append("inline_threshold must be non-negative.")
        if self.ai_tuning.learning_rate <= 0:
            errors.append("learning_rate must be positive.")
        if self.ai_tuning.exploration_rate < 0 or self.ai_tuning.exploration_rate > 1:
            errors.append("exploration_rate must be in [0, 1].")
        if self.codegen.indent_size < 1:
            errors.append("indent_size must be at least 1.")
        if self.max_errors < 1:
            errors.append("max_errors must be at least 1.")
        return errors


# 默认配置
DEFAULT_CONFIG = CompilerConfig()

# 优化级别预设配置
OPTIMIZATION_PRESETS: dict[int, dict[str, bool]] = {
    0: {
        "enable_constant_folding": False,
        "enable_dead_code_elimination": False,
        "enable_loop_invariant_hoisting": False,
        "enable_common_subexpression_elimination": False,
        "enable_copy_propagation": False,
        "enable_strength_reduction": False,
        "enable_peephole": False,
        "enable_inlining": False,
        "enable_tail_call": False,
        "enable_vectorization": False,
    },
    1: {
        "enable_constant_folding": True,
        "enable_dead_code_elimination": True,
        "enable_loop_invariant_hoisting": False,
        "enable_common_subexpression_elimination": False,
        "enable_copy_propagation": True,
        "enable_strength_reduction": False,
        "enable_peephole": True,
        "enable_inlining": False,
        "enable_tail_call": False,
        "enable_vectorization": False,
    },
    2: {
        "enable_constant_folding": True,
        "enable_dead_code_elimination": True,
        "enable_loop_invariant_hoisting": True,
        "enable_common_subexpression_elimination": True,
        "enable_copy_propagation": True,
        "enable_strength_reduction": True,
        "enable_peephole": True,
        "enable_inlining": False,
        "enable_tail_call": False,
        "enable_vectorization": False,
    },
    3: {
        "enable_constant_folding": True,
        "enable_dead_code_elimination": True,
        "enable_loop_invariant_hoisting": True,
        "enable_common_subexpression_elimination": True,
        "enable_copy_propagation": True,
        "enable_strength_reduction": True,
        "enable_peephole": True,
        "enable_inlining": True,
        "enable_tail_call": True,
        "enable_vectorization": True,
    },
}


def apply_optimization_preset(config: CompilerConfig, level: int) -> CompilerConfig:
    """应用优化级别预设"""
    if level in OPTIMIZATION_PRESETS:
        for key, val in OPTIMIZATION_PRESETS[level].items():
            setattr(config.optimization, key, val)
        config.optimization.optimization_level = level
    return config