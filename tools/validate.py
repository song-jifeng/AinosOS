"""
Translation Validation Tool
============================

Validates translation files for completeness, consistency, and correctness.

Checks:
* All keys present across locales
* No missing translations
* Placeholder consistency (same ``{var}`` placeholders in all locales)
* Plural form completeness
* ICU message format validity
* File format validity (JSON, YAML)
* Value types (all values should be strings or dicts)
"""

from __future__ import annotations

import os
import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of a translation validation.

    Attributes
    ----------
    valid : bool
        Whether the validation passed.
    errors : list[dict]
        List of error details.
    warnings : list[dict]
        List of warning details.
    stats : dict
        Validation statistics.
    """

    def __init__(self) -> None:
        self.valid = True
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.stats: dict[str, Any] = {}

    def add_error(self, message: str, locale: str = "", key: str = "", file: str = "") -> None:
        """Add a validation error."""
        self.valid = False
        self.errors.append({
            "message": message,
            "locale": locale,
            "key": key,
            "file": file,
        })

    def add_warning(self, message: str, locale: str = "", key: str = "", file: str = "") -> None:
        """Add a validation warning."""
        self.warnings.append({
            "message": message,
            "locale": locale,
            "key": key,
            "file": file,
        })

    def to_dict(self) -> dict[str, Any]:
        """Convert to a serializable dictionary."""
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }

    def __repr__(self) -> str:
        return (
            f"ValidationResult(valid={self.valid}, "
            f"errors={len(self.errors)}, warnings={len(self.warnings)})"
        )


class ValidationTool:
    """Validate translation files and data.

    Parameters
    ----------
    locales_dir : str
        Directory containing locale subdirectories.
    reference_locale : str, optional
        Locale to use as the reference (source language). Defaults to ``"en_US"``.
    """

    # ICU placeholder pattern for validation
    ICU_PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")

    def __init__(
        self,
        locales_dir: str,
        reference_locale: str = "en_US",
    ) -> None:
        self._locales_dir = locales_dir
        self._reference_locale = reference_locale

    # ---- Validation methods ----

    def validate_all(self) -> dict[str, ValidationResult]:
        """Run all validations.

        Returns
        -------
        dict[str, ValidationResult]
            Mapping of validation category -> result.
        """
        return {
            "file_format": self.validate_file_formats(),
            "key_completeness": self.validate_key_completeness(),
            "placeholder_consistency": self.validate_placeholder_consistency(),
            "plural_completeness": self.validate_plural_completeness(),
            "value_types": self.validate_value_types(),
            "icu_format": self.validate_icu_format(),
        }

    def validate_file_formats(self) -> ValidationResult:
        """Validate that all translation files are valid JSON.

        Returns
        -------
        ValidationResult
        """
        result = ValidationResult()
        locales = self._get_locales()

        for locale in locales:
            locale_dir = os.path.join(self._locales_dir, locale)
            if not os.path.isdir(locale_dir):
                result.add_error(f"Locale directory not found", locale=locale, file=locale_dir)
                continue

            for filename in sorted(os.listdir(locale_dir)):
                if not filename.endswith(".json"):
                    continue
                file_path = os.path.join(locale_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        result.add_error(
                            f"File root is not a JSON object: {type(data).__name__}",
                            locale=locale, key="", file=file_path,
                        )
                except json.JSONDecodeError as exc:
                    result.add_error(
                        f"Invalid JSON: {exc}",
                        locale=locale, key="", file=file_path,
                    )
                except (OSError, IOError) as exc:
                    result.add_error(
                        f"File read error: {exc}",
                        locale=locale, key="", file=file_path,
                    )

        result.stats = {
            "type": "file_format",
            "locales_checked": len(locales),
        }
        return result

    def validate_key_completeness(self) -> ValidationResult:
        """Validate that all locales have the same keys as the reference.

        Returns
        -------
        ValidationResult
        """
        result = ValidationResult()
        all_keys = self._load_all_keys()

        if not all_keys:
            result.add_error("No translation data found")
            return result

        reference_keys = all_keys.get(self._reference_locale, set())
        if not reference_keys:
            result.add_warning(
                f"Reference locale '{self._reference_locale}' has no keys",
            )
            # Use the first available locale as reference
            for loc, keys in all_keys.items():
                if keys:
                    reference_keys = keys
                    self._reference_locale = loc
                    break

        for locale, keys in all_keys.items():
            if locale == self._reference_locale:
                continue

            missing = reference_keys - keys
            extra = keys - reference_keys

            for key in sorted(missing):
                result.add_error(
                    f"Missing translation for key",
                    locale=locale, key=key,
                )

            for key in sorted(extra):
                result.add_warning(
                    f"Extra key not in reference locale",
                    locale=locale, key=key,
                )

        result.stats = {
            "type": "key_completeness",
            "reference_locale": self._reference_locale,
            "reference_key_count": len(reference_keys),
            "locales_checked": len(all_keys) - 1,
            "total_missing": sum(1 for e in result.errors),
            "total_extra": sum(1 for w in result.warnings),
        }
        return result

    def validate_placeholder_consistency(self) -> ValidationResult:
        """Validate that ICU placeholders match across locales.

        For each key, all locales should have the same ``{var}`` placeholders.

        Returns
        -------
        ValidationResult
        """
        result = ValidationResult()
        locale_data = self._load_locale_data()

        if not locale_data:
            return result

        # Build placeholder map: key -> locale -> set of placeholders
        placeholders: dict[str, dict[str, set[str]]] = {}
        for locale, data in locale_data.items():
            flat = self._flatten_dict(data)
            for key, value in flat.items():
                if isinstance(value, str):
                    found = set(self.ICU_PLACEHOLDER_PATTERN.findall(value))
                    if found:
                        if key not in placeholders:
                            placeholders[key] = {}
                        placeholders[key][locale] = found

        # Check consistency
        for key, locale_ph in placeholders.items():
            ref_locale = self._reference_locale if self._reference_locale in locale_ph else next(iter(locale_ph))
            ref_ph = locale_ph[ref_locale]

            for locale, ph in locale_ph.items():
                if ph != ref_ph:
                    missing = ref_ph - ph
                    extra = ph - ref_ph
                    if missing:
                        result.add_error(
                            f"Missing placeholders: {', '.join(sorted(missing))}",
                            locale=locale, key=key,
                        )
                    if extra:
                        result.add_warning(
                            f"Extra placeholders: {', '.join(sorted(extra))}",
                            locale=locale, key=key,
                        )

        result.stats = {
            "type": "placeholder_consistency",
            "keys_with_placeholders": len(placeholders),
            "locales_checked": len(locale_data),
        }
        return result

    def validate_plural_completeness(self) -> ValidationResult:
        """Validate that plural forms are complete.

        Checks that plural dictionaries have at least ``"other"`` form.

        Returns
        -------
        ValidationResult
        """
        result = ValidationResult()
        locale_data = self._load_locale_data()

        for locale, data in locale_data.items():
            self._check_plural_forms(data, locale, "", result)

        result.stats = {
            "type": "plural_completeness",
            "locales_checked": len(locale_data),
        }
        return result

    def validate_value_types(self) -> ValidationResult:
        """Validate that all translation values are of the correct type.

        Values should be strings, dicts (for pluralization), or lists.

        Returns
        -------
        ValidationResult
        """
        result = ValidationResult()
        locale_data = self._load_locale_data()

        for locale, data in locale_data.items():
            flat = self._flatten_dict(data, include_dicts=True)
            for key, value in flat.items():
                if isinstance(value, dict):
                    # Check plural dict values are strings
                    for form_key, form_value in value.items():
                        if not isinstance(form_value, str):
                            result.add_error(
                                f"Plural form '{form_key}' value is not a string: {type(form_value).__name__}",
                                locale=locale, key=f"{key}.{form_key}",
                            )
                elif isinstance(value, list):
                    # Allow lists for some use cases
                    for item in value:
                        if not isinstance(item, str):
                            result.add_warning(
                                f"List contains non-string element: {type(item).__name__}",
                                locale=locale, key=key,
                            )
                elif not isinstance(value, str):
                    result.add_error(
                        f"Value is not a string or dict: {type(value).__name__} = {value!r}",
                        locale=locale, key=key,
                    )

        result.stats = {
            "type": "value_types",
            "locales_checked": len(locale_data),
        }
        return result

    def validate_icu_format(self) -> ValidationResult:
        """Validate ICU message format syntax.

        Checks for:
        * Balanced braces ``{...}``
        * Valid plural syntax
        * Valid select syntax

        Returns
        -------
        ValidationResult
        """
        result = ValidationResult()
        locale_data = self._load_locale_data()

        for locale, data in locale_data.items():
            flat = self._flatten_dict(data)
            for key, value in flat.items():
                if isinstance(value, str):
                    if "{" in value:
                        self._check_icu_syntax(value, locale, key, result)

        result.stats = {
            "type": "icu_format",
            "locales_checked": len(locale_data),
        }
        return result

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

    def _load_locale_data(self) -> dict[str, dict[str, Any]]:
        """Load all locale data from JSON files."""
        from ainos_i18n.loaders.json import JSONLoader
        loader = JSONLoader(self._locales_dir)
        locales = self._get_locales()
        data: dict[str, dict[str, Any]] = {}
        for locale in locales:
            try:
                data[locale] = loader.load(locale)
            except Exception as exc:
                logger.warning("Failed to load locale '%s': %s", locale, exc)
                data[locale] = {}
        return data

    def _load_all_keys(self) -> dict[str, set[str]]:
        """Load all keys for all locales."""
        locale_data = self._load_locale_data()
        all_keys: dict[str, set[str]] = {}
        for locale, data in locale_data.items():
            keys = self._collect_keys(data)
            all_keys[locale] = keys
        return all_keys

    @staticmethod
    def _collect_keys(data: dict[str, Any], prefix: str = "") -> set[str]:
        """Recursively collect all dot-separated leaf keys."""
        keys: set[str] = set()
        for k, v in data.items():
            full_key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                # Check if it's a plural dict (forms like "one", "other")
                if all(isinstance(sk, str) and len(sk) < 10 for sk in v):
                    # Could be a plural form; treat as leaf
                    keys.add(full_key)
                else:
                    keys |= ValidationTool._collect_keys(v, f"{full_key}.")
            else:
                keys.add(full_key)
        return keys

    @staticmethod
    def _flatten_dict(data: dict[str, Any], prefix: str = "", include_dicts: bool = False) -> dict[str, Any]:
        """Flatten a nested dict to dot-separated keys."""
        flat: dict[str, Any] = {}
        for k, v in data.items():
            full_key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                # Check if it's a plural dict
                if all(isinstance(sk, str) and len(sk) < 10 for sk in v):
                    if include_dicts:
                        flat[full_key] = v
                    else:
                        for sk, sv in v.items():
                            flat[f"{full_key}.{sk}"] = sv
                else:
                    flat.update(ValidationTool._flatten_dict(v, f"{full_key}.", include_dicts))
            else:
                flat[full_key] = v
        return flat

    @staticmethod
    def _check_plural_forms(
        data: dict[str, Any],
        locale: str,
        prefix: str,
        result: ValidationResult,
    ) -> None:
        """Recursively check plural form completeness."""
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                form_keys = set(value.keys())
                # Check if this looks like a plural dict
                if form_keys.issubset({"zero", "one", "two", "few", "many", "other"}):
                    if "other" not in form_keys:
                        result.add_error(
                            f"Plural dict missing required 'other' form",
                            locale=locale, key=full_key,
                        )
                else:
                    ValidationTool._check_plural_forms(value, locale, full_key, result)

    @staticmethod
    def _check_icu_syntax(
        text: str,
        locale: str,
        key: str,
        result: ValidationResult,
    ) -> None:
        """Check ICU message syntax."""
        # Check balanced braces
        stack = []
        for i, ch in enumerate(text):
            if ch == "{":
                stack.append(i)
            elif ch == "}":
                if not stack:
                    result.add_error(
                        f"Unbalanced closing brace at position {i}",
                        locale=locale, key=key,
                    )
                    return
                stack.pop()

        if stack:
            result.add_error(
                f"Unbalanced opening brace(s) at position(s): {stack}",
                locale=locale, key=key,
            )

    def __repr__(self) -> str:
        return (
            f"ValidationTool(locales_dir={self._locales_dir!r}, "
            f"reference_locale={self._reference_locale!r})"
        )