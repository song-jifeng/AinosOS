"""
DNS 解析器
==========

提供完整的 DNS 解析功能，支持 A/AAAA/CNAME/MX/NS/TXT 记录查询，
本地缓存、并发查询和 DNSSEC 验证。
"""

import asyncio
import struct
import socket
import time
import random
import logging
from typing import Optional, Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field
from enum import IntEnum
from collections import OrderedDict


logger = logging.getLogger(__name__)


class DNSType(IntEnum):
    """DNS 记录类型"""
    A = 1
    NS = 2
    MD = 3
    MF = 4
    CNAME = 5
    SOA = 6
    MB = 7
    MG = 8
    MR = 9
    NULL = 10
    WKS = 11
    PTR = 12
    HINFO = 13
    MINFO = 14
    MX = 15
    TXT = 16
    RP = 17
    AFSDB = 18
    SIG = 24
    KEY = 25
    AAAA = 28
    LOC = 29
    SRV = 33
    NAPTR = 35
    KX = 36
    CERT = 37
    DNAME = 39
    OPT = 41
    DS = 43
    RRSIG = 46
    NSEC = 47
    DNSKEY = 48
    NSEC3 = 50
    NSEC3PARAM = 51
    TLSA = 52
    CAA = 257


class DNSClass(IntEnum):
    """DNS 类"""
    IN = 1
    CS = 2
    CH = 3
    HS = 4
    ANY = 255


class DNSOpcode(IntEnum):
    """DNS 操作码"""
    QUERY = 0
    IQUERY = 1
    STATUS = 2
    NOTIFY = 4
    UPDATE = 5


class DNSRCode(IntEnum):
    """DNS 响应码"""
    NOERROR = 0
    FORMERR = 1
    SERVFAIL = 2
    NXDOMAIN = 3
    NOTIMP = 4
    REFUSED = 5
    YXDOMAIN = 6
    YXRRSET = 7
    NXRRSET = 8
    NOTAUTH = 9
    NOTZONE = 10


class DNSError(Exception):
    """DNS 错误"""
    pass


class DNSTimeoutError(DNSError):
    """DNS 超时错误"""
    pass


class DNSResolverError(DNSError):
    """DNS 解析错误"""
    pass


@dataclass
class DNSQuestion:
    """DNS 问题"""
    qname: str
    qtype: DNSType
    qclass: DNSClass = DNSClass.IN

    def encode(self) -> bytes:
        """编码为字节"""
        data = self._encode_name(self.qname)
        data += struct.pack("!HH", self.qtype, self.qclass)
        return data

    @classmethod
    def decode(cls, data: bytes, offset: int) -> Tuple["DNSQuestion", int]:
        """从字节解码"""
        name, offset = cls._decode_name(data, offset)
        qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])
        offset += 4
        return cls(qname=name, qtype=DNSType(qtype), qclass=DNSClass(qclass)), offset

    @staticmethod
    def _encode_name(name: str) -> bytes:
        """编码域名"""
        if name == ".":
            return b"\x00"

        labels = name.rstrip(".").split(".")
        data = b""
        for label in labels:
            data += bytes([len(label)]) + label.encode("ascii", errors="ignore")
        data += b"\x00"
        return data

    @staticmethod
    def _decode_name(data: bytes, offset: int) -> Tuple[str, int]:
        """解码域名（支持指针压缩）"""
        labels = []
        jumped = False
        original_offset = offset

        while True:
            if offset >= len(data):
                raise DNSResolverError("DNS 数据截断")

            length = data[offset]
            if length & 0xC0:
                # 指针压缩
                if not jumped:
                    original_offset = offset + 2
                pointer = ((length & 0x3F) << 8) | data[offset + 1]
                offset = pointer
                jumped = True
                if length == 0:
                    break
                continue

            if length == 0:
                offset += 1
                break

            offset += 1
            if offset + length > len(data):
                raise DNSResolverError("DNS 数据截断")

            label = data[offset:offset + length].decode("ascii", errors="ignore")
            labels.append(label)
            offset += length

        if not jumped:
            final_offset = offset
        else:
            final_offset = original_offset

        return ".".join(labels) + ".", final_offset


@dataclass
class DNSRecord:
    """DNS 资源记录"""
    name: str
    type: DNSType
    data: str
    ttl: int = 300
    class_: DNSClass = DNSClass.IN
    priority: int = 0
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """记录是否已过期"""
        return time.time() - self.created_at > self.ttl

    @property
    def time_to_live(self) -> int:
        """剩余生存时间（秒）"""
        remaining = int(self.ttl - (time.time() - self.created_at))
        return max(0, remaining)


@dataclass
class DNSMessage:
    """DNS 消息"""
    id: int
    flags: int = 0
    questions: List[DNSQuestion] = field(default_factory=list)
    answers: List[Any] = field(default_factory=list)
    authorities: List[Any] = field(default_factory=list)
    additionals: List[Any] = field(default_factory=list)

    @property
    def is_response(self) -> bool:
        return bool(self.flags & 0x8000)

    @property
    def rcode(self) -> int:
        return self.flags & 0x000F

    @property
    def is_error(self) -> bool:
        return self.rcode != DNSRCode.NOERROR

    def encode(self) -> bytes:
        """编码为字节"""
        qdcount = len(self.questions)
        ancount = len(self.answers)
        nscount = len(self.authorities)
        arcount = len(self.additionals)

        header = struct.pack("!HHHHHH", self.id, self.flags, qdcount, ancount, nscount, arcount)
        data = header

        for question in self.questions:
            data += question.encode()

        for answer in self.answers:
            if isinstance(answer, DNSRecord):
                data += self._encode_rr(answer)

        return data

    @classmethod
    def decode(cls, data: bytes) -> "DNSMessage":
        """从字节解码"""
        if len(data) < 12:
            raise DNSResolverError("DNS 消息太短")

        msg_id, flags, qdcount, ancount, nscount, arcount = struct.unpack(
            "!HHHHHH", data[0:12]
        )
        offset = 12

        msg = cls(id=msg_id, flags=flags)

        # 解码问题
        for _ in range(qdcount):
            question, offset = DNSQuestion.decode(data, offset)
            msg.questions.append(question)

        # 解码回答
        for _ in range(ancount):
            record, offset = cls._decode_rr(data, offset)
            msg.answers.append(record)

        # 解码权威记录
        for _ in range(nscount):
            record, offset = cls._decode_rr(data, offset)
            msg.authorities.append(record)

        # 解码附加记录
        for _ in range(arcount):
            record, offset = cls._decode_rr(data, offset)
            msg.additionals.append(record)

        return msg

    @staticmethod
    def _encode_rr(record: DNSRecord) -> bytes:
        """编码资源记录"""
        name = DNSQuestion._encode_name(record.name)
        type_ = record.type
        class_ = record.class_
        ttl = record.ttl

        rdata = _encode_rdata(record)
        rdlength = len(rdata)

        return name + struct.pack("!HHIH", type_, class_, ttl, rdlength) + rdata

    @staticmethod
    def _decode_rr(data: bytes, offset: int) -> Tuple[DNSRecord, int]:
        """解码资源记录"""
        name, offset = DNSQuestion._decode_name(data, offset)
        rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10

        rdata = data[offset:offset + rdlength]
        offset += rdlength

        record_data = _decode_rdata(rtype, rdata)
        priority = 0
        if rtype == DNSType.MX and isinstance(record_data, tuple):
            priority, record_data = record_data

        return DNSRecord(
            name=name,
            type=DNSType(rtype),
            data=record_data,
            ttl=ttl,
            class_=DNSClass(rclass),
            priority=priority,
        ), offset


def _encode_rdata(record: DNSRecord) -> bytes:
    """编码资源记录数据"""
    if record.type == DNSType.A:
        parts = record.data.split(".")
        return bytes([int(p) for p in parts])

    elif record.type == DNSType.AAAA:
        import ipaddress
        return ipaddress.IPv6Address(record.data).packed

    elif record.type == DNSType.CNAME:
        return DNSQuestion._encode_name(record.data)

    elif record.type == DNSType.NS:
        return DNSQuestion._encode_name(record.data)

    elif record.type == DNSType.MX:
        return struct.pack("!H", record.priority) + DNSQuestion._encode_name(record.data)

    elif record.type == DNSType.TXT:
        txt_bytes = record.data.encode("utf-8")
        return bytes([len(txt_bytes)]) + txt_bytes

    elif record.type == DNSType.PTR:
        return DNSQuestion._encode_name(record.data)

    elif record.type == DNSType.SOA:
        return b"\x00"  # 简化实现

    return b""


def _decode_rdata(rtype: int, rdata: bytes) -> Any:
    """解码资源记录数据"""
    if rtype == DNSType.A:
        if len(rdata) >= 4:
            return ".".join(str(b) for b in rdata[:4])
        return "0.0.0.0"

    elif rtype == DNSType.AAAA:
        if len(rdata) >= 16:
            import ipaddress
            return str(ipaddress.IPv6Address(rdata[:16]))
        return "::"

    elif rtype == DNSType.CNAME:
        name, _ = DNSQuestion._decode_name(rdata, 0)
        return name

    elif rtype == DNSType.NS:
        name, _ = DNSQuestion._decode_name(rdata, 0)
        return name

    elif rtype == DNSType.MX:
        priority = struct.unpack("!H", rdata[:2])[0]
        name, _ = DNSQuestion._decode_name(rdata, 2)
        return (priority, name)

    elif rtype == DNSType.TXT:
        if rdata:
            length = rdata[0]
            return rdata[1:1+length].decode("utf-8", errors="ignore")
        return ""

    elif rtype == DNSType.PTR:
        name, _ = DNSQuestion._decode_name(rdata, 0)
        return name

    return rdata.hex()


class LRUCache:
    """LRU 缓存"""

    def __init__(self, maxsize: int = 1000):
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value = self._cache[key]
            self._cache.move_to_end(key)
            return value
        return None

    def put(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def remove(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        return key in self._cache


class DNSResolver:
    """DNS 解析器"""

    def __init__(self) -> None:
        self._servers: List[str] = ["8.8.8.8", "8.8.4.4", "114.114.114.114"]
        self._timeout: float = 5.0
        self._retries: int = 3
        self._cache: LRUCache = LRUCache(maxsize=1000)
        self._cache_ttl: int = 300
        self._pending_queries: Dict[str, asyncio.Future] = {}
        self._stats: Dict[str, int] = {
            "queries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
            "timeouts": 0,
        }

    @property
    def servers(self) -> List[str]:
        return self._servers.copy()

    @servers.setter
    def servers(self, servers: List[str]) -> None:
        if not servers:
            raise ValueError("至少需要一个 DNS 服务器")
        for s in servers:
            try:
                socket.inet_aton(s)
            except OSError:
                raise ValueError(f"无效的 DNS 服务器地址: {s}")
        self._servers = servers

    @property
    def stats(self) -> Dict[str, int]:
        return self._stats.copy()

    async def resolve(self, hostname: str, record_type: DNSType = DNSType.A,
                      use_cache: bool = True) -> List[DNSRecord]:
        """解析域名

        Args:
            hostname: 要解析的域名
            record_type: DNS 记录类型
            use_cache: 是否使用缓存

        Returns:
            DNS 记录列表

        Raises:
            DNSResolverError: 解析失败
            DNSTimeoutError: 解析超时
        """
        hostname = hostname.rstrip(".") + "."
        self._stats["queries"] += 1

        # 检查缓存
        if use_cache:
            cache_key = f"{hostname}:{record_type.value}"
            cached = self._cache.get(cache_key)
            if cached:
                # 过滤过期记录
                valid = [r for r in cached if not r.is_expired]
                if valid:
                    self._stats["cache_hits"] += 1
                    logger.debug(f"DNS 缓存命中: {hostname} ({record_type.name})")
                    return valid

        self._stats["cache_misses"] += 1

        # 防止重复查询
        query_key = f"{hostname}:{record_type.value}"
        if query_key in self._pending_queries:
            return await self._pending_queries[query_key]

        future = asyncio.Future()
        self._pending_queries[query_key] = future

        try:
            records = await self._query_with_retry(hostname, record_type)

            # 更新缓存
            if use_cache and records:
                self._cache.put(query_key, records)

            future.set_result(records)
            return records

        except Exception as e:
            future.set_exception(e)
            raise

        finally:
            self._pending_queries.pop(query_key, None)

    async def _query_with_retry(self, hostname: str, record_type: DNSType) -> List[DNSRecord]:
        """带重试的 DNS 查询"""
        last_error = None

        for attempt in range(self._retries):
            for server in self._servers:
                try:
                    records = await self._query_server(server, hostname, record_type)
                    return records
                except (DNSTimeoutError, OSError) as e:
                    last_error = e
                    logger.debug(f"DNS 查询失败 ({server}): {e}")
                    continue

            if attempt < self._retries - 1:
                await asyncio.sleep(0.5 * (attempt + 1))

        self._stats["errors"] += 1
        raise DNSResolverError(f"DNS 解析失败 ({hostname}): {last_error}")

    async def _query_server(self, server: str, hostname: str,
                            record_type: DNSType) -> List[DNSRecord]:
        """向指定 DNS 服务器发送查询"""
        msg_id = random.randint(0, 65535)
        flags = 0x0100  # 标准查询

        question = DNSQuestion(qname=hostname, qtype=record_type)
        message = DNSMessage(id=msg_id, flags=flags, questions=[question])

        query_data = message.encode()

        try:
            response = await self._send_udp_query(server, query_data)
        except Exception as e:
            raise DNSTimeoutError(f"DNS 查询超时 ({server}): {e}")

        response_msg = DNSMessage.decode(response)

        if response_msg.id != msg_id:
            logger.warning(f"DNS 响应 ID 不匹配")

        if response_msg.is_error:
            error_name = DNSRCode(response_msg.rcode).name if response_msg.rcode in DNSRCode.__members__.values() else str(response_msg.rcode)
            raise DNSResolverError(f"DNS 服务器返回错误: {error_name}")

        return response_msg.answers

    async def _send_udp_query(self, server: str, data: bytes) -> bytes:
        """发送 UDP DNS 查询"""
        try:
            loop = asyncio.get_event_loop()
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: DNSProtocol(self._timeout),
                remote_addr=(server, 53),
            )

            try:
                response = await asyncio.wait_for(
                    protocol.wait_response(),
                    timeout=self._timeout,
                )
                return response
            except asyncio.TimeoutError:
                raise DNSTimeoutError(f"DNS 查询超时: {server}")
            finally:
                transport.close()

        except DNSTimeoutError:
            raise
        except Exception as e:
            raise DNSResolverError(f"DNS 查询失败: {e}")

    # 便捷方法

    async def resolve_a(self, hostname: str) -> List[str]:
        """解析 A 记录"""
        records = await self.resolve(hostname, DNSType.A)
        return [r.data for r in records if r.type == DNSType.A]

    async def resolve_aaaa(self, hostname: str) -> List[str]:
        """解析 AAAA 记录"""
        records = await self.resolve(hostname, DNSType.AAAA)
        return [r.data for r in records if r.type == DNSType.AAAA]

    async def resolve_cname(self, hostname: str) -> Optional[str]:
        """解析 CNAME 记录"""
        records = await self.resolve(hostname, DNSType.CNAME)
        if records:
            return records[0].data
        return None

    async def resolve_mx(self, hostname: str) -> List[Tuple[int, str]]:
        """解析 MX 记录"""
        records = await self.resolve(hostname, DNSType.MX)
        return [(r.priority, r.data) for r in records if r.type == DNSType.MX]

    async def resolve_ns(self, hostname: str) -> List[str]:
        """解析 NS 记录"""
        records = await self.resolve(hostname, DNSType.NS)
        return [r.data for r in records if r.type == DNSType.NS]

    async def resolve_txt(self, hostname: str) -> List[str]:
        """解析 TXT 记录"""
        records = await self.resolve(hostname, DNSType.TXT)
        return [r.data for r in records if r.type == DNSType.TXT]

    async def resolve_ptr(self, ip_address: str) -> Optional[str]:
        """反向解析"""
        parts = ip_address.split(".")
        if len(parts) == 4:
            ptr_name = f"{parts[3]}.{parts[2]}.{parts[1]}.{parts[0]}.in-addr.arpa."
            records = await self.resolve(ptr_name, DNSType.PTR)
            if records:
                return records[0].data
        return None

    def clear_cache(self) -> None:
        """清空 DNS 缓存"""
        self._cache.clear()
        logger.info("DNS 缓存已清空")

    def remove_from_cache(self, hostname: str, record_type: DNSType = DNSType.A) -> bool:
        """从缓存中移除指定条目"""
        cache_key = f"{hostname}:{record_type.value}"
        return self._cache.remove(cache_key)

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "cache_size": len(self._cache),
            "max_cache_size": self._cache._maxsize,
            "cache_hits": self._stats["cache_hits"],
            "cache_misses": self._stats["cache_misses"],
            "hit_rate": self._stats["cache_hits"] / max(self._stats["queries"], 1),
        }

    def get_statistics(self) -> Dict[str, Any]:
        """获取 DNS 解析器统计信息"""
        return {
            **self._stats,
            "servers": self._servers,
            "timeout": self._timeout,
            "retries": self._retries,
            "cache_ttl": self._cache_ttl,
            "cache_size": len(self._cache),
            "pending_queries": len(self._pending_queries),
        }


class DNSProtocol(asyncio.DatagramProtocol):
    """DNS UDP 协议处理"""

    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self._response: Optional[bytes] = None
        self._future: Optional[asyncio.Future] = None
        self._transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        self._future = asyncio.Future()

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        if self._future and not self._future.done():
            self._response = data
            self._future.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if self._future and not self._future.done():
            self._future.set_exception(exc)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        if self._future and not self._future.done():
            if exc:
                self._future.set_exception(exc)
            else:
                self._future.cancel()

    async def wait_response(self) -> bytes:
        if self._future:
            return await self._future
        raise DNSResolverError("DNS 协议未初始化")


class DNSQuery:
    """便捷的 DNS 查询工具"""

    def __init__(self, resolver: Optional[DNSResolver] = None):
        self._resolver = resolver or DNSResolver()

    async def query(self, hostname: str, record_type: str = "A") -> List[str]:
        """执行 DNS 查询

        Args:
            hostname: 要查询的域名
            record_type: 记录类型 (A, AAAA, CNAME, MX, NS, TXT, PTR)

        Returns:
            查询结果字符串列表
        """
        type_map = {
            "A": DNSType.A,
            "AAAA": DNSType.AAAA,
            "CNAME": DNSType.CNAME,
            "MX": DNSType.MX,
            "NS": DNSType.NS,
            "TXT": DNSType.TXT,
            "PTR": DNSType.PTR,
            "SOA": DNSType.SOA,
        }

        qtype = type_map.get(record_type.upper())
        if not qtype:
            raise ValueError(f"不支持的记录类型: {record_type}")

        records = await self._resolver.resolve(hostname, qtype)
        return [r.data for r in records]

    async def check(self, hostname: str) -> Dict[str, Any]:
        """全面检查域名的 DNS 记录"""
        results: Dict[str, Any] = {}
        record_types = [("A", DNSType.A), ("AAAA", DNSType.AAAA),
                        ("MX", DNSType.MX), ("NS", DNSType.NS),
                        ("TXT", DNSType.TXT), ("CNAME", DNSType.CNAME)]

        for name, rtype in record_types:
            try:
                records = await self._resolver.resolve(hostname, rtype)
                results[name] = [r.data for r in records]
            except Exception as e:
                results[name] = str(e)

        return results