#!/usr/bin/env python3
"""Ainos Desktop - Log Viewer Widget.

Provides real-time log viewing with filtering, search, and
configurable display options. Receives log entries via Qt signals
from the logging system.
"""

import logging
from typing import Any
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize
from PySide6.QtGui import QColor, QFont, QTextCursor, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QPlainTextEdit,
    QTextEdit,
    QComboBox,
    QLineEdit,
    QCheckBox,
    QGroupBox,
    QSplitter,
    QSizePolicy,
    QMenu,
    QApplication,
    QFileDialog,
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
)

from utils.logger import get_log_emitter, LogLevel

logger = logging.getLogger(__name__)


class LogLevelFilter(QComboBox):
    """Combo box for filtering log levels."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize the log level filter.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.addItems(["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.setCurrentText("ALL")
        self.setFixedWidth(120)


class LogEntryWidget(QFrame):
    """Widget for displaying a single log entry."""

    LEVEL_COLORS = {
        "DEBUG": ("#00BCD4", "#1A3A4A"),
        "INFO": ("#4CAF50", "#1A3C2A"),
        "WARNING": ("#FF9800", "#3C2A1A"),
        "ERROR": ("#F44336", "#3C1A1A"),
        "CRITICAL": ("#D32F2F", "#4A1A1A"),
    }

    def __init__(
        self,
        timestamp: str,
        level: str,
        logger_name: str,
        message: str,
        parent: QWidget | None = None,
    ):
        """Initialize the log entry widget.

        Args:
            timestamp: Log entry timestamp.
            level: Log level.
            logger_name: Logger name.
            message: Log message content.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._timestamp = timestamp
        self._level = level
        self._logger_name = logger_name
        self._message = message

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        colors = self.LEVEL_COLORS.get(level, ("#FFFFFF", "#1E1E2E"))

        self.setStyleSheet(f"""
            LogEntryWidget {{
                background-color: {colors[1]};
                border: none;
                border-bottom: 1px solid #313244;
                border-radius: 0;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        # Level badge
        level_label = QLabel(level)
        level_label.setFixedWidth(70)
        level_label.setStyleSheet(
            f"font-size: 8pt; font-weight: bold; color: {colors[0]}; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(level_label)

        # Timestamp
        time_label = QLabel(timestamp)
        time_label.setFixedWidth(160)
        time_label.setStyleSheet("font-size: 8pt; color: #6C7086; background: transparent; border: none;")
        layout.addWidget(time_label)

        # Logger name
        name_label = QLabel(logger_name)
        name_label.setFixedWidth(180)
        name_label.setStyleSheet("font-size: 8pt; color: #585B70; background: transparent; border: none;")
        layout.addWidget(name_label)

        # Message
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(
            f"font-size: 9pt; color: #CDD6F4; background: transparent; border: none;"
        )
        msg_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(msg_label, 1)


class LogViewerWidget(QWidget):
    """Real-time log viewer widget with filtering and search capabilities."""

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the log viewer widget.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app
        self._entries: list[logging.LogRecord] = []
        self._displayed_entries: list[LogEntryWidget] = []
        self._max_lines = app.config.get("log_viewer.max_lines", 10000)
        self._auto_scroll = app.config.get("log_viewer.auto_scroll", True)
        self._paused = False
        self._theme = "dark"

        self._setup_ui()

        # Connect to the global log emitter
        emitter = get_log_emitter()
        emitter.log_received.connect(self._on_log_received)

        # Batch update timer
        self._batch_timer = QTimer(self)
        self._batch_timer.timeout.connect(self._flush_batch)
        self._batch_timer.start(200)  # 200ms batch interval

        # Buffer for incoming log entries
        self._log_buffer: list[logging.LogRecord] = []

        logger.info("Log viewer widget initialized")

    def _setup_ui(self) -> None:
        """Set up the log viewer UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()

        header_text = QLabel("Log Viewer")
        header_text.setProperty("heading", True)
        header_layout.addWidget(header_text)

        header_layout.addStretch()

        # Filter controls
        self._level_filter = LogLevelFilter()
        self._level_filter.currentTextChanged.connect(self._apply_filter)
        header_layout.addWidget(self._level_filter)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search logs...")
        self._search_input.setFixedWidth(250)
        self._search_input.textChanged.connect(self._apply_filter)
        header_layout.addWidget(self._search_input)

        # Pause button
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.clicked.connect(self._toggle_pause)
        header_layout.addWidget(self._pause_btn)

        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_logs)
        header_layout.addWidget(clear_btn)

        # Export button
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_logs)
        header_layout.addWidget(export_btn)

        main_layout.addLayout(header_layout)

        # ===== Log Display Area =====
        self._log_area = QWidget()
        self._log_layout = QVBoxLayout(self._log_area)
        self._log_layout.setContentsMargins(0, 0, 0, 0)
        self._log_layout.setSpacing(0)
        self._log_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Scroll area for logs
        self._scroll_area = QFrame()
        self._scroll_area.setFrameShape(QFrame.Shape.StyledPanel)
        self._scroll_area.setStyleSheet("""
            QFrame {
                background-color: #1E1E2E;
                border: 1px solid #313244;
                border-radius: 6px;
            }
        """)

        scroll_layout = QVBoxLayout(self._scroll_area)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)

        self._scroll_content = QScrollArea()
        self._scroll_content.setWidgetResizable(True)
        self._scroll_content.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_content.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content.setWidget(self._log_area)

        scroll_layout.addWidget(self._scroll_content)

        main_layout.addWidget(self._scroll_area, 1)

        # ===== Status Bar =====
        status_layout = QHBoxLayout()

        self._entry_count_label = QLabel("0 entries")
        self._entry_count_label.setStyleSheet("font-size: 9pt; color: #6C7086;")
        status_layout.addWidget(self._entry_count_label)

        status_layout.addStretch()

        self._status_label = QLabel("Live")
        self._status_label.setStyleSheet("font-size: 9pt; color: #A6E3A1;")
        status_layout.addWidget(self._status_label)

        main_layout.addLayout(status_layout)

    @Slot(object)
    def _on_log_received(self, record: logging.LogRecord) -> None:
        """Handle a log record received from the logging system.

        Args:
            record: The log record.
        """
        if self._paused:
            return

        # Add to buffer for batch processing
        self._log_buffer.append(record)

        # Trim buffer if too large
        if len(self._log_buffer) > 500:
            self._flush_batch()

        # Trim total entries
        if len(self._entries) > self._max_lines * 2:
            self._entries = self._entries[-self._max_lines:]

    @Slot()
    def _flush_batch(self) -> None:
        """Flush buffered log entries to the display."""
        if not self._log_buffer:
            return

        records = self._log_buffer.copy()
        self._log_buffer.clear()

        # Add to entry list
        self._entries.extend(records)

        # Check if auto-scroll was at bottom
        scrollbar = self._scroll_content.verticalScrollBar()
        was_at_bottom = scrollbar and scrollbar.value() >= scrollbar.maximum() - 20

        # Add new entries that pass the filter
        for record in records:
            if self._entry_passes_filter(record):
                entry_widget = self._create_entry_widget(record)
                self._log_layout.addWidget(entry_widget)
                self._displayed_entries.append(entry_widget)

        # Trim displayed entries
        if len(self._displayed_entries) > self._max_lines:
            for i in range(len(self._displayed_entries) - self._max_lines):
                widget = self._displayed_entries.pop(0)
                widget.deleteLater()

        # Update count
        self._entry_count_label.setText(
            f"{len(self._entries)} entries ({len(self._displayed_entries)} shown)"
        )

        # Auto-scroll
        if was_at_bottom and self._auto_scroll:
            QTimer.singleShot(50, self._scroll_to_bottom)

    def _entry_passes_filter(self, record: logging.LogRecord) -> bool:
        """Check if a log entry passes the current filter.

        Args:
            record: The log record to check.

        Returns:
            True if the entry should be displayed.
        """
        # Level filter
        level_filter = self._level_filter.currentText()
        if level_filter != "ALL":
            record_level = LogLevel.from_string(record.levelname).value
            filter_level = LogLevel.from_string(level_filter).value
            if record_level < filter_level:
                return False

        # Search filter
        search_text = self._search_input.text().lower()
        if search_text:
            message = record.getMessage().lower()
            if search_text not in message:
                return False

        return True

    def _create_entry_widget(self, record: logging.LogRecord) -> LogEntryWidget:
        """Create a log entry widget from a record.

        Args:
            record: The log record.

        Returns:
            LogEntryWidget instance.
        """
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        message = record.getMessage()
        logger_name = record.name

        return LogEntryWidget(
            timestamp=timestamp,
            level=record.levelname,
            logger_name=logger_name,
            message=message,
        )

    @Slot()
    def _apply_filter(self) -> None:
        """Re-apply the current filter to all entries."""
        # Clear displayed entries
        for widget in self._displayed_entries:
            widget.deleteLater()
        self._displayed_entries.clear()

        # Re-add entries that pass the filter
        for record in self._entries:
            if self._entry_passes_filter(record):
                entry_widget = self._create_entry_widget(record)
                self._log_layout.addWidget(entry_widget)
                self._displayed_entries.append(entry_widget)

        # Update count
        self._entry_count_label.setText(
            f"{len(self._entries)} entries ({len(self._displayed_entries)} shown)"
        )

        # Scroll to bottom
        if self._auto_scroll:
            QTimer.singleShot(50, self._scroll_to_bottom)

    @Slot()
    def _toggle_pause(self) -> None:
        """Toggle pause/resume of log capture."""
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.setText("Resume")
            self._status_label.setText("Paused")
            self._status_label.setStyleSheet("font-size: 9pt; color: #FAB387;")
        else:
            self._pause_btn.setText("Pause")
            self._status_label.setText("Live")
            self._status_label.setStyleSheet("font-size: 9pt; color: #A6E3A1;")
            # Flush buffered entries
            self._flush_batch()

    @Slot()
    def _clear_logs(self) -> None:
        """Clear all log entries."""
        self._entries.clear()
        for widget in self._displayed_entries:
            widget.deleteLater()
        self._displayed_entries.clear()
        self._entry_count_label.setText("0 entries")

    @Slot()
    def _export_logs(self) -> None:
        """Export log entries to a file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Logs", f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            "Log Files (*.log);;Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                for record in self._entries:
                    timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
                    message = record.getMessage()
                    f.write(f"{timestamp} [{record.levelname}] {record.name}: {message}\n")

            self._app.show_info_dialog(
                "Export Complete",
                f"Exported {len(self._entries)} log entries to:\n{file_path}"
            )
        except (IOError, OSError) as e:
            self._app.show_error_dialog("Export Failed", str(e))

    def _scroll_to_bottom(self) -> None:
        """Scroll the log view to the bottom."""
        scrollbar = self._scroll_content.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the log viewer.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name

    def cleanup(self) -> None:
        """Cleanup resources."""
        self._batch_timer.stop()
        # Disconnect signal
        emitter = get_log_emitter()
        try:
            emitter.log_received.disconnect(self._on_log_received)
        except (TypeError, RuntimeError):
            pass