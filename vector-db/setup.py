"""
Ainos Vector Database - Setup configuration.
"""

from setuptools import setup, find_packages

setup(
    name="ainos-vector-db",
    version="0.1.0",
    description="A high-performance vector database built with NumPy",
    long_description=open("README.md", "r", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Ainos",
    author_email="dev@ainos.io",
    url="https://github.com/ainos/vector-db",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.20.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
        ],
        "server": [
            # No additional dependencies needed for server
        ],
        "all": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Database :: Database Engines/Servers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="vector database, nearest neighbor search, hnsw, ivf, pq, lsh, embeddings",
    project_urls={
        "Bug Reports": "https://github.com/ainos/vector-db/issues",
        "Source": "https://github.com/ainos/vector-db",
    },
)