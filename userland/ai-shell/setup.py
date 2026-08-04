"""Ainos Shell - An AI-powered shell for developers."""

from __future__ import annotations

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="ainos-sh",
    version="1.0.0",
    description="An AI-powered shell for developers",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Ainos Team",
    author_email="dev@ainos.ai",
    url="https://github.com/ainos/ainos-sh",
    license="MIT",
    packages=find_packages(include=["src", "src.*", "plugins", "plugins.*"]),
    package_dir={
        "src": "src",
        "plugins": "plugins",
    },
    python_requires=">=3.10",
    install_requires=[
        "httpx>=0.24.0",
        "pyyaml>=6.0",
    ],
    extras_require={
        "ai": [
            "openai>=1.0.0",
            "anthropic>=0.30.0",
        ],
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "mypy>=1.0.0",
            "black>=23.0.0",
            "ruff>=0.1.0",
        ],
        "all": [
            "openai>=1.0.0",
            "anthropic>=0.30.0",
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ainos-sh=src.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Shells",
        "Topic :: System :: System Shells",
    ],
    keywords=[
        "shell", "terminal", "cli", "ai", "command-line",
        "developer-tools", "productivity", "openai", "llm",
    ],
    include_package_data=True,
    zip_safe=False,
)