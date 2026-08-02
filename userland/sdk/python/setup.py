"""Setup script for the ainos-sdk package."""

from setuptools import find_packages, setup

setup(
    name="ainos-sdk",
    version="0.1.0",
    description="Python SDK for the Ainos AI Daemon",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Ainos OS Team",
    url="https://github.com/ainos-os/ainos",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="ainos, ai, daemon, sdk, llm",
    project_urls={
        "Source": "https://github.com/ainos-os/ainos",
    },
)