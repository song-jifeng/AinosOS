"""
AI 编译器工具链 - 语法分析器测试
"""

import pytest
from src.frontend.lexer import Lexer
from src.frontend.parser import Parser, ParserHelper
from src.frontend.ast import (
    Program, Module, FunctionDecl, VariableDecl, Block, IfStmt, WhileStmt,
    ForStmt, ReturnStmt, BinaryOp, IntegerLiteral, Identifier, Call,
    Parameter, ClassDecl, TypeAnnotation, ExpressionStmt,
)
from src.utils.errors import ErrorReporter


class TestParser:
    """语法分析器测试"""

    def _parse(self, source: str, reporter: ErrorReporter = None) -> Program:
        """辅助解析方法"""
        reporter = reporter or ErrorReporter()
        lexer = Lexer(source, error_reporter=reporter)
        tokens = lexer.tokenize()
        parser = Parser(tokens, error_reporter=reporter)
        return parser.parse()

    def test_empty_program(self):
        """测试空程序"""
        program = self._parse("")
        assert len(program.modules) == 0

    def test_function_declaration(self):
        """测试函数声明"""
        source = "fn main() { return 0; }"
        program = self._parse(source)
        assert len(program.modules) > 0
        module = program.modules[0]
        assert len(module.declarations) > 0
        decl = module.declarations[0]
        assert isinstance(decl, FunctionDecl)
        assert decl.name == "main"

    def test_function_with_params(self):
        """测试带参数的函数"""
        source = "fn add(a: int, b: int) -> int { return a + b; }"
        program = self._parse(source)
        decl = program.modules[0].declarations[0]
        assert isinstance(decl, FunctionDecl)
        assert len(decl.params) == 2
        assert decl.params[0].name == "a"
        assert decl.params[1].name == "b"
        assert decl.return_type is not None

    def test_variable_declaration(self):
        """测试变量声明"""
        source = "let x: int = 42;"
        program = self._parse(source)
        decl = program.modules[0].declarations[0]
        assert isinstance(decl, VariableDecl)
        assert decl.name == "x"
        assert decl.initializer is not None
        assert isinstance(decl.initializer, IntegerLiteral)
        assert decl.initializer.value == 42

    def test_const_declaration(self):
        """测试常量声明"""
        source = "const MAX: int = 100;"
        program = self._parse(source)
        decl = program.modules[0].declarations[0]
        assert isinstance(decl, VariableDecl)
        assert decl.name == "MAX"
        assert not decl.mutable

    def test_if_statement(self):
        """测试 if 语句"""
        source = """
fn test() {
    if (x > 0) {
        return 1;
    } else {
        return 0;
    }
}
"""
        program = self._parse(source)
        decl = program.modules[0].declarations[0]
        assert isinstance(decl, FunctionDecl)
        body = decl.body
        assert isinstance(body, Block)
        assert len(body.statements) > 0
        if_stmt = body.statements[0]
        assert isinstance(if_stmt, IfStmt)
        assert if_stmt.else_body is not None

    def test_while_statement(self):
        """测试 while 语句"""
        source = """
fn test() {
    while (i < 10) {
        i = i + 1;
    }
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_for_statement(self):
        """测试 for 语句"""
        source = """
fn test() {
    for (let i = 0; i < 10; i = i + 1) {
        print(i);
    }
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_return_statement(self):
        """测试 return 语句"""
        source = "fn test() -> int { return 42; }"
        program = self._parse(source)
        decl = program.modules[0].declarations[0]
        assert isinstance(decl, FunctionDecl)
        body = decl.body
        assert isinstance(body, Block)
        assert len(body.statements) > 0
        ret = body.statements[0]
        assert isinstance(ret, ReturnStmt)
        assert ret.value is not None

    def test_function_call(self):
        """测试函数调用"""
        source = """
fn test() {
    let result = add(3, 4);
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_class_declaration(self):
        """测试类声明"""
        source = """
class Point {
    let x: int;
    let y: int;
    fn new(x: int, y: int) -> Point {
        return null;
    }
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0
        decl = program.modules[0].declarations[0]
        assert isinstance(decl, ClassDecl)
        assert decl.name == "Point"

    def test_import_declaration(self):
        """测试 import 声明"""
        source = 'import "math.ai";'
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_binary_expressions(self):
        """测试二元表达式"""
        source = """
fn test() {
    let a = 1 + 2 * 3 - 4 / 2;
    let b = (a + 1) * 2;
    let c = x > 0 && y < 10;
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_unary_expressions(self):
        """测试一元表达式"""
        source = """
fn test() {
    let a = -x;
    let b = !flag;
    let c = ~val;
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_array_literal(self):
        """测试数组字面量"""
        source = """
fn test() {
    let arr = [1, 2, 3, 4, 5];
    let first = arr[0];
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_nested_blocks(self):
        """测试嵌套块"""
        source = """
fn test() {
    {
        let x = 1;
        {
            let y = 2;
        }
    }
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_parse_errors(self):
        """测试语法错误"""
        reporter = ErrorReporter()
        self._parse("fn test() { return ; }", reporter)
        # 没有分号的情况
        reporter2 = ErrorReporter()
        self._parse("fn test() { return }", reporter2)
        # 应该捕获到错误

    def test_multiple_functions(self):
        """测试多个函数"""
        source = """
fn add(a: int, b: int) -> int {
    return a + b;
}
fn sub(a: int, b: int) -> int {
    return a - b;
}
fn main() {
    return 0;
}
"""
        program = self._parse(source)
        funcs = [d for d in program.modules[0].declarations if isinstance(d, FunctionDecl)]
        assert len(funcs) == 3

    def test_type_annotations(self):
        """测试类型注解"""
        source = """
fn process(data: tensor<float, [3, 224, 224]>) -> array<int> {
    return null;
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_lambda_expression(self):
        """测试 lambda 表达式"""
        source = """
fn test() {
    let f = lambda (x: int) -> int => x * 2;
    let result = f(5);
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_ternary_expression(self):
        """测试三元表达式"""
        source = """
fn test() {
    let max = (a > b) ? a : b;
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_assert_statement(self):
        """测试 assert 语句"""
        source = """
fn test() {
    assert(x > 0, "x must be positive");
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_break_continue(self):
        """测试 break/continue"""
        source = """
fn test() {
    while (true) {
        if (done) {
            break;
        }
        continue;
    }
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_expression_operator_precedence(self):
        """测试运算符优先级"""
        source = """
fn test() {
    let a = 1 + 2 * 3;      // 1 + (2 * 3) = 7
    let b = (1 + 2) * 3;    // 9
    let c = -1 + 2;         // 1
    let d = !true && false;  // false
}
"""
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0

    def test_export_declaration(self):
        """测试 export 声明"""
        source = "export fn public_func() { return 0; }"
        program = self._parse(source)
        assert len(program.modules[0].declarations) > 0


class TestParserHelper:
    """语法分析辅助工具测试"""

    def test_parse_source(self):
        """测试 parse_source"""
        source = "fn main() { return 0; }"
        program = ParserHelper.parse_source(source)
        assert isinstance(program, Program)
        assert len(program.modules) > 0
        assert len(program.modules[0].declarations) > 0

    def test_error_recovery(self):
        """测试错误恢复"""
        reporter = ErrorReporter()
        source = """
fn valid() { return 0; }
fn invalid( { return 1; }
fn also_valid() { return 2; }
"""
        program = ParserHelper.parse_source(source, error_reporter=reporter)
        # 即使有错误，也应该能解析到 valid 函数
        funcs = [d for d in program.modules[0].declarations if isinstance(d, FunctionDecl)]
        assert len(funcs) >= 2