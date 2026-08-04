#!/usr/bin/env python3
"""Ainos Desktop - Application Bootstrap.

This module provides the AinosApplication class, which extends QApplication
with theme management, system tray integration, and global configuration.
"""

import os
import sys
import logging
import signal
from typing import Any

from PySide6.QtCore import Qt, QSettings, QTimer, Signal, QObject
from PySide6.QtGui import QIcon, QPalette, QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QSystemTrayIcon,
    QMenu,
    QMessageBox,
    QStyleFactory,
)

from utils.config import ConfigManager
from theme.dark_theme import DarkTheme
from theme.light_theme import LightTheme
from window import MainWindow

logger = logging.getLogger(__name__)


class AppSignals(QObject):
    """Application-wide signals for cross-component communication."""

    theme_changed = Signal(str)
    language_changed = Signal(str)
    connection_status_changed = Signal(bool)
    settings_changed = Signal(str, object)
    shutdown_requested = Signal()


class AinosApplication(QApplication):
    """Extended QApplication with Ainos-specific functionality.

    Manages application lifecycle, themes, system tray, and global settings.
    """

    def __init__(
        self,
        argv: list[str],
        app_name: str = "Ainos Desktop",
        organization: str = "Ainos",
        organization_domain: str = "ainos.ai",
    ):
        """Initialize the application.

        Args:
            argv: Command-line arguments.
            app_name: Application display name.
            organization: Organization name for QSettings.
            organization_domain: Organization domain for QSettings.
        """
        super().__init__(argv)

        # Application metadata
        self.setApplicationName(app_name)
        self.setOrganizationName(organization)
        self.setOrganizationDomain(organization_domain)
        self.setApplicationVersion(self._get_version())

        # Global signals
        self.signals = AppSignals()

        # Configuration
        self.config = ConfigManager()

        # Theme
        self._current_theme = "dark"
        self._themes = {
            "dark": DarkTheme(),
            "light": LightTheme(),
        }

        # Main window
        self._main_window: MainWindow | None = None

        # System tray
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None

        # Auto-save timer
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._on_auto_save)
        self._auto_save_interval = self.config.get("auto_save_interval", 300000)  # 5 min
        self._auto_save_timer.start(self._auto_save_interval)

        # Application-wide settings
        self._setup_application()

        # Handle quit signals
        self.aboutToQuit.connect(self._on_about_to_quit)

        # Platform-specific setup
        self._setup_platform()

        logger.info("AinosApplication initialized")

    def _get_version(self) -> str:
        """Get the application version string.

        Returns:
            Version string from package metadata or default.
        """
        try:
            from __init__ import __version__
            return __version__
        except ImportError:
            return "0.1.0"

    def _setup_application(self) -> None:
        """Configure application-wide Qt settings."""
        # Use Fusion style for consistent cross-platform look
        self.setStyle(QStyleFactory.create("Fusion"))

        # High DPI support
        self.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            self.setAttribute(Qt.AA_EnableHighDpiScaling, True)  # type: ignore

        # Font settings
        font = self.font()
        font.setPointSize(10)
        self.setFont(font)

        # Application icon
        icon = self._create_default_icon()
        self.setWindowIcon(icon)

    def _setup_platform(self) -> None:
        """Platform-specific setup."""
        if sys.platform == "win32":
            # Windows: Set taskbar icon
            try:
                import ctypes
                myappid = f"ainos.desktop.{self.applicationVersion()}"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)  # type: ignore
            except (ImportError, AttributeError, OSError):
                pass
        elif sys.platform == "darwin":
            # macOS: Set native menu bar
            self.setAttribute(Qt.AA_DontShowIconsInMenus, False)

    def _create_default_icon(self) -> QIcon:
        """Create a default application icon programmatically.

        Returns:
            A QIcon instance. Falls back to empty icon if creation fails.
        """
        icon = QIcon()
        try:
            # Try to load from resources
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.darkBlue)
            icon.addPixmap(pixmap)
        except Exception as e:
            logger.warning("Could not create default icon: %s", e)
        return icon

    def run(self) -> int:
        """Run the application.

        Creates and shows the main window, then enters the event loop.

        Returns:
            Exit code from the event loop.
        """
        # Create main window
        self._main_window = MainWindow(self)
        self._main_window.show()

        # Setup system tray
        if self.config.get("tray.enabled", True):
            self._setup_system_tray()

        # Apply theme
        self.apply_theme(self._current_theme)

        # Handle minimize to tray
        if self.config.get("window.minimized", False):
            QTimer.singleShot(100, self._main_window.hide)

        logger.info("Application event loop started")

        # Enter event loop
        return self.exec()

    def _setup_system_tray(self) -> None:
        """Initialize the system tray icon with context menu."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this platform")
            return

        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip("Ainos Desktop")

        # Create tray menu
        self._tray_menu = QMenu()

        show_action = QAction("Show Window", self._tray_menu)
        show_action.triggered.connect(self._show_main_window)
        self._tray_menu.addAction(show_action)

        hide_action = QAction("Hide Window", self._tray_menu)
        hide_action.triggered.connect(self._hide_main_window)
        self._tray_menu.addAction(hide_action)

        self._tray_menu.addSeparator()

        # Theme submenu
        theme_menu = self._tray_menu.addMenu("Theme")
        dark_action = QAction("Dark", theme_menu)
        dark_action.triggered.connect(lambda: self.apply_theme("dark"))
        theme_menu.addAction(dark_action)

        light_action = QAction("Light", theme_menu)
        light_action.triggered.connect(lambda: self.apply_theme("light"))
        theme_menu.addAction(light_action)

        self._tray_menu.addSeparator()

        quit_action = QAction("Quit", self._tray_menu)
        quit_action.triggered.connect(self._quit_application)
        self._tray_menu.addAction(quit_action)

        self._tray_icon.setContextMenu(self._tray_menu)

        # Tray icon signals
        self._tray_icon.activated.connect(self._on_tray_activated)

        self._tray_icon.show()
        logger.info("System tray icon initialized")

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle system tray icon activation.

        Args:
            reason: The activation reason (click, double-click, etc.).
        """
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_main_window()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click: toggle visibility
            if self._main_window and self._main_window.isVisible():
                self._main_window.raise_()
                self._main_window.activateWindow()
            else:
                self._show_main_window()

    def _show_main_window(self) -> None:
        """Show and bring the main window to front."""
        if self._main_window:
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()

    def _hide_main_window(self) -> None:
        """Hide the main window to system tray."""
        if self._main_window:
            self._main_window.hide()

    def _on_about_to_quit(self) -> None:
        """Cleanup handler triggered before application exit."""
        logger.info("Application shutting down...")

        # Save configuration
        self.config.save()

        # Cleanup main window
        if self._main_window:
            self._main_window.cleanup()

        # Remove tray icon
        if self._tray_icon:
            self._tray_icon.hide()
            self._tray_icon = None

        logger.info("Shutdown complete")

    def _on_auto_save(self) -> None:
        """Periodic auto-save of configuration."""
        try:
            self.config.save()
            logger.debug("Auto-save completed")
        except Exception as e:
            logger.error("Auto-save failed: %s", e)

    def _quit_application(self) -> None:
        """Gracefully quit the application."""
        self.signals.shutdown_requested.emit()

        if self._main_window:
            self._main_window.close()

        self.quit()

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme to the application.

        Args:
            theme_name: Name of the theme ('dark' or 'light').
        """
        if theme_name not in self._themes:
            logger.warning("Unknown theme: %s. Falling back to 'dark'", theme_name)
            theme_name = "dark"

        theme = self._themes[theme_name]
        self._current_theme = theme_name

        # Apply stylesheet
        self.setStyleSheet(theme.stylesheet())

        # Apply palette
        self.setPalette(theme.palette())

        # Update main window
        if self._main_window:
            self._main_window.apply_theme(theme_name)

        # Emit signal
        self.signals.theme_changed.emit(theme_name)

        # Update tray tooltip
        if self._tray_icon:
            self._tray_icon.setToolTip(f"Ainos Desktop ({theme_name.title()} Theme)")

        self.config.set("theme", theme_name, save=True)
        logger.info("Theme applied: %s", theme_name)

    def get_theme(self) -> str:
        """Get the current theme name.

        Returns:
            Current theme name.
        """
        return self._current_theme

    def show_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration: int = 5000,
    ) -> None:
        """Show a system tray notification.

        Args:
            title: Notification title.
            message: Notification body text.
            icon: Notification icon type.
            duration: Display duration in milliseconds.
        """
        if self._tray_icon and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, icon, duration)

    def show_error_dialog(self, title: str, message: str, details: str = "") -> None:
        """Show a modal error dialog.

        Args:
            title: Dialog title.
            message: Error message.
            details: Optional detailed error information.
        """
        msg_box = QMessageBox(self._main_window)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        if details:
            msg_box.setDetailedText(details)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def show_info_dialog(self, title: str, message: str) -> None:
        """Show a modal information dialog.

        Args:
            title: Dialog title.
            message: Information message.
        """
        QMessageBox.information(self._main_window, title, message)

    def show_confirm_dialog(
        self,
        title: str,
        message: str,
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
    ) -> bool:
        """Show a confirmation dialog.

        Args:
            title: Dialog title.
            message: Confirmation message.
            confirm_text: Text for the confirm button.
            cancel_text: Text for the cancel button.

        Returns:
            True if confirmed, False otherwise.
        """
        msg_box = QMessageBox(self._main_window)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        confirm_btn = msg_box.addButton(confirm_text, QMessageBox.ButtonRole.YesRole)
        msg_box.addButton(cancel_text, QMessageBox.ButtonRole.NoRole)
        msg_box.setDefaultButton(confirm_btn)
        msg_box.exec()
        return msg_box.clickedButton() == confirm_btn

    @property
    def main_window(self) -> MainWindow | None:
        """Get the main window instance.

        Returns:
            The MainWindow instance, or None if not yet created.
        """
        return self._main_window

    @property
    def current_theme(self) -> str:
        """Get the current theme name.

        Returns:
            Current theme name.
        """
        return self._current_theme