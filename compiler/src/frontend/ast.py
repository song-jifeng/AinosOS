"""
AI 编译器工具链 - AST 节点定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.frontend.token import Token, TokenType


class ASTNode:
    """AST 节点基类"""

    def __init__(self, line: int = 0, column: int = 0, file: str = ""):
        self.line = line
        self.column = column
        self.file = file

    def accept(self, visitor: "ASTVisitor") -> Any:
        """访问者模式入口"""
        method_name = f"visit_{self.__class__.__name__}"
        if hasattr(visitor, method_name):
            return getattr(visitor, method_name)(self)
        raise NotImplementedError(f"Visitor {type(visitor).__name__} has no method {method_name}")

    def children(self) -> list[ASTNode]:
        """返回子节点列表"""
        return []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


# ---------- 字面量 ----------

@dataclass
class IntegerLiteral(ASTNode):
    """整数字面量"""
    value: int
    token: Optional[Token] = None

    def __init__(self, value: int, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.value = value
        self.token = token

    def __repr__(self) -> str:
        return f"IntegerLiteral({self.value})"


@dataclass
class FloatLiteral(ASTNode):
    """浮点数字面量"""
    value: float
    token: Optional[Token] = None

    def __init__(self, value: float, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.value = value
        self.token = token

    def __repr__(self) -> str:
        return f"FloatLiteral({self.value})"


@dataclass
class StringLiteral(ASTNode):
    """字符串字面量"""
    value: str
    token: Optional[Token] = None

    def __init__(self, value: str, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.value = value
        self.token = token

    def __repr__(self) -> str:
        return f"StringLiteral({self.value!r})"


@dataclass
class BooleanLiteral(ASTNode):
    """布尔字面量"""
    value: bool
    token: Optional[Token] = None

    def __init__(self, value: bool, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.value = value
        self.token = token

    def __repr__(self) -> str:
        return f"BooleanLiteral({self.value})"


@dataclass
class NullLiteral(ASTNode):
    """空字面量"""
    token: Optional[Token] = None

    def __init__(self, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.token = token

    def __repr__(self) -> str:
        return "NullLiteral()"


# ---------- 表达式 ----------

@dataclass
class Identifier(ASTNode):
    """标识符"""
    name: str
    token: Optional[Token] = None

    def __init__(self, name: str, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.name = name
        self.token = token

    def __repr__(self) -> str:
        return f"Identifier({self.name})"


@dataclass
class BinaryOp(ASTNode):
    """二元运算表达式"""
    left: ASTNode
    op: Token
    right: ASTNode

    def __init__(self, left: ASTNode, op: Token, right: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.left = left
        self.op = op
        self.right = right

    def children(self) -> list[ASTNode]:
        return [self.left, self.right]

    def __repr__(self) -> str:
        return f"BinaryOp({self.op})"


@dataclass
class UnaryOp(ASTNode):
    """一元运算表达式"""
    op: Token
    operand: ASTNode
    prefix: bool = True  # True 前缀, False 后缀

    def __init__(self, op: Token, operand: ASTNode, prefix: bool = True, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.op = op
        self.operand = operand
        self.prefix = prefix

    def children(self) -> list[ASTNode]:
        return [self.operand]

    def __repr__(self) -> str:
        return f"UnaryOp({self.op}, prefix={self.prefix})"


@dataclass
class Assignment(ASTNode):
    """赋值表达式"""
    target: ASTNode
    op: Token  # 赋值运算符
    value: ASTNode

    def __init__(self, target: ASTNode, op: Token, value: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.target = target
        self.op = op
        self.value = value

    def children(self) -> list[ASTNode]:
        return [self.target, self.value]

    def __repr__(self) -> str:
        return f"Assignment({self.op})"


@dataclass
class Call(ASTNode):
    """函数调用表达式"""
    callee: ASTNode
    args: list[ASTNode]
    token: Optional[Token] = None

    def __init__(self, callee: ASTNode, args: list[ASTNode], token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.callee = callee
        self.args = args
        self.token = token

    def children(self) -> list[ASTNode]:
        return [self.callee] + self.args

    def __repr__(self) -> str:
        return f"Call({len(self.args)} args)"


@dataclass
class Access(ASTNode):
    """属性访问表达式 (a.b 或 a[b])"""
    obj: ASTNode
    key: ASTNode
    is_index: bool = False  # True 为索引访问 [], False 为属性访问 .

    def __init__(self, obj: ASTNode, key: ASTNode, is_index: bool = False, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.obj = obj
        self.key = key
        self.is_index = is_index

    def children(self) -> list[ASTNode]:
        return [self.obj, self.key]

    def __repr__(self) -> str:
        return f"Access(is_index={self.is_index})"


@dataclass
class ArrayLiteral(ASTNode):
    """数组字面量 [1, 2, 3]"""
    elements: list[ASTNode]

    def __init__(self, elements: list[ASTNode], line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.elements = elements

    def children(self) -> list[ASTNode]:
        return self.elements

    def __repr__(self) -> str:
        return f"ArrayLiteral({len(self.elements)} elements)"


@dataclass
class RecordLiteral(ASTNode):
    """记录字面量 {a: 1, b: 2}"""
    entries: list[tuple[ASTNode, ASTNode]]

    def __init__(self, entries: list[tuple[ASTNode, ASTNode]], line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.entries = entries

    def children(self) -> list[ASTNode]:
        children = []
        for key, val in self.entries:
            children.append(key)
            children.append(val)
        return children

    def __repr__(self) -> str:
        return f"RecordLiteral({len(self.entries)} entries)"


@dataclass
class LambdaExpr(ASTNode):
    """Lambda 表达式"""
    params: list[Parameter]
    body: ASTNode
    return_type: Optional[ASTNode] = None

    def __init__(self, params: list[Parameter], body: ASTNode, return_type: Optional[ASTNode] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.params = params
        self.body = body
        self.return_type = return_type

    def children(self) -> list[ASTNode]:
        return self.params + [self.body]

    def __repr__(self) -> str:
        return f"LambdaExpr({len(self.params)} params)"


@dataclass
class TernaryExpr(ASTNode):
    """三元表达式 cond ? then_expr : else_expr"""
    condition: ASTNode
    then_expr: ASTNode
    else_expr: ASTNode

    def __init__(self, condition: ASTNode, then_expr: ASTNode, else_expr: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.condition = condition
        self.then_expr = then_expr
        self.else_expr = else_expr

    def children(self) -> list[ASTNode]:
        return [self.condition, self.then_expr, self.else_expr]

    def __repr__(self) -> str:
        return "TernaryExpr()"


@dataclass
class CastExpr(ASTNode):
    """类型转换表达式"""
    expr: ASTNode
    target_type: ASTNode

    def __init__(self, expr: ASTNode, target_type: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.expr = expr
        self.target_type = target_type

    def children(self) -> list[ASTNode]:
        return [self.expr, self.target_type]

    def __repr__(self) -> str:
        return "CastExpr()"


# ---------- 类型注解 ----------

@dataclass
class TypeAnnotation(ASTNode):
    """类型注解"""
    name: str  # 类型名称: int, float, bool, string, void, tensor
    type_params: list[ASTNode] = field(default_factory=list)  # 泛型参数

    def __init__(self, name: str, type_params: list[ASTNode] | None = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.name = name
        self.type_params = type_params or []

    def children(self) -> list[ASTNode]:
        return self.type_params

    def __repr__(self) -> str:
        if self.type_params:
            return f"TypeAnnotation({self.name}[{', '.join(str(t) for t in self.type_params)}])"
        return f"TypeAnnotation({self.name})"


@dataclass
class ArrayType(ASTNode):
    """数组类型 annotation"""
    element_type: ASTNode
    size: Optional[ASTNode] = None

    def __init__(self, element_type: ASTNode, size: Optional[ASTNode] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.element_type = element_type
        self.size = size

    def children(self) -> list[ASTNode]:
        return [self.element_type] + ([self.size] if self.size else [])

    def __repr__(self) -> str:
        return f"ArrayType({self.element_type})"


@dataclass
class TensorType(ASTNode):
    """张量类型"""
    element_type: ASTNode
    shape: list[ASTNode]  # 维度列表

    def __init__(self, element_type: ASTNode, shape: list[ASTNode] | None = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.element_type = element_type
        self.shape = shape or []

    def children(self) -> list[ASTNode]:
        return [self.element_type] + self.shape

    def __repr__(self) -> str:
        return f"TensorType({self.element_type}, dims={len(self.shape)})"


@dataclass
class FunctionType(ASTNode):
    """函数类型 (param_types) -> return_type"""
    param_types: list[ASTNode]
    return_type: ASTNode

    def __init__(self, param_types: list[ASTNode], return_type: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.param_types = param_types
        self.return_type = return_type

    def children(self) -> list[ASTNode]:
        return self.param_types + [self.return_type]

    def __repr__(self) -> str:
        return f"FunctionType({len(self.param_types)} params -> {self.return_type})"


# ---------- 语句 ----------

@dataclass
class Parameter(ASTNode):
    """函数参数"""
    name: str
    type_annotation: Optional[ASTNode] = None
    default_value: Optional[ASTNode] = None
    mutable: bool = False

    def __init__(self, name: str, type_annotation: Optional[ASTNode] = None, default_value: Optional[ASTNode] = None, mutable: bool = False, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.name = name
        self.type_annotation = type_annotation
        self.default_value = default_value
        self.mutable = mutable

    def children(self) -> list[ASTNode]:
        children = []
        if self.type_annotation:
            children.append(self.type_annotation)
        if self.default_value:
            children.append(self.default_value)
        return children

    def __repr__(self) -> str:
        return f"Parameter({self.name})"


@dataclass
class VariableDecl(ASTNode):
    """变量声明"""
    name: str
    type_annotation: Optional[ASTNode] = None
    initializer: Optional[ASTNode] = None
    mutable: bool = False
    is_exported: bool = False
    token: Optional[Token] = None

    def __init__(self, name: str, type_annotation: Optional[ASTNode] = None, initializer: Optional[ASTNode] = None, mutable: bool = False, is_exported: bool = False, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.name = name
        self.type_annotation = type_annotation
        self.initializer = initializer
        self.mutable = mutable
        self.is_exported = is_exported
        self.token = token

    def children(self) -> list[ASTNode]:
        children = []
        if self.type_annotation:
            children.append(self.type_annotation)
        if self.initializer:
            children.append(self.initializer)
        return children

    def __repr__(self) -> str:
        return f"VariableDecl({self.name}, mutable={self.mutable})"


@dataclass
class Block(ASTNode):
    """语句块"""
    statements: list[ASTNode]

    def __init__(self, statements: list[ASTNode], line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.statements = statements

    def children(self) -> list[ASTNode]:
        return self.statements

    def __repr__(self) -> str:
        return f"Block({len(self.statements)} stmts)"


@dataclass
class IfStmt(ASTNode):
    """If 语句"""
    condition: ASTNode
    then_body: ASTNode
    else_body: Optional[ASTNode] = None

    def __init__(self, condition: ASTNode, then_body: ASTNode, else_body: Optional[ASTNode] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.condition = condition
        self.then_body = then_body
        self.else_body = else_body

    def children(self) -> list[ASTNode]:
        children = [self.condition, self.then_body]
        if self.else_body:
            children.append(self.else_body)
        return children

    def __repr__(self) -> str:
        return "IfStmt()"


@dataclass
class WhileStmt(ASTNode):
    """While 语句"""
    condition: ASTNode
    body: ASTNode

    def __init__(self, condition: ASTNode, body: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.condition = condition
        self.body = body

    def children(self) -> list[ASTNode]:
        return [self.condition, self.body]

    def __repr__(self) -> str:
        return "WhileStmt()"


@dataclass
class ForStmt(ASTNode):
    """For 语句"""
    init: Optional[ASTNode]  # 初始化语句或变量声明
    condition: Optional[ASTNode]
    update: Optional[ASTNode]  # 迭代表达式
    body: ASTNode

    def __init__(self, init: Optional[ASTNode], condition: Optional[ASTNode], update: Optional[ASTNode], body: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.init = init
        self.condition = condition
        self.update = update
        self.body = body

    def children(self) -> list[ASTNode]:
        children = []
        if self.init:
            children.append(self.init)
        if self.condition:
            children.append(self.condition)
        if self.update:
            children.append(self.update)
        children.append(self.body)
        return children

    def __repr__(self) -> str:
        return "ForStmt()"


@dataclass
class ForInStmt(ASTNode):
    """For-in 语句 (for x in iterable)"""
    target: ASTNode  # 循环变量
    iterable: ASTNode  # 可迭代对象
    body: ASTNode

    def __init__(self, target: ASTNode, iterable: ASTNode, body: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.target = target
        self.iterable = iterable
        self.body = body

    def children(self) -> list[ASTNode]:
        return [self.target, self.iterable, self.body]

    def __repr__(self) -> str:
        return "ForInStmt()"


@dataclass
class BreakStmt(ASTNode):
    """Break 语句"""
    token: Optional[Token] = None

    def __init__(self, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.token = token

    def __repr__(self) -> str:
        return "BreakStmt()"


@dataclass
class ContinueStmt(ASTNode):
    """Continue 语句"""
    token: Optional[Token] = None

    def __init__(self, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.token = token

    def __repr__(self) -> str:
        return "ContinueStmt()"


@dataclass
class ReturnStmt(ASTNode):
    """Return 语句"""
    value: Optional[ASTNode] = None
    token: Optional[Token] = None

    def __init__(self, value: Optional[ASTNode] = None, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.value = value
        self.token = token

    def children(self) -> list[ASTNode]:
        return [self.value] if self.value else []

    def __repr__(self) -> str:
        return "ReturnStmt()"


@dataclass
class AssertStmt(ASTNode):
    """Assert 语句"""
    condition: ASTNode
    message: Optional[ASTNode] = None

    def __init__(self, condition: ASTNode, message: Optional[ASTNode] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.condition = condition
        self.message = message

    def children(self) -> list[ASTNode]:
        children = [self.condition]
        if self.message:
            children.append(self.message)
        return children

    def __repr__(self) -> str:
        return "AssertStmt()"


@dataclass
class DeferStmt(ASTNode):
    """Defer 语句"""
    call: ASTNode

    def __init__(self, call: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.call = call

    def children(self) -> list[ASTNode]:
        return [self.call]

    def __repr__(self) -> str:
        return "DeferStmt()"


@dataclass
class MatchStmt(ASTNode):
    """Match 语句（模式匹配）"""
    target: ASTNode
    arms: list[tuple[ASTNode, ASTNode]]  # (pattern, body)

    def __init__(self, target: ASTNode, arms: list[tuple[ASTNode, ASTNode]], line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.target = target
        self.arms = arms

    def children(self) -> list[ASTNode]:
        children = [self.target]
        for pattern, body in self.arms:
            children.append(pattern)
            children.append(body)
        return children

    def __repr__(self) -> str:
        return f"MatchStmt({len(self.arms)} arms)"


@dataclass
class ExpressionStmt(ASTNode):
    """表达式语句"""
    expression: ASTNode

    def __init__(self, expression: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.expression = expression

    def children(self) -> list[ASTNode]:
        return [self.expression]

    def __repr__(self) -> str:
        return "ExpressionStmt()"


# ---------- 声明 ----------

@dataclass
class FunctionDecl(ASTNode):
    """函数声明"""
    name: str
    params: list[Parameter]
    return_type: Optional[ASTNode]
    body: ASTNode
    is_exported: bool = False
    is_extern: bool = False
    decorators: list[ASTNode] = field(default_factory=list)
    token: Optional[Token] = None

    def __init__(self, name: str, params: list[Parameter], return_type: Optional[ASTNode], body: ASTNode, is_exported: bool = False, is_extern: bool = False, decorators: list[ASTNode] | None = None, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.name = name
        self.params = params
        self.return_type = return_type
        self.body = body
        self.is_exported = is_exported
        self.is_extern = is_extern
        self.decorators = decorators or []
        self.token = token

    def children(self) -> list[ASTNode]:
        children = []
        for p in self.params:
            children.append(p)
        if self.return_type:
            children.append(self.return_type)
        if isinstance(self.body, ASTNode):
            children.append(self.body)
        return children + self.decorators

    def __repr__(self) -> str:
        return f"FunctionDecl({self.name}, {len(self.params)} params)"


@dataclass
class ClassDecl(ASTNode):
    """类声明"""
    name: str
    base_class: Optional[ASTNode] = None
    body: list[ASTNode] = field(default_factory=list)
    is_exported: bool = False
    decorators: list[ASTNode] = field(default_factory=list)
    token: Optional[Token] = None

    def __init__(self, name: str, base_class: Optional[ASTNode] = None, body: list[ASTNode] | None = None, is_exported: bool = False, decorators: list[ASTNode] | None = None, token: Optional[Token] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.name = name
        self.base_class = base_class
        self.body = body or []
        self.is_exported = is_exported
        self.decorators = decorators or []
        self.token = token

    def children(self) -> list[ASTNode]:
        children = []
        if self.base_class:
            children.append(self.base_class)
        children.extend(self.body)
        children.extend(self.decorators)
        return children

    def __repr__(self) -> str:
        return f"ClassDecl({self.name})"


@dataclass
class ImportDecl(ASTNode):
    """Import 声明"""
    module: str  # 模块路径
    names: list[tuple[str, Optional[str]]]  # [(原名, 别名)]
    source: str  # 来源

    def __init__(self, module: str, names: list[tuple[str, Optional[str]]], source: str = "", line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.module = module
        self.names = names
        self.source = source

    def __repr__(self) -> str:
        return f"ImportDecl({self.module})"


@dataclass
class ExportDecl(ASTNode):
    """Export 声明"""
    declaration: ASTNode

    def __init__(self, declaration: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.declaration = declaration

    def children(self) -> list[ASTNode]:
        return [self.declaration]

    def __repr__(self) -> str:
        return "ExportDecl()"


@dataclass
class TypeDecl(ASTNode):
    """类型别名声明"""
    name: str
    type_expr: ASTNode

    def __init__(self, name: str, type_expr: ASTNode, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.name = name
        self.type_expr = type_expr

    def children(self) -> list[ASTNode]:
        return [self.type_expr]

    def __repr__(self) -> str:
        return f"TypeDecl({self.name})"


# ---------- 顶层 ----------

@dataclass
class Module(ASTNode):
    """模块（源文件）"""
    name: str
    declarations: list[ASTNode]
    file: str = ""

    def __init__(self, name: str, declarations: list[ASTNode], file: str = ""):
        super().__init__(line=0, column=0, file=file)
        self.name = name
        self.declarations = declarations
        self.file = file

    def children(self) -> list[ASTNode]:
        return self.declarations

    def __repr__(self) -> str:
        return f"Module({self.name}, {len(self.declarations)} decls)"


@dataclass
class Program(ASTNode):
    """程序（包含多个模块）"""
    modules: list[Module]
    entry_module: Optional[str] = None

    def __init__(self, modules: list[Module], entry_module: Optional[str] = None):
        super().__init__(line=0, column=0)
        self.modules = modules
        self.entry_module = entry_module

    def children(self) -> list[ASTNode]:
        return self.modules

    def __repr__(self) -> str:
        return f"Program({len(self.modules)} modules)"


# ---------- 模式匹配节点 ----------

@dataclass
class MatchPattern(ASTNode):
    """匹配模式"""
    pattern_type: str  # "wildcard", "literal", "variable", "or", "guard"
    value: Any
    sub_patterns: list[MatchPattern] = field(default_factory=list)
    guard: Optional[ASTNode] = None

    def __init__(self, pattern_type: str, value: Any = None, sub_patterns: list[MatchPattern] | None = None, guard: Optional[ASTNode] = None, line: int = 0, column: int = 0, file: str = ""):
        super().__init__(line, column, file)
        self.pattern_type = pattern_type
        self.value = value
        self.sub_patterns = sub_patterns or []
        self.guard = guard

    def __repr__(self) -> str:
        return f"MatchPattern({self.pattern_type})"


# ---------- 访问者接口 ----------

class ASTVisitor:
    """AST 访问者基类"""

    def visit(self, node: ASTNode) -> Any:
        """访问节点"""
        return node.accept(self)

    def visit_IntegerLiteral(self, node: IntegerLiteral) -> Any:
        raise NotImplementedError

    def visit_FloatLiteral(self, node: FloatLiteral) -> Any:
        raise NotImplementedError

    def visit_StringLiteral(self, node: StringLiteral) -> Any:
        raise NotImplementedError

    def visit_BooleanLiteral(self, node: BooleanLiteral) -> Any:
        raise NotImplementedError

    def visit_NullLiteral(self, node: NullLiteral) -> Any:
        raise NotImplementedError

    def visit_Identifier(self, node: Identifier) -> Any:
        raise NotImplementedError

    def visit_BinaryOp(self, node: BinaryOp) -> Any:
        raise NotImplementedError

    def visit_UnaryOp(self, node: UnaryOp) -> Any:
        raise NotImplementedError

    def visit_Assignment(self, node: Assignment) -> Any:
        raise NotImplementedError

    def visit_Call(self, node: Call) -> Any:
        raise NotImplementedError

    def visit_Access(self, node: Access) -> Any:
        raise NotImplementedError

    def visit_ArrayLiteral(self, node: ArrayLiteral) -> Any:
        raise NotImplementedError

    def visit_RecordLiteral(self, node: RecordLiteral) -> Any:
        raise NotImplementedError

    def visit_LambdaExpr(self, node: LambdaExpr) -> Any:
        raise NotImplementedError

    def visit_TernaryExpr(self, node: TernaryExpr) -> Any:
        raise NotImplementedError

    def visit_CastExpr(self, node: CastExpr) -> Any:
        raise NotImplementedError

    def visit_TypeAnnotation(self, node: TypeAnnotation) -> Any:
        raise NotImplementedError

    def visit_ArrayType(self, node: ArrayType) -> Any:
        raise NotImplementedError

    def visit_TensorType(self, node: TensorType) -> Any:
        raise NotImplementedError

    def visit_FunctionType(self, node: FunctionType) -> Any:
        raise NotImplementedError

    def visit_Parameter(self, node: Parameter) -> Any:
        raise NotImplementedError

    def visit_VariableDecl(self, node: VariableDecl) -> Any:
        raise NotImplementedError

    def visit_Block(self, node: Block) -> Any:
        raise NotImplementedError

    def visit_IfStmt(self, node: IfStmt) -> Any:
        raise NotImplementedError

    def visit_WhileStmt(self, node: WhileStmt) -> Any:
        raise NotImplementedError

    def visit_ForStmt(self, node: ForStmt) -> Any:
        raise NotImplementedError

    def visit_ForInStmt(self, node: ForInStmt) -> Any:
        raise NotImplementedError

    def visit_BreakStmt(self, node: BreakStmt) -> Any:
        raise NotImplementedError

    def visit_ContinueStmt(self, node: ContinueStmt) -> Any:
        raise NotImplementedError

    def visit_ReturnStmt(self, node: ReturnStmt) -> Any:
        raise NotImplementedError

    def visit_AssertStmt(self, node: AssertStmt) -> Any:
        raise NotImplementedError

    def visit_DeferStmt(self, node: DeferStmt) -> Any:
        raise NotImplementedError

    def visit_MatchStmt(self, node: MatchStmt) -> Any:
        raise NotImplementedError

    def visit_ExpressionStmt(self, node: ExpressionStmt) -> Any:
        raise NotImplementedError

    def visit_FunctionDecl(self, node: FunctionDecl) -> Any:
        raise NotImplementedError

    def visit_ClassDecl(self, node: ClassDecl) -> Any:
        raise NotImplementedError

    def visit_ImportDecl(self, node: ImportDecl) -> Any:
        raise NotImplementedError

    def visit_ExportDecl(self, node: ExportDecl) -> Any:
        raise NotImplementedError

    def visit_TypeDecl(self, node: TypeDecl) -> Any:
        raise NotImplementedError

    def visit_Module(self, node: Module) -> Any:
        raise NotImplementedError

    def visit_Program(self, node: Program) -> Any:
        raise NotImplementedError

    def visit_MatchPattern(self, node: MatchPattern) -> Any:
        raise NotImplementedError


class ASTPrinter(ASTVisitor):
    """AST 打印器（用于调试）"""

    def __init__(self, indent: int = 2):
        self._indent = indent
        self._depth = 0

    def _print(self, text: str) -> str:
        prefix = " " * (self._depth * self._indent)
        return prefix + text

    def _visit_children(self, node: ASTNode, label: str = "children") -> list[str]:
        result = []
        children = node.children()
        if children:
            result.append(self._print(f"{label}:"))
            self._depth += 1
            for child in children:
                result.append(self.visit(child))
            self._depth -= 1
        return result

    def visit_IntegerLiteral(self, node: IntegerLiteral) -> str:
        return self._print(f"IntegerLiteral({node.value})")

    def visit_FloatLiteral(self, node: FloatLiteral) -> str:
        return self._print(f"FloatLiteral({node.value})")

    def visit_StringLiteral(self, node: StringLiteral) -> str:
        return self._print(f"StringLiteral({node.value!r})")

    def visit_BooleanLiteral(self, node: BooleanLiteral) -> str:
        return self._print(f"BooleanLiteral({node.value})")

    def visit_NullLiteral(self, node: NullLiteral) -> str:
        return self._print("NullLiteral")

    def visit_Identifier(self, node: Identifier) -> str:
        return self._print(f"Identifier({node.name})")

    def visit_BinaryOp(self, node: BinaryOp) -> str:
        lines = [self._print(f"BinaryOp({node.op.type})")]
        self._depth += 1
        lines.append(self.visit(node.left))
        lines.append(self.visit(node.right))
        self._depth -= 1
        return "\n".join(lines)

    def visit_UnaryOp(self, node: UnaryOp) -> str:
        prefix = "Prefix" if node.prefix else "Postfix"
        lines = [self._print(f"UnaryOp({node.op.type}, {prefix})")]
        self._depth += 1
        lines.append(self.visit(node.operand))
        self._depth -= 1
        return "\n".join(lines)

    def visit_Assignment(self, node: Assignment) -> str:
        lines = [self._print(f"Assignment({node.op.type})")]
        self._depth += 1
        lines.append(self.visit(node.target))
        lines.append(self.visit(node.value))
        self._depth -= 1
        return "\n".join(lines)

    def visit_Call(self, node: Call) -> str:
        lines = [self._print(f"Call({len(node.args)} args)")]
        self._depth += 1
        lines.append(self.visit(node.callee))
        for arg in node.args:
            lines.append(self.visit(arg))
        self._depth -= 1
        return "\n".join(lines)

    def visit_Access(self, node: Access) -> str:
        idx = "index" if node.is_index else "property"
        lines = [self._print(f"Access({idx})")]
        self._depth += 1
        lines.append(self.visit(node.obj))
        lines.append(self.visit(node.key))
        self._depth -= 1
        return "\n".join(lines)

    def visit_ArrayLiteral(self, node: ArrayLiteral) -> str:
        lines = [self._print(f"ArrayLiteral({len(node.elements)} elements)")]
        self._depth += 1
        for el in node.elements:
            lines.append(self.visit(el))
        self._depth -= 1
        return "\n".join(lines)

    def visit_RecordLiteral(self, node: RecordLiteral) -> str:
        lines = [self._print(f"RecordLiteral({len(node.entries)} entries)")]
        self._depth += 1
        for key, val in node.entries:
            lines.append(self._print("entry:"))
            self._depth += 1
            lines.append(self.visit(key))
            lines.append(self.visit(val))
            self._depth -= 1
        self._depth -= 1
        return "\n".join(lines)

    def visit_LambdaExpr(self, node: LambdaExpr) -> str:
        lines = [self._print(f"LambdaExpr({len(node.params)} params)")]
        self._depth += 1
        for p in node.params:
            lines.append(self.visit(p))
        lines.append(self.visit(node.body))
        self._depth -= 1
        return "\n".join(lines)

    def visit_TernaryExpr(self, node: TernaryExpr) -> str:
        lines = [self._print("TernaryExpr")]
        self._depth += 1
        lines.append(self.visit(node.condition))
        lines.append(self.visit(node.then_expr))
        lines.append(self.visit(node.else_expr))
        self._depth -= 1
        return "\n".join(lines)

    def visit_CastExpr(self, node: CastExpr) -> str:
        lines = [self._print("CastExpr")]
        self._depth += 1
        lines.append(self.visit(node.expr))
        lines.append(self.visit(node.target_type))
        self._depth -= 1
        return "\n".join(lines)

    def visit_TypeAnnotation(self, node: TypeAnnotation) -> str:
        return self._print(f"TypeAnnotation({node.name})")

    def visit_ArrayType(self, node: ArrayType) -> str:
        return self._print(f"ArrayType")

    def visit_TensorType(self, node: TensorType) -> str:
        return self._print(f"TensorType(dims={len(node.shape)})")

    def visit_FunctionType(self, node: FunctionType) -> str:
        return self._print(f"FunctionType")

    def visit_Parameter(self, node: Parameter) -> str:
        return self._print(f"Parameter({node.name})")

    def visit_VariableDecl(self, node: VariableDecl) -> str:
        mut = "mut" if node.mutable else "let"
        lines = [self._print(f"VariableDecl({node.name}, {mut})")]
        self._depth += 1
        if node.type_annotation:
            lines.append(self.visit(node.type_annotation))
        if node.initializer:
            lines.append(self.visit(node.initializer))
        self._depth -= 1
        return "\n".join(lines)

    def visit_Block(self, node: Block) -> str:
        lines = [self._print(f"Block({len(node.statements)} stmts)")]
        self._depth += 1
        for s in node.statements:
            lines.append(self.visit(s))
        self._depth -= 1
        return "\n".join(lines)

    def visit_IfStmt(self, node: IfStmt) -> str:
        lines = [self._print("IfStmt")]
        self._depth += 1
        lines.append(self.visit(node.condition))
        lines.append(self.visit(node.then_body))
        if node.else_body:
            lines.append(self.visit(node.else_body))
        self._depth -= 1
        return "\n".join(lines)

    def visit_WhileStmt(self, node: WhileStmt) -> str:
        lines = [self._print("WhileStmt")]
        self._depth += 1
        lines.append(self.visit(node.condition))
        lines.append(self.visit(node.body))
        self._depth -= 1
        return "\n".join(lines)

    def visit_ForStmt(self, node: ForStmt) -> str:
        lines = [self._print("ForStmt")]
        self._depth += 1
        if node.init:
            lines.append(self.visit(node.init))
        if node.condition:
            lines.append(self.visit(node.condition))
        if node.update:
            lines.append(self.visit(node.update))
        lines.append(self.visit(node.body))
        self._depth -= 1
        return "\n".join(lines)

    def visit_ForInStmt(self, node: ForInStmt) -> str:
        lines = [self._print("ForInStmt")]
        self._depth += 1
        lines.append(self.visit(node.target))
        lines.append(self.visit(node.iterable))
        lines.append(self.visit(node.body))
        self._depth -= 1
        return "\n".join(lines)

    def visit_BreakStmt(self, node: BreakStmt) -> str:
        return self._print("BreakStmt")

    def visit_ContinueStmt(self, node: ContinueStmt) -> str:
        return self._print("ContinueStmt")

    def visit_ReturnStmt(self, node: ReturnStmt) -> str:
        lines = [self._print("ReturnStmt")]
        if node.value:
            self._depth += 1
            lines.append(self.visit(node.value))
            self._depth -= 1
        return "\n".join(lines)

    def visit_AssertStmt(self, node: AssertStmt) -> str:
        return self._print("AssertStmt")

    def visit_DeferStmt(self, node: DeferStmt) -> str:
        lines = [self._print("DeferStmt")]
        self._depth += 1
        lines.append(self.visit(node.call))
        self._depth -= 1
        return "\n".join(lines)

    def visit_MatchStmt(self, node: MatchStmt) -> str:
        lines = [self._print(f"MatchStmt({len(node.arms)} arms)")]
        self._depth += 1
        lines.append(self.visit(node.target))
        for i, (pattern, body) in enumerate(node.arms):
            lines.append(self._print(f"arm {i}:"))
            self._depth += 1
            lines.append(self.visit(pattern))
            lines.append(self.visit(body))
            self._depth -= 1
        self._depth -= 1
        return "\n".join(lines)

    def visit_ExpressionStmt(self, node: ExpressionStmt) -> str:
        lines = [self._print("ExpressionStmt")]
        self._depth += 1
        lines.append(self.visit(node.expression))
        self._depth -= 1
        return "\n".join(lines)

    def visit_FunctionDecl(self, node: FunctionDecl) -> str:
        lines = [self._print(f"FunctionDecl({node.name}, {len(node.params)} params)")]
        self._depth += 1
        for p in node.params:
            lines.append(self.visit(p))
        if node.return_type:
            lines.append(self.visit(node.return_type))
        lines.append(self.visit(node.body))
        self._depth -= 1
        return "\n".join(lines)

    def visit_ClassDecl(self, node: ClassDecl) -> str:
        lines = [self._print(f"ClassDecl({node.name})")]
        self._depth += 1
        if node.base_class:
            lines.append(self.visit(node.base_class))
        for member in node.body:
            lines.append(self.visit(member))
        self._depth -= 1
        return "\n".join(lines)

    def visit_ImportDecl(self, node: ImportDecl) -> str:
        return self._print(f"ImportDecl({node.module})")

    def visit_ExportDecl(self, node: ExportDecl) -> str:
        lines = [self._print("ExportDecl")]
        self._depth += 1
        lines.append(self.visit(node.declaration))
        self._depth -= 1
        return "\n".join(lines)

    def visit_TypeDecl(self, node: TypeDecl) -> str:
        return self._print(f"TypeDecl({node.name})")

    def visit_Module(self, node: Module) -> str:
        lines = [self._print(f"Module({node.name})")]
        self._depth += 1
        for decl in node.declarations:
            lines.append(self.visit(decl))
        self._depth -= 1
        return "\n".join(lines)

    def visit_Program(self, node: Program) -> str:
        lines = [self._print("Program")]
        self._depth += 1
        for mod in node.modules:
            lines.append(self.visit(mod))
        self._depth -= 1
        return "\n".join(lines)

    def visit_MatchPattern(self, node: MatchPattern) -> str:
        return self._print(f"MatchPattern({node.pattern_type})")


# 类型系统类型枚举
class TypeKind:
    """类型种类"""
    INTEGER = "int"
    FLOAT = "float"
    BOOLEAN = "bool"
    STRING = "string"
    VOID = "void"
    NULL = "null"
    ARRAY = "array"
    TENSOR = "tensor"
    FUNCTION = "function"
    CLASS = "class"
    RECORD = "record"
    TYPE_VAR = "type_var"
    ANY = "any"
    NEVERTYPE = "never"  # bottom type


@dataclass
class TypeInfo:
    """类型信息（语义分析后使用）"""
    kind: str  # TypeKind 中的值
    name: str = ""
    element_type: Optional["TypeInfo"] = None  # 数组/张量元素类型
    shape: list[int] = field(default_factory=list)  # 张量形状
    return_type: Optional["TypeInfo"] = None  # 函数返回类型
    param_types: list["TypeInfo"] = field(default_factory=list)  # 函数参数类型
    fields: dict[str, "TypeInfo"] = field(default_factory=dict)  # 记录/类字段
    methods: dict[str, "TypeInfo"] = field(default_factory=dict)  # 类方法
    type_params: list[str] = field(default_factory=list)  # 泛型参数

    def __repr__(self) -> str:
        if self.kind == TypeKind.ARRAY and self.element_type:
            return f"array<{self.element_type}>"
        if self.kind == TypeKind.TENSOR and self.element_type:
            return f"tensor<{self.element_type}, {self.shape}>"
        if self.kind == TypeKind.FUNCTION:
            params = ", ".join(str(p) for p in self.param_types)
            return f"({params}) -> {self.return_type}"
        return self.name or self.kind

    def is_numeric(self) -> bool:
        return self.kind in (TypeKind.INTEGER, TypeKind.FLOAT)

    def is_integral(self) -> bool:
        return self.kind == TypeKind.INTEGER

    def is_float_point(self) -> bool:
        return self.kind == TypeKind.FLOAT

    def is_boolean(self) -> bool:
        return self.kind == TypeKind.BOOLEAN

    def is_string(self) -> bool:
        return self.kind == TypeKind.STRING

    def is_void(self) -> bool:
        return self.kind == TypeKind.VOID

    def is_array(self) -> bool:
        return self.kind == TypeKind.ARRAY

    def is_tensor(self) -> bool:
        return self.kind == TypeKind.TENSOR

    def is_function(self) -> bool:
        return self.kind == TypeKind.FUNCTION

    def is_class(self) -> bool:
        return self.kind == TypeKind.CLASS

    def is_any(self) -> bool:
        return self.kind == TypeKind.ANY

    def can_assign_to(self, other: "TypeInfo") -> bool:
        """检查当前类型是否可以赋值给目标类型"""
        if other.is_any():
            return True
        if self.kind == other.kind:
            if self.is_array() and other.is_array():
                return self.element_type.can_assign_to(other.element_type) if self.element_type and other.element_type else True
            if self.is_tensor() and other.is_tensor():
                if self.shape != other.shape:
                    return False
                return self.element_type.can_assign_to(other.element_type) if self.element_type and other.element_type else True
            return True
        # 整数可以隐式转换为浮点数
        if self.is_integral() and other.is_float_point():
            return True
        return False

    @staticmethod
    def create_int() -> "TypeInfo":
        return TypeInfo(kind=TypeKind.INTEGER, name="int")

    @staticmethod
    def create_float() -> "TypeInfo":
        return TypeInfo(kind=TypeKind.FLOAT, name="float")

    @staticmethod
    def create_bool() -> "TypeInfo":
        return TypeInfo(kind=TypeKind.BOOLEAN, name="bool")

    @staticmethod
    def create_string() -> "TypeInfo":
        return TypeInfo(kind=TypeKind.STRING, name="string")

    @staticmethod
    def create_void() -> "TypeInfo":
        return TypeInfo(kind=TypeKind.VOID, name="void")

    @staticmethod
    def create_null() -> "TypeInfo":
        return TypeInfo(kind=TypeKind.NULL, name="null")

    @staticmethod
    def create_array(element_type: "TypeInfo") -> "TypeInfo":
        return TypeInfo(kind=TypeKind.ARRAY, name=f"array<{element_type}>", element_type=element_type)

    @staticmethod
    def create_tensor(element_type: "TypeInfo", shape: list[int] | None = None) -> "TypeInfo":
        shape = shape or []
        return TypeInfo(kind=TypeKind.TENSOR, name=f"tensor<{element_type}, {shape}>", element_type=element_type, shape=shape)

    @staticmethod
    def create_function(param_types: list["TypeInfo"], return_type: "TypeInfo") -> "TypeInfo":
        params_str = ", ".join(str(p) for p in param_types)
        return TypeInfo(kind=TypeKind.FUNCTION, name=f"({params_str}) -> {return_type}", param_types=param_types, return_type=return_type)

    @staticmethod
    def create_class(name: str, fields: dict[str, "TypeInfo"] | None = None, methods: dict[str, "TypeInfo"] | None = None) -> "TypeInfo":
        return TypeInfo(kind=TypeKind.CLASS, name=name, fields=fields or {}, methods=methods or {})

    @staticmethod
    def create_any() -> "TypeInfo":
        return TypeInfo(kind=TypeKind.ANY, name="any")


# 常用类型实例
INT_TYPE = TypeInfo.create_int()
FLOAT_TYPE = TypeInfo.create_float()
BOOL_TYPE = TypeInfo.create_bool()
STRING_TYPE = TypeInfo.create_string()
VOID_TYPE = TypeInfo.create_void()
NULL_TYPE = TypeInfo.create_null()
ANY_TYPE = TypeInfo.create_any()