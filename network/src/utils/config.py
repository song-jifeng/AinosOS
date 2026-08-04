"""
配置管理模块
============

提供网络栈配置管理功能，支持 YAML/JSON 配置文件加载、环境变量覆盖和动态配置更新。
"""

import os
import json
import yaml
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum


class ConfigError(Exception):
    """配置错误"""
    pass


class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StackMode(str, Enum):
    """网络栈运行模式"""
    KERNEL = "kernel"       # 内核态模式
    USERSPACE = "userspace" # 用户态模式
    MIXED = "mixed"         # 混合模式
    SIMULATION = "simulation" # 模拟模式


@dataclass
class NetworkConfig:
    """网络配置"""
    # 基础网络配置
    host: str = "0.0.0.0"
    port: int = 0
    mtu: int = 1500
    mss: int = 1460
    ttl: int = 64
    window_size: int = 65535
    buffer_size: int = 65536
    backlog: int = 128
    timeout: float = 30.0
    max_connections: int = 1000
    tcp_fast_open: bool = False
    tcp_nodelay: bool = True
    reuse_address: bool = True
    keepalive: bool = True
    keepalive_interval: int = 60

    # DNS 配置
    dns_servers: List[str] = field(default_factory=lambda: [
        "8.8.8.8", "8.8.4.4", "114.114.114.114"
    ])
    dns_timeout: float = 5.0
    dns_retries: int = 3
    dns_cache_size: int = 1000
    dns_cache_ttl: int = 300

    # HTTP 配置
    http_max_connections: int = 10
    http_max_header_size: int = 8192
    http_max_body_size: int = 10485760  # 10MB
    http_keep_alive: bool = True
    http_keep_alive_timeout: float = 30.0
    http2_enable: bool = True
    http2_max_concurrent_streams: int = 100
    http2_initial_window_size: int = 65535

    # WebSocket 配置
    ws_max_message_size: int = 1048576  # 1MB
    ws_ping_interval: float = 30.0
    ws_ping_timeout: float = 10.0
    ws_max_frame_size: int = 65536

    # 代理配置
    proxy_enabled: bool = False
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8080
    proxy_auth: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NetworkConfig":
        """从字典创建"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AIConfig:
    """AI 模块配置"""
    # 流量预测
    traffic_pred_enabled: bool = True
    traffic_pred_model: str = "lstm"
    traffic_pred_window: int = 100
    traffic_pred_interval: float = 60.0
    traffic_pred_threshold: float = 0.8

    # 拥塞控制
    congestion_control_enabled: bool = True
    congestion_control_algorithm: str = "adaptive"
    congestion_control_interval: float = 10.0
    congestion_control_sensitivity: float = 0.5

    # 智能路由
    routing_enabled: bool = True
    routing_algorithm: str = "reinforcement"
    routing_update_interval: float = 30.0
    routing_max_paths: int = 5
    routing_metrics: List[str] = field(default_factory=lambda: [
        "latency", "bandwidth", "loss", "jitter"
    ])

    # 异常检测
    anomaly_detection_enabled: bool = True
    anomaly_detection_model: str = "isolation_forest"
    anomaly_detection_interval: float = 5.0
    anomaly_detection_threshold: float = 0.7
    anomaly_detection_sensitivity: float = 0.6
    anomaly_detection_features: List[str] = field(default_factory=lambda: [
        "packet_rate", "byte_rate", "flow_count",
        "tcp_syn_rate", "tcp_error_rate", "icmp_rate"
    ])

    # 模型训练
    model_retrain_interval: int = 86400  # 24小时
    model_learning_rate: float = 0.001
    model_batch_size: int = 32
    model_epochs: int = 100
    model_validation_split: float = 0.2

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AIConfig":
        """从字典创建"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MonitorConfig:
    """监控配置"""
    capture_enabled: bool = True
    capture_interface: str = "any"
    capture_promiscuous: bool = True
    capture_snaplen: int = 65535
    capture_buffer_size: int = 10485760  # 10MB
    capture_timeout: float = 60.0
    capture_filter: str = ""

    analysis_enabled: bool = True
    analysis_interval: float = 5.0
    analysis_window: int = 300  # 5分钟
    analysis_top_flows: int = 100
    analysis_top_talkers: int = 20

    dashboard_enabled: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 9090
    dashboard_refresh_interval: float = 2.0
    dashboard_max_points: int = 1000

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class StackConfig:
    """网络栈整体配置"""
    # 通用配置
    mode: StackMode = StackMode.USERSPACE
    log_level: LogLevel = LogLevel.INFO
    log_file: Optional[str] = None
    log_format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    data_dir: str = "./data"
    debug: bool = False
    version: str = "2.1.0"

    # 子模块配置
    network: NetworkConfig = field(default_factory=NetworkConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)

    # 插件配置
    plugins: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # 自定义配置
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["mode"] = self.mode.value
        result["log_level"] = self.log_level.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StackConfig":
        """从字典创建配置"""
        if "network" in data and isinstance(data["network"], dict):
            data["network"] = NetworkConfig.from_dict(data["network"])
        if "ai" in data and isinstance(data["ai"], dict):
            data["ai"] = AIConfig.from_dict(data["ai"])
        if "monitor" in data and isinstance(data["monitor"], dict):
            data["monitor"] = MonitorConfig.from_dict(data["monitor"])
        if "mode" in data and isinstance(data["mode"], str):
            try:
                data["mode"] = StackMode(data["mode"])
            except ValueError:
                data["mode"] = StackMode.USERSPACE
        if "log_level" in data and isinstance(data["log_level"], str):
            try:
                data["log_level"] = LogLevel(data["log_level"])
            except ValueError:
                data["log_level"] = LogLevel.INFO

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ConfigManager:
    """配置管理器，支持多源配置加载与合并"""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._config: StackConfig = StackConfig()
        self._config_path: Optional[str] = config_path
        self._watchers: List[Any] = []
        self._loaded_files: List[str] = []

    @property
    def config(self) -> StackConfig:
        """获取当前配置"""
        return self._config

    @property
    def network(self) -> NetworkConfig:
        """获取网络配置"""
        return self._config.network

    @property
    def ai(self) -> AIConfig:
        """获取 AI 配置"""
        return self._config.ai

    @property
    def monitor(self) -> MonitorConfig:
        """获取监控配置"""
        return self._config.monitor

    def load_defaults(self) -> None:
        """加载默认配置"""
        self._config = StackConfig()
        self._log("已加载默认配置")

    def load_from_file(self, filepath: str) -> bool:
        """从文件加载配置

        Args:
            filepath: 配置文件路径 (支持 .json, .yaml, .yml)

        Returns:
            是否成功加载

        Raises:
            ConfigError: 配置文件格式错误
        """
        path = Path(filepath)
        if not path.exists():
            raise ConfigError(f"配置文件不存在: {filepath}")

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                if path.suffix in (".yaml", ".yml"):
                    data = yaml.safe_load(f)
                elif path.suffix == ".json":
                    data = json.load(f)
                else:
                    raise ConfigError(f"不支持的配置文件格式: {path.suffix}")

            if not isinstance(data, dict):
                raise ConfigError("配置文件必须包含一个顶层字典")

            # 合并配置
            self._merge_config(data)
            self._loaded_files.append(filepath)
            self._log(f"已加载配置文件: {filepath}")
            return True

        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ConfigError(f"配置文件解析错误: {e}")

    def load_from_dict(self, data: Dict[str, Any]) -> None:
        """从字典加载配置"""
        self._merge_config(data)

    def load_from_env(self, prefix: str = "AINOS_NET_") -> None:
        """从环境变量加载配置

        环境变量命名规则: AINOS_NET_SECTION_KEY=value
        例如: AINOS_NET_NETWORK_HOST=0.0.0.0
             AINOS_NET_AI_TRAFFIC_PRED_ENABLED=true
        """
        env_config: Dict[str, Any] = {}
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue

            parts = key[len(prefix):].lower().split("_")
            if len(parts) < 2:
                continue

            section = parts[0]
            setting = "_".join(parts[1:])

            if section not in env_config:
                env_config[section] = {}

            # 尝试类型转换
            env_config[section][setting] = self._parse_env_value(value)

        if env_config:
            self._merge_config(env_config)
            self._log(f"已从环境变量加载配置 ({len(env_config)} 个部分)")

    def _parse_env_value(self, value: str) -> Any:
        """解析环境变量值"""
        if value.lower() in ("true", "yes", "1"):
            return True
        elif value.lower() in ("false", "no", "0"):
            return False
        elif value.lower() == "null":
            return None
        else:
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return value

    def _merge_config(self, data: Dict[str, Any]) -> None:
        """合并配置数据"""
        current = self._config.to_dict()

        # 深层合并
        for key, value in data.items():
            if key in current and isinstance(current[key], dict) and isinstance(value, dict):
                current[key].update(value)
            else:
                current[key] = value

        self._config = StackConfig.from_dict(current)

    def save(self, filepath: Optional[str] = None) -> bool:
        """保存配置到文件

        Args:
            filepath: 保存路径，默认使用加载时的路径

        Returns:
            是否成功保存
        """
        path = filepath or self._config_path
        if not path:
            raise ConfigError("未指定保存路径")

        data = self._config.to_dict()
        path_obj = Path(path)

        try:
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            with open(path_obj, "w", encoding="utf-8") as f:
                if path_obj.suffix in (".yaml", ".yml"):
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
                elif path_obj.suffix == ".json":
                    json.dump(data, f, indent=2, ensure_ascii=False)
                else:
                    raise ConfigError(f"不支持的配置文件格式: {path_obj.suffix}")

            self._log(f"配置已保存到: {path}")
            return True

        except (yaml.YAMLError, IOError) as e:
            raise ConfigError(f"保存配置失败: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项 (支持点号分隔的路径)

        Args:
            key: 配置键，如 "network.host" 或 "ai.traffic_pred_enabled"
            default: 默认值

        Returns:
            配置值
        """
        parts = key.split(".")
        value = self._config.to_dict()

        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return default

        return value if value is not None else default

    def set(self, key: str, value: Any) -> None:
        """设置配置项 (支持点号分隔的路径)

        Args:
            key: 配置键，如 "network.host"
            value: 配置值
        """
        data = self._config.to_dict()
        parts = key.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value
        self._config = StackConfig.from_dict(data)

    def update(self, updates: Dict[str, Any]) -> None:
        """批量更新配置"""
        self._merge_config(updates)

    def reset(self) -> None:
        """重置配置为默认值"""
        self._config = StackConfig()
        self._loaded_files.clear()
        self._log("配置已重置为默认值")

    def validate(self) -> List[str]:
        """验证配置有效性

        Returns:
            错误消息列表，空列表表示配置有效
        """
        errors: List[str] = []

        # 验证网络配置
        if not (0 < self._config.network.port < 65536 if self._config.network.port > 0 else True):
            errors.append(f"端口号无效: {self._config.network.port}")

        if not (576 <= self._config.network.mtu <= 65535):
            errors.append(f"MTU 值无效: {self._config.network.mtu}")

        if self._config.network.dns_servers:
            import re
            ip_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
            for dns in self._config.network.dns_servers:
                if not ip_pattern.match(dns):
                    errors.append(f"DNS 服务器地址无效: {dns}")

        # 验证 AI 配置
        if not (0 < self._config.ai.traffic_pred_threshold <= 1.0):
            errors.append("流量预测阈值需在 0-1 之间")

        if not (0 < self._config.ai.anomaly_detection_threshold <= 1.0):
            errors.append("异常检测阈值需在 0-1 之间")

        return errors

    def watch(self, callback: Any) -> None:
        """注册配置变更回调

        Args:
            callback: 配置变更时的回调函数
        """
        if callback not in self._watchers:
            self._watchers.append(callback)

    def _notify_watchers(self) -> None:
        """通知所有观察者配置已变更"""
        for callback in self._watchers:
            try:
                callback(self._config)
            except Exception as e:
                self._log(f"配置回调执行出错: {e}")

    def _log(self, message: str) -> None:
        """内部日志（开发阶段用 print 代替）"""
        if self._config.debug:
            print(f"[ConfigManager] {message}")

    def list_loaded_files(self) -> List[str]:
        """列出已加载的配置文件"""
        return self._loaded_files.copy()

    def export_config(self, format: str = "yaml") -> str:
        """导出配置为字符串

        Args:
            format: 导出格式 (yaml 或 json)

        Returns:
            配置字符串
        """
        data = self._config.to_dict()
        if format == "yaml":
            return yaml.dump(data, default_flow_style=False, allow_unicode=True)
        elif format == "json":
            return json.dumps(data, indent=2, ensure_ascii=False)
        else:
            raise ConfigError(f"不支持的导出格式: {format}")


# 全局配置实例
global_config = ConfigManager()


def get_config() -> ConfigManager:
    """获取全局配置管理器"""
    return global_config


def load_config(path: str) -> StackConfig:
    """便捷函数：加载配置并返回

    Args:
        path: 配置文件路径

    Returns:
        加载的配置
    """
    mgr = ConfigManager(path)
    mgr.load_from_file(path)
    return mgr.config


def create_default_config(path: str) -> None:
    """创建默认配置文件

    Args:
        path: 配置文件的保存路径
    """
    config = StackConfig()
    mgr = ConfigManager()
    mgr._config = config
    mgr.save(path)