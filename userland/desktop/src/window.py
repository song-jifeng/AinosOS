#!/usr/bin/env python3
"""Ainos Desktop - Main Window.

This module provides the main application window with tab-based navigation,
sidebar, and integrated status bar.
"""

import logging
from typing import Any

from PySide6.QtCore import Qt, QSize, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QMenuBar,
    QMenu,
    QToolBar,
    QStatusBar,
    QSplitter,
    QPushButton,
    QLabel,
    QFrame,
    QSizePolicy,
    QApplication,
    QMessageBox,
)

from widgets.dashboard import DashboardWidget
from widgets.model_manager import ModelManagerWidget
from widgets.inference import InferenceWidget
from widgets.monitor import MonitorWidget
from widgets.context_viewer import ContextViewerWidget
from widgets.settings import SettingsWidget
from widgets.log_viewer import LogViewerWidget
from widgets.status_bar import AinosStatusBar
from dialogs.about import AboutDialog
from dialogs.settings import SettingsDialog

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with tab navigation and system tray integration."""

    # Global signals
    theme_changed = Signal(str)
    tab_changed = Signal(int)

    TAB_NAMES = [
        "Dashboard",
        "Model Manager",
        "Inference",
        "Monitor",
        "Context Viewer",
        "Settings",
        "Log Viewer",
    ]

    TAB_ICONS = [
        "📊",
        "🧠",
        "💬",
        "📈",
        "📋",
        "⚙️",
        "📝",
    ]

    def __init__(self, app: Any, parent: QWidget | None = None):
        """Initialize the main window.

        Args:
            app: The AinosApplication instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app = app

        # Window state
        self._current_tab = 0
        self._is_fullscreen = False
        self._is_maximized = False

        # Widget references
        self._widgets: dict[str, QWidget] = {}
        self._tab_widget: QTabWidget | None = None

        # Setup UI
        self._setup_window()
        self._setup_menu_bar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._setup_shortcuts()
        self._connect_signals()

        # Restore window geometry
        self._restore_geometry()

        # Start health check timer
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._on_health_check)
        self._health_timer.start(30000)  # 30 seconds

        logger.info("Main window initialized")

    def _setup_window(self) -> None:
        """Configure window properties."""
        self.setWindowTitle("Ainos Desktop")
        self.setMinimumSize(1024, 700)
        self.resize(1400, 900)

        # Center on screen
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        """Center the window on the current screen."""
        screen = self.screen()
        if screen:
            screen_geometry = screen.availableGeometry()
            window_geometry = self.frameGeometry()
            center = screen_geometry.center()
            window_geometry.moveCenter(center)
            self.move(window_geometry.topLeft())

    def _setup_menu_bar(self) -> None:
        """Create the application menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        new_session_action = QAction("&New Session", self)
        new_session_action.setShortcut(QKeySequence("Ctrl+N"))
        new_session_action.setStatusTip("Start a new inference session")
        new_session_action.triggered.connect(self._on_new_session)
        file_menu.addAction(new_session_action)

        file_menu.addSeparator()

        settings_action = QAction("&Settings...", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.setStatusTip("Open settings dialog")
        settings_action.triggered.connect(self._open_settings_dialog)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.setStatusTip("Exit the application")
        quit_action.triggered.connect(self._app._quit_application)
        file_menu.addAction(quit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        clear_context_action = QAction("Clear &Context", self)
        clear_context_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        clear_context_action.setStatusTip("Clear all context data")
        clear_context_action.triggered.connect(self._on_clear_context)
        edit_menu.addAction(clear_context_action)

        edit_menu.addSeparator()

        preferences_action = QAction("&Preferences...", self)
        preferences_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        preferences_action.triggered.connect(self._open_settings_dialog)
        edit_menu.addAction(preferences_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        toggle_sidebar_action = QAction("Toggle &Sidebar", self)
        toggle_sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        toggle_sidebar_action.setStatusTip("Show or hide the sidebar")
        toggle_sidebar_action.triggered.connect(self._on_toggle_sidebar)
        view_menu.addAction(toggle_sidebar_action)

        view_menu.addSeparator()

        fullscreen_action = QAction("&Fullscreen", self)
        fullscreen_action.setShortcut(QKeySequence("F11"))
        fullscreen_action.setCheckable(True)
        fullscreen_action.triggered.connect(self._on_toggle_fullscreen)
        view_menu.addAction(fullscreen_action)

        # Theme submenu
        theme_menu = view_menu.addMenu("&Theme")
        dark_action = QAction("&Dark", theme_menu)
        dark_action.setCheckable(True)
        dark_action.setChecked(self._app.current_theme == "dark")
        dark_action.triggered.connect(lambda: self._app.apply_theme("dark"))
        theme_menu.addAction(dark_action)

        light_action = QAction("&Light", theme_menu)
        light_action.setCheckable(True)
        light_action.setChecked(self._app.current_theme == "light")
        light_action.triggered.connect(lambda: self._app.apply_theme("light"))
        theme_menu.addAction(light_action)

        # Keep theme menu items in sync
        self.theme_changed.connect(lambda t: dark_action.setChecked(t == "dark"))
        self.theme_changed.connect(lambda t: light_action.setChecked(t == "light"))

        view_menu.addSeparator()

        # Tab navigation submenu
        tabs_menu = view_menu.addMenu("&Go to Tab")
        for i, name in enumerate(self.TAB_NAMES):
            action = QAction(f"&{i + 1}. {name}", self)
            action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            action.triggered.connect(lambda checked, idx=i: self._switch_to_tab(idx))
            tabs_menu.addAction(action)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        reload_models_action = QAction("&Reload Models", self)
        reload_models_action.setShortcut(QKeySequence("Ctrl+R"))
        reload_models_action.setStatusTip("Reload model list from backend")
        reload_models_action.triggered.connect(self._on_reload_models)
        tools_menu.addAction(reload_models_action)

        tools_menu.addSeparator()

        diagnostics_action = QAction("Run &Diagnostics", self)
        diagnostics_action.setStatusTip("Run system diagnostics")
        diagnostics_action.triggered.connect(self._on_run_diagnostics)
        tools_menu.addAction(diagnostics_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About Ainos Desktop", self)
        about_action.setStatusTip("About this application")
        about_action.triggered.connect(self._open_about_dialog)
        help_menu.addAction(about_action)

        about_qt_action = QAction("About &Qt", self)
        about_qt_action.triggered.connect(QApplication.aboutQt)
        help_menu.addAction(about_qt_action)

    def _setup_central_widget(self) -> None:
        """Create the central widget with tab navigation."""
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Tab widget
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setTabsClosable(False)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        # Create all tab widgets
        self._create_tabs()

        main_layout.addWidget(self._tab_widget)

    def _create_tabs(self) -> None:
        """Create and add all tab widgets."""
        tab_configs = [
            ("Dashboard", DashboardWidget),
            ("Model Manager", ModelManagerWidget),
            ("Inference", InferenceWidget),
            ("Monitor", MonitorWidget),
            ("Context Viewer", ContextViewerWidget),
            ("Settings", SettingsWidget),
            ("Log Viewer", LogViewerWidget),
        ]

        for name, widget_class in tab_configs:
            try:
                widget = widget_class(self._app)
                self._widgets[name.lower().replace(" ", "_")] = widget
                self._tab_widget.addTab(widget, name)
                logger.debug("Created tab: %s", name)
            except Exception as e:
                logger.error("Failed to create tab %s: %s", name, e)
                # Create placeholder
                placeholder = QWidget()
                layout = QVBoxLayout(placeholder)
                layout.addWidget(QLabel(f"Failed to load {name}: {e}"))
                self._tab_widget.addTab(placeholder, name)

    def _setup_status_bar(self) -> None:
        """Create the application status bar."""
        self._status_bar = AinosStatusBar(self._app, self)
        self.setStatusBar(self._status_bar)

    def _setup_shortcuts(self) -> None:
        """Register keyboard shortcuts."""
        # Most shortcuts are handled via menu actions
        pass

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        # Theme changes
        self._app.signals.theme_changed.connect(self.apply_theme)
        self._app.signals.connection_status_changed.connect(
            self._on_connection_status_changed
        )
        self._app.signals.shutdown_requested.connect(self._on_shutdown_requested)

    def _restore_geometry(self) -> None:
        """Restore window geometry from settings."""
        geometry = self._app.config.get("window.geometry", "")
        if geometry:
            try:
                parts = geometry.replace("x", ",").split(",")
                if len(parts) == 2:
                    w, h = int(parts[0]), int(parts[1])
                    self.resize(w, h)
                elif len(parts) == 4:
                    x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    self.setGeometry(x, y, w, h)
            except (ValueError, IndexError) as e:
                logger.warning("Failed to restore window geometry: %s", e)

        # Restore maximized state
        if self._app.config.get("window.maximized", False):
            self.showMaximized()

    def _save_geometry(self) -> None:
        """Save current window geometry to settings."""
        if self.isMaximized():
            self._app.config.set("window.maximized", True)
        else:
            self._app.config.set("window.maximized", False)
            geo = self.geometry()
            geometry_str = f"{geo.x()},{geo.y()},{geo.width()}x{geo.height()}"
            self._app.config.set("window.geometry", geometry_str)

    # === Slots ===

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change events.

        Args:
            index: Index of the newly selected tab.
        """
        self._current_tab = index
        self.tab_changed.emit(index)
        logger.debug("Switched to tab: %s", self.TAB_NAMES[index] if index < len(self.TAB_NAMES) else f"Tab {index}")

    @Slot()
    def _on_new_session(self) -> None:
        """Start a new inference session."""
        self._switch_to_tab(2)  # Inference tab
        inference_widget = self._widgets.get("inference")
        if inference_widget and hasattr(inference_widget, "new_session"):
            inference_widget.new_session()

    @Slot()
    def _on_clear_context(self) -> None:
        """Clear all context data after confirmation."""
        confirmed = self._app.show_confirm_dialog(
            "Clear Context",
            "Are you sure you want to clear all context data? This cannot be undone.",
            "Clear",
            "Cancel",
        )
        if confirmed:
            context_widget = self._widgets.get("context_viewer")
            if context_widget and hasattr(context_widget, "clear_all"):
                context_widget.clear_all()

    @Slot()
    def _on_toggle_sidebar(self) -> None:
        """Toggle sidebar visibility (placeholder for future sidebar)."""
        logger.debug("Sidebar toggle requested")

    @Slot()
    def _on_toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""
        if self._is_fullscreen:
            self.showNormal()
            if self._is_maximized:
                self.showMaximized()
        else:
            self._is_maximized = self.isMaximized()
            self.showFullscreen()
        self._is_fullscreen = not self._is_fullscreen

    @Slot()
    def _on_reload_models(self) -> None:
        """Reload model list from backend."""
        model_widget = self._widgets.get("model_manager")
        if model_widget and hasattr(model_widget, "refresh_models"):
            model_widget.refresh_models()

    @Slot()
    def _on_run_diagnostics(self) -> None:
        """Run system diagnostics."""
        self._switch_to_tab(3)  # Monitor tab
        monitor_widget = self._widgets.get("monitor")
        if monitor_widget and hasattr(monitor_widget, "run_diagnostics"):
            monitor_widget.run_diagnostics()

    @Slot()
    def _on_health_check(self) -> None:
        """Periodic health check."""
        # Update status bar with system info
        status_bar = self._status_bar
        if status_bar and hasattr(status_bar, "update_system_info"):
            try:
                status_bar.update_system_info()
            except Exception as e:
                logger.debug("Health check error: %s", e)

    @Slot(bool)
    def _on_connection_status_changed(self, connected: bool) -> None:
        """Handle connection status changes.

        Args:
            connected: True if connected to backend.
        """
        if self._status_bar:
            self._status_bar.set_connection_status(connected)

    @Slot()
    def _on_shutdown_requested(self) -> None:
        """Handle shutdown request."""
        self._save_geometry()

    def _switch_to_tab(self, index: int) -> None:
        """Switch to a specific tab by index.

        Args:
            index: Tab index to switch to.
        """
        if self._tab_widget and 0 <= index < self._tab_widget.count():
            self._tab_widget.setCurrentIndex(index)

    def _open_settings_dialog(self) -> None:
        """Open the settings dialog."""
        dialog = SettingsDialog(self._app, self)
        dialog.exec()

    def _open_about_dialog(self) -> None:
        """Open the about dialog."""
        dialog = AboutDialog(self)
        dialog.exec()

    # === Public Methods ===

    def apply_theme(self, theme_name: str) -> None:
        """Apply theme to the main window and all widgets.

        Args:
            theme_name: Name of the theme to apply.
        """
        self.theme_changed.emit(theme_name)

        # Update all child widgets
        for widget in self._widgets.values():
            if hasattr(widget, "apply_theme"):
                try:
                    widget.apply_theme(theme_name)
                except Exception as e:
                    logger.debug("Widget theme apply error: %s", e)

        # Update status bar
        if self._status_bar and hasattr(self._status_bar, "apply_theme"):
            try:
                self._status_bar.apply_theme(theme_name)
            except Exception as e:
                logger.debug("Status bar theme apply error: %s", e)

        logger.debug("Theme applied to main window: %s", theme_name)

    def get_widget(self, name: str) -> QWidget | None:
        """Get a specific widget by name.

        Args:
            name: Widget name key (e.g., 'dashboard', 'model_manager').

        Returns:
            The widget instance, or None if not found.
        """
        return self._widgets.get(name)

    def cleanup(self) -> None:
        """Cleanup resources before shutdown."""
        logger.info("Cleaning up main window resources")
        self._save_geometry()

        # Cleanup all widgets
        for name, widget in self._widgets.items():
            if hasattr(widget, "cleanup"):
                try:
                    widget.cleanup()
                except Exception as e:
                    logger.error("Error cleaning up %s: %s", name, e)

        # Stop timers
        if hasattr(self, "_health_timer") and self._health_timer:
            self._health_timer.stop()

    # === Event Handlers ===

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close events.

        Args:
            event: The close event.
        """
        # Check if we should minimize to tray instead of closing
        minimize_to_tray = self._app.config.get("tray.minimize_on_close", True)
        if minimize_to_tray and self._app.config.get("tray.enabled", True):
            event.ignore()
            self.hide()
            self._app.show_notification(
                "Ainos Desktop",
                "Application minimized to system tray. Double-click to restore.",
            )
        else:
            self._save_geometry()
            self._app._quit_application()
            event.accept()

    def changeEvent(self, event) -> None:
        """Handle window state changes.

        Args:
            event: The change event.
        """
        super().changeEvent(event)
        if event.type() == event.WindowStateChange:
            self._is_maximized = self.isMaximized()

    def resizeEvent(self, event) -> None:
        """Handle window resize events.

        Args:
            event: The resize event.
        """
        super().resizeEvent(event)
        # Auto-save geometry on resize (debounced)
        if hasattr(self, "_resize_timer"):
            self._resize_timer.stop()
        else:
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._save_geometry)
        self._resize_timer.start(1000)