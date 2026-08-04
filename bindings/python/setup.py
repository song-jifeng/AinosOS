"""Ainos Python SDK - Setup Configuration."""
from __future__ import annotations

import pathlib
import re
from typing import Any

from setuptools import find_packages, setup

HERE: pathlib.Path = pathlib.Path(__file__).parent.resolve()


def _read_file(path: str) -> str:
    """Read a file from the project root."""
    return (HERE / path).read_text(encoding="utf-8")


def _get_version() -> str:
    """Extract version from ainos/__init__.py without importing."""
    init_content: str = _read_file("ainos/__init__.py")
    match: re.Match[str] | None = re.search(
        r'__version__\s*[:=]\s*["\']([^"\']+)["\']',
        init_content,
    )
    if match:
        return match.group(1)
    return "0.1.0"


setup(
    name="ainos",
    version=_get_version(),
    description="Python SDK for the Ainos inference daemon",
    long_description=_read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/ainos/ainos-python",
    author="Ainos Team",
    author_email="dev@ainos.ai",
    license="MIT",
    package_dir={"": "."},
    packages=find_packages(include=["ainos", "ainos.*"]),
    python_requires=">=3.10",
    install_requires=[
        # No external dependencies required; SDK uses only stdlib.
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.1.0",
            "mypy>=1.5.0",
            "ruff>=0.1.0",
            "pre-commit>=3.5.0",
        ],
        "docs": [
            "sphinx>=7.2.0",
            "sphinx-rtd-theme>=1.3.0",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords=["ainos", "inference", "llm", "ai", "machine-learning", "tcp", "ndjson"],
    project_urls={
        "Bug Reports": "https://github.com/ainos/ainos-python/issues",
        "Source": "https://github.com/ainos/ainos-python",
        "Documentation": "https://ainos-python.readthedocs.io",
    },
    zip_safe=False,
)  # type: ignore[no-untyped-call]