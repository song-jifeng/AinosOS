#!/usr/bin/env python3
"""Ainos Desktop - Charts Components.

This module provides real-time chart widgets for displaying
CPU, memory, GPU, and temperature data using pyqtgraph.
"""

import math
import logging
from typing import Any
from collections import deque

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QSizePolicy,
)

try:
    import pyqtgraph as pg

    PYQTGRAPH_AVAILABLE = True
except ImportError:
    PYQTGRAPH_AVAILABLE = False
    pg = None  # type: ignore

logger = logging.getLogger(__name__)


class ChartTheme:
    """Manages chart color schemes for dark and light themes."""

    DARK = {
        "bg": "#1E1E2E",
        "grid": "#313244",
        "label": "#CDD6F4",
        "axis": "#6C7086",
        "line_1": "#89B4FA",
        "line_2": "#A6E3A1",
        "line_3": "#FAB387",
        "line_4": "#CBA6F7",
        "line_5": "#F38BA8",
        "fill_1": "#1A3A5C",
        "fill_2": "#1A3C2A",
        "fill_3": "#3C2A1A",
        "crosshair": "#FFFFFF",
    }

    LIGHT = {
        "bg": "#FFFFFF",
        "grid": "#E5E5EF",
        "label": "#1A1A2E",
        "axis": "#8888A0",
        "line_1": "#2563EB",
        "line_2": "#16A34A",
        "line_3": "#D97706",
        "line_4": "#7C3AED",
        "line_5": "#DC2626",
        "fill_1": "#DBEAFE",
        "fill_2": "#DCFCE7",
        "fill_3": "#FEF3C7",
        "crosshair": "#333333",
    }

    @classmethod
    def get(cls, theme: str = "dark") -> dict[str, str]:
        """Get color scheme for a theme.

        Args:
            theme: Theme name ('dark' or 'light').

        Returns:
            Dictionary of color values.
        """
        return cls.DARK if theme == "dark" else cls.LIGHT


class TimeSeriesChart(QFrame):
    """A real-time time series chart widget.

    Displays scrolling line charts with configurable update intervals,
    data point limits, and multiple series support.
    """

    def __init__(
        self,
        title: str = "",
        ylabel: str = "",
        max_points: int = 300,
        update_interval_ms: int = 2000,
        parent: QWidget | None = None,
    ):
        """Initialize the time series chart.

        Args:
            title: Chart title.
            ylabel: Y-axis label.
            max_points: Maximum number of data points to display.
            update_interval_ms: Update interval in milliseconds.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("chartFrame")

        self._title = title
        self._ylabel = ylabel
        self._max_points = max_points
        self._update_interval_ms = update_interval_ms
        self._theme = "dark"
        self._series: dict[str, dict[str, Any]] = {}
        self._paused = False

        # Setup UI
        self._setup_ui()

        # Update timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_plot)
        if update_interval_ms > 0:
            self._timer.start(update_interval_ms)

        logger.debug("TimeSeriesChart created: %s", title)

    def _setup_ui(self) -> None:
        """Set up the chart UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Title
        if self._title:
            title_label = QLabel(self._title)
            title_label.setProperty("subheading", True)
            layout.addWidget(title_label)

        # Plot widget
        if PYQTGRAPH_AVAILABLE:
            self._plot_widget = pg.PlotWidget()
            self._plot_widget.setBackground(None)
            self._plot_widget.setLabel("left", self._ylabel)
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self._plot_widget.setMouseEnabled(x=False, y=False)
            self._plot_widget.setMenuEnabled(False)
            self._plot_widget.setMinimumHeight(200)
            self._plot_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

            # Remove default axis
            self._plot_widget.getAxis("bottom").setStyle(
                tickFont=QFont("", 8), tickTextOffset=4
            )
            self._plot_widget.getAxis("left").setStyle(
                tickFont=QFont("", 8), tickTextOffset=4
            )

            self._plot_widget.enableAutoRange(axis="y", enable=True)
            self._plot_widget.setLimits(xMin=-self._max_points, xMax=0)

            layout.addWidget(self._plot_widget, 1)
        else:
            placeholder = QLabel(
                "Chart library (pyqtgraph) not available.\n"
                "Install it with: pip install pyqtgraph"
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #6C7086; padding: 40px;")
            layout.addWidget(placeholder, 1)

        # Legend
        self._legend_widget = QWidget()
        self._legend_layout = QHBoxLayout(self._legend_widget)
        self._legend_layout.setContentsMargins(0, 4, 0, 0)
        self._legend_layout.setSpacing(16)
        self._legend_layout.addStretch()
        layout.addWidget(self._legend_widget)

    def add_series(
        self,
        name: str,
        color: str | None = None,
        line_width: int = 2,
        fill: bool = False,
    ) -> None:
        """Add a new data series to the chart.

        Args:
            name: Series identifier.
            color: Line color hex string. Uses theme colors if None.
            line_width: Line width in pixels.
            fill: Whether to fill under the curve.
        """
        if name in self._series:
            return

        colors = ChartTheme.get(self._theme)
        color_map = {
            "cpu": colors["line_1"],
            "memory": colors["line_2"],
            "gpu": colors["line_3"],
            "temperature": colors["line_4"],
            "custom_1": colors["line_1"],
            "custom_2": colors["line_2"],
            "custom_3": colors["line_3"],
            "custom_4": colors["line_4"],
            "custom_5": colors["line_5"],
        }

        series_color = color or color_map.get(name, colors["line_1"])

        series_data = {
            "name": name,
            "color": series_color,
            "line_width": line_width,
            "fill": fill,
            "data": deque(maxlen=self._max_points),
            "curve": None,
            "fill_curve": None,
        }

        if PYQTGRAPH_AVAILABLE:
            pen = pg.mkPen(color=series_color, width=line_width)
            series_data["curve"] = self._plot_widget.plot(
                [], [], pen=pen, name=name
            )

            if fill:
                fill_color = QColor(series_color)
                fill_color.setAlpha(40)
                series_data["fill_curve"] = pg.FillBetweenItem(
                    curve1=series_data["curve"],
                    curve2=pg.PlotCurveItem([], []),
                    brush=pg.mkBrush(fill_color),
                )
                self._plot_widget.addItem(series_data["fill_curve"])

        self._series[name] = series_data

        # Add to legend
        legend_label = QLabel(f"● {name}")
        legend_label.setStyleSheet(f"color: {series_color}; font-size: 9pt;")
        self._legend_layout.insertWidget(
            self._legend_layout.count() - 1, legend_label
        )

        logger.debug("Series added to chart '%s': %s", self._title, name)

    def remove_series(self, name: str) -> None:
        """Remove a data series from the chart.

        Args:
            name: Series identifier to remove.
        """
        if name not in self._series:
            return

        series = self._series.pop(name)

        if PYQTGRAPH_AVAILABLE:
            if series["fill_curve"]:
                self._plot_widget.removeItem(series["fill_curve"])
            if series["curve"]:
                self._plot_widget.removeItem(series["curve"])

        # Remove from legend
        for i in range(self._legend_layout.count()):
            item = self._legend_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QLabel):
                if name in item.widget().text():
                    item.widget().deleteLater()
                    break

        logger.debug("Series removed from chart '%s': %s", self._title, name)

    def add_data_point(self, series_name: str, value: float) -> None:
        """Add a single data point to a series.

        Args:
            series_name: Series identifier.
            value: Data point value.
        """
        if series_name not in self._series:
            self.add_series(series_name)

        self._series[series_name]["data"].append(value)

    def add_data_batch(self, series_name: str, values: list[float]) -> None:
        """Add multiple data points to a series at once.

        Args:
            series_name: Series identifier.
            values: List of data point values.
        """
        if series_name not in self._series:
            self.add_series(series_name)

        for v in values:
            self._series[series_name]["data"].append(v)

    def clear_data(self) -> None:
        """Clear all data from all series."""
        for series in self._series.values():
            series["data"].clear()
        self._update_plot()

    def set_update_interval(self, interval_ms: int) -> None:
        """Set the chart update interval.

        Args:
            interval_ms: Update interval in milliseconds. 0 to disable.
        """
        self._update_interval_ms = interval_ms
        self._timer.stop()
        if interval_ms > 0:
            self._timer.start(interval_ms)

    def set_paused(self, paused: bool) -> None:
        """Pause or resume chart updates.

        Args:
            paused: True to pause, False to resume.
        """
        self._paused = paused

    @Slot()
    def _update_plot(self) -> None:
        """Update the chart display."""
        if self._paused or not PYQTGRAPH_AVAILABLE:
            return

        try:
            for series_name, series in self._series.items():
                data = list(series["data"])
                if not data:
                    continue

                x = list(range(-len(data) + 1, 1))
                y = data

                if series["curve"]:
                    series["curve"].setData(x, y)

                if series["fill_curve"] and series["fill_curve"]:
                    # Create a zero line for fill base
                    base_line = pg.PlotCurveItem(x, [0] * len(x))
                    series["fill_curve"].setCurves(
                        curve1=series["curve"], curve2=base_line
                    )

        except Exception as e:
            logger.debug("Chart update error: %s", e)

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the chart.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        self._theme = theme_name
        colors = ChartTheme.get(theme_name)

        if PYQTGRAPH_AVAILABLE:
            # Update axis colors
            axis_pen = pg.mkPen(color=colors["axis"], width=1)
            label_color = colors["label"]

            self._plot_widget.getAxis("bottom").setPen(axis_pen)
            self._plot_widget.getAxis("bottom").setTextPen(label_color)
            self._plot_widget.getAxis("left").setPen(axis_pen)
            self._plot_widget.getAxis("left").setTextPen(label_color)

            # Update grid
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # Update series colors
        for series_name, series in self._series.items():
            if series["curve"] and PYQTGRAPH_AVAILABLE:
                series["curve"].setPen(
                    pg.mkPen(color=series["color"], width=series["line_width"])
                )

    def apply_theme_to_series(self, color_map: dict[str, str]) -> None:
        """Apply custom colors to specific series.

        Args:
            color_map: Dictionary mapping series names to color strings.
        """
        for name, color in color_map.items():
            if name in self._series:
                self._series[name]["color"] = color
                if self._series[name]["curve"] and PYQTGRAPH_AVAILABLE:
                    self._series[name]["curve"].setPen(
                        pg.mkPen(color=color, width=self._series[name]["line_width"])
                    )


class CpuChart(TimeSeriesChart):
    """Specialized chart for CPU usage display."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize the CPU chart.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(
            title="CPU Usage",
            ylabel="Usage (%)",
            max_points=300,
            update_interval_ms=2000,
            parent=parent,
        )
        self.add_series("cpu", line_width=2, fill=True)
        # Set Y range
        if PYQTGRAPH_AVAILABLE:
            self._plot_widget.setYRange(0, 100)


class MemoryChart(TimeSeriesChart):
    """Specialized chart for memory usage display."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize the memory chart.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(
            title="Memory Usage",
            ylabel="Usage (%)",
            max_points=300,
            update_interval_ms=2000,
            parent=parent,
        )
        self.add_series("memory", line_width=2, fill=True)
        if PYQTGRAPH_AVAILABLE:
            self._plot_widget.setYRange(0, 100)


class TemperatureChart(TimeSeriesChart):
    """Specialized chart for temperature display."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize the temperature chart.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(
            title="Temperature",
            ylabel="Temperature (°C)",
            max_points=300,
            update_interval_ms=2000,
            parent=parent,
        )
        self.add_series("temperature", line_width=2, fill=True)
        if PYQTGRAPH_AVAILABLE:
            self._plot_widget.setYRange(0, 100)


class GpuChart(TimeSeriesChart):
    """Specialized chart for GPU usage display."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize the GPU chart.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(
            title="GPU Usage",
            ylabel="Usage (%)",
            max_points=300,
            update_interval_ms=2000,
            parent=parent,
        )
        self.add_series("gpu", line_width=2, fill=True)
        self.add_series("gpu_memory", line_width=2, fill=False)
        if PYQTGRAPH_AVAILABLE:
            self._plot_widget.setYRange(0, 100)


class SystemChartWidget(QWidget):
    """Composite widget that contains multiple system charts.

    Provides CPU, Memory, GPU, and Temperature charts in a grid layout.
    """

    def __init__(self, parent: QWidget | None = None):
        """Initialize the system chart widget.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._setup_ui()

        # Update timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_series)
        self._timer.start(10000)  # Check series every 10s

    def _setup_ui(self) -> None:
        """Set up the widget layout."""
        from PySide6.QtWidgets import QGridLayout

        layout = QGridLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create charts
        self.cpu_chart = CpuChart()
        self.memory_chart = MemoryChart()
        self.gpu_chart = GpuChart()
        self.temperature_chart = TemperatureChart()

        # Add to layout (2x2 grid)
        layout.addWidget(self.cpu_chart, 0, 0)
        layout.addWidget(self.memory_chart, 0, 1)
        layout.addWidget(self.gpu_chart, 1, 0)
        layout.addWidget(self.temperature_chart, 1, 1)

        # Set equal stretch
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)

    def _check_series(self) -> None:
        """Ensure all series are properly initialized."""
        pass

    def update_data(
        self,
        cpu: float | None = None,
        memory: float | None = None,
        gpu: float | None = None,
        gpu_memory: float | None = None,
        temperature: float | None = None,
    ) -> None:
        """Update all chart data points.

        Args:
            cpu: CPU usage percentage.
            memory: Memory usage percentage.
            gpu: GPU usage percentage.
            gpu_memory: GPU memory usage percentage.
            temperature: Temperature in Celsius.
        """
        if cpu is not None:
            self.cpu_chart.add_data_point("cpu", cpu)
        if memory is not None:
            self.memory_chart.add_data_point("memory", memory)
        if gpu is not None:
            self.gpu_chart.add_data_point("gpu", gpu)
        if gpu_memory is not None:
            self.gpu_chart.add_data_point("gpu_memory", gpu_memory)
        if temperature is not None:
            self.temperature_chart.add_data_point("temperature", temperature)

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to all charts.

        Args:
            theme_name: Theme name ('dark' or 'light').
        """
        for chart in [self.cpu_chart, self.memory_chart, self.gpu_chart, self.temperature_chart]:
            chart.apply_theme(theme_name)