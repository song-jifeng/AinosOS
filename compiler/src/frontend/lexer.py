"""
AI 编译器工具链 - 词法分析器
"""

from __future__ import annotations

from typing import Optional

from src.frontend.token import Token, TokenType, OPERATOR_STRINGS
from src.utils.errors import LexerError, ErrorReporter


class Lexer:
    """词法分析器 - 将源代码转换为 Token 流"""

    def __init__(self, source: str, file: str = "", error_reporter: Optional[ErrorReporter] = None):
        self.source: str = source
        self.file: str = file
        self.error_reporter: ErrorReporter = error_reporter or ErrorReporter()
        self.pos: int = 0
        self.line: int = 1
        self.column: int = 1
        self.tokens: list[Token] = []
        self._token_start: int = 0  # 当前 token 开始位置

        # 关键字映射
        self._keywords: dict[str, str] = TokenType.keywords()

    def tokenize(self) -> list[Token]:
        """执行词法分析，返回 Token 列表"""
        self.tokens = []
        while self.pos < len(self.source):
            self._token_start = self.pos
            ch = self._peek()

            if ch.isspace():
                self._skip_whitespace()
            elif ch == '/' and self._peek_next() == '/':
                self._skip_line_comment()
            elif ch == '/' and self._peek_next() == '*':
                self._skip_block_comment()
            elif ch == '"' or ch == "'":
                self._read_string(ch)
            elif ch.isdigit():
                self._read_number()
            elif ch.isalpha() or ch == '_':
                self._read_identifier()
            elif ch == '#':
                self._read_hash_comment()
            else:
                self._read_operator_or_delimiter()

        self.tokens.append(Token(TokenType.EOF, None, self.line, self.column, self.file))
        return self.tokens

    def _peek(self) -> str:
        """查看当前字符"""
        if self.pos < len(self.source):
            return self.source[self.pos]
        return '\0'

    def _peek_next(self) -> str:
        """查看下一个字符"""
        if self.pos + 1 < len(self.source):
            return self.source[self.pos + 1]
        return '\0'

    def _advance(self) -> str:
        """前进一个字符，返回该字符"""
        ch = self.source[self.pos]
        self.pos += 1
        if ch == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _skip_whitespace(self) -> None:
        """跳过空白字符"""
        while self.pos < len(self.source) and self.source[self.pos].isspace():
            self._advance()

    def _skip_line_comment(self) -> None:
        """跳过行注释 // ..."""
        while self.pos < len(self.source) and self.source[self.pos] != '\n':
            self._advance()

    def _skip_block_comment(self) -> None:
        """跳过块注释 /* ... */"""
        self._advance()  # 跳过 *
        self._advance()  # 跳过 /
        while self.pos < len(self.source):
            if self.source[self.pos] == '*' and self._peek_next() == '/':
                self._advance()  # 跳过 *
                self._advance()  # 跳过 /
                return
            self._advance()
        # 未闭合的块注释
        self.error_reporter.report_error(
            LexerError("未闭合的块注释", self.line, self.column, self.file)
        )

    def _read_hash_comment(self) -> None:
        """跳过 Hash 注释 # ..."""
        while self.pos < len(self.source) and self.source[self.pos] != '\n':
            self._advance()

    def _read_string(self, quote: str) -> None:
        """读取字符串字面量"""
        start_line = self.line
        start_col = self.column
        self._advance()  # 跳过开头的引号
        value_parts = []

        while self.pos < len(self.source):
            ch = self._advance()
            if ch == '\\':
                # 转义字符
                if self.pos < len(self.source):
                    esc = self._advance()
                    if esc == 'n':
                        value_parts.append('\n')
                    elif esc == 't':
                        value_parts.append('\t')
                    elif esc == 'r':
                        value_parts.append('\r')
                    elif esc == '\\':
                        value_parts.append('\\')
                    elif esc == '"':
                        value_parts.append('"')
                    elif esc == "'":
                        value_parts.append("'")
                    elif esc == '0':
                        value_parts.append('\0')
                    elif esc == 'x':
                        # 十六进制转义 \xNN
                        hex_str = ""
                        for _ in range(2):
                            if self.pos < len(self.source) and self.source[self.pos].isalnum():
                                hex_str += self._advance()
                            else:
                                break
                        if hex_str:
                            value_parts.append(chr(int(hex_str, 16)))
                        else:
                            value_parts.append('\\x')
                    elif esc == 'u':
                        # Unicode 转义 \uNNNN
                        uni_str = ""
                        for _ in range(4):
                            if self.pos < len(self.source) and self.source[self.pos].isalnum():
                                uni_str += self._advance()
                            else:
                                break
                        if uni_str:
                            value_parts.append(chr(int(uni_str, 16)))
                        else:
                            value_parts.append('\\u')
                    else:
                        value_parts.append(esc)
            elif ch == quote:
                # 闭合引号
                token_type = TokenType.STRING_LITERAL if quote == '"' else TokenType.CHAR_LITERAL
                value = ''.join(value_parts)
                # 字符字面量限制
                if token_type == TokenType.CHAR_LITERAL and len(value) > 1:
                    self.error_reporter.report_error(
                        LexerError("字符字面量只能包含一个字符", start_line, start_col, self.file)
                    )
                self.tokens.append(Token(token_type, value, start_line, start_col, self.file))
                return
            else:
                value_parts.append(ch)
        # 未闭合的字符串
        self.error_reporter.report_error(
            LexerError("未闭合的字符串字面量", start_line, start_col, self.file)
        )

    def _read_number(self) -> None:
        """读取数字字面量"""
        start_line = self.line
        start_col = self.column
        num_str = ""
        is_float = False

        # 检测进制前缀
        if self._peek() == '0' and self.pos + 1 < len(self.source):
            next_ch = self.source[self.pos + 1].lower()
            if next_ch == 'x':
                # 十六进制
                self._advance()  # 0
                self._advance()  # x
                num_str = "0x"
                while self.pos < len(self.source) and (self.source[self.pos].isdigit() or self.source[self.pos].lower() in 'abcdef'):
                    num_str += self._advance()
                if num_str == "0x":
                    self.error_reporter.report_error(
                        LexerError("无效的十六进制字面量", start_line, start_col, self.file)
                    )
                    return
                value = int(num_str, 16)
                self.tokens.append(Token(TokenType.INTEGER, value, start_line, start_col, self.file))
                return
            elif next_ch == 'b':
                # 二进制
                self._advance()  # 0
                self._advance()  # b
                num_str = ""
                while self.pos < len(self.source) and self.source[self.pos] in '01':
                    num_str += self._advance()
                if not num_str:
                    self.error_reporter.report_error(
                        LexerError("无效的二进制字面量", start_line, start_col, self.file)
                    )
                    return
                value = int(num_str, 2)
                self.tokens.append(Token(TokenType.INTEGER, value, start_line, start_col, self.file))
                return
            elif next_ch == 'o':
                # 八进制
                self._advance()  # 0
                self._advance()  # o
                num_str = ""
                while self.pos < len(self.source) and self.source[self.pos] in '01234567':
                    num_str += self._advance()
                if not num_str:
                    self.error_reporter.report_error(
                        LexerError("无效的八进制字面量", start_line, start_col, self.file)
                    )
                    return
                value = int(num_str, 8)
                self.tokens.append(Token(TokenType.INTEGER, value, start_line, start_col, self.file))
                return

        # 十进制数字
        while self.pos < len(self.source) and self.source[self.pos].isdigit():
            num_str += self._advance()

        # 检查浮点数 (小数点或指数)
        if self.pos < len(self.source) and self.source[self.pos] == '.':
            next_ch = self._peek_next()
            if next_ch.isdigit():
                is_float = True
                num_str += self._advance()  # .
                while self.pos < len(self.source) and self.source[self.pos].isdigit():
                    num_str += self._advance()
            elif next_ch != '.' and next_ch != '_' and not next_ch.isalpha():
                # 单独的小数点可能是方法调用，暂时不处理
                pass

        # 指数部分
        if self.pos < len(self.source) and self.source[self.pos].lower() == 'e':
            is_float = True
            num_str += self._advance()  # e
            if self.pos < len(self.source) and self.source[self.pos] in '+-':
                num_str += self._advance()
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                num_str += self._advance()

        if is_float:
            try:
                value = float(num_str)
            except ValueError:
                self.error_reporter.report_error(
                    LexerError(f"无效的浮点数字面量: {num_str}", start_line, start_col, self.file)
                )
                return
            self.tokens.append(Token(TokenType.FLOAT_LITERAL, value, start_line, start_col, self.file))
        else:
            try:
                value = int(num_str)
            except ValueError:
                self.error_reporter.report_error(
                    LexerError(f"无效的整数字面量: {num_str}", start_line, start_col, self.file)
                )
                return
            self.tokens.append(Token(TokenType.INTEGER, value, start_line, start_col, self.file))

    def _read_identifier(self) -> None:
        """读取标识符或关键字"""
        start_line = self.line
        start_col = self.column
        ident = ""

        while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] == '_'):
            ident += self._advance()

        # 检查是否为关键字
        if ident in self._keywords:
            token_type = self._keywords[ident]
            if token_type == TokenType.TRUE:
                self.tokens.append(Token(token_type, True, start_line, start_col, self.file))
            elif token_type == TokenType.FALSE:
                self.tokens.append(Token(token_type, False, start_line, start_col, self.file))
            elif token_type == TokenType.NULL:
                self.tokens.append(Token(token_type, None, start_line, start_col, self.file))
            else:
                self.tokens.append(Token(token_type, ident, start_line, start_col, self.file))
        else:
            self.tokens.append(Token(TokenType.IDENTIFIER, ident, start_line, start_col, self.file))

    def _read_operator_or_delimiter(self) -> None:
        """读取运算符或分隔符"""
        start_line = self.line
        start_col = self.column

        # 多字符运算符
        two_char = self.source[self.pos:self.pos + 2] if self.pos + 1 < len(self.source) else ""
        three_char = self.source[self.pos:self.pos + 3] if self.pos + 2 < len(self.source) else ""

        # 优先匹配三字符运算符
        if three_char in OPERATOR_STRINGS:
            op_type = OPERATOR_STRINGS[three_char]
            for _ in range(3):
                self._advance()
            self.tokens.append(Token(op_type, three_char, start_line, start_col, self.file))
            return

        # 匹配两字符运算符
        if two_char in OPERATOR_STRINGS:
            op_type = OPERATOR_STRINGS[two_char]
            for _ in range(2):
                self._advance()
            self.tokens.append(Token(op_type, two_char, start_line, start_col, self.file))
            return

        # 单字符运算符或分隔符
        ch = self.source[self.pos]
        if ch in OPERATOR_STRINGS:
            op_type = OPERATOR_STRINGS[ch]
            self._advance()
            self.tokens.append(Token(op_type, ch, start_line, start_col, self.file))
        else:
            # 未知字符
            self.error_reporter.report_error(
                LexerError(f"无法识别的字符: '{ch}' (0x{ord(ch):04x})", self.line, self.column, self.file)
            )
            self._advance()


class LexerHelper:
    """词法分析辅助工具"""

    @staticmethod
    def tokenize_file(filepath: str, error_reporter: Optional[ErrorReporter] = None) -> list[Token]:
        """从文件读取并词法分析"""
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        lexer = Lexer(source, filepath, error_reporter)
        return lexer.tokenize()

    @staticmethod
    def is_valid_identifier(name: str) -> bool:
        """检查标识符是否有效"""
        if not name:
            return False
        if name[0].isdigit():
            return False
        if TokenType.is_keyword(name):
            return False
        return all(c.isalnum() or c == '_' for c in name)

    @staticmethod
    def tokens_to_string(tokens: list[Token]) -> str:
        """将 Token 列表转换为可读字符串"""
        lines = []
        for token in tokens:
            if token.type == TokenType.EOF:
                lines.append(f"  {token.line}:{token.column}  <EOF>")
            else:
                lines.append(f"  {token.line}:{token.column}  {token.type:20s}  {token.value!r}")
        return "\n".join(lines)