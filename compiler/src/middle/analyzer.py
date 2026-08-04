"""
AI 编译器工具链 - 语义分析器
"""

from __future__ import annotations

from typing import Optional, Any

from src.frontend.ast import (
    ASTNode, ASTVisitor,
    IntegerLiteral, FloatLiteral, StringLiteral, BooleanLiteral, NullLiteral,
    Identifier, BinaryOp, UnaryOp, Assignment, Call, Access,
    ArrayLiteral, RecordLiteral, LambdaExpr, TernaryExpr, CastExpr,
    TypeAnnotation, ArrayType, TensorType, FunctionType,
    Parameter, VariableDecl, Block, IfStmt, WhileStmt, ForStmt, ForInStmt,
    BreakStmt, ContinueStmt, ReturnStmt, AssertStmt, DeferStmt, MatchStmt,
    ExpressionStmt, FunctionDecl, ClassDecl, ImportDecl, ExportDecl,
    TypeDecl, Module, Program, MatchPattern,
    TypeInfo, TypeKind,
    INT_TYPE, FLOAT_TYPE, BOOL_TYPE, STRING_TYPE, VOID_TYPE, NULL_TYPE, ANY_TYPE,
)
from src.utils.errors import SemanticError, TypeError, NameError, ErrorReporter


class Symbol:
    """符号表中的符号"""

    def __init__(self, name: str, type_info: TypeInfo, kind: str = "variable",
                 is_mutable: bool = False, is_exported: bool = False,
                 node: Optional[ASTNode] = None, line: int = 0, column: int = 0):
        self.name = name
        self.type_info = type_info
        self.kind = kind  # "variable", "function", "class", "type", "parameter"
        self.is_mutable = is_mutable
        self.is_exported = is_exported
        self.node = node
        self.line = line
        self.column = column

    def __repr__(self) -> str:
        return f"Symbol({self.name}, {self.type_info}, kind={self.kind})"


class Scope:
    """作用域"""

    def __init__(self, name: str = "global", parent: Optional["Scope"] = None):
        self.name = name
        self.parent = parent
        self.symbols: dict[str, Symbol] = {}
        self.children: list["Scope"] = []

    def define(self, symbol: Symbol) -> bool:
        """定义符号，返回是否成功（False 表示重定义）"""
        if symbol.name in self.symbols:
            return False
        self.symbols[symbol.name] = symbol
        return True

    def lookup(self, name: str) -> Optional[Symbol]:
        """查找符号（包括父作用域）"""
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def lookup_local(self, name: str) -> Optional[Symbol]:
        """仅在当前作用域查找"""
        return self.symbols.get(name)

    def add_child(self, scope: "Scope") -> None:
        """添加子作用域"""
        self.children.append(scope)

    def __repr__(self) -> str:
        symbols = ", ".join(self.symbols.keys())
        return f"Scope({self.name}, {{{symbols}}})"


class SymbolTable:
    """符号表"""

    def __init__(self):
        self.global_scope = Scope("global", None)
        self.current_scope = self.global_scope
        self._scope_counter = 0

    def enter_scope(self, name: str = "") -> Scope:
        """进入新作用域"""
        if not name:
            self._scope_counter += 1
            name = f"block_{self._scope_counter}"
        new_scope = Scope(name, self.current_scope)
        self.current_scope.add_child(new_scope)
        self.current_scope = new_scope
        return new_scope

    def exit_scope(self) -> Optional[Scope]:
        """退出当前作用域"""
        parent = self.current_scope.parent
        if parent:
            self.current_scope = parent
        return parent

    def define(self, symbol: Symbol) -> bool:
        """在当前作用域定义符号"""
        return self.current_scope.define(symbol)

    def lookup(self, name: str) -> Optional[Symbol]:
        """查找符号"""
        return self.current_scope.lookup(name)

    def lookup_local(self, name: str) -> Optional[Symbol]:
        """在当前作用域查找"""
        return self.current_scope.lookup_local(name)

    def __repr__(self) -> str:
        return f"SymbolTable(current={self.current_scope.name})"


class SemanticAnalyzer(ASTVisitor):
    """语义分析器 - 类型检查、符号表、作用域管理"""

    def __init__(self, error_reporter: Optional[ErrorReporter] = None):
        self.error_reporter: ErrorReporter = error_reporter or ErrorReporter()
        self.symbol_table: SymbolTable = SymbolTable()
        self.current_function: Optional[FunctionDecl] = None
        self.current_class: Optional[ClassDecl] = None
        self._loop_depth: int = 0
        self._type_cache: dict[ASTNode, TypeInfo] = {}

    def analyze(self, program: Program) -> Program:
        """分析程序"""
        # 第一遍: 注册所有顶层声明
        for module in program.modules:
            for decl in module.declarations:
                self._register_top_level_decl(decl)

        # 第二遍: 类型检查和语义分析
        for module in program.modules:
            for decl in module.declarations:
                self.visit(decl)

        return program

    def _register_top_level_decl(self, decl: ASTNode) -> None:
        """注册顶层声明"""
        if isinstance(decl, FunctionDecl):
            # 创建函数类型
            param_types = []
            for param in decl.params:
                ptype = self._type_annotation_to_type(param.type_annotation) if param.type_annotation else ANY_TYPE
                param_types.append(ptype)
            return_type = self._type_annotation_to_type(decl.return_type) if decl.return_type else VOID_TYPE
            func_type = TypeInfo.create_function(param_types, return_type)
            symbol = Symbol(decl.name, func_type, "function", node=decl, line=decl.line, column=decl.column)
            if not self.symbol_table.define(symbol):
                self.error_reporter.report_error(
                    SemanticError(f"重复定义函数 '{decl.name}'", decl.line, decl.column)
                )
        elif isinstance(decl, ClassDecl):
            class_type = TypeInfo.create_class(decl.name)
            symbol = Symbol(decl.name, class_type, "class", node=decl, line=decl.line, column=decl.column)
            if not self.symbol_table.define(symbol):
                self.error_reporter.report_error(
                    SemanticError(f"重复定义类 '{decl.name}'", decl.line, decl.column)
                )
        elif isinstance(decl, VariableDecl):
            var_type = self._type_annotation_to_type(decl.type_annotation) if decl.type_annotation else ANY_TYPE
            symbol = Symbol(decl.name, var_type, "variable", decl.mutable, decl.is_exported, decl, decl.line, decl.column)
            if not self.symbol_table.define(symbol):
                self.error_reporter.report_error(
                    SemanticError(f"重复定义变量 '{decl.name}'", decl.line, decl.column)
                )

    def _type_annotation_to_type(self, annotation: Optional[ASTNode]) -> TypeInfo:
        """将类型注解 AST 节点转换为 TypeInfo"""
        if annotation is None:
            return ANY_TYPE
        if isinstance(annotation, TypeAnnotation):
            mapping = {
                "int": INT_TYPE, "float": FLOAT_TYPE, "bool": BOOL_TYPE,
                "string": STRING_TYPE, "void": VOID_TYPE, "any": ANY_TYPE,
            }
            if annotation.name in mapping:
                return mapping[annotation.name]
            # 自定义类型
            symbol = self.symbol_table.lookup(annotation.name)
            if symbol and symbol.type_info:
                return symbol.type_info
            return ANY_TYPE
        elif isinstance(annotation, ArrayType):
            elem_type = self._type_annotation_to_type(annotation.element_type)
            return TypeInfo.create_array(elem_type)
        elif isinstance(annotation, TensorType):
            elem_type = self._type_annotation_to_type(annotation.element_type)
            shape = []
            for dim in annotation.shape:
                if isinstance(dim, IntegerLiteral):
                    shape.append(dim.value)
            return TypeInfo.create_tensor(elem_type, shape)
        elif isinstance(annotation, FunctionType):
            param_types = [self._type_annotation_to_type(pt) for pt in annotation.param_types]
            return_type = self._type_annotation_to_type(annotation.return_type)
            return TypeInfo.create_function(param_types, return_type)
        return ANY_TYPE

    def _get_type(self, node: ASTNode) -> TypeInfo:
        """获取表达式的类型"""
        if node in self._type_cache:
            return self._type_cache[node]
        if isinstance(node, IntegerLiteral):
            return INT_TYPE
        elif isinstance(node, FloatLiteral):
            return FLOAT_TYPE
        elif isinstance(node, StringLiteral):
            return STRING_TYPE
        elif isinstance(node, BooleanLiteral):
            return BOOL_TYPE
        elif isinstance(node, NullLiteral):
            return NULL_TYPE
        elif isinstance(node, Identifier):
            symbol = self.symbol_table.lookup(node.name)
            if symbol:
                return symbol.type_info
            self.error_reporter.report_error(
                NameError(f"未定义的标识符 '{node.name}'", node.line, node.column)
            )
            return ANY_TYPE
        elif isinstance(node, BinaryOp):
            return self._infer_binary_op_type(node)
        elif isinstance(node, UnaryOp):
            return self._infer_unary_op_type(node)
        elif isinstance(node, Call):
            return self._infer_call_type(node)
        elif isinstance(node, Assignment):
            return self._get_type(node.value)
        elif isinstance(node, ArrayLiteral):
            if node.elements:
                elem_type = self._get_type(node.elements[0])
                return TypeInfo.create_array(elem_type)
            return TypeInfo.create_array(ANY_TYPE)
        elif isinstance(node, RecordLiteral):
            return TypeInfo(TypeKind.RECORD, "record")
        elif isinstance(node, LambdaExpr):
            param_types = [self._get_type(p) for p in node.params]
            return_type = self._type_annotation_to_type(node.return_type) if node.return_type else ANY_TYPE
            return TypeInfo.create_function(param_types, return_type)
        elif isinstance(node, TernaryExpr):
            then_type = self._get_type(node.then_expr)
            else_type = self._get_type(node.else_expr)
            if then_type.can_assign_to(else_type):
                return else_type
            return then_type
        elif isinstance(node, CastExpr):
            return self._type_annotation_to_type(node.target_type)
        elif isinstance(node, Access):
            obj_type = self._get_type(node.obj)
            if node.is_index:
                if obj_type.is_array() and obj_type.element_type:
                    return obj_type.element_type
                if obj_type.is_tensor() and obj_type.element_type:
                    return obj_type.element_type
                return ANY_TYPE
            else:
                # 属性访问
                if obj_type.is_class() or obj_type.kind == TypeKind.RECORD:
                    if isinstance(node.key, Identifier):
                        field_name = node.key.name
                        if field_name in obj_type.fields:
                            return obj_type.fields[field_name]
                        if field_name in obj_type.methods:
                            return obj_type.methods[field_name]
                return ANY_TYPE
        return ANY_TYPE

    def _infer_binary_op_type(self, node: BinaryOp) -> TypeInfo:
        """推断二元运算结果类型"""
        left_type = self._get_type(node.left)
        right_type = self._get_type(node.right)
        op_type = node.op.type

        # 比较运算返回 bool
        from src.frontend.token import TokenType
        if op_type in (TokenType.EQUAL_EQUAL, TokenType.NOT_EQUAL, TokenType.LESS,
                       TokenType.GREATER, TokenType.LESS_EQUAL, TokenType.GREATER_EQUAL):
            return BOOL_TYPE

        # 逻辑运算返回 bool
        if op_type in (TokenType.AND, TokenType.OR):
            return BOOL_TYPE

        # 算术运算
        if left_type.is_float_point() or right_type.is_float_point():
            return FLOAT_TYPE
        if left_type.is_numeric() and right_type.is_numeric():
            return INT_TYPE

        # 字符串拼接
        if op_type == TokenType.PLUS and left_type.is_string() and right_type.is_string():
            return STRING_TYPE

        return ANY_TYPE

    def _infer_unary_op_type(self, node: UnaryOp) -> TypeInfo:
        """推断一元运算结果类型"""
        operand_type = self._get_type(node.operand)
        from src.frontend.token import TokenType
        if node.op.type in (TokenType.NOT,):
            return BOOL_TYPE
        if node.op.type in (TokenType.MINUS, TokenType.PLUS, TokenType.BIT_NOT):
            return operand_type
        if node.op.type in (TokenType.PLUS_PLUS, TokenType.MINUS_MINUS):
            return operand_type
        return operand_type

    def _infer_call_type(self, node: Call) -> TypeInfo:
        """推断函数调用结果类型"""
        if isinstance(node.callee, Identifier):
            symbol = self.symbol_table.lookup(node.callee.name)
            if symbol and symbol.type_info.is_function() and symbol.type_info.return_type:
                return symbol.type_info.return_type
        # 检查 lambda 调用
        if isinstance(node.callee, LambdaExpr):
            return node.callee.return_type or ANY_TYPE
        return ANY_TYPE

    def _check_type_compatibility(self, expected: TypeInfo, actual: TypeInfo, node: ASTNode, context: str = "") -> bool:
        """检查类型兼容性"""
        if expected.is_any() or actual.is_any():
            return True
        if actual.can_assign_to(expected):
            return True
        self.error_reporter.report_error(
            TypeError(f"类型不匹配{': ' + context if context else ''}: 期望 {expected}，实际 {actual}",
                      node.line, node.column)
        )
        return False

    # ---------- 访问者方法 ----------

    def visit_Program(self, node: Program) -> Any:
        for module in node.modules:
            self.visit(module)

    def visit_Module(self, node: Module) -> Any:
        for decl in node.declarations:
            self.visit(decl)

    def visit_FunctionDecl(self, node: FunctionDecl) -> Any:
        prev_function = self.current_function
        self.current_function = node

        self.symbol_table.enter_scope(f"function_{node.name}")

        # 添加参数到符号表
        for param in node.params:
            self.visit(param)
            param_type = self._type_annotation_to_type(param.type_annotation) if param.type_annotation else ANY_TYPE
            symbol = Symbol(param.name, param_type, "parameter", param.mutable, node=param, line=param.line, column=param.column)
            self.symbol_table.define(symbol)

        # 分析函数体
        if node.body:
            self.visit(node.body)

        self.symbol_table.exit_scope()
        self.current_function = prev_function

    def visit_ClassDecl(self, node: ClassDecl) -> Any:
        prev_class = self.current_class
        self.current_class = node

        self.symbol_table.enter_scope(f"class_{node.name}")
        for member in node.body:
            self.visit(member)
        self.symbol_table.exit_scope()

        self.current_class = prev_class

    def visit_VariableDecl(self, node: VariableDecl) -> Any:
        # 推断类型
        declared_type = self._type_annotation_to_type(node.type_annotation) if node.type_annotation else None
        init_type = None

        if node.initializer:
            init_type = self._get_type(node.initializer)
            self.visit(node.initializer)

        # 类型检查
        if declared_type and init_type:
            self._check_type_compatibility(declared_type, init_type, node, f"变量 '{node.name}' 初始化")

        # 确定最终类型
        final_type = declared_type or init_type or ANY_TYPE

        # 更新符号
        symbol = self.symbol_table.lookup_local(node.name)
        if symbol:
            symbol.type_info = final_type
        else:
            symbol = Symbol(node.name, final_type, "variable", node.mutable, node.is_exported, node, node.line, node.column)
            self.symbol_table.define(symbol)

    def visit_Parameter(self, node: Parameter) -> Any:
        if node.type_annotation:
            self.visit(node.type_annotation)
        if node.default_value:
            self.visit(node.default_value)

    def visit_Block(self, node: Block) -> Any:
        self.symbol_table.enter_scope("block")
        for stmt in node.statements:
            self.visit(stmt)
        self.symbol_table.exit_scope()

    def visit_IfStmt(self, node: IfStmt) -> Any:
        cond_type = self._get_type(node.condition)
        self.visit(node.condition)
        if not cond_type.is_boolean() and not cond_type.is_any():
            self.error_reporter.report_error(
                TypeError(f"if 条件需要 bool 类型，实际为 {cond_type}", node.condition.line, node.condition.column)
            )
        self.visit(node.then_body)
        if node.else_body:
            self.visit(node.else_body)

    def visit_WhileStmt(self, node: WhileStmt) -> Any:
        cond_type = self._get_type(node.condition)
        self.visit(node.condition)
        if not cond_type.is_boolean() and not cond_type.is_any():
            self.error_reporter.report_error(
                TypeError(f"while 条件需要 bool 类型，实际为 {cond_type}", node.condition.line, node.condition.column)
            )
        self._loop_depth += 1
        self.visit(node.body)
        self._loop_depth -= 1

    def visit_ForStmt(self, node: ForStmt) -> Any:
        self._loop_depth += 1
        self.symbol_table.enter_scope("for")
        if node.init:
            self.visit(node.init)
        if node.condition:
            cond_type = self._get_type(node.condition)
            self.visit(node.condition)
            if not cond_type.is_boolean() and not cond_type.is_any():
                self.error_reporter.report_error(
                    TypeError(f"for 条件需要 bool 类型，实际为 {cond_type}", node.condition.line, node.condition.column)
                )
        if node.update:
            self.visit(node.update)
        self.visit(node.body)
        self.symbol_table.exit_scope()
        self._loop_depth -= 1

    def visit_ForInStmt(self, node: ForInStmt) -> Any:
        self._loop_depth += 1
        self.symbol_table.enter_scope("for_in")
        self.visit(node.target)
        self.visit(node.iterable)
        self.visit(node.body)
        self.symbol_table.exit_scope()
        self._loop_depth -= 1

    def visit_ReturnStmt(self, node: ReturnStmt) -> Any:
        if node.value:
            self.visit(node.value)
            ret_type = self._get_type(node.value)
            if self.current_function:
                expected_type = self._type_annotation_to_type(self.current_function.return_type) if self.current_function.return_type else VOID_TYPE
                self._check_type_compatibility(expected_type, ret_type, node, "return 类型")
        else:
            if self.current_function and self.current_function.return_type:
                ret_type = self._type_annotation_to_type(self.current_function.return_type)
                if not ret_type.is_void() and not ret_type.is_any():
                    self.error_reporter.report_error(
                        TypeError(f"函数需要返回 {ret_type}，但 return 没有值", node.line, node.column)
                    )

    def visit_BreakStmt(self, node: BreakStmt) -> Any:
        if self._loop_depth == 0:
            self.error_reporter.report_error(
                SemanticError("break 语句不在循环中", node.line, node.column)
            )

    def visit_ContinueStmt(self, node: ContinueStmt) -> Any:
        if self._loop_depth == 0:
            self.error_reporter.report_error(
                SemanticError("continue 语句不在循环中", node.line, node.column)
            )

    def visit_ExpressionStmt(self, node: ExpressionStmt) -> Any:
        self.visit(node.expression)

    def visit_BinaryOp(self, node: BinaryOp) -> Any:
        self.visit(node.left)
        self.visit(node.right)
        left_type = self._get_type(node.left)
        right_type = self._get_type(node.right)
        self._type_cache[node] = self._infer_binary_op_type(node)

    def visit_UnaryOp(self, node: UnaryOp) -> Any:
        self.visit(node.operand)
        self._type_cache[node] = self._infer_unary_op_type(node)

    def visit_Assignment(self, node: Assignment) -> Any:
        self.visit(node.target)
        self.visit(node.value)
        target_type = self._get_type(node.target)
        value_type = self._get_type(node.value)
        self._check_type_compatibility(target_type, value_type, node, "赋值")

        # 检查可变性
        if isinstance(node.target, Identifier):
            symbol = self.symbol_table.lookup(node.target.name)
            if symbol and not symbol.is_mutable:
                self.error_reporter.report_error(
                    SemanticError(f"不能修改不可变变量 '{node.target.name}'", node.target.line, node.target.column)
                )

    def visit_Call(self, node: Call) -> Any:
        self.visit(node.callee)
        for arg in node.args:
            self.visit(arg)

        # 检查参数数量
        if isinstance(node.callee, Identifier):
            symbol = self.symbol_table.lookup(node.callee.name)
            if symbol and symbol.type_info.is_function():
                expected_count = len(symbol.type_info.param_types)
                actual_count = len(node.args)
                if expected_count != actual_count:
                    self.error_reporter.report_error(
                        TypeError(f"函数 '{node.callee.name}' 期望 {expected_count} 个参数，实际 {actual_count} 个",
                                  node.line, node.column)
                    )
                else:
                    for i, (arg, expected_type) in enumerate(zip(node.args, symbol.type_info.param_types)):
                        arg_type = self._get_type(arg)
                        self._check_type_compatibility(expected_type, arg_type, arg, f"参数 {i + 1}")

    def visit_Identifier(self, node: Identifier) -> Any:
        if node.name != "_":
            symbol = self.symbol_table.lookup(node.name)
            if not symbol:
                self.error_reporter.report_error(
                    NameError(f"未定义的标识符 '{node.name}'", node.line, node.column)
                )

    def visit_IntegerLiteral(self, node: IntegerLiteral) -> Any:
        pass

    def visit_FloatLiteral(self, node: FloatLiteral) -> Any:
        pass

    def visit_StringLiteral(self, node: StringLiteral) -> Any:
        pass

    def visit_BooleanLiteral(self, node: BooleanLiteral) -> Any:
        pass

    def visit_NullLiteral(self, node: NullLiteral) -> Any:
        pass

    def visit_ArrayLiteral(self, node: ArrayLiteral) -> Any:
        for elem in node.elements:
            self.visit(elem)

    def visit_RecordLiteral(self, node: RecordLiteral) -> Any:
        for key, val in node.entries:
            self.visit(key)
            self.visit(val)

    def visit_LambdaExpr(self, node: LambdaExpr) -> Any:
        self.symbol_table.enter_scope("lambda")
        for param in node.params:
            self.visit(param)
            param_type = self._type_annotation_to_type(param.type_annotation) if param.type_annotation else ANY_TYPE
            symbol = Symbol(param.name, param_type, "parameter", param.mutable, node=param, line=param.line, column=param.column)
            self.symbol_table.define(symbol)
        self.visit(node.body)
        self.symbol_table.exit_scope()

    def visit_TernaryExpr(self, node: TernaryExpr) -> Any:
        self.visit(node.condition)
        self.visit(node.then_expr)
        self.visit(node.else_expr)
        cond_type = self._get_type(node.condition)
        if not cond_type.is_boolean() and not cond_type.is_any():
            self.error_reporter.report_error(
                TypeError(f"三元表达式条件需要 bool 类型，实际为 {cond_type}", node.condition.line, node.condition.column)
            )

    def visit_CastExpr(self, node: CastExpr) -> Any:
        self.visit(node.expr)
        self.visit(node.target_type)

    def visit_Access(self, node: Access) -> Any:
        self.visit(node.obj)
        self.visit(node.key)

    def visit_AssertStmt(self, node: AssertStmt) -> Any:
        self.visit(node.condition)
        if node.message:
            self.visit(node.message)

    def visit_DeferStmt(self, node: DeferStmt) -> Any:
        self.visit(node.call)

    def visit_MatchStmt(self, node: MatchStmt) -> Any:
        self.visit(node.target)
        for pattern, body in node.arms:
            self.visit(pattern)
            self.visit(body)

    def visit_MatchPattern(self, node: MatchPattern) -> Any:
        pass

    def visit_ImportDecl(self, node: ImportDecl) -> Any:
        pass

    def visit_ExportDecl(self, node: ExportDecl) -> Any:
        self.visit(node.declaration)

    def visit_TypeDecl(self, node: TypeDecl) -> Any:
        pass

    def visit_TypeAnnotation(self, node: TypeAnnotation) -> Any:
        pass

    def visit_ArrayType(self, node: ArrayType) -> Any:
        self.visit(node.element_type)

    def visit_TensorType(self, node: TensorType) -> Any:
        self.visit(node.element_type)

    def visit_FunctionType(self, node: FunctionType) -> Any:
        for pt in node.param_types:
            self.visit(pt)
        self.visit(node.return_type)


class TypeChecker:
    """类型检查器（便捷包装）"""

    def __init__(self, error_reporter: Optional[ErrorReporter] = None):
        self.analyzer = SemanticAnalyzer(error_reporter)
        self.error_reporter = self.analyzer.error_reporter

    def check(self, program: Program) -> Program:
        """执行类型检查"""
        return self.analyzer.analyze(program)

    def get_type(self, node: ASTNode) -> TypeInfo:
        """获取节点类型"""
        return self.analyzer._get_type(node)