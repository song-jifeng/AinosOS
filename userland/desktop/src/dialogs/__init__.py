# Ainos Desktop - Dialogs Package
"""Dialog windows for the Ainos Desktop application."""

from .about import AboutDialog
from .model_load import ModelLoadDialog
from .settings import SettingsDialog

__all__ = [
    "AboutDialog",
    "ModelLoadDialog",
    "SettingsDialog",
]