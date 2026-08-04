"""
Loader Base Class
==================

Abstract base class for all translation data loaders.

A loader is responsible for loading translation data from a specific
source (filesystem, database, network, etc.) and returning it as a
nested dictionary of key-value pairs.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LoaderError(Exception):
    """Base exception for loader-related errors."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class LoaderNotFoundError(LoaderError):
    """Raised when a translation source is not found."""

    pass


class LoaderParseError(LoaderError):
    """Raised when a translation source cannot be parsed."""

    pass


class Loader(abc.ABC):
    """Abstract base class for translation data loaders.

    Subclasses must implement ``load()`` to return translation data
    for a given locale.

    Parameters
    ----------
    source_dir : str, optional
        Base directory for translation files.
    """

    def __init__(self, source_dir: str | None = None) -> None:
        self._source_dir = source_dir

    @property
    def source_dir(self) -> str | None:
        """Get the source directory."""
        return self._source_dir

    @abc.abstractmethod
    def load(self, locale: str) -> dict[str, Any]:
        """Load translation data for a locale.

        Parameters
        ----------
        locale : str
            Locale code, e.g. ``"zh_CN"``.

        Returns
        -------
        dict[str, Any]
            Nested dictionary of translation key-value pairs.
            Must return an empty dict rather than raising on
            missing files (the caller handles missing data).

        Raises
        ------
        LoaderError
            On unrecoverable errors.
        """
        ...

    def load_all(self, locales: list[str]) -> dict[str, dict[str, Any]]:
        """Load translation data for multiple locales.

        Parameters
        ----------
        locales : list[str]
            List of locale codes.

        Returns
        -------
        dict[str, dict[str, Any]]
            Mapping of locale -> translation data.
        """
        result: dict[str, dict[str, Any]] = {}
        for locale in locales:
            try:
                result[locale] = self.load(locale)
            except Exception as exc:
                logger.warning("Failed to load locale '%s': %s", locale, exc)
                result[locale] = {}
        return result

    def supports_locale(self, locale: str) -> bool:
        """Check if this loader supports a given locale.

        Default implementation returns True if loading succeeds.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        bool
        """
        try:
            data = self.load(locale)
            return bool(data)
        except Exception:
            return False

    def get_available_locales(self) -> list[str]:
        """Get list of locales available through this loader.

        Returns
        -------
        list[str]
            Default returns empty list; subclasses should override.
        """
        return []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source_dir={self._source_dir!r})"