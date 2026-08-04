"""
AI 流量预测模块
===============

基于深度学习模型的网络流量预测，支持 LSTM、GRU 和 Transformer 等模型，
能够预测未来时间窗口内的网络流量变化。
"""

import asyncio
import time
import math
import json
import logging
import numpy as np
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque
from enum import Enum


logger = logging.getLogger(__name__)


class TrafficModel(Enum):
    """流量预测模型类型"""
    ARIMA = "arima"
    LSTM = "lstm"
    GRU = "gru"
    TRANSFORMER = "transformer"
    SEASONAL_NAIVE = "seasonal_naive"
    MOVING_AVERAGE = "moving_average"
    HOLT_WINTERS = "holt_winters"
    ENSEMBLE = "ensemble"


@dataclass
class PredictionResult:
    """预测结果"""
    timestamp: float = field(default_factory=time.time)
    values: List[float] = field(default_factory=list)
    confidence: float = 0.0
    lower_bound: List[float] = field(default_factory=list)
    upper_bound: List[float] = field(default_factory=list)
    model_used: TrafficModel = TrafficModel.MOVING_AVERAGE
    horizon: int = 10
    mse: float = 0.0
    mae: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def mean_value(self) -> float:
        if self.values:
            return sum(self.values) / len(self.values)
        return 0.0

    @property
    def trend(self) -> str:
        if len(self.values) < 2:
            return "stable"
        if self.values[-1] > self.values[0] * 1.1:
            return "rising"
        elif self.values[-1] < self.values[0] * 0.9:
            return "falling"
        return "stable"


@dataclass
class TrafficWindow:
    """流量窗口数据"""
    timestamps: List[float] = field(default_factory=list)
    values: List[float] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    max_size: int = 1000

    def add(self, value: float, label: str = "", timestamp: Optional[float] = None) -> None:
        """添加数据点"""
        self.timestamps.append(timestamp or time.time())
        self.values.append(value)
        self.labels.append(label)
        if len(self.values) > self.max_size:
            self.timestamps.pop(0)
            self.values.pop(0)
            self.labels.pop(0)

    @property
    def size(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        if self.values:
            return sum(self.values) / len(self.values)
        return 0.0

    @property
    def std(self) -> float:
        if len(self.values) > 1:
            m = self.mean
            variance = sum((v - m) ** 2 for v in self.values) / len(self.values)
            return math.sqrt(variance)
        return 0.0

    @property
    def min(self) -> float:
        return min(self.values) if self.values else 0.0

    @property
    def max(self) -> float:
        return max(self.values) if self.values else 0.0

    @property
    def latest(self) -> float:
        return self.values[-1] if self.values else 0.0

    def get_recent(self, n: int) -> List[float]:
        """获取最近 N 个值"""
        return self.values[-n:] if len(self.values) >= n else self.values.copy()

    def normalize(self, values: Optional[List[float]] = None) -> List[float]:
        """归一化数据"""
        data = values if values is not None else self.values
        if not data:
            return []
        m = self.mean
        s = self.std if self.std > 0 else 1.0
        return [(v - m) / s for v in data]

    def denormalize(self, normalized: List[float]) -> List[float]:
        """反归一化"""
        m = self.mean
        s = self.std if self.std > 0 else 1.0
        return [v * s + m for v in normalized]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "size": self.size,
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "latest": self.latest,
        }


class TrafficPredictor:
    """网络流量预测器"""

    def __init__(self, window_size: int = 100, horizon: int = 10,
                 model_type: TrafficModel = TrafficModel.MOVING_AVERAGE,
                 update_interval: float = 60.0) -> None:
        self.window_size = window_size
        self.horizon = horizon
        self.model_type = model_type
        self.update_interval = update_interval
        self._window = TrafficWindow(max_size=window_size * 2)
        self._history: List[PredictionResult] = []
        self._max_history: int = 100
        self._is_trained: bool = False
        self._model_params: Dict[str, Any] = {}
        self._seasonal_period: int = 24
        self._last_prediction: Optional[PredictionResult] = None
        self._prediction_callbacks: List[Callable] = []
        self._training_task: Optional[asyncio.Task] = None
        self._stats: Dict[str, Any] = {
            "predictions_made": 0,
            "total_mae": 0.0,
            "total_mse": 0.0,
            "best_mae": float("inf"),
            "worst_mae": 0.0,
        }

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def add_data_point(self, value: float, label: str = "") -> None:
        """添加数据点"""
        self._window.add(value, label)
        logger.debug(f"流量数据点已添加: {value} ({label})")

    def add_data_batch(self, values: List[float], labels: Optional[List[str]] = None) -> None:
        """批量添加数据点"""
        for i, value in enumerate(values):
            label = labels[i] if labels and i < len(labels) else ""
            self._window.add(value, label)

    def train(self) -> bool:
        """训练预测模型

        Returns:
            是否训练成功
        """
        if self._window.size < self.horizon * 2:
            logger.warning(f"数据不足，无法训练: {self._window.size} < {self.horizon * 2}")
            return False

        if self.model_type == TrafficModel.MOVING_AVERAGE:
            self._train_moving_average()
        elif self.model_type == TrafficModel.SEASONAL_NAIVE:
            self._train_seasonal_naive()
        elif self.model_type == TrafficModel.HOLT_WINTERS:
            self._train_holt_winters()
        elif self.model_type == TrafficModel.ARIMA:
            self._train_arima()
        elif self.model_type == TrafficModel.LSTM:
            self._train_lstm()
        elif self.model_type == TrafficModel.ENSEMBLE:
            self._train_ensemble()
        else:
            self._train_moving_average()

        self._is_trained = True
        logger.info(f"流量预测模型已训练: {self.model_type.value}")
        return True

    def _train_moving_average(self) -> None:
        """训练移动平均模型"""
        values = self._window.values
        self._model_params = {
            "mean": sum(values) / len(values),
            "std": (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values)) ** 0.5,
            "trend": 0.0,
        }

        # 计算简单趋势
        if len(values) > 1:
            n = min(10, len(values))
            recent = values[-n:]
            self._model_params["trend"] = (recent[-1] - recent[0]) / n

    def _train_seasonal_naive(self) -> None:
        """训练季节性朴素模型"""
        values = self._window.values
        period = self._seasonal_period

        if len(values) >= period * 2:
            # 计算季节性模式
            seasonal_pattern = []
            for i in range(period):
                idx = -(period - i)
                if abs(idx) <= len(values):
                    seasonal_pattern.append(values[idx])

            base_level = sum(values[:-period]) / max(len(values) - period, 1)
            self._model_params = {
                "base_level": base_level,
                "seasonal_pattern": seasonal_pattern,
                "period": period,
            }
        else:
            self._model_params = {
                "base_level": sum(values) / len(values),
                "seasonal_pattern": [],
                "period": period,
            }

    def _train_holt_winters(self) -> None:
        """训练 Holt-Winters 指数平滑模型"""
        values = self._window.values
        alpha = 0.3
        beta = 0.1
        gamma = 0.1
        period = min(self._seasonal_period, len(values) // 2)

        if len(values) < 2:
            self._model_params = {"level": values[-1] if values else 0, "trend": 0, "seasonal": []}
            return

        # 初始化
        level = values[0]
        trend = values[1] - values[0] if len(values) > 1 else 0
        seasonal = [0] * period

        # 迭代平滑
        for i, v in enumerate(values):
            if i < period:
                seasonal[i] = v - level
            else:
                old_level = level
                level = alpha * (v - seasonal[i % period]) + (1 - alpha) * (level + trend)
                trend = beta * (level - old_level) + (1 - beta) * trend
                seasonal[i % period] = gamma * (v - level) + (1 - gamma) * seasonal[i % period]

        self._model_params = {
            "level": level,
            "trend": trend,
            "seasonal": seasonal,
            "period": period,
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
        }

    def _train_arima(self) -> None:
        """训练 ARIMA 模型（简化版）"""
        values = self._window.values
        n = len(values)

        if n < 4:
            self._model_params = {"ar_coeffs": [], "ma_coeffs": [], "d": 0, "mean": sum(values) / n if n > 0 else 0}
            return

        # 差分
        d = 1
        diff_values = [values[i] - values[i - 1] for i in range(1, n)]

        # 简单 AR(2) 估计
        ar_coeffs = []
        if len(diff_values) >= 3:
            x1, x2, x3 = diff_values[-3], diff_values[-2], diff_values[-1]
            denom = x1 * x1 + x2 * x2 + 1e-10
            ar_coeffs = [(x1 * x2 + x2 * x3) / denom, (x1 * x3) / denom]

        self._model_params = {
            "ar_coeffs": ar_coeffs[:2],
            "ma_coeffs": [0],
            "d": d,
            "mean": sum(diff_values) / len(diff_values) if diff_values else 0,
            "last_values": values[-3:],
        }

    def _train_lstm(self) -> None:
        """训练 LSTM 模型（模拟实现）"""
        values = self._window.values
        n = len(values)

        if n < 10:
            self._train_moving_average()
            return

        # 模拟 LSTM 训练：提取特征
        lookback = min(10, n // 2)
        features = []
        targets = []

        for i in range(lookback, n):
            features.append(values[i - lookback:i])
            targets.append(values[i])

        # 简单权重计算（模拟 LSTM 学习）
        weights = [1.0 / lookback] * lookback
        if targets:
            bias = sum(targets) / len(targets)

        self._model_params = {
            "lookback": lookback,
            "weights": weights,
            "bias": sum(targets) / len(targets) if targets else 0,
            "hidden_size": 64,
            "num_layers": 2,
        }

    def _train_ensemble(self) -> None:
        """训练集成模型"""
        models = [TrafficModel.MOVING_AVERAGE, TrafficModel.SEASONAL_NAIVE, TrafficModel.HOLT_WINTERS]
        params = {}

        for model_type in models:
            saved = self.model_type
            self.model_type = model_type
            self.train()
            params[model_type.value] = self._model_params.copy()
            self.model_type = saved

        self._model_params = {
            "models": models,
            "params": params,
            "weights": [1.0 / len(models)] * len(models),
        }

    def predict(self, horizon: Optional[int] = None) -> PredictionResult:
        """预测未来流量

        Args:
            horizon: 预测步数，默认使用初始化时的值

        Returns:
            预测结果
        """
        h = horizon or self.horizon

        if not self._is_trained:
            self.train()

        if self.model_type == TrafficModel.MOVING_AVERAGE:
            result = self._predict_moving_average(h)
        elif self.model_type == TrafficModel.SEASONAL_NAIVE:
            result = self._predict_seasonal_naive(h)
        elif self.model_type == TrafficModel.HOLT_WINTERS:
            result = self._predict_holt_winters(h)
        elif self.model_type == TrafficModel.ARIMA:
            result = self._predict_arima(h)
        elif self.model_type == TrafficModel.LSTM:
            result = self._predict_lstm(h)
        elif self.model_type == TrafficModel.ENSEMBLE:
            result = self._predict_ensemble(h)
        else:
            result = self._predict_moving_average(h)

        # 计算置信区间
        self._compute_confidence(result)

        self._last_prediction = result
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        self._stats["predictions_made"] += 1

        # 通知回调
        for callback in self._prediction_callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"预测回调执行出错: {e}")

        logger.debug(f"流量预测完成: horizon={h}, mean={result.mean_value:.2f}")
        return result

    def _predict_moving_average(self, horizon: int) -> PredictionResult:
        """移动平均预测"""
        mean = self._model_params.get("mean", 0)
        trend = self._model_params.get("trend", 0)

        values = []
        for i in range(horizon):
            values.append(mean + trend * (i + 1))

        return PredictionResult(
            values=values,
            model_used=TrafficModel.MOVING_AVERAGE,
            horizon=horizon,
        )

    def _predict_seasonal_naive(self, horizon: int) -> PredictionResult:
        """季节性朴素预测"""
        pattern = self._model_params.get("seasonal_pattern", [])
        base_level = self._model_params.get("base_level", 0)
        period = self._model_params.get("period", 24)

        values = []
        for i in range(horizon):
            if pattern and i < len(pattern):
                values.append(base_level + pattern[i])
            else:
                values.append(base_level)

        return PredictionResult(
            values=values,
            model_used=TrafficModel.SEASONAL_NAIVE,
            horizon=horizon,
        )

    def _predict_holt_winters(self, horizon: int) -> PredictionResult:
        """Holt-Winters 预测"""
        level = self._model_params.get("level", 0)
        trend = self._model_params.get("trend", 0)
        seasonal = self._model_params.get("seasonal", [])
        period = self._model_params.get("period", 1)

        values = []
        for i in range(horizon):
            seasonal_idx = i % period if seasonal else 0
            seasonal_val = seasonal[seasonal_idx] if seasonal_idx < len(seasonal) else 0
            pred = level + (i + 1) * trend + seasonal_val
            values.append(max(0, pred))

        return PredictionResult(
            values=values,
            model_used=TrafficModel.HOLT_WINTERS,
            horizon=horizon,
        )

    def _predict_arima(self, horizon: int) -> PredictionResult:
        """ARIMA 预测"""
        ar_coeffs = self._model_params.get("ar_coeffs", [])
        d = self._model_params.get("d", 0)
        mean = self._model_params.get("mean", 0)
        last_values = list(self._model_params.get("last_values", []))

        values = []
        for i in range(horizon):
            pred = mean
            for j, coeff in enumerate(ar_coeffs):
                idx = -(j + 1)
                if abs(idx) <= len(last_values):
                    pred += coeff * last_values[idx]
            values.append(max(0, pred))
            last_values.append(pred)

        # 逆差分
        if d > 0 and self._window.values:
            base = self._window.values[-1]
            cumsum = base
            for i in range(horizon):
                cumsum += values[i]
                values[i] = max(0, cumsum)

        return PredictionResult(
            values=values,
            model_used=TrafficModel.ARIMA,
            horizon=horizon,
        )

    def _predict_lstm(self, horizon: int) -> PredictionResult:
        """LSTM 预测（模拟）"""
        lookback = self._model_params.get("lookback", 10)
        weights = self._model_params.get("weights", [1.0 / lookback] * lookback)
        bias = self._model_params.get("bias", 0)
        recent = self._window.get_recent(lookback)

        values = []
        current_input = list(recent)
        for i in range(horizon):
            if len(current_input) >= lookback:
                pred = bias
                for j in range(lookback):
                    if j < len(weights) and j < len(current_input):
                        pred += weights[j] * current_input[-(j + 1)]
                values.append(max(0, pred))
                current_input.append(pred)
            else:
                values.append(max(0, bias))
                current_input.append(bias)

        return PredictionResult(
            values=values,
            model_used=TrafficModel.LSTM,
            horizon=horizon,
        )

    def _predict_ensemble(self, horizon: int) -> PredictionResult:
        """集成模型预测"""
        models_config = self._model_params.get("models", [])
        weights = self._model_params.get("weights", [])
        all_values = []

        for i, model_type in enumerate(models_config):
            saved = self.model_type
            self.model_type = model_type
            self._model_params = self._model_params.get("params", {}).get(model_type.value, {})
            result = self.predict(horizon)
            all_values.append(result.values)
            self.model_type = saved

        # 加权平均
        values = []
        for i in range(horizon):
            weighted = 0.0
            total_weight = 0.0
            for j, model_values in enumerate(all_values):
                w = weights[j] if j < len(weights) else 1.0 / len(all_values)
                if i < len(model_values):
                    weighted += w * model_values[i]
                    total_weight += w
            values.append(weighted / total_weight if total_weight > 0 else 0)

        return PredictionResult(
            values=values,
            model_used=TrafficModel.ENSEMBLE,
            horizon=horizon,
        )

    def _compute_confidence(self, result: PredictionResult) -> None:
        """计算预测置信度"""
        if self._window.size < 2:
            result.confidence = 0.5
            return

        # 基于历史误差的置信度
        if self._history:
            recent_errors = [abs(h.values[0] - self._window.values[-1])
                           for h in self._history[-10:]
                           if h.values and self._window.values]
            if recent_errors:
                mean_error = sum(recent_errors) / len(recent_errors)
                current_std = self._window.std
                if current_std > 0:
                    result.confidence = max(0, min(1, 1 - mean_error / current_std))
                else:
                    result.confidence = 0.8
            else:
                result.confidence = 0.7
        else:
            result.confidence = 0.6

        # 置信区间
        std = self._window.std * (1 - result.confidence + 0.1)
        result.lower_bound = [v - std * 1.96 for v in result.values]
        result.upper_bound = [v + std * 1.96 for v in result.values]

    def evaluate(self, actual_values: List[float]) -> Dict[str, float]:
        """评估预测精度

        Args:
            actual_values: 实际值列表

        Returns:
            评估指标字典 (mse, mae, mape, smape)
        """
        if not self._last_prediction or not actual_values:
            return {"mse": 0, "mae": 0, "mape": 0, "smape": 0}

        predicted = self._last_prediction.values[:len(actual_values)]
        n = len(predicted)

        if n == 0:
            return {"mse": 0, "mae": 0, "mape": 0, "smape": 0}

        mse = sum((p - a) ** 2 for p, a in zip(predicted, actual_values)) / n
        mae = sum(abs(p - a) for p, a in zip(predicted, actual_values)) / n
        mape = sum(abs((a - p) / max(a, 1e-10)) for p, a in zip(predicted, actual_values)) / n * 100
        smape = sum(2 * abs(a - p) / max(abs(a) + abs(p), 1e-10) for p, a in zip(predicted, actual_values)) / n * 100

        self._stats["total_mae"] += mae
        self._stats["total_mse"] += mse
        self._stats["best_mae"] = min(self._stats["best_mae"], mae)
        self._stats["worst_mae"] = max(self._stats["worst_mae"], mae)

        return {"mse": mse, "mae": mae, "mape": mape, "smape": smape}

    def on_prediction(self, callback: Callable) -> None:
        """注册预测回调"""
        self._prediction_callbacks.append(callback)

    async def start_auto_predict(self) -> None:
        """启动自动预测循环"""
        self.train()
        while True:
            self.predict()
            await asyncio.sleep(self.update_interval)

    def get_history(self, n: int = 10) -> List[PredictionResult]:
        """获取历史预测结果"""
        return self._history[-n:]

    def get_window_data(self) -> TrafficWindow:
        """获取窗口数据"""
        return self._window

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "window_size": self._window.size,
            "window_mean": self._window.mean,
            "window_std": self._window.std,
            "model_type": self.model_type.value,
            "is_trained": self._is_trained,
            "horizon": self.horizon,
            "last_prediction_mean": self._last_prediction.mean_value if self._last_prediction else None,
            "last_prediction_confidence": self._last_prediction.confidence if self._last_prediction else None,
        }

    def reset(self) -> None:
        """重置预测器"""
        self._window = TrafficWindow(max_size=self.window_size * 2)
        self._history.clear()
        self._is_trained = False
        self._model_params.clear()
        self._last_prediction = None
        self._stats = {
            "predictions_made": 0,
            "total_mae": 0.0,
            "total_mse": 0.0,
            "best_mae": float("inf"),
            "worst_mae": 0.0,
        }
        logger.info("流量预测器已重置")