"""
AI 编译器工具链 - 词法分析器测试
"""

import pytest
from src.frontend.lexer import Lexer, LexerHelper
from src.frontend.token import TokenType, Token
from src.utils.errors import ErrorReporter


class TestLexer:
    """词法分析器测试"""

    def test_empty_source(self):
        """测试空源代码"""
        lexer = Lexer("")
        tokens = lexer.tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_whitespace_only(self):
        """测试纯空白字符"""
        lexer = Lexer("   \n\t\r  ")
        tokens = lexer.tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_identifier(self):
        """测试标识符"""
        lexer = Lexer("hello world _test foo123")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "hello"
        assert tokens[1].type == TokenType.IDENTIFIER
        assert tokens[1].value == "world"
        assert tokens[2].type == TokenType.IDENTIFIER
        assert tokens[2].value == "_test"
        assert tokens[3].type == TokenType.IDENTIFIER
        assert tokens[3].value == "foo123"

    def test_keywords(self):
        """测试关键字"""
        source = "fn let const if else while for return class import true false null"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        keyword_tokens = [t for t in tokens if t.type != TokenType.EOF]
        expected_types = [
            TokenType.FN, TokenType.LET, TokenType.CONST, TokenType.IF,
            TokenType.ELSE, TokenType.WHILE, TokenType.FOR, TokenType.RETURN,
            TokenType.CLASS, TokenType.IMPORT, TokenType.TRUE, TokenType.FALSE,
            TokenType.NULL,
        ]
        for token, expected in zip(keyword_tokens, expected_types):
            assert token.type == expected, f"期望 {expected}，实际 {token.type}"

    def test_integer_literals(self):
        """测试整数字面量"""
        lexer = Lexer("42 0 12345 0xFF 0b1010 0o77")
        tokens = lexer.tokenize()
        integers = [t for t in tokens if t.type == TokenType.INTEGER]
        assert len(integers) == 6
        assert integers[0].value == 42
        assert integers[1].value == 0
        assert integers[2].value == 12345
        assert integers[3].value == 255  # 0xFF
        assert integers[4].value == 10   # 0b1010
        assert integers[5].value == 63   # 0o77

    def test_float_literals(self):
        """测试浮点数字面量"""
        lexer = Lexer("3.14 0.5 10.0 1e10 2.5e-3")
        tokens = lexer.tokenize()
        floats = [t for t in tokens if t.type == TokenType.FLOAT_LITERAL]
        assert len(floats) == 5
        assert floats[0].value == 3.14
        assert floats[1].value == 0.5
        assert floats[2].value == 10.0
        assert floats[3].value == 1e10
        assert pytest.approx(floats[4].value, 0.001) == 0.0025

    def test_string_literals(self):
        """测试字符串字面量"""
        lexer = Lexer('"hello" "world" "hello\\nworld" "escape\\ttest"')
        tokens = lexer.tokenize()
        strings = [t for t in tokens if t.type == TokenType.STRING_LITERAL]
        assert len(strings) == 4
        assert strings[0].value == "hello"
        assert strings[1].value == "world"
        assert strings[2].value == "hello\nworld"
        assert strings[3].value == "escape\ttest"

    def test_operators(self):
        """测试运算符"""
        source = "+ - * / % = == != < > <= >= && || ! & | ^ ~ << >>"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        operators = [t for t in tokens if t.type != TokenType.EOF]
        expected_types = [
            TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
            TokenType.PERCENT, TokenType.EQUAL, TokenType.EQUAL_EQUAL,
            TokenType.NOT_EQUAL, TokenType.LESS, TokenType.GREATER,
            TokenType.LESS_EQUAL, TokenType.GREATER_EQUAL, TokenType.AND,
            TokenType.OR, TokenType.NOT, TokenType.BIT_AND, TokenType.BIT_OR,
            TokenType.BIT_XOR, TokenType.BIT_NOT, TokenType.LEFT_SHIFT,
            TokenType.RIGHT_SHIFT,
        ]
        for token, expected in zip(operators, expected_types):
            assert token.type == expected, f"期望 {expected}，实际 {token.type}"

    def test_compound_operators(self):
        """测试复合运算符"""
        source = "+= -= *= /= %= ++ -- -> => <<= >>= ::"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        ops = [t for t in tokens if t.type != TokenType.EOF]
        expected_types = [
            TokenType.PLUS_EQUAL, TokenType.MINUS_EQUAL, TokenType.STAR_EQUAL,
            TokenType.SLASH_EQUAL, TokenType.PERCENT_EQUAL, TokenType.PLUS_PLUS,
            TokenType.MINUS_MINUS, TokenType.ARROW, TokenType.FAT_ARROW,
            TokenType.LEFT_SHIFT_EQUAL, TokenType.RIGHT_SHIFT_EQUAL, TokenType.COLON_COLON,
        ]
        assert len(ops) == len(expected_types)
        for token, expected in zip(ops, expected_types):
            assert token.type == expected, f"期望 {expected}，实际 {token.type}"

    def test_delimiters(self):
        """测试分隔符"""
        source = "() {} [] , ; : ."
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        delimiters = [t for t in tokens if t.type != TokenType.EOF]
        expected_types = [
            TokenType.LPAREN, TokenType.RPAREN, TokenType.LBRACE, TokenType.RBRACE,
            TokenType.LBRACKET, TokenType.RBRACKET, TokenType.COMMA, TokenType.SEMICOLON,
            TokenType.COLON, TokenType.DOT,
        ]
        assert len(delimiters) == len(expected_types)
        for token, expected in zip(delimiters, expected_types):
            assert token.type == expected

    def test_line_comments(self):
        """测试行注释"""
        lexer = Lexer("// this is a comment\nlet x = 42;")
        tokens = lexer.tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 4  # let, x, =, 42, ;
        assert non_eof[0].type == TokenType.LET

    def test_block_comments(self):
        """测试块注释"""
        lexer = Lexer("/* block comment */ let x = 42;")
        tokens = lexer.tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 4

    def test_hash_comments(self):
        """测试 hash 注释"""
        lexer = Lexer("# hash comment\nlet x = 42;")
        tokens = lexer.tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 4

    def test_line_numbers(self):
        """测试行号记录"""
        source = "let\nx\n=\n42;"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert non_eof[0].line == 1  # let
        assert non_eof[1].line == 2  # x
        assert non_eof[2].line == 3  # =
        assert non_eof[3].line == 4  # 42

    def test_invalid_char(self):
        """测试无效字符"""
        reporter = ErrorReporter()
        lexer = Lexer("let @x = 42;", error_reporter=reporter)
        tokens = lexer.tokenize()
        assert reporter.has_errors()

    def test_unclosed_string(self):
        """测试未闭合字符串"""
        reporter = ErrorReporter()
        lexer = Lexer('"hello', error_reporter=reporter)
        tokens = lexer.tokenize()
        assert reporter.has_errors()

    def test_unclosed_block_comment(self):
        """测试未闭合块注释"""
        reporter = ErrorReporter()
        lexer = Lexer("/* unclosed comment", error_reporter=reporter)
        tokens = lexer.tokenize()
        assert reporter.has_errors()

    def test_boolean_literals(self):
        """测试布尔字面量"""
        lexer = Lexer("true false")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.TRUE
        assert tokens[0].value is True
        assert tokens[1].type == TokenType.FALSE
        assert tokens[1].value is False

    def test_null_literal(self):
        """测试 null 字面量"""
        lexer = Lexer("null")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.NULL
        assert tokens[0].value is None

    def test_multiple_operators(self):
        """测试连续运算符"""
        source = "a + b * c / d % e"
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 9

    def test_underscore_identifier(self):
        """测试下划线标识符"""
        lexer = Lexer("_ __ _hidden _123")
        tokens = lexer.tokenize()
        for t in tokens:
            if t.type != TokenType.EOF:
                assert t.type == TokenType.IDENTIFIER

    def test_source_position(self):
        """测试源位置"""
        lexer = Lexer("fn main() {\n  let x = 1;\n}")
        tokens = lexer.tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        # 验证位置
        fn_tok = non_eof[0]
        assert fn_tok.line == 1
        assert fn_tok.column == 1

    def test_integer_limits(self):
        """测试整数边界"""
        lexer = Lexer("2147483647 0 999999999999999999999999999")
        tokens = lexer.tokenize()
        ints = [t for t in tokens if t.type == TokenType.INTEGER]
        assert len(ints) >= 2
        assert ints[0].value == 2147483647


class TestLexerHelper:
    """词法分析辅助工具测试"""

    def test_is_valid_identifier(self):
        """测试标识符验证"""
        assert LexerHelper.is_valid_identifier("hello")
        assert LexerHelper.is_valid_identifier("_test")
        assert LexerHelper.is_valid_identifier("foo123")
        assert not LexerHelper.is_valid_identifier("123abc")
        assert not LexerHelper.is_valid_identifier("")
        assert not LexerHelper.is_valid_identifier("let")  # 关键字

    def test_tokens_to_string(self):
        """测试 Token 转字符串"""
        from src.frontend.token import Token, TokenType
        tokens = [
            Token(TokenType.LET, "let", 1, 1),
            Token(TokenType.IDENTIFIER, "x", 1, 5),
            Token(TokenType.EOF, None, 1, 6),
        ]
        result = LexerHelper.tokens_to_string(tokens)
        assert "LET" in result
        assert "IDENTIFIER" in result
        assert "EOF" in result