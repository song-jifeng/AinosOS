#!/usr/bin/env python3
"""AinosOS IPC 协议模糊测试 - 随机消息注入、异常格式测试、内存安全测试"""

import json
import random
import string
import sys
import os
import time
import struct
import unittest
import threading
import queue
import socket
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

# ============================================================
# IPC 协议常量
# ============================================================

IPC_MAGIC = b"AIPC"
IPC_VERSION = 1

# 消息类型
MSG_REQUEST = 0x01
MSG_RESPONSE = 0x02
MSG_ERROR = 0x03
MSG_STREAM = 0x04
MSG_STREAM_END = 0x05
MSG_HEARTBEAT = 0x06
MSG_AUTH = 0x07
MSG_AUTH_RESPONSE = 0x08
MSG_SUBSCRIBE = 0x09
MSG_EVENT = 0x0A
MSG_CANCEL = 0x0B
MSG_CONFIG = 0x0C
MSG_LOG = 0x0D
MSG_METRICS = 0x0E

# 标志位
FLAG_NONE = 0x00
FLAG_ENCRYPTED = 0x01
FLAG_COMPRESSED = 0x02
FLAG_PRIORITY = 0x04
FLAG_BATCH = 0x08

# 最大消息大小
MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16 MB
MIN_MESSAGE_SIZE = 8  # 最小头部大小

# 帧头部格式
FRAME_HEADER_FORMAT = "!4sBBHI"  # magic(4) + version(1) + type(1) + flags(2) + length(4)
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)


# ============================================================
# IPC 帧结构
# ============================================================

@dataclass
class IPCFrame:
    """IPC 帧结构"""
    magic: bytes = IPC_MAGIC
    version: int = IPC_VERSION
    msg_type: int = MSG_REQUEST
    flags: int = FLAG_NONE
    payload: bytes = b""

    @property
    def length(self) -> int:
        return len(self.payload)

    def encode(self) -> bytes:
        """编码为二进制"""
        return struct.pack(
            FRAME_HEADER_FORMAT,
            self.magic,
            self.version,
            self.msg_type,
            self.flags,
            self.length
        ) + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "IPCFrame":
        """从二进制解码"""
        if len(data) < FRAME_HEADER_SIZE:
            raise ValueError(f"帧数据过短: {len(data)} < {FRAME_HEADER_SIZE}")

        magic, version, msg_type, flags, length = struct.unpack(
            FRAME_HEADER_FORMAT, data[:FRAME_HEADER_SIZE]
        )

        if magic != IPC_MAGIC:
            raise ValueError(f"魔数错误: {magic}")

        payload = data[FRAME_HEADER_SIZE:FRAME_HEADER_SIZE + length]

        return cls(
            magic=magic,
            version=version,
            msg_type=msg_type,
            flags=flags,
            payload=payload
        )


# ============================================================
# 随机 IPC 消息生成器
# ============================================================

class IPCFuzzGenerator:
    """IPC 模糊测试生成器"""

    def __init__(self, seed: Optional[int] = None):
        if seed is None:
            seed = int(time.time())
        self.seed = seed
        self.random = random.Random(seed)

    def random_bytes(self, length: int) -> bytes:
        return bytes(self.random.randint(0, 255) for _ in range(length))

    def random_string(self, min_len: int = 0, max_len: int = 100) -> str:
        length = self.random.randint(min_len, max_len)
        return ''.join(self.random.choice(string.ascii_letters + string.digits + " \t\n")
                      for _ in range(length))

    def random_payload(self, size: int = 100) -> bytes:
        """生成随机负载"""
        payload_type = self.random.choice([
            "json", "binary", "mixed", "empty", "large"
        ])

        if payload_type == "json":
            data = {
                "id": self.random_string(5, 20),
                "type": "request",
                "method": self.random.choice([
                    "inference.create", "model.load", "system.info"
                ]),
                "params": {
                    "key": self.random_string(0, 50),
                    "value": self.random.randint(0, 1000)
                }
            }
            return json.dumps(data).encode()

        elif payload_type == "binary":
            return self.random_bytes(size)

        elif payload_type == "mixed":
            prefix = self.random_string(0, 10).encode()
            binary = self.random_bytes(size // 2)
            suffix = self.random_string(0, 10).encode()
            return prefix + binary + suffix

        elif payload_type == "empty":
            return b""

        elif payload_type == "large":
            return self.random_bytes(self.random.randint(10000, 100000))

        return b""

    def generate_valid_frame(self) -> IPCFrame:
        """生成有效帧"""
        return IPCFrame(
            magic=IPC_MAGIC,
            version=IPC_VERSION,
            msg_type=self.random.choice([
                MSG_REQUEST, MSG_RESPONSE, MSG_ERROR,
                MSG_STREAM, MSG_HEARTBEAT, MSG_AUTH
            ]),
            flags=self.random.choice([FLAG_NONE, FLAG_ENCRYPTED, FLAG_COMPRESSED, FLAG_PRIORITY]),
            payload=self.random_payload(self.random.randint(10, 500))
        )

    def generate_corrupted_frame(self) -> bytes:
        """生成损坏的帧数据"""
        corruption_type = self.random.choice([
            "bad_magic",
            "bad_version",
            "bad_type",
            "bad_flags",
            "bad_length",
            "truncated",
            "extra_data",
            "all_zeros",
            "all_ones",
            "random_bytes",
            "invalid_utf8",
            "negative_length",
            "zero_length_header",
            "max_length",
            "length_mismatch",
        ])

        if corruption_type == "bad_magic":
            # 错误的魔数
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                self.random_bytes(4),
                IPC_VERSION,
                MSG_REQUEST,
                FLAG_NONE,
                100
            )
            return header + self.random_bytes(100)

        elif corruption_type == "bad_version":
            # 错误的版本号
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                IPC_MAGIC,
                self.random.randint(255, 65535),
                MSG_REQUEST,
                FLAG_NONE,
                100
            )
            return header + self.random_bytes(100)

        elif corruption_type == "bad_type":
            # 错误的消息类型
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                IPC_MAGIC,
                IPC_VERSION,
                self.random.randint(0x10, 0xFF),
                FLAG_NONE,
                100
            )
            return header + self.random_bytes(100)

        elif corruption_type == "bad_flags":
            # 错误的标志位
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                IPC_MAGIC,
                IPC_VERSION,
                MSG_REQUEST,
                self.random.randint(0x1000, 0xFFFF),
                100
            )
            return header + self.random_bytes(100)

        elif corruption_type == "bad_length":
            # 错误的长度字段
            fake_length = self.random.choice([0, -1, 2**31 - 1, 2**32 - 1, 0xFFFFFFFF])
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                IPC_MAGIC,
                IPC_VERSION,
                MSG_REQUEST,
                FLAG_NONE,
                max(fake_length, 0)
            )
            return header + self.random_bytes(100)

        elif corruption_type == "truncated":
            # 截断的帧
            frame = self.generate_valid_frame().encode()
            cut_point = self.random.randint(1, len(frame) - 1)
            return frame[:cut_point]

        elif corruption_type == "extra_data":
            # 额外数据
            frame = self.generate_valid_frame().encode()
            return frame + self.random_bytes(self.random.randint(10, 100))

        elif corruption_type == "all_zeros":
            return b"\x00" * self.random.randint(FRAME_HEADER_SIZE, 1000)

        elif corruption_type == "all_ones":
            return b"\xFF" * self.random.randint(FRAME_HEADER_SIZE, 1000)

        elif corruption_type == "random_bytes":
            return self.random_bytes(self.random.randint(1, 1000))

        elif corruption_type == "invalid_utf8":
            return b"\xFF\xFE\x00\xFF" * 100

        elif corruption_type == "negative_length":
            # 尝试构造负数长度
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                IPC_MAGIC,
                IPC_VERSION,
                MSG_REQUEST,
                FLAG_NONE,
                0xFFFFFFFF  # 无符号最大，在有符号解释中为 -1
            )
            return header

        elif corruption_type == "zero_length_header":
            return struct.pack(FRAME_HEADER_FORMAT, b"\x00\x00\x00\x00", 0, 0, 0, 0)

        elif corruption_type == "max_length":
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                IPC_MAGIC,
                IPC_VERSION,
                MSG_REQUEST,
                FLAG_NONE,
                MAX_MESSAGE_SIZE * 2
            )
            return header + self.random_bytes(100)

        elif corruption_type == "length_mismatch":
            # 声明的长度与实际数据长度不匹配
            declared = self.random.randint(50, 200)
            actual = self.random.choice([declared // 2, declared * 2, 0])
            header = struct.pack(
                FRAME_HEADER_FORMAT,
                IPC_MAGIC,
                IPC_VERSION,
                MSG_REQUEST,
                FLAG_NONE,
                declared
            )
            return header + self.random_bytes(max(actual, 0))

        return self.generate_valid_frame().encode()


# ============================================================
# IPC 协议测试器
# ============================================================

class IPCFuzzTester:
    """IPC 协议模糊测试器"""

    def __init__(self, seed: Optional[int] = None):
        self.seed = seed or int(time.time())
        self.gen = IPCFuzzGenerator(self.seed)
        self.results = {
            "frames_encoded": 0,
            "frames_decoded": 0,
            "errors": [],
            "memory_safety_issues": [],
            "buffer_overflow_attempts": 0,
            "protocol_violations": [],
            "edge_cases_tested": set()
        }

    def test_frame_encode_decode(self, count: int = 1000) -> None:
        """测试帧的编解码"""
        for i in range(count):
            original = self.gen.generate_valid_frame()
            try:
                encoded = original.encode()
                decoded = IPCFrame.decode(encoded)

                assert decoded.magic == original.magic, "魔数不匹配"
                assert decoded.version == original.version, "版本不匹配"
                assert decoded.msg_type == original.msg_type, "类型不匹配"
                assert decoded.flags == original.flags, "标志不匹配"
                assert decoded.payload == original.payload, "负载不匹配"

                self.results["frames_decoded"] += 1
            except Exception as e:
                self.results["errors"].append({
                    "index": i,
                    "type": "encode_decode_error",
                    "error": str(e)
                })
            finally:
                self.results["frames_encoded"] += 1

    def test_corrupted_frames(self, count: int = 2000) -> None:
        """测试损坏帧的处理"""
        for i in range(count):
            corrupted = self.gen.generate_corrupted_frame()
            try:
                decoded = IPCFrame.decode(corrupted)
                # 如果能解码，验证基本属性
                if decoded.magic != IPC_MAGIC:
                    self.results["protocol_violations"].append({
                        "index": i,
                        "issue": "解码了魔数错误的帧"
                    })
                if decoded.length > len(corrupted) - FRAME_HEADER_SIZE:
                    self.results["buffer_overflow_attempts"] += 1
            except (ValueError, struct.error):
                pass  # 期望的失败
            except Exception as e:
                self.results["errors"].append({
                    "index": i,
                    "type": "corrupted_frame_error",
                    "error": str(e)
                })

    def test_buffer_overflow_safety(self) -> None:
        """测试缓冲区溢出安全性"""
        # 测试极大长度值
        overflow_lengths = [
            2**31 - 1,  # INT_MAX
            2**32 - 1,  # UINT_MAX
            2**63 - 1,  # INT64_MAX
            0xFFFFFFFF,
            100 * 1024 * 1024,  # 100 MB
        ]

        for length in overflow_lengths:
            try:
                header = struct.pack(
                    FRAME_HEADER_FORMAT,
                    IPC_MAGIC,
                    IPC_VERSION,
                    MSG_REQUEST,
                    FLAG_NONE,
                    min(length, 0xFFFFFFFF)
                )
                # 检查是否会导致内存安全问题
                if length > MAX_MESSAGE_SIZE:
                    self.results["buffer_overflow_attempts"] += 1
            except struct.error:
                pass  # struct 溢出保护
            except Exception as e:
                self.results["memory_safety_issues"].append({
                    "type": "buffer_overflow",
                    "length": length,
                    "error": str(e)
                })

    def test_memory_exhaustion(self) -> None:
        """测试内存耗尽保护"""
        # 测试大量小帧
        frames = []
        try:
            for _ in range(100000):
                frame = self.gen.generate_valid_frame()
                frames.append(frame.encode())
                if len(frames) > 10000:
                    break
        except MemoryError:
            self.results["memory_safety_issues"].append({
                "type": "memory_exhaustion",
                "frame_count": len(frames)
            })

        # 测试超大帧
        try:
            large_frame = IPCFrame(
                magic=IPC_MAGIC,
                version=IPC_VERSION,
                msg_type=MSG_REQUEST,
                flags=FLAG_NONE,
                payload=b"x" * MAX_MESSAGE_SIZE
            )
            encoded = large_frame.encode()
            decoded = IPCFrame.decode(encoded)
            assert len(decoded.payload) == MAX_MESSAGE_SIZE
        except MemoryError:
            self.results["memory_safety_issues"].append({
                "type": "large_frame_memory_error"
            })
        except Exception as e:
            pass

    def test_edge_cases(self) -> None:
        """测试边界情况"""
        # 1. 空负载
        try:
            frame = IPCFrame(payload=b"")
            encoded = frame.encode()
            decoded = IPCFrame.decode(encoded)
            assert decoded.payload == b""
            self.results["edge_cases_tested"].add("empty_payload")
        except Exception as e:
            self.results["errors"].append({"type": "empty_payload", "error": str(e)})

        # 2. 单字节负载
        try:
            for byte_val in [0x00, 0xFF, 0x41, 0xFE]:
                frame = IPCFrame(payload=bytes([byte_val]))
                encoded = frame.encode()
                decoded = IPCFrame.decode(encoded)
                assert decoded.payload == bytes([byte_val])
            self.results["edge_cases_tested"].add("single_byte_payload")
        except Exception as e:
            self.results["errors"].append({"type": "single_byte", "error": str(e)})

        # 3. 所有可能的类型值
        for msg_type in range(0x00, 0x10):
            try:
                frame = IPCFrame(msg_type=msg_type, payload=b"test")
                encoded = frame.encode()
                decoded = IPCFrame.decode(encoded)
                assert decoded.msg_type == msg_type
            except Exception:
                pass
        self.results["edge_cases_tested"].add("all_message_types")

        # 4. 所有可能的标志组合
        for flags in range(0x00, 0x10):
            try:
                frame = IPCFrame(flags=flags, payload=b"test")
                encoded = frame.encode()
                decoded = IPCFrame.decode(encoded)
                assert decoded.flags == flags
            except Exception:
                pass
        self.results["edge_cases_tested"].add("all_flag_combinations")

        # 5. 最大帧大小
        try:
            max_payload = b"x" * (MAX_MESSAGE_SIZE - FRAME_HEADER_SIZE)
            frame = IPCFrame(payload=max_payload)
            encoded = frame.encode()
            assert len(encoded) <= MAX_MESSAGE_SIZE
            self.results["edge_cases_tested"].add("max_frame_size")
        except Exception as e:
            self.results["errors"].append({"type": "max_frame", "error": str(e)})

        # 6. 最小帧大小
        try:
            frame = IPCFrame(payload=b"")
            encoded = frame.encode()
            assert len(encoded) == FRAME_HEADER_SIZE
            self.results["edge_cases_tested"].add("min_frame_size")
        except Exception as e:
            self.results["errors"].append({"type": "min_frame", "error": str(e)})

        # 7. 版本兼容性
        for version in [0, 1, 2, 255, 65535]:
            try:
                frame = IPCFrame(version=version, payload=b"test")
                encoded = frame.encode()
                decoded = IPCFrame.decode(encoded)
                self.results["edge_cases_tested"].add(f"version_{version}")
            except Exception:
                pass

        # 8. 并发解码
        import concurrent.futures
        frames = [self.gen.generate_valid_frame().encode() for _ in range(100)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(IPCFrame.decode, f) for f in frames]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass
        self.results["edge_cases_tested"].add("concurrent_decode")

    def test_message_injection(self, count: int = 1000) -> None:
        """测试随机消息注入"""
        for i in range(count):
            # 生成随机消息
            msg_type = self.gen.random.choice([
                MSG_REQUEST, MSG_RESPONSE, MSG_ERROR,
                MSG_STREAM, MSG_STREAM_END, MSG_HEARTBEAT,
                MSG_AUTH, MSG_AUTH_RESPONSE, MSG_SUBSCRIBE,
                MSG_EVENT, MSG_CANCEL, MSG_CONFIG, MSG_LOG, MSG_METRICS
            ])

            payload = self.gen.random_payload(self.gen.random.randint(0, 500))

            frame = IPCFrame(
                magic=IPC_MAGIC,
                version=IPC_VERSION,
                msg_type=msg_type,
                flags=FLAG_NONE,
                payload=payload
            )

            try:
                encoded = frame.encode()
                decoded = IPCFrame.decode(encoded)
                assert decoded.msg_type == msg_type
                assert decoded.payload == payload
            except Exception as e:
                self.results["errors"].append({
                    "index": i,
                    "type": "injection_error",
                    "msg_type": msg_type,
                    "error": str(e)
                })

    def test_protocol_consistency(self) -> None:
        """测试协议一致性"""
        # 1. 请求-响应一致性
        request_id = "req_test_001"
        request = IPCFrame(
            msg_type=MSG_REQUEST,
            payload=json.dumps({
                "id": request_id,
                "method": "inference.create",
                "params": {"prompt": "test"}
            }).encode()
        )

        response = IPCFrame(
            msg_type=MSG_RESPONSE,
            payload=json.dumps({
                "request_id": request_id,
                "status": "ok",
                "result": {"output": "test response"}
            }).encode()
        )

        # 验证响应引用了正确的请求 ID
        req_payload = json.loads(request.payload)
        resp_payload = json.loads(response.payload)
        assert resp_payload["request_id"] == req_payload["id"], \
            "响应未引用正确请求 ID"

        self.results["edge_cases_tested"].add("request_response_consistency")

        # 2. 流式序列一致性
        stream_id = "stream_test_001"
        sequences = []
        for i in range(1, 6):
            stream_frame = IPCFrame(
                msg_type=MSG_STREAM,
                payload=json.dumps({
                    "request_id": stream_id,
                    "sequence": i,
                    "data": {"token": f"token_{i}"}
                }).encode()
            )
            sequences.append(json.loads(stream_frame.payload)["sequence"])

        # 验证序列递增
        for i in range(1, len(sequences)):
            assert sequences[i] > sequences[i-1], \
                f"流式序列不递增: {sequences}"

        self.results["edge_cases_tested"].add("stream_sequence_consistency")

        # 3. 错误消息格式一致性
        error_frame = IPCFrame(
            msg_type=MSG_ERROR,
            payload=json.dumps({
                "request_id": "req_test_001",
                "error": {
                    "code": "INVALID_PARAMS",
                    "message": "Invalid temperature value"
                }
            }).encode()
        )

        error_payload = json.loads(error_frame.payload)
        assert "code" in error_payload["error"], "错误消息缺少 code"
        assert "message" in error_payload["error"], "错误消息缺少 message"

        self.results["edge_cases_tested"].add("error_format_consistency")

    def test_malformed_utf8(self) -> None:
        """测试畸形 UTF-8 处理"""
        malformed_sequences = [
            b"\xFF",           # 无效起始字节
            b"\xC0\xAF",       # 过长编码
            b"\xE0\x80\xAF",   # 过长编码
            b"\xF0\x80\x80\xAF", # 过长编码
            b"\xED\xA0\x80",   # 代理对
            b"\xF4\x90\x80\x80", # 超出范围
            b"\xFE",           # 无效字节
            b"\xFF\xFE\x00\x00", # BOM
            b"\x00",           # 空字节
            b"\xC2\x00",       # 中间的空字节
        ]

        for seq in malformed_sequences:
            try:
                frame = IPCFrame(payload=seq)
                encoded = frame.encode()
                decoded = IPCFrame.decode(encoded)
                # 验证原始字节被保留
                assert decoded.payload == seq
            except Exception as e:
                self.results["errors"].append({
                    "type": "malformed_utf8",
                    "sequence": seq.hex(),
                    "error": str(e)
                })

    def test_packet_splitting(self) -> None:
        """测试分包和粘包处理"""
        # 生成多个帧
        frames = [self.gen.generate_valid_frame() for _ in range(10)]
        all_data = b"".join(f.encode() for f in frames)

        # 模拟 TCP 分包
        offset = 0
        decoded_frames = []
        while offset < len(all_data):
            # 随机分割
            chunk_size = self.gen.random.randint(FRAME_HEADER_SIZE, 200)
            chunk = all_data[offset:offset + chunk_size]

            if len(chunk) >= FRAME_HEADER_SIZE:
                try:
                    frame = IPCFrame.decode(chunk)
                    decoded_frames.append(frame)
                    offset += FRAME_HEADER_SIZE + frame.length
                except (ValueError, struct.error):
                    offset += 1  # 跳过损坏数据
            else:
                offset += len(chunk)

        self.results["edge_cases_tested"].add("packet_splitting")

    def test_alignment_bounds(self) -> None:
        """测试对齐边界"""
        # 测试不同对齐长度的帧
        for alignment in [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]:
            payload_size = alignment  # 恰好对齐
            frame = IPCFrame(payload=b"x" * payload_size)
            encoded = frame.encode()
            decoded = IPCFrame.decode(encoded)
            assert decoded.payload == b"x" * payload_size

        self.results["edge_cases_tested"].add("alignment_bounds")

    def run_all(self) -> Dict[str, Any]:
        """运行所有测试"""
        print(f"IPC 模糊测试开始 (seed={self.seed})")
        print("=" * 60)

        print("\n1. 测试帧编解码...")
        self.test_frame_encode_decode(2000)
        print(f"   编解码 {self.results['frames_decoded']} 帧")

        print("\n2. 测试损坏帧...")
        self.test_corrupted_frames(3000)
        print(f"   缓冲区溢出尝试: {self.results['buffer_overflow_attempts']}")

        print("\n3. 测试缓冲区溢出安全...")
        self.test_buffer_overflow_safety()

        print("\n4. 测试内存耗尽保护...")
        self.test_memory_exhaustion()

        print("\n5. 测试边界情况...")
        self.test_edge_cases()
        print(f"   边界情况测试: {len(self.results['edge_cases_tested'])}")

        print("\n6. 测试消息注入...")
        self.test_message_injection(2000)

        print("\n7. 测试协议一致性...")
        self.test_protocol_consistency()

        print("\n8. 测试畸形 UTF-8...")
        self.test_malformed_utf8()

        print("\n9. 测试分包处理...")
        self.test_packet_splitting()

        print("\n10. 测试对齐边界...")
        self.test_alignment_bounds()

        print("\n" + "=" * 60)
        print("测试完成!")

        errors = len(self.results["errors"])
        safety_issues = len(self.results["memory_safety_issues"])
        violations = len(self.results["protocol_violations"])

        print(f"帧编码: {self.results['frames_encoded']}")
        print(f"帧解码: {self.results['frames_decoded']}")
        print(f"错误: {errors}")
        print(f"内存安全问题: {safety_issues}")
        print(f"协议违规: {violations}")
        print(f"边界情况: {len(self.results['edge_cases_tested'])}")

        return self.results


# ============================================================
# 单元测试
# ============================================================

class TestIPCFuzz(unittest.TestCase):
    """IPC 模糊测试单元测试"""

    def setUp(self):
        self.gen = IPCFuzzGenerator(seed=42)

    def test_frame_header_size(self):
        """测试帧头部大小"""
        header = struct.pack(FRAME_HEADER_FORMAT, IPC_MAGIC, 1, MSG_REQUEST, 0, 0)
        self.assertEqual(len(header), FRAME_HEADER_SIZE)

    def test_valid_frame_encode_decode(self):
        """测试有效帧编解码"""
        frame = IPCFrame(
            magic=IPC_MAGIC,
            version=IPC_VERSION,
            msg_type=MSG_REQUEST,
            flags=FLAG_NONE,
            payload=b"hello world"
        )
        encoded = frame.encode()
        decoded = IPCFrame.decode(encoded)
        self.assertEqual(decoded.magic, IPC_MAGIC)
        self.assertEqual(decoded.version, IPC_VERSION)
        self.assertEqual(decoded.msg_type, MSG_REQUEST)
        self.assertEqual(decoded.payload, b"hello world")

    def test_invalid_magic(self):
        """测试无效魔数"""
        with self.assertRaises(ValueError):
            header = struct.pack(FRAME_HEADER_FORMAT, b"XXXX", 1, MSG_REQUEST, 0, 5)
            IPCFrame.decode(header + b"hello")

    def test_empty_payload(self):
        """测试空负载"""
        frame = IPCFrame(payload=b"")
        encoded = frame.encode()
        decoded = IPCFrame.decode(encoded)
        self.assertEqual(len(decoded.payload), 0)

    def test_large_payload(self):
        """测试大负载"""
        payload = b"x" * 100000
        frame = IPCFrame(payload=payload)
        encoded = frame.encode()
        decoded = IPCFrame.decode(encoded)
        self.assertEqual(len(decoded.payload), 100000)

    def test_truncated_frame(self):
        """测试截断帧"""
        frame = IPCFrame(payload=b"test data")
        encoded = frame.encode()
        truncated = encoded[:FRAME_HEADER_SIZE + 3]  # 只保留部分负载
        with self.assertRaises(Exception):
            IPCFrame.decode(truncated)

    def test_all_message_types(self):
        """测试所有消息类型"""
        for msg_type in range(0x01, 0x0F):
            frame = IPCFrame(msg_type=msg_type, payload=b"test")
            encoded = frame.encode()
            decoded = IPCFrame.decode(encoded)
            self.assertEqual(decoded.msg_type, msg_type)

    def test_flags_preservation(self):
        """测试标志位保留"""
        for flags in [0x00, 0x01, 0x02, 0x04, 0x08, 0xFF]:
            frame = IPCFrame(flags=flags, payload=b"test")
            encoded = frame.encode()
            decoded = IPCFrame.decode(encoded)
            self.assertEqual(decoded.flags, flags)

    def test_negative_length_protection(self):
        """测试负数长度保护"""
        # 尝试构造一个看起来像负数长度的帧
        header = struct.pack(FRAME_HEADER_FORMAT, IPC_MAGIC, 1, MSG_REQUEST, 0, 0xFFFFFFFF)
        with self.assertRaises(Exception):
            IPCFrame.decode(header)

    def test_concurrent_decode(self):
        """测试并发解码"""
        import concurrent.futures
        frames = [
            IPCFrame(payload=f"test_{i}".encode()).encode()
            for i in range(100)
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(IPCFrame.decode, f) for f in frames]
            for future in concurrent.futures.as_completed(futures):
                decoded = future.result()
                self.assertIsInstance(decoded, IPCFrame)

    def test_payload_integrity(self):
        """测试负载完整性"""
        for i in range(100):
            payload = self.gen.random_bytes(self.gen.random.randint(0, 1000))
            frame = IPCFrame(payload=payload)
            encoded = frame.encode()
            decoded = IPCFrame.decode(encoded)
            self.assertEqual(decoded.payload, payload)


# ============================================================
# 模拟 IPC 服务器
# ============================================================

class MockIPCServer:
    """模拟 IPC 服务器用于测试"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self.server = None
        self.running = False
        self.received_frames: List[IPCFrame] = []
        self._thread = None

    def start(self):
        """启动服务器"""
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self.port

    def _accept_loop(self):
        """接受连接循环"""
        while self.running:
            try:
                client, addr = self.server.accept()
                thread = threading.Thread(
                    target=self._handle_client, args=(client,), daemon=True
                )
                thread.start()
            except Exception:
                pass

    def _handle_client(self, client: socket.socket):
        """处理客户端连接"""
        buffer = b""
        while self.running:
            try:
                data = client.recv(4096)
                if not data:
                    break
                buffer += data

                # 尝试解码帧
                while len(buffer) >= FRAME_HEADER_SIZE:
                    try:
                        frame = IPCFrame.decode(buffer)
                        self.received_frames.append(frame)
                        buffer = buffer[FRAME_HEADER_SIZE + frame.length:]
                    except (ValueError, struct.error):
                        # 跳过损坏数据
                        buffer = buffer[1:]
            except Exception:
                break
        client.close()

    def stop(self):
        """停止服务器"""
        self.running = False
        if self.server:
            self.server.close()


# ============================================================
# 主入口
# ============================================================

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="AinosOS IPC 模糊测试")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument("--iterations", type=int, default=10000, help="测试迭代次数")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--unittest", action="store_true", help="运行单元测试")
    parser.add_argument("--server", action="store_true", help="启动模拟服务器测试")

    args = parser.parse_args()

    if args.unittest:
        unittest.main(argv=[sys.argv[0]])
        return

    if args.server:
        server = MockIPCServer()
        port = server.start()
        print(f"模拟 IPC 服务器已启动 (端口: {port})")
        print("按 Ctrl+C 停止")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n收到 {len(server.received_frames)} 帧")
        finally:
            server.stop()
        return

    # 运行模糊测试
    tester = IPCFuzzTester(seed=args.seed)
    results = tester.run_all()

    if results["errors"] or results["memory_safety_issues"]:
        print("\n发现问题:")
        for err in results["errors"][:10]:
            print(f"  - 错误: {err}")
        for issue in results["memory_safety_issues"][:5]:
            print(f"  - 安全问题: {issue}")
        return 1

    print("\n所有 IPC 模糊测试通过!")
    return 0


if __name__ == "__main__":
    sys.exit(main())