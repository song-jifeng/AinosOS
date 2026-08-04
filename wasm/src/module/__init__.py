"""WebAssembly module parsing, type system, and validation."""

from .types import (
    ValType, FuncType, BlockType, GlobalType, TableType, MemoryType,
    ImportType, ExportType, ElemType, Mutability, Limits,
    Import, Export, Value, ValueStack, RefType,
)
from .parser import (
    WasmParser, WasmModule, WasmFunction, DataSegment, ElementSegment,
    parse_wasm, parse_wasm_file, WasmParseError,
)
from .decoder import (
    Opcode, MiscOpcode, SimdOpcode, Instruction, InstructionDecoder,
    is_control_flow, is_memory_instruction, is_comparison,
    is_arithmetic, is_conversion, get_opcode_name,
)
from .validator import WasmValidator, ValidationError, validate_module

__all__ = [
    # Types
    "ValType", "FuncType", "BlockType", "GlobalType", "TableType",
    "MemoryType", "ImportType", "ExportType", "ElemType", "Mutability",
    "Limits", "Import", "Export", "Value", "ValueStack", "RefType",
    # Parser
    "WasmParser", "WasmModule", "WasmFunction", "DataSegment",
    "ElementSegment", "parse_wasm", "parse_wasm_file", "WasmParseError",
    # Decoder
    "Opcode", "MiscOpcode", "SimdOpcode", "Instruction",
    "InstructionDecoder", "is_control_flow", "is_memory_instruction",
    "is_comparison", "is_arithmetic", "is_conversion", "get_opcode_name",
    # Validator
    "WasmValidator", "ValidationError", "validate_module",
]