#!/usr/bin/env python3
"""Ainos Desktop - Dark Theme.

Provides a modern dark color palette and QSS stylesheet
for the dark theme mode of the application.
"""

from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt


class DarkTheme:
    """Dark theme definition with palette and stylesheet.

    Provides a consistent dark appearance across all UI components
    using a carefully chosen color palette.
    """

    # Color palette
    COLORS = {
        # Background colors
        "bg_primary": "#1E1E2E",
        "bg_secondary": "#181825",
        "bg_tertiary": "#11111B",
        "bg_card": "#252540",
        "bg_input": "#2A2A45",
        "bg_hover": "#313150",
        "bg_selected": "#3A3A60",
        "bg_tooltip": "#2D2D4A",

        # Text colors
        "text_primary": "#CDD6F4",
        "text_secondary": "#A0A8C0",
        "text_muted": "#6C7086",
        "text_accent": "#89B4FA",
        "text_disabled": "#585B70",

        # Accent colors
        "accent_blue": "#89B4FA",
        "accent_cyan": "#89DCEB",
        "accent_green": "#A6E3A1",
        "accent_yellow": "#F9E2AF",
        "accent_orange": "#FAB387",
        "accent_red": "#F38BA8",
        "accent_purple": "#CBA6F7",
        "accent_teal": "#94E2D5",

        # Border colors
        "border_primary": "#45475A",
        "border_secondary": "#313244",
        "border_focus": "#89B4FA",

        # Status colors
        "success": "#A6E3A1",
        "warning": "#FAB387",
        "error": "#F38BA8",
        "info": "#89B4FA",

        # Scrollbar colors
        "scrollbar_bg": "#1E1E2E",
        "scrollbar_fg": "#45475A",
        "scrollbar_hover": "#585B70",

        # Chart colors
        "chart_line_1": "#89B4FA",
        "chart_line_2": "#A6E3A1",
        "chart_line_3": "#FAB387",
        "chart_line_4": "#CBA6F7",
        "chart_line_5": "#F38BA8",
        "chart_fill_1": "#1A3A5C",
        "chart_fill_2": "#1A3C2A",
        "chart_fill_3": "#3C2A1A",
        "chart_grid": "#313244",
        "chart_bg": "#1E1E2E",
    }

    def palette(self) -> QPalette:
        """Create a QPalette for the dark theme.

        Returns:
            Configured dark QPalette.
        """
        p = QPalette()

        # Window
        p.setColor(QPalette.ColorRole.Window, QColor(self.COLORS["bg_primary"]))
        p.setColor(QPalette.ColorRole.WindowText, QColor(self.COLORS["text_primary"]))

        # Base/Text
        p.setColor(QPalette.ColorRole.Base, QColor(self.COLORS["bg_secondary"]))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor(self.COLORS["bg_tertiary"]))
        p.setColor(QPalette.ColorRole.Text, QColor(self.COLORS["text_primary"]))

        # Buttons
        p.setColor(QPalette.ColorRole.Button, QColor(self.COLORS["bg_card"]))
        p.setColor(QPalette.ColorRole.ButtonText, QColor(self.COLORS["text_primary"]))

        # Bright text
        p.setColor(QPalette.ColorRole.BrightText, QColor(self.COLORS["accent_red"]))

        # Links
        p.setColor(QPalette.ColorRole.Link, QColor(self.COLORS["accent_blue"]))
        p.setColor(QPalette.ColorRole.LinkVisited, QColor(self.COLORS["accent_purple"]))

        # Highlight
        p.setColor(QPalette.ColorRole.Highlight, QColor(self.COLORS["accent_blue"]))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(self.COLORS["bg_primary"]))

        # Disabled
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText,
                   QColor(self.COLORS["text_disabled"]))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                   QColor(self.COLORS["text_disabled"]))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
                   QColor(self.COLORS["text_disabled"]))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight,
                   QColor(self.COLORS["bg_hover"]))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText,
                   QColor(self.COLORS["text_disabled"]))

        # Tooltip
        p.setColor(QPalette.ColorRole.ToolTipBase, QColor(self.COLORS["bg_tooltip"]))
        p.setColor(QPalette.ColorRole.ToolTipText, QColor(self.COLORS["text_primary"]))

        # Placeholder text
        p.setColor(QPalette.ColorRole.PlaceholderText, QColor(self.COLORS["text_muted"]))

        return p

    def stylesheet(self) -> str:
        """Generate the QSS stylesheet for the dark theme.

        Returns:
            Complete QSS stylesheet string.
        """
        c = self.COLORS
        return f"""
        /* ===== Global ===== */
        QWidget {{
            background-color: {c['bg_primary']};
            color: {c['text_primary']};
            font-family: 'Segoe UI', 'SF Pro Display', 'Ubuntu', sans-serif;
            font-size: 10pt;
        }}

        QMainWindow {{
            background-color: {c['bg_primary']};
        }}

        /* ===== Labels ===== */
        QLabel {{
            color: {c['text_primary']};
            background: transparent;
            border: none;
            padding: 2px;
        }}

        QLabel[heading="true"] {{
            font-size: 16pt;
            font-weight: bold;
            color: {c['text_primary']};
            padding: 8px 4px;
        }}

        QLabel[subheading="true"] {{
            font-size: 12pt;
            font-weight: 600;
            color: {c['text_secondary']};
            padding: 4px 4px;
        }}

        QLabel[status="success"] {{
            color: {c['success']};
        }}

        QLabel[status="warning"] {{
            color: {c['warning']};
        }}

        QLabel[status="error"] {{
            color: {c['error']};
        }}

        QLabel[status="info"] {{
            color: {c['info']};
        }}

        /* ===== Push Buttons ===== */
        QPushButton {{
            background-color: {c['bg_card']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 6px;
            padding: 8px 20px;
            font-size: 10pt;
            font-weight: 500;
            min-height: 20px;
        }}

        QPushButton:hover {{
            background-color: {c['bg_hover']};
            border-color: {c['border_focus']};
        }}

        QPushButton:pressed {{
            background-color: {c['bg_selected']};
        }}

        QPushButton:disabled {{
            background-color: {c['bg_tertiary']};
            color: {c['text_disabled']};
            border-color: {c['border_secondary']};
        }}

        QPushButton:focus {{
            border-color: {c['border_focus']};
        }}

        QPushButton[primary="true"] {{
            background-color: {c['accent_blue']};
            color: {c['bg_primary']};
            border: none;
            font-weight: 600;
        }}

        QPushButton[primary="true"]:hover {{
            background-color: #7AA8F0;
        }}

        QPushButton[primary="true"]:pressed {{
            background-color: #6A98E0;
        }}

        QPushButton[danger="true"] {{
            background-color: {c['accent_red']};
            color: {c['bg_primary']};
            border: none;
        }}

        QPushButton[danger="true"]:hover {{
            background-color: #E07A90;
        }}

        /* ===== Line Edit ===== */
        QLineEdit {{
            background-color: {c['bg_input']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 10pt;
            selection-background-color: {c['accent_blue']};
            selection-color: {c['bg_primary']};
        }}

        QLineEdit:focus {{
            border-color: {c['border_focus']};
        }}

        QLineEdit:disabled {{
            background-color: {c['bg_tertiary']};
            color: {c['text_disabled']};
        }}

        QLineEdit[readOnly="true"] {{
            background-color: {c['bg_tertiary']};
        }}

        /* ===== Text Edit ===== */
        QTextEdit, QPlainTextEdit {{
            background-color: {c['bg_input']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 6px;
            padding: 8px;
            font-family: 'Consolas', 'SF Mono', 'Fira Code', monospace;
            font-size: 10pt;
            selection-background-color: {c['accent_blue']};
            selection-color: {c['bg_primary']};
        }}

        QTextEdit:focus, QPlainTextEdit:focus {{
            border-color: {c['border_focus']};
        }}

        /* ===== Combo Box ===== */
        QComboBox {{
            background-color: {c['bg_input']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 10pt;
            min-width: 100px;
        }}

        QComboBox:hover {{
            border-color: {c['border_focus']};
        }}

        QComboBox::drop-down {{
            border: none;
            width: 30px;
        }}

        QComboBox::down-arrow {{
            image: none;
            border: solid {c['text_secondary']};
            border-width: 0 2px 2px 0;
            padding: 3px;
            transform: rotate(45deg);
        }}

        QComboBox QAbstractItemView {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 4px;
            selection-background-color: {c['accent_blue']};
            selection-color: {c['bg_primary']};
            outline: none;
        }}

        /* ===== Spin Box ===== */
        QSpinBox, QDoubleSpinBox {{
            background-color: {c['bg_input']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 10pt;
        }}

        QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {c['border_focus']};
        }}

        /* ===== Check Box ===== */
        QCheckBox {{
            color: {c['text_primary']};
            spacing: 8px;
            font-size: 10pt;
        }}

        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {c['border_primary']};
            border-radius: 4px;
            background: transparent;
        }}

        QCheckBox::indicator:checked {{
            background-color: {c['accent_blue']};
            border-color: {c['accent_blue']};
        }}

        QCheckBox::indicator:hover {{
            border-color: {c['border_focus']};
        }}

        /* ===== Radio Button ===== */
        QRadioButton {{
            color: {c['text_primary']};
            spacing: 8px;
            font-size: 10pt;
        }}

        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {c['border_primary']};
            border-radius: 10px;
            background: transparent;
        }}

        QRadioButton::indicator:checked {{
            background-color: {c['accent_blue']};
            border-color: {c['accent_blue']};
        }}

        /* ===== Tab Widget ===== */
        QTabWidget::pane {{
            border: 1px solid {c['border_secondary']};
            border-top: none;
            background-color: {c['bg_primary']};
            border-radius: 0 0 8px 8px;
        }}

        QTabBar::tab {{
            background-color: {c['bg_secondary']};
            color: {c['text_secondary']};
            border: 1px solid {c['border_secondary']};
            border-bottom: none;
            padding: 10px 24px;
            font-size: 10pt;
            font-weight: 500;
            margin-right: 2px;
            border-radius: 8px 8px 0 0;
        }}

        QTabBar::tab:selected {{
            background-color: {c['bg_primary']};
            color: {c['text_accent']};
            border-bottom: 2px solid {c['accent_blue']};
        }}

        QTabBar::tab:hover:!selected {{
            background-color: {c['bg_hover']};
            color: {c['text_primary']};
        }}

        QTabBar::tab:disabled {{
            color: {c['text_disabled']};
        }}

        /* ===== Scroll Bars ===== */
        QScrollBar:vertical {{
            background-color: {c['scrollbar_bg']};
            width: 12px;
            border: none;
            border-radius: 6px;
        }}

        QScrollBar::handle:vertical {{
            background-color: {c['scrollbar_fg']};
            min-height: 30px;
            border-radius: 6px;
            margin: 2px;
        }}

        QScrollBar::handle:vertical:hover {{
            background-color: {c['scrollbar_hover']};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
            border: none;
        }}

        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}

        QScrollBar:horizontal {{
            background-color: {c['scrollbar_bg']};
            height: 12px;
            border: none;
            border-radius: 6px;
        }}

        QScrollBar::handle:horizontal {{
            background-color: {c['scrollbar_fg']};
            min-width: 30px;
            border-radius: 6px;
            margin: 2px;
        }}

        QScrollBar::handle:horizontal:hover {{
            background-color: {c['scrollbar_hover']};
        }}

        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
            border: none;
        }}

        /* ===== List View / Tree View ===== */
        QListView, QTreeView, QTableView {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 6px;
            selection-background-color: {c['accent_blue']};
            selection-color: {c['bg_primary']};
            alternate-background-color: {c['bg_tertiary']};
            font-size: 10pt;
        }}

        QListView::item, QTreeView::item, QTableView::item {{
            padding: 6px 10px;
            border: none;
        }}

        QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{
            background-color: {c['bg_hover']};
        }}

        QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {{
            background-color: {c['accent_blue']};
            color: {c['bg_primary']};
        }}

        QHeaderView::section {{
            background-color: {c['bg_card']};
            color: {c['text_secondary']};
            border: none;
            border-bottom: 1px solid {c['border_primary']};
            padding: 8px 12px;
            font-weight: 600;
            font-size: 9pt;
        }}

        QHeaderView::section:hover {{
            background-color: {c['bg_hover']};
        }}

        /* ===== Menu Bar ===== */
        QMenuBar {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border-bottom: 1px solid {c['border_secondary']};
            padding: 2px;
        }}

        QMenuBar::item {{
            padding: 6px 12px;
            border-radius: 4px;
        }}

        QMenuBar::item:selected {{
            background-color: {c['accent_blue']};
            color: {c['bg_primary']};
        }}

        QMenu {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 8px;
            padding: 6px;
        }}

        QMenu::item {{
            padding: 8px 32px 8px 16px;
            border-radius: 4px;
        }}

        QMenu::item:selected {{
            background-color: {c['accent_blue']};
            color: {c['bg_primary']};
        }}

        QMenu::separator {{
            height: 1px;
            background-color: {c['border_primary']};
            margin: 4px 8px;
        }}

        QMenu::indicator {{
            width: 16px;
            height: 16px;
        }}

        /* ===== Status Bar ===== */
        QStatusBar {{
            background-color: {c['bg_secondary']};
            color: {c['text_secondary']};
            border-top: 1px solid {c['border_secondary']};
            font-size: 9pt;
            padding: 2px 8px;
        }}

        QStatusBar::item {{
            border: none;
        }}

        /* ===== Tool Bar ===== */
        QToolBar {{
            background-color: {c['bg_secondary']};
            border: none;
            border-bottom: 1px solid {c['border_secondary']};
            padding: 4px;
            spacing: 4px;
        }}

        QToolButton {{
            background-color: transparent;
            color: {c['text_secondary']};
            border: none;
            border-radius: 4px;
            padding: 6px 10px;
        }}

        QToolButton:hover {{
            background-color: {c['bg_hover']};
            color: {c['text_primary']};
        }}

        QToolButton:pressed {{
            background-color: {c['bg_selected']};
        }}

        /* ===== Progress Bar ===== */
        QProgressBar {{
            background-color: {c['bg_input']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 4px;
            text-align: center;
            font-size: 9pt;
            height: 20px;
        }}

        QProgressBar::chunk {{
            background-color: {c['accent_blue']};
            border-radius: 3px;
        }}

        /* ===== Group Box ===== */
        QGroupBox {{
            background-color: {c['bg_card']};
            border: 1px solid {c['border_primary']};
            border-radius: 8px;
            margin-top: 16px;
            padding: 16px 12px 12px 12px;
            font-size: 10pt;
            font-weight: 600;
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 4px 12px;
            color: {c['text_accent']};
        }}

        /* ===== Splitter ===== */
        QSplitter::handle {{
            background-color: {c['border_secondary']};
            width: 2px;
            height: 2px;
        }}

        QSplitter::handle:hover {{
            background-color: {c['accent_blue']};
        }}

        /* ===== Tool Tip ===== */
        QToolTip {{
            background-color: {c['bg_tooltip']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 4px;
            padding: 6px 10px;
            font-size: 9pt;
        }}

        /* ===== Frame ===== */
        QFrame[frameShape="4"], QFrame[frameShape="5"] {{
            background-color: transparent;
            border: none;
        }}

        QFrame[card="true"] {{
            background-color: {c['bg_card']};
            border: 1px solid {c['border_primary']};
            border-radius: 8px;
            padding: 12px;
        }}

        /* ===== Dialog ===== */
        QDialog {{
            background-color: {c['bg_primary']};
        }}

        /* ===== Slider ===== */
        QSlider::groove:horizontal {{
            background-color: {c['bg_input']};
            height: 6px;
            border-radius: 3px;
        }}

        QSlider::handle:horizontal {{
            background-color: {c['accent_blue']};
            width: 18px;
            height: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }}

        QSlider::handle:horizontal:hover {{
            background-color: #7AA8F0;
        }}

        QSlider::sub-page:horizontal {{
            background-color: {c['accent_blue']};
            border-radius: 3px;
        }}

        /* ===== Table ===== */
        QTableWidget {{
            background-color: {c['bg_secondary']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 6px;
            gridline-color: {c['border_secondary']};
            font-size: 10pt;
        }}

        QTableWidget::item {{
            padding: 6px 10px;
        }}

        QTableWidget::item:selected {{
            background-color: {c['accent_blue']};
            color: {c['bg_primary']};
        }}

        /* ===== Scroll Area ===== */
        QScrollArea {{
            border: none;
            background: transparent;
        }}

        /* ===== Dock Widget ===== */
        QDockWidget {{
            background-color: {c['bg_primary']};
            color: {c['text_primary']};
            border: 1px solid {c['border_primary']};
            border-radius: 4px;
            titlebar-close-icon: none;
        }}

        QDockWidget::title {{
            background-color: {c['bg_card']};
            padding: 6px 12px;
            border-bottom: 1px solid {c['border_secondary']};
        }}

        /* ===== Misc ===== */
        QDialogButtonBox QPushButton {{
            min-width: 80px;
        }}

        QStackedWidget {{
            background: transparent;
            border: none;
        }}
        """