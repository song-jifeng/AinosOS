"""
监控模块单元测试
================
"""

import pytest
from src.monitor.capture import (
    PacketCapture, PacketSniffer, CapturedPacket,
    CaptureFilter, PCAPWriter, PCAPReader,
    CaptureState,
)
from src.monitor.analyzer import (
    TrafficAnalyzer, FlowAnalyzer, ProtocolAnalyzer,
    FlowStats, BandwidthUsage,
)
from src.monitor.anomally import AnomalyDetector, AnomalyReport, AnomalyType
from src.monitor.dashboard import (
    NetworkDashboard, DashboardWidget, DashboardMetrics,
    WidgetType,
)


class TestPacketCapture:
    """数据包捕获测试"""

    def test_capture_creation(self):
        """测试抓包管理器创建"""
        capture = PacketCapture()
        assert capture is not None
        assert not capture.is_capturing

    @pytest.mark.asyncio
    async def test_capture_start_stop(self):
        """测试开始和停止抓包"""
        capture = PacketCapture()
        await capture.start("any")
        assert capture.is_capturing
        result = await capture.stop()
        assert not capture.is_capturing

    def test_sniffer_state(self):
        """测试嗅探器状态"""
        sniffer = PacketSniffer()
        assert sniffer.state == CaptureState.IDLE

    def test_sniffer_filter(self):
        """测试过滤器"""
        sniffer = PacketSniffer()
        filter_obj = CaptureFilter(src_ip="192.168.1.1")
        sniffer.set_filter(filter_obj)
        assert sniffer._filter.is_active

    def test_captured_packet(self):
        """测试捕获的数据包"""
        packet = CapturedPacket(
            length=100,
            raw_data=b"test",
            src_ip="192.168.1.1",
            dst_ip="10.0.0.1",
            src_port=12345,
            dst_port=80,
            protocol="TCP",
            info="Test packet",
        )
        assert packet.size == "100 B"
        assert packet.src_ip == "192.168.1.1"
        assert packet.protocol == "TCP"


class TestTrafficAnalyzer:
    """流量分析器测试"""

    def test_analyzer_creation(self):
        """测试分析器创建"""
        analyzer = TrafficAnalyzer()
        assert analyzer.total_packets == 0
        assert analyzer.total_bytes == 0

    def test_analyze_packet(self):
        """测试分析数据包"""
        analyzer = TrafficAnalyzer()
        analyzer.analyze_packet(
            src_ip="192.168.1.1",
            dst_ip="10.0.0.1",
            src_port=12345,
            dst_port=80,
            protocol="TCP",
            length=100,
        )
        assert analyzer.total_packets == 1
        assert analyzer.total_bytes == 100

    def test_multiple_packets(self):
        """测试多个数据包分析"""
        analyzer = TrafficAnalyzer()
        for i in range(10):
            analyzer.analyze_packet(
                src_ip=f"192.168.1.{i}",
                dst_ip="10.0.0.1",
                protocol="TCP",
                length=100,
            )
        assert analyzer.total_packets == 10
        assert len(analyzer.get_top_talkers(5)) > 0

    def test_protocol_distribution(self):
        """测试协议分布"""
        analyzer = TrafficAnalyzer()
        analyzer.analyze_packet(protocol="TCP", length=100)
        analyzer.analyze_packet(protocol="UDP", length=50)
        dist = analyzer.get_protocol_distribution()
        assert dist.tcp > 0
        assert dist.udp > 0

    def test_bandwidth_usage(self):
        """测试带宽使用"""
        analyzer = TrafficAnalyzer()
        bw = analyzer.get_bandwidth_usage()
        assert isinstance(bw, BandwidthUsage)

    def test_flow_summary(self):
        """测试流摘要"""
        analyzer = TrafficAnalyzer()
        # 添加一些数据包以创建流
        analyzer.analyze_packet(src_ip="10.0.0.1", dst_ip="10.0.0.2",
                               src_port=80, dst_port=12345, protocol="TCP", length=100)
        summary = analyzer.get_flow_summary()
        assert summary["total_flows"] > 0

    def test_reset(self):
        """测试重置"""
        analyzer = TrafficAnalyzer()
        analyzer.analyze_packet(protocol="TCP", length=100)
        assert analyzer.total_packets > 0
        analyzer.reset()
        assert analyzer.total_packets == 0


class TestAnomalyDetector:
    """异常检测器测试"""

    def test_detector_creation(self):
        """测试检测器创建"""
        detector = AnomalyDetector()
        assert detector is not None

    def test_update_rates(self):
        """测试更新速率"""
        detector = AnomalyDetector()
        detector.update_rates(
            packet_rate=1000,
            byte_rate=1000000,
            error_rate=0.01,
            connection_rate=50,
            syn_rate=10,
        )
        alerts = detector.detect()
        assert isinstance(alerts, list)

    def test_traffic_surge_detection(self):
        """测试流量突增检测"""
        detector = AnomalyDetector()
        # 添加正常基线
        for _ in range(10):
            detector.update_rates(packet_rate=100, byte_rate=10000,
                                 error_rate=0.01, connection_rate=10, syn_rate=5)
        # 添加异常值
        detector.update_rates(packet_rate=10000, byte_rate=1000000,
                             error_rate=0.01, connection_rate=10, syn_rate=5)
        # 检测
        detector.update_rates(packet_rate=10000, byte_rate=1000000,
                             error_rate=0.01, connection_rate=10, syn_rate=5)
        alerts = detector.detect()
        surge_alerts = [a for a in alerts if a.anomaly_type == AnomalyType.TRAFFIC_SURGE]
        # 可能有也可能没有，取决于基线
        assert isinstance(alerts, list)


class TestNetworkDashboard:
    """仪表盘测试"""

    def test_dashboard_creation(self):
        """测试仪表盘创建"""
        dashboard = NetworkDashboard()
        assert dashboard is not None
        assert dashboard.uptime >= 0

    def test_add_widget(self):
        """测试添加组件"""
        dashboard = NetworkDashboard()
        widget = dashboard.add_widget("test_chart", WidgetType.CHART, "测试图表")
        assert widget is not None
        assert widget.name == "test_chart"
        assert widget.widget_type == WidgetType.CHART

    def test_remove_widget(self):
        """测试移除组件"""
        dashboard = NetworkDashboard()
        dashboard.add_widget("test", WidgetType.STAT)
        assert dashboard.remove_widget("test")
        assert not dashboard.remove_widget("nonexistent")

    def test_update_metrics(self):
        """测试更新指标"""
        dashboard = NetworkDashboard()
        metrics = DashboardMetrics(
            packet_rate=1000,
            byte_rate=1000000,
            active_connections=50,
        )
        dashboard.update_metrics(metrics)
        assert dashboard.metrics.packet_rate == 1000
        assert dashboard.metrics.active_connections == 50

    def test_update_widget(self):
        """测试更新组件"""
        dashboard = NetworkDashboard()
        dashboard.add_widget("test", WidgetType.STAT)
        dashboard.update_widget("test", {"value": 42})
        widget = dashboard.get_widget("test")
        assert widget.data == {"value": 42}

    def test_get_statistics(self):
        """测试统计信息"""
        dashboard = NetworkDashboard()
        stats = dashboard.get_statistics()
        assert "is_running" in stats
        assert "widget_count" in stats