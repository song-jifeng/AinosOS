"""
AI 编译器工具链 - 测试配置
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from src.utils.errors import ErrorReporter


@pytest.fixture
def error_reporter():
    """提供错误报告器实例"""
    return ErrorReporter()


@pytest.fixture
def sample_source():
    """提供示例源代码"""
    return """
fn fibonacci(n: int) -> int {
    if (n <= 1) {
        return n;
    }
    return fibonacci(n - 1) + fibonacci(n - 2);
}

fn main() {
    let result: int = fibonacci(10);
    return result;
}
"""


@pytest.fixture
def simple_source():
    """提供简单源代码"""
    return """
fn add(a: int, b: int) -> int {
    return a + b;
}

fn main() {
    let x: int = add(3, 4);
    return x;
}
"""


@pytest.fixture
def sample_tokens():
    """提供示例 Token 列表"""
    from src.frontend.token import Token, TokenType
    return [
        Token(TokenType.FN, "fn", 1, 1),
        Token(TokenType.IDENTIFIER, "main", 1, 4),
        Token(TokenType.LPAREN, "(", 1, 8),
        Token(TokenType.RPAREN, ")", 1, 9),
        Token(TokenType.LBRACE, "{", 1, 11),
        Token(TokenType.INTEGER, 42, 2, 5),
        Token(TokenType.SEMICOLON, ";", 2, 7),
        Token(TokenType.RBRACE, "}", 3, 1),
        Token(TokenType.EOF, None, 3, 2),
    ]


def assert_no_errors(reporter: ErrorReporter) -> None:
    """断言没有错误"""
    if reporter.has_errors():
        pytest.fail(f"存在未预期的错误: {reporter.summary()}")


def assert_has_errors(reporter: ErrorReporter, count: int = 1) -> None:
    """断言有指定数量的错误"""
    assert reporter.error_count() == count, f"期望 {count} 个错误，实际 {reporter.error_count()}"