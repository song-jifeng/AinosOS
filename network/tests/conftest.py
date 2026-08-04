"""
测试配置和工具函数
==================
"""

import asyncio
import pytest
from typing import Any, Dict


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_tcp_packet_data() -> bytes:
    """生成示例 TCP 数据包"""
    import struct
    src_port = 12345
    dst_port = 80
    seq_num = 1000
    ack_num = 0
    data_offset = 5
    flags = 0x02  # SYN
    window = 65535
    checksum = 0
    urgent = 0
    header = struct.pack("!HHIIBBHHH",
        src_port, dst_port, seq_num, ack_num,
        (data_offset << 4), flags, window, checksum, urgent)
    return header


@pytest.fixture
def sample_ip_packet_data() -> bytes:
    """生成示例 IP 数据包"""
    import struct
    version_ihl = 0x45
    tos = 0
    total_length = 40
    identification = 12345
    flags_fragment = 0
    ttl = 64
    protocol = 6
    checksum = 0
    src_ip = bytes([192, 168, 1, 1])
    dst_ip = bytes([8, 8, 8, 8])
    header = struct.pack("!BBHHHBBH4s4s",
        version_ihl, tos, total_length, identification,
        flags_fragment, ttl, protocol, checksum, src_ip, dst_ip)
    return header


@pytest.fixture
def sample_http_request() -> bytes:
    return b"GET / HTTP/1.1\r\nHost: example.com\r\nUser-Agent: Test\r\n\r\n"


@pytest.fixture
def sample_http_response() -> bytes:
    return b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 12\r\n\r\nHello World!"


@pytest.fixture
def sample_dns_query() -> bytes:
    import struct
    req_id = 0x1234
    flags = 0x0100
    qdcount = 1
    ancount = 0
    nscount = 0
    arcount = 0
    header = struct.pack("!HHHHHH", req_id, flags, qdcount, ancount, nscount, arcount)
    # 域名: example.com
    qname = b"\x07example\x03com\x00"
    qtype = 1  # A
    qclass = 1  # IN
    question = qname + struct.pack("!HH", qtype, qclass)
    return header + question


@pytest.fixture
def sample_websocket_frame() -> bytes:
    """生成示例 WebSocket 帧"""
    frame = bytearray()
    frame.append(0x81)  # FIN + TEXT
    frame.append(0x05)  # 长度 5
    frame.extend(b"Hello")
    return bytes(frame)


@pytest.fixture
def mock_config() -> Dict[str, Any]:
    return {
        "network": {
            "host": "0.0.0.0",
            "port": 0,
            "mtu": 1500,
            "timeout": 30.0,
        },
        "ai": {
            "traffic_pred_enabled": True,
            "congestion_control_enabled": True,
            "routing_enabled": True,
            "anomaly_detection_enabled": True,
        },
        "monitor": {
            "capture_enabled": False,
            "dashboard_enabled": False,
        },
    }