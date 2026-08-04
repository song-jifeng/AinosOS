#!/usr/bin/env python3
"""Ainos Desktop - Dashboard Widget.

Provides an overview dashboard with system metrics, model status,
quick actions, and real-time charts.
"""

import logging
import time
from typing import Any
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QProgressBar,
    QGroupBox,
    QSplitter,
)

from widgets.charts import SystemChartWidget, TimeSeriesChart

logger = logging.getLogger(__name__)


class MetricCard(QFrame):
    """A card widget displaying a single metric value."""

    def __init__(
        self,
        title: str,
        value: str = "--",
        unit: str = "",
        icon: str = "",
        color: str = "#89B4FA",
        parent: QWidget | None = None,
    ):
        """Initialize the metric card.

        Args:
            title: Metric title.
            value: Current value string.
            unit: Unit of measurement.
            icon: Emoji icon.
            color: Accent color.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(180, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._title = title
        self._value = value
        self._unit = unit
        self._icon = icon
        self._color = color

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the card UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        # Top row: icon + title
        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)

        if self._icon:
            icon_label = QLabel(self._icon)
            icon_label.setStyleSheet("font-size: 20px;")
            top_layout.addWidget(icon_label)

        title_label = QLabel(self._title)
        title_label.setStyleSheet(
            f"font-size: 10pt; color: #A0A8C0; font-weight: 500;"
        )
        top_layout.addWidget(title_label)
        top_layout.addStretch()

        layout.addLayout(top_layout)

        # Value
        value_layout = QHBoxLayout()
        value_layout.setSpacing(4)

        self._value_label = QLabel(self._value)
        self._value_label.setStyleSheet(
            f"font-size: 28pt; font-weight: bold; color: {self._color};"
        )
        value_layout.addWidget(self._value_label)

        if self._unit:
            unit_label = QLabel(self._unit)
            unit_label.setStyleSheet(
                f"font-size: 12pt; color: #6C7086; padding-top: 8px;"
            )
            value_layout.addWidget(unit_label)

        value_layout.addStretch()
        layout.addLayout(value_layout)

        # Progress bar container
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #313244;
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {self._color};
                border-radius: 2px;
            }}
        """)
        layout.addWidget(self._progress_bar)

    def set_value(self, value: str) -> None:
        """Set the displayed value.

        Args:
            value: Value string to display.
        """
        self._value_label.setText(value)

    def set_progress(self, value: int) -> None:
        """Set the progress bar value.

        Args:
            value: Progress value (0-100).
        """
        self._progress_bar.setValue(max(0, min(100, value)))


class QuickActionButton(QPushButton):
    """A styled quick action button."""

    def __init__(
        self,
        text: str,
        description: str = "",
        icon: str = "",
        parent: QWidget | None = None,
    ):
        """Initialize the quick action button.

        Args:
            text: Button text.
            description: Description text.
            icon: Emoji icon.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setMinimumSize(160, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Create button content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        if icon:
            icon_label = QLabel(icon)
            icon_label.setStyleSheet("font-size: 24px;")
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        text_label = QLabel(text)
        text_label.setStyleSheet("font-size: 10pt; font-weight: 600; color: #CDD6F4;")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setStyleSheet("font-size: 8pt; color: #6C7086;")
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)


class DashboardWidget(QWidget):
    """Main dashboard overview widget.

    Displays system metrics, model status, quick actions,
    and real-time monitoring charts.
    """

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the dashboard widget.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app
        self._theme = "dark"

        # Data history
        self._cpu_history: list[float] = []
        self._memory_history: list[float] = []
        self._gpu_history: list[float] = []

        # Setup UI
        self._setup_ui()

        # Update timer
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_metrics)
        self._update_timer.start(3000)  # Every 3 seconds

        logger.info("Dashboard widget initialized")

    def _setup_ui(self) -> None:
        """Set up the dashboard UI."""
        # Main scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_content.setObjectName("dashboardContent")
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # Header
        header_layout = QHBoxLayout()

        header_text = QLabel("Dashboard")
        header_text.setProperty("heading", True)
        header_layout.addWidget(header_text)

        header_layout.addStretch()

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("primary", True)
        refresh_btn.setFixedWidth(120)
        refresh_btn.clicked.connect(self._update_metrics)
        header_layout.addWidget(refresh_btn)

        main_layout.addLayout(header_layout)

        # Subtitle
        subtitle = QLabel("System overview and performance metrics")
        subtitle.setProperty("subheading", True)
        main_layout.addWidget(subtitle)

        # ===== Metric Cards Row =====
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        self._cpu_card = MetricCard("CPU Usage", "0%", "", "🖥️", "#89B4FA")
        cards_layout.addWidget(self._cpu_card)

        self._memory_card = MetricCard("Memory", "0%", "", "🧠", "#A6E3A1")
        cards_layout.addWidget(self._memory_card)

        self._gpu_card = MetricCard("GPU Usage", "N/A", "", "🎮", "#CBA6F7")
        cards_layout.addWidget(self._gpu_card)

        self._model_card = MetricCard("Active Models", "0", "", "🤖", "#FAB387")
        cards_layout.addWidget(self._model_card)

        self._uptime_card = MetricCard("Uptime", "0s", "", "⏱️", "#89DCEB")
        cards_layout.addWidget(self._uptime_card)

        main_layout.addLayout(cards_layout)

        # ===== Charts Section =====
        charts_label = QLabel("Real-time Monitoring")
        charts_label.setProperty("subheading", True)
        main_layout.addWidget(charts_label)

        self._charts_widget = SystemChartWidget()
        self._charts_widget.setMinimumHeight(400)
        main_layout.addWidget(self._charts_widget, 1)

        # ===== Quick Actions =====
        actions_label = QLabel("Quick Actions")
        actions_label.setProperty("subheading", True)
        main_layout.addWidget(actions_label)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(12)

        # Quick action buttons
        load_model_btn = QuickActionButton(
            "Load Model", "Load a model from the backend", "📥"
        )
        load_model_btn.clicked.connect(self._on_load_model)
        actions_layout.addWidget(load_model_btn)

        new_inference_btn = QuickActionButton(
            "New Inference", "Start a new inference session", "💬"
        )
        new_inference_btn.clicked.connect(self._on_new_inference)
        actions_layout.addWidget(new_inference_btn)

        run_diagnostics_btn = QuickActionButton(
            "Run Diagnostics", "Check system health", "🔍"
        )
        run_diagnostics_btn.clicked.connect(self._on_run_diagnostics)
        actions_layout.addWidget(run_diagnostics_btn)

        view_logs_btn = QuickActionButton(
            "View Logs", "Browse application logs", "📝"
        )
        view_logs_btn.clicked.connect(self._on_view_logs)
        actions_layout.addWidget(view_logs_btn)

        actions_layout.addStretch()
        main_layout.addLayout(actions_layout)

        # ===== System Info =====
        info_label = QLabel("System Information")
        info_label.setProperty("subheading", True)
        main_layout.addWidget(info_label)

        info_frame = QFrame()
        info_frame.setObjectName("metricCard")
        info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        info_layout = QGridLayout(info_frame)
        info_layout.setSpacing(12)
        info_layout.setContentsMargins(16, 12, 16, 12)

        # System info labels
        self._info_labels = {}
        info_items = [
            ("OS", "os_info", "Detecting..."),
            ("Python", "python_info", ""),
            ("CPU Cores", "cpu_cores", "--"),
            ("Total Memory", "total_mem", "--"),
            ("Disk Usage", "disk_usage", "--"),
            ("Processes", "processes", "--"),
        ]

        for i, (label, key, default) in enumerate(info_items):
            row = i // 3
            col = i % 3
            lbl = QLabel(f"{label}: {default}")
            lbl.setStyleSheet("font-size: 10pt; color: #A0A8C0; padding: 4px 0;")
            info_layout.addWidget(lbl, row, col)
            self._info_labels[key] = lbl

        main_layout.addWidget(info_frame)

        # Add stretch at bottom
        main_layout.addStretch()

        # Setup scroll area
        scroll_area.setWidget(scroll_content)
        scroll_area.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                background-color: #1E1E2E;
                width: 10px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #45475A;
                min-height: 30px;
                border-radius: 5px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #585B70;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

        # Main layout
        main_widget_layout = QVBoxLayout(self)
        main_widget_layout.setContentsMargins(0, 0, 0, 0)
        main_widget_layout.addWidget(scroll_area)

    @Slot()
    def _update_metrics(self) -> None:
        """Update all dashboard metrics."""
        try:
            import psutil

            # CPU
            cpu_percent = psutil.cpu_percent(interval=None)
            cpu_count = psutil.cpu_count()
            self._cpu_card.set_value(f"{cpu_percent:.0f}%")
            self._cpu_card.set_progress(int(cpu_percent))
            self._cpu_history.append(cpu_percent)
            if len(self._cpu_history) > 300:
                self._cpu_history.pop(0)

            # Memory
            mem = psutil.virtual_memory()
            mem_gb = mem.used / (1024 ** 3)
            mem_total_gb = mem.total / (1024 ** 3)
            self._memory_card.set_value(f"{mem.percent:.0f}%")
            self._memory_card.set_progress(int(mem.percent))
            self._memory_history.append(mem.percent)
            if len(self._memory_history) > 300:
                self._memory_history.pop(0)

            # GPU (try nvidia-smi)
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
                    if lines:
                        parts = [p.strip() for p in lines[0].split(',')]
                        if len(parts) >= 1:
                            gpu_util = float(parts[0])
                            self._gpu_card.set_value(f"{gpu_util:.0f}%")
                            self._gpu_card.set_progress(int(gpu_util))
                            self._gpu_history.append(gpu_util)
                            if len(self._gpu_history) > 300:
                                self._gpu_history.pop(0)
                        if len(parts) >= 3:
                            gpu_mem_used = float(parts[1])
                            gpu_mem_total = float(parts[2])
                            self._gpu_card.setToolTip(
                                f"GPU Memory: {gpu_mem_used:.0f}MB / {gpu_mem_total:.0f}MB"
                            )
            except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
                pass

            # Update system info
            import platform
            self._info_labels["os_info"].setText(f"OS: {platform.system()} {platform.release()}")
            self._info_labels["python_info"].setText(f"Python: {platform.python_version()}")
            self._info_labels["cpu_cores"].setText(f"CPU Cores: {cpu_count}")

            mem_total_text = f"{mem_total_gb:.1f} GB"
            self._info_labels["total_mem"].setText(f"Total Memory: {mem_total_text}")

            # Disk
            try:
                disk = psutil.disk_usage('/')
                self._info_labels["disk_usage"].setText(
                    f"Disk: {disk.used / (1024**3):.0f}/{disk.total / (1024**3):.0f} GB ({disk.percent}%)"
                )
            except Exception:
                pass

            # Processes
            try:
                proc_count = len(psutil.pids())
                self._info_labels["processes"].setText(f"Processes: {proc_count}")
            except Exception:
                pass

            # Uptime
            try:
                boot_time = psutil.boot_time()
                uptime_seconds = time.time() - boot_time
                hours = int(uptime_seconds // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                self._uptime_card.set_value(f"{hours}h {minutes}m")
            except Exception:
                pass

            # Update charts
            self._charts_widget.update_data(
                cpu=cpu_percent,
                memory=mem.percent,
            )

            # Model count
            model_count = len(self._app.main_window.get_widget("model_manager")._models) if self._app.main_window and self._app.main_window.get_widget("model_manager") else 0
            self._model_card.set_value(str(model_count))

        except ImportError:
            logger.debug("psutil not available for dashboard metrics")
        except Exception as e:
            logger.debug("Dashboard update error: %s", e)

    @Slot()
    def _on_load_model(self) -> None:
        """Navigate to model manager tab."""
        if self._app.main_window:
            self._app.main_window._switch_to_tab(1)

    @Slot()
    def _on_new_inference(self) -> None:
        """Navigate to inference tab."""
        if self._app.main_window:
            self._app.main_window._switch_to_tab(2)

    @Slot()
    def _on_run_diagnostics(self) -> None:
        """Navigate to monitor tab."""
        if self._app.main_window:
            self._app.main_window._switch_to_tab(3)

    @Slot()
    def _on_view_logs(self) -> None:
        """Navigate to log viewer tab."""
        if self._app.main_window:
            self._app.main_window._switch_to_tab(6)

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the dashboard.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name
        self._charts_widget.apply_theme(theme_name)

    def cleanup(self) -> None:
        """Cleanup resources."""
        self._update_timer.stop()