# Ainos Desktop - Widgets Package
"""UI widgets for the Ainos Desktop application."""

from .dashboard import DashboardWidget
from .model_manager import ModelManagerWidget
from .inference import InferenceWidget
from .monitor import MonitorWidget
from .context_viewer import ContextViewerWidget
from .settings import SettingsWidget
from .log_viewer import LogViewerWidget
from .status_bar import AinosStatusBar
from .charts import (
    CpuChart,
    MemoryChart,
    TemperatureChart,
    GpuChart,
    SystemChartWidget,
)

__all__ = [
    "DashboardWidget",
    "ModelManagerWidget",
    "InferenceWidget",
    "MonitorWidget",
    "ContextViewerWidget",
    "SettingsWidget",
    "LogViewerWidget",
    "AinosStatusBar",
    "CpuChart",
    "MemoryChart",
    "TemperatureChart",
    "GpuChart",
    "SystemChartWidget",
]