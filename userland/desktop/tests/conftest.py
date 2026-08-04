#!/usr/bin/env python3
"""Pytest configuration and fixtures for Ainos Desktop tests."""

import sys
import os
import pytest
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication instance for the test session."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def mock_app():
    """Create a mock AinosApplication."""
    app = MagicMock()
    app.config.get.return_value = "dark"
    app.config.set = MagicMock()
    app.config.save = MagicMock()
    app.current_theme = "dark"
    app.main_window = None
    app.show_confirm_dialog.return_value = True
    app.show_info_dialog = MagicMock()
    app.show_error_dialog = MagicMock()
    return app


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary configuration file."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("""
    theme: dark
    connection:
        host: 127.0.0.1
        port: 8765
    """)
    return str(config_path)


@pytest.fixture
def sample_model_info():
    """Create a sample ModelInfo for testing."""
    from client.models import ModelInfo, ModelStatus

    return ModelInfo(
        id="test-model",
        name="Test Model",
        version="1.0",
        model_type="llm",
        description="A test model",
        status=ModelStatus.UNLOADED,
        size_bytes=1_000_000_000,
        parameter_count=1_000_000_000,
        quantization="Q4_K_M",
        context_length=4096,
    )


def pytest_configure(config):
    """Configure pytest for GUI tests."""
    # Set QT_QPA_PLATFORM to offscreen for headless testing
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"