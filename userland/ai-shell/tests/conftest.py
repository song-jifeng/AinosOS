"""
Pytest configuration and fixtures for Ainos Shell tests.
"""

from __future__ import annotations

import os
import sys
import tempfile
import typing as t
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.utils import (
    ensure_dir,
    write_file,
    get_home_dir,
    get_config_dir,
)
from src.config import ConfigManager, get_config_manager
from src.themes import ThemeManager, get_theme_manager
from src.history import HistoryManager, get_history_manager
from src.executor import CommandExecutor, get_executor
from src.completer import Completer, get_completer
from src.prompt import PromptRenderer, get_prompt_renderer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def temp_config_dir(monkeypatch: pytest.MonkeyPatch) -> t.Iterator[str]:
    """Use a temporary config directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = os.path.join(tmpdir, ".ainos")
        ensure_dir(config_dir)
        ensure_dir(os.path.join(config_dir, "data"))
        ensure_dir(os.path.join(config_dir, "themes"))
        ensure_dir(os.path.join(config_dir, "plugins"))

        monkeypatch.setenv("HOME", tmpdir)
        monkeypatch.setenv("USERPROFILE", tmpdir)  # Windows
        monkeypatch.setattr("src.utils.get_config_dir", lambda: config_dir)
        monkeypatch.setattr("src.utils.get_home_dir", lambda: tmpdir)

        yield tmpdir


@pytest.fixture
def temp_dir() -> t.Iterator[str]:
    """Create a temporary working directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        yield tmpdir
        os.chdir(old_cwd)


@pytest.fixture
def config_manager() -> ConfigManager:
    """Get a fresh config manager."""
    return ConfigManager()


@pytest.fixture
def theme_manager() -> ThemeManager:
    """Get the theme manager."""
    return get_theme_manager()


@pytest.fixture
def history_manager(temp_config_dir: str) -> HistoryManager:
    """Get a history manager with temp database."""
    db_path = os.path.join(temp_config_dir, "data", "test_history.db")
    return HistoryManager(db_path=db_path)


@pytest.fixture
def executor() -> CommandExecutor:
    """Get a command executor."""
    return get_executor()


@pytest.fixture
def completer() -> Completer:
    """Get a completer."""
    return get_completer()


@pytest.fixture
def prompt_renderer() -> PromptRenderer:
    """Get a prompt renderer."""
    return get_prompt_renderer()


@pytest.fixture
def sample_files(temp_dir: str) -> t.List[str]:
    """Create sample files in the temp directory."""
    files = [
        "test.txt",
        "test.py",
        "test.md",
        "data.csv",
        "config.json",
        "README.md",
        "src/main.py",
        "src/utils.py",
        "tests/test_main.py",
    ]
    for f in files:
        path = os.path.join(temp_dir, f)
        ensure_dir(os.path.dirname(path))
        write_file(path, f"Content of {f}")
    return files


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def assert_exit_code_zero(result: t.Any) -> None:
    """Assert that a command result has exit code 0."""
    assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}: {result.stderr}"


def assert_exit_code(result: t.Any, code: int) -> None:
    """Assert that a command result has a specific exit code."""
    assert result.exit_code == code, f"Expected exit code {code}, got {result.exit_code}: {result.stderr}"


def run_command(shell: t.Any, command: str) -> int:
    """Run a command through the shell and return exit code."""
    shell.execute_source(command)
    return shell.state.exit_code


# ---------------------------------------------------------------------------
# Pytest configuration
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "ai: marks tests that require AI features")


def pytest_collection_modifyitems(config: pytest.Config, items: t.List[pytest.Item]) -> None:
    """Modify test collection to skip slow tests by default."""
    try:
        if config.getoption("--runslow"):
            return  # Don't skip slow tests
    except (ValueError, AttributeError):
        pass
    skip_slow = pytest.mark.skip(reason="use --runslow to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)