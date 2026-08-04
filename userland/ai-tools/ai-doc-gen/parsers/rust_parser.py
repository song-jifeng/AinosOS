"""Rust source code parser for AI Documentation Generator.

Extracts structured documentation data from Rust source files using regex-based
analysis for common Rust patterns.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class RustDocstringInfo:
    """Parsed Rust docstring information."""

    def __init__(self):
        self.summary: str = ""
        self.description: str = ""
        self.params: List[Dict[str, str]] = []
        self.returns: Optional[Dict[str, str]] = None
        self.panics: List[str] = []
        self.errors: List[str] = []
        self.safety: List[str] = []
        self.examples: List[str] = []
        self.see_also: List[str] = []
        self.deprecated: Optional[str] = None
        self.attributes: List[str] = []
        self.style: str = "rustdoc"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "description": self.description,
            "params": self.params,
            "returns": self.returns,
            "panics": self.panics,
            "errors": self.errors,
            "safety": self.safety,
            "examples": self.examples,
            "see_also": self.see_also,
            "deprecated": self.deprecated,
            "attributes": self.attributes,
            "style": self.style,
        }


class RustParamInfo:
    """Information about a Rust function parameter."""

    def __init__(self, name: str, type_str: str = "",
                 is_self: bool = False, is_mut: bool = False,
                 is_ref: bool = False):
        self.name = name
        self.type_str = type_str
        self.is_self = is_self
        self.is_mut = is_mut
        self.is_ref = is_ref

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_str,
            "is_self": self.is_self,
            "is_mut": self.is_mut,
            "is_ref": self.is_ref,
        }


class RustFunctionInfo:
    """Information about a Rust function/method."""

    def __init__(self, name: str, lineno: int = 0):
        self.name = name
        self.qualname = name
        self.lineno = lineno
        self.params: List[RustParamInfo] = []
        self.return_type: str = ""
        self.docstring: RustDocstringInfo = RustDocstringInfo()
        self.is_async: bool = False
        self.is_unsafe: bool = False
        self.is_pub: bool = False
        self.is_const: bool = False
        self.is_abi: bool = False
        self.abi_name: str = ""
        self.generics: List[str] = []
        self.where_clause: List[str] = []
        self.attributes: List[str] = []
        self.source_code: str = ""
        self.is_method: bool = False
        self.visibility: str = "private"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "params": [p.to_dict() for p in self.params],
            "return_type": self.return_type,
            "docstring": self.docstring.to_dict(),
            "is_async": self.is_async,
            "is_unsafe": self.is_unsafe,
            "is_pub": self.is_pub,
            "is_const": self.is_const,
            "generics": self.generics,
            "attributes": self.attributes,
            "visibility": self.visibility,
        }


class RustStructInfo:
    """Information about a Rust struct."""

    def __init__(self, name: str, lineno: int = 0):
        self.name = name
        self.qualname = name
        self.lineno = lineno
        self.fields: List[Dict[str, Any]] = []
        self.docstring: RustDocstringInfo = RustDocstringInfo()
        self.generics: List[str] = []
        self.attributes: List[str] = []
        self.is_pub: bool = False
        self.is_tuple_struct: bool = False
        self.is_unit_struct: bool = False
        self.derives: List[str] = []
        self.visibility: str = "private"
        self.source_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "fields": self.fields,
            "docstring": self.docstring.to_dict(),
            "generics": self.generics,
            "attributes": self.attributes,
            "is_pub": self.is_pub,
            "is_tuple_struct": self.is_tuple_struct,
            "is_unit_struct": self.is_unit_struct,
            "derives": self.derives,
            "visibility": self.visibility,
        }


class RustEnumInfo:
    """Information about a Rust enum."""

    def __init__(self, name: str, lineno: int = 0):
        self.name = name
        self.qualname = name
        self.lineno = lineno
        self.variants: List[Dict[str, Any]] = []
        self.docstring: RustDocstringInfo = RustDocstringInfo()
        self.generics: List[str] = []
        self.attributes: List[str] = []
        self.is_pub: bool = False
        self.derives: List[str] = []
        self.visibility: str = "private"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "variants": self.variants,
            "docstring": self.docstring.to_dict(),
            "generics": self.generics,
            "attributes": self.attributes,
            "is_pub": self.is_pub,
            "derives": self.derives,
            "visibility": self.visibility,
        }


class RustTraitInfo:
    """Information about a Rust trait."""

    def __init__(self, name: str, lineno: int = 0):
        self.name = name
        self.qualname = name
        self.lineno = lineno
        self.methods: List[RustFunctionInfo] = []
        self.associated_types: List[Dict[str, str]] = []
        self.associated_consts: List[Dict[str, str]] = []
        self.docstring: RustDocstringInfo = RustDocstringInfo()
        self.generics: List[str] = []
        self.supertraits: List[str] = []
        self.attributes: List[str] = []
        self.is_pub: bool = False
        self.is_unsafe: bool = False
        self.visibility: str = "private"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "methods": [m.to_dict() for m in self.methods],
            "associated_types": self.associated_types,
            "associated_consts": self.associated_consts,
            "docstring": self.docstring.to_dict(),
            "generics": self.generics,
            "supertraits": self.supertraits,
            "attributes": self.attributes,
            "is_pub": self.is_pub,
            "is_unsafe": self.is_unsafe,
            "visibility": self.visibility,
        }


class RustImplInfo:
    """Information about a Rust impl block."""

    def __init__(self, type_name: str, lineno: int = 0):
        self.type_name = type_name
        self.lineno = lineno
        self.methods: List[RustFunctionInfo] = []
        self.trait_name: Optional[str] = None
        self.generics: List[str] = []
        self.is_unsafe: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type_name": self.type_name,
            "lineno": self.lineno,
            "methods": [m.to_dict() for m in self.methods],
            "trait_name": self.trait_name,
            "generics": self.generics,
            "is_unsafe": self.is_unsafe,
        }


class RustModuleInfo:
    """Information about a Rust module."""

    def __init__(self, name: str, filepath: str = ""):
        self.name = name
        self.filepath = filepath
        self.docstring: RustDocstringInfo = RustDocstringInfo()
        self.functions: List[RustFunctionInfo] = []
        self.structs: List[RustStructInfo] = []
        self.enums: List[RustEnumInfo] = []
        self.traits: List[RustTraitInfo] = []
        self.impls: List[RustImplInfo] = []
        self.type_aliases: List[Dict[str, str]] = []
        self.constants: List[Dict[str, Any]] = []
        self.statics: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, str]] = []
        self.macros: List[Dict[str, Any]] = []
        self.submodules: List[str] = []
        self.source_code: str = ""
        self.attributes: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "filepath": self.filepath,
            "docstring": self.docstring.to_dict(),
            "functions": [f.to_dict() for f in self.functions],
            "structs": [s.to_dict() for s in self.structs],
            "enums": [e.to_dict() for e in self.enums],
            "traits": [t.to_dict() for t in self.traits],
            "type_aliases": self.type_aliases,
            "constants": self.constants,
            "statics": self.statics,
            "imports": self.imports,
            "submodules": self.submodules,
        }


class RustParseResult:
    """Container for parsed Rust documentation."""

    def __init__(self, source_file: str = ""):
        self.source_file = source_file
        self.language = "rust"
        self.module: Optional[RustModuleInfo] = None
        self.raw_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file": self.source_file,
            "language": self.language,
            "module": self.module.to_dict() if self.module else None,
        }


# ---------------------------------------------------------------------------
# Rustdoc parser
# ---------------------------------------------------------------------------

class RustdocParser:
    """Parse Rustdoc-style comments (/// and //!)."""

    @classmethod
    def parse(cls, docstring: str) -> RustDocstringInfo:
        """Parse a Rustdoc-style comment.

        Args:
            docstring: Raw docstring text (with /// markers removed)

        Returns:
            RustDocstringInfo with parsed fields
        """
        info = RustDocstringInfo()
        docstring = docstring.strip()

        # Remove leading whitespace
        lines = []
        for line in docstring.split("\n"):
            stripped = line.strip()
            lines.append(stripped)
        docstring = "\n".join(lines)

        # Extract sections
        sections = cls._split_sections(docstring)

        # First section is the summary/description
        if sections:
            first_section = sections[0]
            # Summary is first line
            summary_lines = first_section.split("\n", 1)
            info.summary = summary_lines[0].strip()
            if len(summary_lines) > 1:
                info.description = summary_lines[1].strip()

        # Parse remaining sections
        for i in range(1, len(sections)):
            section = sections[i]
            section_lower = section.lower()

            if section_lower.startswith("# parameters") or section_lower.startswith("# arguments"):
                cls._parse_params(section, info)
            elif section_lower.startswith("# returns"):
                cls._parse_returns(section, info)
            elif section_lower.startswith("# panics"):
                cls._parse_panics(section, info)
            elif section_lower.startswith("# errors"):
                cls._parse_errors(section, info)
            elif section_lower.startswith("# safety"):
                cls._parse_safety(section, info)
            elif section_lower.startswith("# examples"):
                cls._parse_examples(section, info)
            elif section_lower.startswith("# see also"):
                cls._parse_see_also(section, info)

        return info

    @classmethod
    def _split_sections(cls, docstring: str) -> List[str]:
        """Split docstring into sections by markdown headers."""
        sections = []
        current = []
        for line in docstring.split("\n"):
            if line.startswith("# ") or line.startswith("## "):
                if current:
                    sections.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current).strip())
        # If no sections found, treat entire docstring as one section
        if not sections:
            sections = [docstring]
        return sections

    @classmethod
    def _parse_params(cls, section: str, info: RustDocstringInfo) -> None:
        """Parse parameters section."""
        for line in section.split("\n"):
            match = re.match(r'^\s*[-*]\s*`(\w+)`\s*:\s*(.*)', line)
            if match:
                info.params.append({
                    "name": match.group(1),
                    "description": match.group(2).strip(),
                })
            # Also match: `name` - description
            match2 = re.match(r'^\s*`(\w+)`\s*[-–—]\s*(.*)', line)
            if match2:
                info.params.append({
                    "name": match2.group(1),
                    "description": match2.group(2).strip(),
                })

    @classmethod
    def _parse_returns(cls, section: str, info: RustDocstringInfo) -> None:
        """Parse returns section."""
        lines = section.split("\n")
        desc_lines = [l for l in lines[1:] if l.strip() and not l.startswith("#")]
        if desc_lines:
            info.returns = {"description": " ".join(desc_lines).strip()}

    @classmethod
    def _parse_panics(cls, section: str, info: RustDocstringInfo) -> None:
        """Parse panics section."""
        for line in section.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                info.panics.append(stripped)

    @classmethod
    def _parse_errors(cls, section: str, info: RustDocstringInfo) -> None:
        """Parse errors section."""
        for line in section.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                info.errors.append(stripped)

    @classmethod
    def _parse_safety(cls, section: str, info: RustDocstringInfo) -> None:
        """Parse safety section."""
        for line in section.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                info.safety.append(stripped)

    @classmethod
    def _parse_examples(cls, section: str, info: RustDocstringInfo) -> None:
        """Parse examples section."""
        in_code = False
        current_example = []
        for line in section.split("\n"):
            if line.strip().startswith("```"):
                if in_code:
                    info.examples.append("\n".join(current_example))
                    current_example = []
                    in_code = False
                else:
                    in_code = True
            elif in_code:
                current_example.append(line)
        # If no code blocks, take lines after the header
        if not info.examples:
            lines = section.split("\n")[1:]
            code_lines = [l for l in lines if l.strip() and not l.startswith("#")]
            if code_lines:
                info.examples.append("\n".join(code_lines))

    @classmethod
    def _parse_see_also(cls, section: str, info: RustDocstringInfo) -> None:
        """Parse see also section."""
        for line in section.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                # Remove markdown link formatting
                clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', stripped)
                if clean:
                    info.see_also.append(clean)


# ---------------------------------------------------------------------------
# Rust Parser
# ---------------------------------------------------------------------------

class RustParser:
    """Parse Rust source files and extract documentation data.

    Uses regex-based analysis to extract functions, structs, enums, traits,
    impl blocks, and module-level elements.
    """

    language = "rust"

    def __init__(self):
        self.source: str = ""
        self.module_info: Optional[RustModuleInfo] = None
        self._current_comment: str = ""

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def parse_file(self, filepath: str, include_source: bool = True) -> RustParseResult:
        """Parse a Rust source file.

        Args:
            filepath: Path to .rs file
            include_source: Include source code text in output

        Returns:
            RustParseResult with extracted data
        """
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        return self.parse_string(source, filepath=filepath, include_source=include_source)

    def parse_string(self, source: str, filepath: str = "",
                     include_source: bool = True) -> RustParseResult:
        """Parse Rust source code from a string.

        Args:
            source: Rust source code
            filepath: Optional file path for context
            include_source: Include source code text in output

        Returns:
            RustParseResult with extracted data
        """
        self.source = source

        result = RustParseResult(source_file=filepath)
        result.raw_source = source if include_source else ""

        module_name = self._get_module_name(filepath)
        self.module_info = RustModuleInfo(name=module_name, filepath=filepath)
        self.module_info.source_code = source if include_source else ""

        # Remove comments to get clean source for parsing
        clean_source = self._remove_comments(source)

        # Extract outer attributes
        self._extract_attributes(source, clean_source)

        # Module docstring
        module_doc = self._extract_inner_doc_comment(source)
        if module_doc:
            self.module_info.docstring = RustdocParser.parse(module_doc)

        # Extract imports
        self._extract_imports(clean_source)

        # Extract constants
        self._extract_constants(clean_source)

        # Extract statics
        self._extract_statics(clean_source)

        # Extract structs
        self._extract_structs(source, clean_source)

        # Extract enums
        self._extract_enums(source, clean_source)

        # Extract traits
        self._extract_traits(source, clean_source)

        # Extract functions
        self._extract_functions(source, clean_source)

        # Extract impl blocks
        self._extract_impls(source, clean_source)

        # Extract type aliases
        self._extract_type_aliases(clean_source)

        # Extract macros
        self._extract_macros(source, clean_source)

        result.module = self.module_info
        return result

    def parse_project(self, root_dir: str, recursive: bool = True,
                      include_source: bool = False) -> Dict[str, RustParseResult]:
        """Parse all Rust files in a project directory.

        Args:
            root_dir: Project root directory
            recursive: Whether to recurse into subdirectories
            include_source: Include source code in output

        Returns:
            Dict mapping file paths to RustParseResult objects
        """
        results = {}
        root_dir = os.path.abspath(root_dir)

        for root, dirs, files in os.walk(root_dir):
            if not recursive and root != root_dir:
                break
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                if file.endswith(".rs"):
                    filepath = os.path.join(root, file)
                    try:
                        results[filepath] = self.parse_file(
                            filepath, include_source=include_source
                        )
                    except Exception:
                        continue

        return results

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _get_module_name(self, filepath: str) -> str:
        """Extract module name from file path."""
        if not filepath:
            return "<string>"
        name = os.path.splitext(os.path.basename(filepath))[0]
        if name == "mod":
            parent = os.path.basename(os.path.dirname(filepath))
            if parent:
                return parent
        return name

    def _remove_comments(self, source: str) -> str:
        """Remove comments from Rust source code."""
        # Remove line comments
        source = re.sub(r'//[^!].*$', '', source, flags=re.MULTILINE)
        # Remove block comments (not doc comments)
        source = re.sub(r'/\*[^*!].*?\*/', '', source, flags=re.DOTALL)
        # Remove string literals to avoid false matches
        source = re.sub(r'"(?:[^"\\]|\\.)*"', '""', source)
        # Remove raw string literals
        source = re.sub(r'r#"[^"]*"#', '""', source)
        return source

    def _extract_inner_doc_comment(self, source: str) -> Optional[str]:
        """Extract inner doc comment (//! or /*! ... */)."""
        # Line-style inner doc comments
        lines = []
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith("//!"):
                lines.append(stripped[3:])
            elif stripped.startswith("// #"):
                # Continuation
                pass
        if lines:
            return "\n".join(lines)

        # Block-style inner doc comments
        block_match = re.search(r'/\*!([^*]|\*[^/])*\*/', source, re.DOTALL)
        if block_match:
            inner = block_match.group(0)[3:-2]
            return inner.strip()

        return None

    def _extract_outer_doc_comment(self, source: str, position: int) -> Optional[str]:
        """Extract outer doc comment (/// or /** ... */) before a position."""
        before = source[:position].rstrip()
        # Line-style doc comments
        lines = []
        for line in before.split("\n")[-10:]:  # Look at last 10 lines
            stripped = line.strip()
            if stripped.startswith("///"):
                lines.append(stripped[3:])
            elif stripped == "" or stripped.startswith("//"):
                if lines:
                    break
            else:
                if lines:
                    break
        if lines:
            # Check that only whitespace/comments between doc comment and element
            lines.reverse()
            return "\n".join(lines)

        # Block-style doc comments
        block_match = re.search(r'/\*\*([^*]|\*[^/])*\*/', before, re.DOTALL)
        if block_match:
            # Check whitespace only between comment and position
            after_comment = before[block_match.end():].strip()
            if after_comment == "":
                inner = block_match.group(0)[3:-2]
                return inner.strip()

        return None

    def _extract_attributes(self, source: str, clean_source: str) -> None:
        """Extract attributes from source."""
        pattern = re.compile(r'#!?\[(.*?)\]', re.DOTALL)
        for match in pattern.finditer(source):
            attr = match.group(1).strip()
            if not attr.startswith("!"):
                self.module_info.attributes.append(attr)

    def _extract_imports(self, clean_source: str) -> None:
        """Extract use statements."""
        pattern = re.compile(
            r'use\s+((?:\w+::)*\w+(?:\s+as\s+\w+)?)\s*;', re.MULTILINE
        )
        for match in pattern.finditer(clean_source):
            import_str = match.group(1).strip()
            parts = import_str.split(" as ")
            self.module_info.imports.append({
                "path": parts[0],
                "alias": parts[1] if len(parts) > 1 else None,
            })

    def _extract_constants(self, clean_source: str) -> None:
        """Extract const declarations."""
        pattern = re.compile(
            r'(?:pub\s+)?const\s+(\w+)\s*(?::\s*([^=]+?))?\s*=\s*([^;]+);', re.MULTILINE
        )
        for match in pattern.finditer(clean_source):
            name = match.group(1)
            type_str = match.group(2).strip() if match.group(2) else ""
            value = match.group(3).strip()
            self.module_info.constants.append({
                "name": name,
                "type": type_str,
                "value": value,
            })

    def _extract_statics(self, clean_source: str) -> None:
        """Extract static declarations."""
        pattern = re.compile(
            r'(?:pub\s+)?(?:static\s+(?:mut\s+)?)(\w+)\s*(?::\s*([^=]+?))?\s*=\s*([^;]+);', re.MULTILINE
        )
        for match in pattern.finditer(clean_source):
            name = match.group(1)
            type_str = match.group(2).strip() if match.group(2) else ""
            value = match.group(3).strip()
            self.module_info.statics.append({
                "name": name,
                "type": type_str,
                "value": value,
                "is_mut": "mut" in clean_source[match.start():match.end()],
            })

    def _extract_structs(self, source: str, clean_source: str) -> None:
        """Extract struct definitions."""
        # Named struct with fields
        pattern = re.compile(
            r'(#\[derive\(([^)]+)\)\])?\s*'
            r'(?:pub\s+)?struct\s+(\w+)'
            r'(?:<([^>]+)>)?'
            r'\s*\{([^}]*)\}',
            re.DOTALL
        )
        for match in pattern.finditer(source):
            derives = match.group(2) or ""
            name = match.group(3)
            generics = match.group(4) or ""
            body = match.group(5)

            struct_info = RustStructInfo(
                name=name,
                lineno=source[:match.start()].count("\n") + 1,
            )
            struct_info.source_code = match.group(0)
            struct_info.is_pub = "pub" in match.group(0)[:match.start(3)]
            struct_info.visibility = "pub" if struct_info.is_pub else "private"
            struct_info.generics = [g.strip() for g in generics.split(",") if g.strip()]
            struct_info.derives = [d.strip() for d in derives.split(",") if d.strip()]

            # Extract fields
            for field_line in body.split(","):
                field_line = field_line.strip()
                if field_line:
                    field_match = re.match(
                        r'(?:pub\s+)?(\w+)\s*:\s*([^,]+)', field_line
                    )
                    if field_match:
                        struct_info.fields.append({
                            "name": field_match.group(1),
                            "type": field_match.group(2).strip(),
                            "visibility": "pub" if "pub" in field_line else "private",
                        })

            # Doc comment
            doc = self._extract_outer_doc_comment(source, match.start())
            if doc:
                struct_info.docstring = RustdocParser.parse(doc)

            self.module_info.structs.append(struct_info)

        # Tuple struct
        tuple_pattern = re.compile(
            r'(?:pub\s+)?struct\s+(\w+)(?:<([^>]+)>)?\s*\(([^)]*)\)\s*;',
            re.DOTALL
        )
        for match in tuple_pattern.finditer(clean_source):
            name = match.group(1)
            generics = match.group(2) or ""
            tuple_fields = match.group(3)

            struct_info = RustStructInfo(
                name=name,
                lineno=clean_source[:match.start()].count("\n") + 1,
            )
            struct_info.is_tuple_struct = True
            struct_info.generics = [g.strip() for g in generics.split(",") if g.strip()]

            fields = [f.strip() for f in tuple_fields.split(",") if f.strip()]
            for i, field_type in enumerate(fields):
                struct_info.fields.append({
                    "name": str(i),
                    "type": field_type,
                    "position": i,
                })

            self.module_info.structs.append(struct_info)

        # Unit struct
        unit_pattern = re.compile(
            r'(?:pub\s+)?struct\s+(\w+)(?:<([^>]+)>)?\s*;',
        )
        for match in unit_pattern.finditer(clean_source):
            name = match.group(1)
            generics = match.group(2) or ""

            # Skip if already matched as tuple struct
            if any(s.name == name for s in self.module_info.structs):
                continue

            struct_info = RustStructInfo(
                name=name,
                lineno=clean_source[:match.start()].count("\n") + 1,
            )
            struct_info.is_unit_struct = True
            struct_info.generics = [g.strip() for g in generics.split(",") if g.strip()]

            self.module_info.structs.append(struct_info)

    def _extract_enums(self, source: str, clean_source: str) -> None:
        """Extract enum definitions."""
        pattern = re.compile(
            r'(?:pub\s+)?enum\s+(\w+)'
            r'(?:<([^>]+)>)?'
            r'\s*\{([^}]*)\}',
            re.DOTALL
        )
        for match in pattern.finditer(source):
            name = match.group(1)
            generics = match.group(2) or ""
            body = match.group(3)

            enum_info = RustEnumInfo(
                name=name,
                lineno=source[:match.start()].count("\n") + 1,
            )
            enum_info.is_pub = "pub" in match.group(0)[:match.start(1)]
            enum_info.visibility = "pub" if enum_info.is_pub else "private"
            enum_info.generics = [g.strip() for g in generics.split(",") if g.strip()]

            # Extract variants
            for variant_line in body.split(","):
                variant_line = variant_line.strip()
                if not variant_line:
                    continue

                # Variant with data
                data_match = re.match(
                    r'(\w+)(?:\(([^)]*)\))?(?:{([^}]*?)})?\s*(?:=\s*([^,]+))?',
                    variant_line
                )
                if data_match:
                    variant_name = data_match.group(1)
                    tuple_data = data_match.group(2)
                    struct_data = data_match.group(3)
                    discriminant = data_match.group(4)

                    variant = {
                        "name": variant_name,
                        "discriminant": discriminant.strip() if discriminant else None,
                        "fields": [],
                    }

                    if tuple_data:
                        variant["fields"] = [
                            {"type": f.strip()} for f in tuple_data.split(",") if f.strip()
                        ]
                        variant["kind"] = "tuple"
                    elif struct_data:
                        struct_fields = []
                        for sf in struct_data.split(","):
                            sf = sf.strip()
                            if sf:
                                sf_match = re.match(r'(\w+)\s*:\s*([^,]+)', sf)
                                if sf_match:
                                    struct_fields.append({
                                        "name": sf_match.group(1),
                                        "type": sf_match.group(2).strip(),
                                    })
                        variant["fields"] = struct_fields
                        variant["kind"] = "struct"
                    else:
                        variant["kind"] = "unit"

                    enum_info.variants.append(variant)

            # Doc comment
            doc = self._extract_outer_doc_comment(source, match.start())
            if doc:
                enum_info.docstring = RustdocParser.parse(doc)

            self.module_info.enums.append(enum_info)

    def _extract_traits(self, source: str, clean_source: str) -> None:
        """Extract trait definitions."""
        pattern = re.compile(
            r'(?:pub\s+)?(?:unsafe\s+)?trait\s+(\w+)'
            r'(?:<([^>]+)>)??'
            r'(?:\s*:\s*([^{]+))?'
            r'\s*\{([^}]*)\}',
            re.DOTALL
        )
        for match in pattern.finditer(source):
            name = match.group(1)
            generics = match.group(2) or ""
            supertraits = match.group(3) or ""
            body = match.group(4)

            trait_info = RustTraitInfo(
                name=name,
                lineno=source[:match.start()].count("\n") + 1,
            )
            trait_info.is_pub = "pub" in match.group(0)[:match.start(1)]
            trait_info.is_unsafe = "unsafe" in match.group(0)[:match.start(1)]
            trait_info.visibility = "pub" if trait_info.is_pub else "private"
            trait_info.generics = [g.strip() for g in generics.split(",") if g.strip()]

            if supertraits:
                trait_info.supertraits = [s.strip() for s in supertraits.split("+")]

            # Extract methods and associated items from body
            self._extract_trait_body(body, trait_info)

            # Doc comment
            doc = self._extract_outer_doc_comment(source, match.start())
            if doc:
                trait_info.docstring = RustdocParser.parse(doc)

            self.module_info.traits.append(trait_info)

    def _extract_trait_body(self, body: str, trait_info: RustTraitInfo) -> None:
        """Extract methods and associated items from a trait body."""
        # Associated types
        at_pattern = re.compile(
            r'(?:pub\s+)?type\s+(\w+)(?:\s*:\s*([^;]+))?\s*;', re.MULTILINE
        )
        for match in at_pattern.finditer(body):
            trait_info.associated_types.append({
                "name": match.group(1),
                "bounds": match.group(2).strip() if match.group(2) else "",
            })

        # Associated constants
        ac_pattern = re.compile(
            r'(?:pub\s+)?const\s+(\w+)\s*:\s*([^;]+);', re.MULTILINE
        )
        for match in ac_pattern.finditer(body):
            trait_info.associated_consts.append({
                "name": match.group(1),
                "type": match.group(2).strip(),
            })

        # Method signatures
        method_pattern = re.compile(
            r'(?:fn\s+(\w+))\s*\(([^)]*)\)\s*'
            r'(?:->\s*([^{;]+))?\s*(?:;|\{)',
            re.DOTALL
        )
        for match in method_pattern.finditer(body):
            method_name = match.group(1)
            params_str = match.group(2) or ""
            return_type = match.group(3).strip() if match.group(3) else ""

            func_info = RustFunctionInfo(
                name=method_name,
                lineno=0,
            )
            func_info.return_type = return_type
            func_info.is_method = True

            # Parse parameters
            self._parse_fn_params(params_str, func_info)

            trait_info.methods.append(func_info)

    def _extract_functions(self, source: str, clean_source: str) -> None:
        """Extract free functions."""
        # Match fn definitions that are not inside impl/trait blocks
        # This is a simplified approach - find top-level functions
        pattern = re.compile(
            r'(?:(?:pub|pub\(crate\)|pub\(self\)|pub\(super\))\s+)?'
            r'(?:async\s+)?(?:unsafe\s+)?(?:extern\s+"([^"]+)"\s+)?'
            r'(?:const\s+)?fn\s+(\w+)\s*'
            r'(?:<([^>]+)>)??\s*'
            r'\(([^)]*)\)\s*'
            r'(?:->\s*([^{;]+))?\s*'
            r'(?:where\s+([^{]+))?\s*'
            r'\{',
            re.DOTALL
        )

        for match in pattern.finditer(source):
            abi = match.group(1) or ""
            name = match.group(2)
            generics = match.group(3) or ""
            params_str = match.group(4) or ""
            return_type = match.group(5).strip() if match.group(5) else ""
            where_clause = match.group(6) or ""

            # Skip if inside impl or trait block (handled separately)
            before = source[:match.start()]
            if re.search(r'(impl|trait)\s', before):
                # Check if this is a nested function or a method
                # Count braces to determine nesting
                continue

            func_info = RustFunctionInfo(
                name=name,
                lineno=source[:match.start()].count("\n") + 1,
            )
            func_info.return_type = return_type
            func_info.is_async = "async" in match.group(0)[:match.start(2)]
            func_info.is_unsafe = "unsafe" in match.group(0)[:match.start(2)]
            func_info.is_pub = "pub" in match.group(0)[:match.start(2)]
            func_info.visibility = "pub" if func_info.is_pub else "private"
            func_info.is_const = "const" in match.group(0)[:match.start(2)]
            func_info.is_abi = bool(abi)
            func_info.abi_name = abi
            func_info.generics = [g.strip() for g in generics.split(",") if g.strip()]
            if where_clause:
                func_info.where_clause = [w.strip() for w in where_clause.split(",")]

            # Parse parameters
            self._parse_fn_params(params_str, func_info)

            # Doc comment
            doc = self._extract_outer_doc_comment(source, match.start())
            if doc:
                func_info.docstring = RustdocParser.parse(doc)

            self.module_info.functions.append(func_info)

    def _extract_impls(self, source: str, clean_source: str) -> None:
        """Extract impl blocks."""
        pattern = re.compile(
            r'(?:unsafe\s+)?impl'
            r'(?:<([^>]+)>)??\s+'
            r'(\w+(?:<[^>]+>)?)'  # Type name (or trait name)
            r'(?:\s+for\s+(\w+(?:<[^>]+>)?))?\s*'  # for Type
            r'\{',
            re.DOTALL
        )

        for match in pattern.finditer(source):
            generics = match.group(1) or ""
            first_type = match.group(2).strip()
            second_type = match.group(3)

            impl_info = RustImplInfo(
                type_name=second_type or first_type,
                lineno=source[:match.start()].count("\n") + 1,
            )
            impl_info.generics = [g.strip() for g in generics.split(",") if g.strip()]
            if second_type:
                impl_info.trait_name = first_type

            # Extract methods from impl block
            # Find the closing brace and extract body
            open_pos = match.end() - 1  # position of {
            close_pos = self._find_matching_brace(source, open_pos)
            if close_pos:
                body = source[open_pos + 1:close_pos]
                self._extract_impl_methods(body, impl_info, source, match.start())

            self.module_info.impls.append(impl_info)

    def _extract_impl_methods(self, body: str, impl_info: RustImplInfo,
                              source: str, impl_start: int) -> None:
        """Extract methods from an impl block body."""
        method_pattern = re.compile(
            r'(?:(?:pub|pub\(crate\)|pub\(self\)|pub\(super\))\s+)?'
            r'(?:async\s+)?(?:unsafe\s+)?(?:extern\s+"([^"]+)"\s+)?'
            r'(?:const\s+)?fn\s+(\w+)\s*'
            r'(?:<([^>]+)>)??\s*'
            r'\(([^)]*)\)\s*'
            r'(?:->\s*([^{;]+))?\s*'
            r'(?:where\s+([^{]+))?\s*'
            r'\{',
            re.DOTALL
        )

        for match in method_pattern.finditer(body):
            name = match.group(2)
            params_str = match.group(4) or ""
            return_type = match.group(5).strip() if match.group(5) else ""

            func_info = RustFunctionInfo(
                name=name,
                lineno=impl_start + body[:match.start()].count("\n") + 1,
            )
            func_info.return_type = return_type
            func_info.is_method = True
            func_info.is_pub = "pub" in match.group(0)[:match.start(2)]
            func_info.visibility = "pub" if func_info.is_pub else "private"

            # Parse parameters
            self._parse_fn_params(params_str, func_info)

            # Doc comment - use the outer source, not body
            doc = self._extract_outer_doc_comment(body, match.start())
            if doc:
                func_info.docstring = RustdocParser.parse(doc)

            impl_info.methods.append(func_info)

    def _parse_fn_params(self, params_str: str, func_info: RustFunctionInfo) -> None:
        """Parse function parameters from a parameter string."""
        if not params_str.strip():
            return

        params = self._split_rust_params(params_str)
        for param in params:
            param = param.strip()
            if not param:
                continue

            # &self, &mut self, self
            if param in ("self", "&self", "&mut self"):
                func_info.params.append(RustParamInfo(
                    name="self",
                    is_self=True,
                    is_mut="mut" in param,
                    is_ref="&" in param,
                ))
                continue

            # pattern: name: Type
            match = re.match(r'(?:mut\s+)?(\w+)\s*:\s*(.+)', param)
            if match:
                name = match.group(1)
                type_str = match.group(2).strip()
                func_info.params.append(RustParamInfo(
                    name=name,
                    type_str=type_str,
                    is_mut="mut" in param[:match.start(2)],
                ))

    def _split_rust_params(self, params_str: str) -> List[str]:
        """Split parameter string by comma, respecting nested generics."""
        parts = []
        depth = 0
        current = []
        for char in params_str:
            if char in '<(':
                depth += 1
                current.append(char)
            elif char in '>)':
                depth -= 1
                current.append(char)
            elif char == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(char)
        if current:
            parts.append(''.join(current))
        return parts

    def _extract_type_aliases(self, clean_source: str) -> None:
        """Extract type alias definitions."""
        pattern = re.compile(
            r'(?:pub\s+)?type\s+(\w+)(?:<([^>]+)>)??\s*=\s*([^;]+);', re.MULTILINE
        )
        for match in pattern.finditer(clean_source):
            name = match.group(1)
            generics = match.group(2) or ""
            type_str = match.group(3).strip()
            self.module_info.type_aliases.append({
                "name": name,
                "type": type_str,
                "generics": [g.strip() for g in generics.split(",") if g.strip()],
            })

    def _extract_macros(self, source: str, clean_source: str) -> None:
        """Extract macro_rules! definitions."""
        pattern = re.compile(
            r'macro_rules!\s+(\w+)\s*\{([^}]*)\}',
            re.DOTALL
        )
        for match in pattern.finditer(source):
            self.module_info.macros.append({
                "name": match.group(1),
                "lineno": source[:match.start()].count("\n") + 1,
            })

    def _find_matching_brace(self, source: str, open_pos: int) -> Optional[int]:
        """Find the position of the matching closing brace."""
        depth = 1
        pos = open_pos + 1
        while pos < len(source) and depth > 0:
            if source[pos] == '{':
                depth += 1
            elif source[pos] == '}':
                depth -= 1
            pos += 1
        return pos - 1 if depth == 0 else None

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    def get_statistics(self, result: RustParseResult) -> Dict[str, Any]:
        """Get summary statistics about the parsed Rust documentation.

        Args:
            result: RustParseResult object

        Returns:
            Dict with counts and metrics
        """
        if not result.module:
            return {}

        m = result.module
        all_methods = []
        for impl_info in m.impls:
            all_methods.extend(impl_info.methods)
        for trait_info in m.traits:
            all_methods.extend(trait_info.methods)

        all_functions = m.functions + all_methods
        documented_funcs = sum(1 for f in all_functions
                               if f.docstring and f.docstring.summary)
        documented_structs = sum(1 for s in m.structs
                                 if s.docstring and s.docstring.summary)
        documented_enums = sum(1 for e in m.enums
                               if e.docstring and e.docstring.summary)

        return {
            "total_functions": len(m.functions),
            "total_methods": len(all_methods),
            "total_structs": len(m.structs),
            "total_enums": len(m.enums),
            "total_traits": len(m.traits),
            "total_impls": len(m.impls),
            "total_constants": len(m.constants),
            "total_statics": len(m.statics),
            "total_imports": len(m.imports),
            "total_macros": len(m.macros),
            "total_type_aliases": len(m.type_aliases),
            "documented_functions": documented_funcs,
            "documented_structs": documented_structs,
            "documented_enums": documented_enums,
            "doc_coverage_functions": (
                (documented_funcs / len(all_functions) * 100)
                if all_functions else 0
            ),
            "doc_coverage_structs": (
                (documented_structs / len(m.structs) * 100)
                if m.structs else 0
            ),
            "doc_coverage_enums": (
                (documented_enums / len(m.enums) * 100)
                if m.enums else 0
            ),
        }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def extract_rust_attributes(source: str) -> List[Dict[str, Any]]:
    """Extract all attributes from Rust source.

    Args:
        source: Rust source code

    Returns:
        List of attributes with name and arguments
    """
    attributes = []
    pattern = re.compile(r'#!?\[(\w+)(?:\(([^)]*)\))?\]', re.DOTALL)
    for match in pattern.finditer(source):
        attributes.append({
            "name": match.group(1),
            "args": match.group(2).strip() if match.group(2) else "",
            "lineno": source[:match.start()].count("\n") + 1,
        })
    return attributes


def extract_derive_attributes(source: str) -> List[Dict[str, List[str]]]:
    """Extract #[derive(...)] attributes.

    Args:
        source: Rust source code

    Returns:
        List of derive attributes with trait names
    """
    derives = []
    pattern = re.compile(r'#\[derive\(([^)]+)\)\]')
    for match in pattern.finditer(source):
        traits = [t.strip() for t in match.group(1).split(",")]
        derives.append({
            "traits": traits,
            "lineno": source[:match.start()].count("\n") + 1,
        })
    return derives


def generate_rust_api_summary(result: RustParseResult) -> str:
    """Generate a human-readable API summary from parsed Rust data.

    Args:
        result: RustParseResult object

    Returns:
        Formatted summary string
    """
    if not result.module:
        return "No data parsed."

    m = result.module
    lines = []
    lines.append(f"# Rust API Summary: {result.source_file}")
    lines.append("")

    if m.docstring.summary:
        lines.append(m.docstring.summary)
        lines.append("")

    if m.functions:
        lines.append(f"## Functions ({len(m.functions)})")
        for func in m.functions:
            params_str = ", ".join(
                p.name + (f": {p.type_str}" if p.type_str else "")
                for p in func.params
            )
            vis = "pub " if func.is_pub else ""
            async_str = "async " if func.is_async else ""
            unsafe_str = "unsafe " if func.is_unsafe else ""
            ret_str = f" -> {func.return_type}" if func.return_type else ""
            lines.append(f"- {vis}{unsafe_str}{async_str}`fn {func.name}({params_str}){ret_str}`")
            if func.docstring and func.docstring.summary:
                lines.append(f"  - {func.docstring.summary}")
        lines.append("")

    if m.structs:
        lines.append(f"## Structs ({len(m.structs)})")
        for s in m.structs:
            lines.append(f"- `struct {s.name}`")
            if s.docstring and s.docstring.summary:
                lines.append(f"  - {s.docstring.summary}")
            if s.fields:
                lines.append(f"  - Fields: {len(s.fields)}")
        lines.append("")

    if m.enums:
        lines.append(f"## Enums ({len(m.enums)})")
        for e in m.enums:
            lines.append(f"- `enum {e.name}`")
            if e.docstring and e.docstring.summary:
                lines.append(f"  - {e.docstring.summary}")
            if e.variants:
                lines.append(f"  - Variants: {len(e.variants)}")
        lines.append("")

    if m.traits:
        lines.append(f"## Traits ({len(m.traits)})")
        for t in m.traits:
            lines.append(f"- `trait {t.name}`")
            if t.docstring and t.docstring.summary:
                lines.append(f"  - {t.docstring.summary}")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "RustParser",
    "RustdocParser",
    "RustDocstringInfo",
    "RustFunctionInfo",
    "RustStructInfo",
    "RustEnumInfo",
    "RustTraitInfo",
    "RustImplInfo",
    "RustModuleInfo",
    "RustParseResult",
    "extract_rust_attributes",
    "extract_derive_attributes",
    "generate_rust_api_summary",
]