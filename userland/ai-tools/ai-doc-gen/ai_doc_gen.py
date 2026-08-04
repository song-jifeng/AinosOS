#!/usr/bin/env python3
"""
AinosOS AI Documentation Generator
===================================
AI-powered documentation generator that parses source code comments from multiple
languages and generates documentation in Markdown, HTML, and OpenAPI formats.

Subcommands:
    generate    Generate documentation from source files
    serve       Serve generated documentation via HTTP
    watch       Watch source files for changes and regenerate

Supports Python, C, Rust, Java, and Go source code with Mermaid/PlantUML
diagram generation.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import textwrap
import time
import hashlib
import http.server
import socketserver
import threading
import webbrowser
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generator, List, Optional,
    Sequence, Set, Tuple, Type, Union,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
APP_NAME = "ai-doc-gen"

SUPPORTED_EXTENSIONS = {
    ".py", ".c", ".h", ".rs", ".java", ".go",
    ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".kt",
}

DOC_OUTPUT_FORMATS = ("markdown", "html", "openapi", "json")

DIAGRAM_TYPES = ("mermaid", "plantuml", "none")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DocParam:
    """Documented parameter."""
    name: str
    type: str = ""
    description: str = ""
    required: bool = True
    default_value: Optional[str] = None


@dataclass
class DocFunction:
    """Documented function/method."""
    name: str
    qualname: str = ""
    signature: str = ""
    summary: str = ""
    description: str = ""
    params: List[DocParam] = field(default_factory=list)
    returns: Optional[Dict[str, str]] = None
    raises: List[Dict[str, str]] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    deprecation: Optional[str] = None
    source_file: str = ""
    line_number: int = 0
    modifiers: List[str] = field(default_factory=list)
    is_method: bool = False
    is_static: bool = False
    is_async: bool = False


@dataclass
class DocClass:
    """Documented class."""
    name: str
    qualname: str = ""
    summary: str = ""
    description: str = ""
    methods: List[DocFunction] = field(default_factory=list)
    attributes: List[Dict[str, str]] = field(default_factory=list)
    bases: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    source_file: str = ""
    line_number: int = 0
    is_abstract: bool = False
    is_interface: bool = False


@dataclass
class DocModule:
    """Documented module/file."""
    name: str
    filepath: str = ""
    summary: str = ""
    description: str = ""
    functions: List[DocFunction] = field(default_factory=list)
    classes: List[DocClass] = field(default_factory=list)
    variables: List[Dict[str, Any]] = field(default_factory=list)
    constants: List[Dict[str, Any]] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    todos: List[Dict[str, Any]] = field(default_factory=list)
    fixmes: List[Dict[str, Any]] = field(default_factory=list)
    language: str = "python"


@dataclass
class DocResult:
    """Complete documentation result."""
    modules: Dict[str, DocModule] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Docstring parsers for each language
# ---------------------------------------------------------------------------

class DocstringParser:
    """Parse docstrings in various styles (Google, NumPy, Sphinx, Javadoc, Godoc)."""

    @staticmethod
    def parse_python(docstring: str) -> Dict[str, Any]:
        """Parse Python docstring (Google/NumPy/Sphinx style)."""
        if not docstring:
            return {"summary": "", "description": "", "params": [], "returns": None}

        result: Dict[str, Any] = {
            "summary": "",
            "description": "",
            "params": [],
            "returns": None,
            "raises": [],
            "examples": [],
            "notes": [],
        }

        lines = docstring.strip().split("\n")
        if not lines:
            return result

        # First line is summary
        result["summary"] = lines[0].strip()

        # Detect style
        text = "\n".join(lines)

        # Google-style sections
        section_pattern = re.compile(
            r"^(Args|Arguments|Parameters|Returns|Yields|Raises|Attributes|"
            r"Note|Notes|Example|Examples|Todo|Deprecated)\s*:",
            re.MULTILINE | re.IGNORECASE
        )

        if section_pattern.search(text):
            DocstringParser._parse_google_sections(text, result)
        elif re.search(r":param\s+\w+\s*:", text):
            DocstringParser._parse_sphinx(text, result)
        else:
            # Plain docstring
            if len(lines) > 1:
                desc_lines = [l.strip() for l in lines[1:] if l.strip()]
                result["description"] = " ".join(desc_lines)

        return result

    @staticmethod
    def _parse_google_sections(text: str, result: Dict[str, Any]) -> None:
        """Parse Google-style docstring sections."""
        current_section = None
        lines = text.split("\n")

        for line in lines:
            stripped = line.strip()
            section_match = re.match(
                r"^(Args|Arguments|Parameters|Returns|Yields|Raises|Attributes|"
                r"Note|Notes|Example|Examples|Todo|Deprecated)\s*:",
                stripped, re.IGNORECASE
            )
            if section_match:
                current_section = section_match.group(1).lower()
                continue

            if current_section in ("args", "arguments", "parameters"):
                param_match = re.match(r"(\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)", stripped)
                if param_match:
                    result["params"].append({
                        "name": param_match.group(1),
                        "type": (param_match.group(2) or "").strip(),
                        "description": param_match.group(3).strip(),
                    })
            elif current_section == "returns":
                ret_match = re.match(r"(?:(\w+)\s*:\s*)?(.*)", stripped)
                if ret_match:
                    if result["returns"] is None:
                        result["returns"] = {}
                    if ret_match.group(1):
                        result["returns"]["type"] = ret_match.group(1).strip()
                    if ret_match.group(2):
                        result["returns"]["description"] = ret_match.group(2).strip()
            elif current_section == "raises":
                raise_match = re.match(r"(\w+(?:\.\w+)*)\s*:\s*(.*)", stripped)
                if raise_match:
                    result["raises"].append({
                        "type": raise_match.group(1),
                        "description": raise_match.group(2).strip(),
                    })
            elif current_section in ("note", "notes"):
                if stripped:
                    result["notes"].append(stripped)
            elif current_section in ("example", "examples"):
                if stripped:
                    result["examples"].append(stripped)

    @staticmethod
    def _parse_sphinx(text: str, result: Dict[str, Any]) -> None:
        """Parse Sphinx-style docstring."""
        # :param name: description
        for match in re.finditer(r":param\s+(\w+)\s*:\s*(.*?)(?=:param|:type|:returns|:raises|$)", text, re.DOTALL):
            result["params"].append({
                "name": match.group(1),
                "type": "",
                "description": match.group(2).strip(),
            })

        # :type name: type
        type_map = {}
        for match in re.finditer(r":type\s+(\w+)\s*:\s*(.*?)(?=:param|:type|:returns|:raises|$)", text, re.DOTALL):
            type_map[match.group(1)] = match.group(2).strip()
        for param in result["params"]:
            if param["name"] in type_map:
                param["type"] = type_map[param["name"]]

        # :returns: description
        ret_match = re.search(r":returns?\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:rtype|$)", text, re.DOTALL)
        if ret_match:
            result["returns"] = {"description": ret_match.group(1).strip()}

        # :rtype: type
        rtype_match = re.search(r":rtype\s*:\s*(.*?)(?=:param|:type|:returns|:raises|$)", text, re.DOTALL)
        if rtype_match:
            if result["returns"] is None:
                result["returns"] = {}
            result["returns"]["type"] = rtype_match.group(1).strip()

        # :raises ExcType: description
        for match in re.finditer(r":raises\s+(\w+)\s*:\s*(.*?)(?=:param|:type|:returns|:raises|$)", text, re.DOTALL):
            result["raises"].append({
                "type": match.group(1),
                "description": match.group(2).strip(),
            })

    @staticmethod
    def parse_c(docstring: str) -> Dict[str, Any]:
        """Parse C Doxygen-style comment."""
        if not docstring:
            return {"summary": "", "description": "", "params": [], "returns": None}

        result: Dict[str, Any] = {
            "summary": "",
            "description": "",
            "params": [],
            "returns": None,
            "see": [],
            "warning": [],
            "note": [],
            "deprecated": None,
        }

        # Extract brief
        brief_match = re.search(r"@brief\s+(.*?)(?=@|\n\s*\n|$)", docstring, re.DOTALL)
        if brief_match:
            result["summary"] = brief_match.group(1).strip()

        # Extract params
        for match in re.finditer(r"@param\s+\[?(in|out|in,out)?\]?\s*(\w+)\s+(.*?)(?=@|\n\s*\n|$)", docstring, re.DOTALL):
            result["params"].append({
                "name": match.group(2),
                "description": match.group(3).strip(),
                "direction": match.group(1) or "",
            })

        # Extract return
        ret_match = re.search(r"@returns?\s+(.*?)(?=@|\n\s*\n|$)", docstring, re.DOTALL)
        if ret_match:
            result["returns"] = {"description": ret_match.group(1).strip()}

        # Extract warnings
        for match in re.finditer(r"@warning\s+(.*?)(?=@|\n\s*\n|$)", docstring, re.DOTALL):
            result["warning"].append(match.group(1).strip())

        # Extract notes
        for match in re.finditer(r"@note\s+(.*?)(?=@|\n\s*\n|$)", docstring, re.DOTALL):
            result["note"].append(match.group(1).strip())

        # Extract deprecated
        dep_match = re.search(r"@deprecated\s+(.*?)(?=@|\n\s*\n|$)", docstring, re.DOTALL)
        if dep_match:
            result["deprecated"] = dep_match.group(1).strip()

        # If no brief, use first paragraph
        if not result["summary"]:
            lines = docstring.strip().split("\n")
            clean_lines = [l.lstrip("*").strip() for l in lines]
            clean_lines = [l for l in clean_lines if l and not l.startswith("@")]
            if clean_lines:
                result["summary"] = clean_lines[0]

        return result

    @staticmethod
    def parse_rust(docstring: str) -> Dict[str, Any]:
        """Parse Rustdoc-style comment."""
        if not docstring:
            return {"summary": "", "description": "", "params": [], "returns": None}

        result: Dict[str, Any] = {
            "summary": "",
            "description": "",
            "params": [],
            "returns": None,
            "panics": [],
            "errors": [],
            "safety": [],
            "examples": [],
        }

        lines = docstring.strip().split("\n")
        clean_lines = [l.strip() for l in lines]

        text = "\n".join(clean_lines)

        # Split by sections
        sections = re.split(r"\n\s*#\s+", text)

        # First section is summary
        if sections:
            first_lines = sections[0].strip().split("\n")
            if first_lines:
                result["summary"] = first_lines[0].strip()
                if len(first_lines) > 1:
                    result["description"] = "\n".join(first_lines[1:]).strip()

        # Parse remaining sections
        for section in sections[1:]:
            section_lower = section.lower()
            lines = section.split("\n")

            if section_lower.startswith("parameters") or section_lower.startswith("arguments"):
                for line in lines[1:]:
                    match = re.match(r'^\s*[-*]\s*`(\w+)`\s*:\s*(.*)', line)
                    if match:
                        result["params"].append({
                            "name": match.group(1),
                            "description": match.group(2).strip(),
                        })
            elif section_lower.startswith("returns"):
                desc_lines = [l for l in lines[1:] if l.strip()]
                if desc_lines:
                    result["returns"] = {"description": " ".join(desc_lines).strip()}
            elif section_lower.startswith("panics"):
                for line in lines[1:]:
                    if line.strip() and not line.startswith("-"):
                        result["panics"].append(line.strip())
            elif section_lower.startswith("errors"):
                for line in lines[1:]:
                    if line.strip() and not line.startswith("-"):
                        result["errors"].append(line.strip())
            elif section_lower.startswith("safety"):
                for line in lines[1:]:
                    if line.strip() and not line.startswith("-"):
                        result["safety"].append(line.strip())
            elif section_lower.startswith("examples"):
                in_code = False
                current = []
                for line in lines[1:]:
                    if line.strip().startswith("```"):
                        if in_code:
                            result["examples"].append("\n".join(current))
                            current = []
                            in_code = False
                        else:
                            in_code = True
                    elif in_code:
                        current.append(line)

        return result

    @staticmethod
    def parse_java(docstring: str) -> Dict[str, Any]:
        """Parse Java Javadoc-style comment."""
        if not docstring:
            return {"summary": "", "description": "", "params": [], "returns": None}

        result: Dict[str, Any] = {
            "summary": "",
            "description": "",
            "params": [],
            "returns": None,
            "throws": [],
            "see": [],
            "deprecated": None,
            "since": None,
            "author": [],
        }

        # Clean the comment
        lines = docstring.strip().split("\n")
        clean_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith("*"):
                line = line[1:].strip()
            clean_lines.append(line)
        text = "\n".join(clean_lines)

        # Extract summary (first sentence before first dot-space or first tag)
        end_match = re.search(r'\.\s+', text)
        if end_match:
            result["summary"] = text[:end_match.start() + 1].strip()
        else:
            result["summary"] = clean_lines[0] if clean_lines else ""

        # Extract params
        for match in re.finditer(r"@param\s+(\w+)\s+(.*?)(?=@|\n\s*\n|$)", text, re.DOTALL):
            result["params"].append({
                "name": match.group(1),
                "description": match.group(2).strip(),
            })

        # Extract return
        ret_match = re.search(r"@return\s+(.*?)(?=@|\n\s*\n|$)", text, re.DOTALL)
        if ret_match:
            result["returns"] = {"description": ret_match.group(1).strip()}

        # Extract throws
        for match in re.finditer(r"@throws\s+(\w+)\s+(.*?)(?=@|\n\s*\n|$)", text, re.DOTALL):
            result["throws"].append({
                "type": match.group(1),
                "description": match.group(2).strip(),
            })

        # Extract deprecated
        if re.search(r"@deprecated", text):
            dep_match = re.search(r"@deprecated\s+(.*?)(?=@|\n\s*\n|$)", text, re.DOTALL)
            result["deprecated"] = dep_match.group(1).strip() if dep_match else ""

        # Extract since
        since_match = re.search(r"@since\s+(.*?)(?=@|\n\s*\n|$)", text, re.DOTALL)
        if since_match:
            result["since"] = since_match.group(1).strip()

        # Extract authors
        for match in re.finditer(r"@author\s+(.*?)(?=@|\n\s*\n|$)", text, re.DOTALL):
            result["author"].append(match.group(1).strip())

        return result

    @staticmethod
    def parse_go(docstring: str) -> Dict[str, Any]:
        """Parse Go-style comment (line comments before declaration)."""
        if not docstring:
            return {"summary": "", "description": ""}

        result: Dict[str, Any] = {
            "summary": "",
            "description": "",
        }

        lines = docstring.strip().split("\n")
        if not lines:
            return result

        # First line is summary
        result["summary"] = lines[0].strip()

        # Rest is description
        if len(lines) > 1:
            desc_lines = [l.strip() for l in lines[1:] if l.strip()]
            result["description"] = " ".join(desc_lines)

        return result


# ---------------------------------------------------------------------------
# Source Code Parsers
# ---------------------------------------------------------------------------

class PythonDocParser:
    """Parse Python source files for documentation."""

    def parse(self, source: str, filepath: str = "") -> DocModule:
        """Parse Python source into a DocModule."""
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ValueError(f"Failed to parse Python source: {e}")

        module_name = os.path.splitext(os.path.basename(filepath))[0] if filepath else "module"
        if module_name == "__init__":
            module_name = os.path.basename(os.path.dirname(filepath))

        module = DocModule(name=module_name, filepath=filepath, language="python")

        # Module docstring
        module_doc = ast.get_docstring(tree)
        if module_doc:
            parsed = DocstringParser.parse_python(module_doc)
            module.summary = parsed["summary"]
            module.description = parsed["description"]

        lines = source.splitlines()

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = self._parse_function(node, lines, source)
                module.functions.append(func)
            elif isinstance(node, ast.ClassDef):
                cls = self._parse_class(node, lines, source)
                module.classes.append(cls)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        val = ast.unparse(node.value) if hasattr(ast, "unparse") else ""
                        var_info = {"name": target.id, "value": val, "line": node.lineno}
                        if target.id.isupper():
                            module.constants.append(var_info)
                        else:
                            module.variables.append(var_info)

        # Extract TODO/FIXME comments
        for i, line in enumerate(lines, 1):
            todo_match = re.search(r"#\s*TODO\b\s*:?\s*(.*)", line, re.IGNORECASE)
            if todo_match:
                module.todos.append({"text": todo_match.group(1).strip(), "line": i})
            fixme_match = re.search(r"#\s*FIXME\b\s*:?\s*(.*)", line, re.IGNORECASE)
            if fixme_match:
                module.fixmes.append({"text": fixme_match.group(1).strip(), "line": i})

        return module

    def _parse_function(self, node: ast.AST, lines: List[str], source: str,
                        parent_class: Optional[str] = None) -> DocFunction:
        """Parse a function definition from AST."""
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise ValueError("Expected FunctionDef or AsyncFunctionDef")

        qualname = f"{parent_class}.{node.name}" if parent_class else node.name

        func = DocFunction(
            name=node.name,
            qualname=qualname,
            source_file=source,
            line_number=node.lineno,
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )

        # Build signature string
        try:
            func.signature = ast.unparse(node) if hasattr(ast, "unparse") else node.name
        except Exception:
            func.signature = node.name

        # Docstring
        docstring = ast.get_docstring(node)
        if docstring:
            parsed = DocstringParser.parse_python(docstring)
            func.summary = parsed["summary"]
            func.description = parsed["description"]
            func.params = [DocParam(**p) for p in parsed["params"]]
            if parsed["returns"]:
                func.returns = parsed["returns"]
            func.raises = parsed["raises"]
            func.examples = parsed["examples"]
            func.notes = parsed["notes"]

        # Decorators
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                func.modifiers.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                func.modifiers.append(f"{self._get_attr_name(dec.value)}.{dec.attr}")
            if isinstance(dec, ast.Name) and dec.id == "staticmethod":
                func.is_static = True

        # Parameters (from AST for type info)
        if not func.params:
            for arg in node.args.args:
                type_hint = self._get_annotation_str(arg.annotation)
                func.params.append(DocParam(
                    name=arg.arg,
                    type=type_hint or "",
                    required=True,
                ))

        # Return type
        if node.returns and not func.returns:
            type_str = self._get_annotation_str(node.returns)
            func.returns = {"type": type_str, "description": ""}

        return func

    def _parse_class(self, node: ast.ClassDef, lines: List[str], source: str) -> DocClass:
        """Parse a class definition."""
        cls = DocClass(
            name=node.name,
            qualname=node.name,
            source_file=source,
            line_number=node.lineno,
        )

        docstring = ast.get_docstring(node)
        if docstring:
            parsed = DocstringParser.parse_python(docstring)
            cls.summary = parsed["summary"]
            cls.description = parsed["description"]

        # Bases
        for base in node.bases:
            name = self._get_annotation_str(base)
            if name:
                cls.bases.append(name)

        # Decorators
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                cls.decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                val = self._get_attr_name(dec.value)
                cls.decorators.append(f"{val}.{dec.attr}")

        # Methods
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method = self._parse_function(child, lines, source, parent_class=node.name)
                method.is_method = True
                cls.methods.append(method)

        return cls

    def _get_annotation_str(self, node: Optional[ast.AST]) -> str:
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return f"{self._get_annotation_str(node.value)}.{node.attr}"
            if isinstance(node, ast.Subscript):
                value = self._get_annotation_str(node.value)
                if isinstance(node.slice, ast.Tuple):
                    slices = ", ".join(self._get_annotation_str(el) for el in node.slice.elts)
                    return f"{value}[{slices}]"
                sl = self._get_annotation_str(node.slice)
                return f"{value}[{sl}]"
            if isinstance(node, ast.Constant):
                return repr(node.value)
            return str(node)

    def _get_attr_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_attr_name(node.value)}.{node.attr}"
        return str(node)


class CWithDocParser:
    """Parse C source files with Doxygen comments for documentation."""

    def parse(self, source: str, filepath: str = "") -> DocModule:
        """Parse C source into a DocModule."""
        name = os.path.splitext(os.path.basename(filepath))[0] if filepath else "module"
        module = DocModule(name=name, filepath=filepath, language="c")

        lines = source.splitlines()

        # Extract all comments
        doc_comments = self._extract_doc_comments(source)

        # Extract functions
        cleaned = re.sub(r'"[^"]*"', '""', source)
        cleaned = re.sub(r"'[^']*'", "''", cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        func_pattern = re.compile(
            r'(?:(?:static|inline|extern|const|volatile)\s+)*'
            r'(\w+(?:\s*\*+)?)\s+'  # return type
            r'(\w+)\s*'  # function name
            r'\(([^)]*)\)\s*'  # params
            r'(?:\{|;)',  # body start or semicolon
            re.MULTILINE
        )

        for match in func_pattern.finditer(cleaned):
            ret_type = match.group(1).strip()
            name = match.group(2)
            params_str = match.group(3).strip()
            line_no = source[:match.start()].count("\n") + 1

            if name in ("if", "while", "for", "switch", "return", "sizeof"):
                continue

            func = DocFunction(
                name=name,
                qualname=name,
                signature=f"{ret_type} {name}({params_str})",
                line_number=line_no,
                source_file=filepath,
            )

            # Find preceding doc comment
            comment = self._get_comment_before(source, match.start())
            if comment:
                parsed = DocstringParser.parse_c(comment)
                func.summary = parsed["summary"]
                func.description = parsed["description"]
                func.params = [DocParam(**{k: v for k, v in p.items() if k != "direction"})
                              for p in parsed["params"]]
                if parsed["returns"]:
                    func.returns = parsed["returns"]

            if not func.params:
                self._parse_c_params(params_str, func)

            module.functions.append(func)

        # Extract structs
        struct_pattern = re.compile(
            r'(?:typedef\s+)?struct\s+(\w+)\s*\{([^}]*)\}(?:\s*(\w+))?\s*;',
            re.DOTALL,
        )
        for match in struct_pattern.finditer(cleaned):
            cls_name = match.group(3) or match.group(1)
            cls = DocClass(name=cls_name, line_number=source[:match.start()].count("\n") + 1)
            comment = self._get_comment_before(source, match.start())
            if comment:
                parsed = DocstringParser.parse_c(comment)
                cls.summary = parsed["summary"]
            module.classes.append(cls)

        # Extract defines
        for match in re.finditer(r'#define\s+(\w+)(?:\s+(.*))?', source, re.MULTILINE):
            module.constants.append({
                "name": match.group(1),
                "value": (match.group(2) or "").strip(),
            })

        return module

    def _extract_doc_comments(self, source: str) -> List[Dict[str, Any]]:
        """Extract all Doxygen-style comments."""
        comments = []
        for match in re.finditer(r'/\*\*([^*]|\*[^/])*\*/', source, re.DOTALL):
            inner = match.group(0)[3:-2]
            comments.append({
                "text": inner.strip(),
                "start": match.start(),
                "end": match.end(),
            })
        return comments

    def _get_comment_before(self, source: str, position: int) -> Optional[str]:
        """Get the Doxygen comment immediately before a code element."""
        before = source[:position].rstrip()
        match = re.search(r'/\*\*([^*]|\*[^/])*\*/', before, re.DOTALL)
        if match:
            after_comment = before[match.end():].strip()
            if after_comment == "":
                return match.group(0)[3:-2].strip()
        return None

    def _parse_c_params(self, params_str: str, func: DocFunction) -> None:
        """Parse C function parameters."""
        if not params_str or params_str.strip() == "void":
            return
        parts = self._split_by_commas(params_str)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            match = re.match(r'((?:const|volatile|unsigned|signed|struct|union|enum)\s+)?'
                            r'(\w+(?:\s*\*+)?)\s+(\w+)', part)
            if match:
                func.params.append(DocParam(
                    name=match.group(3),
                    type=(match.group(1) or "") + match.group(2).strip(),
                ))

    @staticmethod
    def _split_by_commas(s: str) -> List[str]:
        parts: List[str] = []
        depth = 0
        current: List[str] = []
        for ch in s:
            if ch == '(':
                depth += 1
                current.append(ch)
            elif ch == ')':
                depth -= 1
                current.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts


class RustDocParser:
    """Parse Rust source files with Rustdoc comments."""

    def parse(self, source: str, filepath: str = "") -> DocModule:
        """Parse Rust source into a DocModule."""
        name = os.path.splitext(os.path.basename(filepath))[0] if filepath else "module"
        if name == "mod":
            name = os.path.basename(os.path.dirname(filepath))

        module = DocModule(name=name, filepath=filepath, language="rust")

        # Module docstring
        mod_doc = self._extract_inner_doc(source)
        if mod_doc:
            parsed = DocstringParser.parse_rust(mod_doc)
            module.summary = parsed["summary"]
            module.description = parsed["description"]

        # Clean source for parsing
        clean = re.sub(r'///.*', '', source)
        clean = re.sub(r'//!.*', '', clean)
        clean = re.sub(r'/\*[\s\S]*?\*/', '', clean)
        clean = re.sub(r'//.*', '', clean)

        # Extract functions
        fn_pattern = re.compile(
            r'(?:(?:pub\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+"[^"]*"\s+)?)?'
            r'fn\s+(\w+)(?:<\s*([^>]+)\s*>)?\s*\(([^)]*)\)'
            r'(?:\s*->\s*([^{;]+))?',
        )

        for match in fn_pattern.finditer(source):
            name = match.group(1)
            params_str = match.group(3) or ""
            return_type = match.group(4)

            # Skip if in impl/trait block
            before = source[:match.start()]
            if re.search(r'\b(impl|trait)\b', before):
                continue

            func = DocFunction(
                name=name,
                qualname=name,
                signature=f"fn {name}({params_str})" + (f" -> {return_type.strip()}" if return_type else ""),
                line_number=source[:match.start()].count("\n") + 1,
                source_file=filepath,
                is_async="async" in before[-200:],
            )

            # Doc comment
            doc = self._extract_outer_doc(source, match.start())
            if doc:
                parsed = DocstringParser.parse_rust(doc)
                func.summary = parsed["summary"]
                func.description = parsed["description"]
                func.params = [DocParam(**p) for p in parsed["params"]]
                if parsed["returns"]:
                    func.returns = parsed["returns"]

            # Parameters from signature
            self._parse_rust_params(params_str, func)

            module.functions.append(func)

        # Extract structs
        struct_pattern = re.compile(r'(?:pub\s+)?struct\s+(\w+)(?:<\s*([^>]+)\s*>)?\s*\{')
        for match in struct_pattern.finditer(source):
            cls = DocClass(
                name=match.group(1),
                line_number=source[:match.start()].count("\n") + 1,
            )
            doc = self._extract_outer_doc(source, match.start())
            if doc:
                parsed = DocstringParser.parse_rust(doc)
                cls.summary = parsed["summary"]
            module.classes.append(cls)

        # Extract enums
        enum_pattern = re.compile(r'(?:pub\s+)?enum\s+(\w+)(?:<\s*([^>]+)\s*>)?\s*\{')
        for match in enum_pattern.finditer(source):
            cls = DocClass(
                name=match.group(1),
                line_number=source[:match.start()].count("\n") + 1,
            )
            doc = self._extract_outer_doc(source, match.start())
            if doc:
                parsed = DocstringParser.parse_rust(doc)
                cls.summary = parsed["summary"]
            module.classes.append(cls)

        # Extract traits
        trait_pattern = re.compile(r'(?:pub\s+)?(?:unsafe\s+)?trait\s+(\w+)(?:<\s*([^>]+)\s*>)?')
        for match in trait_pattern.finditer(source):
            cls = DocClass(
                name=match.group(1),
                line_number=source[:match.start()].count("\n") + 1,
                is_interface=True,
                is_abstract=True,
            )
            doc = self._extract_outer_doc(source, match.start())
            if doc:
                parsed = DocstringParser.parse_rust(doc)
                cls.summary = parsed["summary"]
            module.classes.append(cls)

        return module

    def _extract_inner_doc(self, source: str) -> Optional[str]:
        """Extract inner doc comment (//! or /*! ... */)."""
        lines = []
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith("//!"):
                lines.append(stripped[3:])
        if lines:
            return "\n".join(lines)
        block_match = re.search(r'/\*!([^*]|\*[^/])*\*/', source, re.DOTALL)
        if block_match:
            return block_match.group(0)[3:-2].strip()
        return None

    def _extract_outer_doc(self, source: str, position: int) -> Optional[str]:
        """Extract outer doc comment (///) before a position."""
        before = source[:position].rstrip()
        lines = []
        for line in before.split("\n")[-20:]:
            stripped = line.strip()
            if stripped.startswith("///"):
                lines.append(stripped[3:])
            elif stripped == "" or stripped == "}":
                if lines:
                    break
            else:
                if lines:
                    break
        if lines:
            lines.reverse()
            return "\n".join(lines)
        block_match = re.search(r'/\*\*([^*]|\*[^/])*\*/', before, re.DOTALL)
        if block_match:
            after_comment = before[block_match.end():].strip()
            if after_comment == "":
                return block_match.group(0)[3:-2].strip()
        return None

    def _parse_rust_params(self, params_str: str, func: DocFunction) -> None:
        """Parse Rust function parameters."""
        if not params_str.strip():
            return
        parts = self._split_by_commas(params_str)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part in ("self", "&self", "&mut self"):
                continue
            match = re.match(r'(?:mut\s+)?(\w+)\s*:\s*(.+)', part)
            if match:
                func.params.append(DocParam(
                    name=match.group(1),
                    type=match.group(2).strip(),
                ))

    @staticmethod
    def _split_by_commas(s: str) -> List[str]:
        parts: List[str] = []
        depth = 0
        current: List[str] = []
        for ch in s:
            if ch in '<(':
                depth += 1
                current.append(ch)
            elif ch in ')>':
                depth -= 1
                current.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts


class JavaDocParser:
    """Parse Java source files with Javadoc comments."""

    def parse(self, source: str, filepath: str = "") -> DocModule:
        """Parse Java source into a DocModule."""
        name = os.path.splitext(os.path.basename(filepath))[0] if filepath else "module"
        module = DocModule(name=name, filepath=filepath, language="java")

        # Extract package declaration
        pkg_match = re.search(r'package\s+([\w.]+);', source)
        if pkg_match:
            name = pkg_match.group(1)
            module.name = name

        # Extract imports
        for match in re.finditer(r'import\s+([\w.*]+);', source):
            module.imports.append(match.group(1))

        # Clean source
        clean = re.sub(r'//.*', '', source)

        # Extract classes
        class_pattern = re.compile(
            r'(?:/\*\*([^*]|\*[^/])*\*/\s*)?'
            r'(?:public\s+)?(?:abstract\s+)?(?:final\s+)?'
            r'(?:class|interface|@interface|enum)\s+(\w+)'
            r'(?:\s*extends\s+(\w+))?'
            r'(?:\s*implements\s+([^{]+))?'
            r'\s*\{',
            re.DOTALL,
        )

        for match in class_pattern.finditer(source):
            doc = match.group(1)
            cls_name = match.group(2)
            extends = match.group(3) or ""
            implements = match.group(4) or ""

            cls = DocClass(
                name=cls_name,
                qualname=f"{module.name}.{cls_name}" if module.name else cls_name,
                line_number=source[:match.start()].count("\n") + 1,
            )

            if doc:
                parsed = DocstringParser.parse_java(doc.strip())
                cls.summary = parsed["summary"]
                cls.description = parsed["description"]

            if extends:
                cls.bases.append(extends.strip())
            if implements:
                for iface in implements.split(","):
                    cls.bases.append(iface.strip())

            module.classes.append(cls)

        # Extract functions (standalone, not in classes)
        # This is simplified — Java functions are almost always in classes
        func_pattern = re.compile(
            r'(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?'
            r'(\w+(?:<[^>]+>)?)\s+(\w+)\s*\(([^)]*)\)\s*(?:\{|throws\s+\w+)?',
            re.MULTILINE,
        )

        for match in func_pattern.finditer(clean):
            ret_type = match.group(1).strip()
            func_name = match.group(2)
            params_str = match.group(3).strip()

            func = DocFunction(
                name=func_name,
                signature=f"{ret_type} {func_name}({params_str})",
                line_number=source[:match.start()].count("\n") + 1,
                source_file=filepath,
            )

            # Find preceding doc comment
            before = source[:match.start()]
            doc_match = re.search(r'/\*\*([^*]|\*[^/])*\*/', before, re.DOTALL)
            if doc_match:
                after = before[doc_match.end():].strip()
                if after == "":
                    parsed = DocstringParser.parse_java(doc_match.group(0)[3:-2].strip())
                    func.summary = parsed["summary"]
                    func.description = parsed["description"]
                    func.params = [DocParam(**p) for p in parsed["params"]]
                    if parsed["returns"]:
                        func.returns = parsed["returns"]

            # Parse parameters
            if params_str and params_str != "void":
                for param_str in params_str.split(","):
                    param_str = param_str.strip()
                    parts = param_str.rsplit(None, 1)
                    if len(parts) == 2:
                        func.params.append(DocParam(name=parts[1], type=parts[0]))

            module.functions.append(func)

        return module


class GoDocParser:
    """Parse Go source files with Go comments."""

    def parse(self, source: str, filepath: str = "") -> DocModule:
        """Parse Go source into a DocModule."""
        name = os.path.splitext(os.path.basename(filepath))[0] if filepath else "module"
        module = DocModule(name=name, filepath=filepath, language="go")

        # Package declaration
        pkg_match = re.search(r'^package\s+(\w+)', source, re.MULTILINE)
        if pkg_match:
            module.name = pkg_match.group(1)

        # Extract imports
        in_import = False
        for line in source.split("\n"):
            if line.strip().startswith("import ("):
                in_import = True
            elif in_import and line.strip().startswith(")"):
                in_import = False
            elif in_import and line.strip():
                import_path = line.strip().strip('"')
                if import_path:
                    module.imports.append(import_path)
            import_match = re.match(r'import\s+"([^"]+)"', line)
            if import_match:
                module.imports.append(import_match.group(1))

        # Extract functions
        func_pattern = re.compile(
            r'(?:func\s+)(?:\w+\s+)?(\w+)\s*\(([^)]*)\)\s*(?:\(?([^;{]*?)\)?\s*)?(?:\{|;)',
            re.MULTILINE,
        )

        # Collect comments before functions
        comment_map = self._extract_go_comments(source)

        for match in func_pattern.finditer(source):
            name = match.group(1)
            params_str = match.group(2).strip()
            ret_str = match.group(3) or ""

            if name[0].islower():
                continue  # Skip unexported functions

            func = DocFunction(
                name=name,
                signature=f"func {name}({params_str}) {ret_str}",
                line_number=source[:match.start()].count("\n") + 1,
                source_file=filepath,
            )

            # Doc comment
            doc = comment_map.get(match.start(), "")
            if doc:
                parsed = DocstringParser.parse_go(doc)
                func.summary = parsed["summary"]
                func.description = parsed["description"]

            # Parse parameters
            if params_str:
                for param_str in params_str.split(","):
                    param_str = param_str.strip()
                    if param_str:
                        parts = param_str.rsplit(None, 1)
                        if len(parts) == 2:
                            func.params.append(DocParam(name=parts[1], type=parts[0]))

            module.functions.append(func)

        # Extract types (structs, interfaces)
        type_pattern = re.compile(
            r'(?:type\s+)(\w+)\s+(struct|interface)\s*\{',
            re.MULTILINE,
        )
        for match in type_pattern.finditer(source):
            cls = DocClass(
                name=match.group(1),
                line_number=source[:match.start()].count("\n") + 1,
                is_interface=match.group(2) == "interface",
            )
            doc = comment_map.get(match.start(), "")
            if doc:
                parsed = DocstringParser.parse_go(doc)
                cls.summary = parsed["summary"]
            module.classes.append(cls)

        return module

    def _extract_go_comments(self, source: str) -> Dict[int, str]:
        """Extract Go comments and map them to positions."""
        comment_map: Dict[int, str] = {}
        lines = source.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            # Single-line comment
            if stripped.startswith("//"):
                comment_lines = []
                while i < len(lines) and lines[i].strip().startswith("//"):
                    comment_lines.append(lines[i].strip()[2:].strip())
                    i += 1
                # Skip blank lines
                while i < len(lines) and not lines[i].strip():
                    i += 1
                if i < len(lines):
                    pos = sum(len(l) + 1 for l in lines[:i])
                    comment_map[pos] = "\n".join(comment_lines)
            else:
                i += 1
        return comment_map


# ---------------------------------------------------------------------------
# Documentation Generator
# ---------------------------------------------------------------------------

class DocGenerator:
    """Generate documentation from parsed source data."""

    def __init__(self) -> None:
        self.python_parser = PythonDocParser()
        self.c_parser = CWithDocParser()
        self.rust_parser = RustDocParser()
        self.java_parser = JavaDocParser()
        self.go_parser = GoDocParser()

    def parse_file(self, filepath: str) -> Optional[DocModule]:
        """Parse a source file and return a DocModule."""
        ext = os.path.splitext(filepath)[1].lower()
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError as e:
            return None

        if ext == ".py":
            try:
                return self.python_parser.parse(source, filepath)
            except (ValueError, SyntaxError) as e:
                return None
        elif ext in (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh"):
            return self.c_parser.parse(source, filepath)
        elif ext == ".rs":
            return self.rust_parser.parse(source, filepath)
        elif ext == ".java":
            return self.java_parser.parse(source, filepath)
        elif ext == ".go":
            return self.go_parser.parse(source, filepath)
        return None

    def parse_directory(self, directory: str, recursive: bool = True) -> DocResult:
        """Parse all source files in a directory."""
        result = DocResult()
        start_time = time.time()

        for root, dirs, files in os.walk(directory):
            if not recursive and root != directory:
                break
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    fpath = os.path.join(root, f)
                    try:
                        module = self.parse_file(fpath)
                        if module:
                            result.modules[fpath] = module
                    except Exception as e:
                        result.errors.append(f"Failed to parse {fpath}: {e}")

        result.duration_ms = (time.time() - start_time) * 1000
        return result


# ---------------------------------------------------------------------------
# Output generators
# ---------------------------------------------------------------------------

class MarkdownDocWriter:
    """Generate Markdown documentation."""

    def write(self, result: DocResult, title: str = "API Documentation") -> str:
        """Generate Markdown from DocResult."""
        lines: List[str] = []
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"*Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*")
        lines.append("")
        lines.append(f"**Files:** {len(result.modules)} | **Duration:** {result.duration_ms:.0f}ms")
        lines.append("")

        for filepath, module in sorted(result.modules.items()):
            rel_path = os.path.relpath(filepath) if filepath else module.name
            lines.append(f"---")
            lines.append(f"## Module: `{module.name}`")
            lines.append("")
            lines.append(f"**File:** `{rel_path}` | **Language:** {module.language}")
            lines.append("")
            if module.summary:
                lines.append(module.summary)
                lines.append("")
            if module.description:
                lines.append(module.description)
                lines.append("")

            # Functions
            if module.functions:
                lines.append("### Functions")
                lines.append("")
                for func in module.functions:
                    lines.append(f"#### `{func.signature}`")
                    lines.append("")
                    if func.summary:
                        lines.append(f"{func.summary}")
                        lines.append("")
                    if func.params:
                        lines.append("**Parameters:**")
                        lines.append("")
                        lines.append("| Name | Type | Description | Required |")
                        lines.append("|------|------|-------------|----------|")
                        for p in func.params:
                            req = "Yes" if p.required else "No"
                            lines.append(f"| `{p.name}` | `{p.type}` | {p.description} | {req} |")
                        lines.append("")
                    if func.returns:
                        lines.append(f"**Returns:** {func.returns.get('type', '')} - {func.returns.get('description', '')}")
                        lines.append("")
                    if func.raises:
                        lines.append("**Raises:**")
                        for r in func.raises:
                            lines.append(f"- `{r['type']}`: {r['description']}")
                        lines.append("")
                    if func.examples:
                        lines.append("**Examples:**")
                        for ex in func.examples:
                            lines.append(f"```")
                            lines.append(ex)
                            lines.append("```")
                        lines.append("")
                    if func.deprecation:
                        lines.append(f"> **Deprecated:** {func.deprecation}")
                        lines.append("")
                lines.append("")

            # Classes
            if module.classes:
                lines.append("### Classes")
                lines.append("")
                for cls in module.classes:
                    bases_str = f"({', '.join(cls.bases)})" if cls.bases else ""
                    lines.append(f"#### `{cls.name}{bases_str}`")
                    lines.append("")
                    if cls.summary:
                        lines.append(f"{cls.summary}")
                        lines.append("")
                    if cls.methods:
                        lines.append("**Methods:**")
                        lines.append("")
                        for method in cls.methods:
                            lines.append(f"- `{method.signature}`")
                            if method.summary:
                                lines.append(f"  - {method.summary}")
                        lines.append("")

            # Constants
            if module.constants:
                lines.append("### Constants")
                lines.append("")
                for const in module.constants:
                    lines.append(f"- `{const['name']}` = `{const.get('value', '')}`")
                lines.append("")

            # TODOs
            if module.todos:
                lines.append("### TODOs")
                lines.append("")
                for todo in module.todos:
                    lines.append(f"- Line {todo['line']}: {todo['text']}")
                lines.append("")

            # FIXMEs
            if module.fixmes:
                lines.append("### FIXMEs")
                lines.append("")
                for fixme in module.fixmes:
                    lines.append(f"- Line {fixme['line']}: {fixme['text']}")
                lines.append("")

        return "\n".join(lines)


class HTMLDocWriter:
    """Generate HTML documentation."""

    CSS = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               line-height: 1.6; color: #333; max-width: 960px; margin: 0 auto; padding: 20px; }
        h1 { border-bottom: 2px solid #4A90D9; padding-bottom: 10px; color: #2c3e50; }
        h2 { color: #2c3e50; margin-top: 30px; border-bottom: 1px solid #eee; }
        h3 { color: #34495e; }
        h4 { color: #555; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
        pre { background: #f8f8f8; padding: 12px; border-radius: 4px; overflow-x: auto; }
        table { border-collapse: collapse; width: 100%; margin: 10px 0; }
        th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
        th { background: #f5f5f5; font-weight: 600; }
        .module { background: #f9f9f9; padding: 15px; border-radius: 6px; margin: 15px 0; }
        .func { margin: 20px 0; padding: 15px; border-left: 3px solid #4A90D9; background: #fafafa; }
        .class { margin: 20px 0; padding: 15px; border-left: 3px solid #27ae60; background: #fafafa; }
        .todo { background: #fff3cd; padding: 8px; border-radius: 4px; }
        .fixme { background: #f8d7da; padding: 8px; border-radius: 4px; }
        .deprecated { background: #e2e3e5; padding: 8px; border-radius: 4px; text-decoration: line-through; }
        .summary { font-size: 1.1em; color: #666; }
        .nav { position: fixed; top: 0; right: 0; width: 250px; height: 100%;
               background: #f8f9fa; border-left: 1px solid #ddd; padding: 15px;
               overflow-y: auto; font-size: 0.9em; }
        .nav a { display: block; padding: 3px 0; color: #4A90D9; text-decoration: none; }
        .nav a:hover { text-decoration: underline; }
        .content { margin-right: 270px; }
    </style>
    """

    def write(self, result: DocResult, title: str = "API Documentation") -> str:
        """Generate HTML from DocResult."""
        lines: List[str] = []
        lines.append("<!DOCTYPE html>")
        lines.append('<html lang="en">')
        lines.append("<head>")
        lines.append(f'<meta charset="UTF-8">')
        lines.append(f'<title>{title}</title>')
        lines.append(self.CSS)
        lines.append("</head>")
        lines.append("<body>")
        lines.append(f'<div class="nav">')
        lines.append(f'<h3>Navigation</h3>')
        for filepath, module in sorted(result.modules.items()):
            anchor = f"module-{module.name}"
            lines.append(f'<a href="#{anchor}">{module.name}</a>')
            if module.functions:
                lines.append(f'<div style="padding-left:12px;">')
                for func in module.functions:
                    lines.append(f'<a href="#func-{func.qualname}">{func.name}()</a>')
                lines.append('</div>')
        lines.append('</div>')
        lines.append(f'<div class="content">')
        lines.append(f'<h1>{title}</h1>')
        lines.append(f'<p class="summary">Generated on {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}')
        lines.append(f'<br>Files: {len(result.modules)} | Duration: {result.duration_ms:.0f}ms</p>')

        for filepath, module in sorted(result.modules.items()):
            rel_path = os.path.relpath(filepath) if filepath else module.name
            lines.append(f'<div class="module" id="module-{module.name}">')
            lines.append(f'<h2>{module.name}</h2>')
            lines.append(f'<p><strong>File:</strong> <code>{rel_path}</code> | <strong>Language:</strong> {module.language}</p>')
            if module.summary:
                lines.append(f'<p>{self._escape_html(module.summary)}</p>')

            if module.functions:
                lines.append('<h3>Functions</h3>')
                for func in module.functions:
                    lines.append(f'<div class="func" id="func-{func.qualname}">')
                    lines.append(f'<h4><code>{self._escape_html(func.signature)}</code></h4>')
                    if func.summary:
                        lines.append(f'<p>{self._escape_html(func.summary)}</p>')
                    if func.params:
                        lines.append('<table><tr><th>Name</th><th>Type</th><th>Description</th><th>Required</th></tr>')
                        for p in func.params:
                            req = "Yes" if p.required else "No"
                            lines.append(f'<tr><td><code>{p.name}</code></td><td><code>{p.type}</code></td>'
                                        f'<td>{self._escape_html(p.description)}</td><td>{req}</td></tr>')
                        lines.append('</table>')
                    if func.returns:
                        lines.append(f'<p><strong>Returns:</strong> {self._escape_html(str(func.returns))}</p>')
                    if func.deprecation:
                        lines.append(f'<div class="deprecated">Deprecated: {self._escape_html(func.deprecation)}</div>')
                    lines.append('</div>')

            if module.classes:
                lines.append('<h3>Classes</h3>')
                for cls in module.classes:
                    lines.append(f'<div class="class">')
                    lines.append(f'<h4>{cls.name}</h4>')
                    if cls.summary:
                        lines.append(f'<p>{self._escape_html(cls.summary)}</p>')
                    if cls.methods:
                        lines.append('<ul>')
                        for method in cls.methods:
                            lines.append(f'<li><code>{self._escape_html(method.signature)}</code>')
                            if method.summary:
                                lines.append(f' - {self._escape_html(method.summary)}')
                            lines.append('</li>')
                        lines.append('</ul>')
                    lines.append('</div>')

            if module.todos:
                lines.append('<h3>TODOs</h3>')
                for todo in module.todos:
                    lines.append(f'<div class="todo">Line {todo["line"]}: {self._escape_html(todo["text"])}</div>')

            if module.fixmes:
                lines.append('<h3>FIXMEs</h3>')
                for fixme in module.fixmes:
                    lines.append(f'<div class="fixme">Line {fixme["line"]}: {self._escape_html(fixme["text"])}</div>')

            lines.append('</div>')

        lines.append('</div>')
        lines.append("</body>")
        lines.append("</html>")
        return "\n".join(lines)

    def _escape_html(self, s: str) -> str:
        s = s.replace("&", "&amp;")
        s = s.replace("<", "&lt;")
        s = s.replace(">", "&gt;")
        s = s.replace('"', "&quot;")
        return s


class OpenAPIDocWriter:
    """Generate OpenAPI/Swagger specification from doc data."""

    def write(self, result: DocResult, title: str = "API Specification") -> str:
        """Generate OpenAPI 3.0 spec."""
        spec: Dict[str, Any] = {
            "openapi": "3.0.3",
            "info": {
                "title": title,
                "version": VERSION,
                "description": f"Generated by {APP_NAME} on {datetime.now(timezone.utc).isoformat()}",
            },
            "paths": {},
            "components": {
                "schemas": {},
            },
        }

        for filepath, module in sorted(result.modules.items()):
            for func in module.functions:
                # Convert function to an API endpoint
                path = f"/api/{module.name}/{func.name}"
                spec["paths"][path] = {
                    "get": {
                        "summary": func.summary or func.name,
                        "description": func.description or func.summary or "",
                        "parameters": [
                            {
                                "name": p.name,
                                "in": "query",
                                "description": p.description,
                                "required": p.required,
                                "schema": {"type": self._openapi_type(p.type)},
                            }
                            for p in func.params
                        ],
                        "responses": {
                            "200": {
                                "description": "Successful response",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": self._openapi_type(
                                                func.returns.get("type", "object") if func.returns else "object"
                                            ),
                                        }
                                    }
                                },
                            }
                        },
                    }
                }

        return json.dumps(spec, indent=2)

    def _openapi_type(self, type_str: str) -> str:
        """Map type hints to OpenAPI types."""
        if not type_str:
            return "object"
        if "int" in type_str:
            return "integer"
        if "float" in type_str or "double" in type_str:
            return "number"
        if "bool" in type_str:
            return "boolean"
        if "str" in type_str or "String" in type_str:
            return "string"
        if "list" in type_str or "List" in type_str or "array" in type_str:
            return "array"
        if "dict" in type_str or "Dict" in type_str or "map" in type_str:
            return "object"
        if "void" in type_str or "None" in type_str:
            return "null"
        return "string"


# ---------------------------------------------------------------------------
# Diagram generation (Mermaid/PlantUML)
# ---------------------------------------------------------------------------

class DiagramGenerator:
    """Generate Mermaid and PlantUML diagrams."""

    @staticmethod
    def class_diagram_mermaid(module: DocModule) -> str:
        """Generate a Mermaid class diagram."""
        lines: List[str] = ["classDiagram"]
        for cls in module.classes:
            if cls.bases:
                for base in cls.bases:
                    lines.append(f"    {cls.name} <|-- {base}")
            lines.append(f"    class {cls.name} {{")
            for attr in cls.attributes:
                lines.append(f"        +{attr.get('type', 'str')} {attr.get('name', '')}")
            for method in cls.methods:
                vis = "+" if not method.name.startswith("_") else "-"
                lines.append(f"        {vis}{method.name}()")
            lines.append("    }")
        return "\n".join(lines)

    @staticmethod
    def class_diagram_plantuml(module: DocModule) -> str:
        """Generate a PlantUML class diagram."""
        lines: List[str] = ["@startuml"]
        for cls in module.classes:
            if cls.bases:
                for base in cls.bases:
                    lines.append(f"{cls.name} --|> {base}")
            lines.append(f"class {cls.name} {{")
            for attr in cls.attributes:
                lines.append(f"    +{attr.get('type', 'str')} {attr.get('name', '')}")
            for method in cls.methods:
                vis = "+" if not method.name.startswith("_") else "-"
                lines.append(f"    {vis}{method.name}()")
            lines.append("}")
        lines.append("@enduml")
        return "\n".join(lines)

    @staticmethod
    def flow_diagram_mermaid(functions: List[DocFunction]) -> str:
        """Generate a Mermaid flow diagram for function call relationships."""
        lines: List[str] = ["flowchart TD"]
        for func in functions:
            lines.append(f"    {func.name}[{func.name}]")
            # Simple call inference from description
            calls = re.findall(r'\b(\w+)\(', func.description or "")
            for call in calls[:5]:
                lines.append(f"    {func.name} --> {call}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------

class WatchMode:
    """Watch source files for changes and regenerate documentation."""

    def __init__(self, generator: DocGenerator, writer: MarkdownDocWriter,
                 output_path: str, verbose: bool = False) -> None:
        self.generator = generator
        self.writer = writer
        self.output_path = output_path
        self.verbose = verbose
        self._file_hashes: Dict[str, str] = {}
        self._running = False

    def start(self, directories: List[str], interval: float = 1.0) -> None:
        """Start watching directories for changes."""
        self._running = True
        self._hash_files(directories)
        print(f"Watching {len(directories)} directories for changes...", file=sys.stderr)

        try:
            while self._running:
                time.sleep(interval)
                if self._check_changes(directories):
                    self._regenerate(directories)
        except KeyboardInterrupt:
            print("\nWatch mode stopped.", file=sys.stderr)
            self._running = False

    def stop(self) -> None:
        """Stop watching."""
        self._running = False

    def _hash_files(self, directories: List[str]) -> None:
        """Hash all watched files."""
        for directory in directories:
            for root, dirs, files in os.walk(directory):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        fpath = os.path.join(root, f)
                        try:
                            with open(fpath, "rb") as fh:
                                content = fh.read()
                            self._file_hashes[fpath] = hashlib.md5(content).hexdigest()
                        except OSError:
                            pass

    def _check_changes(self, directories: List[str]) -> bool:
        """Check if any files have changed."""
        changed = False
        for directory in directories:
            for root, dirs, files in os.walk(directory):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        fpath = os.path.join(root, f)
                        try:
                            with open(fpath, "rb") as fh:
                                content = fh.read()
                            new_hash = hashlib.md5(content).hexdigest()
                            if fpath in self._file_hashes:
                                if self._file_hashes[fpath] != new_hash:
                                    if self.verbose:
                                        print(f"  Changed: {fpath}", file=sys.stderr)
                                    changed = True
                            self._file_hashes[fpath] = new_hash
                        except OSError:
                            pass
        return changed

    def _regenerate(self, directories: List[str]) -> None:
        """Regenerate documentation after changes."""
        result = DocResult()
        for directory in directories:
            dir_result = self.generator.parse_directory(directory)
            result.modules.update(dir_result.modules)
            result.errors.extend(dir_result.errors)

        doc = self.writer.write(result)
        try:
            Path(self.output_path).write_text(doc, encoding="utf-8")
            print(f"  Regenerated: {self.output_path} ({datetime.now().strftime('%H:%M:%S')})",
                  file=sys.stderr)
        except OSError as e:
            print(f"  Error writing: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Serve mode
# ---------------------------------------------------------------------------

class DocHTTPServer:
    """Simple HTTP server for serving documentation."""

    def __init__(self, doc_path: str, port: int = 8080) -> None:
        self.doc_path = doc_path
        self.port = port
        self._server: Optional[socketserver.TCPServer] = None

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=kwargs.pop("directory", "."), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]} {args[2]}\n")

    def start(self, open_browser: bool = False) -> None:
        """Start the HTTP server."""
        os.chdir(self.doc_path)
        handler = self._create_handler()
        try:
            self._server = socketserver.TCPServer(("", self.port), handler)
            if open_browser:
                webbrowser.open(f"http://localhost:{self.port}")
            print(f"Serving documentation at http://localhost:{self.port}", file=sys.stderr)
            print(f"Press Ctrl+C to stop.", file=sys.stderr)
            self._server.serve_forever()
        except OSError as e:
            print(f"Error starting server: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nServer stopped.", file=sys.stderr)
            if self._server:
                self._server.shutdown()

    def _create_handler(self):
        """Create a request handler for the doc path."""
        doc_path = self.doc_path
        class CustomHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=doc_path, **kwargs)
            def log_message(self, format: str, *args: Any) -> None:
                sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]} {args[2]}\n")
        return CustomHandler

    def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.shutdown()


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="AI-powered documentation generator for multiple languages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s generate src/                         # Generate Markdown docs
              %(prog)s generate src/ -f html -o docs/         # HTML output
              %(prog)s generate src/ -f openapi               # OpenAPI spec
              %(prog)s generate main.py --diagram mermaid     # With class diagram
              %(prog)s serve docs/                            # Serve docs via HTTP
              %(prog)s watch src/ docs/                       # Watch and regenerate
        """),
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ------------------------------------------------------------------ #
    # generate subcommand
    # ------------------------------------------------------------------ #
    gen_parser = subparsers.add_parser("generate", help="Generate documentation")
    gen_parser.add_argument("source", type=str, help="Source file or directory")
    gen_parser.add_argument("--output", "-o", type=str, default="",
                            help="Output file or directory (default: stdout)")
    gen_parser.add_argument("--format", "-f", choices=DOC_OUTPUT_FORMATS, default="markdown",
                            help="Output format (default: markdown)")
    gen_parser.add_argument("--title", type=str, default="API Documentation",
                            help="Document title")
    gen_parser.add_argument("--recursive", "-r", action="store_true", default=True,
                            help="Recurse into directories")
    gen_parser.add_argument("--diagram", choices=DIAGRAM_TYPES, default="none",
                            help="Generate diagrams (mermaid/plantuml/none)")
    gen_parser.add_argument("--json", action="store_true",
                            help="Also output raw JSON data")

    # ------------------------------------------------------------------ #
    # serve subcommand
    # ------------------------------------------------------------------ #
    serve_parser = subparsers.add_parser("serve", help="Serve documentation via HTTP")
    serve_parser.add_argument("doc_path", type=str, help="Documentation directory to serve")
    serve_parser.add_argument("--port", "-p", type=int, default=8080,
                              help="Port number (default: 8080)")
    serve_parser.add_argument("--open", action="store_true",
                              help="Open browser automatically")

    # ------------------------------------------------------------------ #
    # watch subcommand
    # ------------------------------------------------------------------ #
    watch_parser = subparsers.add_parser("watch", help="Watch source files and regenerate")
    watch_parser.add_argument("source", type=str, help="Source directory to watch")
    watch_parser.add_argument("output", type=str, help="Output file path")
    watch_parser.add_argument("--format", "-f", choices=DOC_OUTPUT_FORMATS, default="markdown",
                              help="Output format (default: markdown)")
    watch_parser.add_argument("--interval", type=float, default=1.0,
                              help="Polling interval in seconds (default: 1.0)")

    return parser


def cmd_generate(args: argparse.Namespace) -> int:
    """Handle the 'generate' subcommand."""
    gen = DocGenerator()
    source_path = args.source

    if os.path.isfile(source_path):
        module = gen.parse_file(source_path)
        result = DocResult()
        if module:
            result.modules[source_path] = module
    elif os.path.isdir(source_path):
        result = gen.parse_directory(source_path, recursive=args.recursive)
    else:
        print(f"Error: Path not found: {source_path}", file=sys.stderr)
        return 1

    if not result.modules:
        print(f"No supported source files found in {source_path}", file=sys.stderr)
        return 1

    # Generate output
    if args.format == "html":
        writer = HTMLDocWriter()
        output = writer.write(result, title=args.title)
    elif args.format == "openapi":
        writer = OpenAPIDocWriter()
        output = writer.write(result, title=args.title)
    elif args.format == "json":
        output = json.dumps({k: asdict(v) for k, v in result.modules.items()},
                           indent=2, default=str)
    else:
        writer = MarkdownDocWriter()
        output = writer.write(result, title=args.title)

    # Add diagrams if requested
    if args.diagram != "none" and result.modules:
        diagram_gen = DiagramGenerator()
        if args.diagram == "mermaid":
            for filepath, module in result.modules.items():
                if module.classes:
                    diagram = diagram_gen.class_diagram_mermaid(module)
                    output += f"\n\n## Class Diagram (Mermaid)\n\n```mermaid\n{diagram}\n```\n"
        elif args.diagram == "plantuml":
            for filepath, module in result.modules.items():
                if module.classes:
                    diagram = diagram_gen.class_diagram_plantuml(module)
                    output += f"\n\n## Class Diagram (PlantUML)\n\n```plantuml\n{diagram}\n```\n"

    # Output
    if args.output:
        output_path = args.output
        if os.path.isdir(output_path):
            ext_map = {"markdown": ".md", "html": ".html", "openapi": ".json", "json": ".json"}
            out_file = f"docs{ext_map.get(args.format, '.md')}"
            output_path = os.path.join(output_path, out_file)
        Path(output_path).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"Documentation written to {output_path}", file=sys.stderr)
    else:
        print(output)

    if args.verbose:
        print(f"\nParsed {len(result.modules)} files in {result.duration_ms:.0f}ms",
              file=sys.stderr)
        if result.errors:
            for err in result.errors:
                print(f"  Error: {err}", file=sys.stderr)

    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Handle the 'serve' subcommand."""
    doc_path = args.doc_path
    if not os.path.isdir(doc_path):
        print(f"Error: Not a directory: {doc_path}", file=sys.stderr)
        return 1

    server = DocHTTPServer(doc_path, port=args.port)
    server.start(open_browser=args.open)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Handle the 'watch' subcommand."""
    source_path = args.source
    output_path = args.output

    if not os.path.isdir(source_path):
        print(f"Error: Source is not a directory: {source_path}", file=sys.stderr)
        return 1

    gen = DocGenerator()
    writer = MarkdownDocWriter()

    # Initial generation
    result = gen.parse_directory(source_path)
    output = writer.write(result)
    Path(output_path).write_text(output, encoding="utf-8")
    print(f"Initial documentation generated: {output_path}", file=sys.stderr)

    # Watch mode
    watcher = WatchMode(gen, writer, output_path, verbose=args.verbose)
    watcher.start([source_path], interval=args.interval)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "generate":
        return cmd_generate(args)
    elif args.command == "serve":
        return cmd_serve(args)
    elif args.command == "watch":
        return cmd_watch(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())