"""
AI 编译器工具链 - IR 变换
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
    INT_TYPE, FLOAT_TYPE, BOOL_TYPE, STRING_TYPE, VOID_TYPE,
)
from src.middle.ir import (
    IRModule, IRFunction, IRInstruction, IRValue, IRValueType, BasicBlock,
    IROpcode, IRBuilder, IRGlobal,
    create_constant_int, create_constant_float, create_constant_bool, create_constant_string,
)
from src.utils.errors import InternalError, ErrorReporter


class ASTToIRConverter(ASTVisitor):
    """AST 到 IR 的转换器"""

    def __init__(self, ir_module: Optional[IRModule] = None, error_reporter: Optional[ErrorReporter] = None):
        self.ir_module: IRModule = ir_module or IRModule("main")
        self.builder: IRBuilder = IRBuilder(self.ir_module)
        self.error_reporter: ErrorReporter = error_reporter or ErrorReporter()

        # 变量映射: AST 变量名 -> IR 值
        self._var_map: dict[str, IRValue] = {}
        self._in_loop: bool = False
        self._loop_continue_labels: list[str] = []
        self._loop_break_labels: list[str] = []
        self._value_map: dict[ASTNode, IRValue] = {}

    def convert(self, program: Program) -> IRModule:
        """将 AST 程序转换为 IR"""
        for module in program.modules:
            self.ir_module.name = module.name
            for decl in module.declarations:
                self.visit(decl)
        return self.ir_module

    def _type_to_ir_type(self, type_info: TypeInfo) -> IRValueType:
        """将 TypeInfo 转换为 IRValueType"""
        mapping = {
            TypeKind.INTEGER: IRValueType.INT32,
            TypeKind.FLOAT: IRValueType.FLOAT64,
            TypeKind.BOOLEAN: IRValueType.INT1,
            TypeKind.STRING: IRValueType.STRING,
            TypeKind.VOID: IRValueType.VOID,
            TypeKind.ARRAY: IRValueType.ARRAY,
            TypeKind.TENSOR: IRValueType.TENSOR,
        }
        return mapping.get(type_info.kind, IRValueType.INT32)

    def _ast_type_to_ir_type(self, type_node: Optional[ASTNode]) -> IRValueType:
        """将 AST 类型节点转换为 IR 类型"""
        if type_node is None:
            return IRValueType.INT32
        if isinstance(type_node, TypeAnnotation):
            mapping = {
                "int": IRValueType.INT32, "float": IRValueType.FLOAT64,
                "bool": IRValueType.INT1, "string": IRValueType.STRING,
                "void": IRValueType.VOID, "array": IRValueType.ARRAY,
                "tensor": IRValueType.TENSOR,
            }
            return mapping.get(type_node.name, IRValueType.INT32)
        if isinstance(type_node, ArrayType):
            return IRValueType.ARRAY
        if isinstance(type_node, TensorType):
            return IRValueType.TENSOR
        return IRValueType.INT32

    def visit_Program(self, node: Program) -> Any:
        for module in node.modules:
            self.visit(module)

    def visit_Module(self, node: Module) -> Any:
        for decl in node.declarations:
            self.visit(decl)

    def visit_FunctionDecl(self, node: FunctionDecl) -> Any:
        # 确定参数类型
        ir_params = []
        for param in node.params:
            param_type = self._ast_type_to_ir_type(param.type_annotation)
            ir_params.append(IRValue(f"%{param.name}", param_type))

        # 确定返回类型
        return_type = self._ast_type_to_ir_type(node.return_type)

        # 创建 IR 函数
        func = self.builder.new_function(node.name, return_type, ir_params)

        # 分配参数
        for param, ir_param in zip(node.params, ir_params):
            ptr = self.builder.emit_alloc(ir_param.value_type, comment=f"param {param.name}")
            self.builder.emit_store(ptr, ir_param, comment=f"store {param.name}")
            self._var_map[param.name] = ir_param

        # 转换函数体
        if node.body:
            self.visit(node.body)

        # 确保函数有返回
        if not func.entry_block or not func.entry_block.instructions or not func.entry_block.instructions[-1].is_terminator():
            self.builder.emit_return(None, comment="implicit return")

    def visit_Block(self, node: Block) -> Any:
        for stmt in node.statements:
            self.visit(stmt)

    def visit_VariableDecl(self, node: VariableDecl) -> Any:
        var_type = self._ast_type_to_ir_type(node.type_annotation)
        ptr = self.builder.emit_alloc(var_type, comment=f"alloc {node.name}")
        if node.initializer:
            value = self.visit(node.initializer)
            if value:
                if isinstance(value, IRValue):
                    self.builder.emit_store(ptr, value, comment=f"init {node.name}")
                    self._var_map[node.name] = value
                else:
                    self._var_map[node.name] = IRValue(f"%{node.name}", var_type)
            else:
                self._var_map[node.name] = IRValue(f"%{node.name}", var_type)
        else:
            self._var_map[node.name] = IRValue(f"%{node.name}", var_type)

    def visit_ExpressionStmt(self, node: ExpressionStmt) -> Any:
        self.visit(node.expression)

    def visit_IfStmt(self, node: IfStmt) -> Any:
        cond = self.visit(node.condition)
        if not cond:
            return

        else_label = self.builder.new_label("else")
        end_label = self.builder.new_label("if_end")

        # 条件跳转
        self.builder.emit_if_goto(cond, else_label, comment="if condition false -> else")

        # then 分支
        self.visit(node.then_body)
        self.builder.emit_goto(end_label, comment="jump to if_end")

        # else 分支
        self.builder.emit_label(else_label)
        if node.else_body:
            self.visit(node.else_body)
        self.builder.emit_goto(end_label, comment="jump to if_end")

        # 结束标签
        self.builder.emit_label(end_label)

    def visit_WhileStmt(self, node: WhileStmt) -> Any:
        loop_start = self.builder.new_label("loop_start")
        loop_end = self.builder.new_label("loop_end")

        self._loop_continue_labels.append(loop_start)
        self._loop_break_labels.append(loop_end)

        self.builder.emit_label(loop_start)
        cond = self.visit(node.condition)
        if cond:
            self.builder.emit_if_goto(cond, loop_end, comment="while condition false -> end")

        self._in_loop = True
        self.visit(node.body)
        self.builder.emit_goto(loop_start, comment="loop back")

        self.builder.emit_label(loop_end)

        self._loop_continue_labels.pop()
        self._loop_break_labels.pop()
        self._in_loop = False

    def visit_ForStmt(self, node: ForStmt) -> Any:
        loop_start = self.builder.new_label("for_start")
        loop_body = self.builder.new_label("for_body")
        loop_end = self.builder.new_label("for_end")

        self._loop_continue_labels.append(loop_start)
        self._loop_break_labels.append(loop_end)

        # 初始化
        if node.init:
            self.visit(node.init)

        self.builder.emit_goto(loop_start, comment="for loop start")

        # 条件
        self.builder.emit_label(loop_start)
        if node.condition:
            cond = self.visit(node.condition)
            if cond:
                self.builder.emit_if_goto(cond, loop_end, comment="for condition false -> end")
        self.builder.emit_goto(loop_body, comment="jump to body")

        # 循环体
        self.builder.emit_label(loop_body)
        self._in_loop = True
        self.visit(node.body)
        self._in_loop = False

        # 更新
        if node.update:
            self.visit(node.update)

        self.builder.emit_goto(loop_start, comment="loop back")
        self.builder.emit_label(loop_end)

        self._loop_continue_labels.pop()
        self._loop_break_labels.pop()

    def visit_BreakStmt(self, node: BreakStmt) -> Any:
        if self._loop_break_labels:
            self.builder.emit_goto(self._loop_break_labels[-1], comment="break")

    def visit_ContinueStmt(self, node: ContinueStmt) -> Any:
        if self._loop_continue_labels:
            self.builder.emit_goto(self._loop_continue_labels[-1], comment="continue")

    def visit_ReturnStmt(self, node: ReturnStmt) -> Any:
        if node.value:
            value = self.visit(node.value)
            if value:
                self.builder.emit_return(value, comment="return")
        else:
            self.builder.emit_return(None, comment="return")

    def visit_BinaryOp(self, node: BinaryOp) -> Optional[IRValue]:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if not left or not right:
            return None

        from src.frontend.token import TokenType
        op_type = node.op.type

        # 算术运算
        if op_type == TokenType.PLUS:
            return self.builder.emit_add(left, right)
        elif op_type == TokenType.MINUS:
            return self.builder.emit_sub(left, right)
        elif op_type == TokenType.STAR:
            return self.builder.emit_mul(left, right)
        elif op_type == TokenType.SLASH:
            dest = self.builder.new_temp(left.value_type)
            opcode = IROpcode.DIV_F if left.value_type == IRValueType.FLOAT64 else IROpcode.DIV_I
            self.builder.emit(opcode, dest, [left, right])
            return dest
        elif op_type == TokenType.PERCENT:
            dest = self.builder.new_temp(IRValueType.INT32)
            self.builder.emit(IROpcode.MOD_I, dest, [left, right])
            return dest

        # 比较运算
        elif op_type == TokenType.EQUAL_EQUAL:
            return self.builder.emit_icmp("eq", left, right)
        elif op_type == TokenType.NOT_EQUAL:
            return self.builder.emit_icmp("ne", left, right)
        elif op_type == TokenType.LESS:
            return self.builder.emit_icmp("lt", left, right)
        elif op_type == TokenType.GREATER:
            return self.builder.emit_icmp("gt", left, right)
        elif op_type == TokenType.LESS_EQUAL:
            return self.builder.emit_icmp("le", left, right)
        elif op_type == TokenType.GREATER_EQUAL:
            return self.builder.emit_icmp("ge", left, right)

        # 逻辑运算
        elif op_type == TokenType.AND:
            dest = self.builder.new_temp(IRValueType.INT1)
            self.builder.emit(IROpcode.AND_I, dest, [left, right])
            return dest
        elif op_type == TokenType.OR:
            dest = self.builder.new_temp(IRValueType.INT1)
            self.builder.emit(IROpcode.OR_I, dest, [left, right])
            return dest

        # 位运算
        elif op_type == TokenType.BIT_AND:
            dest = self.builder.new_temp(IRValueType.INT32)
            self.builder.emit(IROpcode.AND_I, dest, [left, right])
            return dest
        elif op_type == TokenType.BIT_OR:
            dest = self.builder.new_temp(IRValueType.INT32)
            self.builder.emit(IROpcode.OR_I, dest, [left, right])
            return dest
        elif op_type == TokenType.BIT_XOR:
            dest = self.builder.new_temp(IRValueType.INT32)
            self.builder.emit(IROpcode.XOR_I, dest, [left, right])
            return dest
        elif op_type == TokenType.LEFT_SHIFT:
            dest = self.builder.new_temp(IRValueType.INT32)
            self.builder.emit(IROpcode.SHL, dest, [left, right])
            return dest
        elif op_type == TokenType.RIGHT_SHIFT:
            dest = self.builder.new_temp(IRValueType.INT32)
            self.builder.emit(IROpcode.SHR, dest, [left, right])
            return dest

        return None

    def visit_UnaryOp(self, node: UnaryOp) -> Optional[IRValue]:
        operand = self.visit(node.operand)
        if not operand:
            return None

        from src.frontend.token import TokenType
        op_type = node.op.type

        if op_type == TokenType.MINUS:
            dest = self.builder.new_temp(operand.value_type)
            self.builder.emit(IROpcode.NEG, dest, [operand])
            return dest
        elif op_type == TokenType.NOT:
            dest = self.builder.new_temp(IRValueType.INT1)
            self.builder.emit(IROpcode.NOT_I, dest, [operand])
            return dest
        elif op_type == TokenType.BIT_NOT:
            dest = self.builder.new_temp(IRValueType.INT32)
            self.builder.emit(IROpcode.NOT_I, dest, [operand])
            return dest

        return None

    def visit_Assignment(self, node: Assignment) -> Optional[IRValue]:
        value = self.visit(node.value)
        if not value:
            return None

        if isinstance(node.target, Identifier):
            name = node.target.name
            if name in self._var_map:
                # 存储到变量
                ptr = self._var_map[name]
                self.builder.emit_store(ptr, value, comment=f"assign {name}")
                self._var_map[name] = value
                return value

        return value

    def visit_Call(self, node: Call) -> Optional[IRValue]:
        args = []
        for arg in node.args:
            arg_val = self.visit(arg)
            if arg_val:
                args.append(arg_val)

        if isinstance(node.callee, Identifier):
            func_name = node.callee.name
            ret_type = IRValueType.INT32  # 默认
            return self.builder.emit_call(func_name, args, ret_type)

        return None

    def visit_Identifier(self, node: Identifier) -> Optional[IRValue]:
        if node.name in self._var_map:
            return self._var_map[node.name]
        # 检查是否为常量
        if node.name == "true":
            return create_constant_bool(True)
        if node.name == "false":
            return create_constant_bool(False)
        if node.name == "null":
            return create_constant_int(0)
        return None

    def visit_IntegerLiteral(self, node: IntegerLiteral) -> IRValue:
        return create_constant_int(node.value)

    def visit_FloatLiteral(self, node: FloatLiteral) -> IRValue:
        return create_constant_float(node.value)

    def visit_StringLiteral(self, node: StringLiteral) -> IRValue:
        return create_constant_string(node.value)

    def visit_BooleanLiteral(self, node: BooleanLiteral) -> IRValue:
        return create_constant_bool(node.value)

    def visit_NullLiteral(self, node: NullLiteral) -> IRValue:
        return create_constant_int(0)

    def visit_ArrayLiteral(self, node: ArrayLiteral) -> IRValue:
        # 简化处理：数组元素逐个处理
        for elem in node.elements:
            self.visit(elem)
        return create_constant_int(0)  # placeholder

    def visit_RecordLiteral(self, node: RecordLiteral) -> IRValue:
        return create_constant_int(0)

    def visit_Access(self, node: Access) -> Optional[IRValue]:
        obj = self.visit(node.obj)
        key = self.visit(node.key)
        return obj

    def visit_AssertStmt(self, node: AssertStmt) -> Any:
        self.visit(node.condition)

    def visit_DeferStmt(self, node: DeferStmt) -> Any:
        self.visit(node.call)

    def visit_MatchStmt(self, node: MatchStmt) -> Any:
        target = self.visit(node.target)
        end_label = self.builder.new_label("match_end")
        for pattern, body in node.arms:
            self.visit(body)
            self.builder.emit_goto(end_label)
        self.builder.emit_label(end_label)

    def visit_ImportDecl(self, node: ImportDecl) -> Any:
        pass

    def visit_ExportDecl(self, node: ExportDecl) -> Any:
        self.visit(node.declaration)

    def visit_TypeDecl(self, node: TypeDecl) -> Any:
        pass

    def visit_TypeAnnotation(self, node: TypeAnnotation) -> Any:
        pass

    def visit_ArrayType(self, node: ArrayType) -> Any:
        pass

    def visit_TensorType(self, node: TensorType) -> Any:
        pass

    def visit_FunctionType(self, node: FunctionType) -> Any:
        pass

    def visit_Parameter(self, node: Parameter) -> Any:
        pass

    def visit_TernaryExpr(self, node: TernaryExpr) -> Optional[IRValue]:
        cond = self.visit(node.condition)
        else_label = self.builder.new_label("ternary_else")
        end_label = self.builder.new_label("ternary_end")
        if cond:
            self.builder.emit_if_goto(cond, else_label)
        then_val = self.visit(node.then_expr)
        self.builder.emit_goto(end_label)
        self.builder.emit_label(else_label)
        else_val = self.visit(node.else_expr)
        self.builder.emit_goto(end_label)
        self.builder.emit_label(end_label)
        return then_val or else_val

    def visit_CastExpr(self, node: CastExpr) -> Optional[IRValue]:
        return self.visit(node.expr)

    def visit_LambdaExpr(self, node: LambdaExpr) -> Any:
        return None

    def visit_ForInStmt(self, node: ForInStmt) -> Any:
        self.visit(node.target)
        self.visit(node.iterable)
        self.visit(node.body)

    def visit_MatchPattern(self, node: MatchPattern) -> Any:
        pass


class IRTransform:
    """IR 变换工具"""

    @staticmethod
    def remove_unreachable_blocks(ir_module: IRModule) -> IRModule:
        """移除不可达基本块"""
        for func in ir_module.functions.values():
            # 标记可达基本块
            reachable: set[str] = set()
            worklist = [func.entry_block] if func.entry_block else []
            visited: set[str] = set()

            while worklist:
                block = worklist.pop()
                if block.name in visited:
                    continue
                visited.add(block.name)
                reachable.add(block.name)
                for succ in block.successors:
                    if succ.name not in visited:
                        worklist.append(succ)

            # 移除不可达块
            func.blocks = [b for b in func.blocks if b.name in reachable]

        return ir_module

    @staticmethod
    def merge_blocks(ir_module: IRModule) -> IRModule:
        """合并连续基本块"""
        for func in ir_module.functions.values():
            i = 0
            while i < len(func.blocks) - 1:
                current = func.blocks[i]
                next_block = func.blocks[i + 1]

                # 如果当前块以无条件跳转到下一块结束
                if (current.instructions and current.instructions[-1].opcode == IROpcode.GOTO
                        and current.instructions[-1].label == next_block.name):
                    # 移除跳转指令
                    current.instructions.pop()
                    # 合并指令
                    current.instructions.extend(next_block.instructions)
                    # 更新后继
                    current.successors = next_block.successors
                    for succ in next_block.successors:
                        for j, pred in enumerate(succ.predecessors):
                            if pred.name == next_block.name:
                                succ.predecessors[j] = current
                    # 移除下一块
                    func.blocks.pop(i + 1)
                else:
                    i += 1

        return ir_module

    @staticmethod
    def simplify_cfg(ir_module: IRModule) -> IRModule:
        """简化控制流图"""
        ir_module = IRTransform.remove_unreachable_blocks(ir_module)
        ir_module = IRTransform.merge_blocks(ir_module)
        return ir_module

    @staticmethod
    def convert_to_ssa(ir_module: IRModule) -> IRModule:
        """转换为 SSA 形式（简化实现）"""
        for func in ir_module.functions.values():
            for block in func.blocks:
                # 在每个基本块开头插入 phi 指令（简化）
                if block.predecessors and len(block.predecessors) > 1:
                    # 检查是否有需要 phi 的变量
                    defined_vars: set[str] = set()
                    for instr in block.instructions:
                        if instr.dest:
                            defined_vars.add(instr.dest.name)
        return ir_module

    @staticmethod
    def verify_ir(ir_module: IRModule) -> list[str]:
        """验证 IR 的正确性"""
        errors = []
        for func_name, func in ir_module.functions.items():
            if not func.blocks:
                errors.append(f"函数 '{func_name}' 没有基本块")
                continue
            for block in func.blocks:
                if not block.instructions:
                    continue
                # 检查终止指令
                last_instr = block.instructions[-1]
                if not last_instr.is_terminator():
                    errors.append(f"基本块 '{block.name}' 在函数 '{func_name}' 中缺少终止指令")
                # 检查终止指令位置
                for instr in block.instructions[:-1]:
                    if instr.is_terminator():
                        errors.append(f"基本块 '{block.name}' 在函数 '{func_name}' 中终止指令不在末尾")
        return errors

    @staticmethod
    def print_ir(ir_module: IRModule) -> str:
        """打印 IR"""
        return str(ir_module)