"""
AI 编译器工具链 - 错误处理模块
"""

from typing import Optional, Any


class CompilerError(Exception):
    """编译错误基类"""

    def __init__(self, message: str, line: int = 0, column: int = 0, file: str = ""):
        self.message = message
        self.line = line
        self.column = column
        self.file = file
        super().__init__(self.__str__())

    def __str__(self) -> str:
        loc = ""
        if self.file:
            loc += f"{self.file}:"
        if self.line > 0:
            loc += f"{self.line}"
            if self.column > 0:
                loc += f":{self.column}"
        if loc:
            return f"{loc}: error: {self.message}"
        return f"error: {self.message}"


class LexerError(CompilerError):
    """词法分析错误"""
    pass


class ParserError(CompilerError):
    """语法分析错误"""
    pass


class SemanticError(CompilerError):
    """语义分析错误"""
    pass


class TypeError(SemanticError):
    """类型错误"""
    pass


class NameError(SemanticError):
    """名称错误"""
    pass


class InternalError(CompilerError):
    """编译器内部错误"""
    pass


class CodeGenError(CompilerError):
    """代码生成错误"""
    pass


class OptimizerError(CompilerError):
    """优化器错误"""
    pass


class AITuningError(CompilerError):
    """AI 调优错误"""
    pass


class ConfigurationError(CompilerError):
    """配置错误"""
    pass


class IrVerificationError(InternalError):
    """IR 验证错误"""
    pass


class UnsupportedFeatureError(CompilerError):
    """不支持的特性错误"""
    pass


def format_error_list(errors: list[CompilerError]) -> str:
    """格式化错误列表"""
    lines = [f"编译过程中发现 {len(errors)} 个错误:\n"]
    for i, err in enumerate(errors, 1):
        lines.append(f"  {i}. {err}")
    return "\n".join(lines)


class ErrorReporter:
    """错误报告器，收集和管理编译错误"""

    def __init__(self):
        self._errors: list[CompilerError] = []
        self._warnings: list[CompilerError] = []

    def report_error(self, error: CompilerError) -> None:
        """报告一个错误"""
        self._errors.append(error)

    def report_warning(self, warning: CompilerError) -> None:
        """报告一个警告"""
        self._warnings.append(warning)

    def report(
        self,
        message: str,
        line: int = 0,
        column: int = 0,
        file: str = "",
        error_type: type = CompilerError,
    ) -> None:
        """便捷报告方法"""
        err = error_type(message, line, column, file)
        self._errors.append(err)

    def has_errors(self) -> bool:
        """是否有错误"""
        return len(self._errors) > 0

    def has_warnings(self) -> bool:
        """是否有警告"""
        return len(self._warnings) > 0

    def errors(self) -> list[CompilerError]:
        """获取所有错误"""
        return list(self._errors)

    def warnings(self) -> list[CompilerError]:
        """获取所有警告"""
        return list(self._warnings)

    def clear(self) -> None:
        """清除所有错误和警告"""
        self._errors.clear()
        self._warnings.clear()

    def error_count(self) -> int:
        """错误数量"""
        return len(self._errors)

    def warning_count(self) -> int:
        """警告数量"""
        return len(self._warnings)

    def summary(self) -> str:
        """生成错误摘要"""
        parts = []
        if self._errors:
            parts.append(f"{len(self._errors)} error(s)")
        if self._warnings:
            parts.append(f"{len(self._warnings)} warning(s)")
        if not parts:
            return "No errors or warnings."
        result = ", ".join(parts) + ":\n"
        for err in self._errors:
            result += f"  Error: {err}\n"
        for warn in self._warnings:
            result += f"  Warning: {warn}\n"
        return result

    def __repr__(self) -> str:
        return f"ErrorReporter(errors={len(self._errors)}, warnings={len(self._warnings)})"