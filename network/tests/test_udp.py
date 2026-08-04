"""
UDP 协议单元测试
================
"""

import pytest
from src.protocol.udp import (
    UDPProtocol, UDPDatagram, UDPSocket,
    UDPError, UDPPortUnavailable,
)


class TestUDPDatagram:
    """UDP 数据报测试"""

    def test_udp_datagram_encode_decode(self):
        """测试 UDP 数据报编码和解码"""
        datagram = UDPDatagram(
            src_port=12345,
            dst_port=53,
            payload=b"test data",
        )
        assert datagram.length == 8 + len(b"test data")

        encoded = datagram.encode()
        decoded = UDPDatagram.decode(encoded)

        assert decoded.src_port == 12345
        assert decoded.dst_port == 53
        assert decoded.payload == b"test data"

    def test_udp_datagram_invalid(self):
        """测试无效的 UDP 数据报"""
        with pytest.raises(ValueError):
            UDPDatagram.decode(b"")
        with pytest.raises(ValueError):
            UDPDatagram.decode(b"\x00" * 5)


class TestUDPProtocol:
    """UDP 协议测试"""

    @pytest.mark.asyncio
    async def test_protocol_start_stop(self):
        """测试协议启动和停止"""
        proto = UDPProtocol()
        await proto.start()
        assert proto._is_running
        await proto.stop()
        assert not proto._is_running

    def test_create_socket(self):
        """测试创建套接字"""
        proto = UDPProtocol()
        sock = proto.create_socket(12345)
        assert sock is not None
        assert sock.local_addr[1] == 12345
        assert not sock.is_closed

    def test_create_socket_auto_port(self):
        """测试自动分配端口"""
        proto = UDPProtocol()
        sock = proto.create_socket()
        assert sock.local_addr[1] >= 49152

    def test_create_socket_port_conflict(self):
        """测试端口冲突"""
        proto = UDPProtocol()
        proto.create_socket(12345)
        with pytest.raises(UDPPortUnavailable):
            proto.create_socket(12345)

    @pytest.mark.asyncio
    async def test_send_and_close(self):
        """测试发送和关闭"""
        proto = UDPProtocol()
        await proto.start()

        sock = proto.create_socket(12345)
        await proto.sendto(b"hello", ("127.0.0.1", 53), 12345)

        assert sock.bytes_sent == len(b"hello")
        assert sock.datagrams_sent == 1

        result = await proto.close(12345)
        assert result
        assert sock.is_closed

        await proto.stop()

    @pytest.mark.asyncio
    async def test_data_too_large(self):
        """测试数据报太大"""
        proto = UDPProtocol()
        proto.create_socket(12345)
        with pytest.raises(ValueError, match="数据报太大"):
            await proto.sendto(b"\x00" * 70000, ("127.0.0.1", 53), 12345)

    def test_connect_disconnect(self):
        """测试连接和断开"""
        proto = UDPProtocol()
        sock = proto.create_socket(12345)
        assert not sock.connected

        proto.connect(12345, ("192.168.1.1", 80))
        assert sock.connected
        assert sock.remote_addr == ("192.168.1.1", 80)

        proto.disconnect(12345)
        assert not sock.connected
        assert sock.remote_addr is None

    def test_set_ttl(self):
        """测试设置 TTL"""
        proto = UDPProtocol()
        proto.create_socket(12345)
        proto.set_ttl(12345, 128)
        sock = proto._sockets[12345]
        assert sock.ttl == 128

        with pytest.raises(ValueError):
            proto.set_ttl(12345, 300)

    def test_on_recv_callback(self):
        """测试接收回调"""
        proto = UDPProtocol()
        proto.create_socket(12345)
        callback_data = []

        def callback(data, addr):
            callback_data.append((data, addr))

        proto.on_recv(12345, callback)
        # 发送测试数据报
        datagram = UDPDatagram(
            src_port=53, dst_port=12345,
            payload=b"response",
            src_ip="8.8.8.8",
        )
        proto.process_datagram(datagram)
        assert len(callback_data) == 1
        assert callback_data[0][0] == b"response"

    def test_get_statistics(self):
        """测试统计信息"""
        proto = UDPProtocol()
        stats = proto.get_statistics()
        assert "active_sockets" in stats
        assert "is_running" in stats