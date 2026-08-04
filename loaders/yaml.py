"""
YAML Loader
===========

Loads translation data from YAML files.

Supports the same directory structure as the JSON loader but uses
``.yaml`` / ``.yml`` files.  YAML supports anchors, aliases, and
multi-line strings which are helpful for translation files.

Requires ``PyYAML`` (``yaml`` package).
"""

from __future__ import annotations

import os
import glob
import logging
from typing import Any

from ainos_i18n.loaders.base import Loader, LoaderError, LoaderNotFoundError, LoaderParseError

logger = logging.getLogger(__name__)


class YAMLLoader(Loader):
    """Load translation data from YAML files.

    Parameters
    ----------
    source_dir : str, optional
        Base directory containing locale subdirectories.
    encoding : str, optional
        File encoding. Defaults to ``"utf-8"``.
    merge_strategy : str, optional
        How to merge multiple files: ``"deep"`` or ``"shallow"``.
    """

    def __init__(
        self,
        source_dir: str | None = None,
        encoding: str = "utf-8",
        merge_strategy: str = "deep",
    ) -> None:
        super().__init__(source_dir)
        self._encoding = encoding
        self._merge_strategy = merge_strategy
        self._cache: dict[str, dict[str, Any]] = {}
        self._yaml_available: bool | None = None

    # ---- YAML availability check ----

    def _check_yaml(self) -> bool:
        """Check if PyYAML is available."""
        if self._yaml_available is not None:
            return self._yaml_available
        try:
            import yaml  # type: ignore[import-untyped]
            self._yaml_available = True
            return True
        except ImportError:
            self._yaml_available = False
            logger.warning("PyYAML is not installed. Install with: pip install pyyaml")
            return False

    # ---- Loader API ----

    def load(self, locale: str) -> dict[str, Any]:
        """Load translation data for a locale from YAML files.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        dict[str, Any]
        """
        if not self._check_yaml():
            raise LoaderError("PyYAML is required but not installed. Install with: pip install pyyaml")

        if locale in self._cache:
            return dict(self._cache[locale])

        locale_dir = self._find_locale_dir(locale)
        if not locale_dir:
            logger.warning("Locale directory not found for: %s", locale)
            return {}

        # Find all YAML files
        yaml_files = sorted(
            glob.glob(os.path.join(locale_dir, "*.yaml")) +
            glob.glob(os.path.join(locale_dir, "*.yml"))
        )

        if not yaml_files:
            logger.warning("No YAML files found in locale directory: %s", locale_dir)
            return {}

        # Load and merge
        import yaml
        merged: dict[str, Any] = {}
        for file_path in yaml_files:
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

        self._cache[locale] = dict(merged)
        logger.info("Loaded %d top-level keys for locale '%s' from %d files", len(merged), locale, len(yaml_files))
        return merged

    def get_available_locales(self) -> list[str]:
        """Get list of locales with YAML files.

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
                files = glob.glob(os.path.join(dir_path, "*.yaml")) + glob.glob(os.path.join(dir_path, "*.yml"))
                if files:
                    locales.append(entry)
        return locales

    def clear_cache(self) -> None:
        """Clear the translation cache."""
        self._cache.clear()

    # ---- Internal helpers ----

    def _load_file(self, file_path: str) -> dict[str, Any]:
        """Load and parse a single YAML file.

        Parameters
        ----------
        file_path : str
            Path to YAML file.

        Returns
        -------
        dict[str, Any]

        Raises
        ------
        LoaderNotFoundError
            If the file doesn't exist.
        LoaderParseError
            If the file contains invalid YAML.
        """
        if not os.path.isfile(file_path):
            raise LoaderNotFoundError(f"File not found: {file_path}")

        import yaml
        try:
            with open(file_path, "r", encoding=self._encoding) as f:
                data = yaml.safe_load(f)
            if data is None:
                return {}
            if not isinstance(data, dict):
                raise LoaderParseError(f"Expected YAML mapping in {file_path}, got {type(data).__name__}")
            return data
        except yaml.YAMLError as exc:
            raise LoaderParseError(f"Invalid YAML in {file_path}: {exc}", cause=exc) from exc
        except (OSError, IOError) as exc:
            raise LoaderNotFoundError(f"Error reading {file_path}: {exc}", cause=exc) from exc

    def _find_locale_dir(self, locale: str) -> str | None:
        """Search for a locale directory."""
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
        """Recursively merge overlay into base."""
        result = dict(base)
        for key, value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = YAMLLoader._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def __repr__(self) -> str:
        return (
            f"YAMLLoader(source_dir={self._source_dir!r}, "
            f"encoding={self._encoding!r})"
        )