"""Setup script for AinosDB - Hybrid Database Engine."""

from setuptools import setup, find_packages

setup(
    name="ainosdb",
    version="0.1.0",
    description="AinosDB - Hybrid Database Engine (SQL + Vector + Document)",
    author="AinosOS Team",
    author_email="dev@ainos.ai",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.24.0",
        "numba>=0.57.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.1.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
        ],
        "server": [
            "asyncio",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Database :: Database Engines/Servers",
    ],
)