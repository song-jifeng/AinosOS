#!/usr/bin/env python3
"""Ainos Desktop - Settings Dialog.

Provides a dialog for quick access to commonly used settings
without needing to navigate to the full Settings tab.
"""

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QTabWidget,
    QLineEdit,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QSizePolicy,
    QDialogButtonBox,
    QButtonGroup,
    QRadioButton,
)

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Quick settings dialog for common configuration options."""

    def __init__(self, app: Any, parent: Any | None = None):
        """Initialize the settings dialog.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app

        self.setWindowTitle("Settings")
        self.setMinimumSize(500, 400)
        self.setModal(True)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        header_label = QLabel("Settings")
        header_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #CDD6F4;")
        layout.addWidget(header_label)

        # Tab widget
        tab_widget = QTabWidget()

        # General tab
        general_tab = self._create_general_tab()
        tab_widget.addTab(general_tab, "General")

        # Connection tab
        conn_tab = self._create_connection_tab()
        tab_widget.addTab(conn_tab, "Connection")

        # Inference tab
        inf_tab = self._create_inference_tab()
        tab_widget.addTab(inf_tab, "Inference")

        layout.addWidget(tab_widget, 1)

        # Button box
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def _create_general_tab(self) -> QWidget:
        """Create the general settings tab.

        Returns:
            QWidget with general settings.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        # Theme
        theme_group = QGroupBox("Appearance")
        theme_layout = QVBoxLayout(theme_group)

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

        # Language
        lang_group = QGroupBox("Language")
        lang_layout = QHBoxLayout(lang_group)
        lang_layout.addWidget(QLabel("Interface Language:"))
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["English"])
        lang_layout.addWidget(self._lang_combo)
        lang_layout.addStretch()
        layout.addWidget(lang_group)

        # Window
        window_group = QGroupBox("Window Behavior")
        window_layout = QVBoxLayout(window_group)
        self._minimize_tray = QCheckBox("Minimize to system tray on close")
        window_layout.addWidget(self._minimize_tray)
        self._show_tray = QCheckBox("Show system tray icon")
        window_layout.addWidget(self._show_tray)
        layout.addWidget(window_group)

        layout.addStretch()
        return tab

    def _create_connection_tab(self) -> QWidget:
        """Create the connection settings tab.

        Returns:
            QWidget with connection settings.
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(16)

        conn_group = QGroupBox("Backend Connection")
        conn_layout = QGridLayout(conn_group)
        conn_layout.setSpacing(12)

        conn_layout.addWidget(QLabel("Host:"), 0, 0)
        self._host_input = QLineEdit()
        conn_layout.addWidget(self._host_input, 0, 1)

        conn_layout.addWidget(QLabel("Port:"), 1, 0)
        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        conn_layout.addWidget(self._port_input, 1, 1)

        self._ssl_check = QCheckBox("Use SSL/TLS")
        conn_layout.addWidget(self._ssl_check, 2, 0, 1, 2)

        layout.addWidget(conn_group)

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

        inf_group = QGroupBox("Default Generation Parameters")
        inf_layout = QGridLayout(inf_group)
        inf_layout.setSpacing(12)

        inf_layout.addWidget(QLabel("Temperature:"), 0, 0)
        self._temp_input = QSpinBox()
        self._temp_input.setRange(0, 200)
        self._temp_input.setValue(70)
        self._temp_input.setSuffix(" (0.01x)")
        inf_layout.addWidget(self._temp_input, 0, 1)

        inf_layout.addWidget(QLabel("Max Tokens:"), 1, 0)
        self._max_tokens_input = QSpinBox()
        self._max_tokens_input.setRange(8, 65536)
        self._max_tokens_input.setValue(2048)
        self._max_tokens_input.setSingleStep(128)
        inf_layout.addWidget(self._max_tokens_input, 1, 1)

        self._stream_check = QCheckBox("Stream output by default")
        self._stream_check.setChecked(True)
        inf_layout.addWidget(self._stream_check, 2, 0, 1, 2)

        layout.addWidget(inf_group)

        layout.addStretch()
        return tab

    def _load_settings(self) -> None:
        """Load current settings from config."""
        config = self._app.config

        # General
        theme = config.get("theme", "dark")
        if theme == "light":
            self._theme_group.button(2).setChecked(True)
        else:
            self._theme_group.button(1).setChecked(True)

        self._minimize_tray.setChecked(config.get("window.minimize_on_close", True))
        self._show_tray.setChecked(config.get("tray.enabled", True))

        # Connection
        conn = config.get("connection", {})
        self._host_input.setText(conn.get("host", "127.0.0.1"))
        self._port_input.setValue(conn.get("port", 8765))
        self._ssl_check.setChecked(conn.get("use_ssl", False))

        # Inference
        inf = config.get("inference", {})
        temp = int(inf.get("temperature", 0.7) * 100)
        self._temp_input.setValue(temp)
        self._max_tokens_input.setValue(inf.get("max_tokens", 2048))
        self._stream_check.setChecked(inf.get("stream", True))

    @Slot()
    def _on_save(self) -> None:
        """Save settings and close dialog."""
        config = self._app.config

        # General
        theme_id = self._theme_group.checkedId()
        theme = "light" if theme_id == 2 else "dark"
        config.set("theme", theme)
        config.set("window.minimize_on_close", self._minimize_tray.isChecked())
        config.set("tray.enabled", self._show_tray.isChecked())

        # Connection
        config.set("connection.host", self._host_input.text())
        config.set("connection.port", self._port_input.value())
        config.set("connection.use_ssl", self._ssl_check.isChecked())

        # Inference
        temp = self._temp_input.value() / 100.0
        config.set("inference.temperature", temp)
        config.set("inference.max_tokens", self._max_tokens_input.value())
        config.set("inference.stream", self._stream_check.isChecked())

        config.save()

        # Apply theme
        if theme != self._app.current_theme:
            self._app.apply_theme(theme)

        self.accept()

    @Slot(object)
    def _on_theme_changed(self, button) -> None:
        """Handle theme change from radio buttons.

        Args:
            button: The clicked radio button.
        """
        theme_id = self._theme_group.id(button)
        theme = "light" if theme_id == 2 else "dark"
        self._app.apply_theme(theme)