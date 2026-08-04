#!/usr/bin/env python3
"""Tests for the Model Manager widget."""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt

from client.models import ModelInfo, ModelStatus


@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def mock_app():
    """Create a mock AinosApplication."""
    app = MagicMock()
    app.config.get.return_value = "dark"
    app.main_window = None
    app.show_confirm_dialog.return_value = True
    return app


@pytest.fixture
def sample_model():
    """Create a sample ModelInfo for testing."""
    return ModelInfo(
        id="test-model-7b",
        name="Test Model 7B",
        version="1.0",
        model_type="llm",
        description="A test model for unit testing",
        status=ModelStatus.UNLOADED,
        size_bytes=4_000_000_000,
        parameter_count=7_000_000_000,
        quantization="Q4_K_M",
        context_length=4096,
    )


class TestModelManagerWidget:
    """Test suite for ModelManagerWidget."""

    def test_initialization(self, qapp, mock_app):
        """Test that the model manager initializes correctly."""
        from widgets.model_manager import ModelManagerWidget

        widget = ModelManagerWidget(mock_app)
        assert widget is not None
        assert widget._theme == "dark"

    def test_refresh_models(self, qapp, mock_app):
        """Test refreshing the model list."""
        from widgets.model_manager import ModelManagerWidget

        widget = ModelManagerWidget(mock_app)
        widget.refresh_models()
        assert len(widget._models) > 0

    def test_filter_models_by_search(self, qapp, mock_app):
        """Test filtering models by search text."""
        from widgets.model_manager import ModelManagerWidget

        widget = ModelManagerWidget(mock_app)
        widget.refresh_models()
        widget._search_input.setText("llama")
        widget._filter_models()
        # Should filter to only matching models

    def test_filter_models_by_category(self, qapp, mock_app):
        """Test filtering models by category."""
        from widgets.model_manager import ModelManagerWidget

        widget = ModelManagerWidget(mock_app)
        widget.refresh_models()
        widget._filter_combo.setCurrentText("Loaded")
        widget._filter_models()
        # Should filter to only loaded models

    def test_apply_theme(self, qapp, mock_app):
        """Test theme application."""
        from widgets.model_manager import ModelManagerWidget

        widget = ModelManagerWidget(mock_app)
        widget.apply_theme("light")
        assert widget._theme == "light"

    def test_cleanup(self, qapp, mock_app):
        """Test cleanup stops timers."""
        from widgets.model_manager import ModelManagerWidget

        widget = ModelManagerWidget(mock_app)
        widget.cleanup()
        assert not widget._refresh_timer.isActive()

    def test_load_from_file(self, qapp, mock_app, tmp_path):
        """Test loading a model from file."""
        from widgets.model_manager import ModelManagerWidget

        # Create a temp file
        model_file = tmp_path / "test_model.gguf"
        model_file.write_text("dummy model content")

        widget = ModelManagerWidget(mock_app)
        widget.refresh_models()
        initial_count = len(widget._models)
        widget._load_model_files([str(model_file)])
        assert len(widget._models) == initial_count + 1


class TestModelCard:
    """Test suite for ModelCard."""

    def test_initialization(self, qapp, sample_model):
        """Test model card initialization."""
        from widgets.model_manager import ModelCard

        card = ModelCard(sample_model)
        assert card._model.id == "test-model-7b"

    def test_update_model(self, qapp, sample_model):
        """Test updating model card data."""
        from widgets.model_manager import ModelCard

        card = ModelCard(sample_model)
        updated_model = ModelInfo(
            id="test-model-7b",
            name="Test Model 7B",
            version="1.0",
            model_type="llm",
            description="Updated description",
            status=ModelStatus.LOADED,
            size_bytes=4_000_000_000,
            parameter_count=7_000_000_000,
        )
        card.update_model(updated_model)
        assert card._model.status == ModelStatus.LOADED

    def test_status_colors(self, qapp, sample_model):
        """Test status color mapping."""
        from widgets.model_manager import ModelCard

        card = ModelCard(sample_model)
        assert "loaded" in ModelCard.STATUS_COLORS
        assert "unloaded" in ModelCard.STATUS_COLORS
        assert "error" in ModelCard.STATUS_COLORS


class TestModelInfo:
    """Test suite for ModelInfo data model."""

    def test_formatted_size_bytes(self):
        """Test formatted size output."""
        model = ModelInfo(size_bytes=1_500_000_000)
        assert "GB" in model.formatted_size()

    def test_formatted_size_unknown(self):
        """Test formatted size when size is 0."""
        model = ModelInfo(size_bytes=0)
        assert model.formatted_size() == "Unknown"

    def test_formatted_parameters_billions(self):
        """Test parameter formatting for billions."""
        model = ModelInfo(parameter_count=7_000_000_000)
        assert model.formatted_parameters() == "7B"

    def test_formatted_parameters_millions(self):
        """Test parameter formatting for millions."""
        model = ModelInfo(parameter_count=137_000_000)
        assert model.formatted_parameters() == "137M"

    def test_formatted_parameters_unknown(self):
        """Test parameter formatting when unknown."""
        model = ModelInfo(parameter_count=0)
        assert model.formatted_parameters() == "Unknown"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        model = ModelInfo(id="test", name="Test", status=ModelStatus.LOADED)
        data = model.to_dict()
        assert data["id"] == "test"
        assert data["status"] == "loaded"

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "id": "test",
            "name": "Test",
            "status": "loaded",
            "model_type": "llm",
        }
        model = ModelInfo.from_dict(data)
        assert model.id == "test"
        assert model.status == ModelStatus.LOADED