"""
JSON Loader
===========

Loads translation data from JSON files.

Directory structure::

    <source_dir>/
    ├── zh_CN/
    │   ├── messages.json
    │   ├── errors.json
    │   └── inference.json
    ├── en_US/
    │   ├── messages.json
    │   ├── errors.json
    │   └── inference.json
    └── ...

Files are merged into a single namespace per locale.
"""

from __future__ import annotations

import json
import os
import glob
import logging
from typing import Any

from ainos_i18n.loaders.base import Loader, LoaderError, LoaderNotFoundError, LoaderParseError

logger = logging.getLogger(__name__)


class JSONLoader(Loader):
    """Load translation data from JSON files.

    Parameters
    ----------
    source_dir : str, optional
        Base directory containing locale subdirectories.
        If None, uses a default path relative to the package.
    encoding : str, optional
        File encoding. Defaults to ``"utf-8"``.
    merge_strategy : str, optional
        How to merge multiple files for the same locale:
        - ``"deep"``: deep merge (default)
        - ``"shallow"``: shallow merge (later files overwrite)
    """

    def __init__(
        self,
        source_dir: str | None = None,
        encoding: str = "utf-8",
        merge_strategy: str = "deep",
    ) -> None:
        super().__init__(source_dir or self._default_source_dir())
        self._encoding = encoding
        self._merge_strategy = merge_strategy
        self._cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _default_source_dir() -> str:
        """Get the default locale directory relative to the package."""
        # Walk up to find the package root
        try:
            from ainos_i18n import __file__ as package_file
            base = os.path.dirname(os.path.dirname(os.path.abspath(package_file)))
            return os.path.join(base, "locales")
        except ImportError:
            # Fallback
            return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "locales"))

    # ---- Loader API ----

    def load(self, locale: str) -> dict[str, Any]:
        """Load translation data for a locale from JSON files.

        Parameters
        ----------
        locale : str
            Locale code, e.g. ``"zh_CN"``.

        Returns
        -------
        dict[str, Any]
            Merged translation data from all JSON files in the locale directory.
        """
        # Check cache first
        if locale in self._cache:
            logger.debug("Cache hit for locale: %s", locale)
            return dict(self._cache[locale])

        locale_dir = os.path.join(self._source_dir, locale) if self._source_dir else ""

        if not locale_dir or not os.path.isdir(locale_dir):
            logger.warning("Locale directory not found: %s", locale_dir)
            # Try alternate path
            locale_dir = self._find_locale_dir(locale)
            if not locale_dir:
                return {}

        # Find all JSON files
        json_files = sorted(glob.glob(os.path.join(locale_dir, "*.json")))
        if not json_files:
            logger.warning("No JSON files found in locale directory: %s", locale_dir)
            return {}

        # Load and merge
        merged: dict[str, Any] = {}
        for file_path in json_files:
            try:
                data = self._load_file(file_path)
                if self._merge_strategy == "deep":
                    merged = self._deep_merge(merged, data)
                else:
                    merged.update(data)
                logger.debug("Loaded: %s (%d keys)", file_path, len(data))
            except LoaderError:
                raise
            except Exception as exc:
                raise LoaderError(f"Failed to load {file_path}: {exc}", cause=exc) from exc

        # Cache the result
        self._cache[locale] = dict(merged)
        logger.info("Loaded %d top-level keys for locale '%s' from %d files", len(merged), locale, len(json_files))
        return merged

    def load_file(self, locale: str, filename: str) -> dict[str, Any]:
        """Load a specific translation file for a locale.

        Parameters
        ----------
        locale : str
            Locale code.
        filename : str
            JSON filename (e.g. ``"messages.json"``).

        Returns
        -------
        dict[str, Any]
        """
        locale_dir = os.path.join(self._source_dir, locale) if self._source_dir else ""
        if not locale_dir or not os.path.isdir(locale_dir):
            locale_dir = self._find_locale_dir(locale)
            if not locale_dir:
                return {}

        file_path = os.path.join(locale_dir, filename)
        if not os.path.isfile(file_path):
            return {}

        return self._load_file(file_path)

    def get_available_locales(self) -> list[str]:
        """Get list of locales that have JSON translation files.

        Returns
        -------
        list[str]
        """
        if not self._source_dir or not os.path.isdir(self._source_dir):
            return []

        locales: list[str] = []
        for entry in sorted(os.listdir(self._source_dir)):
            dir_path = os.path.join(self._source_dir, entry)
            if os.path.isdir(dir_path):
                # Check for JSON files
                if glob.glob(os.path.join(dir_path, "*.json")):
                    locales.append(entry)
        return locales

    def clear_cache(self) -> None:
        """Clear the internal translation cache."""
        self._cache.clear()
        logger.debug("JSONLoader cache cleared")

    def reload(self, locale: str | None = None) -> None:
        """Reload translations, optionally for a specific locale.

        Parameters
        ----------
        locale : str, optional
            If None, clear entire cache.
        """
        if locale:
            self._cache.pop(locale, None)
        else:
            self._cache.clear()

    # ---- Internal helpers ----

    def _load_file(self, file_path: str) -> dict[str, Any]:
        """Load and parse a single JSON file.

        Parameters
        ----------
        file_path : str
            Path to JSON file.

        Returns
        -------
        dict[str, Any]

        Raises
        ------
        LoaderNotFoundError
            If the file doesn't exist.
        LoaderParseError
            If the file contains invalid JSON.
        """
        if not os.path.isfile(file_path):
            raise LoaderNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding=self._encoding) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise LoaderParseError(f"Expected JSON object in {file_path}, got {type(data).__name__}")
            return data
        except json.JSONDecodeError as exc:
            raise LoaderParseError(f"Invalid JSON in {file_path}: {exc}", cause=exc) from exc
        except (OSError, IOError) as exc:
            raise LoaderNotFoundError(f"Error reading {file_path}: {exc}", cause=exc) from exc

    def _find_locale_dir(self, locale: str) -> str | None:
        """Search for a locale directory in alternative locations.

        Searches:
        1. The configured source_dir
        2. Package-relative locales directory
        3. Current working directory
        """
        search_paths = [
            self._source_dir,
            os.path.join(os.path.dirname(__file__), "..", "locales"),
            os.path.join(os.getcwd(), "locales"),
            os.path.join(os.getcwd(), "i18n", "locales"),
        ]

        for base in search_paths:
            if base:
                candidate = os.path.join(base, locale)
                if os.path.isdir(candidate):
                    return candidate

        return None

    @staticmethod
    def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge overlay into base.

        Parameters
        ----------
        base : dict
            Base dictionary.
        overlay : dict
            Dictionary to merge on top.

        Returns
        -------
        dict
            Merged result.
        """
        result = dict(base)
        for key, value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = JSONLoader._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def __repr__(self) -> str:
        return (
            f"JSONLoader(source_dir={self._source_dir!r}, "
            f"encoding={self._encoding!r}, "
            f"merge_strategy={self._merge_strategy!r})"
        )