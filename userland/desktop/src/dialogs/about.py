#!/usr/bin/env python3
"""Ainos Desktop - About Dialog.

Provides information about the application, version, and credits.
"""

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QTabWidget,
    QTextEdit,
    QSizePolicy,
    QApplication,
)

logger = logging.getLogger(__name__)


class AboutDialog(QDialog):
    """About dialog displaying application information."""

    def __init__(self, parent: Any | None = None):
        """Initialize the about dialog.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("About Ainos Desktop")
        self.setFixedSize(520, 480)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # App icon placeholder
        icon_label = QLabel("🧠")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_label)

        # App name
        name_label = QLabel("Ainos Desktop")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-size: 22pt; font-weight: bold; color: #89B4FA;")
        layout.addWidget(name_label)

        # Version
        version_label = QLabel("Version 0.1.0")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("font-size: 12pt; color: #A0A8C0;")
        layout.addWidget(version_label)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #313244;")
        layout.addWidget(separator)

        # Description
        desc_label = QLabel(
            "A cross-platform desktop GUI for the Ainos AI backend.\n\n"
            "Manage AI models, run inference, monitor system performance,\n"
            "and browse context history - all in one desktop application."
        )
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 10pt; color: #CDD6F4; line-height: 1.5;")
        layout.addWidget(desc_label)

        # Credits
        credits_label = QLabel(
            "Built with:\n"
            "Python 3  |  PySide6  |  pyqtgraph  |  psutil\n\n"
            "Copyright (c) 2024 Ainos Team. All rights reserved.\n"
            "Licensed under the MIT License."
        )
        credits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits_label.setWordWrap(True)
        credits_label.setStyleSheet("font-size: 9pt; color: #6C7086;")
        layout.addWidget(credits_label)

        layout.addStretch()

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedSize(100, 36)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)