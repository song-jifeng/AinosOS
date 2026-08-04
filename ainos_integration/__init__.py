"""
AinosOS Integration Package
============================

Integration modules for internationalizing AinosOS components:

* ``shell.py`` -- AI Shell
* ``desktop.py`` -- Desktop GUI
* ``web.py`` -- Web Panel
* ``cli.py`` -- CLI Tools
"""

from ainos_i18n.ainos_integration.shell import ShellI18n
from ainos_i18n.ainos_integration.desktop import DesktopI18n
from ainos_i18n.ainos_integration.web import WebI18n
from ainos_i18n.ainos_integration.cli import CLI18n

__all__ = [
    "ShellI18n",
    "DesktopI18n",
    "WebI18n",
    "CLI18n",
]