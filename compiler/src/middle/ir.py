"""
AI 编译器工具链 - 中间表示 (IR) 定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Any


class IROpcode(Enum):
    """IR 指令操作码"""
    # 控制流
    LABEL = auto()
    GOTO = auto()
    IF_GOTO = auto()
    PHI = auto()
    CALL = auto()
    RETURN = auto()
    RET = auto()
    HALT = auto()

    # 内存操作
    ALLOCA = auto()
    LOAD = auto()
    STORE = auto()
    MEMCPY = auto()
    GEP = auto()  # getelementptr

    # 算术运算
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    NEG = auto()

    # 整型算术
    ADD_I = auto()
    SUB_I = auto()
    MUL_I = auto()
    DIV_I = auto()
    MOD_I = auto()

    # 浮点算术
    ADD_F = auto()
    SUB_F = auto()
    MUL_F = auto()
    DIV_F = auto()

    # 位运算
    AND = auto()
    OR = auto()
    XOR = auto()
    NOT = auto()
    SHL = auto()
    SHR = auto()
    AND_I = auto()
    OR_I = auto()
    XOR_I = auto()
    NOT_I = auto()

    # 比较运算
    EQ = auto()
    NE = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    EQ_I = auto()
    NE_I = auto()
    LT_I = auto()
    GT_I = auto()
    LE_I = auto()
    GE_I = auto()
    EQ_F = auto()
    NE_F = auto()
    LT_F = auto()
    GT_F = auto()
    LE_F = auto()
    GE_F = auto()

    # 类型转换
    INT_TO_FLOAT = auto()
    FLOAT_TO_INT = auto()
    INT_TO_BOOL = auto()
    BOOL_TO_INT = auto()
    EXT = auto()  # 扩展
    TRUNC = auto()  # 截断

    # 特殊操作
    COPY = auto()
    ASSERT = auto()
    NOP = auto()
    COMMENT = auto()
    DEBUG = auto()

    # 张量操作
    TENSOR_INIT = auto()
    TENSOR_GET = auto()
    TENSOR_SET = auto()
    TENSOR_SHAPE = auto()
    TENSOR_RESHAPE = auto()
    TENSOR_SLICE = auto()
    MATMUL = auto()
    CONV2D = auto()
    RELU = auto()
    SIGMOID = auto()
    TANH = auto()
    SOFTMAX = auto()

    @classmethod
    def is_arithmetic(cls, opcode: IROpcode) -> bool:
        return opcode in {
            cls.ADD, cls.SUB, cls.MUL, cls.DIV, cls.MOD, cls.NEG,
            cls.ADD_I, cls.SUB_I, cls.MUL_I, cls.DIV_I, cls.MOD_I,
            cls.ADD_F, cls.SUB_F, cls.MUL_F, cls.DIV_F,
        }

    @classmethod
    def is_comparison(cls, opcode: IROpcode) -> bool:
        return opcode in {
            cls.EQ, cls.NE, cls.LT, cls.GT, cls.LE, cls.GE,
            cls.EQ_I, cls.NE_I, cls.LT_I, cls.GT_I, cls.LE_I, cls.GE_I,
            cls.EQ_F, cls.NE_F, cls.LT_F, cls.GT_F, cls.LE_F, cls.GE_F,
        }

    @classmethod
    def is_bitwise(cls, opcode: IROpcode) -> bool:
        return opcode in {
            cls.AND, cls.OR, cls.XOR, cls.NOT, cls.SHL, cls.SHR,
            cls.AND_I, cls.OR_I, cls.XOR_I, cls.NOT_I,
        }

    @classmethod
    def is_control_flow(cls, opcode: IROpcode) -> bool:
        return opcode in {
            cls.LABEL, cls.GOTO, cls.IF_GOTO, cls.PHI, cls.CALL, cls.RETURN, cls.RET, cls.HALT,
        }

    @classmethod
    def is_memory(cls, opcode: IROpcode) -> bool:
        return opcode in {cls.ALLOCA, cls.LOAD, cls.STORE, cls.MEMCPY, cls.GEP}

    @classmethod
    def is_tensor_op(cls, opcode: IROpcode) -> bool:
        return opcode in {
            cls.TENSOR_INIT, cls.TENSOR_GET, cls.TENSOR_SET, cls.TENSOR_SHAPE,
            cls.TENSOR_RESHAPE, cls.TENSOR_SLICE, cls.MATMUL, cls.CONV2D,
            cls.RELU, cls.SIGMOID, cls.TANH, cls.SOFTMAX,
        }

    @classmethod
    def is_conversion(cls, opcode: IROpcode) -> bool:
        return opcode in {
            cls.INT_TO_FLOAT, cls.FLOAT_TO_INT, cls.INT_TO_BOOL, cls.BOOL_TO_INT,
            cls.EXT, cls.TRUNC,
        }

    @classmethod
    def is_terminator(cls, opcode: IROpcode) -> bool:
        """是否为终止指令（基本块的最后一条）"""
        return opcode in {cls.GOTO, cls.IF_GOTO, cls.RETURN, cls.RET, cls.HALT}

    @classmethod
    def has_side_effects(cls, opcode: IROpcode) -> bool:
        """是否有副作用"""
        return opcode in {
            cls.STORE, cls.CALL, cls.RETURN, cls.RET, cls.GOTO, cls.IF_GOTO,
            cls.ASSERT, cls.TENSOR_SET, cls.STORE,
        }


class IRValueType(Enum):
    """IR 值类型"""
    VOID = auto()
    INT1 = auto()    # 1-bit (bool)
    INT8 = auto()
    INT16 = auto()
    INT32 = auto()
    INT64 = auto()
    UINT8 = auto()
    UINT16 = auto()
    UINT32 = auto()
    UINT64 = auto()
    FLOAT32 = auto()
    FLOAT64 = auto()
    POINTER = auto()
    ARRAY = auto()
    TENSOR = auto()
    FUNCTION = auto()
    STRUCT = auto()
    STRING = auto()

    @classmethod
    def from_string(cls, name: str) -> IRValueType:
        mapping = {
            "void": cls.VOID, "i1": cls.INT1, "i8": cls.INT8, "i16": cls.INT16,
            "i32": cls.INT32, "i64": cls.INT64, "u8": cls.UINT8, "u16": cls.UINT16,
            "u32": cls.UINT32, "u64": cls.UINT64, "f32": cls.FLOAT32, "f64": cls.FLOAT64,
            "ptr": cls.POINTER, "array": cls.ARRAY, "tensor": cls.TENSOR,
            "string": cls.STRING, "struct": cls.STRUCT,
        }
        return mapping.get(name.lower(), cls.INT32)

    def __str__(self) -> str:
        mapping = {
            self.VOID: "void", self.INT1: "i1", self.INT8: "i8", self.INT16: "i16",
            self.INT32: "i32", self.INT64: "i64", self.UINT8: "u8", self.UINT16: "u16",
            self.UINT32: "u32", self.UINT64: "u64", self.FLOAT32: "f32", self.FLOAT64: "f64",
            self.POINTER: "ptr", self.ARRAY: "array", self.TENSOR: "tensor",
            self.STRING: "string", self.STRUCT: "struct", self.FUNCTION: "fn",
        }
        return mapping.get(self, "unknown")


@dataclass
class IRValue:
    """IR 值"""
    name: str
    value_type: IRValueType
    value: Any = None
    is_constant: bool = False

    def __repr__(self) -> str:
        if self.is_constant:
            return f"{self.value_type} {self.value}"
        return f"{self.value_type} {self.name}"

    def __hash__(self) -> int:
        return hash((self.name, self.value_type))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, IRValue):
            return self.name == other.name and self.value_type == other.value_type
        return NotImplemented


@dataclass
class IRInstruction:
    """IR 指令"""
    opcode: IROpcode
    dest: Optional[IRValue] = None
    operands: list[IRValue] = field(default_factory=list)
    label: Optional[str] = None  # 标签名（用于 LABEL 指令）
    comment: str = ""  # 注释

    def __repr__(self) -> str:
        parts = []
        if self.opcode == IROpcode.LABEL:
            parts.append(f"{self.label}:")
            return " ".join(parts)
        if self.opcode == IROpcode.COMMENT:
            return f"  ; {self.comment}"
        if self.opcode == IROpcode.NOP:
            return "  nop"
        if self.opcode == IROpcode.GOTO:
            parts.append(f"  goto {self.label}")
            if self.comment:
                parts.append(f"  ; {self.comment}")
            return " ".join(parts)
        if self.opcode == IROpcode.IF_GOTO:
            cond = self.operands[0] if self.operands else None
            parts.append(f"  if {cond} goto {self.label}")
            if self.comment:
                parts.append(f"  ; {self.comment}")
            return " ".join(parts)
        # 通用格式化
        if self.dest:
            parts.append(f"  {self.dest} = ")
        parts.append(f"{self.opcode.name.lower()}")
        if self.operands:
            parts.append(" " + ", ".join(str(op) for op in self.operands))
        if self.label:
            parts.append(f" -> {self.label}")
        if self.comment:
            parts.append(f"  ; {self.comment}")
        return "".join(parts)

    def is_terminator(self) -> bool:
        """是否为终止指令"""
        return IROpcode.is_terminator(self.opcode)


@dataclass
class BasicBlock:
    """基本块"""
    name: str
    instructions: list[IRInstruction] = field(default_factory=list)
    predecessors: list["BasicBlock"] = field(default_factory=list)
    successors: list["BasicBlock"] = field(default_factory=list)

    def add_instruction(self, instr: IRInstruction) -> None:
        """添加指令"""
        self.instructions.append(instr)

    def add_predecessor(self, block: "BasicBlock") -> None:
        """添加前驱基本块"""
        if block not in self.predecessors:
            self.predecessors.append(block)

    def add_successor(self, block: "BasicBlock") -> None:
        """添加后继基本块"""
        if block not in self.successors:
            self.successors.append(block)

    def remove_instruction(self, instr: IRInstruction) -> None:
        """移除指令"""
        if instr in self.instructions:
            self.instructions.remove(instr)

    def replace_instruction(self, old: IRInstruction, new: IRInstruction) -> None:
        """替换指令"""
        idx = self.instructions.index(old)
        self.instructions[idx] = new

    def __repr__(self) -> str:
        lines = [f"  {self.name}:"]
        for instr in self.instructions:
            lines.append(f"    {instr}")
        return "\n".join(lines)

    @property
    def terminator(self) -> Optional[IRInstruction]:
        """获取终止指令"""
        if self.instructions and self.instructions[-1].is_terminator():
            return self.instructions[-1]
        return None

    @property
    def is_empty(self) -> bool:
        return len(self.instructions) == 0


@dataclass
class IRFunction:
    """IR 函数"""
    name: str
    return_type: IRValueType
    params: list[IRValue]
    blocks: list[BasicBlock] = field(default_factory=list)
    entry_block: Optional[BasicBlock] = None
    is_extern: bool = False
    is_entry: bool = False  # 是否为入口函数

    def add_block(self, block: BasicBlock) -> None:
        """添加基本块"""
        self.blocks.append(block)
        if self.entry_block is None:
            self.entry_block = block

    def new_block(self, name: str = "") -> BasicBlock:
        """创建新的基本块"""
        if not name:
            name = f"bb{len(self.blocks)}"
        block = BasicBlock(name)
        self.blocks.append(block)
        if self.entry_block is None:
            self.entry_block = block
        return block

    def __repr__(self) -> str:
        params_str = ", ".join(str(p) for p in self.params)
        lines = [f"define {self.return_type} @{self.name}({params_str}) {{"]
        for block in self.blocks:
            lines.append(str(block))
        lines.append("}")
        return "\n".join(lines)


@dataclass
class IRGlobal:
    """IR 全局变量"""
    name: str
    value_type: IRValueType
    initializer: Optional[Any] = None
    is_constant: bool = False

    def __repr__(self) -> str:
        const = "constant" if self.is_constant else "global"
        if self.initializer is not None:
            return f"@{self.name} = {const} {self.value_type} {self.initializer}"
        return f"@{self.name} = external {const} {self.value_type}"


class IRModule:
    """IR 模块（包含函数和全局变量）"""

    def __init__(self, name: str = "main"):
        self.name: str = name
        self.functions: dict[str, IRFunction] = {}
        self.globals: dict[str, IRGlobal] = {}
        self.struct_types: dict[str, list[tuple[str, IRValueType]]] = {}

    def add_function(self, func: IRFunction) -> None:
        """添加函数"""
        self.functions[func.name] = func

    def get_function(self, name: str) -> Optional[IRFunction]:
        """获取函数"""
        return self.functions.get(name)

    def add_global(self, global_var: IRGlobal) -> None:
        """添加全局变量"""
        self.globals[global_var.name] = global_var

    def get_global(self, name: str) -> Optional[IRGlobal]:
        """获取全局变量"""
        return self.globals.get(name)

    def add_struct_type(self, name: str, fields: list[tuple[str, IRValueType]]) -> None:
        """添加结构体类型"""
        self.struct_types[name] = fields

    def __repr__(self) -> str:
        lines = [f"; IR Module: {self.name}"]
        for name, g in self.globals.items():
            lines.append(str(g))
        for name, func in self.functions.items():
            lines.append("")
            lines.append(str(func))
        return "\n".join(lines)


class IRBuilder:
    """IR 构建器 - 辅助生成 IR"""

    def __init__(self, module: Optional[IRModule] = None):
        self.module: IRModule = module or IRModule()
        self.current_function: Optional[IRFunction] = None
        self.current_block: Optional[BasicBlock] = None
        self._temp_counter: int = 0
        self._label_counter: int = 0

    def new_temp(self, value_type: IRValueType = IRValueType.INT32) -> IRValue:
        """创建临时变量"""
        name = f"%t{self._temp_counter}"
        self._temp_counter += 1
        return IRValue(name, value_type)

    def new_label(self, prefix: str = "L") -> str:
        """创建新标签"""
        label = f"{prefix}{self._label_counter}"
        self._label_counter += 1
        return label

    def set_current_function(self, func: IRFunction) -> None:
        """设置当前函数"""
        self.current_function = func

    def set_current_block(self, block: BasicBlock) -> None:
        """设置当前基本块"""
        self.current_block = block

    def new_function(self, name: str, return_type: IRValueType = IRValueType.VOID, params: Optional[list[IRValue]] = None) -> IRFunction:
        """创建新函数"""
        func = IRFunction(name, return_type, params or [])
        self.module.add_function(func)
        self.current_function = func
        # 创建入口基本块
        entry = func.new_block(f"entry_{name}")
        self.current_block = entry
        return func

    def new_block(self, name: str = "") -> BasicBlock:
        """创建新基本块并设置为当前块"""
        if not self.current_function:
            raise RuntimeError("No current function")
        block = self.current_function.new_block(name)
        self.current_block = block
        return block

    def emit(self, opcode: IROpcode, dest: Optional[IRValue] = None, operands: Optional[list[IRValue]] = None, label: Optional[str] = None, comment: str = "") -> IRInstruction:
        """发射指令"""
        if not self.current_block:
            raise RuntimeError("No current block")
        instr = IRInstruction(opcode, dest, operands or [], label, comment)
        self.current_block.add_instruction(instr)
        return instr

    def emit_label(self, label: str, comment: str = "") -> IRInstruction:
        """发射标签"""
        return self.emit(IROpcode.LABEL, label=label, comment=comment)

    def emit_goto(self, target_label: str, comment: str = "") -> IRInstruction:
        """发射无条件跳转"""
        return self.emit(IROpcode.GOTO, label=target_label, comment=comment)

    def emit_if_goto(self, condition: IRValue, target_label: str, comment: str = "") -> IRInstruction:
        """发射条件跳转"""
        return self.emit(IROpcode.IF_GOTO, operands=[condition], label=target_label, comment=comment)

    def emit_return(self, value: Optional[IRValue] = None, comment: str = "") -> IRInstruction:
        """发射返回指令"""
        return self.emit(IROpcode.RETURN, operands=[value] if value else [], comment=comment)

    def emit_ret(self, value: Optional[IRValue] = None, comment: str = "") -> IRInstruction:
        """发射返回指令（别名）"""
        return self.emit_ret(IROpcode.RET, operands=[value] if value else [], comment=comment)

    def emit_alloc(self, value_type: IRValueType, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射分配指令"""
        if dest is None:
            dest = self.new_temp(IRValueType.POINTER)
        self.emit(IROpcode.ALLOCA, dest, comment=comment)
        return dest

    def emit_store(self, ptr: IRValue, value: IRValue, comment: str = "") -> IRInstruction:
        """发射存储指令"""
        return self.emit(IROpcode.STORE, operands=[ptr, value], comment=comment)

    def emit_load(self, ptr: IRValue, value_type: IRValueType = IRValueType.INT32, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射加载指令"""
        if dest is None:
            dest = self.new_temp(value_type)
        self.emit(IROpcode.LOAD, dest, [ptr], comment=comment)
        return dest

    def emit_add(self, left: IRValue, right: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射加法指令"""
        if dest is None:
            dest = self.new_temp(left.value_type)
        opcode = IROpcode.ADD_F if left.value_type == IRValueType.FLOAT64 else IROpcode.ADD_I
        self.emit(opcode, dest, [left, right], comment=comment)
        return dest

    def emit_sub(self, left: IRValue, right: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射减法指令"""
        if dest is None:
            dest = self.new_temp(left.value_type)
        opcode = IROpcode.SUB_F if left.value_type == IRValueType.FLOAT64 else IROpcode.SUB_I
        self.emit(opcode, dest, [left, right], comment=comment)
        return dest

    def emit_mul(self, left: IRValue, right: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射乘法指令"""
        if dest is None:
            dest = self.new_temp(left.value_type)
        opcode = IROpcode.MUL_F if left.value_type == IRValueType.FLOAT64 else IROpcode.MUL_I
        self.emit(opcode, dest, [left, right], comment=comment)
        return dest

    def emit_call(self, func_name: str, args: list[IRValue], return_type: IRValueType = IRValueType.VOID, dest: Optional[IRValue] = None, comment: str = "") -> Optional[IRValue]:
        """发射函数调用"""
        if dest is None and return_type != IRValueType.VOID:
            dest = self.new_temp(return_type)
        operands = [IRValue(func_name, IRValueType.FUNCTION)] + args
        self.emit(IROpcode.CALL, dest, operands, comment=comment)
        return dest

    def emit_phi(self, incoming: list[tuple[IRValue, str]], value_type: IRValueType = IRValueType.INT32, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射 Phi 指令"""
        if dest is None:
            dest = self.new_temp(value_type)
        operands = []
        for val, label in incoming:
            operands.append(val)
        self.emit(IROpcode.PHI, dest, operands, comment=comment)
        return dest

    def emit_comment(self, text: str) -> IRInstruction:
        """发射注释"""
        return self.emit(IROpcode.COMMENT, comment=text)

    def emit_nop(self) -> IRInstruction:
        """发射空操作"""
        return self.emit(IROpcode.NOP)

    def emit_copy(self, src: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射拷贝指令"""
        if dest is None:
            dest = self.new_temp(src.value_type)
        self.emit(IROpcode.COPY, dest, [src], comment=comment)
        return dest

    def emit_icmp(self, condition: str, left: IRValue, right: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射整数比较指令"""
        if dest is None:
            dest = self.new_temp(IRValueType.INT1)
        opcode_map = {
            "eq": IROpcode.EQ_I, "ne": IROpcode.NE_I,
            "lt": IROpcode.LT_I, "gt": IROpcode.GT_I,
            "le": IROpcode.LE_I, "ge": IROpcode.GE_I,
        }
        opcode = opcode_map.get(condition, IROpcode.EQ_I)
        self.emit(opcode, dest, [left, right], comment=comment)
        return dest

    def emit_fcmp(self, condition: str, left: IRValue, right: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射浮点比较指令"""
        if dest is None:
            dest = self.new_temp(IRValueType.INT1)
        opcode_map = {
            "eq": IROpcode.EQ_F, "ne": IROpcode.NE_F,
            "lt": IROpcode.LT_F, "gt": IROpcode.GT_F,
            "le": IROpcode.LE_F, "ge": IROpcode.GE_F,
        }
        opcode = opcode_map.get(condition, IROpcode.EQ_F)
        self.emit(opcode, dest, [left, right], comment=comment)
        return dest

    def emit_tensor_init(self, shape: list[IRValue], element_type: IRValueType = IRValueType.FLOAT32, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射张量初始化"""
        if dest is None:
            dest = self.new_temp(IRValueType.TENSOR)
        self.emit(IROpcode.TENSOR_INIT, dest, shape, comment=comment)
        return dest

    def emit_matmul(self, a: IRValue, b: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射矩阵乘法"""
        if dest is None:
            dest = self.new_temp(IRValueType.TENSOR)
        self.emit(IROpcode.MATMUL, dest, [a, b], comment=comment)
        return dest

    def emit_conv2d(self, input_tensor: IRValue, kernel: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射 2D 卷积"""
        if dest is None:
            dest = self.new_temp(IRValueType.TENSOR)
        self.emit(IROpcode.CONV2D, dest, [input_tensor, kernel], comment=comment)
        return dest

    def emit_relu(self, input_tensor: IRValue, dest: Optional[IRValue] = None, comment: str = "") -> IRValue:
        """发射 ReLU 激活"""
        if dest is None:
            dest = self.new_temp(IRValueType.TENSOR)
        self.emit(IROpcode.RELU, dest, [input_tensor], comment=comment)
        return dest

    def __repr__(self) -> str:
        return f"IRBuilder(module={self.module.name})"


def create_constant_int(value: int) -> IRValue:
    """创建整数常量"""
    return IRValue(str(value), IRValueType.INT32, value, True)


def create_constant_float(value: float) -> IRValue:
    """创建浮点常量"""
    return IRValue(str(value), IRValueType.FLOAT64, value, True)


def create_constant_bool(value: bool) -> IRValue:
    """创建布尔常量"""
    return IRValue("true" if value else "false", IRValueType.INT1, value, True)


def create_constant_string(value: str) -> IRValue:
    """创建字符串常量"""
    return IRValue(f'"{value}"', IRValueType.STRING, value, True)