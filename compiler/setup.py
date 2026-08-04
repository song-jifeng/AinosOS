"""
AI 编译器工具链 - 安装配置
"""

from setuptools import setup, find_packages

setup(
    name="ai-compiler",
    version="1.0.0",
    description="AI Compiler Toolchain - 支持 AI 自动调优的编译器工具链",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="AI Compiler Team",
    author_email="team@ai-compiler.dev",
    url="https://github.com/ai-compiler/compiler",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "typing-extensions>=4.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
            "flake8>=6.0.0",
        ],
        "ai": [
            "numpy>=1.24.0",
            "scipy>=1.10.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "aicompiler=src.compiler:Compiler.run_command_line",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Compilers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    keywords="compiler, ai, optimization, machine learning, code generation",
    project_urls={
        "Documentation": "https://ai-compiler.dev/docs",
        "Source": "https://github.com/ai-compiler/compiler",
        "Bug Tracker": "https://github.com/ai-compiler/compiler/issues",
    },
)