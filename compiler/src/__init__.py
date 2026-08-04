"""
AI 编译器工具链

一个支持 AI 自动调优的编译器工具链，支持从自定义 AI 语言生成
C/Python/LLVM IR/x86 代码。
"""

from src.compiler import Compiler, compile_source, compile_file
from src.utils.errors import ErrorReporter
from src.utils.config import CompilerConfig

__version__ = "1.0.0"
__all__ = [
    "Compiler", "compile_source", "compile_file",
    "ErrorReporter", "CompilerConfig",
]