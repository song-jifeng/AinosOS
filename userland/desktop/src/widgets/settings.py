#!/usr/bin/env python3
"""Ainos Desktop - Settings Widget.

Provides application settings management with tabs for connection,
appearance, inference, and logging configuration.
"""

import logging
from typing import Any

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
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QSlider,
    QSizePolicy,
    QMessageBox,
    QFileDialog,
    QButtonGroup,
    QRadioButton,
)

logger = logging.getLogger(__name__)


class SettingsWidget(QWidget):
    """Application settings widget with categorized settings panels."""

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the settings widget.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app
        self._theme = "dark"

        self._setup_ui()

        # Load current settings
        self._load_settings()

        logger.info("Settings widget initialized")

    def _setup_ui(self) -> None:
        """Set up the settings UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()

        header_text = QLabel("Settings")
        header_text.setProperty("heading", True)
        header_layout.addWidget(header_text)

        header_layout.addStretch()

        # Reset button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._on_reset_defaults)
        header_layout.addWidget(reset_btn)

        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._on_save_settings)
        header_layout.addWidget(save_btn)

        main_layout.addLayout(header_layout)

        # Subtitle
        subtitle = QLabel("Configure application behavior and preferences")
        subtitle.setProperty("subheading", True)
        main_layout.addWidget(subtitle)

        # ===== Settings Tabs =====
        self._tab_widget = QTabWidget()

        # Connection tab
        self._connection_tab = self._create_connection_tab()
        self._tab_widget.addTab(self._connection_tab, "Connection")

        # Appearance tab
        self._appearance_tab = self._create_appearance_tab()
        self._tab_widget.addTab(self._appearance_tab, "Appearance")

        # Inference tab
        self._inference_tab = self._create_inference_tab()
        self._tab_widget.addTab(self._inference_tab, "Inference")

        # Monitoring tab
        self._monitor_tab = self._create_monitor_tab()
        self._tab_widget.addTab(self._monitor_tab, "Monitoring")

        # Logging tab
        self._logging_tab = self._create_logging_tab()
        self._tab_widget.addTab(self._logging_tab, "Logging")

        # About tab
        self._about_tab = self._create_about_tab()
        self._tab_widget.addTab(self._about_tab, "About")

        main_layout.addWidget(self._tab_widget, 1)

    def _create_connection_tab(self) -> QWidget:
        """Create the connection settings tab.

        Returns:
            QWidget with connection settings.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        # Backend Connection
        conn_group = QGroupBox("Backend Connection")
        conn_layout = QGridLayout(conn_group)
        conn_layout.setSpacing(12)

        conn_layout.addWidget(QLabel("Host:"), 0, 0)
        self._host_input = QLineEdit("127.0.0.1")
        self._host_input.setPlaceholderText("e.g., 127.0.0.1 or localhost")
        conn_layout.addWidget(self._host_input, 0, 1)

        conn_layout.addWidget(QLabel("Port:"), 1, 0)
        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        self._port_input.setValue(8765)
        conn_layout.addWidget(self._port_input, 1, 1)

        conn_layout.addWidget(QLabel("API Key:"), 2, 0)
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("Enter API key (optional)")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        conn_layout.addWidget(self._api_key_input, 2, 1)

        self._use_ssl_check = QCheckBox("Use SSL/TLS")
        conn_layout.addWidget(self._use_ssl_check, 3, 1)

        layout.addWidget(conn_group)

        # Timeout settings
        timeout_group = QGroupBox("Timeouts & Retries")
        timeout_layout = QGridLayout(timeout_group)
        timeout_layout.setSpacing(12)

        timeout_layout.addWidget(QLabel("Request Timeout (ms):"), 0, 0)
        self._timeout_input = QSpinBox()
        self._timeout_input.setRange(1000, 300000)
        self._timeout_input.setValue(30000)
        self._timeout_input.setSingleStep(1000)
        timeout_layout.addWidget(self._timeout_input, 0, 1)

        timeout_layout.addWidget(QLabel("Reconnect Interval (ms):"), 1, 0)
        self._reconnect_interval = QSpinBox()
        self._reconnect_interval.setRange(1000, 60000)
        self._reconnect_interval.setValue(5000)
        self._reconnect_interval.setSingleStep(1000)
        timeout_layout.addWidget(self._reconnect_interval, 1, 1)

        timeout_layout.addWidget(QLabel("Max Reconnect Attempts:"), 2, 0)
        self._max_reconnect = QSpinBox()
        self._max_reconnect.setRange(0, 100)
        self._max_reconnect.setValue(10)
        timeout_layout.addWidget(self._max_reconnect, 2, 1)

        timeout_layout.addWidget(QLabel("Heartbeat Interval (ms):"), 3, 0)
        self._heartbeat_interval = QSpinBox()
        self._heartbeat_interval.setRange(1000, 60000)
        self._heartbeat_interval.setValue(15000)
        self._heartbeat_interval.setSingleStep(1000)
        timeout_layout.addWidget(self._heartbeat_interval, 3, 1)

        layout.addWidget(timeout_group)

        # Test connection button
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._on_test_connection)
        layout.addWidget(test_btn)

        layout.addStretch()
        return tab

    def _create_appearance_tab(self) -> QWidget:
        """Create the appearance settings tab.

        Returns:
            QWidget with appearance settings.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        # Theme
        theme_group = QGroupBox("Theme")
        theme_layout = QVBoxLayout(theme_group)
        theme_layout.setSpacing(8)

        self._theme_group = QButtonGroup(self)
        dark_radio = QRadioButton("Dark Theme")
        dark_radio.setChecked(True)
        self._theme_group.addButton(dark_radio, 1)
        theme_layout.addWidget(dark_radio)

        light_radio = QRadioButton("Light Theme")
        self._theme_group.addButton(light_radio, 2)
        theme_layout.addWidget(light_radio)

        self._theme_group.buttonClicked.connect(self._on_theme_changed)

        layout.addWidget(theme_group)

        # Window
        window_group = QGroupBox("Window")
        window_layout = QGridLayout(window_group)
        window_layout.setSpacing(12)

        self._minimize_to_tray = QCheckBox("Minimize to system tray on close")
        self._minimize_to_tray.setChecked(True)
        window_layout.addWidget(self._minimize_to_tray, 0, 0, 1, 2)

        self._show_tray_icon = QCheckBox("Show system tray icon")
        self._show_tray_icon.setChecked(True)
        window_layout.addWidget(self._show_tray_icon, 1, 0, 1, 2)

        window_layout.addWidget(QLabel("Font Size:"), 2, 0)
        self._font_size = QSpinBox()
        self._font_size.setRange(8, 24)
        self._font_size.setValue(10)
        window_layout.addWidget(self._font_size, 2, 1)

        self._compact_mode = QCheckBox("Compact mode (reduced spacing)")
        window_layout.addWidget(self._compact_mode, 3, 0, 1, 2)

        layout.addWidget(window_group)

        # Language
        lang_group = QGroupBox("Language")
        lang_layout = QHBoxLayout(lang_group)

        lang_layout.addWidget(QLabel("Interface Language:"))
        self._language_combo = QComboBox()
        self._language_combo.addItems(["English", "简体中文", "繁體中文", "日本語", "한국어"])
        lang_layout.addWidget(self._language_combo)
        lang_layout.addStretch()

        layout.addWidget(lang_group)

        layout.addStretch()
        return tab

    def _create_inference_tab(self) -> QWidget:
        """Create the inference settings tab.

        Returns:
            QWidget with inference settings.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        # Default Generation Parameters
        gen_group = QGroupBox("Default Generation Parameters")
        gen_layout = QGridLayout(gen_group)
        gen_layout.setSpacing(12)

        gen_layout.addWidget(QLabel("Default Model:"), 0, 0)
        self._default_model = QComboBox()
        self._default_model.addItems(["", "Llama 3.1 8B", "Mistral 7B", "CodeLlama 7B"])
        self._default_model.setEditable(True)
        gen_layout.addWidget(self._default_model, 0, 1)

        gen_layout.addWidget(QLabel("Temperature:"), 1, 0)
        self._default_temp = QDoubleSpinBox()
        self._default_temp.setRange(0.0, 2.0)
        self._default_temp.setValue(0.7)
        self._default_temp.setSingleStep(0.1)
        gen_layout.addWidget(self._default_temp, 1, 1)

        gen_layout.addWidget(QLabel("Top P:"), 2, 0)
        self._default_top_p = QDoubleSpinBox()
        self._default_top_p.setRange(0.0, 1.0)
        self._default_top_p.setValue(0.9)
        self._default_top_p.setSingleStep(0.05)
        gen_layout.addWidget(self._default_top_p, 2, 1)

        gen_layout.addWidget(QLabel("Top K:"), 3, 0)
        self._default_top_k = QSpinBox()
        self._default_top_k.setRange(1, 200)
        self._default_top_k.setValue(40)
        gen_layout.addWidget(self._default_top_k, 3, 1)

        gen_layout.addWidget(QLabel("Max Tokens:"), 4, 0)
        self._default_max_tokens = QSpinBox()
        self._default_max_tokens.setRange(8, 65536)
        self._default_max_tokens.setValue(2048)
        self._default_max_tokens.setSingleStep(128)
        gen_layout.addWidget(self._default_max_tokens, 4, 1)

        self._default_stream = QCheckBox("Stream output by default")
        self._default_stream.setChecked(True)
        gen_layout.addWidget(self._default_stream, 5, 0, 1, 2)

        layout.addWidget(gen_group)

        layout.addStretch()
        return tab

    def _create_monitor_tab(self) -> QWidget:
        """Create the monitoring settings tab.

        Returns:
            QWidget with monitoring settings.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        # Update intervals
        interval_group = QGroupBox("Update Intervals")
        interval_layout = QGridLayout(interval_group)
        interval_layout.setSpacing(12)

        interval_layout.addWidget(QLabel("Dashboard Update (ms):"), 0, 0)
        self._dashboard_interval = QSpinBox()
        self._dashboard_interval.setRange(500, 60000)
        self._dashboard_interval.setValue(3000)
        self._dashboard_interval.setSingleStep(500)
        interval_layout.addWidget(self._dashboard_interval, 0, 1)

        interval_layout.addWidget(QLabel("Monitor Update (ms):"), 1, 0)
        self._monitor_interval = QSpinBox()
        self._monitor_interval.setRange(500, 60000)
        self._monitor_interval.setValue(2000)
        self._monitor_interval.setSingleStep(500)
        interval_layout.addWidget(self._monitor_interval, 1, 1)

        interval_layout.addWidget(QLabel("Charts Max Points:"), 2, 0)
        self._chart_points = QSpinBox()
        self._chart_points.setRange(50, 1000)
        self._chart_points.setValue(300)
        self._chart_points.setSingleStep(50)
        interval_layout.addWidget(self._chart_points, 2, 1)

        layout.addWidget(interval_group)

        # Display options
        display_group = QGroupBox("Display Options")
        display_layout = QVBoxLayout(display_group)
        display_layout.setSpacing(8)

        self._show_cpu = QCheckBox("Show CPU metrics")
        self._show_cpu.setChecked(True)
        display_layout.addWidget(self._show_cpu)

        self._show_memory = QCheckBox("Show memory metrics")
        self._show_memory.setChecked(True)
        display_layout.addWidget(self._show_memory)

        self._show_gpu = QCheckBox("Show GPU metrics")
        self._show_gpu.setChecked(True)
        display_layout.addWidget(self._show_gpu)

        self._show_disk = QCheckBox("Show disk metrics")
        self._show_disk.setChecked(True)
        display_layout.addWidget(self._show_disk)

        self._show_network = QCheckBox("Show network metrics")
        display_layout.addWidget(self._show_network)

        self._show_legend = QCheckBox("Show chart legend")
        self._show_legend.setChecked(True)
        display_layout.addWidget(self._show_legend)

        layout.addWidget(display_group)

        layout.addStretch()
        return tab

    def _create_logging_tab(self) -> QWidget:
        """Create the logging settings tab.

        Returns:
            QWidget with logging settings.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        # Log level
        level_group = QGroupBox("Log Level")
        level_layout = QHBoxLayout(level_group)

        level_layout.addWidget(QLabel("Log Level:"))
        self._log_level = QComboBox()
        self._log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self._log_level.setCurrentText("INFO")
        level_layout.addWidget(self._log_level)
        level_layout.addStretch()

        layout.addWidget(level_group)

        # Log file
        file_group = QGroupBox("Log File")
        file_layout = QGridLayout(file_group)
        file_layout.setSpacing(12)

        file_layout.addWidget(QLabel("Log File Path:"), 0, 0)
        file_path_layout = QHBoxLayout()
        self._log_file_path = QLineEdit()
        self._log_file_path.setPlaceholderText("Auto-generated if empty")
        file_path_layout.addWidget(self._log_file_path, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse_log_file)
        file_path_layout.addWidget(browse_btn)
        file_layout.addLayout(file_path_layout, 0, 1)

        file_layout.addWidget(QLabel("Max File Size (MB):"), 1, 0)
        self._log_max_size = QSpinBox()
        self._log_max_size.setRange(1, 1000)
        self._log_max_size.setValue(100)
        file_layout.addWidget(self._log_max_size, 1, 1)

        file_layout.addWidget(QLabel("Backup Count:"), 2, 0)
        self._log_backup_count = QSpinBox()
        self._log_backup_count.setRange(0, 100)
        self._log_backup_count.setValue(5)
        file_layout.addWidget(self._log_backup_count, 2, 1)

        layout.addWidget(file_group)

        # Log viewer settings
        viewer_group = QGroupBox("Log Viewer")
        viewer_layout = QGridLayout(viewer_group)
        viewer_layout.setSpacing(12)

        viewer_layout.addWidget(QLabel("Max Lines:"), 0, 0)
        self._log_max_lines = QSpinBox()
        self._log_max_lines.setRange(100, 100000)
        self._log_max_lines.setValue(10000)
        self._log_max_lines.setSingleStep(1000)
        viewer_layout.addWidget(self._log_max_lines, 0, 1)

        self._log_auto_scroll = QCheckBox("Auto-scroll to new entries")
        self._log_auto_scroll.setChecked(True)
        viewer_layout.addWidget(self._log_auto_scroll, 1, 0, 1, 2)

        self._log_show_timestamps = QCheckBox("Show timestamps")
        self._log_show_timestamps.setChecked(True)
        viewer_layout.addWidget(self._log_show_timestamps, 2, 0, 1, 2)

        self._log_wrap_lines = QCheckBox("Wrap long lines")
        viewer_layout.addWidget(self._log_wrap_lines, 3, 0, 1, 2)

        layout.addWidget(viewer_group)

        layout.addStretch()
        return tab

    def _create_about_tab(self) -> QWidget:
        """Create the about tab.

        Returns:
            QWidget with application information.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # App info
        info_frame = QFrame()
        info_frame.setObjectName("metricCard")
        info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        info_frame.setMaximumWidth(500)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(12)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        app_name = QLabel("Ainos Desktop")
        app_name.setStyleSheet("font-size: 24pt; font-weight: bold; color: #89B4FA;")
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(app_name)

        version = QLabel("Version 0.1.0")
        version.setStyleSheet("font-size: 14pt; color: #A0A8C0;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(version)

        info_layout.addSpacing(20)

        description = QLabel(
            "A cross-platform desktop GUI for the Ainos AI backend.\n"
            "Manage models, run inference, monitor system performance,\n"
            "and browse context history - all in one place."
        )
        description.setWordWrap(True)
        description.setStyleSheet("font-size: 11pt; color: #A0A8C0; line-height: 1.5;")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(description)

        info_layout.addSpacing(20)

        # Tech stack
        tech_label = QLabel(
            "Built with: Python 3, PySide6, pyqtgraph, psutil\n"
            "License: MIT"
        )
        tech_label.setStyleSheet("font-size: 10pt; color: #6C7086;")
        tech_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(tech_label)

        info_layout.addSpacing(20)

        copyright_label = QLabel("Copyright (c) 2024 Ainos Team. All rights reserved.")
        copyright_label.setStyleSheet("font-size: 9pt; color: #585B70;")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(copyright_label)

        # Qt info
        qt_info = QLabel(f"Qt Version: {Qt.qVersion()}")
        qt_info.setStyleSheet("font-size: 9pt; color: #585B70;")
        qt_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(qt_info)

        layout.addWidget(info_frame, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        return tab

    def _load_settings(self) -> None:
        """Load current settings from config manager."""
        config = self._app.config

        # Connection
        conn = config.get("connection", {})
        self._host_input.setText(conn.get("host", "127.0.0.1"))
        self._port_input.setValue(conn.get("port", 8765))
        self._api_key_input.setText(conn.get("api_key", ""))
        self._use_ssl_check.setChecked(conn.get("use_ssl", False))
        self._timeout_input.setValue(conn.get("timeout_ms", 30000))
        self._reconnect_interval.setValue(conn.get("reconnect_interval_ms", 5000))
        self._max_reconnect.setValue(conn.get("max_reconnect_attempts", 10))
        self._heartbeat_interval.setValue(conn.get("heartbeat_interval_ms", 15000))

        # Appearance
        theme = config.get("theme", "dark")
        if theme == "light":
            self._theme_group.button(2).setChecked(True)
        else:
            self._theme_group.button(1).setChecked(True)

        self._minimize_to_tray.setChecked(config.get("window.minimize_on_close", True))
        self._show_tray_icon.setChecked(config.get("tray.enabled", True))
        self._font_size.setValue(config.get("ui.font_size", 10))
        self._compact_mode.setChecked(config.get("ui.compact_mode", False))

        # Inference
        inf = config.get("inference", {})
        self._default_temp.setValue(inf.get("temperature", 0.7))
        self._default_top_p.setValue(inf.get("top_p", 0.9))
        self._default_top_k.setValue(inf.get("top_k", 40))
        self._default_max_tokens.setValue(inf.get("max_tokens", 2048))
        self._default_stream.setChecked(inf.get("stream", True))

        # Monitoring
        mon = config.get("monitor", {})
        self._monitor_interval.setValue(mon.get("update_interval_ms", 2000))
        self._show_cpu.setChecked(mon.get("show_cpu", True))
        self._show_memory.setChecked(mon.get("show_memory", True))
        self._show_gpu.setChecked(mon.get("show_gpu", True))
        self._show_disk.setChecked(mon.get("show_disk", True))
        self._show_network.setChecked(mon.get("show_network", False))

        dash = config.get("dashboard", {})
        self._dashboard_interval.setValue(dash.get("update_interval_ms", 3000))
        self._chart_points.setValue(dash.get("max_data_points", 300))
        self._show_legend.setChecked(dash.get("show_legend", True))

        # Logging
        log = config.get("logging", {})
        self._log_level.setCurrentText(log.get("level", "INFO"))
        self._log_file_path.setText(log.get("file", ""))
        self._log_max_size.setValue(log.get("max_size_mb", 100))
        self._log_backup_count.setValue(log.get("backup_count", 5))

        lv = config.get("log_viewer", {})
        self._log_max_lines.setValue(lv.get("max_lines", 10000))
        self._log_auto_scroll.setChecked(lv.get("auto_scroll", True))
        self._log_show_timestamps.setChecked(lv.get("show_timestamps", True))
        self._log_wrap_lines.setChecked(lv.get("wrap_lines", False))

    @Slot()
    def _on_save_settings(self) -> None:
        """Save all settings to config manager."""
        config = self._app.config

        # Connection
        config.set("connection.host", self._host_input.text())
        config.set("connection.port", self._port_input.value())
        config.set("connection.api_key", self._api_key_input.text())
        config.set("connection.use_ssl", self._use_ssl_check.isChecked())
        config.set("connection.timeout_ms", self._timeout_input.value())
        config.set("connection.reconnect_interval_ms", self._reconnect_interval.value())
        config.set("connection.max_reconnect_attempts", self._max_reconnect.value())
        config.set("connection.heartbeat_interval_ms", self._heartbeat_interval.value())

        # Appearance
        theme_id = self._theme_group.checkedId()
        theme = "light" if theme_id == 2 else "dark"
        config.set("theme", theme)
        config.set("window.minimize_on_close", self._minimize_to_tray.isChecked())
        config.set("tray.enabled", self._show_tray_icon.isChecked())
        config.set("ui.font_size", self._font_size.value())
        config.set("ui.compact_mode", self._compact_mode.isChecked())

        # Inference
        config.set("inference.temperature", self._default_temp.value())
        config.set("inference.top_p", self._default_top_p.value())
        config.set("inference.top_k", self._default_top_k.value())
        config.set("inference.max_tokens", self._default_max_tokens.value())
        config.set("inference.stream", self._default_stream.isChecked())

        # Monitoring
        config.set("monitor.update_interval_ms", self._monitor_interval.value())
        config.set("monitor.show_cpu", self._show_cpu.isChecked())
        config.set("monitor.show_memory", self._show_memory.isChecked())
        config.set("monitor.show_gpu", self._show_gpu.isChecked())
        config.set("monitor.show_disk", self._show_disk.isChecked())
        config.set("monitor.show_network", self._show_network.isChecked())

        config.set("dashboard.update_interval_ms", self._dashboard_interval.value())
        config.set("dashboard.max_data_points", self._chart_points.value())
        config.set("dashboard.show_legend", self._show_legend.isChecked())

        # Logging
        config.set("logging.level", self._log_level.currentText())
        config.set("logging.file", self._log_file_path.text())
        config.set("logging.max_size_mb", self._log_max_size.value())
        config.set("logging.backup_count", self._log_backup_count.value())

        config.set("log_viewer.max_lines", self._log_max_lines.value())
        config.set("log_viewer.auto_scroll", self._log_auto_scroll.isChecked())
        config.set("log_viewer.show_timestamps", self._log_show_timestamps.isChecked())
        config.set("log_viewer.wrap_lines", self._log_wrap_lines.isChecked())

        # Save to file
        config.save()

        # Apply theme immediately
        if theme != self._app.current_theme:
            self._app.apply_theme(theme)

        self._app.show_info_dialog("Settings", "Settings saved successfully.")

    @Slot()
    def _on_reset_defaults(self) -> None:
        """Reset all settings to defaults."""
        confirmed = self._app.show_confirm_dialog(
            "Reset Settings",
            "Are you sure you want to reset all settings to defaults?",
            "Reset",
            "Cancel",
        )
        if confirmed:
            self._app.config.reset()
            self._load_settings()
            self._app.show_info_dialog("Settings", "Settings reset to defaults.")

    @Slot()
    def _on_test_connection(self) -> None:
        """Test the backend connection."""
        host = self._host_input.text()
        port = self._port_input.value()

        self._app.show_info_dialog(
            "Test Connection",
            f"Connection test to {host}:{port} would be performed here.\n\n"
            f"This requires the Ainos backend to be running."
        )

    @Slot()
    def _on_browse_log_file(self) -> None:
        """Browse for a log file path."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Select Log File", "", "Log Files (*.log);;All Files (*)"
        )
        if file_path:
            self._log_file_path.setText(file_path)

    @Slot(object)
    def _on_theme_changed(self, button) -> None:
        """Handle theme change from radio buttons.

        Args:
            button: The clicked radio button.
        """
        theme_id = self._theme_group.id(button)
        theme = "light" if theme_id == 2 else "dark"
        self._app.apply_theme(theme)

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the settings widget.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name