"""
Loader package
"""

from ainos_i18n.loaders.base import Loader, LoaderError
from ainos_i18n.loaders.json import JSONLoader
from ainos_i18n.loaders.yaml import YAMLLoader
from ainos_i18n.loaders.gettext import GettextLoader
from ainos_i18n.loaders.database import DatabaseLoader

__all__ = [
    "Loader",
    "LoaderError",
    "JSONLoader",
    "YAMLLoader",
    "GettextLoader",
    "DatabaseLoader",
]