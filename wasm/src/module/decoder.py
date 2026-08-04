"""WebAssembly instruction decoder.

This module provides the instruction decoding logic for WebAssembly bytecode,
mapping raw opcode bytes to instruction objects with their operands.
"""

from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple, Union

from .types import ValType, BlockType, FuncType


class Opcode(IntEnum):
    """WebAssembly opcode definitions."""
    # Control flow
    UNREACHABLE = 0x00
    NOP = 0x01
    BLOCK = 0x02
    LOOP = 0x03
    IF = 0x04
    ELSE = 0x05
    END = 0x0B
    BR = 0x0C
    BR_IF = 0x0D
    BR_TABLE = 0x0E
    RETURN = 0x0F
    CALL = 0x10
    CALL_INDIRECT = 0x11

    # Parametric
    DROP = 0x1A
    SELECT = 0x1B
    SELECT_T = 0x1C

    # Variable access
    LOCAL_GET = 0x20
    LOCAL_SET = 0x21
    LOCAL_TEE = 0x22
    GLOBAL_GET = 0x23
    GLOBAL_SET = 0x24

    # Memory
    I32_LOAD = 0x28
    I64_LOAD = 0x29
    F32_LOAD = 0x2A
    F64_LOAD = 0x2B
    I32_LOAD8_S = 0x2C
    I32_LOAD8_U = 0x2D
    I32_LOAD16_S = 0x2E
    I32_LOAD16_U = 0x2F
    I64_LOAD8_S = 0x30
    I64_LOAD8_U = 0x31
    I64_LOAD16_S = 0x32
    I64_LOAD16_U = 0x33
    I64_LOAD32_S = 0x34
    I64_LOAD32_U = 0x35
    I32_STORE = 0x36
    I64_STORE = 0x37
    F32_STORE = 0x38
    F64_STORE = 0x39
    I32_STORE8 = 0x3A
    I32_STORE16 = 0x3B
    I64_STORE8 = 0x3C
    I64_STORE16 = 0x3D
    I64_STORE32 = 0x3E
    MEMORY_SIZE = 0x3F
    MEMORY_GROW = 0x40

    # Constants
    I32_CONST = 0x41
    I64_CONST = 0x42
    F32_CONST = 0x43
    F64_CONST = 0x44

    # Comparison operators (i32)
    I32_EQZ = 0x45
    I32_EQ = 0x46
    I32_NE = 0x47
    I32_LT_S = 0x48
    I32_LT_U = 0x49
    I32_GT_S = 0x4A
    I32_GT_U = 0x4B
    I32_LE_S = 0x4C
    I32_LE_U = 0x4D
    I32_GE_S = 0x4E
    I32_GE_U = 0x4F

    # Comparison operators (i64)
    I64_EQZ = 0x50
    I64_EQ = 0x51
    I64_NE = 0x52
    I64_LT_S = 0x53
    I64_LT_U = 0x54
    I64_GT_S = 0x55
    I64_GT_U = 0x56
    I64_LE_S = 0x57
    I64_LE_U = 0x58
    I64_GE_S = 0x59
    I64_GE_U = 0x5A

    # Comparison operators (f32)
    F32_EQ = 0x5B
    F32_NE = 0x5C
    F32_LT = 0x5D
    F32_GT = 0x5E
    F32_LE = 0x5F
    F32_GE = 0x60

    # Comparison operators (f64)
    F64_EQ = 0x61
    F64_NE = 0x62
    F64_LT = 0x63
    F64_GT = 0x64
    F64_LE = 0x65
    F64_GE = 0x66

    # Arithmetic operators (i32)
    I32_CLZ = 0x67
    I32_CTZ = 0x68
    I32_POPCNT = 0x69
    I32_ADD = 0x6A
    I32_SUB = 0x6B
    I32_MUL = 0x6C
    I32_DIV_S = 0x6D
    I32_DIV_U = 0x6E
    I32_REM_S = 0x6F
    I32_REM_U = 0x70
    I32_AND = 0x71
    I32_OR = 0x72
    I32_XOR = 0x73
    I32_SHL = 0x74
    I32_SHR_S = 0x75
    I32_SHR_U = 0x76
    I32_ROTL = 0x77
    I32_ROTR = 0x78

    # Arithmetic operators (i64)
    I64_CLZ = 0x79
    I64_CTZ = 0x7A
    I64_POPCNT = 0x7B
    I64_ADD = 0x7C
    I64_SUB = 0x7D
    I64_MUL = 0x7E
    I64_DIV_S = 0x7F
    I64_DIV_U = 0x80
    I64_REM_S = 0x81
    I64_REM_U = 0x82
    I64_AND = 0x83
    I64_OR = 0x84
    I64_XOR = 0x85
    I64_SHL = 0x86
    I64_SHR_S = 0x87
    I64_SHR_U = 0x88
    I64_ROTL = 0x89
    I64_ROTR = 0x8A

    # Arithmetic operators (f32)
    F32_ABS = 0x8B
    F32_NEG = 0x8C
    F32_CEIL = 0x8D
    F32_FLOOR = 0x8E
    F32_TRUNC = 0x8F
    F32_NEAREST = 0x90
    F32_SQRT = 0x91
    F32_ADD = 0x92
    F32_SUB = 0x93
    F32_MUL = 0x94
    F32_DIV = 0x95
    F32_MIN = 0x96
    F32_MAX = 0x97
    F32_COPYSIGN = 0x98

    # Arithmetic operators (f64)
    F64_ABS = 0x99
    F64_NEG = 0x9A
    F64_CEIL = 0x9B
    F64_FLOOR = 0x9C
    F64_TRUNC = 0x9D
    F64_NEAREST = 0x9E
    F64_SQRT = 0x9F
    F64_ADD = 0xA0
    F64_SUB = 0xA1
    F64_MUL = 0xA2
    F64_DIV = 0xA3
    F64_MIN = 0xA4
    F64_MAX = 0xA5
    F64_COPYSIGN = 0xA6

    # Conversions
    I32_WRAP_I64 = 0xA7
    I32_TRUNC_F32_S = 0xA8
    I32_TRUNC_F32_U = 0xA9
    I32_TRUNC_F64_S = 0xAA
    I32_TRUNC_F64_U = 0xAB
    I64_EXTEND_I32_S = 0xAC
    I64_EXTEND_I32_U = 0xAD
    I64_TRUNC_F32_S = 0xAE
    I64_TRUNC_F32_U = 0xAF
    I64_TRUNC_F64_S = 0xB0
    I64_TRUNC_F64_U = 0xB1
    F32_CONVERT_I32_S = 0xB2
    F32_CONVERT_I32_U = 0xB3
    F32_CONVERT_I64_S = 0xB4
    F32_CONVERT_I64_U = 0xB5
    F32_DEMOTE_F64 = 0xB6
    F64_CONVERT_I32_S = 0xB7
    F64_CONVERT_I32_U = 0xB8
    F64_CONVERT_I64_S = 0xB9
    F64_CONVERT_I64_U = 0xBA
    F64_PROMOTE_F32 = 0xBB

    # Reinterpretations
    I32_REINTERPRET_F32 = 0xBC
    I64_REINTERPRET_F64 = 0xBD
    F32_REINTERPRET_I32 = 0xBE
    F64_REINTERPRET_I64 = 0xBF

    # Sign extension (sign-ext proposal)
    I32_EXTEND8_S = 0xC0
    I32_EXTEND16_S = 0xC1
    I64_EXTEND8_S = 0xC2
    I64_EXTEND16_S = 0xC3
    I64_EXTEND32_S = 0xC4

    # Reference types
    REF_NULL = 0xD0
    REF_IS_NULL = 0xD1
    REF_FUNC = 0xD2

    # Table instructions
    TABLE_GET = 0x25
    TABLE_SET = 0x26
    TABLE_SIZE = 0xFC  # prefix
    TABLE_GROW = 0xFC  # prefix
    TABLE_FILL = 0xFC  # prefix
    TABLE_COPY = 0xFC  # prefix
    TABLE_INIT = 0xFC  # prefix
    ELEM_DROP = 0xFC  # prefix

    # Bulk memory
    MEMORY_INIT = 0xFC
    DATA_DROP = 0xFC
    MEMORY_COPY = 0xFC
    MEMORY_FILL = 0xFC

    # SIMD
    V128_LOAD = 0xFD
    V128_LOAD8X8_S = 0xFD
    V128_LOAD8X8_U = 0xFD
    V128_LOAD16X4_S = 0xFD
    V128_LOAD16X4_U = 0xFD
    V128_LOAD32X2_S = 0xFD
    V128_LOAD32X2_U = 0xFD
    V128_LOAD8_SPLAT = 0xFD
    V128_LOAD16_SPLAT = 0xFD
    V128_LOAD32_SPLAT = 0xFD
    V128_LOAD64_SPLAT = 0xFD
    V128_STORE = 0xFD
    V128_CONST = 0xFD
    I8X16_SPLAT = 0xFD
    I16X8_SPLAT = 0xFD
    I32X4_SPLAT = 0xFD
    I64X2_SPLAT = 0xFD
    F32X4_SPLAT = 0xFD
    F64X2_SPLAT = 0xFD
    I8X16_EXTRACT_LANE_S = 0xFD
    I8X16_EXTRACT_LANE_U = 0xFD
    I16X8_EXTRACT_LANE_S = 0xFD
    I16X8_EXTRACT_LANE_U = 0xFD
    I32X4_EXTRACT_LANE = 0xFD
    I64X2_EXTRACT_LANE = 0xFD
    F32X4_EXTRACT_LANE = 0xFD
    F64X2_EXTRACT_LANE = 0xFD
    I8X16_REPLACE_LANE = 0xFD
    I16X8_REPLACE_LANE = 0xFD
    I32X4_REPLACE_LANE = 0xFD
    I64X2_REPLACE_LANE = 0xFD
    F32X4_REPLACE_LANE = 0xFD
    F64X2_REPLACE_LANE = 0xFD

    # Truncation with saturation (nontrapping-float-to-int)
    I32_TRUNC_SAT_F32_S = 0xFC
    I32_TRUNC_SAT_F32_U = 0xFC
    I32_TRUNC_SAT_F64_S = 0xFC
    I32_TRUNC_SAT_F64_U = 0xFC
    I64_TRUNC_SAT_F32_S = 0xFC
    I64_TRUNC_SAT_F32_U = 0xFC
    I64_TRUNC_SAT_F64_S = 0xFC
    I64_TRUNC_SAT_F64_U = 0xFC

    # Prefix opcodes
    MISC_PREFIX = 0xFC
    SIMD_PREFIX = 0xFD
    ATOMIC_PREFIX = 0xFE
    GC_PREFIX = 0xFB


# Misc opcodes (0xFC prefix)
class MiscOpcode(IntEnum):
    """Opcode values for instructions with the 0xFC prefix."""
    I32_TRUNC_SAT_F32_S = 0x00
    I32_TRUNC_SAT_F32_U = 0x01
    I32_TRUNC_SAT_F64_S = 0x02
    I32_TRUNC_SAT_F64_U = 0x03
    I64_TRUNC_SAT_F32_S = 0x04
    I64_TRUNC_SAT_F32_U = 0x05
    I64_TRUNC_SAT_F64_S = 0x06
    I64_TRUNC_SAT_F64_U = 0x07
    MEMORY_INIT = 0x08
    DATA_DROP = 0x09
    MEMORY_COPY = 0x0A
    MEMORY_FILL = 0x0B
    TABLE_GROW = 0x0C
    TABLE_SIZE = 0x0D
    TABLE_FILL = 0x0E
    TABLE_COPY = 0x0F
    TABLE_INIT = 0x10
    ELEM_DROP = 0x11


# SIMD opcodes (0xFD prefix)
class SimdOpcode(IntEnum):
    """SIMD opcode values for instructions with the 0xFD prefix."""
    V128_LOAD = 0x00
    V128_LOAD8X8_S = 0x01
    V128_LOAD8X8_U = 0x02
    V128_LOAD16X4_S = 0x03
    V128_LOAD16X4_U = 0x04
    V128_LOAD32X2_S = 0x05
    V128_LOAD32X2_U = 0x06
    V128_LOAD8_SPLAT = 0x07
    V128_LOAD16_SPLAT = 0x08
    V128_LOAD32_SPLAT = 0x09
    V128_LOAD64_SPLAT = 0x0A
    V128_LOAD32_ZERO = 0x0B
    V128_LOAD64_ZERO = 0x0C
    V128_STORE = 0x0D
    V128_LOAD8_LANE = 0x0E
    V128_LOAD16_LANE = 0x0F
    V128_LOAD32_LANE = 0x10
    V128_LOAD64_LANE = 0x11
    V128_STORE8_LANE = 0x12
    V128_STORE16_LANE = 0x13
    V128_STORE32_LANE = 0x14
    V128_STORE64_LANE = 0x15
    V128_CONST = 0x16
    I8X16_SHUFFLE = 0x17
    I8X16_SWIZZLE = 0x18
    I8X16_SPLAT = 0x19
    I16X8_SPLAT = 0x1A
    I32X4_SPLAT = 0x1B
    I64X2_SPLAT = 0x1C
    F32X4_SPLAT = 0x1D
    F64X2_SPLAT = 0x1E
    I8X16_EXTRACT_LANE_S = 0x1F
    I8X16_EXTRACT_LANE_U = 0x20
    I16X8_EXTRACT_LANE_S = 0x21
    I16X8_EXTRACT_LANE_U = 0x22
    I32X4_EXTRACT_LANE = 0x23
    I64X2_EXTRACT_LANE = 0x24
    F32X4_EXTRACT_LANE = 0x25
    F64X2_EXTRACT_LANE = 0x26
    I8X16_REPLACE_LANE = 0x27
    I16X8_REPLACE_LANE = 0x28
    I32X4_REPLACE_LANE = 0x29
    I64X2_REPLACE_LANE = 0x2A
    F32X4_REPLACE_LANE = 0x2B
    F64X2_REPLACE_LANE = 0x2C
    I8X16_EQ = 0x2D
    I8X16_NE = 0x2E
    I8X16_LT_S = 0x2F
    I8X16_LT_U = 0x30
    I8X16_GT_S = 0x31
    I8X16_GT_U = 0x32
    I8X16_LE_S = 0x33
    I8X16_LE_U = 0x34
    I8X16_GE_S = 0x35
    I8X16_GE_U = 0x36
    I16X8_EQ = 0x37
    I16X8_NE = 0x38
    I16X8_LT_S = 0x39
    I16X8_LT_U = 0x3A
    I16X8_GT_S = 0x3B
    I16X8_GT_U = 0x3C
    I16X8_LE_S = 0x3D
    I16X8_LE_U = 0x3E
    I16X8_GE_S = 0x3F
    I16X8_GE_U = 0x40
    I32X4_EQ = 0x41
    I32X4_NE = 0x42
    I32X4_LT_S = 0x43
    I32X4_LT_U = 0x44
    I32X4_GT_S = 0x45
    I32X4_GT_U = 0x46
    I32X4_LE_S = 0x47
    I32X4_LE_U = 0x48
    I32X4_GE_S = 0x49
    I32X4_GE_U = 0x4A
    I64X2_EQ = 0x4B
    I64X2_NE = 0x4C
    I64X2_LT_S = 0x4D
    I64X2_GT_S = 0x4E
    I64X2_LE_S = 0x4F
    I64X2_GE_S = 0x50
    F32X4_EQ = 0x51
    F32X4_NE = 0x52
    F32X4_LT = 0x53
    F32X4_GT = 0x54
    F32X4_LE = 0x55
    F32X4_GE = 0x56
    F64X2_EQ = 0x57
    F64X2_NE = 0x58
    F64X2_LT = 0x59
    F64X2_GT = 0x5A
    F64X2_LE = 0x5B
    F64X2_GE = 0x5C
    I8X16_NEG = 0x5D
    I16X8_NEG = 0x5E
    I32X4_NEG = 0x5F
    I64X2_NEG = 0x60
    F32X4_NEG = 0x61
    F64X2_NEG = 0x62
    I8X16_ABS = 0x63
    I16X8_ABS = 0x64
    I32X4_ABS = 0x65
    I64X2_ABS = 0x66
    I8X16_SWIZZLE2 = 0x67
    I8X16_NARROW_I16X8_S = 0x68
    I8X16_NARROW_I16X8_U = 0x69
    I16X8_NARROW_I32X4_S = 0x6A
    I16X8_NARROW_I32X4_U = 0x6B
    I8X16_ALL_TRUE = 0x6C
    I16X8_ALL_TRUE = 0x6D
    I32X4_ALL_TRUE = 0x6E
    I64X2_ALL_TRUE = 0x6F
    I8X16_BITMASK = 0x70
    I16X8_BITMASK = 0x71
    I32X4_BITMASK = 0x72
    I64X2_BITMASK = 0x73
    I8X16_SHL = 0x74
    I16X8_SHL = 0x75
    I32X4_SHL = 0x76
    I64X2_SHL = 0x77
    I8X16_SHR_S = 0x78
    I8X16_SHR_U = 0x79
    I16X8_SHR_S = 0x7A
    I16X8_SHR_U = 0x7B
    I32X4_SHR_S = 0x7C
    I32X4_SHR_U = 0x7D
    I64X2_SHR_S = 0x7E
    I64X2_SHR_U = 0x7F
    I8X16_ADD = 0x80
    I16X8_ADD = 0x81
    I32X4_ADD = 0x82
    I64X2_ADD = 0x83
    I8X16_ADD_SAT_S = 0x84
    I8X16_ADD_SAT_U = 0x85
    I16X8_ADD_SAT_S = 0x86
    I16X8_ADD_SAT_U = 0x87
    I8X16_SUB = 0x88
    I16X8_SUB = 0x89
    I32X4_SUB = 0x8A
    I64X2_SUB = 0x8B
    I8X16_SUB_SAT_S = 0x8C
    I8X16_SUB_SAT_U = 0x8D
    I16X8_SUB_SAT_S = 0x8E
    I16X8_SUB_SAT_U = 0x8F
    I8X16_MIN_S = 0x90
    I8X16_MIN_U = 0x91
    I16X8_MIN_S = 0x92
    I16X8_MIN_U = 0x93
    I32X4_MIN_S = 0x94
    I32X4_MIN_U = 0x95
    I8X16_MAX_S = 0x96
    I8X16_MAX_U = 0x97
    I16X8_MAX_S = 0x98
    I16X8_MAX_U = 0x99
    I32X4_MAX_S = 0x9A
    I32X4_MAX_U = 0x9B
    I8X16_AVGR_U = 0x9C
    I16X8_AVGR_U = 0x9D
    I16X8_EXTMUL_LOW_I32X4_S = 0x9E
    I16X8_EXTMUL_LOW_I32X4_U = 0x9F
    I16X8_EXTMUL_HIGH_I32X4_S = 0xA0
    I16X8_EXTMUL_HIGH_I32X4_U = 0xA1
    I32X4_EXTMUL_LOW_I64X2_S = 0xA2
    I32X4_EXTMUL_LOW_I64X2_U = 0xA3
    I32X4_EXTMUL_HIGH_I64X2_S = 0xA4
    I32X4_EXTMUL_HIGH_I64X2_U = 0xA5
    I16X8_Q15MUL_S = 0xA6
    I8X16_DOT_I16X8_S = 0xA7
    I8X16_REL_SWIZZLE = 0xA8
    I8X16_REL_SWIZZLE2 = 0xA9
    I16X8_DOT_I8X16_I7X16 = 0xAA
    I8X16_POPCNT = 0xAB
    F32X4_CEIL = 0xAC
    F64X2_CEIL = 0xAD
    F32X4_FLOOR = 0xAE
    F64X2_FLOOR = 0xAF
    F32X4_TRUNC = 0xB0
    F64X2_TRUNC = 0xB1
    F32X4_NEAREST = 0xB2
    F64X2_NEAREST = 0xB3
    F32X4_ADD = 0xB4
    F64X2_ADD = 0xB5
    F32X4_SUB = 0xB6
    F64X2_SUB = 0xB7
    F32X4_MUL = 0xB8
    F64X2_MUL = 0xB9
    F32X4_DIV = 0xBA
    F64X2_DIV = 0xBB
    F32X4_MIN = 0xBC
    F64X2_MIN = 0xBD
    F32X4_MAX = 0xBE
    F64X2_MAX = 0xBF
    F32X4_PMIN = 0xC0
    F64X2_PMIN = 0xC1
    F32X4_PMAX = 0xC2
    F64X2_PMAX = 0xC3
    F32X4_SQRT = 0xC4
    F64X2_SQRT = 0xC5
    F32X4_DEMOTE_F64X2_ZERO = 0xC6
    F64X2_PROMOTE_LOW_F32X4 = 0xC7
    F32X4_CONVERT_I32X4_S = 0xC8
    F32X4_CONVERT_I32X4_U = 0xC9
    I32X4_TRUNC_SAT_F32X4_S = 0xCA
    I32X4_TRUNC_SAT_F32X4_U = 0xCB
    F32X4_CONVERT_I64X2_S = 0xCC
    F32X4_CONVERT_I64X2_U = 0xCD
    I64X2_TRUNC_SAT_F32X4_S = 0xCE
    I64X2_TRUNC_SAT_F32X4_U = 0xCF
    F64X2_CONVERT_LOW_I32X4_S = 0xD0
    F64X2_CONVERT_LOW_I32X4_U = 0xD1
    I32X4_TRUNC_SAT_F64X2_S_ZERO = 0xD2
    I32X4_TRUNC_SAT_F64X2_U_ZERO = 0xD3
    I8X16_MUL = 0xD4
    I16X8_MUL = 0xD5
    I32X4_MUL = 0xD6
    I64X2_MUL = 0xD7
    I8X16_EXTADD_PAIRWISE_I16X8_S = 0xD8
    I8X16_EXTADD_PAIRWISE_I16X8_U = 0xD9
    I16X8_EXTADD_PAIRWISE_I32X4_S = 0xDA
    I16X8_EXTADD_PAIRWISE_I32X4_U = 0xDB
    I16X8_EXTADD_PAIRWISE_I32X4_S2 = 0xDC
    I16X8_EXTADD_PAIRWISE_I32X4_U2 = 0xDD
    I32X4_TRUNC_SAT_F64X2_S_ZERO = 0xDE
    I32X4_TRUNC_SAT_F64X2_U_ZERO = 0xDF


class Instruction:
    """A decoded WebAssembly instruction with its operands."""

    def __init__(
        self,
        opcode: Opcode,
        immediates: Optional[List[Any]] = None,
        block_type: Optional[BlockType] = None,
        prefix: int = 0,
        sub_opcode: int = 0,
        offset: int = 0,
        size: int = 0,
    ):
        """Initialize a decoded instruction.

        Args:
            opcode: The instruction opcode.
            immediates: List of immediate operands.
            block_type: Block type for structured control flow.
            prefix: Prefix byte (0xFC, 0xFD, 0xFE) or 0 for none.
            sub_opcode: The sub-opcode for prefixed instructions.
            offset: Offset in the bytecode where this instruction starts.
            size: Total size of the instruction in bytes.
        """
        self.opcode = opcode
        self.immediates = immediates or []
        self.block_type = block_type
        self.prefix = prefix
        self.sub_opcode = sub_opcode
        self.offset = offset
        self.size = size

    def __repr__(self) -> str:
        parts = [f"opcode=0x{self.opcode:02X}"]
        if self.prefix:
            parts.append(f"prefix=0x{self.prefix:02X}")
        if self.immediates:
            parts.append(f"immediates={self.immediates}")
        if self.block_type is not None:
            parts.append(f"block_type={self.block_type}")
        return f"Instruction({', '.join(parts)})"

    def __str__(self) -> str:
        """Human-readable representation of the instruction."""
        name = self.opcode.name.lower()
        if self.immediates:
            imms = ", ".join(str(imm) for imm in self.immediates)
            return f"{name} {imms}"
        return name

    @property
    def name(self) -> str:
        """Get the instruction name."""
        return self.opcode.name.lower()


class InstructionDecoder:
    """Decoder for WebAssembly binary instructions.

    This class decodes raw bytecode sequences into Instruction objects
    with their operands, handling prefix opcodes and all immediate formats.
    """

    def __init__(self, enable_extensions: bool = True):
        """Initialize the decoder.

        Args:
            enable_extensions: Whether to enable extended instruction support.
        """
        self.enable_extensions = enable_extensions

    def decode(self, code: bytes, offset: int = 0) -> Instruction:
        """Decode a single instruction starting at the given offset.

        Args:
            code: The bytecode sequence.
            offset: The starting offset.

        Returns:
            A decoded Instruction object.

        Raises:
            ValueError: If the opcode is invalid or the bytecode is malformed.
        """
        if offset >= len(code):
            raise ValueError(f"Offset {offset} out of bounds for code of length {len(code)}")

        start_offset = offset
        opcode_byte = code[offset]
        offset += 1

        # Handle prefix opcodes
        if opcode_byte == 0xFC:
            return self._decode_misc_prefix(code, offset, start_offset)
        elif opcode_byte == 0xFD:
            return self._decode_simd_prefix(code, offset, start_offset)
        elif opcode_byte == 0xFE:
            return self._decode_atomic_prefix(code, offset, start_offset)

        # Try to decode as a regular opcode
        try:
            opcode = Opcode(opcode_byte)
        except ValueError:
            raise ValueError(f"Invalid opcode: 0x{opcode_byte:02X} at offset {offset - 1}")

        # Dispatch based on opcode to decode immediates
        return self._decode_instruction(opcode, code, offset, start_offset)

    def _decode_misc_prefix(self, code: bytes, offset: int, start_offset: int) -> Instruction:
        """Decode a 0xFC-prefixed instruction.

        Args:
            code: The bytecode sequence.
            offset: Current offset after the prefix byte.
            start_offset: The original start offset.

        Returns:
            A decoded Instruction.
        """
        if offset >= len(code):
            raise ValueError("Unexpected end of code in 0xFC prefix")

        sub_opcode = code[offset]
        offset += 1

        try:
            misc_op = MiscOpcode(sub_opcode)
        except ValueError:
            raise ValueError(f"Invalid 0xFC sub-opcode: 0x{sub_opcode:02X}")

        opcode_map = {
            MiscOpcode.I32_TRUNC_SAT_F32_S: Opcode.I32_TRUNC_SAT_F32_S,
            MiscOpcode.I32_TRUNC_SAT_F32_U: Opcode.I32_TRUNC_SAT_F32_U,
            MiscOpcode.I32_TRUNC_SAT_F64_S: Opcode.I32_TRUNC_SAT_F64_S,
            MiscOpcode.I32_TRUNC_SAT_F64_U: Opcode.I32_TRUNC_SAT_F64_U,
            MiscOpcode.I64_TRUNC_SAT_F32_S: Opcode.I64_TRUNC_SAT_F32_S,
            MiscOpcode.I64_TRUNC_SAT_F32_U: Opcode.I64_TRUNC_SAT_F32_U,
            MiscOpcode.I64_TRUNC_SAT_F64_S: Opcode.I64_TRUNC_SAT_F64_S,
            MiscOpcode.I64_TRUNC_SAT_F64_U: Opcode.I64_TRUNC_SAT_F64_U,
            MiscOpcode.MEMORY_INIT: Opcode.MEMORY_INIT,
            MiscOpcode.DATA_DROP: Opcode.DATA_DROP,
            MiscOpcode.MEMORY_COPY: Opcode.MEMORY_COPY,
            MiscOpcode.MEMORY_FILL: Opcode.MEMORY_FILL,
            MiscOpcode.TABLE_GROW: Opcode.TABLE_GROW,
            MiscOpcode.TABLE_SIZE: Opcode.TABLE_SIZE,
            MiscOpcode.TABLE_FILL: Opcode.TABLE_FILL,
            MiscOpcode.TABLE_COPY: Opcode.TABLE_COPY,
            MiscOpcode.TABLE_INIT: Opcode.TABLE_INIT,
            MiscOpcode.ELEM_DROP: Opcode.ELEM_DROP,
        }

        opcode = opcode_map.get(misc_op)
        if opcode is None:
            raise ValueError(f"Unsupported 0xFC sub-opcode: 0x{sub_opcode:02X}")

        # Decode sub-opcode specific immediates
        immediates = []
        if misc_op in (MiscOpcode.I32_TRUNC_SAT_F32_S, MiscOpcode.I32_TRUNC_SAT_F32_U,
                        MiscOpcode.I32_TRUNC_SAT_F64_S, MiscOpcode.I32_TRUNC_SAT_F64_U,
                        MiscOpcode.I64_TRUNC_SAT_F32_S, MiscOpcode.I64_TRUNC_SAT_F32_U,
                        MiscOpcode.I64_TRUNC_SAT_F64_S, MiscOpcode.I64_TRUNC_SAT_F64_U):
            # No immediates for trunc sat
            pass
        elif misc_op == MiscOpcode.MEMORY_INIT:
            # data_idx, mem_idx
            from ..utils.leb128 import decode_unsigned_leb128
            data_idx, offset = decode_unsigned_leb128(code, offset)
            mem_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [data_idx, mem_idx]
        elif misc_op == MiscOpcode.DATA_DROP:
            from ..utils.leb128 import decode_unsigned_leb128
            data_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [data_idx]
        elif misc_op == MiscOpcode.MEMORY_COPY:
            # dst_mem, src_mem
            from ..utils.leb128 import decode_unsigned_leb128
            dst_mem, offset = decode_unsigned_leb128(code, offset)
            src_mem, offset = decode_unsigned_leb128(code, offset)
            immediates = [dst_mem, src_mem]
        elif misc_op == MiscOpcode.MEMORY_FILL:
            from ..utils.leb128 import decode_unsigned_leb128
            mem_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [mem_idx]
        elif misc_op == MiscOpcode.TABLE_GROW:
            from ..utils.leb128 import decode_unsigned_leb128
            table_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [table_idx]
        elif misc_op == MiscOpcode.TABLE_SIZE:
            from ..utils.leb128 import decode_unsigned_leb128
            table_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [table_idx]
        elif misc_op == MiscOpcode.TABLE_FILL:
            from ..utils.leb128 import decode_unsigned_leb128
            table_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [table_idx]
        elif misc_op == MiscOpcode.TABLE_COPY:
            from ..utils.leb128 import decode_unsigned_leb128
            dst_table, offset = decode_unsigned_leb128(code, offset)
            src_table, offset = decode_unsigned_leb128(code, offset)
            immediates = [dst_table, src_table]
        elif misc_op == MiscOpcode.TABLE_INIT:
            from ..utils.leb128 import decode_unsigned_leb128
            elem_idx, offset = decode_unsigned_leb128(code, offset)
            table_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [elem_idx, table_idx]
        elif misc_op == MiscOpcode.ELEM_DROP:
            from ..utils.leb128 import decode_unsigned_leb128
            elem_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [elem_idx]

        inst_size = offset - start_offset
        return Instruction(
            opcode=opcode,
            immediates=immediates,
            prefix=0xFC,
            sub_opcode=sub_opcode,
            offset=start_offset,
            size=inst_size,
        )

    def _decode_simd_prefix(self, code: bytes, offset: int, start_offset: int) -> Instruction:
        """Decode a 0xFD-prefixed SIMD instruction.

        Args:
            code: The bytecode sequence.
            offset: Current offset after the prefix byte.
            start_offset: The original start offset.

        Returns:
            A decoded Instruction.
        """
        if offset >= len(code):
            raise ValueError("Unexpected end of code in 0xFD prefix")

        from ..utils.leb128 import decode_unsigned_leb128

        sub_opcode = code[offset]
        offset += 1

        try:
            simd_op = SimdOpcode(sub_opcode)
        except ValueError:
            raise ValueError(f"Invalid 0xFD sub-opcode: 0x{sub_opcode:02X}")

        immediates = []

        # Decode SIMD instruction-specific immediates
        if simd_op in (SimdOpcode.V128_LOAD, SimdOpcode.V128_LOAD8X8_S,
                        SimdOpcode.V128_LOAD8X8_U, SimdOpcode.V128_LOAD16X4_S,
                        SimdOpcode.V128_LOAD16X4_U, SimdOpcode.V128_LOAD32X2_S,
                        SimdOpcode.V128_LOAD32X2_U, SimdOpcode.V128_LOAD8_SPLAT,
                        SimdOpcode.V128_LOAD16_SPLAT, SimdOpcode.V128_LOAD32_SPLAT,
                        SimdOpcode.V128_LOAD64_SPLAT, SimdOpcode.V128_STORE,
                        SimdOpcode.V128_LOAD32_ZERO, SimdOpcode.V128_LOAD64_ZERO):
            # Memory load/store with align and offset
            align, offset = decode_unsigned_leb128(code, offset)
            mem_offset, offset = decode_unsigned_leb128(code, offset)
            immediates = [align, mem_offset]
        elif simd_op in (SimdOpcode.V128_LOAD8_LANE, SimdOpcode.V128_LOAD16_LANE,
                          SimdOpcode.V128_LOAD32_LANE, SimdOpcode.V128_LOAD64_LANE,
                          SimdOpcode.V128_STORE8_LANE, SimdOpcode.V128_STORE16_LANE,
                          SimdOpcode.V128_STORE32_LANE, SimdOpcode.V128_STORE64_LANE):
            align, offset = decode_unsigned_leb128(code, offset)
            mem_offset, offset = decode_unsigned_leb128(code, offset)
            lane_idx = code[offset]
            offset += 1
            immediates = [align, mem_offset, lane_idx]
        elif simd_op == SimdOpcode.V128_CONST:
            # 16 bytes of immediate value
            value = code[offset:offset + 16]
            offset += 16
            immediates = [value]
        elif simd_op == SimdOpcode.I8X16_SHUFFLE:
            # 16 lane indices
            lanes = list(code[offset:offset + 16])
            offset += 16
            immediates = [lanes]
        elif simd_op in (SimdOpcode.I8X16_EXTRACT_LANE_S, SimdOpcode.I8X16_EXTRACT_LANE_U,
                          SimdOpcode.I16X8_EXTRACT_LANE_S, SimdOpcode.I16X8_EXTRACT_LANE_U,
                          SimdOpcode.I32X4_EXTRACT_LANE, SimdOpcode.I64X2_EXTRACT_LANE,
                          SimdOpcode.F32X4_EXTRACT_LANE, SimdOpcode.F64X2_EXTRACT_LANE):
            lane_idx = code[offset]
            offset += 1
            immediates = [lane_idx]
        elif simd_op in (SimdOpcode.I8X16_REPLACE_LANE, SimdOpcode.I16X8_REPLACE_LANE,
                          SimdOpcode.I32X4_REPLACE_LANE, SimdOpcode.I64X2_REPLACE_LANE,
                          SimdOpcode.F32X4_REPLACE_LANE, SimdOpcode.F64X2_REPLACE_LANE):
            lane_idx = code[offset]
            offset += 1
            immediates = [lane_idx]
        else:
            # Other SIMD ops have no immediates
            pass

        inst_size = offset - start_offset
        return Instruction(
            opcode=Opcode.V128_LOAD,  # Generic SIMD opcode
            immediates=immediates,
            prefix=0xFD,
            sub_opcode=sub_opcode,
            offset=start_offset,
            size=inst_size,
        )

    def _decode_atomic_prefix(self, code: bytes, offset: int, start_offset: int) -> Instruction:
        """Decode a 0xFE-prefixed atomic instruction.

        This is a placeholder for the threads proposal's atomic instructions.

        Args:
            code: The bytecode sequence.
            offset: Current offset after the prefix byte.
            start_offset: The original start offset.

        Returns:
            A decoded Instruction.
        """
        if offset >= len(code):
            raise ValueError("Unexpected end of code in 0xFE prefix")

        from ..utils.leb128 import decode_unsigned_leb128

        sub_opcode = code[offset]
        offset += 1

        # Atomic memory instructions have align and offset
        align, offset = decode_unsigned_leb128(code, offset)
        mem_offset, offset = decode_unsigned_leb128(code, offset)

        inst_size = offset - start_offset
        return Instruction(
            opcode=Opcode.MEMORY_SIZE,  # Placeholder
            immediates=[align, mem_offset],
            prefix=0xFE,
            sub_opcode=sub_opcode,
            offset=start_offset,
            size=inst_size,
        )

    def _decode_instruction(self, opcode: Opcode, code: bytes, offset: int,
                            start_offset: int) -> Instruction:
        """Decode instruction immediates based on the opcode.

        Args:
            opcode: The decoded opcode.
            code: The bytecode sequence.
            offset: Current offset after the opcode byte.
            start_offset: The original start offset.

        Returns:
            A decoded Instruction with proper immediates.
        """
        from ..utils.leb128 import decode_unsigned_leb128, decode_signed_leb128

        immediates = []
        block_type = None

        # Control flow instructions
        if opcode in (Opcode.BLOCK, Opcode.LOOP, Opcode.IF):
            block_type, offset = self._decode_block_type(code, offset)
        elif opcode == Opcode.ELSE:
            pass
        elif opcode == Opcode.END:
            pass
        elif opcode == Opcode.BR:
            label_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [label_idx]
        elif opcode == Opcode.BR_IF:
            label_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [label_idx]
        elif opcode == Opcode.BR_TABLE:
            num_targets, offset = decode_unsigned_leb128(code, offset)
            targets = []
            for _ in range(num_targets):
                target, offset = decode_unsigned_leb128(code, offset)
                targets.append(target)
            default_target, offset = decode_unsigned_leb128(code, offset)
            immediates = [targets, default_target]
        elif opcode == Opcode.RETURN:
            pass
        elif opcode == Opcode.CALL:
            func_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [func_idx]
        elif opcode == Opcode.CALL_INDIRECT:
            type_idx, offset = decode_unsigned_leb128(code, offset)
            table_idx = code[offset]  # 0x00 for table 0
            offset += 1
            immediates = [type_idx]  # table_idx is always 0 table

        # Parametric
        elif opcode in (Opcode.DROP,):
            pass
        elif opcode == Opcode.SELECT:
            pass
        elif opcode == Opcode.SELECT_T:
            # Number of types followed by the types
            num_types, offset = decode_unsigned_leb128(code, offset)
            val_types = []
            for _ in range(num_types):
                vt, offset = decode_unsigned_leb128(code, offset)
                val_types.append(vt)
            immediates = [val_types]

        # Variable access
        elif opcode in (Opcode.LOCAL_GET, Opcode.LOCAL_SET, Opcode.LOCAL_TEE):
            local_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [local_idx]
        elif opcode in (Opcode.GLOBAL_GET, Opcode.GLOBAL_SET):
            global_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [global_idx]

        # Memory load/store
        elif opcode in (Opcode.I32_LOAD, Opcode.I64_LOAD, Opcode.F32_LOAD, Opcode.F64_LOAD,
                         Opcode.I32_LOAD8_S, Opcode.I32_LOAD8_U, Opcode.I32_LOAD16_S,
                         Opcode.I32_LOAD16_U, Opcode.I64_LOAD8_S, Opcode.I64_LOAD8_U,
                         Opcode.I64_LOAD16_S, Opcode.I64_LOAD16_U, Opcode.I64_LOAD32_S,
                         Opcode.I64_LOAD32_U, Opcode.I32_STORE, Opcode.I64_STORE,
                         Opcode.F32_STORE, Opcode.F64_STORE, Opcode.I32_STORE8,
                         Opcode.I32_STORE16, Opcode.I64_STORE8, Opcode.I64_STORE16,
                         Opcode.I64_STORE32):
            align, offset = decode_unsigned_leb128(code, offset)
            mem_offset, offset = decode_unsigned_leb128(code, offset)
            immediates = [align, mem_offset]
        elif opcode in (Opcode.MEMORY_SIZE, Opcode.MEMORY_GROW):
            zero_byte = code[offset]
            offset += 1
            immediates = [zero_byte]

        # Constants
        elif opcode == Opcode.I32_CONST:
            value, offset = decode_signed_leb128(code, offset)
            immediates = [value]
        elif opcode == Opcode.I64_CONST:
            value, offset = decode_signed_leb128(code, offset)
            immediates = [value]
        elif opcode == Opcode.F32_CONST:
            import struct
            if offset + 4 > len(code):
                raise ValueError("Unexpected end of code for f32.const")
            value = struct.unpack('<f', code[offset:offset + 4])[0]
            offset += 4
            immediates = [value]
        elif opcode == Opcode.F64_CONST:
            import struct
            if offset + 8 > len(code):
                raise ValueError("Unexpected end of code for f64.const")
            value = struct.unpack('<d', code[offset:offset + 8])[0]
            offset += 8
            immediates = [value]

        # Reference types
        elif opcode == Opcode.REF_NULL:
            reftype = code[offset]
            offset += 1
            immediates = [reftype]
        elif opcode == Opcode.REF_IS_NULL:
            pass
        elif opcode == Opcode.REF_FUNC:
            func_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [func_idx]

        # Table instructions
        elif opcode in (Opcode.TABLE_GET, Opcode.TABLE_SET):
            table_idx, offset = decode_unsigned_leb128(code, offset)
            immediates = [table_idx]

        # Sign extension (0xC0-0xC4)
        elif opcode in (Opcode.I32_EXTEND8_S, Opcode.I32_EXTEND16_S,
                         Opcode.I64_EXTEND8_S, Opcode.I64_EXTEND16_S,
                         Opcode.I64_EXTEND32_S):
            pass

        # Arithmetic, comparison, conversion - no immediates
        else:
            # These instructions have no immediates
            pass

        inst_size = offset - start_offset
        return Instruction(
            opcode=opcode,
            immediates=immediates,
            block_type=block_type,
            offset=start_offset,
            size=inst_size,
        )

    def _decode_block_type(self, code: bytes, offset: int) -> Tuple[BlockType, int]:
        """Decode a block type from a bytecode sequence.

        Args:
            code: The bytecode sequence.
            offset: The current offset.

        Returns:
            A tuple of (BlockType, next_offset).
        """
        from ..utils.leb128 import decode_signed_leb128, decode_unsigned_leb128

        if offset >= len(code):
            raise ValueError("Unexpected end of code while decoding block type")

        byte_val = code[offset]

        # Empty block type
        if byte_val == 0x40:
            offset += 1
            return BlockType.empty(), offset

        # Single value type (0x7F, 0x7E, 0x7D, 0x7C)
        if byte_val in (0x7F, 0x7E, 0x7D, 0x7C, 0x7B, 0x70, 0x6F):
            valtype = ValType(byte_val)
            offset += 1
            return BlockType.from_valtype(valtype), offset

        # Function type index (signed LEB128, negative = type index)
        # In the binary format, a signed LEB128 that is negative indicates
        # a type index (the actual type index is -(val + 1))
        type_idx, offset = decode_signed_leb128(code, offset)
        if type_idx < 0:
            actual_idx = - (type_idx + 1)
            return BlockType(results=[], type_idx=actual_idx), offset

        # For positive values, treat as valtype
        try:
            valtype = ValType(type_idx)
            return BlockType.from_valtype(valtype), offset
        except ValueError:
            return BlockType(results=[], type_idx=type_idx), offset

    def decode_function(self, code: bytes) -> List[Instruction]:
        """Decode all instructions in a function body.

        Args:
            code: The raw bytecode for the function body.

        Returns:
            A list of decoded Instruction objects.
        """
        instructions = []
        offset = 0

        while offset < len(code):
            instr = self.decode(code, offset)
            instructions.append(instr)
            offset += instr.size

        return instructions


def get_opcode_name(opcode: Opcode) -> str:
    """Get the human-readable name for an opcode.

    Args:
        opcode: The opcode value.

    Returns:
        The lowercase name of the opcode.
    """
    return opcode.name.lower()


def get_opcode_doc(opcode: Opcode) -> str:
    """Get a brief documentation string for an opcode.

    Args:
        opcode: The opcode value.

    Returns:
        A brief description of the instruction.
    """
    docs = {
        Opcode.UNREACHABLE: "Trap unconditionally",
        Opcode.NOP: "No operation",
        Opcode.BLOCK: "Begin a block construct",
        Opcode.LOOP: "Begin a loop construct",
        Opcode.IF: "Begin an if construct",
        Opcode.ELSE: "Begin the else block of an if",
        Opcode.END: "End a block, loop, or if",
        Opcode.BR: "Branch to a label",
        Opcode.BR_IF: "Branch conditionally to a label",
        Opcode.BR_TABLE: "Branch to a label by table",
        Opcode.RETURN: "Return from the current function",
        Opcode.CALL: "Call a function by index",
        Opcode.CALL_INDIRECT: "Call a function indirectly",
        Opcode.DROP: "Drop a value from the stack",
        Opcode.SELECT: "Select one of two values",
        Opcode.LOCAL_GET: "Read a local variable",
        Opcode.LOCAL_SET: "Write a local variable",
        Opcode.LOCAL_TEE: "Write a local variable and keep the value",
        Opcode.GLOBAL_GET: "Read a global variable",
        Opcode.GLOBAL_SET: "Write a global variable",
        Opcode.I32_LOAD: "Load i32 from memory",
        Opcode.I64_LOAD: "Load i64 from memory",
        Opcode.F32_LOAD: "Load f32 from memory",
        Opcode.F64_LOAD: "Load f64 from memory",
        Opcode.I32_STORE: "Store i32 to memory",
        Opcode.I64_STORE: "Store i64 to memory",
        Opcode.F32_STORE: "Store f32 to memory",
        Opcode.F64_STORE: "Store f64 to memory",
        Opcode.MEMORY_SIZE: "Get the current memory size",
        Opcode.MEMORY_GROW: "Grow the memory",
        Opcode.I32_CONST: "i32 constant",
        Opcode.I64_CONST: "i64 constant",
        Opcode.F32_CONST: "f32 constant",
        Opcode.F64_CONST: "f64 constant",
        Opcode.I32_ADD: "i32 addition",
        Opcode.I32_SUB: "i32 subtraction",
        Opcode.I32_MUL: "i32 multiplication",
        Opcode.I32_DIV_S: "i32 signed division",
        Opcode.I32_DIV_U: "i32 unsigned division",
        Opcode.I32_AND: "i32 and",
        Opcode.I32_OR: "i32 or",
        Opcode.I32_XOR: "i32 xor",
        Opcode.I32_SHL: "i32 shift left",
        Opcode.I32_SHR_S: "i32 signed shift right",
        Opcode.I32_SHR_U: "i32 unsigned shift right",
        Opcode.I64_ADD: "i64 addition",
        Opcode.I64_SUB: "i64 subtraction",
        Opcode.F32_ADD: "f32 addition",
        Opcode.F32_SUB: "f32 subtraction",
        Opcode.F32_MUL: "f32 multiplication",
        Opcode.F32_DIV: "f32 division",
        Opcode.F64_ADD: "f64 addition",
        Opcode.F64_SUB: "f64 subtraction",
        Opcode.F64_MUL: "f64 multiplication",
        Opcode.F64_DIV: "f64 division",
    }
    return docs.get(opcode, f"Unknown opcode 0x{opcode:02X}")


# Map of opcode to the value type it operates on
OPCODE_TYPE_MAP: Dict[Opcode, ValType] = {
    Opcode.I32_EQZ: ValType.I32,
    Opcode.I32_EQ: ValType.I32,
    Opcode.I32_NE: ValType.I32,
    Opcode.I32_LT_S: ValType.I32,
    Opcode.I32_LT_U: ValType.I32,
    Opcode.I32_GT_S: ValType.I32,
    Opcode.I32_GT_U: ValType.I32,
    Opcode.I32_LE_S: ValType.I32,
    Opcode.I32_LE_U: ValType.I32,
    Opcode.I32_GE_S: ValType.I32,
    Opcode.I32_GE_U: ValType.I32,
    Opcode.I64_EQZ: ValType.I64,
    Opcode.I64_EQ: ValType.I64,
    Opcode.I64_NE: ValType.I64,
    Opcode.I64_LT_S: ValType.I64,
    Opcode.I64_LT_U: ValType.I64,
    Opcode.I64_GT_S: ValType.I64,
    Opcode.I64_GT_U: ValType.I64,
    Opcode.I64_LE_S: ValType.I64,
    Opcode.I64_LE_U: ValType.I64,
    Opcode.I64_GE_S: ValType.I64,
    Opcode.I64_GE_U: ValType.I64,
    Opcode.I32_CLZ: ValType.I32,
    Opcode.I32_CTZ: ValType.I32,
    Opcode.I32_POPCNT: ValType.I32,
    Opcode.I32_ADD: ValType.I32,
    Opcode.I32_SUB: ValType.I32,
    Opcode.I32_MUL: ValType.I32,
    Opcode.I32_DIV_S: ValType.I32,
    Opcode.I32_DIV_U: ValType.I32,
    Opcode.I32_REM_S: ValType.I32,
    Opcode.I32_REM_U: ValType.I32,
    Opcode.I32_AND: ValType.I32,
    Opcode.I32_OR: ValType.I32,
    Opcode.I32_XOR: ValType.I32,
    Opcode.I32_SHL: ValType.I32,
    Opcode.I32_SHR_S: ValType.I32,
    Opcode.I32_SHR_U: ValType.I32,
    Opcode.I32_ROTL: ValType.I32,
    Opcode.I32_ROTR: ValType.I32,
    Opcode.I64_CLZ: ValType.I64,
    Opcode.I64_CTZ: ValType.I64,
    Opcode.I64_POPCNT: ValType.I64,
    Opcode.I64_ADD: ValType.I64,
    Opcode.I64_SUB: ValType.I64,
    Opcode.I64_MUL: ValType.I64,
    Opcode.I64_DIV_S: ValType.I64,
    Opcode.I64_DIV_U: ValType.I64,
    Opcode.I64_REM_S: ValType.I64,
    Opcode.I64_REM_U: ValType.I64,
    Opcode.I64_AND: ValType.I64,
    Opcode.I64_OR: ValType.I64,
    Opcode.I64_XOR: ValType.I64,
    Opcode.I64_SHL: ValType.I64,
    Opcode.I64_SHR_S: ValType.I64,
    Opcode.I64_SHR_U: ValType.I64,
    Opcode.I64_ROTL: ValType.I64,
    Opcode.I64_ROTR: ValType.I64,
    Opcode.F32_ABS: ValType.F32,
    Opcode.F32_NEG: ValType.F32,
    Opcode.F32_CEIL: ValType.F32,
    Opcode.F32_FLOOR: ValType.F32,
    Opcode.F32_TRUNC: ValType.F32,
    Opcode.F32_NEAREST: ValType.F32,
    Opcode.F32_SQRT: ValType.F32,
    Opcode.F32_ADD: ValType.F32,
    Opcode.F32_SUB: ValType.F32,
    Opcode.F32_MUL: ValType.F32,
    Opcode.F32_DIV: ValType.F32,
    Opcode.F32_MIN: ValType.F32,
    Opcode.F32_MAX: ValType.F32,
    Opcode.F32_COPYSIGN: ValType.F32,
    Opcode.F64_ABS: ValType.F64,
    Opcode.F64_NEG: ValType.F64,
    Opcode.F64_CEIL: ValType.F64,
    Opcode.F64_FLOOR: ValType.F64,
    Opcode.F64_TRUNC: ValType.F64,
    Opcode.F64_NEAREST: ValType.F64,
    Opcode.F64_SQRT: ValType.F64,
    Opcode.F64_ADD: ValType.F64,
    Opcode.F64_SUB: ValType.F64,
    Opcode.F64_MUL: ValType.F64,
    Opcode.F64_DIV: ValType.F64,
    Opcode.F64_MIN: ValType.F64,
    Opcode.F64_MAX: ValType.F64,
    Opcode.F64_COPYSIGN: ValType.F64,
}


# Instruction classification helpers
def is_control_flow(opcode: Opcode) -> bool:
    """Check if an opcode is a control flow instruction."""
    return opcode in (
        Opcode.UNREACHABLE, Opcode.NOP, Opcode.BLOCK, Opcode.LOOP,
        Opcode.IF, Opcode.ELSE, Opcode.END, Opcode.BR, Opcode.BR_IF,
        Opcode.BR_TABLE, Opcode.RETURN, Opcode.CALL, Opcode.CALL_INDIRECT,
    )


def is_memory_instruction(opcode: Opcode) -> bool:
    """Check if an opcode is a memory instruction."""
    return opcode in (
        Opcode.I32_LOAD, Opcode.I64_LOAD, Opcode.F32_LOAD, Opcode.F64_LOAD,
        Opcode.I32_LOAD8_S, Opcode.I32_LOAD8_U, Opcode.I32_LOAD16_S,
        Opcode.I32_LOAD16_U, Opcode.I64_LOAD8_S, Opcode.I64_LOAD8_U,
        Opcode.I64_LOAD16_S, Opcode.I64_LOAD16_U, Opcode.I64_LOAD32_S,
        Opcode.I64_LOAD32_U, Opcode.I32_STORE, Opcode.I64_STORE,
        Opcode.F32_STORE, Opcode.F64_STORE, Opcode.I32_STORE8,
        Opcode.I32_STORE16, Opcode.I64_STORE8, Opcode.I64_STORE16,
        Opcode.I64_STORE32, Opcode.MEMORY_SIZE, Opcode.MEMORY_GROW,
        Opcode.MEMORY_INIT, Opcode.MEMORY_COPY, Opcode.MEMORY_FILL,
        Opcode.DATA_DROP,
    )


def is_comparison(opcode: Opcode) -> bool:
    """Check if an opcode is a comparison instruction."""
    return opcode in (
        Opcode.I32_EQZ, Opcode.I32_EQ, Opcode.I32_NE,
        Opcode.I32_LT_S, Opcode.I32_LT_U, Opcode.I32_GT_S, Opcode.I32_GT_U,
        Opcode.I32_LE_S, Opcode.I32_LE_U, Opcode.I32_GE_S, Opcode.I32_GE_U,
        Opcode.I64_EQZ, Opcode.I64_EQ, Opcode.I64_NE,
        Opcode.I64_LT_S, Opcode.I64_LT_U, Opcode.I64_GT_S, Opcode.I64_GT_U,
        Opcode.I64_LE_S, Opcode.I64_LE_U, Opcode.I64_GE_S, Opcode.I64_GE_U,
        Opcode.F32_EQ, Opcode.F32_NE, Opcode.F32_LT, Opcode.F32_GT,
        Opcode.F32_LE, Opcode.F32_GE,
        Opcode.F64_EQ, Opcode.F64_NE, Opcode.F64_LT, Opcode.F64_GT,
        Opcode.F64_LE, Opcode.F64_GE,
    )


def is_arithmetic(opcode: Opcode) -> bool:
    """Check if an opcode is an arithmetic instruction."""
    return opcode in (
        Opcode.I32_CLZ, Opcode.I32_CTZ, Opcode.I32_POPCNT,
        Opcode.I32_ADD, Opcode.I32_SUB, Opcode.I32_MUL,
        Opcode.I32_DIV_S, Opcode.I32_DIV_U, Opcode.I32_REM_S, Opcode.I32_REM_U,
        Opcode.I32_AND, Opcode.I32_OR, Opcode.I32_XOR,
        Opcode.I32_SHL, Opcode.I32_SHR_S, Opcode.I32_SHR_U,
        Opcode.I32_ROTL, Opcode.I32_ROTR,
        Opcode.I64_CLZ, Opcode.I64_CTZ, Opcode.I64_POPCNT,
        Opcode.I64_ADD, Opcode.I64_SUB, Opcode.I64_MUL,
        Opcode.I64_DIV_S, Opcode.I64_DIV_U, Opcode.I64_REM_S, Opcode.I64_REM_U,
        Opcode.I64_AND, Opcode.I64_OR, Opcode.I64_XOR,
        Opcode.I64_SHL, Opcode.I64_SHR_S, Opcode.I64_SHR_U,
        Opcode.I64_ROTL, Opcode.I64_ROTR,
        Opcode.F32_ABS, Opcode.F32_NEG, Opcode.F32_CEIL, Opcode.F32_FLOOR,
        Opcode.F32_TRUNC, Opcode.F32_NEAREST, Opcode.F32_SQRT,
        Opcode.F32_ADD, Opcode.F32_SUB, Opcode.F32_MUL, Opcode.F32_DIV,
        Opcode.F32_MIN, Opcode.F32_MAX, Opcode.F32_COPYSIGN,
        Opcode.F64_ABS, Opcode.F64_NEG, Opcode.F64_CEIL, Opcode.F64_FLOOR,
        Opcode.F64_TRUNC, Opcode.F64_NEAREST, Opcode.F64_SQRT,
        Opcode.F64_ADD, Opcode.F64_SUB, Opcode.F64_MUL, Opcode.F64_DIV,
        Opcode.F64_MIN, Opcode.F64_MAX, Opcode.F64_COPYSIGN,
    )


def is_conversion(opcode: Opcode) -> bool:
    """Check if an opcode is a type conversion instruction."""
    return opcode in (
        Opcode.I32_WRAP_I64, Opcode.I32_TRUNC_F32_S, Opcode.I32_TRUNC_F32_U,
        Opcode.I32_TRUNC_F64_S, Opcode.I32_TRUNC_F64_U,
        Opcode.I64_EXTEND_I32_S, Opcode.I64_EXTEND_I32_U,
        Opcode.I64_TRUNC_F32_S, Opcode.I64_TRUNC_F32_U,
        Opcode.I64_TRUNC_F64_S, Opcode.I64_TRUNC_F64_U,
        Opcode.F32_CONVERT_I32_S, Opcode.F32_CONVERT_I32_U,
        Opcode.F32_CONVERT_I64_S, Opcode.F32_CONVERT_I64_U,
        Opcode.F32_DEMOTE_F64,
        Opcode.F64_CONVERT_I32_S, Opcode.F64_CONVERT_I32_U,
        Opcode.F64_CONVERT_I64_S, Opcode.F64_CONVERT_I64_U,
        Opcode.F64_PROMOTE_F32,
        Opcode.I32_REINTERPRET_F32, Opcode.I64_REINTERPRET_F64,
        Opcode.F32_REINTERPRET_I32, Opcode.F64_REINTERPRET_I64,
        Opcode.I32_TRUNC_SAT_F32_S, Opcode.I32_TRUNC_SAT_F32_U,
        Opcode.I32_TRUNC_SAT_F64_S, Opcode.I32_TRUNC_SAT_F64_U,
        Opcode.I64_TRUNC_SAT_F32_S, Opcode.I64_TRUNC_SAT_F32_U,
        Opcode.I64_TRUNC_SAT_F64_S, Opcode.I64_TRUNC_SAT_F64_U,
    )


def is_sign_extension(opcode: Opcode) -> bool:
    """Check if an opcode is a sign extension instruction."""
    return opcode in (
        Opcode.I32_EXTEND8_S, Opcode.I32_EXTEND16_S,
        Opcode.I64_EXTEND8_S, Opcode.I64_EXTEND16_S, Opcode.I64_EXTEND32_S,
    )


def is_reference_type(opcode: Opcode) -> bool:
    """Check if an opcode is a reference type instruction."""
    return opcode in (
        Opcode.REF_NULL, Opcode.REF_IS_NULL, Opcode.REF_FUNC,
    )


def is_table_instruction(opcode: Opcode) -> bool:
    """Check if an opcode is a table instruction."""
    return opcode in (
        Opcode.TABLE_GET, Opcode.TABLE_SET,
        Opcode.TABLE_SIZE, Opcode.TABLE_GROW,
        Opcode.TABLE_FILL, Opcode.TABLE_COPY,
        Opcode.TABLE_INIT, Opcode.ELEM_DROP,
    )