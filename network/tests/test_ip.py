"""
IP 协议单元测试
===============
"""

import pytest
from src.protocol.ip import (
    IPProtocol, IPPacket, IPHeader, IPProtocolNumber,
    IPFlag, IPFragmentAssembler, IPError,
)


class TestIPHeader:
    """IP 头部测试"""

    def test_ip_header_encode_decode(self, sample_ip_packet_data):
        """测试 IP 头部编码和解码"""
        header = IPHeader.decode(sample_ip_packet_data)
        assert header.version == 4
        assert header.ihl == 5
        assert header.src_ip == "192.168.1.1"
        assert header.dst_ip == "8.8.8.8"
        assert header.protocol == 6

        encoded = header.encode()
        assert len(encoded) >= 20

    def test_ip_header_flags(self):
        """测试 IP 标志位"""
        header = IPHeader(flags=IPFlag.DF)
        assert header.is_df
        assert not header.is_mf

        header = IPHeader(flags=IPFlag.MF)
        assert header.is_mf

    def test_ip_header_invalid(self):
        """测试无效的 IP 头部"""
        with pytest.raises(IPError):
            IPHeader.decode(b"")
        with pytest.raises(IPError):
            IPHeader.decode(b"\x00" * 15)


class TestIPPacket:
    """IP 数据包测试"""

    def test_ip_packet_creation(self):
        """测试 IP 数据包创建"""
        header = IPHeader(
            src_ip="192.168.1.1",
            dst_ip="8.8.8.8",
            protocol=6,
        )
        packet = IPPacket(header=header, payload=b"test payload")
        assert packet.src_ip == "192.168.1.1"
        assert packet.dst_ip == "8.8.8.8"
        assert packet.protocol == 6

    def test_ip_packet_encode_decode(self):
        """测试 IP 数据包编码和解码"""
        header = IPHeader(
            src_ip="10.0.0.1",
            dst_ip="10.0.0.2",
            protocol=17,
        )
        original = IPPacket(header=header, payload=b"Hello")
        encoded = original.encode()
        decoded = IPPacket.decode(encoded)
        assert decoded.src_ip == "10.0.0.1"
        assert decoded.dst_ip == "10.0.0.2"
        assert decoded.payload == b"Hello"


class TestIPProtocol:
    """IP 协议测试"""

    @pytest.mark.asyncio
    async def test_protocol_start_stop(self):
        """测试协议启动和停止"""
        ip = IPProtocol()
        await ip.start()
        assert ip._is_running
        await ip.stop()
        assert not ip._is_running

    def test_route_management(self):
        """测试路由管理"""
        ip = IPProtocol()
        ip.add_route("192.168.1.0/24", "192.168.1.1")
        ip.add_route("10.0.0.0/8", "10.0.0.1")
        assert len(ip._routes) == 2

        ip.remove_route("192.168.1.0/24")
        assert len(ip._routes) == 1

    def test_default_gateway(self):
        """测试默认网关"""
        ip = IPProtocol()
        ip.set_default_gateway("192.168.1.1")
        assert ip._default_gateway == "192.168.1.1"

    def test_local_ip_management(self):
        """测试本地 IP 管理"""
        ip = IPProtocol()
        ip.add_local_ip("192.168.1.100")
        assert ip.is_local_ip("192.168.1.100")
        ip.remove_local_ip("192.168.1.100")
        assert not ip.is_local_ip("192.168.1.100")

    def test_packet_filter(self):
        """测试数据包过滤器"""
        ip = IPProtocol()
        filtered = []

        def filter_func(packet):
            filtered.append(packet)
            return True

        ip.add_filter(filter_func)
        assert filter_func in ip._packet_filters
        ip.remove_filter(filter_func)
        assert filter_func not in ip._packet_filters

    def test_create_packet(self):
        """测试创建数据包"""
        ip = IPProtocol()
        packet = ip.create_packet(
            src_ip="192.168.1.1",
            dst_ip="8.8.8.8",
            protocol=6,
            payload=b"test",
        )
        assert packet.src_ip == "192.168.1.1"
        assert packet.dst_ip == "8.8.8.8"
        assert packet.protocol == 6
        assert packet.payload == b"test"

    def test_get_statistics(self):
        """测试统计信息"""
        ip = IPProtocol()
        stats = ip.get_statistics()
        assert "packets_received" in stats
        assert "packets_sent" in stats
        assert "is_running" in stats


class TestIPFragmentAssembler:
    """IP 分片重组测试"""

    def test_fragment_assembly(self):
        """测试分片重组"""
        assembler = IPFragmentAssembler()
        # 创建分片
        payload = b"Hello World Fragment Test"
        header1 = IPHeader(
            identification=1,
            flags=IPFlag.MF,
            src_ip="192.168.1.1",
            dst_ip="10.0.0.1",
        )
        frag1 = IPPacket(header=header1, payload=payload[:10])

        result = assembler.add_fragment(frag1)
        assert result is None  # 尚有分片未到达

        # 第二个分片
        header2 = IPHeader(
            identification=1,
            fragment_offset=10,
            flags=0,
            src_ip="192.168.1.1",
            dst_ip="10.0.0.1",
        )
        frag2 = IPPacket(header=header2, payload=payload[10:])

        result = assembler.add_fragment(frag2)
        assert result is not None
        assert result.payload == payload