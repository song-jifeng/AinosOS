#!/usr/bin/env python3
"""Ainos Desktop - System Monitor Widget.

Provides real-time system performance monitoring with detailed
metrics, process list, and diagnostic tools.
"""

import logging
import time
import platform
from typing import Any
from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QGroupBox,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
)

from widgets.charts import (
    CpuChart,
    MemoryChart,
    GpuChart,
    TemperatureChart,
    TimeSeriesChart,
)

logger = logging.getLogger(__name__)


class MetricGauge(QFrame):
    """A circular-style gauge widget for displaying a single metric."""

    def __init__(
        self,
        title: str,
        unit: str = "%",
        max_value: float = 100.0,
        color: str = "#89B4FA",
        parent: QWidget | None = None,
    ):
        """Initialize the metric gauge.

        Args:
            title: Gauge title.
            unit: Unit of measurement.
            max_value: Maximum value for the gauge.
            color: Gauge color.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._title = title
        self._unit = unit
        self._max_value = max_value
        self._color = color
        self._value = 0.0

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("metricGauge")
        self.setMinimumSize(140, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the gauge UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Title
        title_label = QLabel(self._title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 10pt; color: #A0A8C0; font-weight: 500;")
        layout.addWidget(title_label)

        # Value
        self._value_label = QLabel("0.0")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_label.setStyleSheet(
            f"font-size: 32pt; font-weight: bold; color: {self._color};"
        )
        layout.addWidget(self._value_label)

        # Unit
        unit_label = QLabel(self._unit)
        unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        unit_label.setStyleSheet("font-size: 10pt; color: #6C7086;")
        layout.addWidget(unit_label)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, int(self._max_value))
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: #313244;
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {self._color};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._progress)

    def set_value(self, value: float) -> None:
        """Set the gauge value.

        Args:
            value: Current metric value.
        """
        self._value = value
        self._value_label.setText(f"{value:.1f}")
        self._progress.setValue(int(min(value, self._max_value)))

        # Color code based on value
        if value < 50:
            color = "#A6E3A1"
        elif value < 80:
            color = "#FAB387"
        else:
            color = "#F38BA8"

        self._value_label.setStyleSheet(
            f"font-size: 32pt; font-weight: bold; color: {color};"
        )
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: #313244;
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)


class ProcessTableWidget(QTableWidget):
    """A table widget for displaying running processes."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize the process table.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the table UI."""
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels([
            "PID", "Name", "CPU %", "Memory %", "Memory (MB)", "Status"
        ])
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(True)

    def update_processes(self, processes: list[dict[str, Any]]) -> None:
        """Update the process list.

        Args:
            processes: List of process dictionaries with pid, name, cpu, memory, etc.
        """
        self.setRowCount(0)
        for proc in processes:
            row = self.rowCount()
            self.insertRow(row)

            self.setItem(row, 0, QTableWidgetItem(str(proc.get("pid", ""))))
            self.setItem(row, 1, QTableWidgetItem(proc.get("name", "")))

            cpu = proc.get("cpu_percent", 0)
            cpu_item = QTableWidgetItem(f"{cpu:.1f}")
            if cpu > 50:
                cpu_item.setForeground(QColor("#F38BA8"))
            elif cpu > 20:
                cpu_item.setForeground(QColor("#FAB387"))
            self.setItem(row, 2, cpu_item)

            mem = proc.get("memory_percent", 0)
            mem_item = QTableWidgetItem(f"{mem:.1f}")
            if mem > 20:
                mem_item.setForeground(QColor("#F38BA8"))
            elif mem > 10:
                mem_item.setForeground(QColor("#FAB387"))
            self.setItem(row, 3, mem_item)

            mem_mb = proc.get("memory_mb", 0)
            self.setItem(row, 4, QTableWidgetItem(f"{mem_mb:.0f}"))

            self.setItem(row, 5, QTableWidgetItem(proc.get("status", "running")))


class MonitorWidget(QWidget):
    """System monitoring widget with real-time metrics and diagnostics."""

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the monitor widget.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app
        self._theme = "dark"

        # Data history
        self._history: dict[str, deque] = {
            "cpu": deque(maxlen=300),
            "memory": deque(maxlen=300),
            "gpu": deque(maxlen=300),
            "gpu_memory": deque(maxlen=300),
            "temperature": deque(maxlen=300),
        }

        self._setup_ui()

        # Update timer
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_metrics)
        update_interval = self._app.config.get("monitor.update_interval_ms", 2000)
        self._update_timer.start(update_interval)

        logger.info("Monitor widget initialized")

    def _setup_ui(self) -> None:
        """Set up the monitor UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()

        header_text = QLabel("System Monitor")
        header_text.setProperty("heading", True)
        header_layout.addWidget(header_text)

        header_layout.addStretch()

        # Diagnostics button
        diag_btn = QPushButton("Run Diagnostics")
        diag_btn.setProperty("primary", True)
        diag_btn.clicked.connect(self.run_diagnostics)
        header_layout.addWidget(diag_btn)

        # Pause/Resume button
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.clicked.connect(self._toggle_pause)
        header_layout.addWidget(self._pause_btn)

        main_layout.addLayout(header_layout)

        # Subtitle
        subtitle = QLabel("Real-time system performance and resource utilization")
        subtitle.setProperty("subheading", True)
        main_layout.addLayout(header_layout)
        main_layout.addWidget(subtitle)

        # ===== Gauges Row =====
        gauges_layout = QHBoxLayout()
        gauges_layout.setSpacing(12)

        self._cpu_gauge = MetricGauge("CPU Usage", "%", 100, "#89B4FA")
        gauges_layout.addWidget(self._cpu_gauge)

        self._memory_gauge = MetricGauge("Memory", "%", 100, "#A6E3A1")
        gauges_layout.addWidget(self._memory_gauge)

        self._gpu_gauge = MetricGauge("GPU", "%", 100, "#CBA6F7")
        gauges_layout.addWidget(self._gpu_gauge)

        self._gpu_mem_gauge = MetricGauge("GPU Memory", "%", 100, "#FAB387")
        gauges_layout.addWidget(self._gpu_mem_gauge)

        self._temp_gauge = MetricGauge("Temperature", "C", 100, "#F38BA8")
        gauges_layout.addWidget(self._temp_gauge)

        main_layout.addLayout(gauges_layout)

        # ===== Tabbed Content =====
        self._tab_widget = QTabWidget()

        # Charts tab
        charts_tab = QWidget()
        charts_layout = QVBoxLayout(charts_tab)
        charts_layout.setContentsMargins(12, 12, 12, 12)

        self._system_charts = SystemChartWidget()
        charts_layout.addWidget(self._system_charts)

        self._tab_widget.addTab(charts_tab, "Charts")

        # Processes tab
        processes_tab = QWidget()
        processes_layout = QVBoxLayout(processes_tab)
        processes_layout.setContentsMargins(12, 12, 12, 12)

        self._process_table = ProcessTableWidget()
        processes_layout.addWidget(self._process_table)

        self._tab_widget.addTab(processes_tab, "Processes")

        # System Info tab
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        info_layout.setContentsMargins(12, 12, 12, 12)

        self._info_tree = QTreeWidget()
        self._info_tree.setHeaderLabels(["Property", "Value"])
        self._info_tree.setAlternatingRowColors(True)
        self._info_tree.setColumnWidth(0, 250)
        info_layout.addWidget(self._info_tree)

        self._tab_widget.addTab(info_tab, "System Info")

        # Diagnostics tab
        diag_tab = QWidget()
        diag_layout = QVBoxLayout(diag_tab)
        diag_layout.setContentsMargins(12, 12, 12, 12)

        diag_header = QHBoxLayout()
        diag_run_btn = QPushButton("Run Diagnostics")
        diag_run_btn.setProperty("primary", True)
        diag_run_btn.clicked.connect(self.run_diagnostics)
        diag_header.addWidget(diag_run_btn)

        diag_clear_btn = QPushButton("Clear")
        diag_clear_btn.clicked.connect(self._clear_diagnostics)
        diag_header.addWidget(diag_clear_btn)
        diag_header.addStretch()

        diag_layout.addLayout(diag_header)

        self._diag_output = QTextEdit()
        self._diag_output.setReadOnly(True)
        self._diag_output.setStyleSheet("""
            QTextEdit {
                background-color: #1E1E2E;
                color: #CDD6F4;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 12px;
                font-family: 'Consolas', 'SF Mono', 'Fira Code', monospace;
                font-size: 9pt;
            }
        """)
        diag_layout.addWidget(self._diag_output)

        self._tab_widget.addTab(diag_tab, "Diagnostics")

        main_layout.addWidget(self._tab_widget, 1)

        # Fix the duplicate header_layout issue
        main_layout.insertLayout(1, header_layout)

    @Slot()
    def _update_metrics(self) -> None:
        """Update all monitoring metrics."""
        try:
            import psutil

            # CPU
            cpu_percent = psutil.cpu_percent(interval=None)
            cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
            self._cpu_gauge.set_value(cpu_percent)
            self._history["cpu"].append(cpu_percent)

            # Memory
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
            self._memory_gauge.set_value(mem_percent)
            self._history["memory"].append(mem_percent)

            # GPU info (via nvidia-smi)
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split(", ")
                    if len(parts) >= 1:
                        gpu_util = float(parts[0])
                        self._gpu_gauge.set_value(gpu_util)
                        self._history["gpu"].append(gpu_util)
                    if len(parts) >= 3:
                        gpu_mem_used = float(parts[1])
                        gpu_mem_total = float(parts[2])
                        gpu_mem_pct = (gpu_mem_used / gpu_mem_total * 100) if gpu_mem_total > 0 else 0
                        self._gpu_mem_gauge.set_value(gpu_mem_pct)
                        self._history["gpu_memory"].append(gpu_mem_pct)
                    if len(parts) >= 4:
                        temp = float(parts[3])
                        self._temp_gauge.set_value(temp)
                        self._history["temperature"].append(temp)
            except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
                self._gpu_gauge.set_value(0)
                self._gpu_mem_gauge.set_value(0)
                self._temp_gauge.set_value(0)

            # Update charts
            self._system_charts.update_data(
                cpu=cpu_percent,
                memory=mem_percent,
                gpu=self._gpu_gauge._value if hasattr(self._gpu_gauge, '_value') else None,
                temperature=self._temp_gauge._value if hasattr(self._temp_gauge, '_value') else None,
            )

            # Update process table
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'status']):
                try:
                    info = proc.info
                    mem_info = info.get('memory_info')
                    processes.append({
                        "pid": info['pid'],
                        "name": info['name'] or 'Unknown',
                        "cpu_percent": info['cpu_percent'] or 0.0,
                        "memory_percent": info['memory_percent'] or 0.0,
                        "memory_mb": (mem_info.rss / 1024 / 1024) if mem_info else 0,
                        "status": info['status'] or 'unknown',
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Sort by CPU usage (descending) and take top 50
            processes.sort(key=lambda p: p['cpu_percent'], reverse=True)
            self._process_table.update_processes(processes[:50])

            # Update system info tree
            self._update_system_info()

        except ImportError:
            logger.debug("psutil not available for monitoring")
        except Exception as e:
            logger.debug("Monitor update error: %s", e)

    def _update_system_info(self) -> None:
        """Update the system information tree."""
        self._info_tree.clear()

        try:
            import psutil
            import platform as pf

            # OS info
            os_root = QTreeWidgetItem(self._info_tree, ["Operating System", ""])
            QTreeWidgetItem(os_root, ["System", pf.system()])
            QTreeWidgetItem(os_root, ["Release", pf.release()])
            QTreeWidgetItem(os_root, ["Version", pf.version()])
            QTreeWidgetItem(os_root, ["Architecture", pf.machine()])
            QTreeWidgetItem(os_root, ["Processor", pf.processor()])
            QTreeWidgetItem(os_root, ["Hostname", pf.node()])
            QTreeWidgetItem(os_root, ["Python", pf.python_version()])

            # CPU info
            cpu_root = QTreeWidgetItem(self._info_tree, ["CPU", ""])
            QTreeWidgetItem(cpu_root, ["Physical Cores", str(psutil.cpu_count(logical=False))])
            QTreeWidgetItem(cpu_root, ["Logical Cores", str(psutil.cpu_count(logical=True))])
            QTreeWidgetItem(cpu_root, ["Max Frequency", f"{psutil.cpu_freq().max:.0f} MHz" if psutil.cpu_freq() else "N/A"])
            QTreeWidgetItem(cpu_root, ["Current Frequency", f"{psutil.cpu_freq().current:.0f} MHz" if psutil.cpu_freq() else "N/A"])
            QTreeWidgetItem(cpu_root, ["Current Usage", f"{psutil.cpu_percent(interval=None):.1f}%"])

            # Memory info
            mem = psutil.virtual_memory()
            mem_root = QTreeWidgetItem(self._info_tree, ["Memory", ""])
            QTreeWidgetItem(mem_root, ["Total", f"{mem.total / (1024**3):.1f} GB"])
            QTreeWidgetItem(mem_root, ["Available", f"{mem.available / (1024**3):.1f} GB"])
            QTreeWidgetItem(mem_root, ["Used", f"{mem.used / (1024**3):.1f} GB"])
            QTreeWidgetItem(mem_root, ["Usage", f"{mem.percent:.1f}%"])

            # Swap
            swap = psutil.swap_memory()
            swap_root = QTreeWidgetItem(self._info_tree, ["Swap", ""])
            QTreeWidgetItem(swap_root, ["Total", f"{swap.total / (1024**3):.1f} GB"])
            QTreeWidgetItem(swap_root, ["Used", f"{swap.used / (1024**3):.1f} GB"])
            QTreeWidgetItem(swap_root, ["Usage", f"{swap.percent:.1f}%"])

            # Disk
            disk_root = QTreeWidgetItem(self._info_tree, ["Disk", ""])
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disk_item = QTreeWidgetItem(disk_root, [part.mountpoint, ""])
                    QTreeWidgetItem(disk_item, ["Filesystem", part.fstype])
                    QTreeWidgetItem(disk_item, ["Total", f"{usage.total / (1024**3):.1f} GB"])
                    QTreeWidgetItem(disk_item, ["Used", f"{usage.used / (1024**3):.1f} GB"])
                    QTreeWidgetItem(disk_item, ["Free", f"{usage.free / (1024**3):.1f} GB"])
                    QTreeWidgetItem(disk_item, ["Usage", f"{usage.percent:.1f}%"])
                except (PermissionError, OSError):
                    continue

            # Network
            net_root = QTreeWidgetItem(self._info_tree, ["Network", ""])
            net_io = psutil.net_io_counters()
            QTreeWidgetItem(net_root, ["Bytes Sent", f"{net_io.bytes_sent / (1024**3):.2f} GB"])
            QTreeWidgetItem(net_root, ["Bytes Received", f"{net_io.bytes_recv / (1024**3):.2f} GB"])
            QTreeWidgetItem(net_root, ["Packets Sent", str(net_io.packets_sent)])
            QTreeWidgetItem(net_root, ["Packets Received", str(net_io.packets_recv)])

            # Boot time
            boot_root = QTreeWidgetItem(self._info_tree, ["System", ""])
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            QTreeWidgetItem(boot_root, ["Boot Time", boot_time.strftime("%Y-%m-%d %H:%M:%S")])
            uptime = datetime.now() - boot_time
            days = uptime.days
            hours = uptime.seconds // 3600
            minutes = (uptime.seconds % 3600) // 60
            QTreeWidgetItem(boot_root, ["Uptime", f"{days}d {hours}h {minutes}m"])

            # GPU info
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    gpu_root = QTreeWidgetItem(self._info_tree, ["GPU", ""])
                    for line in result.stdout.strip().split('\n'):
                        parts = [p.strip() for p in line.split(',')]
                        if parts:
                            gpu_item = QTreeWidgetItem(gpu_root, [parts[0], ""])
                            if len(parts) > 1:
                                QTreeWidgetItem(gpu_item, ["Driver", parts[1]])
                            if len(parts) > 2:
                                QTreeWidgetItem(gpu_item, ["Memory", f"{parts[2]} MB"])
                            if len(parts) > 3:
                                QTreeWidgetItem(gpu_item, ["Temperature", f"{parts[3]} C"])
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        except ImportError:
            QTreeWidgetItem(self._info_tree, ["Error", "psutil not available"])

        # Expand top-level items
        self._info_tree.expandToDepth(0)

    @Slot()
    def run_diagnostics(self) -> None:
        """Run system diagnostics and output results."""
        self._tab_widget.setCurrentIndex(3)
        self._diag_output.clear()

        self._diag_output.append("=" * 60)
        self._diag_output.append("  AINOS SYSTEM DIAGNOSTICS")
        self._diag_output.append(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._diag_output.append("=" * 60)
        self._diag_output.append("")

        try:
            import psutil

            # CPU Test
            self._diag_output.append("[CPU]")
            self._diag_output.append(f"  Physical cores: {psutil.cpu_count(logical=False)}")
            self._diag_output.append(f"  Logical cores: {psutil.cpu_count(logical=True)}")
            self._diag_output.append(f"  Current usage: {psutil.cpu_percent(interval=0.5):.1f}%")
            self._diag_output.append(f"  Per-core: {psutil.cpu_percent(interval=None, percpu=True)}")

            # Memory Test
            mem = psutil.virtual_memory()
            self._diag_output.append("")
            self._diag_output.append("[MEMORY]")
            self._diag_output.append(f"  Total: {mem.total / (1024**3):.1f} GB")
            self._diag_output.append(f"  Available: {mem.available / (1024**3):.1f} GB")
            self._diag_output.append(f"  Used: {mem.used / (1024**3):.1f} GB")
            self._diag_output.append(f"  Usage: {mem.percent:.1f}%")

            # Disk Test
            self._diag_output.append("")
            self._diag_output.append("[DISK]")
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    self._diag_output.append(f"  {part.mountpoint} ({part.fstype}):")
                    self._diag_output.append(f"    Total: {usage.total / (1024**3):.1f} GB")
                    self._diag_output.append(f"    Used: {usage.used / (1024**3):.1f} GB ({usage.percent}%)")
                    self._diag_output.append(f"    Free: {usage.free / (1024**3):.1f} GB")
                except PermissionError:
                    continue

            # GPU Test
            self._diag_output.append("")
            self._diag_output.append("[GPU]")
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,name,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            self._diag_output.append(f"  {line}")
                else:
                    self._diag_output.append("  No NVIDIA GPU detected or nvidia-smi not available")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._diag_output.append("  No NVIDIA GPU detected or nvidia-smi not available")

            # Network Test
            self._diag_output.append("")
            self._diag_output.append("[NETWORK]")
            net_io = psutil.net_io_counters()
            self._diag_output.append(f"  Bytes sent: {net_io.bytes_sent / (1024**3):.2f} GB")
            self._diag_output.append(f"  Bytes received: {net_io.bytes_recv / (1024**3):.2f} GB")

            # System
            self._diag_output.append("")
            self._diag_output.append("[SYSTEM]")
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            self._diag_output.append(f"  Boot time: {boot_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self._diag_output.append(f"  Uptime: {uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds % 3600) // 60}m")
            self._diag_output.append(f"  Users: {len(psutil.users())}")

            self._diag_output.append("")
            self._diag_output.append("=" * 60)
            self._diag_output.append("  DIAGNOSTICS COMPLETE")
            self._diag_output.append("=" * 60)

        except ImportError:
            self._diag_output.append("ERROR: psutil library is required for diagnostics.")
            self._diag_output.append("Install with: pip install psutil")
        except Exception as e:
            self._diag_output.append(f"ERROR: Diagnostics failed: {e}")
            logger.exception("Diagnostics error")

    @Slot()
    def _clear_diagnostics(self) -> None:
        """Clear the diagnostics output."""
        self._diag_output.clear()

    @Slot()
    def _toggle_pause(self) -> None:
        """Toggle pause/resume of monitoring updates."""
        if self._update_timer.isActive():
            self._update_timer.stop()
            self._pause_btn.setText("Resume")
        else:
            self._update_timer.start()
            self._pause_btn.setText("Pause")

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the monitor widget.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name
        self._system_charts.apply_theme(theme_name)

    def cleanup(self) -> None:
        """Cleanup resources."""
        self._update_timer.stop()