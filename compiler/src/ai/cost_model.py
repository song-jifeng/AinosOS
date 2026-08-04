"""
AI 编译器工具链 - 成本模型（预测优化收益）
"""

from __future__ import annotations

import math
from typing import Optional, Any

from src.middle.ir import (
    IRModule, IRFunction, IRInstruction, IRValue, IRValueType, BasicBlock, IROpcode,
)


class CostModel:
    """成本模型 - 预测优化收益"""

    def __init__(self):
        # 指令延迟（周期数）
        self._instr_latency: dict[IROpcode, float] = {
            IROpcode.ADD_I: 1.0, IROpcode.SUB_I: 1.0, IROpcode.MUL_I: 3.0,
            IROpcode.DIV_I: 20.0, IROpcode.MOD_I: 20.0,
            IROpcode.ADD_F: 3.0, IROpcode.SUB_F: 3.0, IROpcode.MUL_F: 5.0,
            IROpcode.DIV_F: 20.0,
            IROpcode.LOAD: 4.0, IROpcode.STORE: 4.0,
            IROpcode.CALL: 50.0, IROpcode.RETURN: 10.0,
            IROpcode.GOTO: 2.0, IROpcode.IF_GOTO: 3.0,
            IROpcode.AND_I: 1.0, IROpcode.OR_I: 1.0, IROpcode.XOR_I: 1.0,
            IROpcode.SHL: 1.0, IROpcode.SHR: 1.0,
            IROpcode.EQ_I: 1.0, IROpcode.NE_I: 1.0,
            IROpcode.LT_I: 1.0, IROpcode.GT_I: 1.0,
            IROpcode.LE_I: 1.0, IROpcode.GE_I: 1.0,
            IROpcode.COPY: 1.0, IROpcode.NEG: 1.0,
            IROpcode.MATMUL: 200.0, IROpcode.CONV2D: 500.0,
            IROpcode.RELU: 5.0, IROpcode.SIGMOID: 20.0,
            IROpcode.TANH: 20.0, IROpcode.SOFTMAX: 50.0,
        }
        self._default_latency: float = 5.0

    def estimate_function_cost(self, func: IRFunction) -> float:
        """估计函数执行成本"""
        total_cost = 0.0
        for block in func.blocks:
            for instr in block.instructions:
                total_cost += self._instr_latency.get(instr.opcode, self._default_latency)
            # 分支预测惩罚
            if len(block.successors) > 1:
                total_cost += 2.0
        return total_cost

    def estimate_module_cost(self, ir_module: IRModule) -> float:
        """估计模块执行成本"""
        total_cost = 0.0
        for func in ir_module.functions.values():
            if not func.is_extern:
                total_cost += self.estimate_function_cost(func)
        return total_cost

    def estimate_inline_benefit(self, caller: IRFunction, callee: IRFunction) -> float:
        """估计内联优化收益"""
        caller_cost = self.estimate_function_cost(caller)
        callee_cost = self.estimate_function_cost(callee)

        call_overhead = 10.0  # 调用开销
        inline_cost = callee_cost * 0.8  # 内联后略有减少

        # 如果调用频繁，内联收益更大
        benefit = call_overhead - (inline_cost - callee_cost)
        return benefit

    def estimate_constant_folding_benefit(self, ir_module: IRModule) -> float:
        """估计常量折叠收益"""
        total = 0.0
        for func in ir_module.functions.values():
            for block in func.blocks:
                for instr in block.instructions:
                    if IROpcode.is_arithmetic(instr.opcode) and len(instr.operands) == 2:
                        if all(op.is_constant for op in instr.operands):
                            total += self._instr_latency.get(instr.opcode, self._default_latency) * 0.5
        return total

    def estimate_dead_code_elimination_benefit(self, ir_module: IRModule) -> float:
        """估计死代码消除收益"""
        total = 0.0
        for func in ir_module.functions.values():
            for block in func.blocks:
                used_vars: set[str] = set()
                for instr in block.instructions:
                    for op in instr.operands:
                        if op.name and op.name.startswith('%'):
                            used_vars.add(op.name)
                for instr in block.instructions:
                    if (instr.dest and instr.dest.name not in used_vars
                            and not IROpcode.has_side_effects(instr.opcode)):
                        total += self._instr_latency.get(instr.opcode, self._default_latency)
        return total

    def estimate_loop_hoisting_benefit(self, ir_module: IRModule) -> float:
        """估计循环不变式外提收益"""
        total = 0.0
        for func in ir_module.functions.values():
            # 检测循环
            for block in func.blocks:
                for succ in block.successors:
                    if succ in func.blocks and func.blocks.index(succ) <= func.blocks.index(block):
                        # 发现回边（简单循环检测）
                        for instr in succ.instructions:
                            if IROpcode.is_arithmetic(instr.opcode) and not IROpcode.has_side_effects(instr.opcode):
                                # 估计循环迭代次数为 10
                                total += self._instr_latency.get(instr.opcode, self._default_latency) * 9
        return total

    def estimate_optimization_benefit(self, ir_module: IRModule, pass_name: str) -> float:
        """估计特定优化 pass 的收益"""
        benefit_map = {
            "constant_folding": self.estimate_constant_folding_benefit,
            "dead_code_elimination": self.estimate_dead_code_elimination_benefit,
            "loop_invariant_hoisting": self.estimate_loop_hoisting_benefit,
        }
        estimator = benefit_map.get(pass_name)
        if estimator:
            return estimator(ir_module)
        return 0.0

    def predict_speedup(self, ir_module: IRModule, passes: list[str]) -> float:
        """预测优化后的加速比"""
        original_cost = self.estimate_module_cost(ir_module)
        if original_cost <= 0:
            return 1.0

        saved_cost = 0.0
        for pass_name in passes:
            saved_cost += self.estimate_optimization_benefit(ir_module, pass_name)

        # 避免过度估计
        saved_cost = min(saved_cost, original_cost * 0.8)
        new_cost = original_cost - saved_cost
        return original_cost / new_cost if new_cost > 0 else 1.0

    def get_instruction_count(self, ir_module: IRModule) -> int:
        """获取指令总数"""
        count = 0
        for func in ir_module.functions.values():
            for block in func.blocks:
                count += len(block.instructions)
        return count

    def get_estimated_cycles(self, ir_module: IRModule) -> float:
        """获取估计的周期数"""
        return self.estimate_module_cost(ir_module)


class OptimizationCostBenefitAnalysis:
    """优化成本收益分析"""

    def __init__(self, cost_model: Optional[CostModel] = None):
        self.cost_model = cost_model or CostModel()

    def analyze_pass(self, ir_module: IRModule, pass_name: str) -> dict[str, float]:
        """分析单个优化 pass 的成本和收益"""
        # 成本
        compile_time_cost = {
            "constant_folding": 0.1,
            "dead_code_elimination": 0.2,
            "loop_invariant_hoisting": 0.5,
            "cse": 0.4,
            "copy_propagation": 0.15,
            "strength_reduction": 0.2,
            "peephole": 0.1,
            "inlining": 1.0,
            "tail_call": 0.3,
        }

        # 收益
        benefit = self.cost_model.estimate_optimization_benefit(ir_module, pass_name)
        cost = compile_time_cost.get(pass_name, 0.5)

        return {
            "pass_name": pass_name,
            "compile_cost": cost,
            "runtime_benefit": benefit,
            "net_benefit": benefit - cost,
            "roi": benefit / cost if cost > 0 else 0,
        }

    def analyze_sequence(self, ir_module: IRModule, passes: list[str]) -> dict[str, Any]:
        """分析优化序列的成本和收益"""
        total_cost = 0.0
        total_benefit = 0.0
        pass_analyses = []

        for pass_name in passes:
            analysis = self.analyze_pass(ir_module, pass_name)
            pass_analyses.append(analysis)
            total_cost += analysis["compile_cost"]
            total_benefit += analysis["runtime_benefit"]

        return {
            "passes": pass_analyses,
            "total_cost": total_cost,
            "total_benefit": total_benefit,
            "net_benefit": total_benefit - total_cost,
            "roi": total_benefit / total_cost if total_cost > 0 else 0,
        }

    def recommend_passes(self, ir_module: IRModule, budget: float = 5.0) -> list[str]:
        """在预算内推荐最优优化 pass 组合"""
        available = ["constant_folding", "dead_code_elimination", "copy_propagation",
                     "cse", "strength_reduction", "peephole", "loop_invariant_hoisting",
                     "inlining", "tail_call"]

        # 计算每个 pass 的 ROI
        pass_roi = []
        for pass_name in available:
            analysis = self.analyze_pass(ir_module, pass_name)
            if analysis["roi"] > 0:
                pass_roi.append((pass_name, analysis["roi"], analysis["compile_cost"]))

        # 贪心选择
        pass_roi.sort(key=lambda x: x[1], reverse=True)
        selected = []
        total_cost = 0.0

        for pass_name, roi, cost in pass_roi:
            if total_cost + cost <= budget:
                selected.append(pass_name)
                total_cost += cost

        return selected


class BranchPredictor:
    """分支预测器（用于成本模型）"""

    def __init__(self):
        self._taken_count: dict[str, int] = {}
        self._not_taken_count: dict[str, int] = {}

    def record_branch(self, branch_id: str, taken: bool) -> None:
        """记录分支结果"""
        if taken:
            self._taken_count[branch_id] = self._taken_count.get(branch_id, 0) + 1
        else:
            self._not_taken_count[branch_id] = self._not_taken_count.get(branch_id, 0) + 1

    def predict_taken(self, branch_id: str) -> bool:
        """预测分支是否会被执行"""
        taken = self._taken_count.get(branch_id, 0)
        not_taken = self._not_taken_count.get(branch_id, 0)
        total = taken + not_taken
        if total == 0:
            return True  # 默认预测执行
        return taken > not_taken

    def accuracy(self) -> float:
        """计算预测准确率"""
        if not self._taken_count and not self._not_taken_count:
            return 1.0
        correct = 0
        total = 0
        for branch_id in set(list(self._taken_count.keys()) + list(self._not_taken_count.keys())):
            taken = self._taken_count.get(branch_id, 0)
            not_taken = self._not_taken_count.get(branch_id, 0)
            predicted_taken = taken > not_taken
            actual_taken = taken > not_taken
            if predicted_taken == actual_taken:
                correct += taken + not_taken
            total += taken + not_taken
        return correct / total if total > 0 else 1.0


class MemoryAccessPattern:
    """内存访问模式分析"""

    @staticmethod
    def analyze(ir_module: IRModule) -> dict[str, Any]:
        """分析内存访问模式"""
        load_count = 0
        store_count = 0
        sequential_access = 0
        random_access = 0

        for func in ir_module.functions.values():
            for block in func.blocks:
                for instr in block.instructions:
                    if instr.opcode == IROpcode.LOAD:
                        load_count += 1
                    elif instr.opcode == IROpcode.STORE:
                        store_count += 1
                    elif instr.opcode == IROpcode.GEP:
                        sequential_access += 1
                    elif instr.opcode == IROpcode.TENSOR_GET:
                        random_access += 1

        return {
            "load_count": load_count,
            "store_count": store_count,
            "sequential_access": sequential_access,
            "random_access": random_access,
            "locality_score": sequential_access / max(sequential_access + random_access, 1),
        }