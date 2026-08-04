"""Setup script for the Ainos Performance Benchmark Suite."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the long description from README
here = Path(__file__).resolve().parent
long_description = (here / "README.md").read_text(encoding="utf-8") if (here / "README.md").exists() else ""

# Read requirements from pyproject.toml or define inline
install_requires = [
    "numpy>=1.24.0",
    "scipy>=1.10.0",
    "psutil>=5.9.0",
    "pyyaml>=6.0",
    "matplotlib>=3.6.0",
    "seaborn>=0.12.0",
    "pandas>=1.5.0",
    "orjson>=3.8.0",
    "python-rapidjson>=1.10",
    "rich>=13.0.0",
    "click>=8.1.0",
    "humanize>=4.6.0",
    "pydantic>=2.0.0",
    "tabulate>=0.9.0",
    "dataclasses-json>=0.5.0",
]

extras_require = {
    "ai": [
        "torch>=2.0.0",
        "transformers>=4.30.0",
        "onnxruntime>=1.15.0",
        "sentence-transformers>=2.2.0",
        "faiss-cpu>=1.7.0",
        "annoy>=1.17.0",
    ],
    "dev": [
        "pytest>=7.4.0",
        "pytest-cov>=4.1.0",
        "pytest-benchmark>=4.0.0",
        "mypy>=1.5.0",
        "ruff>=0.1.0",
        "pre-commit>=3.3.0",
    ],
    "docs": [
        "sphinx>=6.2.0",
        "sphinx-rtd-theme>=1.2.0",
        "sphinx-autodoc-typehints>=1.23.0",
    ],
    "all": [
        "torch>=2.0.0",
        "transformers>=4.30.0",
        "onnxruntime>=1.15.0",
        "sentence-transformers>=2.2.0",
        "faiss-cpu>=1.7.0",
        "annoy>=1.17.0",
        "pytest>=7.4.0",
        "pytest-cov>=4.1.0",
        "pytest-benchmark>=4.0.0",
        "mypy>=1.5.0",
        "ruff>=0.1.0",
        "pre-commit>=3.3.0",
    ],
}

setup(
    name="ainos-benchmarks",
    version="1.0.0",
    description="Ainos Performance Benchmark Suite - Comprehensive system and AI benchmarking",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Ainos Performance Engineering",
    author_email="engineering@ainos.ai",
    url="https://github.com/ainos/benchmarks",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: System :: Benchmark",
        "Topic :: Software Development :: Testing",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.12",
    packages=find_packages(include=["benchmarks", "benchmarks.*"]),
    include_package_data=True,
    install_requires=install_requires,
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "ainos-bench=benchmarks.runner:main",
            "ainos-bench-report=benchmarks.reports.report_generator:main",
        ],
    },
    zip_safe=False,
)