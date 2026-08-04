"""
AI 智能模块
===========

提供 AI 驱动的流量预测、拥塞控制优化、智能路由和异常检测。
"""

from src.ai.traffic_pred import TrafficPredictor, TrafficModel, PredictionResult
from src.ai.congestion import CongestionOptimizer, CCAlgorithm, CCZone
from src.ai.routing import SmartRouter, RoutingTable, RouteMetric, RouteEntry
from src.ai.anomaly_detector import AIAnomalyDetector, AnomalyScore, DetectionModel

__all__ = [
    "TrafficPredictor", "TrafficModel", "PredictionResult",
    "CongestionOptimizer", "CCAlgorithm", "CCZone",
    "SmartRouter", "RoutingTable", "RouteMetric", "RouteEntry",
    "AIAnomalyDetector", "AnomalyScore", "DetectionModel",
]