"""WebAssembly module validator.

This module implements validation of WebAssembly modules according to
the WebAssembly specification, checking type correctness, control flow
structure, memory safety, and other constraints.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from .types import (
    FuncType, ValType, GlobalType, TableType, MemoryType,
    ImportType, ExportType, ElemType, Mutability, Limits,
    Import, Export, BlockType,
)
from .parser import WasmModule, WasmFunction, DataSegment, ElementSegment
from .decoder import Instruction, Opcode, is_control_flow, is_memory_instruction
from ..utils.leb128 import decode_unsigned_leb128


class ValidationError(Exception):
    """Exception raised for WebAssembly validation errors."""

    def __init__(self, message: str, context: Optional[str] = None):
        """Initialize the validation error.

        Args:
            message: Error description.
            context: Optional context about where the error occurred.
        """
        full_msg = f"{context}: {message}" if context else message
        super().__init__(full_msg)
        self.context = context


class ControlFrame:
    """Represents a control flow frame during validation.

    Tracks the expected stack types and label information for
    structured control flow validation.
    """

    def __init__(
        self,
        kind: str,
        block_type: BlockType,
        start_stack_height: int,
        unreachable: bool = False,
    ):
        """Initialize a control frame.

        Args:
            kind: The kind of frame ('block', 'loop', 'if', 'else').
            block_type: The block type annotation.
            start_stack_height: The stack height at the start of the block.
            unreachable: Whether the current position is unreachable.
        """
        self.kind = kind
        self.block_type = block_type
        self.start_stack_height = start_stack_height
        self.unreachable = unreachable
        self.continuation_height = start_stack_height + len(block_type.params)

    def __repr__(self) -> str:
        return f"ControlFrame({self.kind}, stack={self.start_stack_height})"


class WasmValidator:
    """Validator for WebAssembly modules.

    Performs structural validation according to the WebAssembly specification,
    including type checking, control flow validation, and section constraints.
    """

    def __init__(self, enable_extensions: bool = True):
        """Initialize the validator.

        Args:
            enable_extensions: Whether to enable extended feature validation.
        """
        self.enable_extensions = enable_extensions

    def validate(self, module: WasmModule) -> List[str]:
        """Validate a complete WebAssembly module.

        Args:
            module: The parsed module to validate.

        Returns:
            A list of validation error messages (empty if valid).
        """
        errors: List[str] = []

        try:
            self._validate_module_structure(module, errors)
        except ValidationError as e:
            errors.append(str(e))

        return errors

    def _validate_module_structure(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the overall structure of the module.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        # Validate version
        if module.version != 1:
            errors.append(f"Unsupported module version: {module.version}")

        # Validate types
        self._validate_types(module, errors)

        # Validate imports
        self._validate_imports(module, errors)

        # Validate functions
        self._validate_functions(module, errors)

        # Validate tables
        self._validate_tables(module, errors)

        # Validate memories
        self._validate_memories(module, errors)

        # Validate globals
        self._validate_globals(module, errors)

        # Validate exports
        self._validate_exports(module, errors)

        # Validate start
        self._validate_start(module, errors)

        # Validate elements
        self._validate_elements(module, errors)

        # Validate data segments
        self._validate_data_segments(module, errors)

    def _validate_types(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the type section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        for i, functype in enumerate(module.types):
            if len(functype.params) > 1000:
                errors.append(f"Type {i}: too many parameters ({len(functype.params)})")
            if len(functype.results) > 1000:
                errors.append(f"Type {i}: too many results ({len(functype.results)})")

    def _validate_imports(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the import section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        for i, imp in enumerate(module.imports):
            if imp.import_type == ImportType.FUNCTION:
                if imp.type_index is not None and imp.type_index >= len(module.types):
                    errors.append(
                        f"Import {i} ({imp.module}.{imp.field}): "
                        f"type index {imp.type_index} out of range"
                    )

    def _validate_functions(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the function and code sections.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        for i, func in enumerate(module.functions):
            if func.type_index >= len(module.types):
                errors.append(f"Function {i}: type index {func.type_index} out of range")
                continue

            functype = module.types[func.type_index]

            try:
                func_errors = self.validate_function_body(func, functype, module.types)
                errors.extend(f"Function {i}: {e}" for e in func_errors)
            except ValidationError as e:
                errors.append(f"Function {i}: {e}")

    def validate_function_body(
        self,
        func: WasmFunction,
        functype: FuncType,
        types: List[FuncType],
    ) -> List[str]:
        """Validate a single function body.

        Args:
            func: The function to validate.
            functype: The function's type signature.
            types: All types in the module.

        Returns:
            A list of validation errors.
        """
        errors: List[str] = []

        # Validate local variable types
        for j, (valtype, count) in enumerate(func.locals):
            if count == 0:
                errors.append(f"Local {j}: zero count")
            if valtype not in (ValType.I32, ValType.I64, ValType.F32, ValType.F64,
                                ValType.V128, ValType.FUNCREF, ValType.EXTERNREF):
                errors.append(f"Local {j}: invalid type {valtype}")

        # Total locals check
        total_locals = functype.param_count + func.local_count
        if total_locals > 50000:
            errors.append(f"Too many locals: {total_locals}")

        # Validate instructions
        if func.instructions:
            instr_errors = self._validate_instructions(
                func.instructions,
                functype,
                types,
                func.local_count,
                functype.param_count,
            )
            errors.extend(instr_errors)

        return errors

    def _validate_instructions(
        self,
        instructions: List[Instruction],
        functype: FuncType,
        types: List[FuncType],
        local_count: int,
        param_count: int,
    ) -> List[str]:
        """Validate a sequence of instructions.

        Uses a symbolic validation approach to track the type stack
        and validate each instruction's type constraints.

        Args:
            instructions: The instructions to validate.
            functype: The function type.
            types: All types in the module.
            local_count: Number of local variables.
            param_count: Number of parameters.

        Returns:
            A list of validation errors.
        """
        errors: List[str] = []
        type_stack: List[ValType] = []
        control_stack: List[ControlFrame] = []
        unreachable: bool = False

        # Initialize with parameters on the stack conceptually
        # (they are locals, not on the value stack)

        try:
            for instr_idx, instr in enumerate(instructions):
                try:
                    self._validate_instruction(
                        instr, instr_idx, type_stack, control_stack,
                        unreachable, functype, types, local_count, param_count,
                    )
                except ValidationError as e:
                    errors.append(f"At instruction {instr_idx} ({instr.name}): {e}")

            # After all instructions, we should be at the end of all blocks
            if control_stack:
                errors.append(f"Unclosed control blocks: {len(control_stack)} remaining")

            # Check that the final stack matches the function results
            if not unreachable and len(control_stack) == 0:
                if len(type_stack) != len(functype.results):
                    errors.append(
                        f"Final stack has {len(type_stack)} values but "
                        f"function expects {len(functype.results)} results"
                    )

        except Exception as e:
            errors.append(f"Unexpected validation error: {e}")

        return errors

    def _validate_instruction(
        self,
        instr: Instruction,
        instr_idx: int,
        type_stack: List[ValType],
        control_stack: List[ControlFrame],
        unreachable: bool,
        functype: FuncType,
        types: List[FuncType],
        local_count: int,
        param_count: int,
    ) -> None:
        """Validate a single instruction.

        Args:
            instr: The instruction to validate.
            instr_idx: Index of the instruction.
            type_stack: The current type stack.
            control_stack: The control flow stack.
            unreachable: Whether the current position is unreachable.
            functype: The function type.
            types: All types in the module.
            local_count: Total number of local variables.
            param_count: Number of parameters.

        Raises:
            ValidationError: If the instruction is invalid.
        """
        opcode = instr.opcode

        # Handle unreachable
        if opcode == Opcode.UNREACHABLE:
            unreachable = True
            return

        if opcode == Opcode.NOP:
            return

        # Control flow
        if opcode == Opcode.BLOCK:
            self._validate_block(instr, type_stack, control_stack, unreachable, types)
        elif opcode == Opcode.LOOP:
            self._validate_loop(instr, type_stack, control_stack, unreachable, types)
        elif opcode == Opcode.IF:
            self._validate_if(instr, type_stack, control_stack, unreachable, types)
            self._pop_operand(type_stack, ValType.I32, "if")
        elif opcode == Opcode.ELSE:
            self._validate_else(type_stack, control_stack)
        elif opcode == Opcode.END:
            self._validate_end(type_stack, control_stack, unreachable)
        elif opcode == Opcode.BR:
            self._validate_br(instr, control_stack, type_stack, unreachable)
        elif opcode == Opcode.BR_IF:
            self._validate_br_if(instr, control_stack, type_stack, unreachable)
        elif opcode == Opcode.BR_TABLE:
            self._validate_br_table(instr, control_stack, type_stack, unreachable)
        elif opcode == Opcode.RETURN:
            self._validate_return(functype, type_stack, unreachable)
        elif opcode == Opcode.CALL:
            self._validate_call(instr, functype, types, type_stack, unreachable)
        elif opcode == Opcode.CALL_INDIRECT:
            self._validate_call_indirect(instr, types, type_stack, unreachable)

        # Parametric
        elif opcode == Opcode.DROP:
            if not unreachable:
                self._pop_operand(type_stack, None, "drop")
        elif opcode == Opcode.SELECT:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "select condition")
                # Pop two values of the same type
                t1 = self._pop_operand(type_stack, None, "select")
                t2 = self._pop_operand(type_stack, None, "select")
                if t1 is not None and t2 is not None and t1 != t2:
                    raise ValidationError(f"select: operand type mismatch ({t1} vs {t2})")
                result_type = t1 if t1 is not None else (t2 if t2 is not None else ValType.I32)
                type_stack.append(result_type)
        elif opcode == Opcode.SELECT_T:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "select_t condition")
                t1 = self._pop_operand(type_stack, None, "select_t")
                t2 = self._pop_operand(type_stack, None, "select_t")
                # Use the type from immediates
                if instr.immediates and instr.immediates[0]:
                    result_type = instr.immediates[0][0]
                    type_stack.append(result_type)
                else:
                    type_stack.append(ValType.I32)

        # Variable access
        elif opcode == Opcode.LOCAL_GET:
            if not unreachable:
                idx = instr.immediates[0]
                if idx >= local_count + param_count:
                    raise ValidationError(f"local.get: index {idx} out of range")
                # Determine type from locals or params
                type_stack.append(ValType.I32)  # Simplified
        elif opcode == Opcode.LOCAL_SET:
            if not unreachable:
                idx = instr.immediates[0]
                if idx >= local_count + param_count:
                    raise ValidationError(f"local.set: index {idx} out of range")
                self._pop_operand(type_stack, None, "local.set")
        elif opcode == Opcode.LOCAL_TEE:
            if not unreachable:
                idx = instr.immediates[0]
                if idx >= local_count + param_count:
                    raise ValidationError(f"local.tee: index {idx} out of range")
                val = self._pop_operand(type_stack, None, "local.tee")
                if val is not None:
                    type_stack.append(val)
        elif opcode == Opcode.GLOBAL_GET:
            pass  # Simplified
        elif opcode == Opcode.GLOBAL_SET:
            if not unreachable:
                self._pop_operand(type_stack, None, "global.set")

        # Memory
        elif is_memory_instruction(opcode):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "memory address")
                if opcode in (Opcode.I32_STORE, Opcode.I64_STORE, Opcode.F32_STORE,
                               Opcode.F64_STORE, Opcode.I32_STORE8, Opcode.I32_STORE16,
                               Opcode.I64_STORE8, Opcode.I64_STORE16, Opcode.I64_STORE32):
                    self._pop_operand(type_stack, None, "store value")
                elif opcode == Opcode.MEMORY_SIZE:
                    type_stack.append(ValType.I32)
                elif opcode == Opcode.MEMORY_GROW:
                    self._pop_operand(type_stack, ValType.I32, "memory.grow pages")
                    type_stack.append(ValType.I32)
                else:
                    # Load instructions push a value
                    load_type = self._get_load_result_type(opcode)
                    type_stack.append(load_type)

        # Constants
        elif opcode == Opcode.I32_CONST:
            if not unreachable:
                type_stack.append(ValType.I32)
        elif opcode == Opcode.I64_CONST:
            if not unreachable:
                type_stack.append(ValType.I64)
        elif opcode == Opcode.F32_CONST:
            if not unreachable:
                type_stack.append(ValType.F32)
        elif opcode == Opcode.F64_CONST:
            if not unreachable:
                type_stack.append(ValType.F64)

        # Reference types
        elif opcode == Opcode.REF_NULL:
            if not unreachable:
                type_stack.append(ValType.FUNCREF)
        elif opcode == Opcode.REF_IS_NULL:
            if not unreachable:
                self._pop_operand(type_stack, None, "ref.is_null")
                type_stack.append(ValType.I32)
        elif opcode == Opcode.REF_FUNC:
            if not unreachable:
                type_stack.append(ValType.FUNCREF)

        # Table instructions
        elif opcode == Opcode.TABLE_GET:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "table.get index")
                type_stack.append(ValType.FUNCREF)
        elif opcode == Opcode.TABLE_SET:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "table.set index")
                self._pop_operand(type_stack, None, "table.set value")

        # Comparison operators
        elif opcode in (Opcode.I32_EQZ, Opcode.I32_EQ, Opcode.I32_NE,
                         Opcode.I32_LT_S, Opcode.I32_LT_U, Opcode.I32_GT_S,
                         Opcode.I32_GT_U, Opcode.I32_LE_S, Opcode.I32_LE_U,
                         Opcode.I32_GE_S, Opcode.I32_GE_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                if opcode != Opcode.I32_EQZ:
                    self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I64_EQZ, Opcode.I64_EQ, Opcode.I64_NE,
                         Opcode.I64_LT_S, Opcode.I64_LT_U, Opcode.I64_GT_S,
                         Opcode.I64_GT_U, Opcode.I64_LE_S, Opcode.I64_LE_U,
                         Opcode.I64_GE_S, Opcode.I64_GE_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                if opcode != Opcode.I64_EQZ:
                    self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.F32_EQ, Opcode.F32_NE, Opcode.F32_LT,
                         Opcode.F32_GT, Opcode.F32_LE, Opcode.F32_GE):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.F64_EQ, Opcode.F64_NE, Opcode.F64_LT,
                         Opcode.F64_GT, Opcode.F64_LE, Opcode.F64_GE):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                type_stack.append(ValType.I32)

        # Arithmetic operators (i32)
        elif opcode in (Opcode.I32_CLZ, Opcode.I32_CTZ, Opcode.I32_POPCNT):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I32_ADD, Opcode.I32_SUB, Opcode.I32_MUL,
                         Opcode.I32_DIV_S, Opcode.I32_DIV_U,
                         Opcode.I32_REM_S, Opcode.I32_REM_U,
                         Opcode.I32_AND, Opcode.I32_OR, Opcode.I32_XOR,
                         Opcode.I32_SHL, Opcode.I32_SHR_S, Opcode.I32_SHR_U,
                         Opcode.I32_ROTL, Opcode.I32_ROTR):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                type_stack.append(ValType.I32)

        # Arithmetic operators (i64)
        elif opcode in (Opcode.I64_CLZ, Opcode.I64_CTZ, Opcode.I64_POPCNT):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                type_stack.append(ValType.I64)
        elif opcode in (Opcode.I64_ADD, Opcode.I64_SUB, Opcode.I64_MUL,
                         Opcode.I64_DIV_S, Opcode.I64_DIV_U,
                         Opcode.I64_REM_S, Opcode.I64_REM_U,
                         Opcode.I64_AND, Opcode.I64_OR, Opcode.I64_XOR,
                         Opcode.I64_SHL, Opcode.I64_SHR_S, Opcode.I64_SHR_U,
                         Opcode.I64_ROTL, Opcode.I64_ROTR):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                type_stack.append(ValType.I64)

        # Arithmetic operators (f32)
        elif opcode in (Opcode.F32_ABS, Opcode.F32_NEG, Opcode.F32_CEIL,
                         Opcode.F32_FLOOR, Opcode.F32_TRUNC, Opcode.F32_NEAREST,
                         Opcode.F32_SQRT):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                type_stack.append(ValType.F32)
        elif opcode in (Opcode.F32_ADD, Opcode.F32_SUB, Opcode.F32_MUL,
                         Opcode.F32_DIV, Opcode.F32_MIN, Opcode.F32_MAX,
                         Opcode.F32_COPYSIGN):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                type_stack.append(ValType.F32)

        # Arithmetic operators (f64)
        elif opcode in (Opcode.F64_ABS, Opcode.F64_NEG, Opcode.F64_CEIL,
                         Opcode.F64_FLOOR, Opcode.F64_TRUNC, Opcode.F64_NEAREST,
                         Opcode.F64_SQRT):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                type_stack.append(ValType.F64)
        elif opcode in (Opcode.F64_ADD, Opcode.F64_SUB, Opcode.F64_MUL,
                         Opcode.F64_DIV, Opcode.F64_MIN, Opcode.F64_MAX,
                         Opcode.F64_COPYSIGN):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                type_stack.append(ValType.F64)

        # Conversions
        elif opcode == Opcode.I32_WRAP_I64:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, "i32.wrap_i64")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I32_TRUNC_F32_S, Opcode.I32_TRUNC_F32_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I32_TRUNC_F64_S, Opcode.I32_TRUNC_F64_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I64_EXTEND_I32_S, Opcode.I64_EXTEND_I32_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                type_stack.append(ValType.I64)
        elif opcode in (Opcode.I64_TRUNC_F32_S, Opcode.I64_TRUNC_F32_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                type_stack.append(ValType.I64)
        elif opcode in (Opcode.I64_TRUNC_F64_S, Opcode.I64_TRUNC_F64_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                type_stack.append(ValType.I64)
        elif opcode in (Opcode.F32_CONVERT_I32_S, Opcode.F32_CONVERT_I32_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                type_stack.append(ValType.F32)
        elif opcode in (Opcode.F32_CONVERT_I64_S, Opcode.F32_CONVERT_I64_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                type_stack.append(ValType.F32)
        elif opcode == Opcode.F32_DEMOTE_F64:
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, "f32.demote_f64")
                type_stack.append(ValType.F32)
        elif opcode in (Opcode.F64_CONVERT_I32_S, Opcode.F64_CONVERT_I32_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                type_stack.append(ValType.F64)
        elif opcode in (Opcode.F64_CONVERT_I64_S, Opcode.F64_CONVERT_I64_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                type_stack.append(ValType.F64)
        elif opcode == Opcode.F64_PROMOTE_F32:
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, "f64.promote_f32")
                type_stack.append(ValType.F64)

        # Reinterpretations
        elif opcode in (Opcode.I32_REINTERPRET_F32,):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, "i32.reinterpret_f32")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I64_REINTERPRET_F64,):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, "i64.reinterpret_f64")
                type_stack.append(ValType.I64)
        elif opcode in (Opcode.F32_REINTERPRET_I32,):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "f32.reinterpret_i32")
                type_stack.append(ValType.F32)
        elif opcode in (Opcode.F64_REINTERPRET_I64,):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, "f64.reinterpret_i64")
                type_stack.append(ValType.F64)

        # Sign extension
        elif opcode in (Opcode.I32_EXTEND8_S, Opcode.I32_EXTEND16_S):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I64_EXTEND8_S, Opcode.I64_EXTEND16_S, Opcode.I64_EXTEND32_S):
            if not unreachable:
                self._pop_operand(type_stack, ValType.I64, f"{instr.name}")
                type_stack.append(ValType.I64)

        # Bulk memory operations
        elif opcode == Opcode.MEMORY_INIT:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "memory.init n")
                self._pop_operand(type_stack, ValType.I32, "memory.init s")
                self._pop_operand(type_stack, ValType.I32, "memory.init d")
        elif opcode == Opcode.DATA_DROP:
            pass
        elif opcode == Opcode.MEMORY_COPY:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "memory.copy n")
                self._pop_operand(type_stack, ValType.I32, "memory.copy s")
                self._pop_operand(type_stack, ValType.I32, "memory.copy d")
        elif opcode == Opcode.MEMORY_FILL:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "memory.fill n")
                self._pop_operand(type_stack, ValType.I32, "memory.fill val")
                self._pop_operand(type_stack, ValType.I32, "memory.fill d")

        # Table operations
        elif opcode == Opcode.TABLE_INIT:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "table.init n")
                self._pop_operand(type_stack, ValType.I32, "table.init s")
                self._pop_operand(type_stack, ValType.I32, "table.init d")
        elif opcode == Opcode.ELEM_DROP:
            pass
        elif opcode == Opcode.TABLE_COPY:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "table.copy n")
                self._pop_operand(type_stack, ValType.I32, "table.copy s")
                self._pop_operand(type_stack, ValType.I32, "table.copy d")
        elif opcode == Opcode.TABLE_FILL:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "table.fill n")
                self._pop_operand(type_stack, None, "table.fill val")
                self._pop_operand(type_stack, ValType.I32, "table.fill d")
        elif opcode == Opcode.TABLE_GROW:
            if not unreachable:
                self._pop_operand(type_stack, ValType.I32, "table.grow n")
                self._pop_operand(type_stack, None, "table.grow val")
                type_stack.append(ValType.I32)
        elif opcode == Opcode.TABLE_SIZE:
            if not unreachable:
                type_stack.append(ValType.I32)

        # Truncation with saturation
        elif opcode in (Opcode.I32_TRUNC_SAT_F32_S, Opcode.I32_TRUNC_SAT_F32_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I32_TRUNC_SAT_F64_S, Opcode.I32_TRUNC_SAT_F64_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                type_stack.append(ValType.I32)
        elif opcode in (Opcode.I64_TRUNC_SAT_F32_S, Opcode.I64_TRUNC_SAT_F32_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F32, f"{instr.name}")
                type_stack.append(ValType.I64)
        elif opcode in (Opcode.I64_TRUNC_SAT_F64_S, Opcode.I64_TRUNC_SAT_F64_U):
            if not unreachable:
                self._pop_operand(type_stack, ValType.F64, f"{instr.name}")
                type_stack.append(ValType.I64)

        else:
            # Unknown opcode
            if self.enable_extensions:
                pass  # Allow unknown opcodes in extension mode
            else:
                raise ValidationError(f"Unknown or unsupported opcode: {instr.name}")

    def _validate_block(
        self,
        instr: Instruction,
        type_stack: List[ValType],
        control_stack: List[ControlFrame],
        unreachable: bool,
        types: List[FuncType],
    ) -> None:
        """Validate a BLOCK instruction.

        Args:
            instr: The BLOCK instruction.
            type_stack: The current type stack.
            control_stack: The control flow stack.
            unreachable: Whether the current position is unreachable.
            types: All types in the module.
        """
        if not unreachable:
            block_type = instr.block_type or BlockType.empty()
            # Pop block parameters
            for param_type in reversed(block_type.params):
                self._pop_operand(type_stack, param_type, "block param")

            frame = ControlFrame("block", block_type, len(type_stack), unreachable)
            control_stack.append(frame)
        else:
            frame = ControlFrame("block", BlockType.empty(), len(type_stack), True)
            control_stack.append(frame)

    def _validate_loop(
        self,
        instr: Instruction,
        type_stack: List[ValType],
        control_stack: List[ControlFrame],
        unreachable: bool,
        types: List[FuncType],
    ) -> None:
        """Validate a LOOP instruction.

        Args:
            instr: The LOOP instruction.
            type_stack: The current type stack.
            control_stack: The control flow stack.
            unreachable: Whether the current position is unreachable.
            types: All types in the module.
        """
        if not unreachable:
            block_type = instr.block_type or BlockType.empty()
            # Pop loop parameters
            for param_type in reversed(block_type.params):
                self._pop_operand(type_stack, param_type, "loop param")

            frame = ControlFrame("loop", block_type, len(type_stack), unreachable)
            control_stack.append(frame)
        else:
            frame = ControlFrame("loop", BlockType.empty(), len(type_stack), True)
            control_stack.append(frame)

    def _validate_if(
        self,
        instr: Instruction,
        type_stack: List[ValType],
        control_stack: List[ControlFrame],
        unreachable: bool,
        types: List[FuncType],
    ) -> None:
        """Validate an IF instruction.

        Args:
            instr: The IF instruction.
            type_stack: The current type stack.
            control_stack: The control flow stack.
            unreachable: Whether the current position is unreachable.
            types: All types in the module.
        """
        if not unreachable:
            block_type = instr.block_type or BlockType.empty()
            # Pop if parameters
            for param_type in reversed(block_type.params):
                self._pop_operand(type_stack, param_type, "if param")

            frame = ControlFrame("if", block_type, len(type_stack), unreachable)
            control_stack.append(frame)
        else:
            frame = ControlFrame("if", BlockType.empty(), len(type_stack), True)
            control_stack.append(frame)

    def _validate_else(
        self,
        type_stack: List[ValType],
        control_stack: List[ControlFrame],
    ) -> None:
        """Validate an ELSE instruction.

        Args:
            type_stack: The current type stack.
            control_stack: The control flow stack.

        Raises:
            ValidationError: If ELSE is invalid.
        """
        if not control_stack:
            raise ValidationError("ELSE without matching IF")

        frame = control_stack[-1]
        if frame.kind != "if":
            raise ValidationError(f"ELSE without matching IF (found {frame.kind})")

        # Reset stack to frame start + params
        self._reset_stack_to_frame(type_stack, frame)

    def _validate_end(
        self,
        type_stack: List[ValType],
        control_stack: List[ControlFrame],
        unreachable: bool,
    ) -> None:
        """Validate an END instruction.

        Args:
            type_stack: The current type stack.
            control_stack: The control flow stack.
            unreachable: Whether the current position is unreachable.

        Raises:
            ValidationError: If END is invalid.
        """
        if not control_stack:
            raise ValidationError("END without matching block")

        frame = control_stack.pop()

        if not unreachable:
            block_results = frame.block_type.results
            expected_height = frame.start_stack_height + len(block_results)

            if len(type_stack) < expected_height:
                raise ValidationError(
                    f"End of {frame.kind}: stack has {len(type_stack)} values, "
                    f"expected at least {expected_height}"
                )

            # Truncate stack to the expected height
            while len(type_stack) > expected_height:
                type_stack.pop()

    def _validate_br(
        self,
        instr: Instruction,
        control_stack: List[ControlFrame],
        type_stack: List[ValType],
        unreachable: bool,
    ) -> None:
        """Validate a BR instruction.

        Args:
            instr: The BR instruction.
            control_stack: The control flow stack.
            type_stack: The current type stack.
            unreachable: Whether the current position is unreachable.

        Raises:
            ValidationError: If BR is invalid.
        """
        if not instr.immediates:
            raise ValidationError("BR: missing label index")
        label_idx = instr.immediates[0]

        if label_idx >= len(control_stack):
            raise ValidationError(f"BR: label index {label_idx} out of range")

        target_frame = control_stack[-(label_idx + 1)]
        arity = len(target_frame.block_type.params) if target_frame.kind == "loop" else len(target_frame.block_type.results)

        if not unreachable and len(type_stack) < target_frame.start_stack_height + arity:
            raise ValidationError(
                f"BR: stack has {len(type_stack)} values, "
                f"expected at least {target_frame.start_stack_height + arity}"
            )

    def _validate_br_if(
        self,
        instr: Instruction,
        control_stack: List[ControlFrame],
        type_stack: List[ValType],
        unreachable: bool,
    ) -> None:
        """Validate a BR_IF instruction.

        Args:
            instr: The BR_IF instruction.
            control_stack: The control flow stack.
            type_stack: The current type stack.
            unreachable: Whether the current position is unreachable.

        Raises:
            ValidationError: If BR_IF is invalid.
        """
        # Pop condition
        if not unreachable:
            self._pop_operand(type_stack, ValType.I32, "br_if condition")

        # Validate branch target (same as br)
        self._validate_br(instr, control_stack, type_stack, unreachable)

    def _validate_br_table(
        self,
        instr: Instruction,
        control_stack: List[ControlFrame],
        type_stack: List[ValType],
        unreachable: bool,
    ) -> None:
        """Validate a BR_TABLE instruction.

        Args:
            instr: The BR_TABLE instruction.
            control_stack: The control flow stack.
            type_stack: The current type stack.
            unreachable: Whether the current position is unreachable.

        Raises:
            ValidationError: If BR_TABLE is invalid.
        """
        if not unreachable:
            self._pop_operand(type_stack, ValType.I32, "br_table index")

        if not instr.immediates or len(instr.immediates) < 2:
            raise ValidationError("BR_TABLE: missing targets")

        targets = instr.immediates[0]
        default_target = instr.immediates[1]

        for target in targets:
            if target >= len(control_stack):
                raise ValidationError(f"BR_TABLE: target {target} out of range")

        if default_target >= len(control_stack):
            raise ValidationError(f"BR_TABLE: default target {default_target} out of range")

    def _validate_return(
        self,
        functype: FuncType,
        type_stack: List[ValType],
        unreachable: bool,
    ) -> None:
        """Validate a RETURN instruction.

        Args:
            functype: The function type.
            type_stack: The current type stack.
            unreachable: Whether the current position is unreachable.

        Raises:
            ValidationError: If RETURN is invalid.
        """
        if not unreachable:
            if len(type_stack) < len(functype.results):
                raise ValidationError(
                    f"RETURN: stack has {len(type_stack)} values, "
                    f"function expects {len(functype.results)} results"
                )

    def _validate_call(
        self,
        instr: Instruction,
        functype: FuncType,
        types: List[FuncType],
        type_stack: List[ValType],
        unreachable: bool,
    ) -> None:
        """Validate a CALL instruction.

        Args:
            instr: The CALL instruction.
            functype: The current function type.
            types: All types in the module.
            type_stack: The current type stack.
            unreachable: Whether the current position is unreachable.

        Raises:
            ValidationError: If CALL is invalid.
        """
        if not instr.immediates:
            raise ValidationError("CALL: missing function index")
        func_idx = instr.immediates[0]

        # We can't validate the callee type without knowing all functions,
        # so we just pop/push the right number of values
        if not unreachable:
            # Pop parameters (simplified - we don't know the exact types)
            # In a full implementation, we'd look up the function's type
            self._pop_operand(type_stack, None, "call param")
            # Push results (simplified)
            type_stack.append(ValType.I32)

    def _validate_call_indirect(
        self,
        instr: Instruction,
        types: List[FuncType],
        type_stack: List[ValType],
        unreachable: bool,
    ) -> None:
        """Validate a CALL_INDIRECT instruction.

        Args:
            instr: The CALL_INDIRECT instruction.
            types: All types in the module.
            type_stack: The current type stack.
            unreachable: Whether the current position is unreachable.

        Raises:
            ValidationError: If CALL_INDIRECT is invalid.
        """
        if not instr.immediates:
            raise ValidationError("CALL_INDIRECT: missing type index")
        type_idx = instr.immediates[0]

        if type_idx >= len(types):
            raise ValidationError(f"CALL_INDIRECT: type index {type_idx} out of range")

        if not unreachable:
            self._pop_operand(type_stack, ValType.I32, "call_indirect table index")
            # Pop parameters and push results (simplified)
            functype = types[type_idx]
            for _ in functype.params:
                self._pop_operand(type_stack, None, "call_indirect param")
            for result_type in functype.results:
                type_stack.append(result_type)

    def _pop_operand(
        self,
        type_stack: List[ValType],
        expected: Optional[ValType],
        context: str = "",
    ) -> Optional[ValType]:
        """Pop a value from the type stack, optionally checking its type.

        Args:
            type_stack: The type stack.
            expected: Expected type, or None to accept any type.
            context: Context description for error messages.

        Returns:
            The popped type, or None if the stack was empty and unreachable.

        Raises:
            ValidationError: If the stack is empty or the type doesn't match.
        """
        if not type_stack:
            raise ValidationError(f"Stack underflow: {context}")

        actual = type_stack.pop()
        if expected is not None and actual != expected:
            raise ValidationError(
                f"Type mismatch in {context}: expected {expected}, got {actual}"
            )
        return actual

    def _reset_stack_to_frame(
        self,
        type_stack: List[ValType],
        frame: ControlFrame,
    ) -> None:
        """Reset the type stack to the state at the beginning of a frame.

        Args:
            type_stack: The type stack to reset.
            frame: The control frame to reset to.
        """
        while len(type_stack) > frame.start_stack_height:
            type_stack.pop()

    def _get_load_result_type(self, opcode: Opcode) -> ValType:
        """Get the result type of a load instruction.

        Args:
            opcode: The load opcode.

        Returns:
            The result value type.
        """
        load_result_map = {
            Opcode.I32_LOAD: ValType.I32,
            Opcode.I32_LOAD8_S: ValType.I32,
            Opcode.I32_LOAD8_U: ValType.I32,
            Opcode.I32_LOAD16_S: ValType.I32,
            Opcode.I32_LOAD16_U: ValType.I32,
            Opcode.I64_LOAD: ValType.I64,
            Opcode.I64_LOAD8_S: ValType.I64,
            Opcode.I64_LOAD8_U: ValType.I64,
            Opcode.I64_LOAD16_S: ValType.I64,
            Opcode.I64_LOAD16_U: ValType.I64,
            Opcode.I64_LOAD32_S: ValType.I64,
            Opcode.I64_LOAD32_U: ValType.I64,
            Opcode.F32_LOAD: ValType.F32,
            Opcode.F64_LOAD: ValType.F64,
        }
        return load_result_map.get(opcode, ValType.I32)

    def _validate_tables(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the table section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        for i, table in enumerate(module.tables):
            if table.min_size > 10000000:
                errors.append(f"Table {i}: initial size {table.min_size} too large")
            if table.max_size is not None and table.max_size < table.min_size:
                errors.append(f"Table {i}: max size {table.max_size} < min size {table.min_size}")

    def _validate_memories(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the memory section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        for i, memory in enumerate(module.memories):
            if memory.min_size > 65536:
                errors.append(f"Memory {i}: initial size {memory.min_size} pages exceeds max")
            if memory.max_size is not None and memory.max_size < memory.min_size:
                errors.append(
                    f"Memory {i}: max size {memory.max_size} < min size {memory.min_size}"
                )

    def _validate_globals(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the global section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        for i, (global_type, _, _) in enumerate(module.globals):
            if global_type.val_type not in (ValType.I32, ValType.I64, ValType.F32, ValType.F64):
                errors.append(f"Global {i}: invalid type {global_type.val_type}")

    def _validate_exports(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the export section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        export_names: Set[str] = set()
        for i, export in enumerate(module.exports):
            if export.name in export_names:
                errors.append(f"Export {i}: duplicate name '{export.name}'")
            export_names.add(export.name)

            # Check export is valid
            if export.export_type == ExportType.FUNCTION:
                total_funcs = len(module.functions) + sum(
                    1 for imp in module.imports if imp.import_type == ImportType.FUNCTION
                )
                if export.index >= total_funcs:
                    errors.append(f"Export '{export.name}': function index {export.index} out of range")
            elif export.export_type == ExportType.TABLE:
                total_tables = len(module.tables) + sum(
                    1 for imp in module.imports if imp.import_type == ImportType.TABLE
                )
                if export.index >= total_tables:
                    errors.append(f"Export '{export.name}': table index {export.index} out of range")
            elif export.export_type == ExportType.MEMORY:
                total_memories = len(module.memories) + sum(
                    1 for imp in module.imports if imp.import_type == ImportType.MEMORY
                )
                if export.index >= total_memories:
                    errors.append(f"Export '{export.name}': memory index {export.index} out of range")
            elif export.export_type == ExportType.GLOBAL:
                total_globals = len(module.globals) + sum(
                    1 for imp in module.imports if imp.import_type == ImportType.GLOBAL
                )
                if export.index >= total_globals:
                    errors.append(f"Export '{export.name}': global index {export.index} out of range")

    def _validate_start(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the start section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        if module.start_function is not None:
            total_funcs = len(module.functions) + sum(
                1 for imp in module.imports if imp.import_type == ImportType.FUNCTION
            )
            if module.start_function >= total_funcs:
                errors.append(f"Start function index {module.start_function} out of range")

    def _validate_elements(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the element section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        for i, elem in enumerate(module.elements):
            if elem.is_active:
                total_tables = len(module.tables) + sum(
                    1 for imp in module.imports if imp.import_type == ImportType.TABLE
                )
                if elem.table_index >= total_tables:
                    errors.append(f"Element {i}: table index {elem.table_index} out of range")

    def _validate_data_segments(self, module: WasmModule, errors: List[str]) -> None:
        """Validate the data section.

        Args:
            module: The module to validate.
            errors: List to append errors to.
        """
        total_memories = len(module.memories) + sum(
            1 for imp in module.imports if imp.import_type == ImportType.MEMORY
        )
        for i, data_seg in enumerate(module.data_segments):
            if data_seg.is_active and total_memories == 0:
                errors.append(f"Data segment {i}: active but no memory defined")
            if data_seg.is_active and data_seg.memory_index >= total_memories:
                errors.append(f"Data segment {i}: memory index {data_seg.memory_index} out of range")


def validate_module(module: WasmModule) -> List[str]:
    """Validate a parsed WebAssembly module (convenience function).

    Args:
        module: The module to validate.

    Returns:
        A list of validation error messages (empty if valid).
    """
    validator = WasmValidator()
    return validator.validate(module)


def validate_module_strict(module: WasmModule) -> None:
    """Validate a module and raise an exception on the first error.

    Args:
        module: The module to validate.

    Raises:
        ValidationError: If the module is invalid.
    """
    errors = validate_module(module)
    if errors:
        raise ValidationError(errors[0])