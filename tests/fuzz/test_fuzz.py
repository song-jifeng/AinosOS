#!/usr/bin/env python3
"""AinosOS 模糊测试 - 随机 IPC 消息生成和协议一致性测试"""

import json
import random
import string
import struct
import sys
import os
import time
import hashlib
import unittest
import tempfile
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

# ============================================================
# 测试配置
# ============================================================

TEST_CONFIG = {
    "max_message_size": 10 * 1024 * 1024,  # 10 MB
    "max_nesting_depth": 20,
    "max_string_length": 10000,
    "max_array_length": 1000,
    "fuzz_iterations": 10000,
    "random_seed_range": (0, 2**32 - 1),
    "protocol_version": "1.0",
    "supported_methods": [
        "inference.create",
        "inference.stream",
        "inference.batch",
        "inference.cancel",
        "model.load",
        "model.unload",
        "model.list",
        "model.info",
        "system.info",
        "system.stats",
        "system.health",
        "system.config",
        "system.shutdown",
    ],
    "message_types": [
        "request", "response", "error", "stream",
        "stream_end", "heartbeat", "auth", "auth_response",
        "subscribe", "event", "cancel", "config_update", "log", "metrics"
    ],
    "error_codes": [
        "OK", "BAD_REQUEST", "UNAUTHORIZED", "FORBIDDEN", "NOT_FOUND",
        "METHOD_NOT_ALLOWED", "REQUEST_TIMEOUT", "RATE_LIMITED",
        "INTERNAL_ERROR", "NOT_IMPLEMENTED", "SERVICE_UNAVAILABLE",
        "MODEL_NOT_LOADED", "MODEL_LOADING", "CONTEXT_FULL",
        "MEMORY_EXHAUSTED", "GPU_UNAVAILABLE", "INVALID_PARAMS",
        "PARAM_OUT_OF_RANGE", "MISSING_PARAM", "PROTOCOL_ERROR",
        "VERSION_MISMATCH", "MESSAGE_TOO_LARGE"
    ]
}


# ============================================================
# 随机数据生成器
# ============================================================

class RandomGenerator:
    """随机数据生成器，用于模糊测试"""

    def __init__(self, seed: Optional[int] = None):
        if seed is None:
            seed = random.randint(*TEST_CONFIG["random_seed_range"])
        self.seed = seed
        self.random = random.Random(seed)

    def reset(self, seed: Optional[int] = None):
        if seed is None:
            seed = self.seed
        self.random = random.Random(seed)

    def random_string(self, min_len: int = 0, max_len: int = 100) -> str:
        """生成随机字符串"""
        length = self.random.randint(min_len, max_len)
        chars = string.ascii_letters + string.digits + string.punctuation + " \t\n"
        # 偶尔包含 unicode
        if self.random.random() < 0.1:
            chars += "你好世界こんにちは안녕하세요"
        return "".join(self.random.choice(chars) for _ in range(length))

    def random_int(self, min_val: int = -2**63, max_val: int = 2**63 - 1) -> int:
        """生成随机整数"""
        if self.random.random() < 0.05:
            # 边界值
            return self.random.choice([0, 1, -1, 2**31 - 1, -2**31, 2**63 - 1, -2**63])
        return self.random.randint(min_val, max_val)

    def random_float(self) -> float:
        """生成随机浮点数"""
        if self.random.random() < 0.05:
            return self.random.choice([0.0, 1.0, -1.0, float('inf'), float('-inf'), float('nan')])
        if self.random.random() < 0.1:
            return self.random.randint(-100, 100) * 1.0
        return self.random.uniform(-1000, 1000)

    def random_bool(self) -> bool:
        """生成随机布尔值"""
        return self.random.choice([True, False, True, False, True, False, None])

    def random_null(self) -> None:
        """生成 None"""
        return None

    def random_value(self, depth: int = 0) -> Any:
        """生成随机 JSON 值"""
        if depth > TEST_CONFIG["max_nesting_depth"]:
            return self.random_string(0, 50)

        choices = [
            lambda: self.random_string(0, 100),
            lambda: self.random_int(),
            lambda: self.random_float(),
            lambda: self.random_bool(),
            lambda: self.random_null(),
            lambda: self.random_object(depth + 1),
            lambda: self.random_array(depth + 1),
        ]

        weights = [30, 20, 10, 10, 5, 15, 10]
        return self.random.choices(choices, weights=weights, k=1)[0]()

    def random_object(self, depth: int = 0) -> Dict[str, Any]:
        """生成随机 JSON 对象"""
        obj = {}
        num_keys = self.random.randint(0, 10)
        for _ in range(num_keys):
            key = self.random_string(0, 30)
            # 偶尔包含特殊字符的键
            if self.random.random() < 0.05:
                key = "\x00" + key + "\x00"
            obj[key] = self.random_value(depth + 1)
        return obj

    def random_array(self, depth: int = 0) -> List[Any]:
        """生成随机 JSON 数组"""
        length = self.random.randint(0, 20)
        return [self.random_value(depth + 1) for _ in range(length)]

    def random_bytes(self, length: int = 100) -> bytes:
        """生成随机字节"""
        return bytes(self.random.randint(0, 255) for _ in range(length))


# ============================================================
# IPC 消息生成器
# ============================================================

class IPCMessageGenerator:
    """IPC 消息生成器"""

    def __init__(self, seed: Optional[int] = None):
        self.gen = RandomGenerator(seed)
        self.sequence = 0

    def generate_message_id(self, prefix: str = "msg") -> str:
        """生成消息 ID"""
        self.sequence += 1
        timestamp = int(time.time() * 1000)
        rand = ''.join(self.gen.random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"{prefix}_{timestamp}_{rand}"

    def generate_base_message(self) -> Dict[str, Any]:
        """生成基础消息结构"""
        msg = {
            "id": self.generate_message_id(),
            "type": self.gen.random.choice(TEST_CONFIG["message_types"]),
            "version": TEST_CONFIG["protocol_version"],
            "timestamp": int(time.time() * 1000) + self.gen.random.randint(-1000, 1000),
        }

        # 可选字段
        if self.gen.random.random() < 0.3:
            msg["ttl"] = self.gen.random.randint(1000, 60000)
        if self.gen.random.random() < 0.3:
            msg["source"] = self.gen.random_string(0, 30)
        if self.gen.random.random() < 0.3:
            msg["target"] = self.gen.random_string(0, 30)

        return msg

    def generate_request(self) -> Dict[str, Any]:
        """生成随机请求消息"""
        msg = self.generate_base_message()
        msg["type"] = "request"
        msg["method"] = self.gen.random.choice(TEST_CONFIG["supported_methods"])
        msg["params"] = self.gen.random_object()

        # 添加认证信息
        if self.gen.random.random() < 0.3:
            msg["auth"] = {
                "token": self.gen.random_string(20, 100),
                "scope": self.gen.random.choice([
                    ["inference"], ["inference", "models"], ["admin"], []
                ])
            }

        return msg

    def generate_response(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """生成随机响应消息"""
        msg = self.generate_base_message()
        msg["type"] = "response"
        msg["request_id"] = request_id or self.generate_message_id("req")
        msg["status"] = self.gen.random.choice(["ok", "error", "streaming"])
        msg["result"] = self.gen.random_object()
        return msg

    def generate_error(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """生成随机错误消息"""
        msg = self.generate_base_message()
        msg["type"] = "error"
        msg["request_id"] = request_id or self.generate_message_id("req")
        msg["error"] = {
            "code": self.gen.random.choice(TEST_CONFIG["error_codes"]),
            "message": self.gen.random_string(0, 200),
            "details": self.gen.random_object() if self.gen.random.random() < 0.5 else {}
        }
        return msg

    def generate_stream(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """生成随机流式消息"""
        msg = self.generate_base_message()
        msg["type"] = "stream"
        msg["request_id"] = request_id or self.generate_message_id("req")
        msg["sequence"] = self.gen.random.randint(1, 10000)
        msg["data"] = {
            "token": self.gen.random_string(0, 50),
            "logprob": self.gen.random_float(),
            "finish_reason": self.gen.random.choice([None, "stop", "length", "error"])
        }
        return msg

    def generate_stream_end(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """生成随机流式结束消息"""
        msg = self.generate_base_message()
        msg["type"] = "stream_end"
        msg["request_id"] = request_id or self.generate_message_id("req")
        msg["sequence"] = self.gen.random.randint(1, 10000)
        msg["usage"] = {
            "prompt_tokens": self.gen.random.randint(1, 10000),
            "completion_tokens": self.gen.random.randint(1, 10000),
            "total_tokens": self.gen.random.randint(1, 20000)
        }
        msg["finish_reason"] = self.gen.random.choice(["stop", "length", "error"])
        return msg

    def generate_heartbeat(self) -> Dict[str, Any]:
        """生成随机心跳消息"""
        msg = self.generate_base_message()
        msg["type"] = "heartbeat"
        msg["source"] = self.gen.random_string(0, 30)
        msg["status"] = {
            "load": self.gen.random_float(),
            "active_requests": self.gen.random_int(0, 100),
            "memory_used_mb": self.gen.random_int(0, 100000)
        }
        return msg

    def generate_auth(self) -> Dict[str, Any]:
        """生成随机认证消息"""
        msg = self.generate_base_message()
        msg["type"] = "auth"
        msg["method"] = self.gen.random.choice(["jwt", "api_key", "none"])
        msg["credentials"] = {
            "token": self.gen.random_string(20, 200),
            "api_key": self.gen.random_string(30, 50)
        }
        return msg

    def generate_random_message(self) -> Dict[str, Any]:
        """生成随机类型的消息"""
        generators = [
            self.generate_request,
            self.generate_response,
            self.generate_error,
            self.generate_stream,
            self.generate_stream_end,
            self.generate_heartbeat,
            self.generate_auth,
        ]
        weights = [30, 20, 10, 15, 5, 10, 10]
        return self.gen.random.choices(generators, weights=weights, k=1)[0]()

    def generate_corrupted_message(self) -> str:
        """生成损坏的消息"""
        corruption_type = self.gen.random.choice([
            "truncated_json",
            "extra_fields",
            "missing_fields",
            "wrong_types",
            "invalid_unicode",
            "binary_data",
            "nested_too_deep",
            "duplicate_keys",
            "very_large",
            "empty",
        ])

        if corruption_type == "truncated_json":
            msg = json.dumps(self.generate_random_message())
            cut = self.gen.random.randint(1, len(msg))
            return msg[:cut]

        elif corruption_type == "extra_fields":
            msg = self.generate_random_message()
            msg.update(self.gen.random_object())
            return json.dumps(msg)

        elif corruption_type == "missing_fields":
            msg = self.generate_random_message()
            keys = list(msg.keys())
            for _ in range(self.gen.random.randint(1, len(keys))):
                key = self.gen.random.choice(keys)
                if key in ("id", "type"):  # 保留必需字段
                    continue
                del msg[key]
            return json.dumps(msg)

        elif corruption_type == "wrong_types":
            msg = self.generate_random_message()
            for key in msg:
                if self.gen.random.random() < 0.3:
                    if isinstance(msg[key], str):
                        msg[key] = self.gen.random_int()
                    elif isinstance(msg[key], (int, float)):
                        msg[key] = self.gen.random_string()
                    elif isinstance(msg[key], dict):
                        msg[key] = self.gen.random_array()
                    elif isinstance(msg[key], list):
                        msg[key] = self.gen.random_object()
            return json.dumps(msg)

        elif corruption_type == "invalid_unicode":
            return self.gen.random_bytes(100).decode('latin-1')

        elif corruption_type == "binary_data":
            return self.gen.random_bytes(1000).decode('latin-1')

        elif corruption_type == "nested_too_deep":
            obj = {}
            current = obj
            for _ in range(100):
                current["nested"] = {}
                current = current["nested"]
            return json.dumps(obj)

        elif corruption_type == "duplicate_keys":
            # 构造带重复键的 JSON
            parts = ['{"key": "value1", "key": "value2", "key": "value3"}']
            return parts[0]

        elif corruption_type == "very_large":
            # 生成超大消息
            large_data = "x" * TEST_CONFIG["max_message_size"] * 2
            msg = {"data": large_data}
            return json.dumps(msg)

        elif corruption_type == "empty":
            return ""

        return json.dumps(self.generate_random_message())


# ============================================================
# 模糊测试器
# ============================================================

class FuzzTester:
    """模糊测试器"""

    def __init__(self, seed: Optional[int] = None):
        self.seed = seed or int(time.time())
        self.gen = IPCMessageGenerator(self.seed)
        self.results = {
            "total_messages": 0,
            "valid_messages": 0,
            "invalid_messages": 0,
            "corrupted_messages": 0,
            "errors": [],
            "protocol_violations": [],
            "boundary_hits": []
        }

    def test_valid_messages(self, count: int = 1000) -> None:
        """测试有效消息的生成和解析"""
        for i in range(count):
            msg = self.gen.generate_random_message()
            try:
                json_str = json.dumps(msg)
                parsed = json.loads(json_str)

                # 验证必需字段
                assert "id" in parsed, "消息缺少 id 字段"
                assert "type" in parsed, "消息缺少 type 字段"
                assert parsed["id"], "id 字段为空"

                self.results["valid_messages"] += 1
            except Exception as e:
                self.results["errors"].append({
                    "index": i,
                    "type": "valid_message_error",
                    "error": str(e)
                })
            finally:
                self.results["total_messages"] += 1

    def test_corrupted_messages(self, count: int = 1000) -> None:
        """测试损坏消息的解析"""
        for i in range(count):
            corrupted = self.gen.generate_corrupted_message()
            try:
                parsed = json.loads(corrupted)
                # 如果能解析，检查是否违反协议
                if not isinstance(parsed, dict):
                    self.results["protocol_violations"].append({
                        "index": i,
                        "issue": "消息不是 JSON 对象"
                    })
                elif "id" not in parsed:
                    self.results["protocol_violations"].append({
                        "index": i,
                        "issue": "缺少 id 字段"
                    })
                self.results["corrupted_messages"] += 1
            except (json.JSONDecodeError, ValueError):
                # 期望的解析失败
                pass
            except Exception as e:
                self.results["errors"].append({
                    "index": i,
                    "type": "corrupted_message_error",
                    "error": str(e)
                })
            finally:
                self.results["total_messages"] += 1

    def test_boundary_values(self) -> None:
        """测试边界值"""
        # 超大整数
        for val in [0, 1, -1, 2**31, 2**32, 2**63 - 1, -2**63]:
            try:
                msg = {"id": "boundary_test", "type": "request", "value": val}
                json.dumps(msg)
                self.results["boundary_hits"].append({
                    "type": "integer_boundary",
                    "value": val
                })
            except Exception as e:
                self.results["errors"].append({
                    "type": "boundary_error",
                    "value": val,
                    "error": str(e)
                })

        # 超大浮点数
        for val in [0.0, 1e-300, 1e300, float('inf'), float('-inf')]:
            try:
                msg = {"id": "boundary_test", "type": "request", "value": val}
                json.dumps(msg)
            except Exception as e:
                self.results["errors"].append({
                    "type": "float_boundary_error",
                    "value": val,
                    "error": str(e)
                })

        # 空字符串
        try:
            msg = {"id": "", "type": "request", "prompt": ""}
            json.dumps(msg)
        except Exception as e:
            self.results["errors"].append({
                "type": "empty_string_error",
                "error": str(e)
            })

        # 超大字符串
        try:
            large_str = "x" * TEST_CONFIG["max_string_length"]
            msg = {"id": "large_test", "type": "request", "data": large_str}
            json.dumps(msg)
        except Exception as e:
            self.results["errors"].append({
                "type": "large_string_error",
                "error": str(e)
            })

    def test_protocol_consistency(self, count: int = 500) -> None:
        """测试协议一致性"""
        for i in range(count):
            msg = self.gen.generate_random_message()
            msg_type = msg.get("type")

            # 检查消息类型一致性
            if msg_type == "request":
                assert "method" in msg, "请求消息缺少 method 字段"
                assert "params" in msg, "请求消息缺少 params 字段"

            elif msg_type == "response":
                assert "request_id" in msg, "响应消息缺少 request_id 字段"
                assert "status" in msg, "响应消息缺少 status 字段"
                assert msg["status"] in ("ok", "error", "streaming"), \
                    f"无效的状态值: {msg['status']}"

            elif msg_type == "error":
                assert "request_id" in msg, "错误消息缺少 request_id 字段"
                assert "error" in msg, "错误消息缺少 error 字段"
                assert "code" in msg["error"], "错误消息缺少 error.code 字段"
                assert "message" in msg["error"], "错误消息缺少 error.message 字段"

            elif msg_type == "stream":
                assert "request_id" in msg, "流式消息缺少 request_id 字段"
                assert "sequence" in msg, "流式消息缺少 sequence 字段"
                assert "data" in msg, "流式消息缺少 data 字段"

                # 检查序列号
                if hasattr(self, '_last_sequence'):
                    if msg.get("sequence", 0) <= self._last_sequence.get(msg["request_id"], 0):
                        self.results["protocol_violations"].append({
                            "index": i,
                            "issue": f"流式序列号不递增: {msg['sequence']}"
                        })
                if not hasattr(self, '_last_sequence'):
                    self._last_sequence = {}
                self._last_sequence[msg.get("request_id", "")] = msg.get("sequence", 0)

            elif msg_type == "stream_end":
                assert "finish_reason" in msg, "流式结束消息缺少 finish_reason 字段"

            elif msg_type == "heartbeat":
                assert "source" in msg, "心跳消息缺少 source 字段"

            elif msg_type == "auth":
                assert "method" in msg, "认证消息缺少 method 字段"
                assert "credentials" in msg, "认证消息缺少 credentials 字段"

    def test_ndjson_parsing(self, count: int = 500) -> None:
        """测试 NDJSON 解析"""
        lines = []
        for _ in range(count):
            msg = self.gen.generate_random_message()
            lines.append(json.dumps(msg))

        ndjson_data = "\n".join(lines) + "\n"

        # 解析 NDJSON
        parsed_lines = []
        for line in ndjson_data.strip().split("\n"):
            if line.strip():
                try:
                    parsed_lines.append(json.loads(line))
                except json.JSONDecodeError:
                    self.results["protocol_violations"].append({
                        "issue": "NDJSON 解析失败"
                    })

        assert len(parsed_lines) == count, \
            f"NDJSON 解析数量不匹配: {len(parsed_lines)} vs {count}"

    def test_sequence_validation(self, count: int = 200) -> None:
        """测试流式序列验证"""
        # 生成递增序列
        request_id = self.gen.generate_message_id("req")
        sequences = []
        for i in range(1, count + 1):
            msg = {
                "id": self.gen.generate_message_id("str"),
                "type": "stream",
                "request_id": request_id,
                "sequence": i,
                "data": {"token": self.gen.random_string(0, 10)}
            }
            sequences.append(msg)

        # 验证序列
        for i, msg in enumerate(sequences):
            assert msg["sequence"] == i + 1, \
                f"序列号错误: 期望 {i+1}, 实际 {msg['sequence']}"

        # 测试乱序
        if len(sequences) > 2:
            sequences[0], sequences[1] = sequences[1], sequences[0]
            has_disorder = False
            for i in range(1, len(sequences)):
                if sequences[i]["sequence"] <= sequences[i-1]["sequence"]:
                    has_disorder = True
                    break
            assert has_disorder, "应检测到乱序"

    def test_auth_flow(self) -> None:
        """测试认证流程"""
        # 认证请求
        auth_msg = {
            "id": self.gen.generate_message_id("auth"),
            "type": "auth",
            "version": TEST_CONFIG["protocol_version"],
            "timestamp": int(time.time() * 1000),
            "method": "jwt",
            "credentials": {
                "token": self.gen.random_string(50, 100)
            }
        }
        assert auth_msg["type"] == "auth"
        assert "credentials" in auth_msg

        # 认证响应
        auth_resp = {
            "id": self.gen.generate_message_id("auth_resp"),
            "type": "auth_response",
            "version": TEST_CONFIG["protocol_version"],
            "timestamp": int(time.time() * 1000),
            "status": "ok",
            "session": {
                "id": self.gen.generate_message_id("sess"),
                "expires_at": int(time.time() * 1000) + 86400000,
                "scope": ["inference", "models"]
            }
        }
        assert auth_resp["type"] == "auth_response"
        assert auth_resp["status"] in ("ok", "error")

    def test_error_handling(self) -> None:
        """测试错误处理"""
        # 测试所有错误码
        for error_code in TEST_CONFIG["error_codes"]:
            error_msg = {
                "id": self.gen.generate_message_id("err"),
                "type": "error",
                "version": TEST_CONFIG["protocol_version"],
                "timestamp": int(time.time() * 1000),
                "request_id": self.gen.generate_message_id("req"),
                "error": {
                    "code": error_code,
                    "message": self.gen.random_string(10, 100),
                    "details": {}
                }
            }
            parsed = json.loads(json.dumps(error_msg))
            assert parsed["error"]["code"] == error_code

    def run_all(self) -> Dict[str, Any]:
        """运行所有测试"""
        print(f"模糊测试开始 (seed={self.seed})")
        print("=" * 50)

        print("\n1. 测试有效消息生成...")
        self.test_valid_messages(2000)
        print(f"   生成 {self.results['valid_messages']} 条有效消息")

        print("\n2. 测试损坏消息...")
        self.test_corrupted_messages(2000)
        print(f"   生成 {self.results['corrupted_messages']} 条损坏消息")

        print("\n3. 测试边界值...")
        self.test_boundary_values()
        print(f"   测试了 {len(self.results['boundary_hits'])} 个边界值")

        print("\n4. 测试协议一致性...")
        self.test_protocol_consistency(1000)

        print("\n5. 测试 NDJSON 解析...")
        self.test_ndjson_parsing(500)

        print("\n6. 测试序列验证...")
        self.test_sequence_validation(200)

        print("\n7. 测试认证流程...")
        self.test_auth_flow()

        print("\n8. 测试错误处理...")
        self.test_error_handling()

        print("\n" + "=" * 50)
        print(f"测试完成!")

        # 统计
        errors = len(self.results["errors"])
        violations = len(self.results["protocol_violations"])
        print(f"总消息数: {self.results['total_messages']}")
        print(f"有效消息: {self.results['valid_messages']}")
        print(f"损坏消息: {self.results['corrupted_messages']}")
        print(f"错误数: {errors}")
        print(f"协议违规: {violations}")

        return self.results


# ============================================================
# 单元测试
# ============================================================

class TestFuzz(unittest.TestCase):
    """模糊测试单元测试"""

    def setUp(self):
        self.fuzzer = FuzzTester(seed=42)

    def test_message_generation(self):
        """测试消息生成"""
        gen = IPCMessageGenerator(seed=123)
        for _ in range(100):
            msg = gen.generate_random_message()
            self.assertIn("id", msg)
            self.assertIn("type", msg)
            self.assertIn("version", msg)

    def test_request_validation(self):
        """测试请求消息验证"""
        gen = IPCMessageGenerator(seed=456)
        for _ in range(50):
            req = gen.generate_request()
            self.assertEqual(req["type"], "request")
            self.assertIn("method", req)
            self.assertIn("params", req)

    def test_stream_sequence(self):
        """测试流式序列"""
        gen = IPCMessageGenerator(seed=789)
        request_id = gen.generate_message_id("req")
        for i in range(1, 10):
            msg = gen.generate_stream(request_id)
            if msg.get("request_id") == request_id:
                self.assertGreater(msg.get("sequence", 0), 0)

    def test_ndjson_encode_decode(self):
        """测试 NDJSON 编解码"""
        gen = IPCMessageGenerator(seed=101)
        messages = [gen.generate_random_message() for _ in range(50)]
        ndjson = "\n".join(json.dumps(m) for m in messages) + "\n"

        parsed = []
        for line in ndjson.strip().split("\n"):
            if line.strip():
                parsed.append(json.loads(line))

        self.assertEqual(len(parsed), len(messages))

    def test_corrupted_message_resilience(self):
        """测试损坏消息的容错性"""
        gen = IPCMessageGenerator(seed=202)
        for _ in range(100):
            corrupted = gen.generate_corrupted_message()
            try:
                json.loads(corrupted)
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                pass  # 期望的失败

    def test_empty_message(self):
        """测试空消息"""
        with self.assertRaises(json.JSONDecodeError):
            json.loads("")

    def test_invalid_json(self):
        """测试无效 JSON"""
        invalid_inputs = [
            "{invalid}",
            "{'single': 'quotes'}",
            "[1, 2, 3",  # 不完整
            "null",
            "undefined",
            "{x: 1}",
        ]
        for invalid in invalid_inputs:
            with self.assertRaises(json.JSONDecodeError):
                json.loads(invalid)

    def test_unicode_handling(self):
        """测试 Unicode 处理"""
        gen = IPCMessageGenerator(seed=303)
        for _ in range(50):
            msg = gen.generate_random_message()
            msg["text"] = "你好世界こんにちは안녕하세요"
            try:
                json_str = json.dumps(msg, ensure_ascii=False)
                parsed = json.loads(json_str)
                self.assertEqual(parsed["text"], msg["text"])
            except Exception as e:
                self.fail(f"Unicode 处理失败: {e}")

    def test_nested_structure(self):
        """测试嵌套结构"""
        gen = IPCMessageGenerator(seed=404)
        for _ in range(50):
            depth = gen.gen.random.randint(1, 10)
            obj = {}
            current = obj
            for i in range(depth):
                current["level"] = {}
                current = current["level"]
                current["value"] = i

            try:
                json_str = json.dumps(obj)
                parsed = json.loads(json_str)
            except Exception as e:
                self.fail(f"嵌套结构处理失败: {e}")

    def test_large_payload(self):
        """测试大负载"""
        gen = IPCMessageGenerator(seed=505)
        large_data = "x" * 100000
        msg = {"id": "large", "type": "request", "data": large_data}
        try:
            json_str = json.dumps(msg)
            self.assertGreater(len(json_str), 100000)
            parsed = json.loads(json_str)
            self.assertEqual(len(parsed["data"]), 100000)
        except Exception as e:
            self.fail(f"大负载处理失败: {e}")


# ============================================================
# 主入口
# ============================================================

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="AinosOS 模糊测试")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument("--iterations", type=int, default=10000, help="测试迭代次数")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--unittest", action="store_true", help="运行单元测试")

    args = parser.parse_args()

    if args.unittest:
        unittest.main(argv=[sys.argv[0]])
        return

    # 运行模糊测试
    fuzzer = FuzzTester(seed=args.seed)
    results = fuzzer.run_all()

    # 结果
    if results["errors"] or results["protocol_violations"]:
        print("\n发现问题:")
        for err in results["errors"][:10]:
            print(f"  - 错误: {err}")
        for vio in results["protocol_violations"][:10]:
            print(f"  - 协议违规: {vio}")
        return 1

    print("\n所有测试通过!")
    return 0


if __name__ == "__main__":
    sys.exit(main())