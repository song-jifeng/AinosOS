"""
AI 编译器工具链 - 主编译器类
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional, Any

from src.utils.errors import (
    CompilerError, LexerError, ParserError, SemanticError,
    CodeGenError, ErrorReporter, format_error_list,
)
from src.utils.config import (
    CompilerConfig, apply_optimization_preset,
)
from src.frontend.lexer import Lexer, LexerHelper
from src.frontend.parser import Parser, ParserHelper
from src.frontend.ast import (
    Program, Module, ASTPrinter,
)
from src.middle.analyzer import SemanticAnalyzer, TypeChecker
from src.middle.ir import IRModule, IRBuilder
from src.middle.transform import ASTToIRConverter, IRTransform
from src.middle.optimizer import Optimizer, OptimizationPipeline
from src.backend.codegen import CodeGenerator, CCodeGenerator, PythonCodeGenerator
from src.backend.x86_gen import X86Generator
from src.backend.llvm_gen import LLVMIRGenerator
from src.ai.autotune import Autotuner, FeatureExtractor
from src.ai.profile import Profiler, ProfileGuidedOptimizer
from src.ai.cost_model import CostModel, OptimizationCostBenefitAnalysis


class Compiler:
    """AI 编译器主编译器类"""

    def __init__(self, config: Optional[CompilerConfig] = None):
        self.config: CompilerConfig = config or CompilerConfig()
        self.error_reporter: ErrorReporter = ErrorReporter()
        self.program: Optional[Program] = None
        self.ir_module: Optional[IRModule] = None
        self.generated_code: str = ""
        self._timings: dict[str, float] = {}

    def compile(self, source: str, file: str = "") -> bool:
        """编译源代码（完整流程）

        Args:
            source: 源代码字符串
            file: 源文件名

        Returns:
            编译是否成功
        """
        self.error_reporter.clear()
        self._timings = {}

        try:
            # 1. 词法分析
            if self.config.timing:
                t0 = time.time()
            tokens = self._lex(source, file)
            if self.config.timing:
                self._timings["lexer"] = time.time() - t0
            if self.config.dump_tokens:
                self._dump_tokens(tokens)

            if self.error_reporter.has_errors() and self.error_reporter.error_count() >= self.config.max_errors:
                return False

            # 2. 语法分析
            if self.config.timing:
                t0 = time.time()
            self.program = self._parse(tokens, file)
            if self.config.timing:
                self._timings["parser"] = time.time() - t0
            if self.config.dump_ast:
                self._dump_ast(self.program)

            if self.error_reporter.has_errors():
                return False

            # 3. 语义分析
            if self.config.timing:
                t0 = time.time()
            self.program = self._analyze(self.program)
            if self.config.timing:
                self._timings["analyzer"] = time.time() - t0

            if self.error_reporter.has_errors():
                return False

            if self.config.check_only:
                return True

            # 4. IR 生成
            if self.config.timing:
                t0 = time.time()
            self.ir_module = self._generate_ir(self.program)
            if self.config.timing:
                self._timings["ir_gen"] = time.time() - t0
            if self.config.dump_ir:
                self._dump_ir(self.ir_module)

            # 5. 优化
            if self.config.timing:
                t0 = time.time()
            self.ir_module = self._optimize(self.ir_module)
            if self.config.timing:
                self._timings["optimizer"] = time.time() - t0

            # 6. AI 自动调优
            if self.config.ai_tuning.enabled:
                if self.config.timing:
                    t0 = time.time()
                self.ir_module = self._ai_tune(self.ir_module)
                if self.config.timing:
                    self._timings["ai_tune"] = time.time() - t0

            # 7. 代码生成
            if self.config.timing:
                t0 = time.time()
            self.generated_code = self._generate_code(self.ir_module, self.program)
            if self.config.timing:
                self._timings["codegen"] = time.time() - t0

            return True

        except CompilerError as e:
            self.error_reporter.report_error(e)
            return False
        except Exception as e:
            self.error_reporter.report_error(
                CompilerError(f"编译过程中发生未预期的错误: {e}", file=file)
            )
            return False

    def compile_file(self, filepath: str) -> bool:
        """编译源文件

        Args:
            filepath: 源文件路径

        Returns:
            编译是否成功
        """
        self.config.source_file = filepath
        if not self.config.output_file or self.config.output_file == "a.out":
            base = os.path.splitext(os.path.basename(filepath))[0]
            self.config.output_file = f"{base}.{self.config.target}"

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
        except IOError as e:
            self.error_reporter.report_error(
                CompilerError(f"无法读取源文件: {e}", file=filepath)
            )
            return False

        return self.compile(source, filepath)

    def _lex(self, source: str, file: str = "") -> list:
        """词法分析"""
        lexer = Lexer(source, file, self.error_reporter)
        tokens = lexer.tokenize()
        if self.config.verbose:
            print(f"词法分析完成: {len(tokens)} tokens")
        return tokens

    def _parse(self, tokens: list, file: str = "") -> Program:
        """语法分析"""
        parser = Parser(tokens, file, self.error_reporter)
        program = parser.parse()
        if self.config.verbose:
            modules = len(program.modules)
            decls = sum(len(m.declarations) for m in program.modules)
            print(f"语法分析完成: {modules} 模块, {decls} 声明")
        return program

    def _analyze(self, program: Program) -> Program:
        """语义分析"""
        analyzer = SemanticAnalyzer(self.error_reporter)
        program = analyzer.analyze(program)
        if self.config.verbose:
            print(f"语义分析完成")
        return program

    def _generate_ir(self, program: Program) -> IRModule:
        """IR 生成"""
        converter = ASTToIRConverter(error_reporter=self.error_reporter)
        ir_module = converter.convert(program)
        if self.config.verbose:
            func_count = len(ir_module.functions)
            print(f"IR 生成完成: {func_count} 函数")
        return ir_module

    def _optimize(self, ir_module: IRModule) -> IRModule:
        """优化"""
        optimizer = OptimizationPipeline(ir_module, self.error_reporter)
        ir_module = optimizer.run(self.config.optimization.optimization_level)
        if self.config.verbose:
            print(f"优化完成 (级别 {self.config.optimization.optimization_level})")
        return ir_module

    def _ai_tune(self, ir_module: IRModule) -> IRModule:
        """AI 自动调优"""
        autotuner = Autotuner(self.config.ai_tuning, self.error_reporter)
        best_sequence = autotuner.tune()
        passes = [s.name for s in best_sequence.steps if s.applied]

        if passes:
            optimizer = Optimizer(ir_module, self.error_reporter)
            ir_module = optimizer.optimize(passes)

        if self.config.verbose:
            print(f"AI 自动调优完成: {passes}")
        return ir_module

    def _generate_code(self, ir_module: IRModule, program: Program) -> str:
        """代码生成"""
        target = self.config.target

        if target == "c":
            return self._generate_c(program)
        elif target == "python":
            return self._generate_python(program)
        elif target == "llvm":
            return self._generate_llvm(ir_module)
        elif target == "x86":
            return self._generate_x86(ir_module)
        else:
            raise CodeGenError(f"不支持的目标语言: {target}")

    def _generate_c(self, program: Program) -> str:
        """生成 C 代码"""
        gen = CCodeGenerator(self.error_reporter)
        return gen.generate(program)

    def _generate_python(self, program: Program) -> str:
        """生成 Python 代码"""
        gen = PythonCodeGenerator(self.error_reporter)
        return gen.generate(program)

    def _generate_llvm(self, ir_module: IRModule) -> str:
        """生成 LLVM IR"""
        gen = LLVMIRGenerator(self.error_reporter)
        return gen.generate(ir_module)

    def _generate_x86(self, ir_module: IRModule) -> str:
        """生成 x86 汇编"""
        gen = X86Generator(self.error_reporter)
        return gen.generate(ir_module)

    def _dump_tokens(self, tokens: list) -> None:
        """打印 Token 列表"""
        print("=" * 60)
        print("Token 列表:")
        print(LexerHelper.tokens_to_string(tokens))
        print("=" * 60)

    def _dump_ast(self, program: Program) -> None:
        """打印 AST"""
        print("=" * 60)
        print("AST:")
        printer = ASTPrinter()
        print(printer.visit(program))
        print("=" * 60)

    def _dump_ir(self, ir_module: IRModule) -> None:
        """打印 IR"""
        print("=" * 60)
        print("IR:")
        print(str(ir_module))
        print("=" * 60)

    def save_output(self, filepath: Optional[str] = None) -> bool:
        """保存生成的代码到文件"""
        path = filepath or self.config.output_file
        if not path:
            self.error_reporter.report_error(
                CompilerError("未指定输出文件路径")
            )
            return False
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.generated_code)
            if self.config.verbose:
                print(f"输出已保存到: {path}")
            return True
        except IOError as e:
            self.error_reporter.report_error(
                CompilerError(f"无法写入输出文件: {e}")
            )
            return False

    def get_timing_report(self) -> str:
        """获取计时报告"""
        if not self._timings:
            return "未收集计时信息"
        lines = ["编译计时:"]
        total = sum(self._timings.values())
        for phase, t in self._timings.items():
            pct = (t / total * 100) if total > 0 else 0
            lines.append(f"  {phase:15s}: {t:.4f}s ({pct:.1f}%)")
        lines.append(f"  {'总时间':15s}: {total:.4f}s")
        return "\n".join(lines)

    def get_optimization_report(self) -> str:
        """获取优化报告"""
        if not self.ir_module:
            return "无 IR 模块"
        from src.middle.optimizer import OptimizationReporter
        return OptimizationReporter.report(self.ir_module, self.ir_module, [])

    def get_errors(self) -> list[CompilerError]:
        """获取编译错误"""
        return self.error_reporter.errors()

    def get_warnings(self) -> list[CompilerError]:
        """获取编译警告"""
        return self.error_reporter.warnings()

    def has_errors(self) -> bool:
        """是否有错误"""
        return self.error_reporter.has_errors()

    def reset(self) -> None:
        """重置编译器状态"""
        self.error_reporter.clear()
        self.program = None
        self.ir_module = None
        self.generated_code = ""
        self._timings = {}

    @staticmethod
    def version() -> str:
        """获取版本信息"""
        return "AI Compiler Toolchain v1.0.0"

    @staticmethod
    def run_command_line(args: Optional[list[str]] = None) -> int:
        """命令行入口

        Args:
            args: 命令行参数

        Returns:
            退出码 (0 成功, 1 失败)
        """
        import argparse

        parser = argparse.ArgumentParser(
            description="AI Compiler Toolchain - AI 编译器工具链",
            prog="aicompiler"
        )
        parser.add_argument("source", nargs="?", help="源文件路径")
        parser.add_argument("-o", "--output", help="输出文件路径")
        parser.add_argument("-t", "--target", choices=["c", "python", "llvm", "x86"],
                          default="c", help="目标语言")
        parser.add_argument("-O", "--optimize", type=int, choices=[0, 1, 2, 3],
                          default=2, help="优化级别")
        parser.add_argument("--dump-tokens", action="store_true", help="打印 Token 列表")
        parser.add_argument("--dump-ast", action="store_true", help="打印 AST")
        parser.add_argument("--dump-ir", action="store_true", help="打印 IR")
        parser.add_argument("--check-only", action="store_true", help="仅检查语法和语义")
        parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
        parser.add_argument("--timing", action="store_true", help="输出计时信息")
        parser.add_argument("--ai-tuning", action="store_true", help="启用 AI 自动调优")
        parser.add_argument("--version", action="store_true", help="显示版本信息")

        parsed = parser.parse_args(args)

        if parsed.version:
            print(Compiler.version())
            return 0

        if not parsed.source:
            parser.print_help()
            return 1

        # 创建配置
        config = CompilerConfig()
        config.source_file = parsed.source
        config.target = parsed.target
        config.output_file = parsed.output or f"output.{parsed.target}"
        config.dump_tokens = parsed.dump_tokens
        config.dump_ast = parsed.dump_ast
        config.dump_ir = parsed.dump_ir
        config.check_only = parsed.check_only
        config.verbose = parsed.verbose
        config.timing = parsed.timing
        config.ai_tuning.enabled = parsed.ai_tuning

        apply_optimization_preset(config, parsed.optimize)

        # 编译
        compiler = Compiler(config)
        success = compiler.compile_file(parsed.source)

        if parsed.verbose or parsed.timing:
            print(compiler.get_timing_report())

        if not success:
            print(compiler.error_reporter.summary(), file=sys.stderr)
            return 1

        if parsed.check_only:
            print("检查通过，无错误。")
            return 0

        # 保存输出
        if not parsed.check_only:
            compiler.save_output()

        if parsed.verbose:
            print(f"编译成功: {parsed.source} -> {config.output_file}")

        return 0


# 便捷函数
def compile_source(source: str, target: str = "c", **kwargs) -> tuple[bool, str, Compiler]:
    """编译源代码字符串

    Args:
        source: 源代码
        target: 目标语言
        **kwargs: 其他配置参数

    Returns:
        (success, generated_code, compiler)
    """
    config = CompilerConfig()
    config.target = target
    for key, val in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, val)
    compiler = Compiler(config)
    success = compiler.compile(source)
    return success, compiler.generated_code, compiler


def compile_file(filepath: str, target: str = "c", **kwargs) -> tuple[bool, str, Compiler]:
    """编译源文件

    Args:
        filepath: 源文件路径
        target: 目标语言
        **kwargs: 其他配置参数

    Returns:
        (success, generated_code, compiler)
    """
    config = CompilerConfig()
    config.target = target
    for key, val in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, val)
    compiler = Compiler(config)
    success = compiler.compile_file(filepath)
    return success, compiler.generated_code, compiler