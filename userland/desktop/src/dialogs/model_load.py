#!/usr/bin/env python3
"""Ainos Desktop - Model Load Dialog.

Provides a dialog for configuring model loading parameters
including quantization, GPU layers, and context settings.
"""

import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QGroupBox,
    QSlider,
    QProgressBar,
    QSizePolicy,
    QLineEdit,
    QMessageBox,
)

from client.models import ModelInfo, ModelStatus

logger = logging.getLogger(__name__)


class ModelLoadDialog(QDialog):
    """Dialog for configuring model loading parameters."""

    def __init__(self, model: ModelInfo, app: Any, parent: Any | None = None):
        """Initialize the model load dialog.

        Args:
            model: The model to load.
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._model = model
        self._app = app
        self._loading = False

        self.setWindowTitle(f"Load Model - {model.name}")
        self.setMinimumSize(450, 400)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Model info header
        header_layout = QHBoxLayout()

        model_icon = QLabel("🧠")
        model_icon.setStyleSheet("font-size: 32px;")
        header_layout.addWidget(model_icon)

        info_layout = QVBoxLayout()
        name_label = QLabel(self._model.name)
        name_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #CDD6F4;")
        info_layout.addWidget(name_label)

        details_label = QLabel(
            f"{self._model.formatted_parameters()} parameters  |  "
            f"{self._model.formatted_size()}  |  "
            f"{self._model.model_type}"
        )
        details_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        info_layout.addWidget(details_label)

        header_layout.addLayout(info_layout, 1)
        layout.addLayout(header_layout)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #313244;")
        layout.addWidget(separator)

        # Configuration options
        config_group = QGroupBox("Loading Configuration")
        config_layout = QGridLayout(config_group)
        config_layout.setSpacing(12)

        # Quantization
        config_layout.addWidget(QLabel("Quantization:"), 0, 0)
        self._quant_combo = QComboBox()
        self._quant_combo.addItems(["Q4_K_M", "Q4_K_S", "Q5_K_M", "Q5_K_S", "Q8_0", "f16"])
        if self._model.quantization:
            idx = self._quant_combo.findText(self._model.quantization)
            if idx >= 0:
                self._quant_combo.setCurrentIndex(idx)
        config_layout.addWidget(self._quant_combo, 0, 1)

        # GPU Layers
        config_layout.addWidget(QLabel("GPU Layers:"), 1, 0)
        self._gpu_layers = QSpinBox()
        self._gpu_layers.setRange(0, 200)
        self._gpu_layers.setValue(0)
        self._gpu_layers.setSpecialValueText("Auto")
        config_layout.addWidget(self._gpu_layers, 1, 1)

        # Context Length
        config_layout.addWidget(QLabel("Context Length:"), 2, 0)
        self._context_length = QSpinBox()
        self._context_length.setRange(512, 131072)
        self._context_length.setValue(min(self._model.context_length, 4096))
        self._context_length.setSingleStep(1024)
        config_layout.addWidget(self._context_length, 2, 1)

        # Batch Size
        config_layout.addWidget(QLabel("Batch Size:"), 3, 0)
        self._batch_size = QSpinBox()
        self._batch_size.setRange(1, 2048)
        self._batch_size.setValue(512)
        self._batch_size.setSingleStep(64)
        config_layout.addWidget(self._batch_size, 3, 1)

        # Threads
        config_layout.addWidget(QLabel("Threads:"), 4, 0)
        self._threads = QSpinBox()
        self._threads.setRange(1, 64)
        self._threads.setValue(8)
        config_layout.addWidget(self._threads, 4, 1)

        # Flash Attention
        self._flash_attn = QCheckBox("Use Flash Attention (if supported)")
        self._flash_attn.setChecked(True)
        config_layout.addWidget(self._flash_attn, 5, 0, 1, 2)

        # Memory mapping
        self._mmap = QCheckBox("Use memory mapping (mmap)")
        self._mmap.setChecked(True)
        config_layout.addWidget(self._mmap, 6, 0, 1, 2)

        layout.addWidget(config_group)

        # Resource estimate
        estimate_group = QGroupBox("Resource Estimate")
        estimate_layout = QVBoxLayout(estimate_group)

        if self._model.gpu_memory_required > 0:
            gpu_mem_label = QLabel(f"GPU Memory Required: ~{self._model.gpu_memory_required} MB")
            gpu_mem_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
            estimate_layout.addWidget(gpu_mem_label)

        # Try to detect available GPU memory
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                free_mem = int(result.stdout.strip().split('\n')[0].strip())
                mem_label = QLabel(f"Available GPU Memory: ~{free_mem} MB")
                if free_mem < self._model.gpu_memory_required:
                    mem_label.setStyleSheet("font-size: 10pt; color: #F38BA8;")
                else:
                    mem_label.setStyleSheet("font-size: 10pt; color: #A6E3A1;")
                estimate_layout.addWidget(mem_label)
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass

        layout.addWidget(estimate_group)

        # Progress bar (hidden initially)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 10pt; color: #A0A8C0;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self._cancel_btn)

        self._load_btn = QPushButton("Load Model")
        self._load_btn.setProperty("primary", True)
        self._load_btn.clicked.connect(self._on_load)
        button_layout.addWidget(self._load_btn)

        layout.addLayout(button_layout)

    @Slot()
    def _on_load(self) -> None:
        """Handle the load action."""
        self._loading = True
        self._load_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._status_label.setVisible(True)
        self._status_label.setText("Loading model...")

        # Simulate loading progress
        self._progress = 0
        self._load_timer = QTimer(self)
        self._load_timer.timeout.connect(self._simulate_progress)
        self._load_timer.start(100)

    def _simulate_progress(self) -> None:
        """Simulate loading progress."""
        self._progress += 2
        self._progress_bar.setValue(self._progress)

        if self._progress < 30:
            self._status_label.setText("Allocating memory...")
        elif self._progress < 60:
            self._status_label.setText("Loading model weights...")
        elif self._progress < 90:
            self._status_label.setText("Initializing inference engine...")
        elif self._progress < 100:
            self._status_label.setText("Finalizing...")
        else:
            self._load_timer.stop()
            self._status_label.setText("Model loaded successfully!")
            self._status_label.setStyleSheet("font-size: 10pt; color: #A6E3A1;")

            # Accept after a short delay
            QTimer.singleShot(500, self.accept)