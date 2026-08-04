"""Parsers package for AI Documentation Generator.

This package provides source code parsers for multiple programming languages,
extracting structured documentation data from source files.
"""

from .python_parser import PythonParser
from .c_parser import CParser
from .rust_parser import RustParser

__all__ = [
    "PythonParser",
    "CParser",
    "RustParser",
]

# Parser registry: maps language identifiers to parser classes
PARSER_REGISTRY = {
    "python": PythonParser,
    "py": PythonParser,
    "c": CParser,
    "h": CParser,
    "rust": RustParser,
    "rs": RustParser,
}


def get_parser(language: str):
    """Get a parser instance for the given language.

    Args:
        language: Language name or file extension (e.g., 'python', 'py', 'rust', 'rs')

    Returns:
        A parser instance matching the language

    Raises:
        ValueError: If no parser is registered for the given language
    """
    language = language.lower().strip()
    if language not in PARSER_REGISTRY:
        supported = sorted(set(PARSER_REGISTRY.keys()))
        raise ValueError(
            f"Unsupported language: '{language}'. "
            f"Supported languages/aliases: {', '.join(supported)}"
        )
    return PARSER_REGISTRY[language]()


def get_parser_for_file(filepath: str):
    """Get a parser instance based on file extension.

    Args:
        filepath: Path to the source file

    Returns:
        A parser instance matching the file extension

    Raises:
        ValueError: If the file extension is not supported
    """
    import os
    _, ext = os.path.splitext(filepath)
    ext = ext.lstrip(".").lower()
    if not ext:
        raise ValueError(f"Cannot determine file type: {filepath}")
    return get_parser(ext)


def parse_file(filepath: str, **kwargs):
    """Parse a single source file and return structured documentation data.

    This is a convenience function that detects the language from the file
    extension and parses accordingly.

    Args:
        filepath: Path to the source file
        **kwargs: Additional arguments passed to the parser

    Returns:
        ParsedDocumentation object with extracted data
    """
    parser = get_parser_for_file(filepath)
    return parser.parse_file(filepath, **kwargs)


def parse_directory(directory: str, recursive: bool = True, **kwargs):
    """Parse all supported source files in a directory.

    Args:
        directory: Path to the directory
        recursive: Whether to recurse into subdirectories
        **kwargs: Additional arguments passed to parsers

    Returns:
        Dictionary mapping file paths to ParsedDocumentation objects
    """
    import os
    from pathlib import Path

    results = {}
    directory = Path(directory)

    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    for root, dirs, files in os.walk(directory):
        if not recursive and root != str(directory):
            break
        # Skip hidden directories and common non-source dirs
        dirs[:] = [d for d in dirs
                   if not d.startswith(".")
                   and d not in ("__pycache__", "node_modules", "venv", ".venv")]
        for file in files:
            filepath = os.path.join(root, file)
            try:
                parser = get_parser_for_file(filepath)
                results[filepath] = parser.parse_file(filepath, **kwargs)
            except (ValueError, UnicodeDecodeError, SyntaxError):
                continue

    return results