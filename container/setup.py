"""Ainos Container Runtime - AI-optimized container management for AinosOS."""
from setuptools import setup, find_packages

setup(
    name="ainos-container",
    version="0.1.0",
    description="AI-optimized container runtime for AinosOS",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Ainos Team",
    author_email="dev@ainos.io",
    url="https://ainos.io",
    packages=find_packages(include=["src", "ai"]),
    include_package_data=True,
    python_requires=">=3.11",
    install_requires=[
        "psutil>=5.9.0",
        "httpx>=0.25.0",
        "pydantic>=2.0.0",
        "pyyaml>=6.0",
        "orjson>=3.9.0",
        "aiofiles>=23.2.0",
        "watchdog>=3.0.0",
        "numpy>=1.25.0",
    ],
    extras_require={
        "gpu": ["pynvml>=11.5.0"],
        "dev": [
            "pytest>=7.4.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.1.0",
            "mypy>=1.5.0",
            "ruff>=0.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ainos-ctl=src.runtime:main",
            "ainos-image=src.image:main",
            "ainos-network=src.network:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.11",
        "Topic :: System :: Operating System",
        "Topic :: System :: Systems Administration",
    ],
)