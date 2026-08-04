"""
TCP 协议单元测试
================
"""

import pytest
from src.protocol.tcp import (
    TCPProtocol, TCPConnection, TCPPacket, TCPState,
    TCPFlag, CongestionControl, RetransmissionManager,
    CongestionState,
)


class TestTCPPacket:
    """TCP 数据包测试"""

    def test_tcp_packet_encode_decode(self, sample_tcp_packet_data):
        """测试 TCP 数据包编码和解码"""
        packet = TCPPacket.decode(sample_tcp_packet_data)
        assert packet.src_port == 12345
        assert packet.dst_port == 80
        assert packet.sequence_number == 1000
        assert packet.is_syn
        assert not packet.is_ack

        encoded = packet.encode()
        assert len(encoded) >= 20

    def test_tcp_packet_flags(self):
        """测试 TCP 标志位"""
        syn_packet = TCPPacket(src_port=80, dst_port=12345, flags=TCPFlag.SYN)
        assert syn_packet.is_syn
        assert not syn_packet.is_ack
        assert not syn_packet.is_fin

        ack_packet = TCPPacket(src_port=80, dst_port=12345, flags=TCPFlag.ACK)
        assert ack_packet.is_ack

        fin_packet = TCPPacket(src_port=80, dst_port=12345, flags=TCPFlag.FIN)
        assert fin_packet.is_fin

    def test_tcp_packet_invalid(self):
        """测试无效的 TCP 数据包"""
        with pytest.raises(ValueError):
            TCPPacket.decode(b"")
        with pytest.raises(ValueError):
            TCPPacket.decode(b"\x00" * 10)


class TestTCPConnection:
    """TCP 连接测试"""

    def test_connection_creation(self):
        """测试连接创建"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        assert conn.state == TCPState.CLOSED
        assert conn.connection_id == "127.0.0.1:50000-192.168.1.1:80"
        assert not conn.is_established
        assert conn.duration >= 0

    def test_connection_state_transitions(self):
        """测试连接状态转换"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        assert conn.state == TCPState.CLOSED

        conn.state = TCPState.ESTABLISHED
        assert conn.is_established
        assert not conn.is_closing
        assert not conn.is_closed

        conn.state = TCPState.CLOSE_WAIT
        assert conn.is_closing

        conn.state = TCPState.CLOSED
        assert conn.is_closed

    def test_connection_statistics(self):
        """测试连接统计信息"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        conn.bytes_sent = 1000
        conn.bytes_received = 500
        conn.packets_sent = 10
        conn.packets_received = 8
        conn.retransmissions = 1

        assert conn.bytes_sent == 1000
        assert conn.throughput >= 0
        assert conn.loss_rate >= 0


class TestTCPProtocol:
    """TCP 协议测试"""

    @pytest.mark.asyncio
    async def test_protocol_start_stop(self):
        """测试协议启动和停止"""
        proto = TCPProtocol()
        await proto.start()
        assert proto._is_running
        await proto.stop()
        assert not proto._is_running

    @pytest.mark.asyncio
    async def test_create_connection(self):
        """测试创建连接"""
        proto = TCPProtocol()
        conn = proto.create_connection(
            ("127.0.0.1", 50000),
            ("192.168.1.1", 80),
        )
        assert conn is not None
        assert conn.state == TCPState.SYN_SENT
        assert conn.connection_id in proto._connections

    def test_listen_and_unlisten(self):
        """测试监听和取消监听"""
        proto = TCPProtocol()
        callback = lambda conn: None
        proto.listen(8080, callback)
        assert 8080 in proto._listeners
        proto.unlisten(8080)
        assert 8080 not in proto._listeners

    def test_connection_limit(self):
        """测试连接数限制"""
        proto = TCPProtocol()
        proto._max_connections = 2
        proto.create_connection(("0.0.0.0", 50000), ("1.1.1.1", 80))
        proto.create_connection(("0.0.0.0", 50001), ("1.1.1.2", 80))
        with pytest.raises(ConnectionError):
            proto.create_connection(("0.0.0.0", 50002), ("1.1.1.3", 80))


class TestCongestionControl:
    """拥塞控制测试"""

    def test_congestion_control_initialization(self):
        """测试拥塞控制初始化"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        cc = CongestionControl(conn)
        assert cc.conn.snd_cwnd == 1
        assert cc.conn.congestion_state == CongestionState.SLOW_START

    def test_slow_start_to_congestion_avoidance(self):
        """测试从慢启动到拥塞避免的转换"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        cc = CongestionControl(conn)
        assert cc.conn.congestion_state == CongestionState.SLOW_START

        # 增长到阈值
        while cc.conn.congestion_state == CongestionState.SLOW_START:
            cc.on_new_ack()

        assert cc.conn.congestion_state == CongestionState.CONGESTION_AVOIDANCE

    def test_packet_loss_handling(self):
        """测试丢包处理"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        cc = CongestionControl(conn)
        cc.conn.snd_cwnd = 100
        cc.on_packet_loss()
        assert cc.conn.snd_cwnd == 1
        assert cc.conn.congestion_state == CongestionState.SLOW_START

    def test_duplicate_ack(self):
        """测试重复 ACK"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        cc = CongestionControl(conn)
        cc.conn.snd_cwnd = 100
        cc.on_duplicate_ack(3)
        assert cc.conn.congestion_state == CongestionState.FAST_RECOVERY

    def test_rtt_update(self):
        """测试 RTT 更新"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        cc = CongestionControl(conn)

        cc.update_rtt(0.1)
        assert cc.conn.srtt > 0
        assert cc.conn.rto > 0

        cc.update_rtt(0.15)
        assert cc.conn.srtt > 0


class TestRetransmissionManager:
    """重传管理器测试"""

    def test_add_and_ack(self):
        """测试添加和确认数据包"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        rm = RetransmissionManager(conn)

        packet = TCPPacket(
            src_port=50000, dst_port=80,
            sequence_number=1000, payload=b"test",
        )
        rm.add_packet(packet)
        assert rm.get_pending_count() == 1

        confirmed = rm.ack_received(1004)
        assert len(confirmed) == 1
        assert rm.get_pending_count() == 0

    def test_retransmission_timeout(self):
        """测试重传超时"""
        conn = TCPConnection(
            local_addr=("127.0.0.1", 50000),
            remote_addr=("192.168.1.1", 80),
        )
        rm = RetransmissionManager(conn, rto=-1.0)  # 立即超时

        packet = TCPPacket(
            src_port=50000, dst_port=80,
            sequence_number=1000, payload=b"test",
        )
        rm.add_packet(packet)
        timed_out = rm.check_timeouts()
        assert len(timed_out) == 1
        assert timed_out[0].retransmitted