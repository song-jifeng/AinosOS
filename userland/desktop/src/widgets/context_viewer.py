#!/usr/bin/env python3
"""Ainos Desktop - Context Viewer Widget.

Provides browsing, searching, and management of inference context/history
with the ability to view, export, and delete context entries.
"""

import logging
import uuid
from typing import Any
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QSplitter,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QMenu,
    QHeaderView,
    QSizePolicy,
    QMessageBox,
    QAbstractItemView,
    QFileDialog,
    QApplication,
    QProgressBar,
)

from client.models import ContextEntry

logger = logging.getLogger(__name__)


class ContextListWidget(QTreeWidget):
    """Tree widget for displaying context sessions."""

    # Signals
    context_selected = Signal(str)  # context_id
    delete_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        """Initialize the context list.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the tree widget UI."""
        self.setHeaderLabels(["Context ID", "Messages", "Created", "Tokens"])
        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 160)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.setSortingEnabled(True)
        self.header().setStretchLastSection(True)

    def _show_context_menu(self, position) -> None:
        """Show the context menu.

        Args:
            position: Mouse position for the menu.
        """
        item = self.itemAt(position)
        if not item:
            return

        context_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not context_id:
            return

        menu = QMenu(self)
        view_action = menu.addAction("View Context")
        view_action.triggered.connect(lambda: self.context_selected.emit(context_id))

        export_action = menu.addAction("Export...")
        export_action.triggered.connect(lambda: self._export_context(context_id))

        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(lambda: self.delete_requested.emit(context_id))

        menu.exec(self.viewport().mapToGlobal(position))

    def _on_selection_changed(self) -> None:
        """Handle selection changes."""
        items = self.selectedItems()
        if items:
            context_id = items[0].data(0, Qt.ItemDataRole.UserRole)
            if context_id:
                self.context_selected.emit(context_id)

    def _export_context(self, context_id: str) -> None:
        """Export a context to a file.

        Args:
            context_id: ID of the context to export.
        """
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Context", f"context_{context_id[:8]}.json",
            "JSON Files (*.json);;Markdown Files (*.md);;Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            # In a real app, this would fetch and export the actual context
            logger.info("Export context %s to %s", context_id, file_path)

    def add_context(self, context_id: str, message_count: int = 0,
                    created_at: str = "", token_count: int = 0) -> None:
        """Add a context item to the list.

        Args:
            context_id: Context identifier.
            message_count: Number of messages in the context.
            created_at: Creation timestamp.
            token_count: Total token count.
        """
        item = QTreeWidgetItem(self)
        item.setText(0, context_id[:16] + "..." if len(context_id) > 16 else context_id)
        item.setText(1, str(message_count))
        item.setText(2, created_at)
        item.setText(3, str(token_count))
        item.setData(0, Qt.ItemDataRole.UserRole, context_id)
        item.setToolTip(0, f"Context ID: {context_id}")


class ContextEntryWidget(QFrame):
    """Widget for displaying a single context entry."""

    def __init__(
        self,
        entry: ContextEntry,
        parent: QWidget | None = None,
    ):
        """Initialize the context entry widget.

        Args:
            entry: The context entry to display.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._entry = entry
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("contextEntry")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the entry UI."""
        is_user = self._entry.role == "user"
        is_system = self._entry.role == "system"

        if is_user:
            bg_color = "#2A3A5C"
            border_color = "#3A4A6C"
            text_color = "#CDD6F4"
            role_display = "User"
        elif is_system:
            bg_color = "#2A3A2A"
            border_color = "#3A4A3A"
            text_color = "#A6E3A1"
            role_display = "System"
        else:
            bg_color = "#252540"
            border_color = "#353550"
            text_color = "#CDD6F4"
            role_display = "Assistant"

        self.setStyleSheet(f"""
            ContextEntryWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        role_label = QLabel(role_display)
        role_label.setStyleSheet(f"font-size: 9pt; font-weight: 600; color: {text_color};")
        header.addWidget(role_label)

        header.addStretch()

        if self._entry.token_count > 0:
            token_label = QLabel(f"{self._entry.token_count} tokens")
            token_label.setStyleSheet("font-size: 8pt; color: #6C7086;")
            header.addWidget(token_label)

        if self._entry.created_at:
            time_label = QLabel(self._entry.created_at[:19])
            time_label.setStyleSheet("font-size: 8pt; color: #6C7086;")
            header.addWidget(time_label)

        layout.addLayout(header)

        # Content
        content_label = QLabel(self._entry.content[:500] + ("..." if len(self._entry.content) > 500 else ""))
        content_label.setWordWrap(True)
        content_label.setStyleSheet(f"font-size: 10pt; color: {text_color}; background: transparent; border: none;")
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(content_label)


class ContextViewerWidget(QWidget):
    """Context viewer widget with browsing, search, and management."""

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the context viewer.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app
        self._contexts: dict[str, list[ContextEntry]] = {}
        self._theme = "dark"

        self._setup_ui()

        # Load demo data
        self._load_demo_data()

        # Auto-refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        interval = self._app.config.get("context_viewer.refresh_interval_ms", 10000)
        if self._app.config.get("context_viewer.auto_refresh", True):
            self._refresh_timer.start(interval)

        logger.info("Context viewer widget initialized")

    def _setup_ui(self) -> None:
        """Set up the context viewer UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()

        header_text = QLabel("Context Viewer")
        header_text.setProperty("heading", True)
        header_layout.addWidget(header_text)

        header_layout.addStretch()

        # Search
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search contexts...")
        self._search_input.setFixedWidth(300)
        self._search_input.textChanged.connect(self._filter_contexts)
        header_layout.addWidget(self._search_input)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("primary", True)
        refresh_btn.clicked.connect(self._load_demo_data)
        header_layout.addWidget(refresh_btn)

        # Clear all button
        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.clicked.connect(self._on_clear_all)
        header_layout.addWidget(clear_all_btn)

        main_layout.addLayout(header_layout)

        # ===== Main Splitter =====
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # Left: Context list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(8)

        list_label = QLabel("Context Sessions")
        list_label.setProperty("subheading", True)
        left_layout.addWidget(list_label)

        self._context_list = ContextListWidget()
        self._context_list.context_selected.connect(self._on_context_selected)
        self._context_list.delete_requested.connect(self._on_delete_context)
        left_layout.addWidget(self._context_list, 1)

        # Context count
        self._context_count_label = QLabel("0 contexts")
        self._context_count_label.setStyleSheet("font-size: 9pt; color: #6C7086;")
        left_layout.addWidget(self._context_count_label)

        splitter.addWidget(left_panel)

        # Right: Context detail
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(8)

        detail_label = QLabel("Context Details")
        detail_label.setProperty("subheading", True)
        right_layout.addWidget(detail_label)

        # Context metadata
        self._context_info_label = QLabel("Select a context from the list to view its contents")
        self._context_info_label.setStyleSheet("font-size: 10pt; color: #6C7086; padding: 8px;")
        self._context_info_label.setWordWrap(True)
        right_layout.addWidget(self._context_info_label)

        # Entries scroll area
        self._entries_scroll = QScrollArea()
        self._entries_scroll.setWidgetResizable(True)
        self._entries_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entries_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._entries_container = QWidget()
        self._entries_layout = QVBoxLayout(self._entries_container)
        self._entries_layout.setSpacing(8)
        self._entries_layout.addStretch()

        self._entries_scroll.setWidget(self._entries_container)
        right_layout.addWidget(self._entries_scroll, 1)

        # Export button
        export_layout = QHBoxLayout()
        self._export_btn = QPushButton("Export Context")
        self._export_btn.clicked.connect(self._on_export_context)
        self._export_btn.setEnabled(False)
        export_layout.addWidget(self._export_btn)

        self._delete_btn = QPushButton("Delete Context")
        self._delete_btn.setProperty("danger", True)
        self._delete_btn.clicked.connect(self._on_delete_selected)
        self._delete_btn.setEnabled(False)
        export_layout.addWidget(self._delete_btn)

        export_layout.addStretch()
        right_layout.addLayout(export_layout)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        main_layout.addWidget(splitter, 1)

    def _load_demo_data(self) -> None:
        """Load demo context data for display."""
        now = datetime.now()
        self._contexts = {}

        # Demo context 1
        ctx1_id = str(uuid.uuid4())
        self._contexts[ctx1_id] = [
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx1_id, role="user",
                content="Hello, can you help me write a Python function to calculate fibonacci numbers?",
                token_count=18, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx1_id, role="assistant",
                content="Certainly! Here's a Python function for fibonacci numbers using both recursive and iterative approaches:\n\n```python\ndef fibonacci_recursive(n):\n    if n <= 1:\n        return n\n    return fibonacci_recursive(n-1) + fibonacci_recursive(n-2)\n\ndef fibonacci_iterative(n):\n    if n <= 1:\n        return n\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b\n```\n\nThe iterative version is more efficient with O(n) time complexity and O(1) space.",
                token_count=98, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx1_id, role="user",
                content="Thanks! Can you also add memoization to the recursive version?",
                token_count=14, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
        ]

        # Demo context 2
        ctx2_id = str(uuid.uuid4())
        self._contexts[ctx2_id] = [
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx2_id, role="user",
                content="What is the capital of France?",
                token_count=8, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx2_id, role="assistant",
                content="The capital of France is Paris. It is one of the most famous cities in the world, known for its art, fashion, culture, and landmarks such as the Eiffel Tower, the Louvre Museum, and Notre-Dame Cathedral.",
                token_count=42, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
        ]

        # Demo context 3
        ctx3_id = str(uuid.uuid4())
        self._contexts[ctx3_id] = [
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx3_id, role="system",
                content="You are a helpful coding assistant. Always provide clear, well-documented code examples.",
                token_count=15, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx3_id, role="user",
                content="Write a quick sort algorithm in Python",
                token_count=10, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx3_id, role="assistant",
                content="Here's a quicksort implementation in Python:\n\n```python\ndef quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + middle + quicksort(right)\n```\n\nThis uses a simple list comprehension approach. For in-place sorting, you'd use a different implementation with indexes.",
                token_count=87, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
            ContextEntry(
                id=str(uuid.uuid4()), context_id=ctx3_id, role="user",
                content="Can you make it in-place?",
                token_count=7, created_at=now.strftime("%Y-%m-%d %H:%M:%S")
            ),
        ]

        # Populate the list
        self._populate_list()

    def _populate_list(self) -> None:
        """Populate the context list widget."""
        self._context_list.clear()

        for ctx_id, entries in self._contexts.items():
            message_count = len(entries)
            total_tokens = sum(e.token_count for e in entries)
            created = entries[0].created_at if entries else ""

            self._context_list.add_context(
                context_id=ctx_id,
                message_count=message_count,
                created_at=created,
                token_count=total_tokens,
            )

        self._context_count_label.setText(f"{len(self._contexts)} contexts")

    @Slot(str)
    def _on_context_selected(self, context_id: str) -> None:
        """Handle context selection.

        Args:
            context_id: ID of the selected context.
        """
        entries = self._contexts.get(context_id, [])
        self._display_entries(context_id, entries)

    def _display_entries(self, context_id: str, entries: list[ContextEntry]) -> None:
        """Display context entries in the detail panel.

        Args:
            context_id: Context identifier.
            entries: List of context entries to display.
        """
        # Clear existing entries
        while self._entries_layout.count() > 1:
            item = self._entries_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        # Update info
        total_tokens = sum(e.token_count for e in entries)
        self._context_info_label.setText(
            f"Context: {context_id[:16]}... | "
            f"{len(entries)} messages | "
            f"{total_tokens} total tokens"
        )

        # Add entries
        for entry in entries:
            entry_widget = ContextEntryWidget(entry)
            self._entries_layout.insertWidget(
                self._entries_layout.count() - 1, entry_widget
            )

        self._selected_context_id = context_id
        self._export_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)

    @Slot(str)
    def _on_delete_context(self, context_id: str) -> None:
        """Handle context deletion request.

        Args:
            context_id: ID of the context to delete.
        """
        confirmed = self._app.show_confirm_dialog(
            "Delete Context",
            "Are you sure you want to delete this context? This cannot be undone.",
            "Delete",
            "Cancel",
        )
        if confirmed:
            self._contexts.pop(context_id, None)
            self._populate_list()
            self._clear_detail_panel()

    @Slot()
    def _on_delete_selected(self) -> None:
        """Delete the currently selected context."""
        if hasattr(self, '_selected_context_id') and self._selected_context_id:
            self._on_delete_context(self._selected_context_id)

    @Slot()
    def _on_clear_all(self) -> None:
        """Clear all contexts after confirmation."""
        if not self._contexts:
            return

        confirmed = self._app.show_confirm_dialog(
            "Clear All Contexts",
            f"Are you sure you want to clear all {len(self._contexts)} contexts? This cannot be undone.",
            "Clear All",
            "Cancel",
        )
        if confirmed:
            self._contexts.clear()
            self._populate_list()
            self._clear_detail_panel()

    @Slot()
    def _on_export_context(self) -> None:
        """Export the currently selected context."""
        if hasattr(self, '_selected_context_id') and self._selected_context_id:
            self._context_list._export_context(self._selected_context_id)

    @Slot()
    def clear_all(self) -> None:
        """Public method to clear all contexts."""
        self._contexts.clear()
        self._populate_list()
        self._clear_detail_panel()

    def _clear_detail_panel(self) -> None:
        """Clear the detail panel."""
        while self._entries_layout.count() > 1:
            item = self._entries_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        self._context_info_label.setText("Select a context from the list to view its contents")
        self._selected_context_id = ""
        self._export_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

    @Slot(str)
    def _filter_contexts(self, text: str) -> None:
        """Filter the context list based on search text.

        Args:
            text: Search text.
        """
        # In a real app, this would filter the list
        # For now, we just re-populate (demo data doesn't change)
        self._populate_list()

    def _auto_refresh(self) -> None:
        """Auto-refresh context list."""
        pass

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the context viewer.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name

    def cleanup(self) -> None:
        """Cleanup resources."""
        self._refresh_timer.stop()