#!/usr/bin/env python3
"""Tests for the Dashboard widget."""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt


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
    return app


class TestDashboardWidget:
    """Test suite for DashboardWidget."""

    def test_initialization(self, qapp, mock_app):
        """Test that the dashboard widget initializes correctly."""
        from widgets.dashboard import DashboardWidget

        widget = DashboardWidget(mock_app)
        assert widget is not None
        assert widget._theme == "dark"
        assert widget._update_timer is not None

    def test_metric_card_creation(self, qapp, mock_app):
        """Test that metric cards are created in the dashboard."""
        from widgets.dashboard import DashboardWidget

        widget = DashboardWidget(mock_app)
        # Check that metric cards exist
        assert hasattr(widget, '_cpu_card')
        assert hasattr(widget, '_memory_card')
        assert hasattr(widget, '_gpu_card')
        assert hasattr(widget, '_model_card')
        assert hasattr(widget, '_uptime_card')

    def test_apply_theme(self, qapp, mock_app):
        """Test theme application."""
        from widgets.dashboard import DashboardWidget

        widget = DashboardWidget(mock_app)
        widget.apply_theme("light")
        assert widget._theme == "light"

    def test_cleanup(self, qapp, mock_app):
        """Test cleanup stops timers."""
        from widgets.dashboard import DashboardWidget

        widget = DashboardWidget(mock_app)
        assert widget._update_timer.isActive()
        widget.cleanup()
        assert not widget._update_timer.isActive()


class TestMetricCard:
    """Test suite for MetricCard."""

    def test_initialization(self, qapp):
        """Test metric card initialization."""
        from widgets.dashboard import MetricCard

        card = MetricCard("CPU Usage", "45%", "%", "🖥️", "#89B4FA")
        assert card._title == "CPU Usage"
        assert card._value == "45%"
        assert card._unit == "%"

    def test_set_value(self, qapp):
        """Test setting a value on the card."""
        from widgets.dashboard import MetricCard

        card = MetricCard("Test", "0%")
        card.set_value("50%")
        assert card._value_label.text() == "50%"

    def test_set_progress(self, qapp):
        """Test setting progress bar value."""
        from widgets.dashboard import MetricCard

        card = MetricCard("Test", "0%")
        card.set_progress(75)
        assert card._progress_bar.value() == 75


class TestQuickActionButton:
    """Test suite for QuickActionButton."""

    def test_initialization(self, qapp):
        """Test quick action button initialization."""
        from widgets.dashboard import QuickActionButton

        btn = QuickActionButton("Load Model", "Description", "📥")
        assert btn is not None


class TestSystemChartWidget:
    """Test suite for SystemChartWidget."""

    def test_initialization(self, qapp):
        """Test system chart widget initialization."""
        from widgets.charts import SystemChartWidget

        widget = SystemChartWidget()
        assert widget is not None
        assert hasattr(widget, 'cpu_chart')
        assert hasattr(widget, 'memory_chart')
        assert hasattr(widget, 'gpu_chart')

    def test_update_data(self, qapp):
        """Test updating chart data."""
        from widgets.charts import SystemChartWidget

        widget = SystemChartWidget()
        widget.update_data(cpu=50.0, memory=60.0, gpu=70.0)
        # Data should be added to the charts
        assert len(widget.cpu_chart._series["cpu"]["data"]) == 1
        assert len(widget.memory_chart._series["memory"]["data"]) == 1


class TestTimeSeriesChart:
    """Test suite for TimeSeriesChart."""

    def test_initialization(self, qapp):
        """Test time series chart initialization."""
        from widgets.charts import TimeSeriesChart

        chart = TimeSeriesChart("Test Chart", "Value (%)", max_points=100)
        assert chart._title == "Test Chart"
        assert chart._ylabel == "Value (%)"
        assert chart._max_points == 100

    def test_add_series(self, qapp):
        """Test adding a data series."""
        from widgets.charts import TimeSeriesChart

        chart = TimeSeriesChart("Test")
        chart.add_series("test_series")
        assert "test_series" in chart._series

    def test_remove_series(self, qapp):
        """Test removing a data series."""
        from widgets.charts import TimeSeriesChart

        chart = TimeSeriesChart("Test")
        chart.add_series("test_series")
        chart.remove_series("test_series")
        assert "test_series" not in chart._series

    def test_add_data_point(self, qapp):
        """Test adding data points."""
        from widgets.charts import TimeSeriesChart

        chart = TimeSeriesChart("Test")
        chart.add_data_point("cpu", 50.0)
        chart.add_data_point("cpu", 60.0)
        assert len(chart._series["cpu"]["data"]) == 2

    def test_clear_data(self, qapp):
        """Test clearing all data."""
        from widgets.charts import TimeSeriesChart

        chart = TimeSeriesChart("Test")
        chart.add_data_point("cpu", 50.0)
        chart.clear_data()
        assert len(chart._series["cpu"]["data"]) == 0

    def test_set_paused(self, qapp):
        """Test pausing chart updates."""
        from widgets.charts import TimeSeriesChart

        chart = TimeSeriesChart("Test")
        chart.set_paused(True)
        assert chart._paused

    def test_apply_theme(self, qapp):
        """Test theme application."""
        from widgets.charts import TimeSeriesChart

        chart = TimeSeriesChart("Test")
        chart.apply_theme("light")
        assert chart._theme == "light"