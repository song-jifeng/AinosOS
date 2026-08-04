"""
网络栈主类
==========

AI 优化网络栈的主入口，整合所有模块并提供统一的初始化和控制接口。
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable

from src.protocol.tcp import TCPProtocol, TCPConnection, TCPState
from src.protocol.udp import UDPProtocol, UDPDatagram
from src.protocol.ip import IPProtocol, IPPacket
from src.protocol.dns import DNSResolver, DNSRecord, DNSType
from src.protocol.http import HTTPClient, HTTPServer, HTTPRequest, HTTPResponse
from src.protocol.websocket import WebSocket, WebSocketServer, WebSocketClient
from src.monitor.capture import PacketCapture, CapturedPacket, CaptureFilter
from src.monitor.analyzer import TrafficAnalyzer, FlowAnalyzer, ProtocolAnalyzer
from src.monitor.anomally import AnomalyDetector, AnomalyReport
from src.monitor.dashboard import NetworkDashboard, DashboardMetrics, DashboardWidget, WidgetType
from src.ai.traffic_pred import TrafficPredictor, TrafficModel, PredictionResult
from src.ai.congestion import CongestionOptimizer, CCAlgorithm, NetworkMetrics
from src.ai.routing import SmartRouter, RoutingTable, RouteEntry, RouteMetric
from src.ai.anomaly_detector import AIAnomalyDetector, AnomalyScore, DetectionModel
from src.tools.ping import Ping, PingResult, PingStats
from src.tools.traceroute import Traceroute, TracerouteHop, TracerouteResult
from src.tools.iperf import Iperf, IperfResult, IperfStream, IperfProtocol, IperfDirection
from src.tools.nmap import NmapScanner, PortResult, ScanResult, PortState, ScanType
from src.tools.proxy import ProxyServer, ProxyConfig, ProxyType, HTTPProxy, Socks5Proxy
from src.utils.config import ConfigManager, StackConfig, NetworkConfig, AIConfig, MonitorConfig


logger = logging.getLogger(__name__)


class NetworkStack:
    """AI 优化网络栈主类

    整合所有网络协议、AI 优化、监控和工具模块，提供统一的管理接口。

    典型用法:
        >>> stack = NetworkStack()
        >>> await stack.initialize()
        >>> await stack.start()
        >>> await stack.ping("8.8.8.8")
        >>> await stack.stop()
    """

    def __init__(self, config: Optional[StackConfig] = None) -> None:
        # 配置
        self._config = config or StackConfig()
        self._config_manager = ConfigManager()
        self._is_initialized: bool = False
        self._is_running: bool = False
        self._start_time: float = 0.0

        # 协议层
        self._tcp: TCPProtocol = TCPProtocol()
        self._udp: UDPProtocol = UDPProtocol()
        self._ip: IPProtocol = IPProtocol()
        self._dns: DNSResolver = DNSResolver()
        self._http_client: HTTPClient = HTTPClient()
        self._http_server: Optional[HTTPServer] = None
        self._ws_server: Optional[WebSocketServer] = None

        # 监控层
        self._capture: PacketCapture = PacketCapture()
        self._analyzer: TrafficAnalyzer = TrafficAnalyzer()
        self._flow_analyzer: FlowAnalyzer = FlowAnalyzer()
        self._protocol_analyzer: ProtocolAnalyzer = ProtocolAnalyzer()
        self._anomaly_detector: AnomalyDetector = AnomalyDetector()
        self._dashboard: NetworkDashboard = NetworkDashboard()

        # AI 层
        self._traffic_predictor: TrafficPredictor = TrafficPredictor()
        self._congestion_optimizer: CongestionOptimizer = CongestionOptimizer()
        self._smart_router: SmartRouter = SmartRouter()
        self._ai_anomaly_detector: AIAnomalyDetector = AIAnomalyDetector()

        # 工具层
        self._proxy: Optional[ProxyServer] = None

        # 后台任务
        self._background_tasks: List[asyncio.Task] = []

        # 事件回调
        self._on_start_callbacks: List[Callable] = []
        self._on_stop_callbacks: List[Callable] = []
        self._on_error_callbacks: List[Callable] = []

    # --- 属性 ---

    @property
    def config(self) -> StackConfig:
        return self._config

    @property
    def config_manager(self) -> ConfigManager:
        return self._config_manager

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def uptime(self) -> float:
        if self._is_running and self._start_time > 0:
            return time.time() - self._start_time
        return 0.0

    @property
    def tcp(self) -> TCPProtocol:
        return self._tcp

    @property
    def udp(self) -> UDPProtocol:
        return self._udp

    @property
    def ip(self) -> IPProtocol:
        return self._ip

    @property
    def dns(self) -> DNSResolver:
        return self._dns

    @property
    def http_client(self) -> HTTPClient:
        return self._http_client

    @property
    def http_server(self) -> Optional[HTTPServer]:
        return self._http_server

    @property
    def capture(self) -> PacketCapture:
        return self._capture

    @property
    def analyzer(self) -> TrafficAnalyzer:
        return self._analyzer

    @property
    def dashboard(self) -> NetworkDashboard:
        return self._dashboard

    @property
    def traffic_predictor(self) -> TrafficPredictor:
        return self._traffic_predictor

    @property
    def congestion_optimizer(self) -> CongestionOptimizer:
        return self._congestion_optimizer

    @property
    def smart_router(self) -> SmartRouter:
        return self._smart_router

    @property
    def ai_anomaly_detector(self) -> AIAnomalyDetector:
        return self._ai_anomaly_detector

    @property
    def proxy(self) -> Optional[ProxyServer]:
        return self._proxy

    # --- 初始化和生命周期 ---

    async def initialize(self) -> bool:
        """初始化网络栈

        Returns:
            是否成功初始化
        """
        if self._is_initialized:
            logger.warning("网络栈已初始化")
            return True

        try:
            logger.info("正在初始化 AI 优化网络栈...")

            # 配置 DNS 服务器
            if self._config.network.dns_servers:
                self._dns.servers = self._config.network.dns_servers

            # 配置 AI 模块
            self._traffic_predictor = TrafficPredictor(
                window_size=self._config.ai.traffic_pred_window,
                model_type=TrafficModel(self._config.ai.traffic_pred_model),
                update_interval=self._config.ai.traffic_pred_interval,
            )

            self._congestion_optimizer = CongestionOptimizer(
                algorithm=CCAlgorithm(self._config.ai.congestion_control_algorithm),
                update_interval=self._config.ai.congestion_control_interval,
                sensitivity=self._config.ai.congestion_control_sensitivity,
            )

            self._smart_router = SmartRouter(
                algorithm=self._config.ai.routing_algorithm,
                update_interval=self._config.ai.routing_update_interval,
                max_paths=self._config.ai.routing_max_paths,
            )

            self._ai_anomaly_detector = AIAnomalyDetector(
                model=DetectionModel(self._config.ai.anomaly_detection_model),
                threshold=self._config.ai.anomaly_detection_threshold,
                sensitivity=self._config.ai.anomaly_detection_sensitivity,
                update_interval=self._config.ai.anomaly_detection_interval,
            )

            # 配置监控
            self._dashboard = NetworkDashboard(
                host=self._config.monitor.dashboard_host,
                port=self._config.monitor.dashboard_port,
                refresh_interval=self._config.monitor.dashboard_refresh_interval,
                max_data_points=self._config.monitor.dashboard_max_points,
            )

            self._is_initialized = True
            logger.info("AI 优化网络栈初始化完成")
            return True

        except Exception as e:
            logger.error(f"网络栈初始化失败: {e}")
            if self._on_error_callbacks:
                for cb in self._on_error_callbacks:
                    try:
                        cb(e)
                    except Exception:
                        pass
            return False

    async def start(self) -> bool:
        """启动网络栈

        Returns:
            是否成功启动
        """
        if not self._is_initialized:
            if not await self.initialize():
                return False

        if self._is_running:
            logger.warning("网络栈已在运行中")
            return True

        try:
            self._start_time = time.time()

            # 启动协议层
            await self._tcp.start()
            await self._udp.start()
            await self._ip.start()

            # 启动监控
            if self._config.monitor.capture_enabled:
                await self._capture.start(self._config.monitor.capture_interface)
            if self._config.monitor.dashboard_enabled:
                await self._dashboard.start()

            # 启动 AI 任务
            if self._config.ai.traffic_pred_enabled:
                task = asyncio.create_task(self._traffic_predict_loop())
                self._background_tasks.append(task)
            if self._config.ai.anomaly_detection_enabled:
                task = asyncio.create_task(self._anomaly_detection_loop())
                self._background_tasks.append(task)
            if self._config.ai.routing_enabled:
                task = asyncio.create_task(self._routing_update_loop())
                self._background_tasks.append(task)

            # 启动仪表盘更新
            task = asyncio.create_task(self._dashboard.update_loop())
            self._background_tasks.append(task)

            self._is_running = True

            # 通知回调
            for cb in self._on_start_callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(self)
                    else:
                        cb(self)
                except Exception as e:
                    logger.error(f"启动回调执行出错: {e}")

            logger.info("AI 优化网络栈已启动")
            return True

        except Exception as e:
            logger.error(f"网络栈启动失败: {e}")
            for cb in self._on_error_callbacks:
                try:
                    cb(e)
                except Exception:
                    pass
            return False

    async def stop(self) -> bool:
        """停止网络栈

        Returns:
            是否成功停止
        """
        if not self._is_running:
            return True

        try:
            # 停止后台任务
            for task in self._background_tasks:
                task.cancel()
            if self._background_tasks:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

            # 停止协议层
            await self._tcp.stop()
            await self._udp.stop()
            await self._ip.stop()

            # 停止监控
            await self._capture.stop()
            if self._config.monitor.dashboard_enabled:
                await self._dashboard.stop()

            # 停止代理
            if self._proxy:
                await self._proxy.stop()

            # 关闭 HTTP 客户端
            await self._http_client.close()

            self._is_running = False

            # 通知回调
            for cb in self._on_stop_callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(self)
                    else:
                        cb(self)
                except Exception as e:
                    logger.error(f"停止回调执行出错: {e}")

            logger.info("AI 优化网络栈已停止")
            return True

        except Exception as e:
            logger.error(f"网络栈停止失败: {e}")
            return False

    async def restart(self) -> bool:
        """重启网络栈"""
        await self.stop()
        return await self.start()

    # --- 事件回调 ---

    def on_start(self, callback: Callable) -> None:
        """注册启动回调"""
        self._on_start_callbacks.append(callback)

    def on_stop(self, callback: Callable) -> None:
        """注册停止回调"""
        self._on_stop_callbacks.append(callback)

    def on_error(self, callback: Callable) -> None:
        """注册错误回调"""
        self._on_error_callbacks.append(callback)

    # --- 后台任务 ---

    async def _traffic_predict_loop(self) -> None:
        """流量预测循环"""
        while self._is_running:
            try:
                self._traffic_predictor.train()
                prediction = self._traffic_predictor.predict()
                # 更新仪表盘
                if prediction:
                    self._dashboard.update_widget("traffic_prediction", {
                        "values": prediction.values,
                        "confidence": prediction.confidence,
                        "trend": prediction.trend,
                    })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"流量预测循环错误: {e}")
            await asyncio.sleep(self._config.ai.traffic_pred_interval)

    async def _anomaly_detection_loop(self) -> None:
        """异常检测循环"""
        while self._is_running:
            try:
                # 收集特征
                features = self._collect_anomaly_features()
                self._ai_anomaly_detector.update_features(features)
                report = self._ai_anomaly_detector.detect()
                if report:
                    logger.warning(f"AI 异常检测: {report.anomaly_type.value} "
                                   f"(score={report.score.score:.3f})")
                    self._dashboard.update_widget("anomaly_alerts", {
                        "type": report.anomaly_type.value,
                        "score": report.score.score,
                        "severity": report.severity,
                        "timestamp": report.timestamp,
                    })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"异常检测循环错误: {e}")
            await asyncio.sleep(self._config.ai.anomaly_detection_interval)

    async def _routing_update_loop(self) -> None:
        """路由更新循环"""
        while self._is_running:
            try:
                self._smart_router.balance_load()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"路由更新循环错误: {e}")
            await asyncio.sleep(self._config.ai.routing_update_interval)

    def _collect_anomaly_features(self) -> Dict[str, float]:
        """收集异常检测特征"""
        features = {}
        try:
            bw = self._analyzer.get_bandwidth_usage()
            features["packet_rate"] = bw.current
            features["byte_rate"] = bw.avg
            features["flow_count"] = self._analyzer.total_flows
            features["bandwidth_usage"] = min(1.0, bw.current / max(bw.peak, 1))
        except Exception:
            pass
        return features

    # --- 网络工具 ---

    async def ping(self, host: str, count: int = 4) -> PingStats:
        """执行 Ping 测试

        Args:
            host: 目标主机
            count: 发送次数

        Returns:
            Ping 统计结果
        """
        pinger = Ping(host, count=count)
        return await pinger.run()

    async def traceroute(self, host: str, max_hops: int = 30) -> TracerouteResult:
        """执行路由追踪"""
        tracer = Traceroute(host, max_hops=max_hops)
        return await tracer.run()

    async def iperf(self, host: str, port: int = 5201,
                     duration: float = 10.0,
                     protocol: str = "tcp") -> IperfResult:
        """执行带宽测试"""
        proto = IperfProtocol.TCP if protocol.lower() == "tcp" else IperfProtocol.UDP
        iperf = Iperf(host, port, protocol=proto, duration=duration)
        return await iperf.run()

    async def port_scan(self, host: str, ports: str = "1-1024") -> ScanResult:
        """执行端口扫描"""
        scanner = NmapScanner(host, ports=ports)
        return await scanner.scan()

    async def resolve_dns(self, hostname: str, record_type: str = "A") -> List[str]:
        """DNS 解析"""
        type_map = {
            "A": DNSType.A, "AAAA": DNSType.AAAA,
            "MX": DNSType.MX, "CNAME": DNSType.CNAME,
            "NS": DNSType.NS, "TXT": DNSType.TXT,
        }
        qtype = type_map.get(record_type.upper(), DNSType.A)
        records = await self._dns.resolve(hostname, qtype)
        return [r.data for r in records]

    async def start_http_server(self, host: str = "0.0.0.0",
                                 port: int = 8080) -> HTTPServer:
        """启动 HTTP 服务器"""
        self._http_server = HTTPServer(host, port)
        await self._http_server.start()
        return self._http_server

    async def start_proxy(self, host: str = "0.0.0.0", port: int = 8080,
                           proxy_type: str = "http") -> ProxyServer:
        """启动代理服务器"""
        ptype = ProxyType.HTTP if proxy_type.lower() == "http" else ProxyType.SOCKS5
        config = ProxyConfig(host=host, port=port, proxy_type=ptype)
        self._proxy = ProxyServer(config)
        await self._proxy.start()
        return self._proxy

    # --- 配置管理 ---

    def load_config(self, filepath: str) -> bool:
        """加载配置文件"""
        try:
            self._config_manager.load_from_file(filepath)
            self._config = self._config_manager.config
            logger.info(f"配置已加载: {filepath}")
            return True
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            return False

    def save_config(self, filepath: str) -> bool:
        """保存配置"""
        try:
            self._config_manager.save(filepath)
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False

    # --- 状态和统计 ---

    def get_statistics(self) -> Dict[str, Any]:
        """获取网络栈全局统计"""
        return {
            "is_initialized": self._is_initialized,
            "is_running": self._is_running,
            "uptime": self.uptime,
            "tcp": self._tcp.get_statistics(),
            "udp": self._udp.get_statistics(),
            "ip": self._ip.get_statistics(),
            "dns": self._dns.get_statistics(),
            "analyzer": self._analyzer.get_statistics(),
            "traffic_predictor": self._traffic_predictor.get_statistics(),
            "congestion_optimizer": self._congestion_optimizer.get_statistics(),
            "smart_router": self._smart_router.get_statistics(),
            "ai_anomaly_detector": self._ai_anomaly_detector.get_statistics(),
            "dashboard": self._dashboard.get_statistics(),
        }

    def get_status(self) -> Dict[str, Any]:
        """获取网络栈状态摘要"""
        return {
            "status": "running" if self._is_running else "stopped",
            "initialized": self._is_initialized,
            "uptime": f"{self.uptime:.1f}s",
            "tcp_connections": self._tcp.active_connections,
            "udp_sockets": self._udp.active_sockets,
            "total_packets": self._analyzer.total_packets,
            "total_bytes": self._analyzer.total_bytes,
            "dns_queries": self._dns.stats["queries"],
            "routes": self._smart_router.route_count,
            "ai_predictions": self._traffic_predictor.get_statistics().get("predictions_made", 0),
            "ai_alerts": self._ai_anomaly_detector.get_statistics().get("detections", 0),
        }

    def __repr__(self) -> str:
        status = "running" if self._is_running else "stopped"
        return f"NetworkStack(status={status}, uptime={self.uptime:.1f}s)"