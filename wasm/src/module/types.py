"""WebAssembly type system.

This module defines the type system for WebAssembly, including value types,
function types, and all type-related utilities used throughout the runtime.
"""

from enum import IntEnum, auto
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


class ValType(IntEnum):
    """WebAssembly value types."""
    I32 = 0x7F
    I64 = 0x7E
    F32 = 0x7D
    F64 = 0x7C
    V128 = 0x7B
    FUNCREF = 0x70
    EXTERNREF = 0x6F

    def __str__(self) -> str:
        return self.name.lower()

    @property
    def size(self) -> int:
        """Get the size of the value type in bytes."""
        if self == ValType.I32:
            return 4
        elif self == ValType.I64:
            return 8
        elif self == ValType.F32:
            return 4
        elif self == ValType.F64:
            return 8
        elif self == ValType.V128:
            return 16
        elif self == ValType.FUNCREF:
            return 4  # Index
        elif self == ValType.EXTERNREF:
            return 4  # Index
        return 0

    @property
    def is_integer(self) -> bool:
        """Check if the type is an integer type."""
        return self in (ValType.I32, ValType.I64)

    @property
    def is_float(self) -> bool:
        """Check if the type is a floating-point type."""
        return self in (ValType.F32, ValType.F64)

    @property
    def is_reference(self) -> bool:
        """Check if the type is a reference type."""
        return self in (ValType.FUNCREF, ValType.EXTERNREF)

    @property
    def is_vector(self) -> bool:
        """Check if the type is a vector type."""
        return self == ValType.V128

    @property
    def is_numeric(self) -> bool:
        """Check if the type is a numeric type."""
        return self.is_integer or self.is_float

    def default_value(self) -> Any:
        """Get the default value for this type."""
        if self == ValType.I32:
            return 0
        elif self == ValType.I64:
            return 0
        elif self == ValType.F32:
            return 0.0
        elif self == ValType.F64:
            return 0.0
        elif self == ValType.V128:
            return 0
        elif self == ValType.FUNCREF:
            return None
        elif self == ValType.EXTERNREF:
            return None
        return 0


class FuncType:
    """WebAssembly function type describing function signatures.

    A function type consists of a sequence of parameter types and a sequence
    of result types.
    """

    def __init__(self, params: List[ValType], results: List[ValType]):
        """Initialize a function type.

        Args:
            params: The parameter types.
            results: The result types.
        """
        self.params = params
        self.results = results

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FuncType):
            return NotImplemented
        return self.params == other.params and self.results == other.results

    def __hash__(self) -> int:
        return hash((tuple(self.params), tuple(self.results)))

    def __repr__(self) -> str:
        params_str = ", ".join(str(p) for p in self.params)
        results_str = ", ".join(str(r) for r in self.results)
        return f"FuncType({params_str}) -> ({results_str})"

    def __str__(self) -> str:
        params_str = " ".join(str(p) for p in self.params)
        results_str = " ".join(str(r) for r in self.results)
        return f"(func (param {params_str}) (result {results_str}))"

    @property
    def param_count(self) -> int:
        """Get the number of parameters."""
        return len(self.params)

    @property
    def result_count(self) -> int:
        """Get the number of results."""
        return len(self.results)


class BlockType:
    """Type annotation for a block in WebAssembly control flow.

    Block types can be:
    - Empty (no parameters, no results)
    - A single value type (one result)
    - A function type index (multi-value return)
    """

    def __init__(
        self,
        params: Optional[List[ValType]] = None,
        results: Optional[List[ValType]] = None,
        type_idx: Optional[int] = None,
    ):
        """Initialize a block type.

        Args:
            params: Parameter types for the block.
            results: Result types for the block.
            type_idx: Index into the type section for multi-value.
        """
        self.params = params or []
        self.results = results or []
        self.type_idx = type_idx

    @classmethod
    def empty(cls) -> "BlockType":
        """Create an empty block type (no params, no results)."""
        return cls()

    @classmethod
    def from_valtype(cls, valtype: ValType) -> "BlockType":
        """Create a block type from a single value type.

        Args:
            valtype: The single value type.

        Returns:
            A BlockType with one result.
        """
        return cls(results=[valtype])

    @classmethod
    def from_functype(cls, functype: FuncType) -> "BlockType":
        """Create a block type from a function type.

        Args:
            functype: The function type.

        Returns:
            A BlockType with params and results from the function type.
        """
        return cls(params=functype.params, results=functype.results)

    def __repr__(self) -> str:
        params_str = ", ".join(str(p) for p in self.params) if self.params else "empty"
        results_str = ", ".join(str(r) for r in self.results) if self.results else "empty"
        return f"BlockType(params=[{params_str}], results=[{results_str}])"


class Mutability(IntEnum):
    """Mutability type for globals."""
    IMMUTABLE = 0
    MUTABLE = 1

    def __str__(self) -> str:
        return "mutable" if self == Mutability.MUTABLE else "immutable"


class ImportType(IntEnum):
    """Types of imports in WebAssembly."""
    FUNCTION = 0
    TABLE = 1
    MEMORY = 2
    GLOBAL = 3

    def __str__(self) -> str:
        return self.name.lower()


class ExportType(IntEnum):
    """Types of exports in WebAssembly."""
    FUNCTION = 0
    TABLE = 1
    MEMORY = 2
    GLOBAL = 3

    def __str__(self) -> str:
        return self.name.lower()


class ElemType(IntEnum):
    """Element types for tables."""
    FUNCREF = 0x70
    EXTERNREF = 0x6F

    def __str__(self) -> str:
        return self.name.lower()


class RefType:
    """Reference type for WebAssembly reference types proposal."""

    def __init__(self, elem_type: ElemType, nullable: bool = True):
        """Initialize a reference type.

        Args:
            elem_type: The element type.
            nullable: Whether the reference can be null.
        """
        self.elem_type = elem_type
        self.nullable = nullable

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RefType):
            return NotImplemented
        return self.elem_type == other.elem_type and self.nullable == other.nullable

    def __repr__(self) -> str:
        null_str = "nullable " if self.nullable else ""
        return f"{null_str}{self.elem_type}"

    def __str__(self) -> str:
        if self.nullable:
            return f"(ref null {self.elem_type.name.lower()})"
        return f"(ref {self.elem_type.name.lower()})"


class GlobalType:
    """Type descriptor for a WebAssembly global variable."""

    def __init__(self, val_type: ValType, mutability: Mutability):
        """Initialize a global type.

        Args:
            val_type: The value type of the global.
            mutability: Whether the global is mutable.
        """
        self.val_type = val_type
        self.mutability = mutability

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GlobalType):
            return NotImplemented
        return self.val_type == other.val_type and self.mutability == other.mutability

    def __repr__(self) -> str:
        return f"GlobalType({self.val_type}, {self.mutability})"


class TableType:
    """Type descriptor for a WebAssembly table."""

    def __init__(self, elem_type: ElemType, min_size: int, max_size: Optional[int] = None):
        """Initialize a table type.

        Args:
            elem_type: The element type of the table.
            min_size: The minimum table size (initial size).
            max_size: The maximum table size, or None for unbounded.
        """
        self.elem_type = elem_type
        self.min_size = min_size
        self.max_size = max_size

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TableType):
            return NotImplemented
        return (self.elem_type == other.elem_type and
                self.min_size == other.min_size and
                self.max_size == other.max_size)

    def __repr__(self) -> str:
        return f"TableType({self.elem_type}, {self.min_size}, {self.max_size})"


class MemoryType:
    """Type descriptor for a WebAssembly linear memory."""

    def __init__(self, min_size: int, max_size: Optional[int] = None, is_shared: bool = False):
        """Initialize a memory type.

        Args:
            min_size: Minimum memory size in pages (64KB each).
            max_size: Maximum memory size in pages, or None for unbounded.
            is_shared: Whether the memory is shared (for threads proposal).
        """
        self.min_size = min_size
        self.max_size = max_size
        self.is_shared = is_shared

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MemoryType):
            return NotImplemented
        return (self.min_size == other.min_size and
                self.max_size == other.max_size and
                self.is_shared == other.is_shared)

    def __repr__(self) -> str:
        shared = "shared " if self.is_shared else ""
        return f"MemoryType({shared}{self.min_size}, {self.max_size})"


class Limits:
    """WebAssembly limits (min/max) for tables and memories."""

    def __init__(self, min_val: int, max_val: Optional[int] = None):
        """Initialize limits.

        Args:
            min_val: The minimum value.
            max_val: The maximum value, or None for unbounded.
        """
        self.min_val = min_val
        self.max_val = max_val

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Limits):
            return NotImplemented
        return self.min_val == other.min_val and self.max_val == other.max_val

    def __repr__(self) -> str:
        if self.max_val is not None:
            return f"Limits({self.min_val}, {self.max_val})"
        return f"Limits({self.min_val})"


class Import:
    """Descriptor for a WebAssembly import."""

    def __init__(
        self,
        module: str,
        field: str,
        import_type: ImportType,
        type_index: Optional[int] = None,
        table_type: Optional[TableType] = None,
        memory_type: Optional[MemoryType] = None,
        global_type: Optional[GlobalType] = None,
    ):
        """Initialize an import descriptor.

        Args:
            module: The module name.
            field: The field name.
            import_type: The type of import.
            type_index: Function type index (for function imports).
            table_type: Table type (for table imports).
            memory_type: Memory type (for memory imports).
            global_type: Global type (for global imports).
        """
        self.module = module
        self.field = field
        self.import_type = import_type
        self.type_index = type_index
        self.table_type = table_type
        self.memory_type = memory_type
        self.global_type = global_type

    def __repr__(self) -> str:
        return f"Import({self.module}.{self.field}, {self.import_type})"


class Export:
    """Descriptor for a WebAssembly export."""

    def __init__(self, name: str, export_type: ExportType, index: int):
        """Initialize an export descriptor.

        Args:
            name: The export name.
            export_type: The type of export.
            index: The index of the exported item.
        """
        self.name = name
        self.export_type = export_type
        self.index = index

    def __repr__(self) -> str:
        return f"Export({self.name}, {self.export_type}, idx={self.index})"


class Value:
    """A typed WebAssembly value.

    This class wraps a raw value with its type information for use
    in the runtime.
    """

    def __init__(self, value: Any, val_type: ValType):
        """Initialize a typed value.

        Args:
            value: The raw value.
            val_type: The WebAssembly value type.
        """
        self.value = value
        self.type = val_type

    def __repr__(self) -> str:
        return f"Value({self.value}, {self.type})"

    @classmethod
    def i32(cls, value: int) -> "Value":
        """Create an i32 value.

        Args:
            value: The 32-bit integer value.

        Returns:
            A Value with type I32.
        """
        return cls(value & 0xFFFFFFFF, ValType.I32)

    @classmethod
    def i64(cls, value: int) -> "Value":
        """Create an i64 value.

        Args:
            value: The 64-bit integer value.

        Returns:
            A Value with type I64.
        """
        return cls(value & 0xFFFFFFFFFFFFFFFF, ValType.I64)

    @classmethod
    def f32(cls, value: float) -> "Value":
        """Create an f32 value.

        Args:
            value: The 32-bit float value.

        Returns:
            A Value with type F32.
        """
        import struct
        # Ensure proper f32 representation
        value = struct.unpack('f', struct.pack('f', value))[0]
        return cls(value, ValType.F32)

    @classmethod
    def f64(cls, value: float) -> "Value":
        """Create an f64 value.

        Args:
            value: The 64-bit float value.

        Returns:
            A Value with type F64.
        """
        return cls(value, ValType.F64)

    @classmethod
    def funcref(cls, func_idx: Optional[int]) -> "Value":
        """Create a funcref value.

        Args:
            func_idx: The function index, or None for null.

        Returns:
            A Value with type FUNCREF.
        """
        return cls(func_idx, ValType.FUNCREF)

    @classmethod
    def externref(cls, ref: Any) -> "Value":
        """Create an externref value.

        Args:
            ref: The external reference.

        Returns:
            A Value with type EXTERNREF.
        """
        return cls(ref, ValType.EXTERNREF)

    def to_i32(self) -> int:
        """Convert to i32, masking to 32 bits."""
        return int(self.value) & 0xFFFFFFFF

    def to_i64(self) -> int:
        """Convert to i64, masking to 64 bits."""
        return int(self.value) & 0xFFFFFFFFFFFFFFFF

    def to_f32(self) -> float:
        """Convert to f32, ensuring proper float32 representation."""
        import struct
        return struct.unpack('f', struct.pack('f', float(self.value)))[0]

    def to_f64(self) -> float:
        """Convert to f64."""
        return float(self.value)


class ValueStack:
    """A stack of WebAssembly values used during execution.

    This is a low-level stack that stores raw values and their types
    for efficient interpretation.
    """

    def __init__(self, max_height: int = 1000000):
        """Initialize the value stack.

        Args:
            max_height: Maximum stack height.
        """
        self.max_height = max_height
        self.values: List[Any] = []
        self.types: List[ValType] = []

    def push(self, value: Any, val_type: ValType) -> None:
        """Push a value onto the stack.

        Args:
            value: The raw value to push.
            val_type: The type of the value.

        Raises:
            RuntimeError: If the stack exceeds the maximum height.
        """
        if len(self.values) >= self.max_height:
            raise RuntimeError("Value stack overflow")
        self.values.append(value)
        self.types.append(val_type)

    def pop(self) -> Any:
        """Pop a value from the stack.

        Returns:
            The popped value.

        Raises:
            IndexError: If the stack is empty.
        """
        if not self.values:
            raise IndexError("Value stack underflow")
        self.types.pop()
        return self.values.pop()

    def pop_typed(self) -> Value:
        """Pop a typed value from the stack.

        Returns:
            A Value object with the popped value and type.
        """
        if not self.values:
            raise IndexError("Value stack underflow")
        val_type = self.types.pop()
        value = self.values.pop()
        return Value(value, val_type)

    def peek(self, depth: int = 0) -> Any:
        """Peek at a value without popping it.

        Args:
            depth: How far from the top to peek (0 = top).

        Returns:
            The value at the given depth.
        """
        if depth >= len(self.values):
            raise IndexError(f"Cannot peek at depth {depth}")
        return self.values[-(depth + 1)]

    def peek_type(self, depth: int = 0) -> ValType:
        """Peek at the type of a value without popping it.

        Args:
            depth: How far from the top to peek (0 = top).

        Returns:
            The type at the given depth.
        """
        if depth >= len(self.types):
            raise IndexError(f"Cannot peek at depth {depth}")
        return self.types[-(depth + 1)]

    def pop_many(self, count: int) -> List[Any]:
        """Pop multiple values from the stack.

        Args:
            count: Number of values to pop.

        Returns:
            List of popped values in order (first popped = deepest).
        """
        if count > len(self.values):
            raise IndexError(f"Cannot pop {count} values, only {len(self.values)} available")
        result = []
        for _ in range(count):
            result.append(self.values.pop())
            self.types.pop()
        result.reverse()
        return result

    def push_many(self, values: List[Any], types: List[ValType]) -> None:
        """Push multiple values onto the stack.

        Args:
            values: The values to push.
            types: The types of the values.
        """
        if len(values) != len(types):
            raise ValueError("Values and types must have the same length")
        for v, t in zip(values, types):
            self.push(v, t)

    def clear(self) -> None:
        """Clear the stack."""
        self.values.clear()
        self.types.clear()

    @property
    def depth(self) -> int:
        """Get the current stack depth."""
        return len(self.values)

    @property
    def is_empty(self) -> bool:
        """Check if the stack is empty."""
        return len(self.values) == 0

    def __len__(self) -> int:
        return len(self.values)

    def __repr__(self) -> str:
        items = []
        for v, t in zip(self.values, self.types):
            items.append(f"{t.name}({v})")
        return f"ValueStack([{', '.join(items)}])"


# Type-related utility functions

def valtype_from_byte(byte_val: int) -> ValType:
    """Convert a byte value to a ValType.

    Args:
        byte_val: The byte value from the binary format.

    Returns:
        The corresponding ValType.

    Raises:
        ValueError: If the byte value is not a valid value type.
    """
    try:
        return ValType(byte_val)
    except ValueError:
        raise ValueError(f"Invalid value type byte: 0x{byte_val:02X}")


def functype_from_bytes(params_bytes: List[int], results_bytes: List[int]) -> FuncType:
    """Create a FuncType from lists of byte-encoded value types.

    Args:
        params_bytes: List of byte-encoded parameter types.
        results_bytes: List of byte-encoded result types.

    Returns:
        A FuncType with the specified types.
    """
    params = [valtype_from_byte(b) for b in params_bytes]
    results = [valtype_from_byte(b) for b in results_bytes]
    return FuncType(params, results)


def is_stack_type(valtype: ValType) -> bool:
    """Check if a value type is a valid stack type.

    Stack types are all value types that can appear on the operand stack.
    This excludes types that are only used in specific contexts.

    Args:
        valtype: The value type to check.

    Returns:
        True if the type is a valid stack type.
    """
    return valtype in (
        ValType.I32, ValType.I64, ValType.F32, ValType.F64,
        ValType.V128, ValType.FUNCREF, ValType.EXTERNREF
    )


def match_valtype(expected: ValType, actual: ValType) -> bool:
    """Check if an actual value type matches an expected type.

    Args:
        expected: The expected value type.
        actual: The actual value type.

    Returns:
        True if the types match.
    """
    return expected == actual


def match_functype(expected: FuncType, actual: FuncType) -> bool:
    """Check if an actual function type matches an expected type.

    Args:
        expected: The expected function type.
        actual: The actual function type.

    Returns:
        True if the types match.
    """
    return expected == expected


def type_index_from_functype(functype: FuncType, types: List[FuncType]) -> int:
    """Find the index of a function type in a type list.

    Args:
        functype: The function type to find.
        types: The list of function types.

    Returns:
        The index of the function type.

    Raises:
        ValueError: If the function type is not found.
    """
    for i, t in enumerate(types):
        if t == functype:
            return i
    raise ValueError(f"Function type {functype} not found in types list")


def type_check_conversion(src_type: ValType, dst_type: ValType) -> bool:
    """Check if a type conversion is valid.

    Args:
        src_type: The source value type.
        dst_type: The destination value type.

    Returns:
        True if the conversion is valid.
    """
    # Same type is always valid
    if src_type == dst_type:
        return True

    # Integer to integer conversions
    if src_type.is_integer and dst_type.is_integer:
        return True

    # Float to float conversions
    if src_type.is_float and dst_type.is_float:
        return True

    # Integer to float conversions
    if src_type.is_integer and dst_type.is_float:
        return True

    # Float to integer conversions
    if src_type.is_float and dst_type.is_integer:
        return True

    return False