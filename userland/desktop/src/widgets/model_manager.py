#!/usr/bin/env python3
"""Ainos Desktop - Model Manager Widget.

Provides model management functionality including listing, loading,
unloading, and drag-and-drop model file loading.
"""

import os
import logging
from typing import Any
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize, QMimeData
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QColor, QFont, QIcon, QPixmap, QPainter
)
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
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QProgressBar,
    QMessageBox,
    QComboBox,
    QLineEdit,
    QAbstractItemView,
    QMenu,
    QInputDialog,
    QFileDialog,
)

from client.models import ModelInfo, ModelStatus
from dialogs.model_load import ModelLoadDialog

logger = logging.getLogger(__name__)


class ModelCard(QFrame):
    """A card widget displaying a single model's information."""

    # Signals
    load_clicked = Signal(str)
    unload_clicked = Signal(str)
    info_clicked = Signal(str)

    STATUS_COLORS = {
        "loaded": "#A6E3A1",
        "loading": "#FAB387",
        "unloaded": "#6C7086",
        "unloading": "#FAB387",
        "error": "#F38BA8",
        "not_found": "#585B70",
        "queued": "#89B4FA",
    }

    def __init__(self, model: ModelInfo, parent: QWidget | None = None):
        """Initialize the model card.

        Args:
            model: Model information to display.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._model = model
        self.setObjectName("modelCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(280, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAcceptDrops(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the card UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # Status indicator row
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)

        # Status dot
        status_color = self.STATUS_COLORS.get(
            self._model.status.value, "#6C7086"
        )
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(10, 10)
        self._status_dot.setStyleSheet(
            f"background-color: {status_color}; border-radius: 5px;"
        )
        status_layout.addWidget(self._status_dot)

        # Status text
        self._status_label = QLabel(self._model.status.value.capitalize())
        self._status_label.setStyleSheet(f"font-size: 9pt; color: {status_color};")
        status_layout.addWidget(self._status_label)

        status_layout.addStretch()

        # Model type badge
        type_label = QLabel(self._model.model_type.upper())
        type_label.setStyleSheet(
            "font-size: 8pt; color: #89B4FA; background-color: #1A3A5C; "
            "border-radius: 4px; padding: 2px 8px; font-weight: 600;"
        )
        status_layout.addWidget(type_label)

        layout.addLayout(status_layout)

        # Model name
        name_label = QLabel(self._model.name or self._model.id)
        name_label.setStyleSheet(
            "font-size: 14pt; font-weight: bold; color: #CDD6F4;"
        )
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # Description
        if self._model.description:
            desc_label = QLabel(self._model.description)
            desc_label.setStyleSheet("font-size: 9pt; color: #6C7086;")
            desc_label.setWordWrap(True)
            desc_label.setMaximumHeight(40)
            layout.addWidget(desc_label)

        # Model details
        details_layout = QHBoxLayout()
        details_layout.setSpacing(16)

        if self._model.size_bytes > 0:
            size_label = QLabel(f"Size: {self._model.formatted_size()}")
            size_label.setStyleSheet("font-size: 9pt; color: #A0A8C0;")
            details_layout.addWidget(size_label)

        if self._model.parameter_count > 0:
            param_label = QLabel(f"Params: {self._model.formatted_parameters()}")
            param_label.setStyleSheet("font-size: 9pt; color: #A0A8C0;")
            details_layout.addWidget(param_label)

        if self._model.quantization:
            quant_label = QLabel(f"Quant: {self._model.quantization}")
            quant_label.setStyleSheet("font-size: 9pt; color: #A0A8C0;")
            details_layout.addWidget(quant_label)

        details_layout.addStretch()
        layout.addLayout(details_layout)

        # Context length
        if self._model.context_length > 0:
            ctx_label = QLabel(f"Context: {self._model.context_length}")
            ctx_label.setStyleSheet("font-size: 9pt; color: #A0A8C0;")
            layout.addWidget(ctx_label)

        # Action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)
        buttons_layout.addStretch()

        if self._model.status == ModelStatus.UNLOADED or self._model.status == ModelStatus.ERROR:
            load_btn = QPushButton("Load")
            load_btn.setProperty("primary", True)
            load_btn.setFixedSize(90, 32)
            load_btn.clicked.connect(lambda: self.load_clicked.emit(self._model.id))
            buttons_layout.addWidget(load_btn)

        elif self._model.status == ModelStatus.LOADED:
            unload_btn = QPushButton("Unload")
            unload_btn.setProperty("danger", True)
            unload_btn.setFixedSize(90, 32)
            unload_btn.clicked.connect(lambda: self.unload_clicked.emit(self._model.id))
            buttons_layout.addWidget(unload_btn)

        info_btn = QPushButton("Details")
        info_btn.setFixedSize(90, 32)
        info_btn.clicked.connect(lambda: self.info_clicked.emit(self._model.id))
        buttons_layout.addWidget(info_btn)

        layout.addLayout(buttons_layout)

        # Error message
        if self._model.error_message:
            error_label = QLabel(f"Error: {self._model.error_message}")
            error_label.setStyleSheet("font-size: 9pt; color: #F38BA8;")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

    def update_model(self, model: ModelInfo) -> None:
        """Update the displayed model information.

        Args:
            model: Updated model information.
        """
        self._model = model
        status_color = self.STATUS_COLORS.get(
            self._model.status.value, "#6C7086"
        )
        self._status_dot.setStyleSheet(
            f"background-color: {status_color}; border-radius: 5px;"
        )
        self._status_label.setText(self._model.status.value.capitalize())
        self._status_label.setStyleSheet(f"font-size: 9pt; color: {status_color};")


class ModelManagerWidget(QWidget):
    """Model management widget with cards and drag-and-drop support."""

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the model manager.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app
        self._models: list[ModelInfo] = []
        self._model_cards: dict[str, ModelCard] = {}
        self._theme = "dark"

        self._setup_ui()
        self._setup_drag_drop()

        # Auto-refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        interval = self._app.config.get("model_manager.refresh_interval_ms", 30000)
        if self._app.config.get("model_manager.auto_refresh", True):
            self._refresh_timer.start(interval)

        logger.info("Model manager widget initialized")

    def _setup_ui(self) -> None:
        """Set up the model manager UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()

        header_text = QLabel("Model Manager")
        header_text.setProperty("heading", True)
        header_layout.addWidget(header_text)

        header_layout.addStretch()

        # Search
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search models...")
        self._search_input.setFixedWidth(250)
        self._search_input.textChanged.connect(self._filter_models)
        header_layout.addWidget(self._search_input)

        # Filter
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All Models", "Loaded", "Unloaded", "LLM", "Embedding", "Vision"])
        self._filter_combo.currentTextChanged.connect(self._filter_models)
        self._filter_combo.setFixedWidth(140)
        header_layout.addWidget(self._filter_combo)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("primary", True)
        refresh_btn.clicked.connect(self.refresh_models)
        header_layout.addWidget(refresh_btn)

        # Load from file button
        load_file_btn = QPushButton("Load from File")
        load_file_btn.clicked.connect(self._on_load_from_file)
        header_layout.addWidget(load_file_btn)

        main_layout.addLayout(header_layout)

        # Drop zone hint
        self._drop_hint = QFrame()
        self._drop_hint.setObjectName("dropZone")
        self._drop_hint.setFrameShape(QFrame.Shape.StyledPanel)
        self._drop_hint.setMinimumHeight(80)
        drop_layout = QVBoxLayout(self._drop_hint)
        drop_label = QLabel("Drop model files here to load them")
        drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_label.setStyleSheet("font-size: 11pt; color: #6C7086; padding: 20px;")
        drop_layout.addWidget(drop_label)
        main_layout.addWidget(self._drop_hint)

        # Model list area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._model_container = QWidget()
        self._model_grid = QGridLayout(self._model_container)
        self._model_grid.setSpacing(12)
        self._model_grid.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self._model_container)
        main_layout.addWidget(scroll_area, 1)

        # Status bar at bottom
        status_layout = QHBoxLayout()
        self._status_label = QLabel("No models loaded")
        self._status_label.setStyleSheet("font-size: 9pt; color: #6C7086;")
        status_layout.addWidget(self._status_label)
        status_layout.addStretch()
        self._model_count_label = QLabel("0 models")
        self._model_count_label.setStyleSheet("font-size: 9pt; color: #A0A8C0;")
        status_layout.addWidget(self._model_count_label)
        main_layout.addLayout(status_layout)

    def _setup_drag_drop(self) -> None:
        """Set up drag-and-drop support."""
        self.setAcceptDrops(True)
        self._drop_hint.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handle drag enter events.

        Args:
            event: The drag enter event.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_hint.setStyleSheet("""
                QFrame#dropZone {
                    border: 2px dashed #89B4FA;
                    background-color: #1A3A5C;
                    border-radius: 8px;
                }
            """)

    def dragLeaveEvent(self, event) -> None:
        """Handle drag leave events.

        Args:
            event: The drag leave event.
        """
        self._drop_hint.setStyleSheet("""
            QFrame#dropZone {
                border: 2px dashed #45475A;
                border-radius: 8px;
            }
        """)

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle drop events for model files.

        Args:
            event: The drop event.
        """
        self._drop_hint.setStyleSheet("""
            QFrame#dropZone {
                border: 2px dashed #45475A;
                border-radius: 8px;
            }
        """)

        files = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                filepath = url.toLocalFile()
                if os.path.isfile(filepath):
                    ext = os.path.splitext(filepath)[1].lower()
                    # Common model file extensions
                    if ext in ('.gguf', '.bin', '.pt', '.pth', '.safetensors',
                               '.onnx', '.ggml', '.h5', '.keras', '.tflite'):
                        files.append(filepath)

        if files:
            self._load_model_files(files)
        else:
            self._app.show_info_dialog(
                "Invalid Files",
                "No valid model files found. Supported formats: "
                ".gguf, .bin, .pt, .pth, .safetensors, .onnx, .ggml, .h5, .keras, .tflite"
            )

    @Slot()
    def refresh_models(self) -> None:
        """Refresh the model list from the backend."""
        self._status_label.setText("Refreshing model list...")

        # Try to get models from the client
        client = getattr(self._app, '_client', None)
        if client and hasattr(client, 'list_models'):
            # Async operation - would need to use QThread or asyncio
            # For now, use demo/placeholder data
            self._load_demo_models()
        else:
            self._load_demo_models()

    def _load_demo_models(self) -> None:
        """Load demo model data for display purposes."""
        from client.models import ModelInfo, ModelStatus

        demo_models = [
            ModelInfo(
                id="llama-3.1-8b",
                name="Llama 3.1 8B",
                version="3.1",
                model_type="llm",
                description="Meta's Llama 3.1 8B instruction-tuned language model",
                status=ModelStatus.LOADED,
                size_bytes=4_700_000_000,
                parameter_count=8_000_000_000,
                quantization="Q4_K_M",
                context_length=131072,
                supported_features=["chat", "completion", "streaming"],
            ),
            ModelInfo(
                id="codellama-7b",
                name="CodeLlama 7B",
                version="1.0",
                model_type="llm",
                description="Specialized code generation model from Meta",
                status=ModelStatus.UNLOADED,
                size_bytes=3_800_000_000,
                parameter_count=7_000_000_000,
                quantization="Q5_K_M",
                context_length=16384,
                supported_features=["chat", "completion", "infill"],
            ),
            ModelInfo(
                id="mistral-7b",
                name="Mistral 7B v0.3",
                version="0.3",
                model_type="llm",
                description="Mistral AI's efficient 7B parameter model",
                status=ModelStatus.UNLOADED,
                size_bytes=4_100_000_000,
                parameter_count=7_000_000_000,
                quantization="Q4_K_M",
                context_length=32768,
                supported_features=["chat", "completion", "streaming"],
            ),
            ModelInfo(
                id="nomic-embed-text-v1.5",
                name="Nomic Embed Text v1.5",
                version="1.5",
                model_type="embedding",
                description="Text embedding model for semantic search",
                status=ModelStatus.LOADED,
                size_bytes=137_000_000,
                parameter_count=137_000_000,
                quantization="f16",
                context_length=2048,
                supported_features=["embedding"],
            ),
            ModelInfo(
                id="llava-1.6-7b",
                name="LLaVA 1.6 7B",
                version="1.6",
                model_type="vision",
                description="Multimodal vision-language model",
                status=ModelStatus.UNLOADED,
                size_bytes=4_500_000_000,
                parameter_count=7_000_000_000,
                quantization="Q4_K_M",
                context_length=4096,
                supported_features=["chat", "vision"],
            ),
            ModelInfo(
                id="deepseek-coder-6.7b",
                name="DeepSeek Coder 6.7B",
                version="1.0",
                model_type="llm",
                description="DeepSeek's code-specialized language model",
                status=ModelStatus.ERROR,
                size_bytes=3_900_000_000,
                parameter_count=6_700_000_000,
                quantization="Q4_K_S",
                context_length=16384,
                supported_features=["chat", "completion"],
                error_message="Insufficient GPU memory (requires 8GB, available 6GB)",
            ),
        ]

        self._models = demo_models
        self._populate_models()

    def _populate_models(self) -> None:
        """Populate the model grid with cards."""
        # Clear existing cards
        for i in reversed(range(self._model_grid.count())):
            item = self._model_grid.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        self._model_cards.clear()

        # Get filter
        filter_text = self._search_input.text().lower()
        filter_category = self._filter_combo.currentText()

        filtered_models = []
        for model in self._models:
            # Apply search filter
            if filter_text and filter_text not in model.name.lower() and filter_text not in model.id.lower():
                continue

            # Apply category filter
            if filter_category == "Loaded" and model.status != ModelStatus.LOADED:
                continue
            elif filter_category == "Unloaded" and model.status != ModelStatus.UNLOADED:
                continue
            elif filter_category == "LLM" and model.model_type != "llm":
                continue
            elif filter_category == "Embedding" and model.model_type != "embedding":
                continue
            elif filter_category == "Vision" and model.model_type != "vision":
                continue

            filtered_models.append(model)

        # Add cards to grid
        row, col = 0, 0
        for model in filtered_models:
            card = ModelCard(model)
            card.load_clicked.connect(self._on_load_model)
            card.unload_clicked.connect(self._on_unload_model)
            card.info_clicked.connect(self._on_model_info)

            self._model_grid.addWidget(card, row, col)
            self._model_cards[model.id] = card

            col += 1
            if col >= 3:  # 3 columns
                col = 0
                row += 1

        # Update status
        self._status_label.setText(
            f"Showing {len(filtered_models)} of {len(self._models)} models"
        )
        self._model_count_label.setText(f"{len(self._models)} models")

    @Slot(str)
    def _filter_models(self, text: str | None = None) -> None:
        """Filter the model list based on search/filter criteria.

        Args:
            text: Search text (unused, read from widget).
        """
        self._populate_models()

    @Slot(str)
    def _on_load_model(self, model_id: str) -> None:
        """Handle load model action.

        Args:
            model_id: ID of the model to load.
        """
        model = next((m for m in self._models if m.id == model_id), None)
        if model:
            dialog = ModelLoadDialog(model, self._app, self)
            if dialog.exec():
                # Update model status
                model.status = ModelStatus.LOADING
                if model_id in self._model_cards:
                    self._model_cards[model_id].update_model(model)

                # Simulate loading (in real app, would call client.load_model)
                self._status_label.setText(f"Loading model: {model.name}...")

                # Update status bar
                if self._app.main_window:
                    status_bar = self._app.main_window.statusBar()
                    if hasattr(status_bar, 'set_model_status'):
                        status_bar.set_model_status(model.name, "loading")

                QTimer.singleShot(2000, lambda: self._on_model_loaded(model))

    def _on_model_loaded(self, model: ModelInfo) -> None:
        """Handle model loading completion.

        Args:
            model: The model that was loaded.
        """
        model.status = ModelStatus.LOADED
        if model.id in self._model_cards:
            self._model_cards[model.id].update_model(model)

        self._status_label.setText(f"Model loaded: {model.name}")
        if self._app.main_window:
            status_bar = self._app.main_window.statusBar()
            if hasattr(status_bar, 'set_model_status'):
                status_bar.set_model_status(model.name, "loaded")

    @Slot(str)
    def _on_unload_model(self, model_id: str) -> None:
        """Handle unload model action.

        Args:
            model_id: ID of the model to unload.
        """
        model = next((m for m in self._models if m.id == model_id), None)
        if not model:
            return

        confirm = self._app.config.get("model_manager.confirm_unload", True)
        if confirm:
            confirmed = self._app.show_confirm_dialog(
                "Unload Model",
                f"Are you sure you want to unload '{model.name}'?",
                "Unload",
                "Cancel",
            )
            if not confirmed:
                return

        model.status = ModelStatus.UNLOADING
        if model_id in self._model_cards:
            self._model_cards[model_id].update_model(model)

        self._status_label.setText(f"Unloading model: {model.name}...")

        QTimer.singleShot(1000, lambda: self._on_model_unloaded(model))

    def _on_model_unloaded(self, model: ModelInfo) -> None:
        """Handle model unloading completion.

        Args:
            model: The model that was unloaded.
        """
        model.status = ModelStatus.UNLOADED
        if model.id in self._model_cards:
            self._model_cards[model.id].update_model(model)

        self._status_label.setText(f"Model unloaded: {model.name}")
        if self._app.main_window:
            status_bar = self._app.main_window.statusBar()
            if hasattr(status_bar, 'set_model_status'):
                status_bar.set_model_status("", "unloaded")

    @Slot(str)
    def _on_model_info(self, model_id: str) -> None:
        """Show detailed model information.

        Args:
            model_id: ID of the model.
        """
        model = next((m for m in self._models if m.id == model_id), None)
        if not model:
            return

        info_text = f"""
        <h2>{model.name}</h2>
        <table>
        <tr><td><b>Model ID:</b></td><td>{model.id}</td></tr>
        <tr><td><b>Version:</b></td><td>{model.version}</td></tr>
        <tr><td><b>Type:</b></td><td>{model.model_type}</td></tr>
        <tr><td><b>Status:</b></td><td>{model.status.value}</td></tr>
        <tr><td><b>Size:</b></td><td>{model.formatted_size()}</td></tr>
        <tr><td><b>Parameters:</b></td><td>{model.formatted_parameters()}</td></tr>
        <tr><td><b>Quantization:</b></td><td>{model.quantization}</td></tr>
        <tr><td><b>Context Length:</b></td><td>{model.context_length}</td></tr>
        <tr><td><b>GPU Memory Required:</b></td><td>{model.gpu_memory_required} MB</td></tr>
        <tr><td><b>Path:</b></td><td>{model.path}</td></tr>
        </table>
        """

        if model.supported_features:
            info_text += "<p><b>Supported Features:</b> " + ", ".join(model.supported_features) + "</p>"

        if model.error_message:
            info_text += f'<p style="color: #F38BA8;"><b>Error:</b> {model.error_message}</p>'

        self._app.show_info_dialog(f"Model Info - {model.name}", info_text)

    @Slot()
    def _on_load_from_file(self) -> None:
        """Open file dialog to load a model file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Model File",
            "",
            "Model Files (*.gguf *.bin *.pt *.pth *.safetensors *.onnx *.ggml *.h5 *.keras *.tflite);;All Files (*)"
        )
        if file_path:
            self._load_model_files([file_path])

    def _load_model_files(self, file_paths: list[str]) -> None:
        """Load model files by adding them to the model list.

        Args:
            file_paths: List of file paths to load.
        """
        for filepath in file_paths:
            filename = os.path.basename(filepath)
            model_id = os.path.splitext(filename)[0]

            # Check if already exists
            if any(m.id == model_id for m in self._models):
                logger.info("Model already exists: %s", model_id)
                continue

            model = ModelInfo(
                id=model_id,
                name=filename,
                model_type="llm",
                description=f"Loaded from: {filepath}",
                status=ModelStatus.UNLOADED,
                path=filepath,
                size_bytes=os.path.getsize(filepath),
            )

            self._models.append(model)
            self._status_label.setText(f"Added model file: {filename}")

        self._populate_models()

    def _auto_refresh(self) -> None:
        """Auto-refresh the model list."""
        # In a real app, this would poll the backend
        pass

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the model manager.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name

    def cleanup(self) -> None:
        """Cleanup resources."""
        self._refresh_timer.stop()