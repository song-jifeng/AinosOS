"""
流量监控示例
============

展示如何使用网络栈的监控和 AI 功能进行实时流量分析。
"""

import asyncio
import random
import time
import logging
from src.monitor.analyzer import TrafficAnalyzer
from src.monitor.dashboard import NetworkDashboard, DashboardMetrics, WidgetType
from src.ai.traffic_pred import TrafficPredictor, TrafficModel
from src.ai.anomaly_detector import AIAnomalyDetector, DetectionModel


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def simulate_traffic(analyzer: TrafficAnalyzer) -> None:
    """模拟网络流量"""
    protocols = ["TCP", "UDP", "ICMP", "DNS", "HTTP", "HTTPS"]
    ips = [f"192.168.1.{i}" for i in range(1, 20)]

    while True:
        # 模拟正常流量
        packet_count = random.randint(1, 10)
        for _ in range(packet_count):
            src_ip = random.choice(ips)
            dst_ip = random.choice(ips)
            protocol = random.choice(protocols)
            length = random.randint(40, 1500)

            analyzer.analyze_packet(
                src_ip=src_ip,
                dst_ip=dst_ip,
                src_port=random.randint(1024, 65535),
                dst_port=random.choice([80, 443, 53, 22]),
                protocol=protocol,
                length=length,
            )

        # 偶尔模拟流量峰值
        if random.random() < 0.05:
            for _ in range(random.randint(50, 200)):
                analyzer.analyze_packet(
                    src_ip="10.0.0.1",
                    dst_ip=random.choice(ips),
                    protocol="TCP",
                    length=random.randint(40, 100),
                )
            logger.info("模拟流量峰值")

        await asyncio.sleep(0.1)


async def update_dashboard(dashboard: NetworkDashboard, predictor: TrafficPredictor,
                           anomaly_detector: AIAnomalyDetector,
                           analyzer: TrafficAnalyzer) -> None:
    """更新仪表盘"""
    while True:
        # 更新流量预测
        predictor.add_data_point(analyzer._stats["total_bytes"])
        prediction = predictor.predict()
        dashboard.update_widget("traffic_prediction", {
            "values": prediction.values if prediction else [],
            "confidence": prediction.confidence if prediction else 0,
            "trend": prediction.trend if prediction else "stable",
        })

        # 更新异常检测特征
        bw = analyzer.get_bandwidth_usage()
        features = {
            "packet_rate": bw.current,
            "byte_rate": bw.avg,
            "flow_count": analyzer.total_flows,
            "bandwidth_usage": min(1.0, bw.current / max(bw.peak, 1)),
        }
        anomaly_detector.update_features(features)
        report = anomaly_detector.detect()
        if report:
            dashboard.update_widget("anomaly_alerts", {
                "type": report.anomaly_type.value,
                "score": report.score.score,
                "severity": report.severity,
            })

        # 更新仪表盘指标
        metrics = DashboardMetrics(
            packet_rate=bw.current / 1000,
            byte_rate=bw.avg,
            throughput=analyzer.avg_throughput,
            active_connections=analyzer.total_flows,
            total_connections=analyzer.total_packets,
            active_flows=analyzer.total_flows,
        )
        dashboard.update_metrics(metrics)

        await asyncio.sleep(2)


async def print_status(analyzer: TrafficAnalyzer, dashboard: NetworkDashboard) -> None:
    """打印状态信息"""
    while True:
        bw = analyzer.get_bandwidth_usage()
        logger.info("=" * 50)
        logger.info(f"网络状态报告")
        logger.info(f"总数据包: {analyzer.total_packets}")
        logger.info(f"总字节数: {analyzer.total_bytes}")
        logger.info(f"平均吞吐量: {analyzer.avg_throughput / 1024:.1f} KB/s")
        logger.info(f"当前带宽: {bw.current / 1024:.1f} KB/s")
        logger.info(f"峰值带宽: {bw.peak / 1024:.1f} KB/s")
        logger.info(f"活跃流: {analyzer.total_flows}")

        # 协议分布
        dist = analyzer.get_protocol_distribution()
        logger.info(f"协议分布:")
        logger.info(f"  TCP: {dist.tcp * 100:.1f}%")
        logger.info(f"  UDP: {dist.udp * 100:.1f}%")
        logger.info(f"  其他: {dist.other * 100:.1f}%")

        # 流量最多的源
        top_talkers = analyzer.get_top_talkers(3)
        logger.info(f"Top Talkers:")
        for ip, count in top_talkers:
            logger.info(f"  {ip}: {count} 个数据包")

        # 仪表盘状态
        dash_stats = dashboard.get_statistics()
        logger.info(f"仪表盘更新: {dash_stats['updates']} 次")

        await asyncio.sleep(10)


async def main():
    logger.info("启动网络流量监控示例...")

    # 初始化组件
    analyzer = TrafficAnalyzer(window_size=300)
    predictor = TrafficPredictor(
        window_size=100,
        horizon=10,
        model_type=TrafficModel.HOLT_WINTERS,
    )
    anomaly_detector = AIAnomalyDetector(
        model=DetectionModel.STATISTICAL,
        threshold=0.7,
    )
    dashboard = NetworkDashboard(refresh_interval=2.0)

    # 添加仪表盘组件
    dashboard.add_widget("traffic_prediction", WidgetType.CHART, "流量预测")
    dashboard.add_widget("anomaly_alerts", WidgetType.ALERT_LIST, "异常告警")
    dashboard.add_widget("bandwidth_gauge", WidgetType.GAUGE, "带宽使用")

    # 启动仪表盘
    await dashboard.start()

    # 并发运行任务
    tasks = [
        asyncio.create_task(simulate_traffic(analyzer)),
        asyncio.create_task(update_dashboard(dashboard, predictor, anomaly_detector, analyzer)),
        asyncio.create_task(print_status(analyzer, dashboard)),
        asyncio.create_task(dashboard.update_loop()),
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("正在停止监控...")
        for task in tasks:
            task.cancel()
        await dashboard.stop()


if __name__ == "__main__":
    asyncio.run(main())