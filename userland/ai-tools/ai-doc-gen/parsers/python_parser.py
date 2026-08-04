"""Python source code parser for AI Documentation Generator.

Extracts structured documentation data from Python source files using
the built-in AST module. Supports Google, NumPy, and Sphinx docstring styles.
"""

import ast
import re
import os
import textwrap
from typing import (
    Any, Dict, List, Optional, Tuple, Union,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class DocstringInfo:
    """Parsed docstring information."""

    def __init__(self):
        self.summary: str = ""
        self.description: str = ""
        self.params: List[Dict[str, str]] = []
        self.returns: Optional[Dict[str, str]] = None
        self.raises: List[Dict[str, str]] = []
        self.examples: List[str] = []
        self.notes: List[str] = []
        self.see_also: List[str] = []
        self.attributes: List[Dict[str, str]] = []
        self.style: str = "unknown"
        self.deprecated: Optional[str] = None
        self.yields: Optional[Dict[str, str]] = None
        self.references: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "description": self.description,
            "params": self.params,
            "returns": self.returns,
            "raises": self.raises,
            "examples": self.examples,
            "notes": self.notes,
            "see_also": self.see_also,
            "attributes": self.attributes,
            "style": self.style,
            "deprecated": self.deprecated,
            "yields": self.yields,
            "references": self.references,
        }


class ParameterInfo:
    """Information about a function/method parameter."""

    def __init__(self, name: str, type_hint: Optional[str] = None,
                 default_value: Optional[str] = None,
                 kind: str = "positional_or_keyword",
                 description: str = ""):
        self.name = name
        self.type_hint = type_hint
        self.default_value = default_value
        self.kind = kind  # positional_or_keyword, var_positional, keyword_only, var_keyword
        self.description = description
        self.required = default_value is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type_hint": self.type_hint,
            "default_value": self.default_value,
            "kind": self.kind,
            "description": self.description,
            "required": self.required,
        }


class FunctionInfo:
    """Information about a function or method."""

    def __init__(self, name: str, qualname: str = "",
                 lineno: int = 0, end_lineno: int = 0):
        self.name = name
        self.qualname = qualname or name
        self.lineno = lineno
        self.end_lineno = end_lineno
        self.params: List[ParameterInfo] = []
        self.return_type: Optional[str] = None
        self.docstring: DocstringInfo = DocstringInfo()
        self.decorators: List[str] = []
        self.is_async: bool = False
        self.is_generator: bool = False
        self.is_static: bool = False
        self.is_classmethod: bool = False
        self.is_property: bool = False
        self.is_abstract: bool = False
        self.body_summary: str = ""
        self.exceptions: List[str] = []
        self.source_code: str = ""
        self.modifiers: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "end_lineno": self.end_lineno,
            "params": [p.to_dict() for p in self.params],
            "return_type": self.return_type,
            "docstring": self.docstring.to_dict(),
            "decorators": self.decorators,
            "is_async": self.is_async,
            "is_generator": self.is_generator,
            "is_static": self.is_static,
            "is_classmethod": self.is_classmethod,
            "is_property": self.is_property,
            "is_abstract": self.is_abstract,
            "body_summary": self.body_summary,
            "exceptions": self.exceptions,
            "modifiers": self.modifiers,
        }


class ClassInfo:
    """Information about a class."""

    def __init__(self, name: str, qualname: str = "",
                 lineno: int = 0, end_lineno: int = 0):
        self.name = name
        self.qualname = qualname or name
        self.lineno = lineno
        self.end_lineno = end_lineno
        self.bases: List[str] = []
        self.decorators: List[str] = []
        self.docstring: DocstringInfo = DocstringInfo()
        self.methods: List[FunctionInfo] = []
        self.class_vars: List[Dict[str, Any]] = []
        self.instance_vars: List[Dict[str, Any]] = []
        self.inner_classes: List["ClassInfo"] = []
        self.is_abstract: bool = False
        self.is_dataclass: bool = False
        self.is_enum: bool = False
        self.is_exception: bool = False
        self.is_namedtuple: bool = False
        self.metaclass: Optional[str] = None
        self.source_code: str = ""
        self.modifiers: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "end_lineno": self.end_lineno,
            "bases": self.bases,
            "decorators": self.decorators,
            "docstring": self.docstring.to_dict(),
            "methods": [m.to_dict() for m in self.methods],
            "class_vars": self.class_vars,
            "instance_vars": self.instance_vars,
            "inner_classes": [c.to_dict() for c in self.inner_classes],
            "is_abstract": self.is_abstract,
            "is_dataclass": self.is_dataclass,
            "is_enum": self.is_enum,
            "is_exception": self.is_exception,
            "modifiers": self.modifiers,
        }


class ModuleInfo:
    """Information about a module."""

    def __init__(self, name: str, filepath: str = ""):
        self.name = name
        self.filepath = filepath
        self.docstring: DocstringInfo = DocstringInfo()
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self.variables: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, str]] = []
        self.from_imports: List[Dict[str, str]] = []
        self.constants: List[Dict[str, Any]] = []
        self.type_aliases: List[Dict[str, str]] = []
        self.submodules: List[str] = []
        self.source_code: str = ""
        self.encoding: str = "utf-8"
        self.shebang: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "filepath": self.filepath,
            "docstring": self.docstring.to_dict(),
            "functions": [f.to_dict() for f in self.functions],
            "classes": [c.to_dict() for c in self.classes],
            "variables": self.variables,
            "imports": self.imports,
            "from_imports": self.from_imports,
            "constants": self.constants,
            "type_aliases": self.type_aliases,
            "submodules": self.submodules,
            "encoding": self.encoding,
        }


class ParsedDocumentation:
    """Top-level container for parsed documentation."""

    def __init__(self, source_file: str = "", language: str = "python"):
        self.source_file = source_file
        self.language = language
        self.module: Optional[ModuleInfo] = None
        self.global_functions: List[FunctionInfo] = []
        self.global_classes: List[ClassInfo] = []
        self.global_variables: List[Dict[str, Any]] = []
        self.comments: List[Dict[str, Any]] = []
        self.todos: List[Dict[str, Any]] = []
        self.fixmes: List[Dict[str, Any]] = []
        self.notes_list: List[Dict[str, Any]] = []
        self.raw_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file": self.source_file,
            "language": self.language,
            "module": self.module.to_dict() if self.module else None,
            "global_functions": [f.to_dict() for f in self.global_functions],
            "global_classes": [c.to_dict() for c in self.global_classes],
            "global_variables": self.global_variables,
            "comments": self.comments,
            "todos": self.todos,
            "fixmes": self.fixmes,
        }


# ---------------------------------------------------------------------------
# Docstring parsers
# ---------------------------------------------------------------------------

class DocstringParser:
    """Parse docstrings in Google, NumPy, and Sphinx styles."""

    GOOGLE_SECTION_PATTERN = re.compile(
        r"^(Args|Arguments|Parameters|Keyword Args|Keyword Arguments|Kwargs|"
        r"Returns|Yields|Raises|Attributes|Note|Notes|Example|Examples|"
        r"References|See Also|Deprecated|Todo|Warning|Warnings)\s*:",
        re.MULTILINE | re.IGNORECASE
    )

    NUMPY_SECTION_PATTERN = re.compile(
        r"^(Parameters|Returns|Yields|Raises|Attributes|Notes|Examples|"
        r"References|See Also|Deprecated|Todo|Warning|Warnings|"
        r"Keyword Args|Keyword Arguments|Other Parameters)\s*\n[-=]+\s*$",
        re.MULTILINE
    )

    SPHINX_PARAM_PATTERN = re.compile(
        r":param\s+(\w+)\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )
    SPHINX_TYPE_PATTERN = re.compile(
        r":type\s+(\w+)\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|$)",
        re.DOTALL
    )
    SPHINX_RETURN_PATTERN = re.compile(
        r":returns?\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )
    SPHINX_RTYPE_PATTERN = re.compile(
        r":rtype\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )
    SPHINX_RAISE_PATTERN = re.compile(
        r":raises\s+(\w+)\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )
    SPHINX_YIELD_PATTERN = re.compile(
        r":yields?\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )
    SPHINX_DEPRECATED_PATTERN = re.compile(
        r":deprecated\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )
    SPHINX_NOTE_PATTERN = re.compile(
        r":note\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )
    SPHINX_EXAMPLE_PATTERN = re.compile(
        r":example\s*:\s*(.*?)(?=:param|:type|:returns|:raises|:yields|:rtype|:keyword|$)",
        re.DOTALL
    )

    @classmethod
    def parse(cls, docstring: str) -> DocstringInfo:
        """Parse a docstring and return structured information.

        Automatically detects the docstring style (Google, NumPy, Sphinx, or plain).

        Args:
            docstring: The raw docstring text

        Returns:
            DocstringInfo with parsed fields
        """
        info = DocstringInfo()
        if not docstring:
            return info

        docstring = textwrap.dedent(docstring).strip()

        # Detect style
        if cls._is_sphinx_style(docstring):
            info.style = "sphinx"
            cls._parse_sphinx(docstring, info)
        elif cls._is_numpy_style(docstring):
            info.style = "numpy"
            cls._parse_numpy(docstring, info)
        elif cls._is_google_style(docstring):
            info.style = "google"
            cls._parse_google(docstring, info)
        else:
            info.style = "plain"
            cls._parse_plain(docstring, info)

        return info

    @classmethod
    def _is_sphinx_style(cls, docstring: str) -> bool:
        return bool(re.search(r":param\s+\w+\s*:", docstring)) or bool(
            re.search(r":returns?\s*:", docstring)
        )

    @classmethod
    def _is_numpy_style(cls, docstring: str) -> bool:
        lines = docstring.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped in ("Parameters", "Returns", "Yields", "Raises", "Attributes"):
                if i + 1 < len(lines) and re.match(r"^[-=]+\s*$", lines[i + 1]):
                    return True
        return False

    @classmethod
    def _is_google_style(cls, docstring: str) -> bool:
        return bool(cls.GOOGLE_SECTION_PATTERN.search(docstring))

    @classmethod
    def _parse_plain(cls, docstring: str, info: DocstringInfo) -> None:
        """Parse a plain (no style) docstring."""
        lines = docstring.strip().split("\n")
        if not lines:
            return

        # First line is the summary
        info.summary = lines[0].strip()

        # Rest is description
        if len(lines) > 1:
            desc_lines = []
            for line in lines[1:]:
                stripped = line.strip()
                if stripped:
                    desc_lines.append(stripped)
            info.description = " ".join(desc_lines)

    @classmethod
    def _parse_google(cls, docstring: str, info: DocstringInfo) -> None:
        """Parse Google-style docstring."""
        lines = docstring.split("\n")
        current_section = None
        current_param = None
        summary_done = False
        desc_lines = []

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Check for section headers
            section_match = re.match(
                r"^(Args|Arguments|Parameters|Keyword Args|Keyword Arguments|"
                r"Kwargs|Returns|Yields|Raises|Attributes|Note|Notes|Example|"
                r"Examples|References|See Also|Deprecated|Todo|Warning|Warnings)\s*:",
                stripped, re.IGNORECASE
            )
            if section_match:
                if not summary_done and desc_lines:
                    info.summary = desc_lines[0] if desc_lines else ""
                    info.description = " ".join(desc_lines[1:]) if len(desc_lines) > 1 else ""
                    summary_done = True
                current_section = section_match.group(1).lower()
                current_param = None
                i += 1
                continue

            if current_section:
                if current_section in ("args", "arguments", "parameters", "keyword args",
                                        "keyword arguments", "kwargs"):
                    # Param line: name (type): description
                    param_match = re.match(
                        r"(\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)", stripped
                    )
                    if param_match:
                        current_param = {
                            "name": param_match.group(1),
                            "type": (param_match.group(2) or "").strip(),
                            "description": param_match.group(3).strip(),
                        }
                        info.params.append(current_param)
                    elif current_param and stripped:
                        # Continuation of previous param description
                        current_param["description"] += " " + stripped

                elif current_section == "returns":
                    ret_match = re.match(
                        r"(?:(\w+)\s*:\s*)?(.*)", stripped
                    )
                    if ret_match:
                        if info.returns is None:
                            info.returns = {}
                        info.returns["type"] = (ret_match.group(1) or "").strip()
                        info.returns["description"] = ret_match.group(2).strip()
                    elif info.returns:
                        info.returns["description"] += " " + stripped

                elif current_section == "yields":
                    yld_match = re.match(
                        r"(?:(\w+)\s*:\s*)?(.*)", stripped
                    )
                    if yld_match:
                        if info.yields is None:
                            info.yields = {}
                        info.yields["type"] = (yld_match.group(1) or "").strip()
                        info.yields["description"] = yld_match.group(2).strip()
                    elif info.yields:
                        info.yields["description"] += " " + stripped

                elif current_section == "raises":
                    raise_match = re.match(
                        r"(\w+(?:\.\w+)*)\s*:\s*(.*)", stripped
                    )
                    if raise_match:
                        info.raises.append({
                            "type": raise_match.group(1),
                            "description": raise_match.group(2).strip(),
                        })

                elif current_section == "attributes":
                    attr_match = re.match(
                        r"(\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)", stripped
                    )
                    if attr_match:
                        info.attributes.append({
                            "name": attr_match.group(1),
                            "type": (attr_match.group(2) or "").strip(),
                            "description": attr_match.group(3).strip(),
                        })

                elif current_section in ("note", "notes"):
                    if stripped:
                        info.notes.append(stripped)

                elif current_section in ("example", "examples"):
                    if stripped:
                        info.examples.append(stripped)

                elif current_section == "deprecated":
                    if info.deprecated is None:
                        info.deprecated = stripped
                    else:
                        info.deprecated += " " + stripped

                elif current_section == "references":
                    if stripped:
                        info.references.append(stripped)

                elif current_section == "see also":
                    if stripped:
                        info.see_also.append(stripped)

            else:
                # Before any section header
                if stripped and not summary_done:
                    desc_lines.append(stripped)

            i += 1

        # If no section headers found, treat whole docstring as plain
        if not summary_done and desc_lines:
            info.summary = desc_lines[0] if desc_lines else ""
            info.description = " ".join(desc_lines[1:]) if len(desc_lines) > 1 else ""

    @classmethod
    def _parse_numpy(cls, docstring: str, info: DocstringInfo) -> None:
        """Parse NumPy-style docstring."""
        lines = docstring.split("\n")
        current_section = None
        current_param = None
        summary_done = False
        desc_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Check for section headers (word followed by --- or ===)
            section_header = None
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and all(c in "-=" for c in next_line):
                    section_words = {
                        "parameters", "returns", "yields", "raises",
                        "attributes", "notes", "examples", "references",
                        "see also", "deprecated", "todo", "warning",
                        "warnings", "keyword args", "keyword arguments",
                        "other parameters", "note",
                    }
                    if stripped.lower() in section_words:
                        section_header = stripped.lower()
                        i += 2  # Skip header and underline
                        continue

            if section_header:
                if not summary_done and desc_lines:
                    info.summary = desc_lines[0] if desc_lines else ""
                    info.description = " ".join(desc_lines[1:]) if len(desc_lines) > 1 else ""
                    summary_done = True
                current_section = section_header
                current_param = None
                continue

            if current_section:
                if current_section == "parameters":
                    # Parameter name : type
                    param_match = re.match(r"(\w+)\s*:\s*(.*)", stripped)
                    if param_match:
                        current_param = {
                            "name": param_match.group(1),
                            "type": param_match.group(2).strip(),
                            "description": "",
                        }
                        info.params.append(current_param)
                    elif current_param and stripped:
                        if current_param["description"]:
                            current_param["description"] += " " + stripped
                        else:
                            current_param["description"] = stripped

                elif current_section == "returns":
                    ret_match = re.match(r"(?:(\w+)\s*:\s*)?(.*)", stripped)
                    if ret_match:
                        if info.returns is None:
                            info.returns = {}
                        if ret_match.group(1):
                            info.returns["type"] = ret_match.group(1).strip()
                        if ret_match.group(2):
                            info.returns["description"] = ret_match.group(2).strip()
                    elif info.returns and stripped:
                        info.returns["description"] += " " + stripped

                elif current_section == "yields":
                    yld_match = re.match(r"(?:(\w+)\s*:\s*)?(.*)", stripped)
                    if yld_match:
                        if info.yields is None:
                            info.yields = {}
                        if yld_match.group(1):
                            info.yields["type"] = yld_match.group(1).strip()
                        if yld_match.group(2):
                            info.yields["description"] = yld_match.group(2).strip()
                    elif info.yields and stripped:
                        info.yields["description"] += " " + stripped

                elif current_section == "raises":
                    raise_match = re.match(r"(\w+(?:\.\w+)*)\s*:\s*(.*)", stripped)
                    if raise_match:
                        info.raises.append({
                            "type": raise_match.group(1),
                            "description": raise_match.group(2).strip(),
                        })

                elif current_section == "attributes":
                    attr_match = re.match(r"(\w+)\s*:\s*(.*)", stripped)
                    if attr_match:
                        info.attributes.append({
                            "name": attr_match.group(1),
                            "type": attr_match.group(2).strip(),
                            "description": "",
                        })

                elif current_section in ("notes", "note"):
                    if stripped:
                        info.notes.append(stripped)

                elif current_section in ("examples", "example"):
                    if stripped:
                        info.examples.append(stripped)

                elif current_section == "deprecated":
                    if info.deprecated is None:
                        info.deprecated = stripped
                    else:
                        info.deprecated += " " + stripped

                elif current_section == "references":
                    if stripped:
                        info.references.append(stripped)

            else:
                if stripped and not summary_done:
                    desc_lines.append(stripped)

            i += 1

        if not summary_done and desc_lines:
            info.summary = desc_lines[0] if desc_lines else ""
            info.description = " ".join(desc_lines[1:]) if len(desc_lines) > 1 else ""

    @classmethod
    def _parse_sphinx(cls, docstring: str, info: DocstringInfo) -> None:
        """Parse Sphinx-style docstring."""
        # Extract summary (first paragraph)
        lines = docstring.strip().split("\n")
        summary_lines = []
        desc_lines = []
        in_directives = False
        in_first = True

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_first:
                    in_first = False
                    continue
                else:
                    if not in_directives:
                        continue
            if re.match(r":param|:type|:returns|:raises|:yields|:rtype|:keyword|:deprecated|:note|:example", stripped):
                in_directives = True
                continue
            if not in_directives:
                if in_first:
                    summary_lines.append(stripped)
                else:
                    desc_lines.append(stripped)

        if summary_lines:
            info.summary = summary_lines[0]
            info.description = " ".join(summary_lines[1:] + desc_lines)

        # Extract params
        for match in cls.SPHINX_PARAM_PATTERN.finditer(docstring):
            name = match.group(1)
            desc = match.group(2).strip()
            # Find existing param or add new
            existing = [p for p in info.params if p["name"] == name]
            if existing:
                existing[0]["description"] = desc
            else:
                info.params.append({"name": name, "type": "", "description": desc})

        # Extract types
        for match in cls.SPHINX_TYPE_PATTERN.finditer(docstring):
            name = match.group(1)
            type_str = match.group(2).strip()
            existing = [p for p in info.params if p["name"] == name]
            if existing:
                existing[0]["type"] = type_str
            else:
                info.params.append({"name": name, "type": type_str, "description": ""})

        # Extract returns
        ret_match = cls.SPHINX_RETURN_PATTERN.search(docstring)
        if ret_match:
            if info.returns is None:
                info.returns = {}
            info.returns["description"] = ret_match.group(1).strip()

        rtype_match = cls.SPHINX_RTYPE_PATTERN.search(docstring)
        if rtype_match:
            if info.returns is None:
                info.returns = {}
            info.returns["type"] = rtype_match.group(1).strip()

        # Extract raises
        for match in cls.SPHINX_RAISE_PATTERN.finditer(docstring):
            info.raises.append({
                "type": match.group(1),
                "description": match.group(2).strip(),
            })

        # Extract yields
        yld_match = cls.SPHINX_YIELD_PATTERN.search(docstring)
        if yld_match:
            if info.yields is None:
                info.yields = {}
            info.yields["description"] = yld_match.group(1).strip()

        # Extract deprecated
        dep_match = cls.SPHINX_DEPRECATED_PATTERN.search(docstring)
        if dep_match:
            info.deprecated = dep_match.group(1).strip()

        # Extract notes
        for match in cls.SPHINX_NOTE_PATTERN.finditer(docstring):
            info.notes.append(match.group(1).strip())

        # Extract examples
        for match in cls.SPHINX_EXAMPLE_PATTERN.finditer(docstring):
            info.examples.append(match.group(1).strip())


# ---------------------------------------------------------------------------
# Python Parser
# ---------------------------------------------------------------------------

class PythonParser:
    """Parse Python source files and extract documentation data.

    Uses the built-in ``ast`` module to parse Python source code and extract
    structured information about functions, classes, methods, and module-level
    elements.

    Attributes:
        language: Language identifier ('python')
        source: Raw source code being parsed
        tree: AST root node
        module_info: ModuleInfo being built
    """

    language = "python"

    def __init__(self):
        self.source: str = ""
        self.tree: ast.Module = None
        self.module_info: Optional[ModuleInfo] = None
        self._current_class: Optional[ClassInfo] = None

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def parse_file(self, filepath: str, include_source: bool = True,
                   include_comments: bool = True) -> ParsedDocumentation:
        """Parse a Python source file.

        Args:
            filepath: Path to the .py file
            include_source: Include source code text in output
            include_comments: Extract inline comments

        Returns:
            ParsedDocumentation with extracted data
        """
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        return self.parse_string(source, filepath=filepath,
                                 include_source=include_source,
                                 include_comments=include_comments)

    def parse_string(self, source: str, filepath: str = "",
                     include_source: bool = True,
                     include_comments: bool = True) -> ParsedDocumentation:
        """Parse Python source code from a string.

        Args:
            source: Python source code
            filepath: Optional file path for context
            include_source: Include source code text in output
            include_comments: Extract inline comments

        Returns:
            ParsedDocumentation with extracted data
        """
        self.source = source
        self.tree = ast.parse(source, filename=filepath)

        result = ParsedDocumentation(source_file=filepath, language="python")
        result.raw_source = source if include_source else ""

        # Module info
        module_name = self._get_module_name(filepath)
        self.module_info = ModuleInfo(name=module_name, filepath=filepath)
        self.module_info.source_code = source if include_source else ""

        # Module docstring
        module_doc = ast.get_docstring(self.tree)
        if module_doc:
            self.module_info.docstring = DocstringParser.parse(module_doc)

        # Extract imports
        self._extract_imports(self.tree, self.module_info)

        # Extract top-level elements
        self._extract_body(self.tree, self.module_info)

        result.module = self.module_info
        result.global_functions = self.module_info.functions
        result.global_classes = self.module_info.classes
        result.global_variables = self.module_info.variables

        # Extract comments
        if include_comments:
            result.comments = self._extract_comments(source)
            result.todos = self._extract_tagged_comments(source, "TODO")
            result.fixmes = self._extract_tagged_comments(source, "FIXME")
            result.notes_list = self._extract_tagged_comments(source, "NOTE")

        return result

    def parse_project(self, root_dir: str, recursive: bool = True,
                      include_source: bool = False,
                      include_comments: bool = True) -> Dict[str, ParsedDocumentation]:
        """Parse all Python files in a project directory.

        Args:
            root_dir: Project root directory
            recursive: Whether to recurse into subdirectories
            include_source: Include source code in output
            include_comments: Extract inline comments

        Returns:
            Dict mapping file paths to ParsedDocumentation objects
        """
        import os
        results = {}
        root_dir = os.path.abspath(root_dir)

        for root, dirs, files in os.walk(root_dir):
            if not recursive and root != root_dir:
                break
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and d not in ("__pycache__", "node_modules", "venv", ".venv",
                                     "env", ".env", "build", "dist", "*.egg-info")]
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    try:
                        results[filepath] = self.parse_file(
                            filepath, include_source=include_source,
                            include_comments=include_comments
                        )
                    except (SyntaxError, UnicodeDecodeError) as e:
                        results[filepath] = ParsedDocumentation(
                            source_file=filepath, language="python"
                        )
        return results

    # -----------------------------------------------------------------------
    # Internal extraction methods
    # -----------------------------------------------------------------------

    def _get_module_name(self, filepath: str) -> str:
        """Extract module name from file path."""
        if not filepath:
            return "<string>"
        name = os.path.splitext(os.path.basename(filepath))[0]
        if name == "__init__":
            # Use parent directory name
            parent = os.path.basename(os.path.dirname(filepath))
            if parent:
                return parent
        return name

    def _extract_imports(self, node: ast.Module, module_info: ModuleInfo) -> None:
        """Extract import statements from module."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    module_info.imports.append({
                        "name": alias.name,
                        "asname": alias.asname or "",
                    })
            elif isinstance(child, ast.ImportFrom):
                module_info.from_imports.append({
                    "module": child.module or "",
                    "names": [
                        {"name": alias.name, "asname": alias.asname or ""}
                        for alias in child.names
                    ],
                    "level": child.level or 0,
                })

    def _extract_body(self, node: ast.Module, module_info: ModuleInfo) -> None:
        """Extract top-level definitions from module body."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef) or isinstance(child, ast.AsyncFunctionDef):
                func_info = self._extract_function(child)
                module_info.functions.append(func_info)
            elif isinstance(child, ast.ClassDef):
                class_info = self._extract_class(child)
                module_info.classes.append(class_info)
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        var_info = self._extract_variable(target, child.value)
                        if var_info:
                            # Check if it's a constant (uppercase name)
                            if target.id.isupper():
                                module_info.constants.append(var_info)
                            else:
                                module_info.variables.append(var_info)
            elif isinstance(child, ast.AnnAssign):
                if isinstance(child.target, ast.Name):
                    var_info = {
                        "name": child.target.id,
                        "type": self._get_annotation_str(child.annotation),
                        "value": self._get_expr_str(child.value) if child.value else None,
                        "lineno": child.lineno,
                    }
                    if child.target.id.isupper():
                        module_info.constants.append(var_info)
                    else:
                        module_info.variables.append(var_info)
            elif isinstance(child, ast.TypeAlias):
                module_info.type_aliases.append({
                    "name": self._get_expr_str(child.name),
                    "value": self._get_expr_str(child.value),
                    "lineno": child.lineno,
                })

    def _extract_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                          parent_class: Optional[ClassInfo] = None) -> FunctionInfo:
        """Extract function/method information from AST node."""
        qualname = (
            f"{parent_class.qualname}.{node.name}"
            if parent_class else node.name
        )
        func_info = FunctionInfo(
            name=node.name,
            qualname=qualname,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
        )
        func_info.is_async = isinstance(node, ast.AsyncFunctionDef)
        func_info.source_code = ast.get_source_segment(self.source, node) or ""

        # Decorators
        func_info.decorators = [
            self._get_decorator_str(d) for d in node.decorator_list
        ]
        self._classify_decorators(func_info)

        # Parameters
        func_info.params = self._extract_params(node.args)

        # Return type annotation
        func_info.return_type = self._get_annotation_str(node.returns)

        # Docstring
        docstring = ast.get_docstring(node)
        if docstring:
            func_info.docstring = DocstringParser.parse(docstring)

        # Body summary (first significant statement)
        func_info.body_summary = self._get_body_summary(node)

        # Check for exceptions (raise statements)
        func_info.exceptions = self._extract_raises(node)

        # Check if generator (yield in body)
        func_info.is_generator = self._has_yield(node)

        return func_info

    def _extract_params(self, args: ast.arguments) -> List[ParameterInfo]:
        """Extract parameter information from function arguments."""
        params = []

        # Positional/keyword parameters
        default_offset = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            default = None
            if i >= default_offset:
                default_idx = i - default_offset
                if default_idx < len(args.defaults):
                    default = self._get_expr_str(args.defaults[default_idx])

            param = ParameterInfo(
                name=arg.arg,
                type_hint=self._get_annotation_str(arg.annotation),
                default_value=default,
                kind="positional_or_keyword",
            )
            params.append(param)

        # *args (var positional)
        if args.vararg:
            param = ParameterInfo(
                name=args.vararg.arg,
                type_hint=self._get_annotation_str(args.vararg.annotation),
                kind="var_positional",
            )
            params.append(param)

        # Keyword-only parameters
        kwonly_offset = len(args.kwonlyargs) - len(args.kw_defaults)
        for i, arg in enumerate(args.kwonlyargs):
            default = None
            if i >= kwonly_offset:
                default_idx = i - kwonly_offset
                if default_idx < len(args.kw_defaults) and args.kw_defaults[default_idx] is not None:
                    default = self._get_expr_str(args.kw_defaults[default_idx])

            param = ParameterInfo(
                name=arg.arg,
                type_hint=self._get_annotation_str(arg.annotation),
                default_value=default,
                kind="keyword_only",
            )
            params.append(param)

        # **kwargs (var keyword)
        if args.kwarg:
            param = ParameterInfo(
                name=args.kwarg.arg,
                type_hint=self._get_annotation_str(args.kwarg.annotation),
                kind="var_keyword",
            )
            params.append(param)

        return params

    def _extract_class(self, node: ast.ClassDef) -> ClassInfo:
        """Extract class information from AST node."""
        class_info = ClassInfo(
            name=node.name,
            qualname=node.name,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
        )
        class_info.source_code = ast.get_source_segment(self.source, node) or ""

        # Base classes
        class_info.bases = [self._get_expr_str(b) for b in node.bases]

        # Decorators
        class_info.decorators = [
            self._get_decorator_str(d) for d in node.decorator_list
        ]
        self._classify_class_decorators(class_info)

        # Metaclass
        for kw in node.keywords:
            if kw.arg == "metaclass":
                class_info.metaclass = self._get_expr_str(kw.value)

        # Docstring
        docstring = ast.get_docstring(node)
        if docstring:
            class_info.docstring = DocstringParser.parse(docstring)

        # Extract class body
        self._current_class = class_info
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef) or isinstance(child, ast.AsyncFunctionDef):
                method_info = self._extract_function(child, parent_class=class_info)
                class_info.methods.append(method_info)
            elif isinstance(child, ast.ClassDef):
                inner_class = self._extract_class(child)
                inner_class.qualname = f"{class_info.qualname}.{inner_class.name}"
                class_info.inner_classes.append(inner_class)
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        var_info = self._extract_variable(target, child.value)
                        if var_info:
                            class_info.class_vars.append(var_info)
            elif isinstance(child, ast.AnnAssign):
                if isinstance(child.target, ast.Name):
                    var_info = {
                        "name": child.target.id,
                        "type": self._get_annotation_str(child.annotation),
                        "value": self._get_expr_str(child.value) if child.value else None,
                        "lineno": child.lineno,
                    }
                    class_info.class_vars.append(var_info)
        self._current_class = None

        return class_info

    def _extract_variable(self, target: ast.Name, value: ast.AST) -> Optional[Dict[str, Any]]:
        """Extract variable information."""
        return {
            "name": target.id,
            "type": self._infer_type_from_value(value),
            "value": self._get_expr_str(value),
            "lineno": target.lineno,
        }

    def _extract_raises(self, node: ast.AST) -> List[str]:
        """Extract exception types from raise statements in a function body."""
        exceptions = []
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                if child.exc is not None:
                    if isinstance(child.exc, ast.Call):
                        exc_name = self._get_expr_str(child.exc.func)
                    else:
                        exc_name = self._get_expr_str(child.exc)
                    if exc_name and exc_name not in exceptions:
                        exceptions.append(exc_name)
        return exceptions

    def _has_yield(self, node: ast.AST) -> bool:
        """Check if a function body contains yield or yield from."""
        for child in ast.walk(node):
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                return True
        return False

    # -----------------------------------------------------------------------
    # Classification helpers
    # -----------------------------------------------------------------------

    def _classify_decorators(self, func_info: FunctionInfo) -> None:
        """Classify common decorators to set flags on the function."""
        for dec in func_info.decorators:
            if dec in ("staticmethod", "@staticmethod"):
                func_info.is_static = True
            elif dec in ("classmethod", "@classmethod"):
                func_info.is_classmethod = True
            elif dec in ("property", "@property"):
                func_info.is_property = True
            elif dec in ("abstractmethod", "@abstractmethod"):
                func_info.is_abstract = True
            elif dec.startswith("abstractmethod"):
                func_info.is_abstract = True

    def _classify_class_decorators(self, class_info: ClassInfo) -> None:
        """Classify common class decorators."""
        for dec in class_info.decorators:
            if dec in ("dataclass", "dataclasses.dataclass", "@dataclass", "@dataclasses.dataclass"):
                class_info.is_dataclass = True
            elif "Enum" in class_info.bases:
                class_info.is_enum = True
            elif dec in ("abstractmethod", "@abstractmethod"):
                class_info.is_abstract = True

    # -----------------------------------------------------------------------
    # Expression string converters
    # -----------------------------------------------------------------------

    def _get_expr_str(self, node: Optional[ast.AST]) -> str:
        """Convert an AST expression node back to a string representation."""
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            return f"<{type(node).__name__}>"

    def _get_annotation_str(self, node: Optional[ast.AST]) -> str:
        """Convert a type annotation AST node to a string."""
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            return f"<{type(node).__name__}>"

    def _get_decorator_str(self, node: ast.AST) -> str:
        """Convert a decorator AST node to a string."""
        try:
            return ast.unparse(node)
        except Exception:
            return f"@{self._get_expr_str(node)}"

    def _infer_type_from_value(self, node: ast.AST) -> str:
        """Infer the type of a variable from its value expression."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return "str"
            elif isinstance(node.value, int):
                return "int"
            elif isinstance(node.value, float):
                return "float"
            elif isinstance(node.value, bool):
                return "bool"
            elif isinstance(node.value, bytes):
                return "bytes"
            elif node.value is None:
                return "None"
            elif isinstance(node.value, complex):
                return "complex"
        elif isinstance(node, ast.List):
            return "list"
        elif isinstance(node, ast.Set):
            return "set"
        elif isinstance(node, ast.Dict):
            return "dict"
        elif isinstance(node, ast.Tuple):
            return "tuple"
        elif isinstance(node, ast.Call):
            func_name = self._get_expr_str(node.func)
            if func_name in ("dict", "list", "set", "tuple", "str", "int", "float", "bool"):
                return func_name
            return func_name
        elif isinstance(node, ast.Lambda):
            return "Callable"
        elif isinstance(node, ast.ListComp):
            return "list"
        elif isinstance(node, ast.SetComp):
            return "set"
        elif isinstance(node, ast.DictComp):
            return "dict"
        elif isinstance(node, ast.GeneratorExp):
            return "generator"
        elif isinstance(node, ast.Name):
            if node.id in ("True", "False"):
                return "bool"
            elif node.id == "None":
                return "None"
            return node.id
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return self._infer_type_from_value(node.operand)
            return "bool"
        elif isinstance(node, ast.BinOp):
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                                     ast.Mod, ast.Pow)):
                left_type = self._infer_type_from_value(node.left)
                right_type = self._infer_type_from_value(node.right)
                if left_type == right_type:
                    return left_type
                return left_type
            return "bool"
        elif isinstance(node, ast.IfExp):
            return self._infer_type_from_value(node.body)
        elif isinstance(node, ast.FString):
            return "str"
        elif isinstance(node, ast.FormattedValue):
            return "str"
        elif isinstance(node, ast.fstring):
            return "str"
        return "Any"

    def _get_body_summary(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Get a summary of the function body (first significant statement)."""
        for child in node.body:
            if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
                continue  # Skip docstring
            if isinstance(child, ast.Pass):
                return "pass (empty implementation)"
            if isinstance(child, ast.Raise):
                return f"raise {self._get_expr_str(child.exc) if child.exc else ''}"
            if isinstance(child, ast.Return):
                if child.value:
                    return f"return {self._get_expr_str(child.value)}"
                return "return None"
            if isinstance(child, ast.FunctionDef):
                return f"defines inner function: {child.name}"
            if isinstance(child, ast.ClassDef):
                return f"defines inner class: {child.name}"
            if isinstance(child, ast.Assign):
                return f"assigns {self._get_expr_str(child.targets[0]) if child.targets else ''}"
            if isinstance(child, ast.If):
                return "conditional logic"
            if isinstance(child, ast.For):
                return "loop"
            if isinstance(child, ast.While):
                return "loop"
            if isinstance(child, ast.Try):
                return "try/except block"
            if isinstance(child, ast.With):
                return "context manager"
            if isinstance(child, ast.Await):
                return "async await"
            if isinstance(child, ast.AsyncFor):
                return "async for loop"
            if isinstance(child, ast.AsyncWith):
                return "async context manager"
            return f"<{type(child).__name__}>"
        return ""

    # -----------------------------------------------------------------------
    # Comment extraction
    # -----------------------------------------------------------------------

    def _extract_comments(self, source: str) -> List[Dict[str, Any]]:
        """Extract inline comments from source code."""
        comments = []
        for i, line in enumerate(source.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                # Full-line comment
                comment_text = stripped[1:].strip()
                multiline = comment_text.startswith("#")
                comments.append({
                    "text": comment_text,
                    "lineno": i,
                    "type": "full_line",
                })
            elif "#" in stripped and not stripped.startswith("'''") and not stripped.startswith('"""'):
                # Inline comment
                idx = line.index("#")
                code = line[:idx].strip()
                comment_text = line[idx + 1:].strip()
                comments.append({
                    "text": comment_text,
                    "code_before": code,
                    "lineno": i,
                    "type": "inline",
                })
        return comments

    def _extract_tagged_comments(self, source: str, tag: str) -> List[Dict[str, Any]]:
        """Extract tagged comments (TODO, FIXME, NOTE)."""
        results = []
        pattern = re.compile(r"#\s*" + re.escape(tag) + r"\b\s*:\s*(.*)", re.IGNORECASE)
        for i, line in enumerate(source.split("\n"), 1):
            match = pattern.search(line)
            if match:
                results.append({
                    "text": match.group(1).strip(),
                    "lineno": i,
                    "tag": tag,
                })
        return results

    # -----------------------------------------------------------------------
    # Utility: get all identifiers
    # -----------------------------------------------------------------------

    def get_identifiers(self, parsed: ParsedDocumentation) -> List[Dict[str, Any]]:
        """Get all identifiers (functions, classes, methods) from parsed data.

        Args:
            parsed: ParsedDocumentation object

        Returns:
            List of identifier dicts with name, kind, and location
        """
        identifiers = []

        if parsed.module:
            for func in parsed.module.functions:
                identifiers.append({
                    "name": func.name,
                    "qualname": func.qualname,
                    "kind": "function",
                    "lineno": func.lineno,
                })
            for cls in parsed.module.classes:
                identifiers.append({
                    "name": cls.name,
                    "qualname": cls.qualname,
                    "kind": "class",
                    "lineno": cls.lineno,
                })
                for method in cls.methods:
                    identifiers.append({
                        "name": method.name,
                        "qualname": method.qualname,
                        "kind": "method",
                        "lineno": method.lineno,
                    })

        return identifiers

    def get_call_graph(self, parsed: ParsedDocumentation) -> Dict[str, List[str]]:
        """Extract a simple call graph from function bodies.

        This is a best-effort analysis that looks for function calls in
        function bodies.

        Args:
            parsed: ParsedDocumentation object

        Returns:
            Dict mapping function names to lists of called function names
        """
        call_graph = {}
        # This would require deeper AST analysis; here we provide a stub
        # that can be extended with more sophisticated analysis
        return call_graph

    # -----------------------------------------------------------------------
    # Summary statistics
    # -----------------------------------------------------------------------

    def get_statistics(self, parsed: ParsedDocumentation) -> Dict[str, Any]:
        """Get summary statistics about the parsed documentation.

        Args:
            parsed: ParsedDocumentation object

        Returns:
            Dict with counts and metrics
        """
        all_functions = list(parsed.global_functions)
        all_classes = list(parsed.global_classes)

        for cls in all_classes:
            all_functions.extend(cls.methods)

        documented_functions = sum(
            1 for f in all_functions if f.docstring and f.docstring.summary
        )
        documented_classes = sum(
            1 for c in all_classes if c.docstring and c.docstring.summary
        )

        stats = {
            "total_functions": len(all_functions),
            "total_classes": len(all_classes),
            "documented_functions": documented_functions,
            "documented_classes": documented_classes,
            "doc_coverage_functions": (
                (documented_functions / len(all_functions) * 100)
                if all_functions else 0
            ),
            "doc_coverage_classes": (
                (documented_classes / len(all_classes) * 100)
                if all_classes else 0
            ),
            "total_params": sum(len(f.params) for f in all_functions),
            "total_decorators": sum(len(f.decorators) for f in all_functions),
            "total_exceptions": sum(len(f.exceptions) for f in all_functions),
            "total_imports": len(parsed.module.imports) if parsed.module else 0,
            "total_from_imports": len(parsed.module.from_imports) if parsed.module else 0,
            "total_variables": len(parsed.global_variables),
            "total_constants": len(parsed.module.constants) if parsed.module else 0,
            "total_comments": len(parsed.comments),
            "total_todos": len(parsed.todos),
            "total_fixmes": len(parsed.fixmes),
            "async_functions": sum(1 for f in all_functions if f.is_async),
            "generator_functions": sum(1 for f in all_functions if f.is_generator),
            "abstract_functions": sum(1 for f in all_functions if f.is_abstract),
            "property_functions": sum(1 for f in all_functions if f.is_property),
            "static_methods": sum(1 for f in all_functions if f.is_static),
            "class_methods": sum(1 for f in all_functions if f.is_classmethod),
            "dataclasses": sum(1 for c in all_classes if c.is_dataclass),
            "enums": sum(1 for c in all_classes if c.is_enum),
            "abstract_classes": sum(1 for c in all_classes if c.is_abstract),
        }

        return stats

    # -----------------------------------------------------------------------
    # Type annotation analysis
    # -----------------------------------------------------------------------

    def analyze_type_coverage(self, parsed: ParsedDocumentation) -> Dict[str, Any]:
        """Analyze type annotation coverage.

        Args:
            parsed: ParsedDocumentation object

        Returns:
            Dict with annotation statistics
        """
        all_functions = list(parsed.global_functions)
        for cls in parsed.global_classes:
            all_functions.extend(cls.methods)

        total_params = 0
        annotated_params = 0
        annotated_returns = 0

        for func in all_functions:
            if func.return_type:
                annotated_returns += 1
            for param in func.params:
                total_params += 1
                if param.type_hint:
                    annotated_params += 1

        return {
            "total_params": total_params,
            "annotated_params": annotated_params,
            "param_annotation_coverage": (
                (annotated_params / total_params * 100) if total_params else 0
            ),
            "total_functions": len(all_functions),
            "annotated_returns": annotated_returns,
            "return_annotation_coverage": (
                (annotated_returns / len(all_functions) * 100)
                if all_functions else 0
            ),
        }


# ---------------------------------------------------------------------------
# Additional utility functions
# ---------------------------------------------------------------------------

def extract_decorator_factory_calls(source: str) -> List[Dict[str, Any]]:
    """Extract decorator factory calls (decorators with arguments).

    Args:
        source: Python source code

    Returns:
        List of decorator calls with name, args, and line number
    """
    tree = ast.parse(source)
    decorators = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    decorators.append({
                        "name": ast.unparse(dec.func),
                        "args": [ast.unparse(a) for a in dec.args],
                        "keywords": {kw.arg: ast.unparse(kw.value) for kw in dec.keywords if kw.arg},
                        "lineno": dec.lineno,
                    })

    return decorators


def extract_import_strings(source: str) -> List[str]:
    """Extract all import statements as strings.

    Args:
        source: Python source code

    Returns:
        List of import statement strings
    """
    tree = ast.parse(source)
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                as_str = f" as {alias.asname}" if alias.asname else ""
                imports.append(f"import {alias.name}{as_str}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = []
            for alias in node.names:
                as_str = f" as {alias.asname}" if alias.asname else ""
                names.append(f"{alias.name}{as_str}")
            imports.append(f"from {module} import {', '.join(names)}")

    return imports


def extract_global_vars(source: str) -> List[Dict[str, Any]]:
    """Extract global variable assignments.

    Args:
        source: Python source code

    Returns:
        List of variable info dicts
    """
    parser = PythonParser()
    result = parser.parse_string(source, include_comments=False)
    return result.global_variables


def extract_type_aliases(source: str) -> List[Dict[str, Any]]:
    """Extract TypeAlias definitions (Python 3.10+).

    Args:
        source: Python source code

    Returns:
        List of type alias dicts
    """
    parser = PythonParser()
    result = parser.parse_string(source, include_comments=False)
    if result.module:
        return result.module.type_aliases
    return []


def generate_api_summary(parsed: ParsedDocumentation) -> str:
    """Generate a human-readable API summary from parsed documentation.

    Args:
        parsed: ParsedDocumentation object

    Returns:
        Formatted summary string
    """
    lines = []
    lines.append(f"# API Summary: {parsed.source_file}")
    lines.append("")

    if parsed.module and parsed.module.docstring.summary:
        lines.append(parsed.module.docstring.summary)
        lines.append("")

    if parsed.global_functions:
        lines.append(f"## Functions ({len(parsed.global_functions)})")
        for func in parsed.global_functions:
            params_str = ", ".join(
                f"{p.name}: {p.type_hint or 'Any'}"
                for p in func.params
            )
            return_str = f" -> {func.return_type}" if func.return_type else ""
            lines.append(f"- `{func.name}({params_str}){return_str}`")
            if func.docstring and func.docstring.summary:
                lines.append(f"  - {func.docstring.summary}")
        lines.append("")

    if parsed.global_classes:
        lines.append(f"## Classes ({len(parsed.global_classes)})")
        for cls in parsed.global_classes:
            bases_str = f"({', '.join(cls.bases)})" if cls.bases else ""
            lines.append(f"- `{cls.name}{bases_str}`")
            if cls.docstring and cls.docstring.summary:
                lines.append(f"  - {cls.docstring.summary}")
            if cls.methods:
                lines.append(f"  - Methods: {len(cls.methods)}")
        lines.append("")

    if parsed.todos:
        lines.append(f"## TODOs ({len(parsed.todos)})")
        for todo in parsed.todos[:10]:
            lines.append(f"- Line {todo['lineno']}: {todo['text']}")
        if len(parsed.todos) > 10:
            lines.append(f"- ... and {len(parsed.todos) - 10} more")
        lines.append("")

    return "\n".join(lines)


def merge_parsed_results(results: Dict[str, ParsedDocumentation]) -> Dict[str, Any]:
    """Merge multiple parsed results into a single summary.

    Args:
        results: Dict mapping file paths to ParsedDocumentation objects

    Returns:
        Merged summary dict
    """
    merged = {
        "total_files": len(results),
        "total_functions": 0,
        "total_classes": 0,
        "total_methods": 0,
        "total_todos": 0,
        "total_fixmes": 0,
        "files": [],
    }

    for filepath, parsed in results.items():
        file_summary = {
            "filepath": filepath,
            "functions": len(parsed.global_functions) if parsed else 0,
            "classes": len(parsed.global_classes) if parsed else 0,
            "todos": len(parsed.todos) if parsed else 0,
            "fixmes": len(parsed.fixmes) if parsed else 0,
            "module_doc": bool(parsed.module and parsed.module.docstring.summary) if parsed else False,
        }

        methods = 0
        for cls in (parsed.global_classes if parsed else []):
            methods += len(cls.methods)

        file_summary["methods"] = methods
        merged["total_functions"] += file_summary["functions"]
        merged["total_classes"] += file_summary["classes"]
        merged["total_methods"] += methods
        merged["total_todos"] += file_summary["todos"]
        merged["total_fixmes"] += file_summary["fixmes"]
        merged["files"].append(file_summary)

    return merged


def find_duplicate_signatures(parsed: ParsedDocumentation) -> List[Dict[str, Any]]:
    """Find functions/methods with duplicate signatures.

    Args:
        parsed: ParsedDocumentation object

    Returns:
        List of duplicate groups
    """
    all_functions = list(parsed.global_functions)
    for cls in parsed.global_classes:
        all_functions.extend(cls.methods)

    sig_map = {}
    for func in all_functions:
        sig = func.name + "(" + ",".join(p.name for p in func.params) + ")"
        if sig not in sig_map:
            sig_map[sig] = []
        sig_map[sig].append(func.qualname)

    return [
        {"signature": sig, "locations": locs}
        for sig, locs in sig_map.items()
        if len(locs) > 1
    ]


# ---------------------------------------------------------------------------
# Module-level exports
# ---------------------------------------------------------------------------

__all__ = [
    "PythonParser",
    "DocstringParser",
    "DocstringInfo",
    "ParameterInfo",
    "FunctionInfo",
    "ClassInfo",
    "ModuleInfo",
    "ParsedDocumentation",
    "extract_decorator_factory_calls",
    "extract_import_strings",
    "extract_global_vars",
    "extract_type_aliases",
    "generate_api_summary",
    "merge_parsed_results",
    "find_duplicate_signatures",
]