"""
Translation Compilation Tool
=============================

Compiles translation source files into optimized formats for runtime use.

Supports:
* Compiling JSON translation files into a single merged bundle per locale
* Compiling to MO (gettext machine object) format
* Compiling to Python module format for fast import
* Minification and optimization
"""

from __future__ import annotations

import os
import json
import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CompilationTool:
    """Compile translation files into optimized formats.

    Parameters
    ----------
    source_dir : str
        Directory containing locale translation files.
    output_dir : str
        Directory for compiled output.
    """

    def __init__(self, source_dir: str, output_dir: str) -> None:
        self._source_dir = source_dir
        self._output_dir = output_dir

    # ---- Compilation methods ----

    def compile_to_json_bundle(self, locale: str) -> dict[str, Any]:
        """Compile all JSON files for a locale into a single merged bundle.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        dict[str, Any]
            Merged translation data.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._source_dir)
        data = loader.load(locale)

        # Write merged bundle
        output_path = os.path.join(self._output_dir, f"{locale}.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("Compiled JSON bundle for '%s' -> %s (%d keys)", locale, output_path, self._count_keys(data))
        return data

    def compile_all_json_bundles(self) -> list[str]:
        """Compile all available locales into JSON bundles.

        Returns
        -------
        list[str]
            List of compiled locale codes.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._source_dir)
        locales = loader.get_available_locales()

        compiled: list[str] = []
        for locale in locales:
            try:
                self.compile_to_json_bundle(locale)
                compiled.append(locale)
            except Exception as exc:
                logger.error("Failed to compile locale '%s': %s", locale, exc)

        logger.info("Compiled %d/%d locales to JSON bundles", len(compiled), len(locales))
        return compiled

    def compile_to_python_module(self, locale: str) -> str:
        """Compile translations for a locale into a Python module.

        The resulting module can be imported directly without parsing JSON.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        str
            Path to the generated Python file.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._source_dir)
        data = loader.load(locale)

        # Generate Python module
        module_path = os.path.join(self._output_dir, f"{locale.replace('-', '_')}.py")
        os.makedirs(os.path.dirname(module_path), exist_ok=True)

        with open(module_path, "w", encoding="utf-8") as f:
            f.write('"""Auto-generated translation module for locale: %s"""\n\n' % locale)
            f.write(f'LOCALE = {locale!r}\n\n')
            f.write("TRANSLATIONS = ")
            # Pretty-print with indentation
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            # Convert JSON to Python dict literal
            py_str = self._json_to_python_dict(data)
            f.write(py_str)
            f.write("\n\n")

            # Add helper functions
            f.write("""
def get(key: str, default: str | None = None) -> str | None:
    \"\"\"Get a translation by dot-separated key.\"\"\"
    parts = key.split(".")
    current = TRANSLATIONS
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
            if current is None:
                return default
        else:
            return default
    return str(current) if current is not None else default


def get_all() -> dict:
    \"\"\"Get all translations.\"\"\"
    return dict(TRANSLATIONS)
""")
            f.write(f"\n\n__all__ = ['LOCALE', 'TRANSLATIONS', 'get', 'get_all']\n")

        logger.info("Compiled Python module for '%s' -> %s", locale, module_path)
        return module_path

    def compile_to_minified_json(self, locale: str) -> str:
        """Compile translations to a minified JSON file.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        str
            Path to the minified JSON file.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._source_dir)
        data = loader.load(locale)

        output_path = os.path.join(self._output_dir, f"{locale}.min.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

        original_size = len(json.dumps(data, ensure_ascii=False, indent=2))
        minified_size = os.path.getsize(output_path)
        savings = (1 - minified_size / original_size) * 100 if original_size > 0 else 0

        logger.info(
            "Minified JSON for '%s': %s (%d -> %d bytes, %.1f%% savings)",
            locale, output_path, original_size, minified_size, savings,
        )
        return output_path

    def compile_all(self) -> dict[str, list[str]]:
        """Compile all locales into all available formats.

        Returns
        -------
        dict[str, list[str]]
            Mapping of locale -> list of output file paths.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._source_dir)
        locales = loader.get_available_locales()

        results: dict[str, list[str]] = {}
        for locale in locales:
            outputs: list[str] = []
            try:
                path = self.compile_to_json_bundle(locale)
                outputs.append(path)
            except Exception as exc:
                logger.error("JSON bundle compile failed for %s: %s", locale, exc)

            try:
                path = self.compile_to_minified_json(locale)
                outputs.append(path)
            except Exception as exc:
                logger.error("Minified JSON compile failed for %s: %s", locale, exc)

            try:
                path = self.compile_to_python_module(locale)
                outputs.append(path)
            except Exception as exc:
                logger.error("Python module compile failed for %s: %s", locale, exc)

            results[locale] = outputs

        return results

    def generate_manifest(self) -> str:
        """Generate a manifest file listing all compiled translations.

        Returns
        -------
        str
            Path to the manifest file.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._source_dir)
        locales = loader.get_available_locales()

        manifest: dict[str, Any] = {
            "generated_at": self._get_timestamp(),
            "locales": {},
        }

        for locale in locales:
            data = loader.load(locale)
            key_count = self._count_keys(data)
            content_hash = hashlib.md5(
                json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()

            manifest["locales"][locale] = {
                "key_count": key_count,
                "hash": content_hash,
                "files": [
                    f"{locale}.json",
                    f"{locale}.min.json",
                ],
            }

        manifest_path = os.path.join(self._output_dir, "manifest.json")
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        logger.info("Manifest generated: %s", manifest_path)
        return manifest_path

    # ---- Internal helpers ----

    @staticmethod
    def _count_keys(data: dict[str, Any], prefix: str = "") -> int:
        """Recursively count leaf keys."""
        count = 0
        for k, v in data.items():
            if isinstance(v, dict):
                count += CompilationTool._count_keys(v, f"{prefix}{k}.")
            else:
                count += 1
        return count

    @staticmethod
    def _json_to_python_dict(data: dict[str, Any], indent: int = 0) -> str:
        """Convert a JSON-compatible dict to a Python dict literal."""
        if not data:
            return "{}"

        spaces = "    " * (indent + 1)
        result = "{\n"
        for key, value in data.items():
            # Format key
            if isinstance(key, str):
                k_repr = repr(key)
            else:
                k_repr = str(key)

            # Format value
            if isinstance(value, dict):
                v_repr = CompilationTool._json_to_python_dict(value, indent + 1)
            elif isinstance(value, str):
                v_repr = repr(value)
            elif isinstance(value, bool):
                v_repr = "True" if value else "False"
            elif value is None:
                v_repr = "None"
            elif isinstance(value, (int, float)):
                v_repr = str(value)
            elif isinstance(value, list):
                v_repr = json.dumps(value, ensure_ascii=False)
            else:
                v_repr = repr(value)

            result += f"{spaces}{k_repr}: {v_repr},\n"

        result += "    " * indent + "}"
        return result

    @staticmethod
    def _get_timestamp() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self) -> str:
        return (
            f"CompilationTool(source_dir={self._source_dir!r}, "
            f"output_dir={self._output_dir!r})"
        )