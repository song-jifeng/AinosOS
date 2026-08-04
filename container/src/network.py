"""
容器网络模块 - Network management for Ainos containers.

支持以下网络模式:
- bridge: 桥接网络 (默认)
- host: 主机网络
- none: 无网络
- overlay: 覆盖网络
- macvlan: MAC VLAN
"""

import enum
import ipaddress
import logging
import os
import random
import re
import string
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional

logger = logging.getLogger(__name__)

NETWORK_DIR = Path("/var/lib/ainos/network")


class NetworkMode(enum.Enum):
    """Container network mode."""

    BRIDGE = "bridge"
    HOST = "host"
    NONE = "none"
    OVERLAY = "overlay"
    MACVLAN = "macvlan"

    def __str__(self) -> str:
        return self.value


class NetworkError(Exception):
    """Raised when a network operation fails."""

    def __init__(self, message: str, mode: Optional[NetworkMode] = None) -> None:
        self.mode = mode
        super().__init__(f"Network{'[' + mode.value + '] ' if mode else ' '}{message}")


@dataclass
class PortMapping:
    """Port mapping from host to container."""

    host_port: int
    container_port: int
    protocol: str = "tcp"
    host_ip: str = "0.0.0.0"

    def validate(self) -> None:
        """Validate port mapping values."""
        if not 1 <= self.host_port <= 65535:
            raise ValueError(f"Host port {self.host_port} out of range")
        if not 1 <= self.container_port <= 65535:
            raise ValueError(f"Container port {self.container_port} out of range")
        if self.protocol.lower() not in ("tcp", "udp", "sctp"):
            raise ValueError(f"Unsupported protocol: {self.protocol}")

    @property
    def iptables_rule(self) -> str:
        """Generate iptables DNAT rule for this port mapping."""
        return (
            f"PREROUTING -d {self.host_ip} -p {self.protocol} "
            f"--dport {self.host_port} -j DNAT "
            f"--to-destination {self.host_ip}:{self.container_port}"
        )


@dataclass
class NetworkConfig:
    """Network configuration for a container."""

    mode: NetworkMode = NetworkMode.BRIDGE
    hostname: str = ""
    dns: list[str] = field(default_factory=lambda: ["8.8.8.8", "1.1.1.1"])
    dns_search: list[str] = field(default_factory=list)
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    gateway: Optional[str] = None
    subnet: Optional[str] = None
    ports: list[PortMapping] = field(default_factory=list)
    extra_hosts: dict[str, str] = field(default_factory=dict)
    bridge_name: str = "ainos0"
    mtu: int = 1500
    enable_ipv6: bool = False
    ipv6_subnet: Optional[str] = None
    network_name: str = "default"

    def validate(self) -> None:
        """Validate network configuration."""
        if self.ip_address:
            try:
                ipaddress.ip_address(self.ip_address)
            except ValueError as e:
                raise ValueError(f"Invalid IP address: {self.ip_address}") from e

        if self.gateway:
            try:
                ipaddress.ip_address(self.gateway)
            except ValueError as e:
                raise ValueError(f"Invalid gateway: {self.gateway}") from e

        if self.subnet:
            try:
                ipaddress.ip_network(self.subnet, strict=False)
            except ValueError as e:
                raise ValueError(f"Invalid subnet: {self.subnet}") from e

        for port in self.ports:
            port.validate()

        if not 68 <= self.mtu <= 65535:
            raise ValueError(f"MTU must be in [68, 65535], got {self.mtu}")


@dataclass
class NetworkStats:
    """Network statistics for a container."""

    rx_bytes: int = 0
    rx_packets: int = 0
    rx_errors: int = 0
    rx_dropped: int = 0
    tx_bytes: int = 0
    tx_packets: int = 0
    tx_errors: int = 0
    tx_dropped: int = 0

    @classmethod
    def from_proc(cls, iface: str) -> "NetworkStats":
        """
        Parse network statistics from /proc/net/dev.

        Args:
            iface: Network interface name.

        Returns:
            NetworkStats object with parsed values.
        """
        stats = cls()
        try:
            with open("/proc/net/dev", "r") as f:
                for line in f:
                    if iface in line:
                        parts = line.split()
                        # Format: iface: rx_bytes rx_packets rx_errs rx_drop ...
                        if len(parts) >= 10:
                            stats.rx_bytes = int(parts[1])
                            stats.rx_packets = int(parts[2])
                            stats.rx_errors = int(parts[3])
                            stats.rx_dropped = int(parts[4])
                            stats.tx_bytes = int(parts[9])
                            stats.tx_packets = int(parts[10])
                            stats.tx_errors = int(parts[11])
                            stats.tx_dropped = int(parts[12])
        except (FileNotFoundError, OSError, IndexError, ValueError) as e:
            logger.warning("Failed to parse /proc/net/dev for %s: %s", iface, e)
        return stats

    def __sub__(self, other: "NetworkStats") -> "NetworkStats":
        return NetworkStats(
            rx_bytes=self.rx_bytes - other.rx_bytes,
            rx_packets=self.rx_packets - other.rx_packets,
            tx_bytes=self.tx_bytes - other.tx_bytes,
            tx_packets=self.tx_packets - other.tx_packets,
        )


class VirtualEthernetPair:
    """
    Manages a veth pair for container networking.

    Creates a veth pair with one end in the host namespace and
    the other moved into the container namespace.
    """

    def __init__(
        self,
        container_id: str,
        host_iface: str,
        container_iface: str = "eth0",
    ) -> None:
        self.container_id = container_id
        self.host_iface = host_iface
        self.container_iface = container_iface

    @staticmethod
    def _run_ip(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run an ip command."""
        try:
            result = subprocess.run(
                ["ip", *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=check,
            )
            return result
        except subprocess.TimeoutExpired as e:
            raise NetworkError(f"ip command timed out: {' '.join(args)}") from e
        except subprocess.CalledProcessError as e:
            raise NetworkError(
                f"ip command failed: {' '.join(args)}: {e.stderr.strip()}"
            ) from e
        except FileNotFoundError as e:
            raise NetworkError("ip command not found. Is iproute2 installed?") from e

    def create(self) -> None:
        """Create the veth pair."""
        try:
            self._run_ip("link", "add", self.host_iface, "type", "veth",
                         "peer", "name", self.container_iface)
            logger.debug(
                "Created veth pair: %s <-> %s for container %s",
                self.host_iface, self.container_iface, self.container_id,
            )
        except NetworkError as e:
            raise NetworkError(
                f"Failed to create veth pair for container {self.container_id}: {e}"
            ) from e

    def move_to_container(self, container_pid: int) -> None:
        """
        Move the container end of the veth pair into the container's network namespace.

        Args:
            container_pid: PID of the container's init process.
        """
        try:
            self._run_ip("link", "set", self.container_iface, "netns", str(container_pid))
            logger.debug(
                "Moved %s to network namespace of PID %d",
                self.container_iface, container_pid,
            )
        except NetworkError as e:
            raise NetworkError(
                f"Failed to move veth to container namespace: {e}"
            ) from e

    def configure_host(self, bridge: str, mtu: int = 1500) -> None:
        """
        Attach host-side veth to bridge and bring it up.

        Args:
            bridge: Bridge interface name.
            mtu: MTU value.
        """
        try:
            self._run_ip("link", "set", self.host_iface, "mtu", str(mtu))
            self._run_ip("link", "set", self.host_iface, "master", bridge)
            self._run_ip("link", "set", self.host_iface, "up")
            logger.debug("Configured host veth %s on bridge %s", self.host_iface, bridge)
        except NetworkError as e:
            raise NetworkError(
                f"Failed to configure host veth {self.host_iface}: {e}"
            ) from e

    def delete(self) -> None:
        """Delete the host-side veth interface."""
        try:
            self._run_ip("link", "delete", self.host_iface, check=False)
            logger.debug("Deleted veth interface %s", self.host_iface)
        except NetworkError:
            pass


class BridgeNetwork:
    """
    Manages a Linux bridge for container networking.

    Creates and configures a bridge with NAT/masquerade for
    outbound connectivity.
    """

    def __init__(
        self,
        name: str = "ainos0",
        subnet: str = "10.88.0.0/16",
        gateway: str = "10.88.0.1",
    ) -> None:
        self.name = name
        self.subnet = subnet
        self.gateway = gateway
        self._ip_allocated: dict[str, str] = {}

    def ensure_bridge(self) -> None:
        """Create the bridge if it doesn't exist."""
        try:
            # Check if bridge exists
            result = subprocess.run(
                ["ip", "link", "show", self.name],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                logger.debug("Bridge %s already exists", self.name)
                return

            # Create bridge
            subprocess.run(
                ["ip", "link", "add", self.name, "type", "bridge"],
                check=True, capture_output=True, text=True, timeout=10,
            )
            subprocess.run(
                ["ip", "addr", "add", f"{self.gateway}/16", "dev", self.name],
                check=True, capture_output=True, text=True, timeout=10,
            )
            subprocess.run(
                ["ip", "link", "set", self.name, "up"],
                check=True, capture_output=True, text=True, timeout=10,
            )

            # Enable NAT/masquerade
            self._enable_nat()

            logger.info("Created bridge %s (%s, gateway %s)", self.name, self.subnet, self.gateway)
        except subprocess.CalledProcessError as e:
            raise NetworkError(f"Failed to create bridge {self.name}: {e.stderr.strip()}")
        except FileNotFoundError as e:
            raise NetworkError("ip/iptables commands not found. Are iproute2 and iptables installed?") from e

    def _enable_nat(self) -> None:
        """Enable IP forwarding and NAT masquerade."""
        try:
            # Enable IP forwarding
            Path("/proc/sys/net/ipv4/ip_forward").write_text("1")

            # Enable NAT
            subprocess.run(
                ["iptables", "-t", "nat", "-C", "POSTROUTING",
                 "-s", self.subnet, "!", "-o", self.name, "-j", "MASQUERADE"],
                capture_output=True, timeout=5, check=False,
            )
            subprocess.run(
                ["iptables", "-t", "nat", "-A", "POSTROUTING",
                 "-s", self.subnet, "!", "-o", self.name, "-j", "MASQUERADE"],
                check=True, capture_output=True, text=True, timeout=10,
            )

            # Allow forwarding between bridge and external interfaces
            for iface in ["-i", "-o"]:
                subprocess.run(
                    ["iptables", "-C", "FORWARD", iface, self.name, "-j", "ACCEPT"],
                    capture_output=True, timeout=5, check=False,
                )
                subprocess.run(
                    ["iptables", "-A", "FORWARD", iface, self.name, "-j", "ACCEPT"],
                    check=True, capture_output=True, text=True, timeout=10,
                )

            logger.info("Enabled NAT masquerade for bridge %s", self.name)
        except subprocess.CalledProcessError as e:
            logger.warning("Failed to enable NAT: %s", e.stderr.strip())
        except OSError as e:
            logger.warning("Failed to enable IP forwarding: %s", e)

    def allocate_ip(self, container_id: str) -> str:
        """
        Allocate an IP address from the bridge subnet.

        Args:
            container_id: Container identifier for tracking.

        Returns:
            Allocated IP address string.
        """
        if container_id in self._ip_allocated:
            return self._ip_allocated[container_id]

        network = ipaddress.IPv4Network(self.subnet, strict=False)
        host_ips = list(network.hosts())

        # Skip gateway (first host) and previously allocated
        allocated_ips = set(self._ip_allocated.values())
        # Calculate offset based on container_id hash for consistency
        offset = 2 + (hash(container_id) % (len(host_ips) - 10))

        for i in range(offset, len(host_ips) - 1):
            ip_str = str(host_ips[i])
            if ip_str not in allocated_ips:
                self._ip_allocated[container_id] = ip_str
                logger.debug("Allocated IP %s to container %s", ip_str, container_id)
                return ip_str

        # Fallback: sequential allocation
        for i in range(2, len(host_ips) - 1):
            ip_str = str(host_ips[i])
            if ip_str not in allocated_ips:
                self._ip_allocated[container_id] = ip_str
                return ip_str

        raise NetworkError(f"No available IP addresses in subnet {self.subnet}")

    def release_ip(self, container_id: str) -> None:
        """Release a previously allocated IP address."""
        self._ip_allocated.pop(container_id, None)
        logger.debug("Released IP for container %s", container_id)

    def add_port_forwarding(self, mapping: PortMapping, container_ip: str) -> None:
        """
        Add iptables DNAT rule for port forwarding.

        Args:
            mapping: Port mapping configuration.
            container_ip: Container's IP address.
        """
        mapping.validate()
        try:
            subprocess.run(
                [
                    "iptables", "-t", "nat", "-A", "PREROUTING",
                    "-d", mapping.host_ip,
                    "-p", mapping.protocol,
                    "--dport", str(mapping.host_port),
                    "-j", "DNAT",
                    "--to-destination", f"{container_ip}:{mapping.container_port}",
                ],
                check=True, capture_output=True, text=True, timeout=10,
            )
            # Also add FORWARD rule
            subprocess.run(
                [
                    "iptables", "-A", "FORWARD",
                    "-p", mapping.protocol,
                    "-d", container_ip,
                    "--dport", str(mapping.container_port),
                    "-j", "ACCEPT",
                ],
                check=True, capture_output=True, text=True, timeout=10,
            )
            logger.info(
                "Added port forwarding: %s:%d -> %s:%d/%s",
                mapping.host_ip, mapping.host_port,
                container_ip, mapping.container_port, mapping.protocol,
            )
        except subprocess.CalledProcessError as e:
            raise NetworkError(f"Failed to add port forwarding: {e.stderr.strip()}")

    def remove_port_forwarding(self, mapping: PortMapping, container_ip: str) -> None:
        """Remove iptables DNAT rule for port forwarding."""
        try:
            subprocess.run(
                [
                    "iptables", "-t", "nat", "-D", "PREROUTING",
                    "-d", mapping.host_ip,
                    "-p", mapping.protocol,
                    "--dport", str(mapping.host_port),
                    "-j", "DNAT",
                    "--to-destination", f"{container_ip}:{mapping.container_port}",
                ],
                check=False, capture_output=True, timeout=5,
            )
            subprocess.run(
                [
                    "iptables", "-D", "FORWARD",
                    "-p", mapping.protocol,
                    "-d", container_ip,
                    "--dport", str(mapping.container_port),
                    "-j", "ACCEPT",
                ],
                check=False, capture_output=True, timeout=5,
            )
            logger.info(
                "Removed port forwarding: %s:%d -> %s:%d/%s",
                mapping.host_ip, mapping.host_port,
                container_ip, mapping.container_port, mapping.protocol,
            )
        except OSError as e:
            logger.warning("Failed to remove port forwarding: %s", e)

    def clean_nat_rules(self) -> None:
        """Remove all NAT rules for this bridge."""
        try:
            subprocess.run(
                ["iptables", "-t", "nat", "-D", "POSTROUTING",
                 "-s", self.subnet, "!", "-o", self.name, "-j", "MASQUERADE"],
                check=False, capture_output=True, timeout=5,
            )
            subprocess.run(
                ["iptables", "-D", "FORWARD", "-i", self.name, "-j", "ACCEPT"],
                check=False, capture_output=True, timeout=5,
            )
            subprocess.run(
                ["iptables", "-D", "FORWARD", "-o", self.name, "-j", "ACCEPT"],
                check=False, capture_output=True, timeout=5,
            )
        except OSError as e:
            logger.warning("Failed to clean NAT rules: %s", e)

    def destroy(self) -> None:
        """Delete the bridge."""
        try:
            self.clean_nat_rules()
            subprocess.run(
                ["ip", "link", "set", self.name, "down"],
                check=False, capture_output=True, timeout=5,
            )
            subprocess.run(
                ["ip", "link", "delete", self.name, "type", "bridge"],
                check=False, capture_output=True, timeout=5,
            )
            logger.info("Destroyed bridge %s", self.name)
        except OSError as e:
            logger.warning("Failed to destroy bridge: %s", e)


class NetworkManager:
    """
    Central network manager for container networking.

    Handles network creation, configuration, and teardown across
    all supported network modes.
    """

    _instances: ClassVar[dict[str, "NetworkManager"]] = {}
    _bridges: ClassVar[dict[str, BridgeNetwork]] = {}

    def __init__(self, container_id: str, config: Optional[NetworkConfig] = None) -> None:
        self.container_id = container_id
        self.config = config or NetworkConfig()
        self._veth: Optional[VirtualEthernetPair] = None
        self._bridge: Optional[BridgeNetwork] = None
        self._container_ip: Optional[str] = None

    @classmethod
    def get_instance(cls, container_id: str, config: Optional[NetworkConfig] = None) -> "NetworkManager":
        """Get or create a NetworkManager instance for a container."""
        if container_id not in cls._instances:
            cls._instances[container_id] = cls(container_id, config)
        return cls._instances[container_id]

    @classmethod
    def remove_instance(cls, container_id: str) -> None:
        """Remove a NetworkManager instance."""
        cls._instances.pop(container_id, None)

    @staticmethod
    def _generate_iface_name() -> str:
        """Generate a unique interface name."""
        suffix = "".join(random.choices(string.hexdigits.lower(), k=5))
        return f"veth{suffix}"

    def setup_bridge_network(self, container_pid: int) -> dict[str, Any]:
        """
        Set up bridge networking for a container.

        Args:
            container_pid: PID of the container's init process.

        Returns:
            Dict with network configuration details (ip, gateway, iface).
        """
        if self.config.mode != NetworkMode.BRIDGE:
            raise NetworkError(
                f"Expected bridge mode, got {self.config.mode}", self.config.mode
            )

        self.config.validate()

        # Get or create bridge
        bridge_name = self.config.bridge_name
        if bridge_name not in self._bridges:
            bridge = BridgeNetwork(
                name=bridge_name,
                subnet=self.config.subnet or "10.88.0.0/16",
                gateway=self.config.gateway or "10.88.0.1",
            )
            bridge.ensure_bridge()
            self._bridges[bridge_name] = bridge
        else:
            bridge = self._bridges[bridge_name]

        self._bridge = bridge

        # Allocate IP
        container_ip = self.config.ip_address or bridge.allocate_ip(self.container_id)
        self._container_ip = container_ip

        # Create veth pair
        host_iface = self._generate_iface_name()
        self._veth = VirtualEthernetPair(self.container_id, host_iface, "eth0")
        self._veth.create()
        self._veth.configure_host(bridge_name, self.config.mtu)
        self._veth.move_to_container(container_pid)

        logger.info(
            "Set up bridge network for container %s: IP=%s, veth=%s",
            self.container_id, container_ip, host_iface,
        )

        return {
            "ip_address": container_ip,
            "gateway": bridge.gateway,
            "interface": "eth0",
            "host_interface": host_iface,
            "bridge": bridge_name,
            "mac_address": self.config.mac_address or "",
            "dns": self.config.dns,
            "dns_search": self.config.dns_search,
        }

    def setup_host_network(self) -> dict[str, Any]:
        """
        Set up host networking (shares host's network stack).

        Returns:
            Dict with network configuration.
        """
        if self.config.mode != NetworkMode.HOST:
            raise NetworkError(f"Expected host mode, got {self.config.mode}", self.config.mode)

        logger.info("Set up host network for container %s", self.container_id)
        return {
            "mode": "host",
            "ip_address": "host",
            "gateway": "host",
            "interface": "host",
            "dns": self.config.dns,
        }

    def setup_none_network(self) -> dict[str, Any]:
        """
        Set up isolated networking (no network interfaces).

        Returns:
            Dict with network configuration.
        """
        if self.config.mode != NetworkMode.NONE:
            raise NetworkError(f"Expected none mode, got {self.config.mode}", self.config.mode)

        logger.info("Set up isolated network for container %s", self.container_id)
        return {
            "mode": "none",
            "ip_address": None,
            "gateway": None,
            "interface": None,
            "dns": [],
        }

    def setup_network(self, container_pid: int) -> dict[str, Any]:
        """
        Set up networking based on the configured mode.

        Args:
            container_pid: PID of the container's init process.

        Returns:
            Dict with network configuration details.
        """
        mode = self.config.mode

        if mode == NetworkMode.BRIDGE:
            return self.setup_bridge_network(container_pid)
        elif mode == NetworkMode.HOST:
            return self.setup_host_network()
        elif mode == NetworkMode.NONE:
            return self.setup_none_network()
        elif mode == NetworkMode.OVERLAY:
            raise NetworkError("Overlay networking not yet implemented", mode)
        elif mode == NetworkMode.MACVLAN:
            raise NetworkError("MACVLAN networking not yet implemented", mode)
        else:
            raise NetworkError(f"Unsupported network mode: {mode}", mode)

    def add_port_mappings(self) -> None:
        """Add port forwarding rules for all configured port mappings."""
        if self.config.mode == NetworkMode.HOST:
            logger.debug("Host mode: port mappings handled by container directly")
            return

        if self.config.mode == NetworkMode.NONE:
            logger.warning("None mode: port mappings not supported")
            return

        if not self._bridge or not self._container_ip:
            raise NetworkError("Bridge network not set up")

        for mapping in self.config.ports:
            self._bridge.add_port_forwarding(mapping, self._container_ip)

    def remove_port_mappings(self) -> None:
        """Remove all port forwarding rules."""
        if not self._bridge or not self._container_ip:
            return

        for mapping in self.config.ports:
            self._bridge.remove_port_forwarding(mapping, self._container_ip)

    def get_stats(self) -> NetworkStats:
        """Get network statistics for the container."""
        if self._veth and self._veth.host_iface:
            return NetworkStats.from_proc(self._veth.host_iface)
        return NetworkStats()

    def teardown(self) -> None:
        """Tear down the container's network configuration."""
        try:
            self.remove_port_mappings()

            if self._bridge and self._container_ip:
                self._bridge.release_ip(self.container_id)

            if self._veth:
                self._veth.delete()

            self._veth = None
            self._container_ip = None

            logger.info("Tore down network for container %s", self.container_id)
        except Exception as e:
            logger.error("Error tearing down network for %s: %s", self.container_id, e)

    @classmethod
    def cleanup_all(cls) -> None:
        """Clean up all network resources."""
        for container_id in list(cls._instances):
            cls._instances[container_id].teardown()
            cls.remove_instance(container_id)

        for bridge in cls._bridges.values():
            bridge.destroy()
        cls._bridges.clear()

    @classmethod
    def list_networks(cls) -> list[dict[str, Any]]:
        """List all container networks."""
        networks: list[dict[str, Any]] = []
        for container_id, instance in cls._instances.items():
            networks.append({
                "container_id": container_id,
                "mode": instance.config.mode.value,
                "ip": instance._container_ip,
                "bridge": instance.config.bridge_name if instance._bridge else None,
            })
        return networks