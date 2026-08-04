"""WebAssembly binary format parser.

This module implements the parsing of WebAssembly binary modules (.wasm files),
extracting all sections and their contents into a structured Module object.
"""

from typing import Any, Dict, List, Optional, Tuple, Union

from .types import (
    FuncType, ValType, GlobalType, TableType, MemoryType,
    ImportType, ExportType, ElemType, Mutability, Limits,
    Import, Export, valtype_from_byte,
)
from .decoder import Instruction, InstructionDecoder, Opcode
from ..utils.leb128 import decode_unsigned_leb128, decode_signed_leb128, LEB128Reader


# Section IDs
SECTION_CUSTOM = 0
SECTION_TYPE = 1
SECTION_IMPORT = 2
SECTION_FUNCTION = 3
SECTION_TABLE = 4
SECTION_MEMORY = 5
SECTION_GLOBAL = 6
SECTION_EXPORT = 7
SECTION_START = 8
SECTION_ELEMENT = 9
SECTION_CODE = 10
SECTION_DATA = 11
SECTION_DATA_COUNT = 12

SECTION_NAMES = {
    0: "custom",
    1: "type",
    2: "import",
    3: "function",
    4: "table",
    5: "memory",
    6: "global",
    7: "export",
    8: "start",
    9: "element",
    10: "code",
    11: "data",
    12: "data_count",
}


class WasmFunction:
    """Represents a parsed WebAssembly function."""

    def __init__(
        self,
        type_index: int,
        locals: Optional[List[Tuple[ValType, int]]] = None,
        body: Optional[bytes] = None,
        instructions: Optional[List[Instruction]] = None,
        name: str = "",
    ):
        """Initialize a function.

        Args:
            type_index: Index into the type section for this function's signature.
            locals: List of (type, count) tuples for local variables.
            body: Raw bytecode body.
            instructions: Decoded instructions.
            name: Optional function name.
        """
        self.type_index = type_index
        self.locals = locals or []
        self.body = body or b""
        self.instructions = instructions or []
        self.name = name

    @property
    def local_count(self) -> int:
        """Get the total number of local variables."""
        return sum(count for _, count in self.locals)

    @property
    def body_size(self) -> int:
        """Get the size of the function body in bytes."""
        return len(self.body)

    def __repr__(self) -> str:
        return f"WasmFunction(type_idx={self.type_index}, locals={self.locals}, name='{self.name}')"


class DataSegment:
    """Represents a data segment for initializing memory."""

    def __init__(
        self,
        mode: int = 0,
        offset_expr: Optional[List[Instruction]] = None,
        offset_value: int = 0,
        data: bytes = b"",
        memory_index: int = 0,
    ):
        """Initialize a data segment.

        Args:
            mode: 0=active (passive=1, passive_explicit=2).
            offset_expr: The offset expression for active segments.
            offset_value: Pre-computed offset value.
            data: The raw data bytes.
            memory_index: The memory index for active segments.
        """
        self.mode = mode
        self.offset_expr = offset_expr or []
        self.offset_value = offset_value
        self.data = data
        self.memory_index = memory_index

    @property
    def is_active(self) -> bool:
        """Check if this is an active segment."""
        return self.mode == 0

    @property
    def is_passive(self) -> bool:
        """Check if this is a passive segment."""
        return self.mode == 1

    def __repr__(self) -> str:
        return f"DataSegment(mode={self.mode}, offset={self.offset_value}, size={len(self.data)})"


class ElementSegment:
    """Represents an element segment for initializing tables."""

    def __init__(
        self,
        table_index: int = 0,
        offset_expr: Optional[List[Instruction]] = None,
        offset_value: int = 0,
        elem_type: int = 0x70,
        items: Optional[List[Union[int, List[Instruction]]]] = None,
        mode: int = 0,
    ):
        """Initialize an element segment.

        Args:
            table_index: The table index.
            offset_expr: The offset expression.
            offset_value: Pre-computed offset value.
            elem_type: The element type (0x70 for funcref, 0x6F for externref).
            items: List of function indices or init expressions.
            mode: 0=active, 1=passive, 2=declarative.
        """
        self.table_index = table_index
        self.offset_expr = offset_expr or []
        self.offset_value = offset_value
        self.elem_type = elem_type
        self.items = items or []
        self.mode = mode

    @property
    def is_active(self) -> bool:
        """Check if this is an active segment."""
        return self.mode == 0

    @property
    def is_passive(self) -> bool:
        """Check if this is a passive segment."""
        return self.mode == 1

    @property
    def is_declarative(self) -> bool:
        """Check if this is a declarative segment."""
        return self.mode == 2

    def __repr__(self) -> str:
        return f"ElementSegment(table={self.table_index}, count={len(self.items)}, mode={self.mode})"


class WasmModule:
    """Represents a parsed WebAssembly module.

    This class holds all the parsed sections and their contents
    from a .wasm binary file.
    """

    def __init__(self):
        """Initialize an empty module."""
        self.magic: bytes = b""
        self.version: int = 0

        # Type section
        self.types: List[FuncType] = []

        # Import section
        self.imports: List[Import] = []

        # Function section (type indices for each function)
        self.function_type_indices: List[int] = []

        # Table section
        self.tables: List[TableType] = []

        # Memory section
        self.memories: List[MemoryType] = []

        # Global section
        self.globals: List[Tuple[GlobalType, List[Instruction], Any]] = []

        # Export section
        self.exports: List[Export] = []

        # Start section
        self.start_function: Optional[int] = None

        # Element section
        self.elements: List[ElementSegment] = []

        # Code section
        self.functions: List[WasmFunction] = []

        # Data section
        self.data_segments: List[DataSegment] = []

        # Data count section
        self.data_count: Optional[int] = None

        # Custom sections (name section, etc.)
        self.custom_sections: Dict[str, bytes] = {}

        # Parse errors
        self.errors: List[str] = []

        # Name section data
        self.function_names: Dict[int, str] = {}
        self.local_names: Dict[int, Dict[int, str]] = {}
        self.module_name: str = ""

    @property
    def function_count(self) -> int:
        """Get the number of functions."""
        return len(self.functions)

    @property
    def import_count(self) -> int:
        """Get the number of imports."""
        return len(self.imports)

    @property
    def export_count(self) -> int:
        """Get the number of exports."""
        return len(self.exports)

    @property
    def has_memory(self) -> bool:
        """Check if the module has a memory."""
        return len(self.memories) > 0

    @property
    def has_table(self) -> bool:
        """Check if the module has a table."""
        return len(self.tables) > 0

    def get_function_type(self, func_idx: int) -> Optional[FuncType]:
        """Get the function type for a function by index.

        Args:
            func_idx: The function index.

        Returns:
            The function type, or None if not found.
        """
        if func_idx < len(self.function_type_indices):
            type_idx = self.function_type_indices[func_idx]
            if type_idx < len(self.types):
                return self.types[type_idx]
        return None

    def get_export(self, name: str) -> Optional[Export]:
        """Get an export by name.

        Args:
            name: The export name.

        Returns:
            The Export object, or None if not found.
        """
        for export in self.exports:
            if export.name == name:
                return export
        return None

    def __repr__(self) -> str:
        return (
            f"WasmModule(version={self.version}, types={len(self.types)}, "
            f"functions={len(self.functions)}, imports={len(self.imports)}, "
            f"exports={len(self.exports)}, memories={len(self.memories)}, "
            f"tables={len(self.tables)})"
        )


class WasmParser:
    """Parser for WebAssembly binary format.

    Parses .wasm binary files into a structured WasmModule object,
    handling all section types and their contents.
    """

    # Magic number for WebAssembly binary modules
    WASM_MAGIC = b'\x00asm'
    WASM_VERSION = 1

    def __init__(self, enable_name_section: bool = True, validate: bool = True):
        """Initialize the parser.

        Args:
            enable_name_section: Whether to parse the name custom section.
            validate: Whether to perform basic validation during parsing.
        """
        self.enable_name_section = enable_name_section
        self.validate = validate
        self.decoder = InstructionDecoder()

    def parse(self, data: bytes) -> WasmModule:
        """Parse a WebAssembly binary module from bytes.

        Args:
            data: The raw .wasm binary data.

        Returns:
            A WasmModule object with all parsed sections.

        Raises:
            ValueError: If the binary format is invalid.
            WasmParseError: If a specific parse error occurs.
        """
        module = WasmModule()
        offset = 0

        # Parse header
        module.magic, offset = self._parse_magic(data, offset)
        module.version, offset = self._parse_version(data, offset)

        # Parse sections
        seen_sections: set = set()

        while offset < len(data):
            section_id, section_size, offset = self._parse_section_header(data, offset)

            if section_id == SECTION_CUSTOM:
                offset = self._parse_custom_section(data, offset, section_size, module)
            elif section_id == SECTION_TYPE:
                self._check_duplicate_section(seen_sections, SECTION_TYPE)
                offset = self._parse_type_section(data, offset, section_size, module)
            elif section_id == SECTION_IMPORT:
                self._check_duplicate_section(seen_sections, SECTION_IMPORT)
                offset = self._parse_import_section(data, offset, section_size, module)
            elif section_id == SECTION_FUNCTION:
                self._check_duplicate_section(seen_sections, SECTION_FUNCTION)
                offset = self._parse_function_section(data, offset, section_size, module)
            elif section_id == SECTION_TABLE:
                offset = self._parse_table_section(data, offset, section_size, module)
            elif section_id == SECTION_MEMORY:
                offset = self._parse_memory_section(data, offset, section_size, module)
            elif section_id == SECTION_GLOBAL:
                offset = self._parse_global_section(data, offset, section_size, module)
            elif section_id == SECTION_EXPORT:
                self._check_duplicate_section(seen_sections, SECTION_EXPORT)
                offset = self._parse_export_section(data, offset, section_size, module)
            elif section_id == SECTION_START:
                self._check_duplicate_section(seen_sections, SECTION_START)
                offset = self._parse_start_section(data, offset, section_size, module)
            elif section_id == SECTION_ELEMENT:
                offset = self._parse_element_section(data, offset, section_size, module)
            elif section_id == SECTION_CODE:
                self._check_duplicate_section(seen_sections, SECTION_CODE)
                offset = self._parse_code_section(data, offset, section_size, module)
            elif section_id == SECTION_DATA:
                offset = self._parse_data_section(data, offset, section_size, module)
            elif section_id == SECTION_DATA_COUNT:
                offset = self._parse_data_count_section(data, offset, section_size, module)
            else:
                # Unknown section, skip it
                offset += section_size

            seen_sections.add(section_id)

        # Apply name section data
        if self.enable_name_section and module.function_names:
            for func in module.functions:
                idx = module.functions.index(func)
                if idx in module.function_names:
                    func.name = module.function_names[idx]

        # Basic validation
        if self.validate:
            self._validate_module(module)

        return module

    def _parse_magic(self, data: bytes, offset: int) -> Tuple[bytes, int]:
        """Parse the magic number.

        Args:
            data: The binary data.
            offset: Current offset.

        Returns:
            Tuple of (magic_bytes, next_offset).

        Raises:
            ValueError: If the magic number is invalid.
        """
        if offset + 4 > len(data):
            raise ValueError("File too short: missing magic number")
        magic = data[offset:offset + 4]
        if magic != self.WASM_MAGIC:
            raise ValueError(
                f"Invalid magic number: expected {self.WASM_MAGIC!r}, got {magic!r}"
            )
        return magic, offset + 4

    def _parse_version(self, data: bytes, offset: int) -> Tuple[int, int]:
        """Parse the version number.

        Args:
            data: The binary data.
            offset: Current offset.

        Returns:
            Tuple of (version, next_offset).

        Raises:
            ValueError: If the version is not supported.
        """
        if offset + 4 > len(data):
            raise ValueError("File too short: missing version")
        version = int.from_bytes(data[offset:offset + 4], 'little')
        if version != self.WASM_VERSION:
            raise ValueError(
                f"Unsupported WASM version: {version}, expected {self.WASM_VERSION}"
            )
        return version, offset + 4

    def _parse_section_header(self, data: bytes, offset: int) -> Tuple[int, int, int]:
        """Parse a section header.

        Args:
            data: The binary data.
            offset: Current offset.

        Returns:
            Tuple of (section_id, section_size, next_offset).
        """
        section_id = data[offset]
        offset += 1
        section_size, offset = decode_unsigned_leb128(data, offset)
        return section_id, section_size, offset

    def _check_duplicate_section(self, seen: set, section_id: int) -> None:
        """Check for duplicate sections.

        Args:
            seen: Set of already seen section IDs.
            section_id: The section ID to check.

        Raises:
            ValueError: If the section is a duplicate.
        """
        if section_id in seen and section_id != SECTION_CUSTOM:
            raise ValueError(
                f"Duplicate section: {SECTION_NAMES.get(section_id, section_id)}"
            )

    def _parse_type_section(self, data: bytes, offset: int, size: int,
                            module: WasmModule) -> int:
        """Parse the type section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            if offset >= end_offset:
                raise ValueError("Unexpected end of type section")

            # Type constructor byte (0x60 = functype)
            type_byte = data[offset]
            offset += 1
            if type_byte != 0x60:
                raise ValueError(f"Expected functype (0x60), got 0x{type_byte:02X}")

            # Parameter types
            param_count, offset = decode_unsigned_leb128(data, offset)
            params = []
            for _ in range(param_count):
                if offset >= end_offset:
                    raise ValueError("Unexpected end of type section params")
                valtype = valtype_from_byte(data[offset])
                offset += 1
                params.append(valtype)

            # Result types
            result_count, offset = decode_unsigned_leb128(data, offset)
            results = []
            for _ in range(result_count):
                if offset >= end_offset:
                    raise ValueError("Unexpected end of type section results")
                valtype = valtype_from_byte(data[offset])
                offset += 1
                results.append(valtype)

            module.types.append(FuncType(params, results))

        return offset

    def _parse_import_section(self, data: bytes, offset: int, size: int,
                               module: WasmModule) -> int:
        """Parse the import section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            # Module name
            module_str, offset = self._parse_name(data, offset)

            # Field name
            field_str, offset = self._parse_name(data, offset)

            # Import type
            import_type_byte = data[offset]
            offset += 1

            try:
                import_type = ImportType(import_type_byte)
            except ValueError:
                raise ValueError(f"Invalid import type: 0x{import_type_byte:02X}")

            if import_type == ImportType.FUNCTION:
                type_idx, offset = decode_unsigned_leb128(data, offset)
                module.imports.append(Import(
                    module=module_str,
                    field=field_str,
                    import_type=import_type,
                    type_index=type_idx,
                ))
            elif import_type == ImportType.TABLE:
                elem_type, offset = self._parse_elem_type(data, offset)
                limits, offset = self._parse_limits(data, offset)
                table_type = TableType(
                    elem_type=ElemType(elem_type),
                    min_size=limits.min_val,
                    max_size=limits.max_val,
                )
                module.imports.append(Import(
                    module=module_str,
                    field=field_str,
                    import_type=import_type,
                    table_type=table_type,
                ))
            elif import_type == ImportType.MEMORY:
                limits, offset = self._parse_limits(data, offset)
                memory_type = MemoryType(
                    min_size=limits.min_val,
                    max_size=limits.max_val,
                )
                module.imports.append(Import(
                    module=module_str,
                    field=field_str,
                    import_type=import_type,
                    memory_type=memory_type,
                ))
            elif import_type == ImportType.GLOBAL:
                val_type = valtype_from_byte(data[offset])
                offset += 1
                mut_byte = data[offset]
                offset += 1
                mutability = Mutability(mut_byte)
                global_type = GlobalType(val_type, mutability)
                module.imports.append(Import(
                    module=module_str,
                    field=field_str,
                    import_type=import_type,
                    global_type=global_type,
                ))

        return offset

    def _parse_function_section(self, data: bytes, offset: int, size: int,
                                 module: WasmModule) -> int:
        """Parse the function section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            type_idx, offset = decode_unsigned_leb128(data, offset)
            module.function_type_indices.append(type_idx)

        return offset

    def _parse_table_section(self, data: bytes, offset: int, size: int,
                              module: WasmModule) -> int:
        """Parse the table section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            elem_type, offset = self._parse_elem_type(data, offset)
            limits, offset = self._parse_limits(data, offset)
            module.tables.append(TableType(
                elem_type=ElemType(elem_type),
                min_size=limits.min_val,
                max_size=limits.max_val,
            ))

        return offset

    def _parse_memory_section(self, data: bytes, offset: int, size: int,
                               module: WasmModule) -> int:
        """Parse the memory section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            limits, offset = self._parse_limits(data, offset)
            module.memories.append(MemoryType(
                min_size=limits.min_val,
                max_size=limits.max_val,
            ))

        return offset

    def _parse_global_section(self, data: bytes, offset: int, size: int,
                               module: WasmModule) -> int:
        """Parse the global section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            val_type = valtype_from_byte(data[offset])
            offset += 1
            mut_byte = data[offset]
            offset += 1
            mutability = Mutability(mut_byte)
            global_type = GlobalType(val_type, mutability)

            # Init expression
            init_expr, offset = self._parse_init_expr(data, offset)

            # Evaluate the init expression to get the initial value
            init_value = self._eval_init_expr(init_expr, val_type)

            module.globals.append((global_type, init_expr, init_value))

        return offset

    def _parse_export_section(self, data: bytes, offset: int, size: int,
                               module: WasmModule) -> int:
        """Parse the export section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            name, offset = self._parse_name(data, offset)
            export_type_byte = data[offset]
            offset += 1
            try:
                export_type = ExportType(export_type_byte)
            except ValueError:
                raise ValueError(f"Invalid export type: 0x{export_type_byte:02X}")
            index, offset = decode_unsigned_leb128(data, offset)
            module.exports.append(Export(name, export_type, index))

        return offset

    def _parse_start_section(self, data: bytes, offset: int, size: int,
                              module: WasmModule) -> int:
        """Parse the start section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        if size > 0:
            func_idx, offset = decode_unsigned_leb128(data, offset)
            module.start_function = func_idx
        return offset

    def _parse_element_section(self, data: bytes, offset: int, size: int,
                                module: WasmModule) -> int:
        """Parse the element section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            flags = data[offset]
            offset += 1

            # Determine element segment mode from flags
            mode = 0  # active
            table_idx = 0
            elem_type = 0x70

            if flags == 0x00:
                # Active, table 0, funcref, elemkind=0x00 for indices
                mode = 0
                table_idx = 0
                elem_type = 0x70
            elif flags == 0x01:
                # Passive, funcref, elemkind=0x00
                mode = 1
                elem_type = 0x70
            elif flags == 0x02:
                # Active, table 0, elemkind byte follows
                mode = 0
                table_idx = 0
                elem_type = data[offset]
                offset += 1
            elif flags == 0x03:
                # Passive, elemkind byte follows
                mode = 1
                elem_type = data[offset]
                offset += 1
            elif flags == 0x04:
                # Active, table index, funcref
                mode = 0
                table_idx, offset = decode_unsigned_leb128(data, offset)
                elem_type = 0x70
            elif flags == 0x05:
                # Passive, funcref
                mode = 1
                elem_type = 0x70
            elif flags == 0x06:
                # Active, table index, elemkind byte
                mode = 0
                table_idx, offset = decode_unsigned_leb128(data, offset)
                elem_type = data[offset]
                offset += 1
            elif flags == 0x07:
                # Declarative, elemkind byte
                mode = 2
                elem_type = data[offset]
                offset += 1
            else:
                raise ValueError(f"Invalid element segment flags: 0x{flags:02X}")

            # Parse offset expression for active segments
            offset_expr = []
            offset_value = 0
            if mode == 0:
                offset_expr, offset = self._parse_init_expr(data, offset)
                offset_value = self._eval_init_expr(offset_expr, ValType.I32)

            # Parse element items
            item_count, offset = decode_unsigned_leb128(data, offset)
            items = []

            if flags in (0x00, 0x02, 0x04, 0x06):
                # Indices mode
                for _ in range(item_count):
                    func_idx, offset = decode_unsigned_leb128(data, offset)
                    items.append(func_idx)
            else:
                # Expressions mode
                for _ in range(item_count):
                    expr, offset = self._parse_init_expr(data, offset)
                    items.append(expr)

            module.elements.append(ElementSegment(
                table_index=table_idx,
                offset_expr=offset_expr,
                offset_value=offset_value,
                elem_type=elem_type,
                items=items,
                mode=mode,
            ))

        return offset

    def _parse_code_section(self, data: bytes, offset: int, size: int,
                             module: WasmModule) -> int:
        """Parse the code section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        if count != len(module.function_type_indices):
            raise ValueError(
                f"Code section count ({count}) does not match function "
                f"section count ({len(module.function_type_indices)})"
            )

        for i in range(count):
            # Parse function body
            body_size, offset = decode_unsigned_leb128(data, offset)
            body_end = offset + body_size

            # Parse locals
            local_count, offset = decode_unsigned_leb128(data, offset)
            locals_list = []
            for _ in range(local_count):
                count_locals, offset = decode_unsigned_leb128(data, offset)
                val_type = valtype_from_byte(data[offset])
                offset += 1
                locals_list.append((val_type, count_locals))

            # Parse function body bytecode
            body_bytes = data[offset:body_end]
            offset = body_end

            # Decode instructions
            try:
                instrs = self.decoder.decode_function(body_bytes)
            except Exception as e:
                instrs = []
                module.errors.append(f"Failed to decode function {i}: {e}")

            func = WasmFunction(
                type_index=module.function_type_indices[i],
                locals=locals_list,
                body=body_bytes,
                instructions=instrs,
            )
            module.functions.append(func)

        return offset

    def _parse_data_section(self, data: bytes, offset: int, size: int,
                             module: WasmModule) -> int:
        """Parse the data section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size
        count, offset = decode_unsigned_leb128(data, offset)

        for _ in range(count):
            flags = data[offset]
            offset += 1

            mode = 0  # active
            memory_idx = 0
            offset_expr = []
            offset_value = 0

            if flags == 0x00:
                # Active, memory 0
                mode = 0
                memory_idx = 0
                offset_expr, offset = self._parse_init_expr(data, offset)
                offset_value = self._eval_init_expr(offset_expr, ValType.I32)
            elif flags == 0x01:
                # Passive
                mode = 1
            elif flags == 0x02:
                # Active with explicit memory index
                mode = 0
                memory_idx, offset = decode_unsigned_leb128(data, offset)
                offset_expr, offset = self._parse_init_expr(data, offset)
                offset_value = self._eval_init_expr(offset_expr, ValType.I32)
            else:
                raise ValueError(f"Invalid data segment flags: 0x{flags:02X}")

            # Data bytes
            data_size, offset = decode_unsigned_leb128(data, offset)
            segment_data = data[offset:offset + data_size]
            offset += data_size

            module.data_segments.append(DataSegment(
                mode=mode,
                offset_expr=offset_expr,
                offset_value=offset_value,
                data=segment_data,
                memory_index=memory_idx,
            ))

        return offset

    def _parse_data_count_section(self, data: bytes, offset: int, size: int,
                                   module: WasmModule) -> int:
        """Parse the data count section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        count, offset = decode_unsigned_leb128(data, offset)
        module.data_count = count
        return offset

    def _parse_custom_section(self, data: bytes, offset: int, size: int,
                               module: WasmModule) -> int:
        """Parse a custom section.

        Args:
            data: The binary data.
            offset: Current offset.
            size: Section size.
            module: The module being built.

        Returns:
            Next offset after the section.
        """
        end_offset = offset + size

        # Parse section name
        name, offset = self._parse_name(data, offset)

        # Store raw data
        content = data[offset:end_offset]
        module.custom_sections[name] = content

        # Parse name section if applicable
        if name == "name" and self.enable_name_section:
            self._parse_name_section(content, module)

        # Jump to end of section
        return end_offset

    def _parse_name_section(self, data: bytes, module: WasmModule) -> None:
        """Parse the name custom section.

        Args:
            data: The name section data.
            module: The module being built.
        """
        offset = 0
        try:
            while offset < len(data):
                subsection_id = data[offset]
                offset += 1
                subsection_size, offset = decode_unsigned_leb128(data, offset)
                subsection_end = offset + subsection_size

                if subsection_id == 0:
                    # Module name
                    module.module_name, offset = self._parse_name(data, offset)
                elif subsection_id == 1:
                    # Function names
                    count, offset = decode_unsigned_leb128(data, offset)
                    for _ in range(count):
                        idx, offset = decode_unsigned_leb128(data, offset)
                        name, offset = self._parse_name(data, offset)
                        module.function_names[idx] = name
                elif subsection_id == 2:
                    # Local names
                    func_count, offset = decode_unsigned_leb128(data, offset)
                    for _ in range(func_count):
                        func_idx, offset = decode_unsigned_leb128(data, offset)
                        local_count, offset = decode_unsigned_leb128(data, offset)
                        local_names = {}
                        for _ in range(local_count):
                            local_idx, offset = decode_unsigned_leb128(data, offset)
                            local_name, offset = self._parse_name(data, offset)
                            local_names[local_idx] = local_name
                        module.local_names[func_idx] = local_names
                else:
                    # Unknown subsection, skip
                    pass

                offset = subsection_end
        except (ValueError, IndexError):
            # Name section is best-effort, ignore parse errors
            pass

    def _parse_name(self, data: bytes, offset: int) -> Tuple[str, int]:
        """Parse a UTF-8 string (name) from the binary format.

        Args:
            data: The binary data.
            offset: Current offset.

        Returns:
            Tuple of (string_value, next_offset).
        """
        length, offset = decode_unsigned_leb128(data, offset)
        if offset + length > len(data):
            raise ValueError(f"Name of length {length} exceeds data bounds")
        name = data[offset:offset + length].decode('utf-8', errors='replace')
        return name, offset + length

    def _parse_limits(self, data: bytes, offset: int) -> Tuple[Limits, int]:
        """Parse limits (min, max) from the binary format.

        Args:
            data: The binary data.
            offset: Current offset.

        Returns:
            Tuple of (Limits, next_offset).
        """
        flags = data[offset]
        offset += 1
        min_val, offset = decode_unsigned_leb128(data, offset)
        max_val = None
        if flags & 0x01:
            max_val, offset = decode_unsigned_leb128(data, offset)
        return Limits(min_val, max_val), offset

    def _parse_elem_type(self, data: bytes, offset: int) -> Tuple[int, int]:
        """Parse an element type byte.

        Args:
            data: The binary data.
            offset: Current offset.

        Returns:
            Tuple of (elem_type, next_offset).
        """
        elem_type = data[offset]
        offset += 1
        if elem_type not in (0x70, 0x6F):
            raise ValueError(f"Invalid element type: 0x{elem_type:02X}")
        return elem_type, offset

    def _parse_init_expr(self, data: bytes, offset: int) -> Tuple[List[Instruction], int]:
        """Parse an initializer expression.

        An init expression is a sequence of instructions terminated by END.

        Args:
            data: The binary data.
            offset: Current offset.

        Returns:
            Tuple of (instructions_list, next_offset).
        """
        instructions = []
        while offset < len(data):
            instr = self.decoder.decode(data, offset)
            instructions.append(instr)
            offset += instr.size
            if instr.opcode == Opcode.END:
                break
        return instructions, offset

    def _eval_init_expr(self, instructions: List[Instruction], expected_type: ValType) -> Any:
        """Evaluate a constant initializer expression.

        This evaluates simple constant expressions (like i32.const, global.get,
        etc.) that are used in data/element segments and global definitions.

        Args:
            instructions: The instructions forming the expression.
            expected_type: The expected result type.

        Returns:
            The evaluated constant value.

        Raises:
            ValueError: If the expression cannot be evaluated as a constant.
        """
        if len(instructions) < 2:  # At least one value instruction + END
            raise ValueError("Invalid init expression: too short")

        # The last instruction should be END
        if instructions[-1].opcode != Opcode.END:
            raise ValueError("Init expression must end with END")

        # Currently we only support simple constant instructions
        init_instr = instructions[0]
        if init_instr.opcode == Opcode.I32_CONST and len(init_instr.immediates) > 0:
            return init_instr.immediates[0]
        elif init_instr.opcode == Opcode.I64_CONST and len(init_instr.immediates) > 0:
            return init_instr.immediates[0]
        elif init_instr.opcode == Opcode.F32_CONST and len(init_instr.immediates) > 0:
            return init_instr.immediates[0]
        elif init_instr.opcode == Opcode.F64_CONST and len(init_instr.immediates) > 0:
            return init_instr.immediates[0]
        elif init_instr.opcode == Opcode.GLOBAL_GET and len(init_instr.immediates) > 0:
            # Global.get in init expressions - will be resolved at instantiation
            return init_instr.immediates[0]
        elif init_instr.opcode == Opcode.REF_NULL:
            return None
        elif init_instr.opcode == Opcode.REF_FUNC and len(init_instr.immediates) > 0:
            return init_instr.immediates[0]
        else:
            raise ValueError(
                f"Cannot evaluate init expression: {init_instr}"
            )

    def _validate_module(self, module: WasmModule) -> None:
        """Perform basic validation on the parsed module.

        Args:
            module: The module to validate.

        Raises:
            ValueError: If validation fails.
        """
        # Validate type indices in function section
        for i, type_idx in enumerate(module.function_type_indices):
            if type_idx >= len(module.types):
                raise ValueError(
                    f"Function {i} references type index {type_idx} "
                    f"but only {len(module.types)} types defined"
                )

        # Validate function count matches
        if len(module.functions) != len(module.function_type_indices):
            raise ValueError(
                f"Function count mismatch: {len(module.functions)} bodies "
                f"vs {len(module.function_type_indices)} declarations"
            )

        # Validate export indices
        for export in module.exports:
            if export.export_type == ExportType.FUNCTION:
                total_funcs = len(module.functions) + sum(
                    1 for imp in module.imports if imp.import_type == ImportType.FUNCTION
                )
                if export.index >= total_funcs:
                    raise ValueError(
                        f"Export '{export.name}' references function index "
                        f"{export.index} but only {total_funcs} functions available"
                    )

        # Validate start function
        if module.start_function is not None:
            total_funcs = len(module.functions) + sum(
                1 for imp in module.imports if imp.import_type == ImportType.FUNCTION
            )
            if module.start_function >= total_funcs:
                raise ValueError(
                    f"Start function index {module.start_function} out of range"
                )

        # Validate data count
        if module.data_count is not None:
            if module.data_count != len(module.data_segments):
                module.errors.append(
                    f"Data count section says {module.data_count} segments "
                    f"but {len(module.data_segments)} found"
                )


class WasmParseError(Exception):
    """Exception raised for WebAssembly parsing errors."""

    def __init__(self, message: str, offset: int = 0):
        """Initialize the error.

        Args:
            message: Error description.
            offset: Byte offset where the error occurred.
        """
        super().__init__(message)
        self.offset = offset


def parse_wasm(data: bytes, validate: bool = True) -> WasmModule:
    """Parse a WebAssembly binary module (convenience function).

    Args:
        data: The raw .wasm binary data.
        validate: Whether to perform basic validation.

    Returns:
        A parsed WasmModule.

    Raises:
        ValueError: If the binary format is invalid.
    """
    parser = WasmParser(validate=validate)
    return parser.parse(data)


def parse_wasm_file(filepath: str, validate: bool = True) -> WasmModule:
    """Parse a WebAssembly binary module from a file.

    Args:
        filepath: Path to the .wasm file.
        validate: Whether to perform basic validation.

    Returns:
        A parsed WasmModule.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the binary format is invalid.
    """
    with open(filepath, 'rb') as f:
        data = f.read()
    return parse_wasm(data, validate=validate)