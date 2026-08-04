"""
AI 编译器工具链 - Token 类型定义
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any


class TokenType:
    """Token 类型常量定义"""
    # 关键字
    LET: str = "LET"
    CONST: str = "CONST"
    FN: str = "FN"
    RETURN: str = "RETURN"
    IF: str = "IF"
    ELSE: str = "ELSE"
    WHILE: str = "WHILE"
    FOR: str = "FOR"
    BREAK: str = "BREAK"
    CONTINUE: str = "CONTINUE"
    CLASS: str = "CLASS"
    IMPORT: str = "IMPORT"
    FROM: str = "FROM"
    EXPORT: str = "EXPORT"
    TRUE: str = "TRUE"
    FALSE: str = "FALSE"
    NULL: str = "NULL"
    VOID: str = "VOID"
    INT: str = "INT"
    FLOAT: str = "FLOAT"
    BOOL: str = "BOOL"
    STRING: str = "STRING"
    ARRAY: str = "ARRAY"
    RECORD: str = "RECORD"
    TENSOR: str = "TENSOR"
    PUBLIC: str = "PUBLIC"
    PRIVATE: str = "PRIVATE"
    MATCH: str = "MATCH"
    LAMBDA: str = "LAMBDA"
    TYPE: str = "TYPE"
    MUT: str = "MUT"
    STATIC: str = "STATIC"
    EXTERN: str = "EXTERN"
    AS: str = "AS"
    IN: str = "IN"
    ASSERT: str = "ASSERT"
    YIELD: str = "YIELD"
    DEFER: str = "DEFER"

    # 字面量
    INTEGER: str = "INTEGER"
    FLOAT_LITERAL: str = "FLOAT_LITERAL"
    STRING_LITERAL: str = "STRING_LITERAL"
    CHAR_LITERAL: str = "CHAR_LITERAL"

    # 标识符
    IDENTIFIER: str = "IDENTIFIER"

    # 运算符
    PLUS: str = "PLUS"            # +
    MINUS: str = "MINUS"          # -
    STAR: str = "STAR"            # *
    SLASH: str = "SLASH"          # /
    PERCENT: str = "PERCENT"      # %
    EQUAL: str = "EQUAL"          # =
    EQUAL_EQUAL: str = "EQUAL_EQUAL"  # ==
    NOT_EQUAL: str = "NOT_EQUAL"  # !=
    LESS: str = "LESS"            # <
    GREATER: str = "GREATER"      # >
    LESS_EQUAL: str = "LESS_EQUAL"  # <=
    GREATER_EQUAL: str = "GREATER_EQUAL"  # >=
    AND: str = "AND"              # &&
    OR: str = "OR"                # ||
    NOT: str = "NOT"              # !
    BIT_AND: str = "BIT_AND"      # &
    BIT_OR: str = "BIT_OR"        # |
    BIT_XOR: str = "BIT_XOR"      # ^
    BIT_NOT: str = "BIT_NOT"      # ~
    LEFT_SHIFT: str = "LEFT_SHIFT"  # <<
    RIGHT_SHIFT: str = "RIGHT_SHIFT"  # >>
    PLUS_EQUAL: str = "PLUS_EQUAL"  # +=
    MINUS_EQUAL: str = "MINUS_EQUAL"  # -=
    STAR_EQUAL: str = "STAR_EQUAL"  # *=
    SLASH_EQUAL: str = "SLASH_EQUAL"  # /=
    PERCENT_EQUAL: str = "PERCENT_EQUAL"  # %=
    AND_EQUAL: str = "AND_EQUAL"  # &=
    OR_EQUAL: str = "OR_EQUAL"    # |=
    XOR_EQUAL: str = "XOR_EQUAL"  # ^=
    LEFT_SHIFT_EQUAL: str = "LEFT_SHIFT_EQUAL"  # <<=
    RIGHT_SHIFT_EQUAL: str = "RIGHT_SHIFT_EQUAL"  # >>=
    PLUS_PLUS: str = "PLUS_PLUS"  # ++
    MINUS_MINUS: str = "MINUS_MINUS"  # --
    ARROW: str = "ARROW"          # ->
    FAT_ARROW: str = "FAT_ARROW"  # =>
    DOT: str = "DOT"              # .
    DOT_DOT: str = "DOT_DOT"      # ..
    COMMA: str = "COMMA"          # ,
    COLON: str = "COLON"          # :
    SEMICOLON: str = "SEMICOLON"  # ;
    COLON_COLON: str = "COLON_COLON"  # ::
    QUESTION: str = "QUESTION"    # ?
    AT: str = "AT"                # @
    HASH: str = "HASH"            # #
    DOLLAR: str = "DOLLAR"        # $
    UNDERSCORE: str = "UNDERSCORE"  # _
    PIPE: str = "PIPE"            # |>

    # 分隔符
    LPAREN: str = "LPAREN"        # (
    RPAREN: str = "RPAREN"        # )
    LBRACKET: str = "LBRACKET"    # [
    RBRACKET: str = "RBRACKET"    # ]
    LBRACE: str = "LBRACE"        # {
    RBRACE: str = "RBRACE"        # }

    # 特殊
    EOF: str = "EOF"
    INDENT: str = "INDENT"
    DEDENT: str = "DEDENT"
    NEWLINE: str = "NEWLINE"
    COMMENT: str = "COMMENT"

    # 类型注解
    TYPE_ANNOT: str = "TYPE_ANNOT"

    # 模式匹配
    PIPE_PATTERN: str = "PIPE_PATTERN"
    WILDCARD: str = "WILDCARD"    # _

    @classmethod
    def keywords(cls) -> dict[str, str]:
        """获取关键字映射表"""
        return {
            "let": cls.LET,
            "const": cls.CONST,
            "fn": cls.FN,
            "return": cls.RETURN,
            "if": cls.IF,
            "else": cls.ELSE,
            "while": cls.WHILE,
            "for": cls.FOR,
            "break": cls.BREAK,
            "continue": cls.CONTINUE,
            "class": cls.CLASS,
            "import": cls.IMPORT,
            "from": cls.FROM,
            "export": cls.EXPORT,
            "true": cls.TRUE,
            "false": cls.FALSE,
            "null": cls.NULL,
            "void": cls.VOID,
            "int": cls.INT,
            "float": cls.FLOAT,
            "bool": cls.BOOL,
            "string": cls.STRING,
            "array": cls.ARRAY,
            "record": cls.RECORD,
            "tensor": cls.TENSOR,
            "public": cls.PUBLIC,
            "private": cls.PRIVATE,
            "match": cls.MATCH,
            "lambda": cls.LAMBDA,
            "type": cls.TYPE,
            "mut": cls.MUT,
            "static": cls.STATIC,
            "extern": cls.EXTERN,
            "as": cls.AS,
            "in": cls.IN,
            "assert": cls.ASSERT,
            "yield": cls.YIELD,
            "defer": cls.DEFER,
        }

    @classmethod
    def is_keyword(cls, identifier: str) -> bool:
        """判断标识符是否为关键字"""
        return identifier in cls.keywords()

    @classmethod
    def binary_operators(cls) -> set[str]:
        """返回所有二元运算符"""
        return {
            cls.PLUS, cls.MINUS, cls.STAR, cls.SLASH, cls.PERCENT,
            cls.EQUAL_EQUAL, cls.NOT_EQUAL, cls.LESS, cls.GREATER,
            cls.LESS_EQUAL, cls.GREATER_EQUAL, cls.AND, cls.OR,
            cls.BIT_AND, cls.BIT_OR, cls.BIT_XOR,
            cls.LEFT_SHIFT, cls.RIGHT_SHIFT,
            cls.DOT, cls.DOT_DOT, cls.PIPE,
        }

    @classmethod
    def assignment_operators(cls) -> set[str]:
        """返回所有赋值运算符"""
        return {
            cls.EQUAL, cls.PLUS_EQUAL, cls.MINUS_EQUAL, cls.STAR_EQUAL,
            cls.SLASH_EQUAL, cls.PERCENT_EQUAL, cls.AND_EQUAL,
            cls.OR_EQUAL, cls.XOR_EQUAL, cls.LEFT_SHIFT_EQUAL,
            cls.RIGHT_SHIFT_EQUAL,
        }

    @classmethod
    def precedence(cls, token_type: str) -> int:
        """返回运算符优先级（值越大优先级越高）"""
        precedence_map = {
            cls.OR: 1,
            cls.AND: 2,
            cls.BIT_OR: 3,
            cls.BIT_XOR: 4,
            cls.BIT_AND: 5,
            cls.EQUAL_EQUAL: 6,
            cls.NOT_EQUAL: 6,
            cls.LESS: 7,
            cls.GREATER: 7,
            cls.LESS_EQUAL: 7,
            cls.GREATER_EQUAL: 7,
            cls.LEFT_SHIFT: 8,
            cls.RIGHT_SHIFT: 8,
            cls.PLUS: 9,
            cls.MINUS: 9,
            cls.STAR: 10,
            cls.SLASH: 10,
            cls.PERCENT: 10,
            cls.PIPE: 11,
            cls.DOT: 12,
            cls.DOT_DOT: 12,
        }
        return precedence_map.get(token_type, 0)


@dataclass
class Token:
    """Token 数据结构"""
    type: str
    value: Any
    line: int
    column: int
    file: str = ""

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, line={self.line}, col={self.column})"

    def __str__(self) -> str:
        if self.type == TokenType.EOF:
            return "<EOF>"
        return f"<{self.type}: {self.value!r}>"

    @property
    def is_keyword(self) -> bool:
        """是否为关键字"""
        return TokenType.is_keyword(self.value) if self.type == TokenType.IDENTIFIER else False

    @property
    def is_operator(self) -> bool:
        """是否为运算符"""
        return self.type in TokenType.binary_operators() or self.type in TokenType.assignment_operators()

    @property
    def is_literal(self) -> bool:
        """是否为字面量"""
        return self.type in {
            TokenType.INTEGER, TokenType.FLOAT_LITERAL,
            TokenType.STRING_LITERAL, TokenType.CHAR_LITERAL,
            TokenType.TRUE, TokenType.FALSE, TokenType.NULL,
        }

    @property
    def precedence(self) -> int:
        """获取运算符优先级"""
        return TokenType.precedence(self.type)


# 运算符与字符串映射
OPERATOR_STRINGS: dict[str, str] = {
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "*": TokenType.STAR,
    "/": TokenType.SLASH,
    "%": TokenType.PERCENT,
    "=": TokenType.EQUAL,
    "==": TokenType.EQUAL_EQUAL,
    "!=": TokenType.NOT_EQUAL,
    "<": TokenType.LESS,
    ">": TokenType.GREATER,
    "<=": TokenType.LESS_EQUAL,
    ">=": TokenType.GREATER_EQUAL,
    "&&": TokenType.AND,
    "||": TokenType.OR,
    "!": TokenType.NOT,
    "&": TokenType.BIT_AND,
    "|": TokenType.BIT_OR,
    "^": TokenType.BIT_XOR,
    "~": TokenType.BIT_NOT,
    "<<": TokenType.LEFT_SHIFT,
    ">>": TokenType.RIGHT_SHIFT,
    "+=": TokenType.PLUS_EQUAL,
    "-=": TokenType.MINUS_EQUAL,
    "*=": TokenType.STAR_EQUAL,
    "/=": TokenType.SLASH_EQUAL,
    "%=": TokenType.PERCENT_EQUAL,
    "&=": TokenType.AND_EQUAL,
    "|=": TokenType.OR_EQUAL,
    "^=": TokenType.XOR_EQUAL,
    "<<=": TokenType.LEFT_SHIFT_EQUAL,
    ">>=": TokenType.RIGHT_SHIFT_EQUAL,
    "++": TokenType.PLUS_PLUS,
    "--": TokenType.MINUS_MINUS,
    "->": TokenType.ARROW,
    "=>": TokenType.FAT_ARROW,
    ".": TokenType.DOT,
    "..": TokenType.DOT_DOT,
    ",": TokenType.COMMA,
    ":": TokenType.COLON,
    ";": TokenType.SEMICOLON,
    "::": TokenType.COLON_COLON,
    "?": TokenType.QUESTION,
    "@": TokenType.AT,
    "#": TokenType.HASH,
    "$": TokenType.DOLLAR,
    "_": TokenType.UNDERSCORE,
    "|>": TokenType.PIPE,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    "[": TokenType.LBRACKET,
    "]": TokenType.RBRACKET,
    "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,
}


def token_type_to_string(token_type: str) -> str:
    """将 Token 类型转换为可读字符串"""
    reverse_map = {v: k for k, v in OPERATOR_STRINGS.items()}
    if token_type in reverse_map:
        return f"'{reverse_map[token_type]}'"
    return token_type.lower()