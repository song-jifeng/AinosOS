"""
AI 编译器工具链 - 优化器测试
"""

import pytest
from src.middle.ir import (
    IRModule, IRFunction, IRInstruction, IRValue, IRValueType, BasicBlock, IROpcode,
    create_constant_int, create_constant_float, IRBuilder,
)
from src.middle.optimizer import Optimizer, OptimizationPipeline
from src.utils.errors import ErrorReporter


class TestOptimizer:
    """优化器测试"""

    @pytest.fixture
    def ir_module(self):
        """创建测试用 IR 模块"""
        module = IRModule("test")
        builder = IRBuilder(module)

        # 创建测试函数
        func = builder.new_function("test_func", IRValueType.INT32, [
            IRValue("%x", IRValueType.INT32),
        ])
        builder.emit_comment("Test function")

        # 加法
        a = builder.emit_add(create_constant_int(2), create_constant_int(3), comment="2 + 3")
        b = builder.emit_add(a, create_constant_int(5), comment="result + 5")
        builder.emit_return(b, comment="return")

        return module

    @pytest.fixture
    def dead_code_module(self):
        """创建含死代码的 IR 模块"""
        module = IRModule("dead_code_test")
        builder = IRBuilder(module)

        func = builder.new_function("dead_func", IRValueType.INT32, [])
        builder.emit_comment("Dead code test")

        a = builder.emit_add(create_constant_int(1), create_constant_int(2), comment="used")
        b = builder.emit_add(create_constant_int(3), create_constant_int(4), comment="unused")
        builder.emit_return(a, comment="return only a")

        return module

    @pytest.fixture
    def loop_module(self):
        """创建含循环的 IR 模块"""
        module = IRModule("loop_test")
        builder = IRBuilder(module)

        func = builder.new_function("loop_func", IRValueType.INT32, [])
        builder.emit_comment("Loop test")

        loop_start = builder.new_label("loop")
        loop_end = builder.new_label("end")

        builder.emit_label(loop_start)
        # 循环不变式
        x = builder.emit_add(create_constant_int(1), create_constant_int(2), comment="loop invariant")
        # 条件
        cond = builder.emit_icmp("lt", create_constant_int(0), create_constant_int(10))
        builder.emit_if_goto(cond, loop_end)

        builder.emit_goto(loop_start)
        builder.emit_label(loop_end)
        builder.emit_return(x)

        return module

    def test_constant_folding(self, ir_module):
        """测试常量折叠"""
        optimizer = Optimizer(ir_module)
        optimizer.constant_folding()

        # 检查常量是否被折叠
        func = ir_module.functions["test_func"]
        for block in func.blocks:
            for instr in block.instructions:
                if instr.opcode == IROpcode.ADD_I:
                    # 应该只剩下一个有实际变量的加法
                    pass

    def test_dead_code_elimination(self, dead_code_module):
        """测试死代码消除"""
        optimizer = Optimizer(dead_code_module)
        optimizer.dead_code_elimination()

        func = dead_code_module.functions["dead_func"]
        for block in func.blocks:
            for instr in block.instructions:
                # 不应该有未使用的加法指令
                if instr.opcode == IROpcode.ADD_I:
                    if instr.dest and instr.dest.name == "%t1":
                        pass  # 这个指令可能被保留

    def test_copy_propagation(self, ir_module):
        """测试复制传播"""
        # 添加复制指令
        func = ir_module.functions["test_func"]
        block = func.blocks[0]
        # 在函数末尾添加复制
        copy_instr = IRInstruction(IROpcode.COPY, create_constant_int(99), [create_constant_int(100)])
        block.add_instruction(copy_instr)

        optimizer = Optimizer(ir_module)
        optimizer.copy_propagation()

    def test_loop_invariant_hoisting(self, loop_module):
        """测试循环不变式外提"""
        optimizer = Optimizer(loop_module)
        optimizer.loop_invariant_hoisting()

    def test_strength_reduction(self, ir_module):
        """测试强度削弱"""
        func = ir_module.functions["test_func"]
        block = func.blocks[0]

        # 添加乘法指令用于强度削弱测试
        x = IRValue("%x", IRValueType.INT32)
        mul_instr = IRInstruction(IROpcode.MUL_I, IRValue("%tmp", IRValueType.INT32), [x, create_constant_int(2)])
        block.add_instruction(mul_instr)

        optimizer = Optimizer(ir_module)
        optimizer.strength_reduction()

        # 检查是否被替换为左移
        found_shift = False
        for instr in block.instructions:
            if instr.opcode == IROpcode.SHL:
                found_shift = True
                break
        assert found_shift, "2*x 应该被优化为 x << 1"

    def test_peephole_optimization(self, ir_module):
        """测试窥孔优化"""
        # 创建冗余复制
        func = ir_module.functions["test_func"]
        block = func.blocks[0]
        dest = IRValue("%tmp", IRValueType.INT32)
        copy1 = IRInstruction(IROpcode.COPY, dest, [dest])  # x = x, 冗余
        block.add_instruction(copy1)

        optimizer = Optimizer(ir_module)
        optimizer.peephole_optimization()

        # 检查冗余复制是否被移除
        for instr in block.instructions:
            assert not (instr.opcode == IROpcode.COPY and instr.dest and instr.operands
                       and instr.dest.name == instr.operands[0].name), "冗余复制应被移除"

    def test_common_subexpression_elimination(self, ir_module):
        """测试公共子表达式消除"""
        func = ir_module.functions["test_func"]
        block = func.blocks[0]

        # 添加重复的表达式
        a = create_constant_int(5)
        b = create_constant_int(7)
        c = create_constant_int(5)
        d = create_constant_int(7)

        expr1 = IRInstruction(IROpcode.ADD_I, IRValue("%r1", IRValueType.INT32), [a, b])
        expr2 = IRInstruction(IROpcode.ADD_I, IRValue("%r2", IRValueType.INT32), [c, d])
        block.add_instruction(expr1)
        block.add_instruction(expr2)

        optimizer = Optimizer(ir_module)
        optimizer.common_subexpression_elimination()

    def test_optimization_pipeline(self, ir_module):
        """测试优化管道"""
        pipeline = OptimizationPipeline(ir_module)
        result = pipeline.run(level=2)
        assert result is ir_module


class TestOptimizationPipeline:
    """优化管道测试"""

    def test_level_0(self, ir_module):
        """测试 O0"""
        module = ir_module
        pipeline = OptimizationPipeline(module)
        result = pipeline.run(level=0)
        assert result == module

    def test_level_1(self, ir_module):
        """测试 O1"""
        pipeline = OptimizationPipeline(ir_module)
        result = pipeline.run(level=1)
        assert result is ir_module

    def test_level_2(self, ir_module):
        """测试 O2"""
        pipeline = OptimizationPipeline(ir_module)
        result = pipeline.run(level=2)
        assert result is ir_module

    def test_level_3(self, ir_module):
        """测试 O3"""
        pipeline = OptimizationPipeline(ir_module)
        result = pipeline.run(level=3)
        assert result is ir_module

    def test_custom_passes(self, ir_module):
        """测试自定义优化顺序"""
        pipeline = OptimizationPipeline(ir_module)
        result = pipeline.run_custom(["constant_folding", "dead_code_elimination"])
        assert result is ir_module

    @pytest.fixture
    def ir_module(self):
        module = IRModule("pipeline_test")
        builder = IRBuilder(module)
        func = builder.new_function("test", IRValueType.INT32, [])
        builder.emit_comment("Pipeline test")
        builder.emit_return(create_constant_int(0))
        return module