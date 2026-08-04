"""
AI 编译器工具链 - AI 自动调优模块
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Optional, Any

from src.utils.errors import AITuningError, ErrorReporter
from src.utils.config import AITuningConfig


@dataclass
class OptimizationStep:
    """优化步骤"""
    name: str
    applied: bool = False
    cost: float = 0.0
    benefit: float = 0.0

    def __repr__(self) -> str:
        return f"Step({self.name}, cost={self.cost:.3f}, benefit={self.benefit:.3f})"


@dataclass
class OptimizationSequence:
    """优化序列"""
    steps: list[OptimizationStep] = field(default_factory=list)
    score: float = 0.0
    compile_time: float = 0.0
    code_size: int = 0
    performance: float = 0.0

    def add_step(self, step: OptimizationStep) -> None:
        """添加优化步骤"""
        self.steps.append(step)

    def total_cost(self) -> float:
        """计算总成本"""
        return sum(s.cost for s in self.steps if s.applied)

    def total_benefit(self) -> float:
        """计算总收益"""
        return sum(s.benefit for s in self.steps if s.applied)

    def net_benefit(self) -> float:
        """计算净收益"""
        return self.total_benefit() - self.total_cost()

    def __repr__(self) -> str:
        return f"Sequence({len(self.steps)} steps, score={self.score:.3f})"


class QLearningOptimizer:
    """Q-Learning 优化顺序学习器"""

    def __init__(self, config: AITuningConfig):
        self.config = config
        self.q_table: dict[tuple, float] = {}  # (state, action) -> Q value
        self.passes: list[str] = [
            "constant_folding", "dead_code_elimination", "copy_propagation",
            "cse", "strength_reduction", "peephole", "loop_invariant_hoisting",
            "inlining", "tail_call",
        ]
        self.learning_rate = config.learning_rate
        self.exploration_rate = config.exploration_rate
        self.discount_factor = config.discount_factor
        self._history: list[OptimizationSequence] = []

    def get_q_value(self, state: tuple, action: str) -> float:
        """获取 Q 值"""
        return self.q_table.get((state, action), 0.0)

    def set_q_value(self, state: tuple, action: str, value: float) -> None:
        """设置 Q 值"""
        self.q_table[(state, action)] = value

    def choose_action(self, state: tuple, available_actions: list[str]) -> str:
        """选择动作（epsilon-greedy）"""
        if random.random() < self.exploration_rate:
            return random.choice(available_actions)

        best_action = available_actions[0]
        best_value = self.get_q_value(state, best_action)
        for action in available_actions[1:]:
            value = self.get_q_value(state, action)
            if value > best_value:
                best_value = value
                best_action = action
        return best_action

    def update(self, state: tuple, action: str, reward: float, next_state: tuple) -> None:
        """更新 Q 值"""
        current_q = self.get_q_value(state, action)
        next_max = max(
            [self.get_q_value(next_state, a) for a in self.passes],
            default=0.0
        )
        new_q = current_q + self.learning_rate * (reward + self.discount_factor * next_max - current_q)
        self.set_q_value(state, action, new_q)

    def learn_optimal_sequence(self, iterations: int = 100) -> OptimizationSequence:
        """学习最优优化顺序"""
        best_sequence = OptimizationSequence()
        best_score = float('-inf')

        for iteration in range(iterations):
            state = self._encode_state([])
            available = list(self.passes)
            sequence = OptimizationSequence()

            for _ in range(len(self.passes)):
                if not available:
                    break
                action = self.choose_action(state, available)
                available.remove(action)

                # 模拟优化效果
                step = OptimizationStep(name=action, applied=True)
                step.cost = self._estimate_cost(action)
                step.benefit = self._estimate_benefit(action)
                sequence.add_step(step)

                next_state = self._encode_state([s.name for s in sequence.steps])
                reward = step.benefit - step.cost
                self.update(state, action, reward, next_state)
                state = next_state

            sequence.score = sequence.net_benefit()
            self._history.append(sequence)

            if sequence.score > best_score:
                best_score = sequence.score
                best_sequence = sequence

            self.exploration_rate *= 0.995  # 衰减探索率

        return best_sequence

    def _encode_state(self, applied: list[str]) -> tuple:
        """将已应用的优化编码为状态"""
        # 使用已应用优化的元组作为状态
        return tuple(sorted(applied))

    def _estimate_cost(self, pass_name: str) -> float:
        """估计优化 pass 的成本"""
        cost_map = {
            "constant_folding": 0.1,
            "dead_code_elimination": 0.2,
            "copy_propagation": 0.15,
            "cse": 0.5,
            "strength_reduction": 0.2,
            "peephole": 0.15,
            "loop_invariant_hoisting": 0.8,
            "inlining": 1.5,
            "tail_call": 0.3,
        }
        return cost_map.get(pass_name, 0.5)

    def _estimate_benefit(self, pass_name: str) -> float:
        """估计优化 pass 的收益"""
        benefit_map = {
            "constant_folding": 0.8,
            "dead_code_elimination": 1.0,
            "copy_propagation": 0.5,
            "cse": 1.2,
            "strength_reduction": 0.6,
            "peephole": 0.4,
            "loop_invariant_hoisting": 1.5,
            "inlining": 2.0,
            "tail_call": 0.5,
        }
        return benefit_map.get(pass_name, 0.5)

    def get_best_sequence(self) -> OptimizationSequence:
        """获取最佳优化顺序"""
        if self._history:
            return max(self._history, key=lambda s: s.score)
        return OptimizationSequence()

    def get_sequence_names(self) -> list[str]:
        """获取优化序列名称列表"""
        best = self.get_best_sequence()
        return [s.name for s in best.steps if s.applied]

    def save_model(self, path: str) -> None:
        """保存 Q 表"""
        data = {
            "q_table": {str(k): v for k, v in self.q_table.items()},
            "history": [self._sequence_to_dict(s) for s in self._history],
            "config": {
                "learning_rate": self.learning_rate,
                "exploration_rate": self.exploration_rate,
                "discount_factor": self.discount_factor,
            }
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_model(self, path: str) -> None:
        """加载 Q 表"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.q_table = {eval(k): v for k, v in data["q_table"].items()}
        self._history = [self._dict_to_sequence(s) for s in data.get("history", [])]

    def _sequence_to_dict(self, seq: OptimizationSequence) -> dict:
        return {
            "steps": [{"name": s.name, "applied": s.applied, "cost": s.cost, "benefit": s.benefit}
                      for s in seq.steps],
            "score": seq.score,
        }

    def _dict_to_sequence(self, d: dict) -> OptimizationSequence:
        seq = OptimizationSequence()
        for s in d["steps"]:
            seq.add_step(OptimizationStep(s["name"], s["applied"], s["cost"], s["benefit"]))
        seq.score = d["score"]
        return seq


class Autotuner:
    """AI 自动调优器"""

    def __init__(self, config: Optional[AITuningConfig] = None, error_reporter: Optional[ErrorReporter] = None):
        self.config = config or AITuningConfig()
        self.error_reporter = error_reporter or ErrorReporter()
        self.optimizer = QLearningOptimizer(self.config)
        self._trained: bool = False

    def tune(self, iterations: int = 100) -> OptimizationSequence:
        """执行自动调优"""
        if self.config.use_reinforcement_learning:
            best_sequence = self.optimizer.learn_optimal_sequence(iterations)
            self._trained = True
            return best_sequence
        return self._get_default_sequence()

    def get_optimal_passes(self) -> list[str]:
        """获取最优优化 pass 列表"""
        if not self._trained:
            self.tune(self.config.max_iterations)
        return self.optimizer.get_sequence_names()

    def _get_default_sequence(self) -> OptimizationSequence:
        """获取默认优化序列"""
        seq = OptimizationSequence()
        default_passes = ["constant_folding", "dead_code_elimination", "copy_propagation",
                          "cse", "strength_reduction", "peephole"]
        for name in default_passes:
            seq.add_step(OptimizationStep(name, True))
        seq.score = 1.0
        return seq

    def save(self, path: str) -> None:
        """保存调优模型"""
        self.optimizer.save_model(path)

    def load(self, path: str) -> None:
        """加载调优模型"""
        self.optimizer.load_model(path)
        self._trained = True

    def report(self) -> str:
        """生成调优报告"""
        lines = ["AI 自动调优报告:"]
        lines.append(f"  使用强化学习: {self.config.use_reinforcement_learning}")
        lines.append(f"  使用成本模型: {self.config.use_cost_model}")
        lines.append(f"  已训练: {self._trained}")

        if self._trained:
            best = self.optimizer.get_best_sequence()
            lines.append(f"  最优序列得分: {best.score:.4f}")
            lines.append(f"  优化顺序:")
            for i, step in enumerate(best.steps):
                if step.applied:
                    lines.append(f"    {i + 1}. {step.name} (成本={step.cost:.3f}, 收益={step.benefit:.3f})")

        return "\n".join(lines)


class NeuralNetwork:
    """简单神经网络（用于成本模型）"""

    def __init__(self, layers: list[int]):
        self.layers = layers
        self.weights: list[list[list[float]]] = []
        self.biases: list[list[float]] = []

        # 初始化权重
        for i in range(len(layers) - 1):
            layer_weights = []
            for _ in range(layers[i]):
                neuron_weights = [random.uniform(-0.5, 0.5) for _ in range(layers[i + 1])]
                layer_weights.append(neuron_weights)
            self.weights.append(layer_weights)
            self.biases.append([random.uniform(-0.5, 0.5) for _ in range(layers[i + 1])])

    def forward(self, inputs: list[float]) -> list[float]:
        """前向传播"""
        current = list(inputs)
        for layer_idx in range(len(self.weights)):
            next_layer = []
            for neuron_idx in range(len(self.weights[layer_idx][0])):
                total = self.biases[layer_idx][neuron_idx]
                for input_idx in range(len(current)):
                    total += current[input_idx] * self.weights[layer_idx][input_idx][neuron_idx]
                next_layer.append(self._sigmoid(total))
            current = next_layer
        return current

    def _sigmoid(self, x: float) -> float:
        """Sigmoid 激活函数"""
        try:
            return 1.0 / (1.0 + math.exp(-x))
        except OverflowError:
            return 0.0 if x < 0 else 1.0

    def train(self, inputs: list[list[float]], targets: list[list[float]], epochs: int = 100, lr: float = 0.01) -> None:
        """训练网络（简化梯度下降）"""
        for epoch in range(epochs):
            total_loss = 0.0
            for inp, target in zip(inputs, targets):
                output = self.forward(inp)
                # 计算损失 (MSE)
                loss = sum((o - t) ** 2 for o, t in zip(output, target)) / len(target)
                total_loss += loss

                # 简化反向传播
                for layer_idx in range(len(self.weights)):
                    for i in range(len(self.weights[layer_idx])):
                        for j in range(len(self.weights[layer_idx][i])):
                            grad = 2 * (output[j] - target[j]) * output[j] * (1 - output[j])
                            if layer_idx == 0:
                                grad *= inp[i]
                            self.weights[layer_idx][i][j] -= lr * grad
            if epoch % 10 == 0:
                avg_loss = total_loss / len(inputs)
                if avg_loss < 0.001:
                    break


class FeatureExtractor:
    """特征提取器 - 从代码中提取特征用于 AI 调优"""

    @staticmethod
    def extract_features(source_code: str) -> list[float]:
        """从源代码中提取特征"""
        features = []
        lines = source_code.split('\n')
        total_chars = len(source_code)

        # 基本特征
        features.append(len(lines) / 1000.0)  # 行数（归一化）
        features.append(total_chars / 10000.0)  # 字符数
        features.append(sum(1 for c in source_code if c == ';') / 100.0)  # 语句数
        features.append(sum(1 for c in source_code if c == '{') / 100.0)  # 块数
        features.append(sum(1 for c in source_code if c == '(') / 100.0)  # 调用数

        # 关键字计数
        keywords = ['fn', 'let', 'const', 'if', 'else', 'while', 'for', 'return', 'class', 'import']
        for kw in keywords:
            features.append(source_code.count(kw) / 50.0)

        # 嵌套深度估计
        max_depth = 0
        current_depth = 0
        for ch in source_code:
            if ch == '{':
                current_depth += 1
                max_depth = max(max_depth, current_depth)
            elif ch == '}':
                current_depth -= 1
        features.append(max_depth / 10.0)

        # 操作符密度
        operators = ['+', '-', '*', '/', '=', '<', '>', '&', '|', '!']
        op_count = sum(source_code.count(op) for op in operators)
        features.append(op_count / 500.0 if total_chars > 0 else 0)

        # 数字和字符串密度
        num_count = sum(1 for c in source_code if c.isdigit())
        features.append(num_count / 500.0)
        str_count = source_code.count('"') / 2
        features.append(str_count / 50.0)

        return features

    @staticmethod
    def extract_ir_features(ir_module: Any) -> list[float]:
        """从 IR 中提取特征"""
        features = []
        try:
            func_count = len(ir_module.functions)
            block_count = sum(len(f.blocks) for f in ir_module.functions.values())
            instr_count = sum(
                len(instr) for f in ir_module.functions.values()
                for b in f.blocks for instr in b.instructions
            )

            features.append(func_count / 20.0)
            features.append(block_count / 100.0)
            features.append(instr_count / 500.0)

            branches = sum(
                1 for f in ir_module.functions.values()
                for b in f.blocks for instr in b.instructions
                if instr.opcode.name in ('IF_GOTO', 'GOTO')
            )
            features.append(branches / 100.0)

            loads = sum(
                1 for f in ir_module.functions.values()
                for b in f.blocks for instr in b.instructions
                if instr.opcode.name == 'LOAD'
            )
            stores = sum(
                1 for f in ir_module.functions.values()
                for b in f.blocks for instr in b.instructions
                if instr.opcode.name == 'STORE'
            )
            features.append(loads / 100.0)
            features.append(stores / 100.0)

            calls = sum(
                1 for f in ir_module.functions.values()
                for b in f.blocks for instr in b.instructions
                if instr.opcode.name == 'CALL'
            )
            features.append(calls / 50.0)

        except Exception:
            features = [0.0] * 8

        return features


class OptimizationRecommender:
    """优化推荐器"""

    def __init__(self):
        self.model = NeuralNetwork([16, 32, 9])  # 9 种优化 pass
        self._trained = False

    def recommend(self, features: list[float]) -> list[tuple[str, float]]:
        """推荐优化 pass 及其置信度"""
        if not self._trained:
            return self._default_recommendations()

        outputs = self.model.forward(features)
        pass_names = [
            "constant_folding", "dead_code_elimination", "copy_propagation",
            "cse", "strength_reduction", "peephole", "loop_invariant_hoisting",
            "inlining", "tail_call",
        ]
        recommendations = list(zip(pass_names, outputs))
        recommendations.sort(key=lambda x: x[1], reverse=True)
        return recommendations

    def _default_recommendations(self) -> list[tuple[str, float]]:
        """默认推荐"""
        defaults = [
            ("constant_folding", 0.9), ("dead_code_elimination", 0.85),
            ("copy_propagation", 0.7), ("cse", 0.6),
            ("strength_reduction", 0.65), ("peephole", 0.5),
            ("loop_invariant_hoisting", 0.4), ("inlining", 0.2),
            ("tail_call", 0.1),
        ]
        return defaults

    def train(self, samples: list[tuple[list[float], list[float]]]) -> None:
        """训练推荐模型"""
        inputs = [s[0] for s in samples]
        targets = [s[1] for s in samples]
        self.model.train(inputs, targets, epochs=200)
        self._trained = True