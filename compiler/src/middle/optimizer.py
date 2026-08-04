"""
AI 编译器工具链 - 优化器
"""

from __future__ import annotations

from typing import Optional, Any

from src.middle.ir import (
    IRModule, IRFunction, IRInstruction, BasicBlock, IRValue, IRValueType,
    IROpcode, IRBuilder, create_constant_int, create_constant_float, create_constant_bool,
)
from src.utils.errors import OptimizerError, ErrorReporter


class Optimizer:
    """编译器优化器 - 实现多种优化 pass"""

    def __init__(self, ir_module: IRModule, error_reporter: Optional[ErrorReporter] = None):
        self.ir_module: IRModule = ir_module
        self.error_reporter: ErrorReporter = error_reporter or ErrorReporter()
        self._changed: bool = False

    def optimize(self, passes: list[str] | None = None) -> IRModule:
        """运行优化 passes"""
        passes = passes or ["constant_folding", "dead_code_elimination"]

        pass_map = {
            "constant_folding": self.constant_folding,
            "dead_code_elimination": self.dead_code_elimination,
            "loop_invariant_hoisting": self.loop_invariant_hoisting,
            "cse": self.common_subexpression_elimination,
            "copy_propagation": self.copy_propagation,
            "strength_reduction": self.strength_reduction,
            "peephole": self.peephole_optimization,
            "inlining": self.inline_functions,
            "tail_call": self.tail_call_elimination,
            "vectorization": self.vectorization,
        }

        for pass_name in passes:
            if pass_name in pass_map:
                self._changed = True
                iteration = 0
                while self._changed and iteration < 10:
                    self._changed = False
                    pass_map[pass_name]()
                    iteration += 1

        return self.ir_module

    def constant_folding(self) -> None:
        """常量折叠 - 在编译时计算常量表达式"""
        for func in self.ir_module.functions.values():
            for block in func.blocks:
                i = 0
                while i < len(block.instructions):
                    instr = block.instructions[i]
                    if IROpcode.is_arithmetic(instr.opcode) and len(instr.operands) == 2:
                        left, right = instr.operands[0], instr.operands[1]
                        if left.is_constant and right.is_constant:
                            result = self._eval_constant_op(instr.opcode, left, right)
                            if result is not None:
                                # 替换指令为常量
                                if instr.dest:
                                    new_instr = IRInstruction(
                                        IROpcode.COPY, instr.dest, [result],
                                        comment=f"constant folded {left.value} {instr.opcode.name} {right.value}"
                                    )
                                    block.replace_instruction(instr, new_instr)
                                    self._changed = True
                    i += 1

    def _eval_constant_op(self, opcode: IROpcode, left: IRValue, right: IRValue) -> Optional[IRValue]:
        """计算常量操作结果"""
        try:
            lv = int(left.value) if left.value else 0
            rv = int(right.value) if right.value else 0
            lf = float(left.value) if left.value else 0.0
            rf = float(right.value) if right.value else 0.0

            if opcode in (IROpcode.ADD, IROpcode.ADD_I):
                return create_constant_int(lv + rv)
            elif opcode in (IROpcode.ADD_F,):
                return create_constant_float(lf + rf)
            elif opcode in (IROpcode.SUB, IROpcode.SUB_I):
                return create_constant_int(lv - rv)
            elif opcode in (IROpcode.SUB_F,):
                return create_constant_float(lf - rf)
            elif opcode in (IROpcode.MUL, IROpcode.MUL_I):
                return create_constant_int(lv * rv)
            elif opcode in (IROpcode.MUL_F,):
                return create_constant_float(lf * rf)
            elif opcode in (IROpcode.DIV, IROpcode.DIV_I):
                if rv != 0:
                    return create_constant_int(lv // rv)
            elif opcode in (IROpcode.DIV_F,):
                if rf != 0.0:
                    return create_constant_float(lf / rf)
            elif opcode in (IROpcode.MOD, IROpcode.MOD_I):
                if rv != 0:
                    return create_constant_int(lv % rv)
            elif opcode == IROpcode.AND_I:
                return create_constant_int(lv & rv)
            elif opcode == IROpcode.OR_I:
                return create_constant_int(lv | rv)
            elif opcode == IROpcode.XOR_I:
                return create_constant_int(lv ^ rv)
            elif opcode == IROpcode.SHL:
                return create_constant_int(lv << rv)
            elif opcode == IROpcode.SHR:
                return create_constant_int(lv >> rv)
            elif opcode in (IROpcode.EQ, IROpcode.EQ_I):
                return create_constant_bool(lv == rv)
            elif opcode in (IROpcode.NE, IROpcode.NE_I):
                return create_constant_bool(lv != rv)
            elif opcode in (IROpcode.LT, IROpcode.LT_I):
                return create_constant_bool(lv < rv)
            elif opcode in (IROpcode.GT, IROpcode.GT_I):
                return create_constant_bool(lv > rv)
            elif opcode in (IROpcode.LE, IROpcode.LE_I):
                return create_constant_bool(lv <= rv)
            elif opcode in (IROpcode.GE, IROpcode.GE_I):
                return create_constant_bool(lv >= rv)
            elif opcode == IROpcode.NEG:
                return create_constant_int(-lv)
        except (ValueError, TypeError, ZeroDivisionError):
            pass
        return None

    def dead_code_elimination(self) -> None:
        """死代码消除 - 移除无用指令"""
        for func in self.ir_module.functions.values():
            self._dce_function(func)

    def _dce_function(self, func: IRFunction) -> None:
        """对函数执行死代码消除"""
        # 收集所有使用的变量
        used_vars: set[str] = set()
        for block in func.blocks:
            for instr in block.instructions:
                if instr.opcode == IROpcode.RETURN or instr.opcode == IROpcode.RET:
                    pass
                for op in instr.operands:
                    if op.name and op.name.startswith('%'):
                        used_vars.add(op.name)
                if instr.opcode == IROpcode.IF_GOTO and instr.label:
                    pass

        # 标记对控制流/副作用重要的指令
        important: set[int] = set()
        for i, block in enumerate(func.blocks):
            for j, instr in enumerate(block.instructions):
                if IROpcode.is_terminator(instr.opcode) or IROpcode.has_side_effects(instr.opcode):
                    important.add((i, j))
                if instr.opcode == IROpcode.CALL:
                    important.add((i, j))
                if instr.opcode == IROpcode.STORE:
                    important.add((i, j))

        # 移除未使用的赋值指令
        for i, block in enumerate(func.blocks):
            to_remove = []
            for j, instr in enumerate(block.instructions):
                if (i, j) in important:
                    continue
                if instr.dest and instr.dest.name not in used_vars:
                    if not IROpcode.has_side_effects(instr.opcode):
                        to_remove.append(instr)
            for instr in to_remove:
                block.remove_instruction(instr)
                self._changed = True

    def loop_invariant_hoisting(self) -> None:
        """循环不变式外提"""
        for func in self.ir_module.functions.values():
            self._hoist_loop_invariants(func)

    def _hoist_loop_invariants(self, func: IRFunction) -> None:
        """将循环不变式提到循环前"""
        # 检测循环结构（简单模式）
        loops = self._find_loops(func)
        for loop in loops:
            header, body = loop
            # 找到循环前的基本块
            preheader = None
            for pred in header.predecessors:
                if pred not in body:
                    preheader = pred
                    break
            if preheader is None:
                continue

            # 找到循环不变指令
            invariant_instrs = []
            for block in body:
                for instr in block.instructions:
                    if IROpcode.is_arithmetic(instr.opcode) and not IROpcode.has_side_effects(instr.opcode):
                        if self._is_loop_invariant(instr, body):
                            invariant_instrs.append((block, instr))

            # 外提
            for block, instr in reversed(invariant_instrs):
                preheader.instructions.insert(-1, instr)  # 插入到终止指令前
                block.remove_instruction(instr)
                self._changed = True

    def _find_loops(self, func: IRFunction) -> list[tuple[BasicBlock, list[BasicBlock]]]:
        """寻找循环结构（简单回边检测）"""
        loops = []
        for block in func.blocks:
            for succ in block.successors:
                if succ in func.blocks and func.blocks.index(succ) <= func.blocks.index(block):
                    # 发现回边
                    if succ not in [l[0] for l in loops]:
                        # 收集循环体
                        body = [succ]
                        visited = {succ}
                        stack = [block]
                        while stack:
                            current = stack.pop()
                            if current not in visited:
                                visited.add(current)
                                body.append(current)
                                for pred in current.predecessors:
                                    if pred not in visited and pred in func.blocks:
                                        stack.append(pred)
                        loops.append((succ, body))
        return loops

    def _is_loop_invariant(self, instr: IRInstruction, loop_body: list[BasicBlock]) -> bool:
        """检查指令是否为循环不变式"""
        for op in instr.operands:
            if op.is_constant:
                continue
            # 检查操作数是否在循环外定义
            defined_in_loop = False
            for block in loop_body:
                for other_instr in block.instructions:
                    if other_instr.dest and other_instr.dest.name == op.name:
                        defined_in_loop = True
                        break
                if defined_in_loop:
                    break
            if defined_in_loop:
                return False
        return True

    def common_subexpression_elimination(self) -> None:
        """公共子表达式消除 (CSE)"""
        for func in self.ir_module.functions.values():
            self._cse_function(func)

    def _cse_function(self, func: IRFunction) -> None:
        """对函数执行 CSE"""
        for block in func.blocks:
            seen: dict[tuple, IRInstruction] = {}
            to_replace: list[tuple[IRInstruction, IRInstruction]] = []

            for instr in block.instructions:
                if IROpcode.is_arithmetic(instr.opcode) and instr.dest:
                    key = (instr.opcode, tuple(op.name for op in instr.operands))
                    if key in seen:
                        to_replace.append((instr, seen[key]))
                    else:
                        seen[key] = instr

            for old, replacement in to_replace:
                if old.dest:
                    copy_instr = IRInstruction(IROpcode.COPY, old.dest, [replacement.dest], comment=f"CSE {replacement.dest.name}")
                    block.replace_instruction(old, copy_instr)
                    self._changed = True

    def copy_propagation(self) -> None:
        """复制传播"""
        for func in self.ir_module.functions.values():
            # 构建值映射
            value_map: dict[str, IRValue] = {}
            for block in func.blocks:
                for instr in block.instructions:
                    if instr.opcode == IROpcode.COPY and instr.dest and instr.operands:
                        value_map[instr.dest.name] = instr.operands[0]

            # 应用映射
            if value_map:
                for block in func.blocks:
                    for instr in block.instructions:
                        for i, op in enumerate(instr.operands):
                            if op.name in value_map and op.name.startswith('%'):
                                instr.operands[i] = value_map[op.name]
                                self._changed = True

    def strength_reduction(self) -> None:
        """强度削弱"""
        for func in self.ir_module.functions.values():
            for block in func.blocks:
                for instr in block.instructions:
                    if instr.opcode == IROpcode.MUL_I and len(instr.operands) == 2:
                        left, right = instr.operands[0], instr.operands[1]
                        if right.is_constant:
                            val = int(right.value) if right.value else 0
                            if val == 2:
                                # x * 2 -> x << 1
                                if instr.dest:
                                    new_instr = IRInstruction(IROpcode.SHL, instr.dest, [left, create_constant_int(1)],
                                                             comment="strength reduction: *2 -> <<1")
                                    block.replace_instruction(instr, new_instr)
                                    self._changed = True
                            elif val == 0:
                                if instr.dest:
                                    new_instr = IRInstruction(IROpcode.COPY, instr.dest, [create_constant_int(0)],
                                                             comment="strength reduction: *0")
                                    block.replace_instruction(instr, new_instr)
                                    self._changed = True
                            elif val == 1:
                                if instr.dest:
                                    new_instr = IRInstruction(IROpcode.COPY, instr.dest, [left],
                                                             comment="strength reduction: *1")
                                    block.replace_instruction(instr, new_instr)
                                    self._changed = True
                            elif val > 0 and (val & (val - 1)) == 0:
                                # 2 的幂次: x * 2^n -> x << n
                                shift = val.bit_length() - 1
                                if shift > 0 and instr.dest:
                                    new_instr = IRInstruction(IROpcode.SHL, instr.dest, [left, create_constant_int(shift)],
                                                             comment=f"strength reduction: *{val} -> <<{shift}")
                                    block.replace_instruction(instr, new_instr)
                                    self._changed = True

                    elif instr.opcode == IROpcode.DIV_I and len(instr.operands) == 2:
                        left, right = instr.operands[0], instr.operands[1]
                        if right.is_constant:
                            val = int(right.value) if right.value else 0
                            if val == 1 and instr.dest:
                                new_instr = IRInstruction(IROpcode.COPY, instr.dest, [left],
                                                         comment="strength reduction: /1")
                                block.replace_instruction(instr, new_instr)
                                self._changed = True
                            elif val > 0 and (val & (val - 1)) == 0:
                                # 2 的幂次: x / 2^n -> x >> n
                                shift = val.bit_length() - 1
                                if shift > 0 and instr.dest:
                                    new_instr = IRInstruction(IROpcode.SHR, instr.dest, [left, create_constant_int(shift)],
                                                             comment=f"strength reduction: /{val} -> >>{shift}")
                                    block.replace_instruction(instr, new_instr)
                                    self._changed = True

    def peephole_optimization(self) -> None:
        """窥孔优化"""
        for func in self.ir_module.functions.values():
            for block in func.blocks:
                i = 0
                while i < len(block.instructions) - 1:
                    curr = block.instructions[i]
                    next_instr = block.instructions[i + 1]

                    # 消除连续的 goto
                    if curr.opcode == IROpcode.GOTO and next_instr.opcode == IROpcode.GOTO:
                        if curr.label == next_instr.label:
                            block.remove_instruction(next_instr)
                            self._changed = True
                            continue

                    # 消除标签后的无条件跳转到下一基本块
                    if curr.opcode == IROpcode.GOTO and curr.label:
                        for j, other_block in enumerate(func.blocks):
                            if other_block.name == curr.label and j == func.blocks.index(block) + 1:
                                # 跳转到下一基本块，可以移除
                                block.remove_instruction(curr)
                                self._changed = True
                                break

                    # 消除冗余的 load/store
                    if curr.opcode == IROpcode.STORE and next_instr.opcode == IROpcode.LOAD:
                        if (curr.operands[0].name == next_instr.operands[0].name
                                and next_instr.dest is not None):
                            # 存储后立即加载同一地址 -> 复制
                            if curr.dest is None:
                                new_instr = IRInstruction(IROpcode.COPY, next_instr.dest, [curr.operands[1]],
                                                         comment="peephole: store+load -> copy")
                                block.replace_instruction(next_instr, new_instr)
                                self._changed = True
                                i += 1
                                continue

                    # 消除无用的复制 x = x
                    if curr.opcode == IROpcode.COPY and curr.dest and curr.operands:
                        if curr.dest.name == curr.operands[0].name:
                            block.remove_instruction(curr)
                            self._changed = True
                            continue

                    # 常量布尔条件简化
                    if curr.opcode == IROpcode.IF_GOTO and curr.operands:
                        cond = curr.operands[0]
                        if cond.is_constant and cond.value is not None:
                            if cond.value:
                                # if true goto L -> goto L
                                new_instr = IRInstruction(IROpcode.GOTO, label=curr.label,
                                                         comment="peephole: if true -> goto")
                                block.replace_instruction(curr, new_instr)
                            else:
                                # if false goto L -> nop
                                block.remove_instruction(curr)
                            self._changed = True
                            continue

                    i += 1

    def inline_functions(self) -> None:
        """函数内联（简单实现）"""
        # 只内联小函数
        threshold = 10  # 指令数阈值
        for func_name, func in list(self.ir_module.functions.items()):
            if func.is_extern or func.is_entry:
                continue
            # 计算函数体指令数
            instr_count = sum(len(b.instructions) for b in func.blocks)
            if instr_count > threshold:
                continue

            # 查找所有调用点并内联
            for caller_name, caller_func in self.ir_module.functions.items():
                if caller_name == func_name:
                    continue
                for block in caller_func.blocks:
                    to_inline = []
                    for instr in block.instructions:
                        if instr.opcode == IROpcode.CALL:
                            callee_name = instr.operands[0].name if instr.operands else ""
                            if callee_name == f"@{func_name}":
                                to_inline.append(instr)

                    # 执行内联替换（简化实现）
                    for instr in to_inline:
                        self._inline_call(caller_func, block, instr, func)

    def _inline_call(self, caller_func: IRFunction, block: BasicBlock, call_instr: IRInstruction, callee: IRFunction) -> None:
        """内联函数调用"""
        idx = block.instructions.index(call_instr)
        # 复制被调用函数的基本块到调用处
        suffix = f"_inline_{callee.name}"
        for callee_block in callee.blocks:
            new_block = BasicBlock(f"{callee_block.name}{suffix}")
            for callee_instr in callee_block.instructions:
                if callee_instr.opcode == IROpcode.RETURN or callee_instr.opcode == IROpcode.RET:
                    # 将 return 替换为对 dest 的赋值
                    if call_instr.dest and callee_instr.operands:
                        copy_instr = IRInstruction(IROpcode.COPY, call_instr.dest, callee_instr.operands,
                                                   comment="inlined return")
                        new_block.add_instruction(copy_instr)
                    # 跳转到调用后的标签
                    after_label = f"after_call{suffix}"
                    new_block.add_instruction(IRInstruction(IROpcode.GOTO, label=after_label))
                else:
                    new_block.add_instruction(callee_instr)
            caller_func.blocks.insert(caller_func.blocks.index(block) + 1, new_block)
        # 移除原调用指令
        block.remove_instruction(call_instr)
        # 添加跳转到内联函数入口
        block.add_instruction(IRInstruction(IROpcode.GOTO, label=f"{callee.entry_block.name}{suffix}" if callee.entry_block else ""))
        # 添加调用后的标签
        after_block = BasicBlock(f"after_call{suffix}")
        caller_func.blocks.insert(caller_func.blocks.index(block) + len(callee.blocks) + 1, after_block)
        self._changed = True

    def tail_call_elimination(self) -> None:
        """尾调用消除"""
        for func in self.ir_module.functions.values():
            for block in func.blocks:
                for i, instr in enumerate(block.instructions):
                    if instr.opcode == IROpcode.CALL:
                        # 检查是否在 return 前
                        if i + 1 < len(block.instructions):
                            next_instr = block.instructions[i + 1]
                            if next_instr.opcode in (IROpcode.RETURN, IROpcode.RET):
                                if next_instr.operands and instr.dest:
                                    if next_instr.operands[0].name == instr.dest.name:
                                        # 尾调用优化: 替换为 goto + 参数传递
                                        block.instructions[i] = IRInstruction(IROpcode.GOTO, label=f"@{func.name}_entry",
                                                                              comment="tail call elimination")
                                        self._changed = True

    def vectorization(self) -> None:
        """向量化（存根实现）"""
        for func in self.ir_module.functions.values():
            for block in func.blocks:
                # 寻找可向量化的循环模式
                # 简单示例：连续的加法操作
                i = 0
                while i < len(block.instructions) - 3:
                    ops = block.instructions[i:i + 4]
                    if all(op.opcode == IROpcode.ADD_I for op in ops):
                        # 可以将这些操作合并：但需要特定的 SIMD 支持
                        # 这里仅作标记
                        for op in ops:
                            op.comment = "vectorizable"
                    i += 1

    def run_all(self) -> IRModule:
        """运行所有优化"""
        for pass_name in ["constant_folding", "copy_propagation", "dead_code_elimination",
                          "strength_reduction", "peephole", "cse", "loop_invariant_hoisting"]:
            self.optimize([pass_name])
        return self.ir_module


class OptimizationPipeline:
    """优化管道 - 管理和执行优化顺序"""

    def __init__(self, ir_module: IRModule, error_reporter: Optional[ErrorReporter] = None):
        self.ir_module = ir_module
        self.error_reporter = error_reporter or ErrorReporter()
        self.optimizer = Optimizer(ir_module, error_reporter)

    def run(self, level: int = 2) -> IRModule:
        """根据优化级别运行管道"""
        if level == 0:
            return self.ir_module

        passes = []
        if level >= 1:
            passes.extend([
                "constant_folding",
                "peephole",
                "dead_code_elimination",
            ])
        if level >= 2:
            passes.extend([
                "copy_propagation",
                "cse",
                "strength_reduction",
                "loop_invariant_hoisting",
            ])
        if level >= 3:
            passes.extend([
                "inlining",
                "tail_call",
                "vectorization",
            ])

        return self.optimizer.optimize(passes)

    def run_custom(self, passes: list[str]) -> IRModule:
        """运行自定义优化顺序"""
        return self.optimizer.optimize(passes)


class OptimizationReporter:
    """优化报告器"""

    @staticmethod
    def report(ir_module: IRModule, before: IRModule, passes: list[str]) -> str:
        """生成优化报告"""
        lines = ["优化报告:"]
        lines.append(f"  模块: {ir_module.name}")
        lines.append(f"  执行的优化: {', '.join(passes)}")

        # 统计指令数变化
        before_instrs = sum(len(instr) for func in before.functions.values()
                           for block in func.blocks for instr in block.instructions)
        after_instrs = sum(len(instr) for func in ir_module.functions.values()
                          for block in func.blocks for instr in block.instructions)

        lines.append(f"  指令数: {before_instrs} -> {after_instrs} ({after_instrs - before_instrs:+d})")
        if before_instrs > 0:
            reduction = (before_instrs - after_instrs) / before_instrs * 100
            lines.append(f"  减少: {reduction:.1f}%")

        return "\n".join(lines)