"""SQL parser for AinosDB.

Implements a recursive descent parser for a subset of SQL,
producing an AST (Abstract Syntax Tree) for further processing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


class TokenType(Enum):
    """Types of tokens in SQL."""
    KEYWORD = auto()
    IDENTIFIER = auto()
    NUMBER = auto()
    STRING = auto()
    OPERATOR = auto()
    PUNCTUATION = auto()
    EOF = auto()


class Keyword(Enum):
    """SQL keywords."""
    SELECT = "SELECT"
    FROM = "FROM"
    WHERE = "WHERE"
    INSERT = "INSERT"
    INTO = "INTO"
    VALUES = "VALUES"
    UPDATE = "UPDATE"
    SET = "SET"
    DELETE = "DELETE"
    CREATE = "CREATE"
    TABLE = "TABLE"
    DATABASE = "DATABASE"
    DROP = "DROP"
    ALTER = "ALTER"
    ADD = "ADD"
    COLUMN = "COLUMN"
    PRIMARY = "PRIMARY"
    KEY = "KEY"
    NOT = "NOT"
    NULL = "NULL"
    DEFAULT = "DEFAULT"
    UNIQUE = "UNIQUE"
    INDEX = "INDEX"
    AND = "AND"
    OR = "OR"
    IN = "IN"
    LIKE = "LIKE"
    BETWEEN = "BETWEEN"
    IS = "IS"
    TRUE = "TRUE"
    FALSE = "FALSE"
    AS = "AS"
    ON = "ON"
    JOIN = "JOIN"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    INNER = "INNER"
    OUTER = "OUTER"
    CROSS = "CROSS"
    FULL = "FULL"
    ORDER = "ORDER"
    BY = "BY"
    ASC = "ASC"
    DESC = "DESC"
    LIMIT = "LIMIT"
    OFFSET = "OFFSET"
    GROUP = "GROUP"
    HAVING = "HAVING"
    DISTINCT = "DISTINCT"
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"
    EXISTS = "EXISTS"
    CASE = "CASE"
    WHEN = "WHEN"
    THEN = "THEN"
    ELSE = "ELSE"
    END = "END"
    USE = "USE"
    SHOW = "SHOW"
    EXPLAIN = "EXPLAIN"
    BEGIN = "BEGIN"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"
    TRANSACTION = "TRANSACTION"
    VECTOR = "VECTOR"
    DOCUMENT = "DOCUMENT"


# Map of keyword strings to Keyword enum
_KEYWORD_MAP: Dict[str, Keyword] = {kw.value: kw for kw in Keyword}


class Token:
    """A single token from the SQL source.

    Attributes:
        token_type: Type of token.
        value: Token value (string, number, etc.).
        keyword: Keyword enum if type is KEYWORD.
        position: Position in source (line, column).
    """

    __slots__ = ("token_type", "value", "keyword", "line", "column")

    def __init__(
        self,
        token_type: TokenType,
        value: str,
        keyword: Optional[Keyword] = None,
        line: int = 0,
        column: int = 0,
    ) -> None:
        self.token_type = token_type
        self.value = value
        self.keyword = keyword
        self.line = line
        self.column = column

    def __repr__(self) -> str:
        if self.token_type == TokenType.KEYWORD:
            return f"KW({self.value})"
        return f"{self.token_type.name}({self.value})"


# --- AST Nodes ---

class ASTNode(ABC):
    """Base class for all AST nodes."""

    @abstractmethod
    def __repr__(self) -> str:
        ...


@dataclass
class ColumnDef:
    """Column definition in CREATE TABLE."""
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    default: Optional[Any] = None


@dataclass
class Expression(ASTNode):
    """A SQL expression."""
    pass


@dataclass
class LiteralExpression(Expression):
    """A literal value (number, string, boolean, null)."""
    value: Any

    def __repr__(self) -> str:
        return f"Literal({self.value!r})"


@dataclass
class ColumnExpression(Expression):
    """A column reference."""
    name: str
    table_name: Optional[str] = None

    def __repr__(self) -> str:
        if self.table_name:
            return f"Column({self.table_name}.{self.name})"
        return f"Column({self.name})"


@dataclass
class BinaryExpression(Expression):
    """A binary operation (e.g., a + b, a = b)."""
    operator: str
    left: Expression
    right: Expression

    def __repr__(self) -> str:
        return f"Binary({self.left} {self.operator} {self.right})"


@dataclass
class UnaryExpression(Expression):
    """A unary operation (e.g., NOT a, -a)."""
    operator: str
    operand: Expression

    def __repr__(self) -> str:
        return f"Unary({self.operator} {self.operand})"


@dataclass
class FunctionCall(Expression):
    """A function call (e.g., COUNT(*), SUM(x))."""
    name: str
    args: List[Expression]
    distinct: bool = False

    def __repr__(self) -> str:
        return f"Func({self.name}({self.args}))"


@dataclass
class BetweenExpression(Expression):
    """BETWEEN expression."""
    expr: Expression
    low: Expression
    high: Expression

    def __repr__(self) -> str:
        return f"Between({self.expr} BETWEEN {self.low} AND {self.high})"


@dataclass
class InExpression(Expression):
    """IN expression."""
    expr: Expression
    values: List[Expression]

    def __repr__(self) -> str:
        return f"In({self.expr} IN {self.values})"


@dataclass
class LikeExpression(Expression):
    """LIKE expression."""
    expr: Expression
    pattern: Expression

    def __repr__(self) -> str:
        return f"Like({self.expr} LIKE {self.pattern})"


@dataclass
class CaseExpression(Expression):
    """CASE WHEN ... THEN ... ELSE ... END expression."""
    conditions: List[Expression]
    results: List[Expression]
    else_result: Optional[Expression] = None

    def __repr__(self) -> str:
        return f"CASE({self.conditions}...{self.else_result})"


@dataclass
class StarExpression(Expression):
    """SELECT * expression."""
    table_name: Optional[str] = None

    def __repr__(self) -> str:
        if self.table_name:
            return f"Star({self.table_name}.*)"
        return "Star(*)"


@dataclass
class SubqueryExpression(Expression):
    """A subquery in an expression."""
    statement: "SelectStatement"

    def __repr__(self) -> str:
        return f"Subquery({self.statement})"


@dataclass
class JoinClause:
    """A JOIN clause in a SELECT statement."""
    join_type: str  # INNER, LEFT, RIGHT, FULL, CROSS
    table_name: str
    table_alias: Optional[str] = None
    on_condition: Optional[Expression] = None


@dataclass
class OrderByItem:
    """An ORDER BY item."""
    expression: Expression
    direction: str = "ASC"  # ASC or DESC


@dataclass
class Statement(ASTNode):
    """Base class for SQL statements."""
    pass


@dataclass
class SelectStatement(Statement):
    """SELECT statement."""
    columns: List[Expression]
    from_table: Optional[str] = None
    from_alias: Optional[str] = None
    joins: List[JoinClause] = field(default_factory=list)
    where_clause: Optional[Expression] = None
    group_by: List[Expression] = field(default_factory=list)
    having: Optional[Expression] = None
    order_by: List[OrderByItem] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None
    distinct: bool = False

    def __repr__(self) -> str:
        return f"SELECT({self.columns} FROM {self.from_table})"


@dataclass
class InsertStatement(Statement):
    """INSERT statement."""
    table_name: str
    columns: List[str] = field(default_factory=list)
    values: List[List[Expression]] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"INSERT INTO {self.table_name}"


@dataclass
class CreateStatement(Statement):
    """CREATE statement (TABLE, DATABASE, INDEX)."""
    object_type: str  # TABLE, DATABASE, INDEX
    name: str
    columns: List[ColumnDef] = field(default_factory=list)
    if_not_exists: bool = False

    def __repr__(self) -> str:
        return f"CREATE {self.object_type} {self.name}"


@dataclass
class DropStatement(Statement):
    """DROP statement (TABLE, DATABASE)."""
    object_type: str
    name: str
    if_exists: bool = False


@dataclass
class DeleteStatement(Statement):
    """DELETE statement."""
    table_name: str
    where_clause: Optional[Expression] = None

    def __repr__(self) -> str:
        return f"DELETE FROM {self.table_name}"


@dataclass
class UpdateStatement(Statement):
    """UPDATE statement."""
    table_name: str
    set_clauses: List[Tuple[str, Expression]] = field(default_factory=list)
    where_clause: Optional[Expression] = None

    def __repr__(self) -> str:
        return f"UPDATE {self.table_name}"


@dataclass
class AlterStatement(Statement):
    """ALTER TABLE statement."""
    table_name: str
    action: str  # ADD COLUMN, DROP COLUMN
    column: Optional[ColumnDef] = None
    column_name: Optional[str] = None


@dataclass
class UseStatement(Statement):
    """USE database statement."""
    database_name: str


@dataclass
class ShowStatement(Statement):
    """SHOW statement (DATABASES, TABLES)."""
    object_type: str


@dataclass
class TransactionStatement(Statement):
    """BEGIN, COMMIT, ROLLBACK statements."""
    action: str  # BEGIN, COMMIT, ROLLBACK


@dataclass
class ExplainStatement(Statement):
    """EXPLAIN statement."""
    statement: Statement


# --- Lexer ---

class SQLLexer:
    """Lexer that tokenizes SQL source text.

    Attributes:
        source: SQL source string.
        pos: Current position in source.
        line: Current line number.
        column: Current column number.
    """

    __slots__ = ("source", "pos", "line", "column", "tokens")

    SINGLE_CHAR_TOKENS = {
        "+": "PLUS", "-": "MINUS", "*": "STAR", "/": "DIV",
        "=": "EQ", "<": "LT", ">": "GT", "(": "LPAREN",
        ")": "RPAREN", ",": "COMMA", ";": "SEMICOLON",
        ".": "DOT",
    }

    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []

    def tokenize(self) -> List[Token]:
        """Tokenize the entire source string.

        Returns:
            List of tokens.
        """
        self.tokens = []
        while self.pos < len(self.source):
            char = self.source[self.pos]

            # Skip whitespace
            if char in " \t\r":
                self._advance()
                continue

            # Newlines
            if char == "\n":
                self.line += 1
                self.column = 1
                self.pos += 1
                continue

            # Comments
            if char == "-" and self._peek(1) == "-":
                self._skip_line()
                continue
            if char == "/" and self._peek(1) == "*":
                self._skip_block_comment()
                continue

            # Single-character tokens
            if char in self.SINGLE_CHAR_TOKENS:
                # Check for two-character operators
                if char == "<" and self._peek(1) == "=":
                    self.tokens.append(self._make_token(TokenType.OPERATOR, "<="))
                    self._advance(2)
                elif char == ">" and self._peek(1) == "=":
                    self.tokens.append(self._make_token(TokenType.OPERATOR, ">="))
                    self._advance(2)
                elif char == "!" and self._peek(1) == "=":
                    self.tokens.append(self._make_token(TokenType.OPERATOR, "!="))
                    self._advance(2)
                else:
                    self.tokens.append(self._make_token(TokenType.OPERATOR, char))
                    self._advance()
                continue

            # Numbers
            if char.isdigit() or (char == "." and self._peek(1).isdigit()):
                self.tokens.append(self._read_number())
                continue

            # Strings
            if char in ("'", '"'):
                self.tokens.append(self._read_string(char))
                continue

            # Identifiers and keywords
            if char.isalpha() or char == "_":
                self.tokens.append(self._read_identifier())
                continue

            raise SyntaxError(
                f"Unexpected character '{char}' at line {self.line}, column {self.column}"
            )

        self.tokens.append(Token(TokenType.EOF, "", line=self.line, column=self.column))
        return self.tokens

    def _advance(self, count: int = 1) -> None:
        self.pos += count
        self.column += count

    def _peek(self, ahead: int = 0) -> str:
        idx = self.pos + ahead
        if idx < len(self.source):
            return self.source[idx]
        return ""

    def _make_token(self, token_type: TokenType, value: str) -> Token:
        token = Token(
            token_type, value, line=self.line,
            column=self.column - len(value) + 1
        )
        if token_type == TokenType.IDENTIFIER:
            upper = value.upper()
            if upper in _KEYWORD_MAP:
                token.token_type = TokenType.KEYWORD
                token.keyword = _KEYWORD_MAP[upper]
        return token

    def _skip_line(self) -> None:
        while self.pos < len(self.source) and self.source[self.pos] != "\n":
            self._advance()

    def _skip_block_comment(self) -> None:
        self._advance(2)
        while self.pos < len(self.source):
            if self.source[self.pos] == "*" and self._peek(1) == "/":
                self._advance(2)
                return
            if self.source[self.pos] == "\n":
                self.line += 1
                self.column = 1
            self._advance()

    def _read_number(self) -> Token:
        start = self.pos
        is_float = False
        while self.pos < len(self.source) and (
            self.source[self.pos].isdigit() or self.source[self.pos] == "."
        ):
            if self.source[self.pos] == ".":
                if is_float:
                    break
                is_float = True
            self._advance()

        return Token(TokenType.NUMBER, self.source[start:self.pos])

    def _read_string(self, quote: str) -> Token:
        self._advance()  # Skip opening quote
        start = self.pos
        while self.pos < len(self.source) and self.source[self.pos] != quote:
            if self.source[self.pos] == "\\":
                self._advance()
            self._advance()

        value = self.source[start:self.pos]
        self._advance()  # Skip closing quote
        return Token(TokenType.STRING, value)

    def _read_identifier(self) -> Token:
        start = self.pos
        while self.pos < len(self.source) and (
            self.source[self.pos].isalnum() or self.source[self.pos] == "_"
        ):
            self._advance()

        value = self.source[start:self.pos]
        upper = value.upper()
        if upper in _KEYWORD_MAP:
            return Token(TokenType.KEYWORD, value, _KEYWORD_MAP[upper])
        return Token(TokenType.IDENTIFIER, value)


# --- Parser ---

class Parser:
    """Recursive descent parser for SQL.

    Transforms a token stream into an AST (Abstract Syntax Tree).

    Attributes:
        tokens: List of tokens to parse.
        pos: Current position in token stream.
    """

    __slots__ = ("tokens", "pos")

    def __init__(self, tokens: List[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> Statement:
        """Parse a single SQL statement.

        Returns:
            AST for the statement.

        Raises:
            SyntaxError: If the SQL is malformed.
        """
        if self._peek().token_type == TokenType.EOF:
            raise SyntaxError("Empty SQL statement")

        token = self._peek()
        if token.token_type != TokenType.KEYWORD:
            raise SyntaxError(f"Expected a keyword, got {token}")

        keyword = token.keyword

        if keyword == Keyword.SELECT:
            return self._parse_select()
        elif keyword == Keyword.INSERT:
            return self._parse_insert()
        elif keyword == Keyword.CREATE:
            return self._parse_create()
        elif keyword == Keyword.DROP:
            return self._parse_drop()
        elif keyword == Keyword.DELETE:
            return self._parse_delete()
        elif keyword == Keyword.UPDATE:
            return self._parse_update()
        elif keyword == Keyword.ALTER:
            return self._parse_alter()
        elif keyword == Keyword.USE:
            return self._parse_use()
        elif keyword == Keyword.SHOW:
            return self._parse_show()
        elif keyword in (Keyword.BEGIN, Keyword.COMMIT, Keyword.ROLLBACK):
            return self._parse_transaction()
        elif keyword == Keyword.EXPLAIN:
            return self._parse_explain()
        else:
            raise SyntaxError(f"Unexpected keyword: {keyword.value}")

    @classmethod
    def parse_sql(cls, sql: str) -> Statement:
        """Parse a SQL string into an AST.

        Args:
            sql: SQL statement string.

        Returns:
            AST for the statement.
        """
        lexer = SQLLexer(sql)
        tokens = lexer.tokenize()
        parser = cls(tokens)
        return parser.parse()

    def _peek(self, ahead: int = 0) -> Token:
        idx = self.pos + ahead
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token(TokenType.EOF, "")

    def _advance(self) -> Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _expect(self, token_type: TokenType, value: Optional[str] = None) -> Token:
        """Expect and consume a token of a specific type.

        Args:
            token_type: Expected token type.
            value: Optional expected value.

        Returns:
            The consumed token.

        Raises:
            SyntaxError: If the token doesn't match.
        """
        token = self._peek()
        if token.token_type != token_type:
            raise SyntaxError(
                f"Expected {token_type.name}, got {token.token_type.name} ('{token.value}') "
                f"at line {token.line}"
            )
        if value is not None and token.value.upper() != value.upper():
            raise SyntaxError(
                f"Expected '{value}', got '{token.value}' at line {token.line}"
            )
        return self._advance()

    def _expect_keyword(self, keyword: Keyword) -> Token:
        """Expect and consume a specific keyword.

        Args:
            keyword: Expected keyword.

        Returns:
            The consumed token.
        """
        token = self._peek()
        if token.token_type != TokenType.KEYWORD or token.keyword != keyword:
            raise SyntaxError(
                f"Expected '{keyword.value}', got '{token.value}' at line {token.line}"
            )
        return self._advance()

    def _maybe_keyword(self, keyword: Keyword) -> bool:
        """Check if the next token is a keyword and consume it if so.

        Args:
            keyword: Keyword to check for.

        Returns:
            True if the keyword was consumed.
        """
        if (self._peek().token_type == TokenType.KEYWORD and
                self._peek().keyword == keyword):
            self._advance()
            return True
        return False

    def _parse_select(self) -> SelectStatement:
        """Parse a SELECT statement."""
        self._advance()  # SELECT

        distinct = self._maybe_keyword(Keyword.DISTINCT)

        # Parse columns
        columns = self._parse_select_columns()

        # FROM clause
        from_table = None
        from_alias = None
        if self._maybe_keyword(Keyword.FROM):
            from_table = self._expect(TokenType.IDENTIFIER).value
            # Optional alias
            if self._maybe_keyword(Keyword.AS):
                from_alias = self._expect(TokenType.IDENTIFIER).value
            elif self._peek().token_type == TokenType.IDENTIFIER and self._peek().value.upper() not in (
                "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "FULL",
                "ORDER", "GROUP", "LIMIT", "HAVING", "ON",
            ):
                from_alias = self._advance().value

        # JOINs
        joins = []
        while self._peek().token_type == TokenType.KEYWORD and self._peek().keyword in (
            Keyword.JOIN, Keyword.LEFT, Keyword.RIGHT, Keyword.INNER, Keyword.OUTER, Keyword.CROSS, Keyword.FULL
        ):
            joins.append(self._parse_join())

        # WHERE clause
        where_clause = None
        if self._maybe_keyword(Keyword.WHERE):
            where_clause = self._parse_expression()

        # GROUP BY
        group_by = []
        if self._maybe_keyword(Keyword.GROUP):
            self._expect_keyword(Keyword.BY)
            group_by = self._parse_expression_list()

        # HAVING
        having = None
        if self._maybe_keyword(Keyword.HAVING):
            having = self._parse_expression()

        # ORDER BY
        order_by = []
        if self._maybe_keyword(Keyword.ORDER):
            self._expect_keyword(Keyword.BY)
            order_by = self._parse_order_by()

        # LIMIT
        limit = None
        if self._maybe_keyword(Keyword.LIMIT):
            limit = int(self._expect(TokenType.NUMBER).value)

        # OFFSET
        offset = None
        if self._maybe_keyword(Keyword.OFFSET):
            offset = int(self._expect(TokenType.NUMBER).value)

        return SelectStatement(
            columns=columns,
            from_table=from_table,
            from_alias=from_alias,
            joins=joins,
            where_clause=where_clause,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            offset=offset,
            distinct=distinct,
        )

    def _parse_select_columns(self) -> List[Expression]:
        """Parse the column list in a SELECT statement."""
        columns = []
        while True:
            if self._peek().token_type == TokenType.OPERATOR and self._peek().value == "*":
                self._advance()
                columns.append(StarExpression())
            else:
                columns.append(self._parse_expression())
                if self._maybe_keyword(Keyword.AS):
                    # Alias is consumed but we could store it
                    self._expect(TokenType.IDENTIFIER)

            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                continue
            break

        return columns

    def _parse_join(self) -> JoinClause:
        """Parse a JOIN clause."""
        join_type = "INNER"
        if self._peek().keyword in (Keyword.LEFT, Keyword.RIGHT, Keyword.FULL, Keyword.CROSS):
            side = self._advance().value.upper()
            if self._maybe_keyword(Keyword.OUTER):
                join_type = side
            elif self._maybe_keyword(Keyword.INNER):
                join_type = side
            elif side == "CROSS":
                join_type = "CROSS"
            else:
                join_type = side

        self._maybe_keyword(Keyword.JOIN)  # consume JOIN keyword if present

        table_name = self._expect(TokenType.IDENTIFIER).value

        table_alias = None
        if self._maybe_keyword(Keyword.AS):
            table_alias = self._expect(TokenType.IDENTIFIER).value

        on_condition = None
        if self._maybe_keyword(Keyword.ON):
            on_condition = self._parse_expression()

        return JoinClause(
            join_type=join_type,
            table_name=table_name,
            table_alias=table_alias,
            on_condition=on_condition,
        )

    def _parse_order_by(self) -> List[OrderByItem]:
        """Parse ORDER BY clause."""
        items = []
        while True:
            expr = self._parse_expression()
            direction = "ASC"
            if self._maybe_keyword(Keyword.DESC):
                direction = "DESC"
            elif self._maybe_keyword(Keyword.ASC):
                direction = "ASC"
            items.append(OrderByItem(expr, direction))

            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                continue
            break

        return items

    def _parse_insert(self) -> InsertStatement:
        """Parse an INSERT statement."""
        self._advance()  # INSERT
        self._expect_keyword(Keyword.INTO)
        table_name = self._expect(TokenType.IDENTIFIER).value

        # Optional column list
        columns = []
        if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == "(":
            self._advance()
            columns = [self._expect(TokenType.IDENTIFIER).value]
            while self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                columns.append(self._expect(TokenType.IDENTIFIER).value)
            self._expect(TokenType.PUNCTUATION, ")")

        self._expect_keyword(Keyword.VALUES)

        # Parse value rows
        values = []
        while True:
            self._expect(TokenType.PUNCTUATION, "(")
            row = []
            row.append(self._parse_expression())
            while self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                row.append(self._parse_expression())
            self._expect(TokenType.PUNCTUATION, ")")
            values.append(row)

            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                continue
            break

        return InsertStatement(
            table_name=table_name,
            columns=columns,
            values=values,
        )

    def _parse_create(self) -> CreateStatement:
        """Parse a CREATE statement."""
        self._advance()  # CREATE

        if self._maybe_keyword(Keyword.TABLE):
            if_not_exists = self._maybe_keyword(Keyword.NOT) and self._maybe_keyword(Keyword.EXISTS)
            name = self._expect(TokenType.IDENTIFIER).value

            columns = []
            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == "(":
                self._advance()
                columns = self._parse_column_defs()
                self._expect(TokenType.PUNCTUATION, ")")

            return CreateStatement(
                object_type="TABLE",
                name=name,
                columns=columns,
                if_not_exists=if_not_exists,
            )

        elif self._maybe_keyword(Keyword.DATABASE):
            if_not_exists = self._maybe_keyword(Keyword.NOT) and self._maybe_keyword(Keyword.EXISTS)
            name = self._expect(TokenType.IDENTIFIER).value
            return CreateStatement(
                object_type="DATABASE",
                name=name,
                if_not_exists=if_not_exists,
            )

        elif self._maybe_keyword(Keyword.INDEX):
            name = self._expect(TokenType.IDENTIFIER).value
            self._expect_keyword(Keyword.ON)
            table_name = self._expect(TokenType.IDENTIFIER).value
            # Column list for index
            self._expect(TokenType.PUNCTUATION, "(")
            columns = [self._expect(TokenType.IDENTIFIER).value]
            while self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                columns.append(self._expect(TokenType.IDENTIFIER).value)
            self._expect(TokenType.PUNCTUATION, ")")
            return CreateStatement(
                object_type="INDEX",
                name=name,
            )

        else:
            raise SyntaxError(f"Expected TABLE, DATABASE, or INDEX after CREATE, got {self._peek().value}")

    def _parse_column_defs(self) -> List[ColumnDef]:
        """Parse column definitions in CREATE TABLE."""
        columns = []

        while True:
            if self._peek().token_type == TokenType.KEYWORD and self._peek().keyword in (
                Keyword.PRIMARY, Keyword.UNIQUE, Keyword.INDEX, Keyword.FOREIGN
            ):
                # Table-level constraint - skip for now
                if self._peek().keyword == Keyword.PRIMARY:
                    self._advance()
                    self._expect_keyword(Keyword.KEY)
                    self._expect(TokenType.PUNCTUATION, "(")
                    while self._peek().token_type != TokenType.PUNCTUATION or self._peek().value != ")":
                        self._advance()
                    self._expect(TokenType.PUNCTUATION, ")")
                else:
                    self._advance()
                    while self._peek().token_type != TokenType.PUNCTUATION or self._peek().value != ")":
                        self._advance()
            else:
                name = self._expect(TokenType.IDENTIFIER).value
                type_token = self._advance()
                if type_token.token_type == TokenType.KEYWORD and type_token.keyword == Keyword.NOT:
                    type_token = self._advance()
                data_type = type_token.value.upper()

                # Handle type parameters like VARCHAR(100)
                if (self._peek().token_type == TokenType.PUNCTUATION and
                        self._peek().value == "("):
                    self._advance()
                    param = self._expect(TokenType.NUMBER).value
                    self._expect(TokenType.PUNCTUATION, ")")
                    data_type = f"{data_type}({param})"

                nullable = True
                primary_key = False
                unique = False
                default = None

                while self._peek().token_type != TokenType.PUNCTUATION or self._peek().value not in (")", ","):
                    if self._peek().token_type == TokenType.EOF:
                        break
                    if self._maybe_keyword(Keyword.NOT):
                        if self._maybe_keyword(Keyword.NULL):
                            nullable = False
                        elif self._maybe_keyword(Keyword.EXISTS):
                            pass
                    elif self._maybe_keyword(Keyword.PRIMARY):
                        self._expect_keyword(Keyword.KEY)
                        primary_key = True
                    elif self._maybe_keyword(Keyword.UNIQUE):
                        unique = True
                    elif self._maybe_keyword(Keyword.DEFAULT):
                        default = self._parse_literal()
                    elif self._maybe_keyword(Keyword.NULL):
                        nullable = True
                    else:
                        break

                columns.append(ColumnDef(
                    name=name,
                    data_type=data_type,
                    nullable=nullable,
                    primary_key=primary_key,
                    unique=unique,
                    default=default,
                ))

            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                continue
            break

        return columns

    def _parse_literal(self) -> Expression:
        """Parse a literal expression."""
        token = self._peek()
        if token.token_type == TokenType.NUMBER:
            self._advance()
            if "." in token.value:
                return LiteralExpression(float(token.value))
            return LiteralExpression(int(token.value))
        elif token.token_type == TokenType.STRING:
            self._advance()
            return LiteralExpression(token.value)
        elif token.token_type == TokenType.KEYWORD:
            if token.keyword == Keyword.TRUE:
                self._advance()
                return LiteralExpression(True)
            elif token.keyword == Keyword.FALSE:
                self._advance()
                return LiteralExpression(False)
            elif token.keyword == Keyword.NULL:
                self._advance()
                return LiteralExpression(None)
        raise SyntaxError(f"Expected literal, got {token}")

    def _parse_drop(self) -> DropStatement:
        """Parse a DROP statement."""
        self._advance()  # DROP

        if self._maybe_keyword(Keyword.TABLE):
            if_exists = self._maybe_keyword(Keyword.IF) and self._maybe_keyword(Keyword.EXISTS)
            name = self._expect(TokenType.IDENTIFIER).value
            return DropStatement(object_type="TABLE", name=name, if_exists=if_exists)

        elif self._maybe_keyword(Keyword.DATABASE):
            if_exists = self._maybe_keyword(Keyword.IF) and self._maybe_keyword(Keyword.EXISTS)
            name = self._expect(TokenType.IDENTIFIER).value
            return DropStatement(object_type="DATABASE", name=name, if_exists=if_exists)

        else:
            raise SyntaxError(f"Expected TABLE or DATABASE after DROP, got {self._peek().value}")

    def _parse_delete(self) -> DeleteStatement:
        """Parse a DELETE statement."""
        self._advance()  # DELETE
        self._expect_keyword(Keyword.FROM)
        table_name = self._expect(TokenType.IDENTIFIER).value

        where_clause = None
        if self._maybe_keyword(Keyword.WHERE):
            where_clause = self._parse_expression()

        return DeleteStatement(table_name=table_name, where_clause=where_clause)

    def _parse_update(self) -> UpdateStatement:
        """Parse an UPDATE statement."""
        self._advance()  # UPDATE
        table_name = self._expect(TokenType.IDENTIFIER).value
        self._expect_keyword(Keyword.SET)

        set_clauses = []
        while True:
            col_name = self._expect(TokenType.IDENTIFIER).value
            self._expect(TokenType.OPERATOR, "=")
            value = self._parse_expression()
            set_clauses.append((col_name, value))

            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                continue
            break

        where_clause = None
        if self._maybe_keyword(Keyword.WHERE):
            where_clause = self._parse_expression()

        return UpdateStatement(
            table_name=table_name,
            set_clauses=set_clauses,
            where_clause=where_clause,
        )

    def _parse_alter(self) -> AlterStatement:
        """Parse an ALTER TABLE statement."""
        self._advance()  # ALTER
        self._expect_keyword(Keyword.TABLE)
        table_name = self._expect(TokenType.IDENTIFIER).value

        if self._maybe_keyword(Keyword.ADD):
            if self._maybe_keyword(Keyword.COLUMN):
                pass
            col = self._parse_column_defs()[0]
            return AlterStatement(table_name=table_name, action="ADD COLUMN", column=col)

        elif self._maybe_keyword(Keyword.DROP):
            if self._maybe_keyword(Keyword.COLUMN):
                pass
            col_name = self._expect(TokenType.IDENTIFIER).value
            return AlterStatement(
                table_name=table_name, action="DROP COLUMN", column_name=col_name
            )

        else:
            raise SyntaxError(f"Expected ADD or DROP after ALTER TABLE, got {self._peek().value}")

    def _parse_use(self) -> UseStatement:
        """Parse a USE statement."""
        self._advance()  # USE
        db_name = self._expect(TokenType.IDENTIFIER).value
        return UseStatement(database_name=db_name)

    def _parse_show(self) -> ShowStatement:
        """Parse a SHOW statement."""
        self._advance()  # SHOW
        if self._maybe_keyword(Keyword.DATABASES):
            return ShowStatement(object_type="DATABASES")
        elif self._maybe_keyword(Keyword.TABLES):
            return ShowStatement(object_type="TABLES")
        else:
            raise SyntaxError(f"Expected DATABASES or TABLES after SHOW, got {self._peek().value}")

    def _parse_transaction(self) -> TransactionStatement:
        """Parse a transaction statement."""
        token = self._advance()
        action = token.value.upper()
        # Consume optional TRANSACTION keyword
        self._maybe_keyword(Keyword.TRANSACTION)
        return TransactionStatement(action=action)

    def _parse_explain(self) -> ExplainStatement:
        """Parse an EXPLAIN statement."""
        self._advance()  # EXPLAIN
        stmt = self.parse()
        return ExplainStatement(statement=stmt)

    def _parse_expression(self) -> Expression:
        """Parse a full expression (handles OR, AND, NOT, comparisons, arithmetic)."""
        return self._parse_or()

    def _parse_or(self) -> Expression:
        left = self._parse_and()
        while self._maybe_keyword(Keyword.OR):
            right = self._parse_and()
            left = BinaryExpression("OR", left, right)
        return left

    def _parse_and(self) -> Expression:
        left = self._parse_not()
        while self._maybe_keyword(Keyword.AND):
            right = self._parse_not()
            left = BinaryExpression("AND", left, right)
        return left

    def _parse_not(self) -> Expression:
        if self._maybe_keyword(Keyword.NOT):
            operand = self._parse_not()
            return UnaryExpression("NOT", operand)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expression:
        left = self._parse_addition()

        if self._peek().token_type == TokenType.OPERATOR:
            op = self._peek().value
            if op in ("=", "!=", "<", ">", "<=", ">="):
                self._advance()
                right = self._parse_addition()
                return BinaryExpression(op, left, right)

        if self._maybe_keyword(Keyword.IN):
            self._expect(TokenType.PUNCTUATION, "(")
            values = [self._parse_expression()]
            while self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                values.append(self._parse_expression())
            self._expect(TokenType.PUNCTUATION, ")")
            return InExpression(left, values)

        if self._maybe_keyword(Keyword.LIKE):
            pattern = self._parse_addition()
            return LikeExpression(left, pattern)

        if self._maybe_keyword(Keyword.BETWEEN):
            low = self._parse_addition()
            self._expect_keyword(Keyword.AND)
            high = self._parse_addition()
            return BetweenExpression(left, low, high)

        if self._maybe_keyword(Keyword.IS):
            if self._maybe_keyword(Keyword.NOT):
                # IS NOT NULL
                if self._maybe_keyword(Keyword.NULL):
                    return BinaryExpression("IS NOT", left, LiteralExpression(None))
            elif self._maybe_keyword(Keyword.NULL):
                return BinaryExpression("IS", left, LiteralExpression(None))

        return left

    def _parse_addition(self) -> Expression:
        left = self._parse_multiplication()
        while (self._peek().token_type == TokenType.OPERATOR and
               self._peek().value in ("+", "-")):
            op = self._advance().value
            right = self._parse_multiplication()
            left = BinaryExpression(op, left, right)
        return left

    def _parse_multiplication(self) -> Expression:
        left = self._parse_unary()
        while (self._peek().token_type == TokenType.OPERATOR and
               self._peek().value in ("*", "/")):
            op = self._advance().value
            right = self._parse_unary()
            left = BinaryExpression(op, left, right)
        return left

    def _parse_unary(self) -> Expression:
        if self._peek().token_type == TokenType.OPERATOR and self._peek().value == "-":
            self._advance()
            operand = self._parse_unary()
            return UnaryExpression("-", operand)
        return self._parse_primary()

    def _parse_primary(self) -> Expression:
        token = self._peek()

        # Literal
        if token.token_type in (TokenType.NUMBER, TokenType.STRING):
            return self._parse_literal()

        # Keyword literals
        if token.token_type == TokenType.KEYWORD:
            if token.keyword in (Keyword.TRUE, Keyword.FALSE, Keyword.NULL):
                return self._parse_literal()
            if token.keyword in (Keyword.COUNT, Keyword.SUM, Keyword.AVG, Keyword.MIN, Keyword.MAX):
                return self._parse_function_call()
            if token.keyword == Keyword.CASE:
                return self._parse_case()
            if token.keyword == Keyword.EXISTS:
                return self._parse_exists()

        # Identifier or column reference
        if token.token_type == TokenType.IDENTIFIER:
            self._advance()
            name = token.value

            # Function call
            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == "(":
                return self._parse_function_call(name)

            # Column with table prefix
            if self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ".":
                self._advance()
                table_name = name
                if self._peek().token_type == TokenType.OPERATOR and self._peek().value == "*":
                    self._advance()
                    return StarExpression(table_name=table_name)
                col_name = self._expect(TokenType.IDENTIFIER).value
                return ColumnExpression(name=col_name, table_name=table_name)

            return ColumnExpression(name=name)

        # Star (for SELECT *)
        if token.token_type == TokenType.OPERATOR and token.value == "*":
            self._advance()
            return StarExpression()

        # Nested expression
        if token.token_type == TokenType.PUNCTUATION and token.value == "(":
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.PUNCTUATION, ")")
            return expr

        # Subquery
        if token.token_type == TokenType.KEYWORD and token.keyword == Keyword.SELECT:
            stmt = self._parse_select()
            return SubqueryExpression(stmt)

        raise SyntaxError(f"Unexpected token: {token}")

    def _parse_function_call(self, name: Optional[str] = None) -> FunctionCall:
        """Parse a function call."""
        if name is None:
            name = self._advance().value.upper()
        self._expect(TokenType.PUNCTUATION, "(")

        distinct = False
        if self._maybe_keyword(Keyword.DISTINCT):
            distinct = True

        args = []
        if self._peek().token_type != TokenType.PUNCTUATION or self._peek().value != ")":
            args.append(self._parse_expression())
            while self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
                self._advance()
                args.append(self._parse_expression())

        self._expect(TokenType.PUNCTUATION, ")")

        return FunctionCall(name=name, args=args, distinct=distinct)

    def _parse_case(self) -> CaseExpression:
        """Parse a CASE expression."""
        self._advance()  # CASE

        conditions = []
        results = []
        else_result = None

        while self._maybe_keyword(Keyword.WHEN):
            conditions.append(self._parse_expression())
            self._expect_keyword(Keyword.THEN)
            results.append(self._parse_expression())

        if self._maybe_keyword(Keyword.ELSE):
            else_result = self._parse_expression()

        self._expect_keyword(Keyword.END)

        return CaseExpression(conditions=conditions, results=results, else_result=else_result)

    def _parse_exists(self) -> SubqueryExpression:
        """Parse an EXISTS subquery."""
        self._advance()  # EXISTS
        self._expect(TokenType.PUNCTUATION, "(")
        stmt = self._parse_select()
        self._expect(TokenType.PUNCTUATION, ")")
        return SubqueryExpression(stmt)

    def _parse_expression_list(self) -> List[Expression]:
        """Parse a comma-separated list of expressions."""
        exprs = [self._parse_expression()]
        while self._peek().token_type == TokenType.PUNCTUATION and self._peek().value == ",":
            self._advance()
            exprs.append(self._parse_expression())
        return exprs