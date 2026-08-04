"""Setup script for the ainos_i18n package."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="ainos_i18n",
    version="1.0.0",
    description="AinosOS Internationalization (i18n) and Localization (l10n) Framework",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="AinosOS Internationalization Team",
    author_email="i18n@ainos.io",
    url="https://github.com/ainos/i18n",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "ainos_i18n": ["locales/**/*.json"],
    },
    python_requires=">=3.10",
    install_requires=[
        "pyyaml>=6.0",
    ],
    extras_require={
        "yaml": ["pyyaml>=6.0"],
        "database": ["sqlite3"],
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "mypy>=1.0",
            "ruff>=0.1",
        ],
    },
    entry_points={
        "console_scripts": [
            "ainos-i18n-extract=ainos_i18n.tools.extract:main",
            "ainos-i18n-compile=ainos_i18n.tools.compile:main",
            "ainos-i18n-validate=ainos_i18n.tools.validate:main",
            "ainos-i18n-sync=ainos_i18n.tools.sync:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Internationalization",
        "Topic :: Software Development :: Localization",
    ],
    keywords="i18n, l10n, internationalization, localization, translation, ainos",
)