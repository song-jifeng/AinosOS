"""
Tests package
"""

import pytest
import json
import os

# Helper: get the locales directory
LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")


@pytest.fixture
def locales_dir() -> str:
    """Fixture providing the locales directory path."""
    return LOCALES_DIR


@pytest.fixture
def sample_translations() -> dict:
    """Fixture providing sample translation data for testing."""
    return {
        "welcome": "Welcome",
        "goodbye": "Goodbye",
        "items": {
            "one": "1 item",
            "other": "{count} items",
        },
        "errors": {
            "timeout": "Request timed out",
            "not_found": "Not found: {resource}",
        },
        "nested": {
            "deep": {
                "key": "Deep value",
            },
        },
    }


@pytest.fixture
def temp_locale_dir(tmp_path):
    """Fixture creating a temporary locale directory with test files."""
    locale_dir = tmp_path / "locales" / "test_XX"
    locale_dir.mkdir(parents=True)

    messages = {
        "welcome": "Test welcome",
        "goodbye": "Test goodbye",
        "items": "{count} items",
    }
    (locale_dir / "messages.json").write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    errors = {
        "timeout": "Timeout error",
        "not_found": "Not found",
    }
    (locale_dir / "errors.json").write_text(
        json.dumps(errors, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def temp_locales_dir(tmp_path):
    """Fixture creating multiple temporary locale directories."""
    locales_data = {
        "en_US": {
            "messages.json": {
                "welcome": "Welcome",
                "goodbye": "Goodbye",
                "items": "{count} items",
            },
            "errors.json": {
                "timeout": "Timeout",
                "not_found": "Not found: {resource}",
            },
        },
        "zh_CN": {
            "messages.json": {
                "welcome": "欢迎",
                "goodbye": "再见",
                "items": "{count} 个项目",
            },
            "errors.json": {
                "timeout": "超时",
                "not_found": "未找到: {resource}",
            },
        },
        "fr_FR": {
            "messages.json": {
                "welcome": "Bienvenue",
                "goodbye": "Au revoir",
                "items": "{count} éléments",
            },
            "errors.json": {
                "timeout": "Délai d'attente dépassé",
                "not_found": "Introuvable: {resource}",
            },
        },
    }

    for locale, files in locales_data.items():
        locale_dir = tmp_path / "locales" / locale
        locale_dir.mkdir(parents=True)
        for filename, content in files.items():
            (locale_dir / filename).write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    return tmp_path