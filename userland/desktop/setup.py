#!/usr/bin/env python3
"""Ainos Desktop - A cross-platform desktop GUI for the Ainos AI backend."""

import os
import re
from setuptools import find_packages, setup


def get_version():
    """Read version from src/__init__.py without importing."""
    init_path = os.path.join("src", "__init__.py")
    if os.path.isfile(init_path):
        with open(init_path, encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
    return "0.1.0"


def get_long_description():
    """Read README.md for long description."""
    readme_path = "README.md"
    if os.path.isfile(readme_path):
        with open(readme_path, encoding="utf-8") as f:
            return f.read()
    return "Ainos Desktop - AI Backend Management Interface"


with open("requirements.txt", encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="ainos-desktop",
    version=get_version(),
    author="Ainos Team",
    author_email="dev@ainos.ai",
    description="A cross-platform desktop GUI for the Ainos AI backend",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    url="https://github.com/ainos/desktop",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-qt>=4.2",
            "pytest-asyncio>=0.21",
            "flake8>=6.0",
            "black>=23.0",
            "mypy>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ainos-desktop=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Desktop Environment :: GUI",
    ],
    python_requires=">=3.10",
)