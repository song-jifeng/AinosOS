"""
Translation Sync Tool
======================

Synchronizes translations between different locales, detects missing
translations, and can auto-translate keys from a reference locale.

Features:
* Detect missing keys in target locales
* Propagate keys from reference locale
* Auto-translate using a translation service (pluggable)
* Generate translation reports
* Export/import translation data in various formats
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Type for auto-translate function
TranslateFunc = Callable[[str, str, str], str]


class SyncTool:
    """Synchronize translations between locales.

    Parameters
    ----------
    locales_dir : str
        Directory containing locale subdirectories.
    reference_locale : str, optional
        Source locale. Defaults to ``"en_US"``.
    """

    def __init__(
        self,
        locales_dir: str,
        reference_locale: str = "en_US",
    ) -> None:
        self._locales_dir = locales_dir
        self._reference_locale = reference_locale

    # ---- Detection ----

    def detect_missing_keys(self, locales: list[str] | None = None) -> dict[str, set[str]]:
        """Detect translation keys missing in target locales.

        Parameters
        ----------
        locales : list[str], optional
            Locales to check. If None, checks all locales.

        Returns
        -------
        dict[str, set[str]]
            Mapping of locale -> set of missing keys.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._locales_dir)
        reference = loader.load(self._reference_locale)
        ref_keys = self._collect_keys(reference)

        if not ref_keys:
            logger.warning("Reference locale '%s' has no keys", self._reference_locale)
            return {}

        missing: dict[str, set[str]] = {}
        target_locales = locales or self._get_locales()

        for locale in target_locales:
            if locale == self._reference_locale:
                continue
            try:
                data = loader.load(locale)
                keys = self._collect_keys(data)
                missing_keys = ref_keys - keys
                if missing_keys:
                    missing[locale] = missing_keys
            except Exception as exc:
                logger.warning("Failed to load locale '%s': %s", locale, exc)
                missing[locale] = ref_keys

        return missing

    def detect_orphaned_keys(self, locales: list[str] | None = None) -> dict[str, set[str]]:
        """Detect keys that exist in target locales but not in reference.

        Parameters
        ----------
        locales : list[str], optional
            Locales to check.

        Returns
        -------
        dict[str, set[str]]
            Mapping of locale -> set of orphaned keys.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._locales_dir)
        reference = loader.load(self._reference_locale)
        ref_keys = self._collect_keys(reference)

        orphaned: dict[str, set[str]] = {}
        target_locales = locales or self._get_locales()

        for locale in target_locales:
            if locale == self._reference_locale:
                continue
            try:
                data = loader.load(locale)
                keys = self._collect_keys(data)
                extra = keys - ref_keys
                if extra:
                    orphaned[locale] = extra
            except Exception as exc:
                logger.warning("Failed to load locale '%s': %s", locale, exc)

        return orphaned

    # ---- Synchronization ----

    def sync_from_reference(
        self,
        target_locales: list[str] | None = None,
        overwrite: bool = False,
        auto_translate: TranslateFunc | None = None,
    ) -> dict[str, int]:
        """Synchronize translations from the reference locale.

        Adds missing keys from the reference locale to target locales.

        Parameters
        ----------
        target_locales : list[str], optional
            Locales to sync. If None, syncs all.
        overwrite : bool, optional
            If True, overwrite existing translations. Default False.
        auto_translate : Callable, optional
            Function ``(text, from_locale, to_locale) -> str`` for auto-translation.

        Returns
        -------
        dict[str, int]
            Mapping of locale -> number of keys added/updated.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._locales_dir)
        reference = loader.load(self._reference_locale)

        if not reference:
            logger.warning("Reference locale '%s' is empty", self._reference_locale)
            return {}

        results: dict[str, int] = {}
        locales = target_locales or self._get_locales()

        for locale in locales:
            if locale == self._reference_locale:
                continue

            files = self._get_locale_files(locale)
            target_data: dict[str, Any] = {}
            for file_path in files:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        target_data.update(data)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Error reading %s: %s", file_path, exc)

            added = self._merge_translations(
                target_data, reference, locale, overwrite, auto_translate,
            )

            # Write back
            self._write_locale_data(locale, target_data)
            results[locale] = added
            logger.info("Synced %d keys to locale '%s'", added, locale)

        return results

    def sync_all(self, overwrite: bool = False, auto_translate: TranslateFunc | None = None) -> dict[str, int]:
        """Synchronize all locales from the reference.

        Parameters
        ----------
        overwrite : bool, optional
            If True, overwrite existing translations.
        auto_translate : Callable, optional
            Auto-translation function.

        Returns
        -------
        dict[str, int]
        """
        return self.sync_from_reference(overwrite=overwrite, auto_translate=auto_translate)

    # ---- Reporting ----

    def generate_report(self, output_file: str | None = None) -> dict[str, Any]:
        """Generate a comprehensive translation status report.

        Parameters
        ----------
        output_file : str, optional
            Path to write the report JSON.

        Returns
        -------
        dict[str, Any]
            Report data.
        """
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._locales_dir)
        locales = self._get_locales()

        report: dict[str, Any] = {
            "generated_at": self._get_timestamp(),
            "reference_locale": self._reference_locale,
            "locales": {},
            "summary": {},
        }

        total_keys = 0
        for locale in locales:
            data = loader.load(locale)
            key_count = self._count_keys(data)
            total_keys = max(total_keys, key_count)

            report["locales"][locale] = {
                "key_count": key_count,
                "completeness": 0.0,
                "missing_keys": [],
            }

        # Calculate completeness
        if total_keys > 0:
            for locale in locales:
                missing = self.detect_missing_keys([locale])
                missing_count = len(missing.get(locale, set()))
                completeness = ((total_keys - missing_count) / total_keys) * 100
                report["locales"][locale]["completeness"] = round(completeness, 1)
                report["locales"][locale]["missing_keys"] = sorted(missing.get(locale, set()))

        # Summary
        complete_count = sum(
            1 for info in report["locales"].values() if info["completeness"] == 100.0
        )
        report["summary"] = {
            "total_locales": len(locales),
            "total_keys": total_keys,
            "complete_locales": complete_count,
            "average_completeness": round(
                sum(info["completeness"] for info in report["locales"].values()) / max(len(locales), 1),
                1,
            ),
        }

        if output_file:
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info("Report written to: %s", output_file)

        return report

    # ---- Export/Import ----

    def export_to_csv(self, output_file: str) -> str:
        """Export translations to CSV format.

        Parameters
        ----------
        output_file : str
            Path to write the CSV file.

        Returns
        -------
        str
            Path to the CSV file.
        """
        import csv
        from ainos_i18n.loaders.json import JSONLoader

        loader = JSONLoader(self._locales_dir)
        locales = self._get_locales()

        # Collect all keys from reference
        reference = loader.load(self._reference_locale)
        all_keys = sorted(self._collect_keys(reference))

        # Also collect keys from other locales
        for locale in locales:
            if locale != self._reference_locale:
                data = loader.load(locale)
                all_keys = sorted(set(all_keys) | self._collect_keys(data))

        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            header = ["key"] + locales
            writer.writerow(header)

            for key in all_keys:
                row = [key]
                for locale in locales:
                    data = loader.load(locale)
                    value = self._deep_get(data, key)
                    row.append(value if isinstance(value, str) else "")
                writer.writerow(row)

        logger.info("CSV export written to: %s", output_file)
        return output_file

    def import_from_csv(self, input_file: str) -> dict[str, int]:
        """Import translations from CSV format.

        Parameters
        ----------
        input_file : str
            Path to the CSV file.

        Returns
        -------
        dict[str, int]
            Mapping of locale -> number of keys imported.
        """
        import csv

        if not os.path.isfile(input_file):
            raise FileNotFoundError(f"CSV file not found: {input_file}")

        imported: dict[str, int] = {}

        with open(input_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError("CSV file has no headers")

            locales = [h for h in reader.fieldnames if h != "key"]

            # Initialize per-locale data
            locale_data: dict[str, dict[str, str]] = {loc: {} for loc in locales}

            for row in reader:
                key = row.get("key", "")
                if not key:
                    continue
                for locale in locales:
                    value = row.get(locale, "")
                    if value:
                        locale_data[locale][key] = value

            # Write back to files
            for locale, translations in locale_data.items():
                if not translations:
                    continue
                self._add_flat_keys_to_locale(locale, translations)
                imported[locale] = len(translations)
                logger.info("Imported %d keys for locale '%s' from CSV", len(translations), locale)

        return imported

    # ---- Internal helpers ----

    def _get_locales(self) -> list[str]:
        """Get list of locale directories."""
        if not os.path.isdir(self._locales_dir):
            return []
        locales: list[str] = []
        for entry in sorted(os.listdir(self._locales_dir)):
            if os.path.isdir(os.path.join(self._locales_dir, entry)):
                locales.append(entry)
        return locales

    def _get_locale_files(self, locale: str) -> list[str]:
        """Get JSON files for a locale."""
        import glob
        locale_dir = os.path.join(self._locales_dir, locale)
        if not os.path.isdir(locale_dir):
            return []
        return sorted(glob.glob(os.path.join(locale_dir, "*.json")))

    def _merge_translations(
        self,
        target: dict[str, Any],
        reference: dict[str, Any],
        locale: str,
        overwrite: bool,
        auto_translate: TranslateFunc | None,
    ) -> int:
        """Merge reference translations into target.

        Returns the number of keys added.
        """
        added = 0
        for key, value in reference.items():
            if isinstance(value, dict):
                if key not in target:
                    target[key] = {}
                if not isinstance(target[key], dict):
                    target[key] = {}
                added += self._merge_translations(
                    target[key], value, locale, overwrite, auto_translate,
                )
            else:
                if key not in target or overwrite:
                    if auto_translate and isinstance(value, str):
                        try:
                            target[key] = auto_translate(value, self._reference_locale, locale)
                        except Exception as exc:
                            logger.warning("Auto-translate failed for '%s': %s", key, exc)
                            target[key] = value
                    else:
                        target[key] = value
                    added += 1

        return added

    def _write_locale_data(self, locale: str, data: dict[str, Any]) -> None:
        """Write translation data back to locale files.

        Distributes keys across existing files, or writes to a single file.
        """
        locale_dir = os.path.join(self._locales_dir, locale)
        os.makedirs(locale_dir, exist_ok=True)

        files = self._get_locale_files(locale)
        if not files:
            # Write to a default messages.json
            file_path = os.path.join(locale_dir, "messages.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            # Write the first file (messages.json) with full data
            file_path = files[0]
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _add_flat_keys_to_locale(self, locale: str, flat_keys: dict[str, str]) -> None:
        """Add flat dot-separated keys to a locale's translation files."""
        locale_dir = os.path.join(self._locales_dir, locale)
        os.makedirs(locale_dir, exist_ok=True)

        # Load existing data
        from ainos_i18n.loaders.json import JSONLoader
        loader = JSONLoader(self._locales_dir)
        existing = loader.load(locale)

        # Add flat keys
        for key, value in flat_keys.items():
            self._deep_set(existing, key, value)

        # Write back
        file_path = os.path.join(locale_dir, "messages.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _collect_keys(data: dict[str, Any], prefix: str = "") -> set[str]:
        """Recursively collect all dot-separated leaf keys."""
        keys: set[str] = set()
        for k, v in data.items():
            full_key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                # Check if it's a plural form dict
                if all(isinstance(sk, str) and len(sk) < 10 for sk in v):
                    keys.add(full_key)
                else:
                    keys |= SyncTool._collect_keys(v, f"{full_key}.")
            else:
                keys.add(full_key)
        return keys

    @staticmethod
    def _count_keys(data: dict[str, Any]) -> int:
        """Count leaf keys in a nested dict."""
        count = 0
        for v in data.values():
            if isinstance(v, dict):
                count += SyncTool._count_keys(v)
            else:
                count += 1
        return count

    @staticmethod
    def _deep_get(data: dict[str, Any], dot_key: str) -> Any:
        """Get a value using dot notation."""
        parts = dot_key.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current

    @staticmethod
    def _deep_set(data: dict[str, Any], dot_key: str, value: Any) -> None:
        """Set a value using dot notation."""
        parts = dot_key.split(".")
        current = data
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                current[part] = value
            else:
                if part not in current:
                    current[part] = {}
                current = current[part]

    @staticmethod
    def _get_timestamp() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self) -> str:
        return (
            f"SyncTool(locales_dir={self._locales_dir!r}, "
            f"reference_locale={self._reference_locale!r})"
        )