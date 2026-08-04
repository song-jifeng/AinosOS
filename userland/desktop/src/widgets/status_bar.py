#!/usr/bin/env python3
"""Ainos Desktop - Status Bar Widget.

Provides a comprehensive status bar with connection status,
model state, system load, and backend information.
"""

import logging
import time
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QFrame,
    QSizePolicy,
    QStatusBar,
)

logger = logging.getLogger(__name__)


class StatusIndicator(QFrame):
    """A small colored indicator dot with a label."""

    def __init__(
        self,
        label: str = "",
        color: str = "#6C7086",
        parent: QWidget | None = None,
    ):
        """Initialize the status indicator.

        Args:
            label: Text label for the indicator.
            color: Initial dot color in hex.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        # Color dot
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._dot.setStyleSheet(
            f"background-color: {color}; border-radius: 5px; min-width: 10px; min-height: 10px;"
        )
        layout.addWidget(self._dot)

        # Label
        self._label = QLabel(label)
        self._label.setStyleSheet("font-size: 9pt; color: #CDD6F4;")
        layout.addWidget(self._label)

    @Slot(str)
    def set_color(self, color: str) -> None:
        """Set the indicator dot color.

        Args:
            color: Hex color string.
        """
        self._dot.setStyleSheet(
            f"background-color: {color}; border-radius: 5px; min-width: 10px; min-height: 10px;"
        )

    @Slot(str)
    def set_label(self, text: str) -> None:
        """Set the indicator label text.

        Args:
            text: New label text.
        """
        self._label.setText(text)

    def set_tooltip(self, text: str) -> None:
        """Set the tooltip for this indicator.

        Args:
            text: Tooltip text.
        """
        self.setToolTip(text)


class AinosStatusBar(QStatusBar):
    """Custom status bar with connection and system indicators.

    Provides real-time status of backend connection, loaded models,
    system load, and other operational indicators.
    """

    # Signal emitted when user clicks on a status item
    status_item_clicked = Signal(str)

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the status bar.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app

        # Connection status colors
        self.CONNECTION_COLORS = {
            "connected": "#A6E3A1",
            "connecting": "#FAB387",
            "disconnected": "#F38BA8",
            "error": "#F38BA8",
        }

        # Setup UI
        self._setup_ui()

        # Update timer for system info
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self.update_system_info)
        self._update_timer.start(5000)  # Every 5 seconds

        # Initial update
        self.update_system_info()

        logger.debug("Status bar initialized")

    def _setup_ui(self) -> None:
        """Set up the status bar UI components."""
        self.setStyleSheet("""
            QStatusBar {
                background-color: #181825;
                border-top: 1px solid #313244;
                padding: 2px 8px;
                font-size: 9pt;
            }
            QStatusBar::item {
                border: none;
            }
        """)

        # Remove default permanent widgets margin
        self.setContentsMargins(0, 0, 0, 0)

        # Connection indicator
        self._connection_indicator = StatusIndicator("Disconnected", "#F38BA8")
        self._connection_indicator.setToolTip("Backend connection status")
        self.addPermanentWidget(self._connection_indicator)

        # Separator
        self._add_separator()

        # Model indicator
        self._model_indicator = StatusIndicator("No model", "#6C7086")
        self._model_indicator.setToolTip("Currently loaded model")
        self.addPermanentWidget(self._model_indicator)

        # Separator
        self._add_separator()

        # CPU indicator
        self._cpu_indicator = StatusIndicator("CPU: --%", "#89B4FA")
        self._cpu_indicator.setToolTip("Current CPU usage")
        self.addPermanentWidget(self._cpu_indicator)

        # Separator
        self._add_separator()

        # Memory indicator
        self._memory_indicator = StatusIndicator("MEM: --%", "#A6E3A1")
        self._memory_indicator.setToolTip("Current memory usage")
        self.addPermanentWidget(self._memory_indicator)

        # Separator
        self._add_separator()

        # GPU indicator
        self._gpu_indicator = StatusIndicator("GPU: --%", "#CBA6F7")
        self._gpu_indicator.setToolTip("Current GPU usage")
        self.addPermanentWidget(self._gpu_indicator)

        # Separator
        self._add_separator()

        # Backend info indicator
        self._backend_label = QLabel("Backend: --")
        self._backend_label.setStyleSheet("font-size: 9pt; color: #6C7086; padding: 0 8px;")
        self._backend_label.setToolTip("Backend server information")
        self.addPermanentWidget(self._backend_label)

        # Left side message area
        self._message_label = QLabel("Ready")
        self._message_label.setStyleSheet("font-size: 9pt; color: #6C7086; padding: 0 8px;")
        self.addWidget(self._message_label)

    def _add_separator(self) -> None:
        """Add a vertical separator line."""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: #313244;")
        separator.setFixedWidth(2)
        self.addPermanentWidget(separator)

    @Slot()
    def update_system_info(self) -> None:
        """Update system information display."""
        try:
            # Try to get system metrics from psutil
            import psutil

            # CPU
            cpu_percent = psutil.cpu_percent(interval=None)
            self._cpu_indicator.set_label(f"CPU: {cpu_percent:.0f}%")

            # Color code CPU
            if cpu_percent < 50:
                self._cpu_indicator.set_color("#A6E3A1")
            elif cpu_percent < 80:
                self._cpu_indicator.set_color("#FAB387")
            else:
                self._cpu_indicator.set_color("#F38BA8")

            # Memory
            mem = psutil.virtual_memory()
            self._memory_indicator.set_label(f"MEM: {mem.percent:.0f}%")

            if mem.percent < 50:
                self._memory_indicator.set_color("#A6E3A1")
            elif mem.percent < 80:
                self._memory_indicator.set_color("#FAB387")
            else:
                self._memory_indicator.set_color("#F38BA8")

            # GPU info (if available)
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split(", ")
                    if len(parts) >= 1:
                        gpu_util = float(parts[0])
                        self._gpu_indicator.set_label(f"GPU: {gpu_util:.0f}%")
                        if gpu_util < 50:
                            self._gpu_indicator.set_color("#A6E3A1")
                        elif gpu_util < 80:
                            self._gpu_indicator.set_color("#FAB387")
                        else:
                            self._gpu_indicator.set_color("#F38BA8")
                else:
                    self._gpu_indicator.set_label("GPU: N/A")
                    self._gpu_indicator.set_color("#6C7086")
            except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
                self._gpu_indicator.set_label("GPU: N/A")
                self._gpu_indicator.set_color("#6C7086")

        except ImportError:
            # psutil not available
            self._cpu_indicator.set_label("CPU: --")
            self._memory_indicator.set_label("MEM: --")
            self._gpu_indicator.set_label("GPU: --")
        except Exception as e:
            logger.debug("Status bar update error: %s", e)

    @Slot(bool)
    def set_connection_status(self, connected: bool) -> None:
        """Set the connection status indicator.

        Args:
            connected: True if connected to backend.
        """
        if connected:
            self._connection_indicator.set_label("Connected")
            self._connection_indicator.set_color("#A6E3A1")
            self._connection_indicator.setToolTip("Connected to backend")
        else:
            self._connection_indicator.set_label("Disconnected")
            self._connection_indicator.set_color("#F38BA8")
            self._connection_indicator.setToolTip("Not connected to backend")

    def set_connection_info(self, host: str, port: int) -> None:
        """Set the connection information display.

        Args:
            host: Backend hostname.
            port: Backend port.
        """
        self._backend_label.setText(f"Backend: {host}:{port}")
        self._backend_label.setToolTip(f"Connected to Ainos backend at {host}:{port}")

    def set_model_status(self, model_name: str, status: str) -> None:
        """Set the model status indicator.

        Args:
            model_name: Name of the loaded model.
            status: Status string ('loaded', 'loading', 'unloaded', 'error').
        """
        if status == "loaded":
            self._model_indicator.set_label(f"Model: {model_name}")
            self._model_indicator.set_color("#A6E3A1")
            self._model_indicator.setToolTip(f"Model {model_name} is loaded")
        elif status == "loading":
            self._model_indicator.set_label(f"Loading: {model_name}")
            self._model_indicator.set_color("#FAB387")
            self._model_indicator.setToolTip(f"Model {model_name} is loading")
        elif status == "error":
            self._model_indicator.set_label(f"Error: {model_name}")
            self._model_indicator.set_color("#F38BA8")
            self._model_indicator.setToolTip(f"Model {model_name} encountered an error")
        else:
            self._model_indicator.set_label("No model loaded")
            self._model_indicator.set_color("#6C7086")
            self._model_indicator.setToolTip("No model is currently loaded")

    @Slot(str)
    def set_message(self, message: str, timeout_ms: int = 5000) -> None:
        """Set the status bar message.

        Args:
            message: Message text to display.
            timeout_ms: Auto-clear timeout in milliseconds. 0 for persistent.
        """
        self._message_label.setText(message)
        if timeout_ms > 0:
            # Clear after timeout
            QTimer.singleShot(timeout_ms, lambda: self._clear_message(message))

    def _clear_message(self, message: str) -> None:
        """Clear the message if it hasn't been changed.

        Args:
            message: The message to clear (only clears if still current).
        """
        if self._message_label.text() == message:
            self._message_label.setText("Ready")

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the status bar.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        if theme_name == "light":
            self.setStyleSheet("""
                QStatusBar {
                    background-color: #F5F5F9;
                    border-top: 1px solid #E5E5EF;
                    padding: 2px 8px;
                    font-size: 9pt;
                }
                QStatusBar::item {
                    border: none;
                }
            """)
            self._message_label.setStyleSheet("font-size: 9pt; color: #555570; padding: 0 8px;")
            self._backend_label.setStyleSheet("font-size: 9pt; color: #8888A0; padding: 0 8px;")
        else:
            self.setStyleSheet("""
                QStatusBar {
                    background-color: #181825;
                    border-top: 1px solid #313244;
                    padding: 2px 8px;
                    font-size: 9pt;
                }
                QStatusBar::item {
                    border: none;
                }
            """)
            self._message_label.setStyleSheet("font-size: 9pt; color: #6C7086; padding: 0 8px;")
            self._backend_label.setStyleSheet("font-size: 9pt; color: #6C7086; padding: 0 8px;")