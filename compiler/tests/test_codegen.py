"""
AI 编译器工具链 - 代码生成器测试
"""

import pytest
from src.frontend.parser import ParserHelper
from src.backend.codegen import CCodeGenerator, PythonCodeGenerator, CodeGenerator
from src.backend.x86_gen import X86Generator
from src.backend.llvm_gen import LLVMIRGenerator
from src.middle.ir import (
    IRModule, IRFunction, IRValue, IRValueType, BasicBlock, IROpcode, IRInstruction,
    create_constant_int, IRBuilder,
)
from src.utils.errors import ErrorReporter


class TestCCodeGenerator:
    """C 代码生成器测试"""

    @pytest.fixture
    def program(self):
        source = """
fn add(a: int, b: int) -> int {
    return a + b;
}

fn main() {
    let x: int = 42;
    let y: int = 10;
    let result: int = add(x, y);
    return result;
}
"""
        return ParserHelper.parse_source(source)

    @pytest.fixture
    def simple_program(self):
        source = "fn main() { return 0; }"
        return ParserHelper.parse_source(source)

    def test_generate_c_code(self, simple_program):
        """测试 C 代码生成"""
        gen = CCodeGenerator()
        code = gen.generate(simple_program)
        assert isinstance(code, str)
        assert len(code) > 0
        assert "main" in code
        assert "return 0" in code

    def test_generate_with_function(self, program):
        """测试带函数的 C 代码生成"""
        gen = CCodeGenerator()
        code = gen.generate(program)
        assert "add" in code
        assert "int" in code
        assert "main" in code

    def test_include_headers(self, program):
        """测试头文件包含"""
        gen = CCodeGenerator()
        code = gen.generate(program)
        assert "#include" in code
        assert "stdio.h" in code

    def test_variable_declaration(self, program):
        """测试变量声明生成"""
        gen = CCodeGenerator()
        code = gen.generate(program)
        assert "int x" in code
        assert "int y" in code
        assert "int result" in code

    def test_expression_generation(self, program):
        """测试表达式生成"""
        gen = CCodeGenerator()
        code = gen.generate(program)
        assert "add(x, y)" in code or "add (x, y)" in code

    def test_empty_program(self):
        """测试空程序"""
        program = ParserHelper.parse_source("")
        gen = CCodeGenerator()
        code = gen.generate(program)
        assert isinstance(code, str)


class TestPythonCodeGenerator:
    """Python 代码生成器测试"""

    @pytest.fixture
    def program(self):
        source = """
fn greet(name: string) {
    print(name);
}

fn main() {
    let msg: string = "hello";
    greet(msg);
    return 0;
}
"""
        return ParserHelper.parse_source(source)

    def test_generate_python_code(self):
        """测试 Python 代码生成"""
        source = "fn main() { return 0; }"
        program = ParserHelper.parse_source(source)
        gen = PythonCodeGenerator()
        code = gen.generate(program)
        assert isinstance(code, str)
        assert "def main" in code
        assert "return" in code

    def test_python_function(self, program):
        """测试 Python 函数生成"""
        gen = PythonCodeGenerator()
        code = gen.generate(program)
        assert "def greet(" in code
        assert "def main(" in code

    def test_python_string(self, program):
        """测试 Python 字符串"""
        gen = PythonCodeGenerator()
        code = gen.generate(program)
        assert "'hello'" in code or '"hello"' in code


class TestCodeGenerator:
    """代码生成器工厂测试"""

    def test_c_codegen(self):
        """测试 C 代码生成器工厂"""
        source = "fn main() { return 0; }"
        program = ParserHelper.parse_source(source)
        gen = CodeGenerator()
        code = gen.generate(program, "c")
        assert "main" in code
        assert "return 0" in code

    def test_python_codegen(self):
        """测试 Python 代码生成器工厂"""
        source = "fn main() { return 0; }"
        program = ParserHelper.parse_source(source)
        gen = CodeGenerator()
        code = gen.generate(program, "python")
        assert "def main" in code
        assert "return" in code

    def test_invalid_target(self):
        """测试无效目标"""
        source = "fn main() { return 0; }"
        program = ParserHelper.parse_source(source)
        gen = CodeGenerator()
        with pytest.raises(Exception):
            gen.generate(program, "invalid")

    def test_generate_from_ir(self):
        """测试从 IR 生成代码"""
        ir_module = IRModule("test")
        builder = IRBuilder(ir_module)
        func = builder.new_function("test_func", IRValueType.INT32, [])
        builder.emit_return(create_constant_int(0))

        code = CodeGenerator.generate_from_ir(ir_module, "c")
        assert isinstance(code, str)
        assert "test_func" in code


class TestX86Generator:
    """x86 汇编生成器测试"""

    def test_generate_x86(self):
        """测试 x86 汇编生成"""
        ir_module = IRModule("test")
        builder = IRBuilder(ir_module)
        func = builder.new_function("main", IRValueType.INT32, [])
        func.is_entry = True
        builder.emit_return(create_constant_int(0))

        gen = X86Generator()
        code = gen.generate(ir_module)
        assert isinstance(code, str)
        assert "main:" in code or "_start:" in code
        assert "ret" in code

    def test_register_allocation(self):
        """测试寄存器分配"""
        from src.backend.x86_gen import X86RegisterAllocator
        alloc = X86RegisterAllocator()
        reg = alloc.allocate("test_var")
        assert reg in ["eax", "ebx", "ecx", "edx", "esi", "edi"]
        alloc.free("test_var")


class TestLLVMIRGenerator:
    """LLVM IR 生成器测试"""

    def test_generate_llvm_ir(self):
        """测试 LLVM IR 生成"""
        ir_module = IRModule("test")
        builder = IRBuilder(ir_module)
        func = builder.new_function("main", IRValueType.INT32, [])
        builder.emit_return(create_constant_int(0))

        gen = LLVMIRGenerator()
        code = gen.generate(ir_module)
        assert isinstance(code, str)
        assert "define" in code
        assert "@main" in code
        assert "ret" in code

    def test_llvm_types(self):
        """测试 LLVM 类型"""
        from src.backend.llvm_gen import LLVMIRGenerator
        gen = LLVMIRGenerator()
        assert gen._ir_type_to_llvm(IRValueType.INT32) == "i32"
        assert gen._ir_type_to_llvm(IRValueType.FLOAT64) == "double"
        assert gen._ir_type_to_llvm(IRValueType.INT1) == "i1"

    def test_llvm_arithmetic(self):
        """测试 LLVM 算术指令"""
        ir_module = IRModule("test")
        builder = IRBuilder(ir_module)
        func = builder.new_function("calc", IRValueType.INT32, [
            IRValue("%a", IRValueType.INT32),
            IRValue("%b", IRValueType.INT32),
        ])
        result = builder.emit_add(IRValue("%a", IRValueType.INT32), IRValue("%b", IRValueType.INT32))
        builder.emit_return(result)

        gen = LLVMIRGenerator()
        code = gen.generate(ir_module)
        assert "add" in code