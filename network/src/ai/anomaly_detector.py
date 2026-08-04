"""
AI 异常检测模块
==============

基于机器学习的网络异常检测系统，支持多种检测算法，包括
Isolation Forest、One-Class SVM、LSTM 自编码器和统计方法。
"""

import time
import math
import random
import logging
from typing import Optional, Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque, defaultdict


logger = logging.getLogger(__name__)


class DetectionModel(Enum):
    """异常检测模型"""
    STATISTICAL = "statistical"
    ISOLATION_FOREST = "isolation_forest"
    ONE_CLASS_SVM = "one_class_svm"
    LSTM_AE = "lstm_ae"
    MOVING_AVERAGE = "moving_average"
    ENSEMBLE = "ensemble"


class AnomalyType(Enum):
    """异常类型"""
    TRAFFIC_SURGE = "traffic_surge"
    TRAFFIC_DROP = "traffic_drop"
    PORT_SCAN = "port_scan"
    DDOS = "ddos"
    LATENCY_SPIKE = "latency_spike"
    PACKET_LOSS = "packet_loss"
    PROTOCOL_ERROR = "protocol_error"
    AUTH_FAILURE = "auth_failure"
    BANDWIDTH_EXHAUST = "bandwidth_exhaust"
    CONNECTION_FLOOD = "connection_flood"
    DNS_ANOMALY = "dns_anomaly"
    UNKNOWN = "unknown"


@dataclass
class AnomalyScore:
    """异常分数"""
    score: float = 0.0
    threshold: float = 0.7
    is_anomaly: bool = False
    severity: str = "info"
    confidence: float = 0.0

    def __post_init__(self) -> None:
        self.is_anomaly = self.score >= self.threshold
        if self.score >= 0.9:
            self.severity = "critical"
        elif self.score >= 0.8:
            self.severity = "high"
        elif self.score >= self.threshold:
            self.severity = "medium"
        else:
            self.severity = "info"


@dataclass
class AnomalyReport:
    """异常报告"""
    timestamp: float = field(default_factory=time.time)
    anomaly_type: AnomalyType = AnomalyType.UNKNOWN
    score: AnomalyScore = field(default_factory=AnomalyScore)
    source: str = ""
    destination: str = ""
    protocol: str = ""
    port: int = 0
    description: str = ""
    features: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[float] = None
    resolution: str = ""

    @property
    def age(self) -> float:
        if self.resolved_at:
            return self.resolved_at - self.timestamp
        return time.time() - self.timestamp

    @property
    def severity(self) -> str:
        return self.score.severity

    def resolve(self, resolution: str = "") -> None:
        """标记为已解决"""
        self.resolved = True
        self.resolved_at = time.time()
        self.resolution = resolution


@dataclass
class FeatureVector:
    """特征向量"""
    features: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    label: Optional[str] = None

    @property
    def as_array(self) -> List[float]:
        return list(self.features.values())

    @property
    def feature_names(self) -> List[str]:
        return list(self.features.keys())

    def __len__(self) -> int:
        return len(self.features)


class AIAnomalyDetector:
    """AI 异常检测器"""

    _DEFAULT_FEATURES = [
        "packet_rate", "byte_rate", "flow_count",
        "tcp_syn_rate", "tcp_error_rate", "icmp_rate",
        "dns_rate", "avg_packet_size", "unique_ports",
        "unique_destinations", "connection_rate",
        "avg_rtt", "loss_rate", "bandwidth_usage",
        "new_connections_rate", "fin_rate", "rst_rate",
    ]

    def __init__(self, model: DetectionModel = DetectionModel.ISOLATION_FOREST,
                 threshold: float = 0.7,
                 sensitivity: float = 0.6,
                 update_interval: float = 5.0) -> None:
        self.model = model
        self.threshold = threshold
        self.sensitivity = sensitivity
        self.update_interval = update_interval
        self._feature_history: List[FeatureVector] = []
        self._max_history: int = 10000
        self._baseline: Dict[str, float] = {}
        self._baseline_std: Dict[str, float] = {}
        self._is_trained: bool = False
        self._current_features: FeatureVector = FeatureVector()
        self._alerts: List[AnomalyReport] = []
        self._max_alerts: int = 1000
        self._active_alerts: List[AnomalyReport] = []
        self._last_update: float = 0.0
        self._alert_callbacks: List[Any] = []
        self._resolution_callbacks: List[Any] = []
        self._stats: Dict[str, Any] = {
            "detections": 0,
            "false_positives": 0,
            "true_positives": 0,
            "avg_detection_time": 0.0,
            "total_alerts": 0,
            "active_alerts": 0,
            "resolved_alerts": 0,
        }

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    @property
    def alerts(self) -> List[AnomalyReport]:
        return self._alerts.copy()

    @property
    def active_alerts(self) -> List[AnomalyReport]:
        return self._active_alerts.copy()

    def update_features(self, features: Dict[str, float]) -> None:
        """更新特征数据

        Args:
            features: 特征字典
        """
        vector = FeatureVector(features=features)
        self._current_features = vector
        self._feature_history.append(vector)

        if len(self._feature_history) > self._max_history:
            self._feature_history.pop(0)

    def add_feature(self, name: str, value: float) -> None:
        """添加单个特征"""
        self._current_features.features[name] = value

    def train(self) -> bool:
        """训练检测模型

        Returns:
            是否训练成功
        """
        if len(self._feature_history) < 10:
            logger.warning(f"数据不足，无法训练: {len(self._feature_history)} < 10")
            return False

        if self.model == DetectionModel.STATISTICAL:
            self._train_statistical()
        elif self.model == DetectionModel.MOVING_AVERAGE:
            self._train_moving_average()
        elif self.model == DetectionModel.ISOLATION_FOREST:
            self._train_isolation_forest()
        elif self.model == DetectionModel.ONE_CLASS_SVM:
            self._train_one_class_svm()
        elif self.model == DetectionModel.LSTM_AE:
            self._train_lstm_ae()
        elif self.model == DetectionModel.ENSEMBLE:
            self._train_ensemble()

        self._is_trained = True
        logger.info(f"异常检测模型已训练: {self.model.value}")
        return True

    def _train_statistical(self) -> None:
        """训练统计模型"""
        all_features = self._collect_features()

        for name, values in all_features.items():
            if values:
                self._baseline[name] = sum(values) / len(values)
                variance = sum((v - self._baseline[name]) ** 2 for v in values) / len(values)
                self._baseline_std[name] = math.sqrt(variance) if variance > 0 else 1e-10

    def _train_moving_average(self) -> None:
        """训练移动平均模型"""
        self._train_statistical()

    def _train_isolation_forest(self) -> None:
        """训练 Isolation Forest 模型（模拟）"""
        all_features = self._collect_features()

        self._baseline = {}
        self._baseline_std = {}
        for name, values in all_features.items():
            if values:
                self._baseline[name] = sum(values) / len(values)
                variance = sum((v - self._baseline[name]) ** 2 for v in values) / len(values)
                self._baseline_std[name] = math.sqrt(variance) if variance > 0 else 1e-10

        # 模拟 Isolation Forest 参数
        self._forest_params = {
            "n_trees": 100,
            "max_depth": int(math.log2(len(self._feature_history))),
            "anomaly_threshold": 0.5,
        }

    def _train_one_class_svm(self) -> None:
        """训练 One-Class SVM 模型（模拟）"""
        self._train_statistical()
        self._svm_params = {
            "nu": 0.1,
            "gamma": 0.01,
            "kernel": "rbf",
            "support_vectors": 100,
        }

    def _train_lstm_ae(self) -> None:
        """训练 LSTM 自编码器模型（模拟）"""
        self._train_statistical()
        self._lstm_params = {
            "sequence_length": 10,
            "encoding_dim": 16,
            "reconstruction_error": 0.1,
        }

    def _train_ensemble(self) -> None:
        """训练集成模型"""
        self._train_statistical()
        self._train_isolation_forest()
        self._forest_params["weight"] = 0.4
        self._svm_params = {"weight": 0.3}
        self._lstm_params = {"weight": 0.3}

    def _collect_features(self) -> Dict[str, List[float]]:
        """收集所有特征值"""
        all_features: Dict[str, List[float]] = defaultdict(list)
        for vector in self._feature_history:
            for name, value in vector.features.items():
                all_features[name].append(value)
        return all_features

    def detect(self) -> Optional[AnomalyReport]:
        """执行异常检测

        Returns:
            如果检测到异常返回报告，否则返回 None
        """
        now = time.time()
        if now - self._last_update < self.update_interval:
            return None

        self._last_update = now

        if not self._is_trained:
            self.train()

        if not self._is_trained:
            return None

        features = self._current_features
        if not features.features:
            return None

        if self.model == DetectionModel.STATISTICAL:
            score = self._detect_statistical(features)
        elif self.model == DetectionModel.MOVING_AVERAGE:
            score = self._detect_moving_average(features)
        elif self.model == DetectionModel.ISOLATION_FOREST:
            score = self._detect_isolation_forest(features)
        elif self.model == DetectionModel.ONE_CLASS_SVM:
            score = self._detect_one_class_svm(features)
        elif self.model == DetectionModel.LSTM_AE:
            score = self._detect_lstm_ae(features)
        elif self.model == DetectionModel.ENSEMBLE:
            score = self._detect_ensemble(features)
        else:
            score = self._detect_statistical(features)

        if score.is_anomaly:
            anomaly_type = self._classify_anomaly(features)
            report = AnomalyReport(
                anomaly_type=anomaly_type,
                score=score,
                features=features.features,
                description=self._generate_description(anomaly_type, score),
            )

            self._alerts.append(report)
            self._active_alerts.append(report)
            if len(self._alerts) > self._max_alerts:
                self._alerts.pop(0)

            self._stats["detections"] += 1
            self._stats["total_alerts"] += 1
            self._stats["active_alerts"] = len(self._active_alerts)

            # 通知回调
            for callback in self._alert_callbacks:
                try:
                    callback(report)
                except Exception as e:
                    logger.error(f"告警回调执行出错: {e}")

            logger.warning(f"检测到异常: {anomaly_type.value} (score={score.score:.3f})")
            return report

        return None

    def _detect_statistical(self, features: FeatureVector) -> AnomalyScore:
        """统计方法检测"""
        max_deviation = 0.0
        total_deviation = 0.0
        feature_count = 0

        for name, value in features.features.items():
            if name in self._baseline and name in self._baseline_std:
                baseline = self._baseline[name]
                std = self._baseline_std[name]
                if std > 0:
                    z_score = abs(value - baseline) / std
                    total_deviation += z_score
                    feature_count += 1
                    max_deviation = max(max_deviation, z_score)

        if feature_count == 0:
            return AnomalyScore(score=0.0, threshold=self.threshold)

        avg_deviation = total_deviation / feature_count
        weighted_score = min(1.0, (max_deviation * 0.6 + avg_deviation * 0.4) / 10.0)
        confidence = min(1.0, feature_count / len(self._DEFAULT_FEATURES))

        return AnomalyScore(
            score=weighted_score,
            threshold=self.threshold,
            confidence=confidence,
        )

    def _detect_moving_average(self, features: FeatureVector) -> AnomalyScore:
        """移动平均检测"""
        return self._detect_statistical(features)

    def _detect_isolation_forest(self, features: FeatureVector) -> AnomalyScore:
        """Isolation Forest 检测（模拟）"""
        statistical_score = self._detect_statistical(features)

        # 模拟隔离森林的异常分数
        anomaly_score = 0.0
        feature_array = list(features.features.values())
        if feature_array:
            # 随机选择一些特征进行隔离
            n_features = len(feature_array)
            path_length = math.log2(n_features) if n_features > 0 else 0
            # 异常点路径较短
            anomaly_score = 1.0 - (path_length / max(self._forest_params.get("max_depth", 10), 1))

        combined = statistical_score.score * 0.3 + anomaly_score * 0.7
        return AnomalyScore(
            score=combined,
            threshold=self.threshold,
            confidence=0.7 + statistical_score.confidence * 0.3,
        )

    def _detect_one_class_svm(self, features: FeatureVector) -> AnomalyScore:
        """One-Class SVM 检测（模拟）"""
        statistical_score = self._detect_statistical(features)
        # 模拟 SVM 决策
        svm_score = min(1.0, statistical_score.score * 1.2)
        return AnomalyScore(
            score=svm_score,
            threshold=self.threshold,
            confidence=statistical_score.confidence * 0.8,
        )

    def _detect_lstm_ae(self, features: FeatureVector) -> AnomalyScore:
        """LSTM 自编码器检测（模拟）"""
        statistical_score = self._detect_statistical(features)
        # 模拟重建误差
        reconstruction_error = statistical_score.score * 0.8 + 0.1
        return AnomalyScore(
            score=min(1.0, reconstruction_error),
            threshold=self.threshold,
            confidence=statistical_score.confidence * 0.9,
        )

    def _detect_ensemble(self, features: FeatureVector) -> AnomalyScore:
        """集成检测"""
        scores = [
            self._detect_statistical(features),
            self._detect_isolation_forest(features),
        ]

        # 加权平均
        total_score = 0.0
        total_weight = 0.0
        weights = [0.3, 0.7]
        for i, s in enumerate(scores):
            w = weights[i] if i < len(weights) else 1.0 / len(scores)
            total_score += w * s.score
            total_weight += w

        avg_score = total_score / total_weight if total_weight > 0 else 0
        avg_confidence = sum(s.confidence for s in scores) / len(scores)

        return AnomalyScore(
            score=avg_score,
            threshold=self.threshold,
            confidence=avg_confidence,
        )

    def _classify_anomaly(self, features: FeatureVector) -> AnomalyType:
        """分类异常类型"""
        f = features.features

        # DDoS 检测
        if f.get("tcp_syn_rate", 0) > 1000 and f.get("connection_rate", 0) > 500:
            return AnomalyType.DDOS
        if f.get("packet_rate", 0) > 10000:
            return AnomalyType.TRAFFIC_SURGE

        # 端口扫描检测
        if f.get("unique_ports", 0) > 100 and f.get("connection_rate", 0) > 50:
            return AnomalyType.PORT_SCAN

        # 延迟突增
        if f.get("avg_rtt", 0) > 1.0 and f.get("avg_rtt", 0) > self._baseline.get("avg_rtt", 0) * 3:
            return AnomalyType.LATENCY_SPIKE

        # 丢包
        if f.get("loss_rate", 0) > 0.1:
            return AnomalyType.PACKET_LOSS

        # 连接洪水
        if f.get("connection_rate", 0) > 200:
            return AnomalyType.CONNECTION_FLOOD

        # 流量下降
        if f.get("byte_rate", 0) < self._baseline.get("byte_rate", 0) * 0.1:
            return AnomalyType.TRAFFIC_DROP

        # 带宽耗尽
        if f.get("bandwidth_usage", 0) > 0.95:
            return AnomalyType.BANDWIDTH_EXHAUST

        return AnomalyType.UNKNOWN

    def _generate_description(self, anomaly_type: AnomalyType, score: AnomalyScore) -> str:
        """生成异常描述"""
        descriptions = {
            AnomalyType.TRAFFIC_SURGE: f"流量突增 (score={score.score:.2f})",
            AnomalyType.TRAFFIC_DROP: f"流量骤降 (score={score.score:.2f})",
            AnomalyType.PORT_SCAN: f"端口扫描检测 (score={score.score:.2f})",
            AnomalyType.DDOS: f"DDoS 攻击检测 (score={score.score:.2f})",
            AnomalyType.LATENCY_SPIKE: f"延迟突增 (score={score.score:.2f})",
            AnomalyType.PACKET_LOSS: f"高丢包率 (score={score.score:.2f})",
            AnomalyType.PROTOCOL_ERROR: f"协议错误 (score={score.score:.2f})",
            AnomalyType.AUTH_FAILURE: f"认证失败异常 (score={score.score:.2f})",
            AnomalyType.BANDWIDTH_EXHAUST: f"带宽耗尽 (score={score.score:.2f})",
            AnomalyType.CONNECTION_FLOOD: f"连接洪水 (score={score.score:.2f})",
            AnomalyType.DNS_ANOMALY: f"DNS 异常 (score={score.score:.2f})",
            AnomalyType.UNKNOWN: f"未知异常 (score={score.score:.2f})",
        }
        return descriptions.get(anomaly_type, f"异常检测 (score={score.score:.2f})")

    def resolve_alert(self, alert_id: int, resolution: str = "") -> bool:
        """解决告警

        Args:
            alert_id: 告警索引
            resolution: 解决方案描述

        Returns:
            是否成功解决
        """
        if 0 <= alert_id < len(self._alerts):
            report = self._alerts[alert_id]
            if not report.resolved:
                report.resolve(resolution)
                if report in self._active_alerts:
                    self._active_alerts.remove(report)
                self._stats["resolved_alerts"] += 1
                self._stats["active_alerts"] = len(self._active_alerts)

                for callback in self._resolution_callbacks:
                    try:
                        callback(report)
                    except Exception as e:
                        logger.error(f"解决回调执行出错: {e}")

                return True
        return False

    def on_alert(self, callback: Any) -> None:
        """注册告警回调"""
        self._alert_callbacks.append(callback)

    def on_resolution(self, callback: Any) -> None:
        """注册告警解决回调"""
        self._resolution_callbacks.append(callback)

    def get_baseline(self) -> Dict[str, float]:
        """获取基线数据"""
        return self._baseline.copy()

    def get_baseline_std(self) -> Dict[str, float]:
        return self._baseline_std.copy()

    def get_feature_names(self) -> List[str]:
        return self._DEFAULT_FEATURES

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "model": self.model.value,
            "threshold": self.threshold,
            "sensitivity": self.sensitivity,
            "is_trained": self._is_trained,
            "feature_history_size": len(self._feature_history),
            "baseline_features": len(self._baseline),
            "active_alerts": len(self._active_alerts),
            "total_alerts": len(self._alerts),
            "resolved_alerts": self._stats["resolved_alerts"],
            "recent_alerts": [
                {
                    "type": a.anomaly_type.value,
                    "score": a.score.score,
                    "severity": a.severity,
                    "time": a.timestamp,
                    "resolved": a.resolved,
                }
                for a in self._alerts[-10:]
            ],
        }

    def reset(self) -> None:
        """重置检测器"""
        self._feature_history.clear()
        self._baseline.clear()
        self._baseline_std.clear()
        self._is_trained = False
        self._current_features = FeatureVector()
        self._alerts.clear()
        self._active_alerts.clear()
        self._last_update = 0.0
        self._stats = {
            "detections": 0,
            "false_positives": 0,
            "true_positives": 0,
            "avg_detection_time": 0.0,
            "total_alerts": 0,
            "active_alerts": 0,
            "resolved_alerts": 0,
        }
        logger.info("异常检测器已重置")