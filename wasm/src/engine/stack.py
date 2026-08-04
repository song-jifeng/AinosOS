"""WebAssembly stack machine.

This module implements the operand stack and control stack used during
WebAssembly execution. It provides efficient push/pop operations and
control flow management.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from ..module.types import ValType, FuncType, BlockType
from ..module.decoder import Instruction, Opcode


class StackValue:
    """A typed value on the operand stack."""

    __slots__ = ('value', 'type')

    def __init__(self, value: Any, val_type: ValType):
        """Initialize a stack value.

        Args:
            value: The raw value.
            val_type: The WebAssembly type.
        """
        self.value = value
        self.type = val_type

    def __repr__(self) -> str:
        return f"{self.type.name}({self.value})"


class ControlEntry:
    """An entry on the control stack for structured control flow."""

    def __init__(
        self,
        kind: str,
        block_type: BlockType,
        start_pc: int,
        start_stack_height: int,
        func_idx: Optional[int] = None,
    ):
        """Initialize a control entry.

        Args:
            kind: The kind ('block', 'loop', 'if', 'else', 'function').
            block_type: The block type annotation.
            start_pc: Program counter at the start of the block.
            start_stack_height: Stack height at the start of the block.
            func_idx: Function index (for function frames).
        """
        self.kind = kind
        self.block_type = block_type
        self.start_pc = start_pc
        self.start_stack_height = start_stack_height
        self.func_idx = func_idx
        self.end_pc: Optional[int] = None
        self.else_pc: Optional[int] = None
        self.unreachable: bool = False
        self.instructions: List[Instruction] = []

    @property
    def label_types(self) -> List[ValType]:
        """Get the label types for branching to this block."""
        if self.kind == 'loop':
            return self.block_type.params
        return self.block_type.results

    @property
    def arity(self) -> int:
        """Get the number of values this block produces."""
        return len(self.block_type.results)

    def __repr__(self) -> str:
        return f"ControlEntry({self.kind}, stack={self.start_stack_height})"


class OperandStack:
    """WebAssembly operand stack with efficient push/pop operations.

    This stack manages typed values during execution, supporting all
    WebAssembly value types and providing type-safe operations.
    """

    def __init__(self, max_height: int = 1000000):
        """Initialize the operand stack.

        Args:
            max_height: Maximum stack height before overflow.
        """
        self.max_height = max_height
        self._values: List[Any] = []
        self._types: List[ValType] = []

    def push(self, value: Any, val_type: ValType) -> None:
        """Push a value onto the stack.

        Args:
            value: The value to push.
            val_type: The type of the value.

        Raises:
            RuntimeError: If the stack overflows.
        """
        if len(self._values) >= self.max_height:
            raise RuntimeError("Operand stack overflow")
        self._values.append(value)
        self._types.append(val_type)

    def push_i32(self, value: int) -> None:
        """Push an i32 value.

        Args:
            value: The 32-bit integer value.
        """
        self.push(value & 0xFFFFFFFF, ValType.I32)

    def push_i64(self, value: int) -> None:
        """Push an i64 value.

        Args:
            value: The 64-bit integer value.
        """
        self.push(value & 0xFFFFFFFFFFFFFFFF, ValType.I64)

    def push_f32(self, value: float) -> None:
        """Push an f32 value.

        Args:
            value: The 32-bit float value.
        """
        import struct
        value = struct.unpack('f', struct.pack('f', value))[0]
        self.push(value, ValType.F32)

    def push_f64(self, value: float) -> None:
        """Push an f64 value.

        Args:
            value: The 64-bit float value.
        """
        self.push(value, ValType.F64)

    def pop(self) -> Any:
        """Pop a value from the stack.

        Returns:
            The popped value.

        Raises:
            IndexError: If the stack is empty.
        """
        if not self._values:
            raise IndexError("Operand stack underflow")
        self._types.pop()
        return self._values.pop()

    def pop_i32(self) -> int:
        """Pop an i32 value.

        Returns:
            The 32-bit integer value.

        Raises:
            IndexError: If the stack is empty.
            TypeError: If the value is not i32.
        """
        if not self._values:
            raise IndexError("Operand stack underflow")
        val_type = self._types.pop()
        if val_type != ValType.I32:
            raise TypeError(f"Expected i32, got {val_type}")
        return self._values.pop()

    def pop_i64(self) -> int:
        """Pop an i64 value.

        Returns:
            The 64-bit integer value.

        Raises:
            IndexError: If the stack is empty.
            TypeError: If the value is not i64.
        """
        if not self._values:
            raise IndexError("Operand stack underflow")
        val_type = self._types.pop()
        if val_type != ValType.I64:
            raise TypeError(f"Expected i64, got {val_type}")
        return self._values.pop()

    def pop_f32(self) -> float:
        """Pop an f32 value.

        Returns:
            The 32-bit float value.

        Raises:
            IndexError: If the stack is empty.
            TypeError: If the value is not f32.
        """
        if not self._values:
            raise IndexError("Operand stack underflow")
        val_type = self._types.pop()
        if val_type != ValType.F32:
            raise TypeError(f"Expected f32, got {val_type}")
        return self._values.pop()

    def pop_f64(self) -> float:
        """Pop an f64 value.

        Returns:
            The 64-bit float value.

        Raises:
            IndexError: If the stack is empty.
            TypeError: If the value is not f64.
        """
        if not self._values:
            raise IndexError("Operand stack underflow")
        val_type = self._types.pop()
        if val_type != ValType.F64:
            raise TypeError(f"Expected f64, got {val_type}")
        return self._values.pop()

    def pop_typed(self) -> Tuple[Any, ValType]:
        """Pop a value with its type.

        Returns:
            Tuple of (value, type).

        Raises:
            IndexError: If the stack is empty.
        """
        if not self._values:
            raise IndexError("Operand stack underflow")
        return (self._values.pop(), self._types.pop())

    def peek(self, depth: int = 0) -> Any:
        """Peek at a value without popping.

        Args:
            depth: How far from the top (0 = top).

        Returns:
            The value at the given depth.
        """
        if depth >= len(self._values):
            raise IndexError(f"Cannot peek at depth {depth}")
        return self._values[-(depth + 1)]

    def peek_type(self, depth: int = 0) -> ValType:
        """Peek at a value's type without popping.

        Args:
            depth: How far from the top (0 = top).

        Returns:
            The type at the given depth.
        """
        if depth >= len(self._types):
            raise IndexError(f"Cannot peek at depth {depth}")
        return self._types[-(depth + 1)]

    def pop_many(self, count: int) -> List[Any]:
        """Pop multiple values from the stack.

        Args:
            count: Number of values to pop.

        Returns:
            List of values in order (first popped = deepest).
        """
        if count > len(self._values):
            raise IndexError(f"Cannot pop {count} values from {len(self._values)}")
        result = [self._values.pop() for _ in range(count)]
        for _ in range(count):
            self._types.pop()
        result.reverse()
        return result

    def push_many(self, values: List[Any], types: List[ValType]) -> None:
        """Push multiple values onto the stack.

        Args:
            values: Values to push.
            types: Types for each value.
        """
        for v, t in zip(values, types):
            self.push(v, t)

    def truncate(self, height: int) -> None:
        """Truncate the stack to a given height.

        Args:
            height: The target height.
        """
        if height < len(self._values):
            del self._values[height:]
            del self._types[height:]

    def clear(self) -> None:
        """Clear the stack."""
        self._values.clear()
        self._types.clear()

    @property
    def height(self) -> int:
        """Get the current stack height."""
        return len(self._values)

    @property
    def is_empty(self) -> bool:
        """Check if the stack is empty."""
        return len(self._values) == 0

    @property
    def values(self) -> List[Any]:
        """Get the raw value list."""
        return list(self._values)

    @property
    def types(self) -> List[ValType]:
        """Get the raw type list."""
        return list(self._types)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        items = []
        for v, t in zip(self._values, self._types):
            items.append(f"{t.name}({v})")
        return f"OperandStack([{', '.join(items)}])"


class ControlStack:
    """Control stack for managing structured control flow.

    Tracks block, loop, if, and function frames during execution,
    enabling proper branching and label resolution.
    """

    def __init__(self, max_depth: int = 100000):
        """Initialize the control stack.

        Args:
            max_depth: Maximum control stack depth.
        """
        self.max_depth = max_depth
        self._frames: List[ControlEntry] = []

    def push(self, entry: ControlEntry) -> None:
        """Push a control frame.

        Args:
            entry: The control entry to push.

        Raises:
            RuntimeError: If the control stack overflows.
        """
        if len(self._frames) >= self.max_depth:
            raise RuntimeError("Control stack overflow")
        self._frames.append(entry)

    def pop(self) -> ControlEntry:
        """Pop the top control frame.

        Returns:
            The popped control entry.

        Raises:
            IndexError: If the stack is empty.
        """
        if not self._frames:
            raise IndexError("Control stack underflow")
        return self._frames.pop()

    def peek(self) -> ControlEntry:
        """Peek at the top control frame without popping.

        Returns:
            The top control entry.
        """
        if not self._frames:
            raise IndexError("Control stack is empty")
        return self._frames[-1]

    def get_label(self, depth: int) -> ControlEntry:
        """Get a control entry by label depth.

        Args:
            depth: Label depth (0 = top, 1 = next, etc.).

        Returns:
            The control entry at the given depth.
        """
        if depth >= len(self._frames):
            raise IndexError(f"Label depth {depth} out of range")
        return self._frames[-(depth + 1)]

    def get_frame(self, func_idx: int) -> Optional[ControlEntry]:
        """Find the control frame for a given function.

        Args:
            func_idx: The function index.

        Returns:
            The control entry for the function, or None.
        """
        for frame in reversed(self._frames):
            if frame.func_idx == func_idx:
                return frame
        return None

    @property
    def depth(self) -> int:
        """Get the current control stack depth."""
        return len(self._frames)

    @property
    def is_empty(self) -> bool:
        """Check if the control stack is empty."""
        return len(self._frames) == 0

    def __len__(self) -> int:
        return len(self._frames)

    def __repr__(self) -> str:
        kinds = [f.kind for f in self._frames]
        return f"ControlStack([{', '.join(kinds)}])"


class CallFrame:
    """A function call frame for the call stack.

    Tracks the function index, local variables, and return address
    for proper function call/return semantics.
    """

    __slots__ = ('func_idx', 'locals', 'module', 'arity', 'return_pc',
                 'return_height', 'stack_height')

    def __init__(
        self,
        func_idx: int,
        locals: List[Any],
        arity: int = 0,
        return_pc: int = 0,
        return_height: int = 0,
        stack_height: int = 0,
    ):
        """Initialize a call frame.

        Args:
            func_idx: The function index.
            locals: List of local variable values.
            arity: Number of return values.
            return_pc: Program counter to return to.
            return_height: Stack height to return to.
            stack_height: Stack height at call time.
        """
        self.func_idx = func_idx
        self.locals = locals
        self.arity = arity
        self.return_pc = return_pc
        self.return_height = return_height
        self.stack_height = stack_height

    def __repr__(self) -> str:
        return f"CallFrame(func={self.func_idx}, arity={self.arity})"


class CallStack:
    """Call stack for managing function call frames.

    Tracks the hierarchy of function calls during execution,
    enabling proper return and stack unwinding.
    """

    def __init__(self, max_depth: int = 100000):
        """Initialize the call stack.

        Args:
            max_depth: Maximum call stack depth.
        """
        self.max_depth = max_depth
        self._frames: List[CallFrame] = []

    def push(self, frame: CallFrame) -> None:
        """Push a call frame.

        Args:
            frame: The call frame to push.

        Raises:
            RuntimeError: If the call stack overflows.
        """
        if len(self._frames) >= self.max_depth:
            raise RuntimeError("Call stack overflow")
        self._frames.append(frame)

    def pop(self) -> CallFrame:
        """Pop the top call frame.

        Returns:
            The popped call frame.

        Raises:
            IndexError: If the stack is empty.
        """
        if not self._frames:
            raise IndexError("Call stack underflow")
        return self._frames.pop()

    def peek(self) -> CallFrame:
        """Peek at the top call frame.

        Returns:
            The top call frame.
        """
        if not self._frames:
            raise IndexError("Call stack is empty")
        return self._frames[-1]

    @property
    def depth(self) -> int:
        """Get the current call stack depth."""
        return len(self._frames)

    @property
    def is_empty(self) -> bool:
        """Check if the call stack is empty."""
        return len(self._frames) == 0

    def __len__(self) -> int:
        return len(self._frames)

    def __repr__(self) -> str:
        return f"CallStack(depth={len(self._frames)})"


class Trap(Exception):
    """Exception raised for WebAssembly traps.

    Traps occur on runtime errors like division by zero,
    memory access out of bounds, indirect call type mismatch, etc.
    """

    def __init__(self, message: str, context: Optional[str] = None):
        """Initialize the trap.

        Args:
            message: Trap description.
            context: Optional context about where the trap occurred.
        """
        full_msg = f"{context}: {message}" if context else message
        super().__init__(full_msg)
        self.context = context


class WasmRuntimeError(Exception):
    """Base exception for WebAssembly runtime errors."""

    def __init__(self, message: str, pc: int = 0):
        """Initialize the error.

        Args:
            message: Error description.
            pc: Program counter where the error occurred.
        """
        super().__init__(message)
        self.pc = pc