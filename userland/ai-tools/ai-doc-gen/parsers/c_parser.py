"""C source code parser for AI Documentation Generator.

Extracts structured documentation data from C source files using regex-based
analysis. Supports Doxygen and K&R style comments.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CDocstringInfo:
    """Parsed C docstring information (Doxygen/K&R style)."""

    def __init__(self):
        self.summary: str = ""
        self.description: str = ""
        self.params: List[Dict[str, str]] = []
        self.returns: Optional[Dict[str, str]] = None
        self.brief: str = ""
        self.see: List[str] = []
        self.warning: List[str] = []
        self.note: List[str] = []
        self.deprecated: Optional[str] = None
        self.style: str = "unknown"
        self.defines: List[Dict[str, str]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "description": self.description,
            "params": self.params,
            "returns": self.returns,
            "brief": self.brief,
            "see": self.see,
            "warning": self.warning,
            "note": self.note,
            "deprecated": self.deprecated,
            "style": self.style,
        }


class CFunctionInfo:
    """Information about a C function."""

    def __init__(self, name: str, lineno: int = 0):
        self.name = name
        self.lineno = lineno
        self.return_type: str = ""
        self.params: List[Dict[str, str]] = []
        self.docstring: CDocstringInfo = CDocstringInfo()
        self.is_static: bool = False
        self.is_inline: bool = False
        self.is_variadic: bool = False
        self.modifiers: List[str] = []
        self.source_code: str = ""
        self.qualname: str = name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "return_type": self.return_type,
            "params": self.params,
            "docstring": self.docstring.to_dict(),
            "is_static": self.is_static,
            "is_inline": self.is_inline,
            "is_variadic": self.is_variadic,
            "modifiers": self.modifiers,
        }


class CStructInfo:
    """Information about a C struct/union/enum."""

    def __init__(self, name: str, kind: str = "struct", lineno: int = 0):
        self.name = name
        self.kind = kind  # struct, union, enum
        self.lineno = lineno
        self.qualname = name
        self.fields: List[Dict[str, Any]] = []
        self.docstring: CDocstringInfo = CDocstringInfo()
        self.members: List[Dict[str, Any]] = []  # For enums
        self.source_code: str = ""
        self.typedef_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "kind": self.kind,
            "lineno": self.lineno,
            "fields": self.fields,
            "docstring": self.docstring.to_dict(),
            "members": self.members,
            "typedef_name": self.typedef_name,
        }


class CFileInfo:
    """Information about a C source/header file."""

    def __init__(self, filepath: str = ""):
        self.filepath = filepath
        self.functions: List[CFunctionInfo] = []
        self.structs: List[CStructInfo] = []
        self.unions: List[CStructInfo] = []
        self.enums: List[CStructInfo] = []
        self.typedefs: List[Dict[str, str]] = []
        self.macros: List[Dict[str, Any]] = []
        self.global_vars: List[Dict[str, Any]] = []
        self.includes: List[str] = []
        self.ifdefs: List[str] = []
        self.docstring: CDocstringInfo = CDocstringInfo()
        self.source_code: str = ""
        self.defines: List[Dict[str, Any]] = []
        self.comments: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filepath": self.filepath,
            "functions": [f.to_dict() for f in self.functions],
            "structs": [s.to_dict() for s in self.structs],
            "unions": [s.to_dict() for s in self.unions],
            "enums": [s.to_dict() for s in self.enums],
            "typedefs": self.typedefs,
            "macros": self.macros,
            "global_vars": self.global_vars,
            "includes": self.includes,
            "defines": self.defines,
        }


class CParseResult:
    """Container for parsed C documentation."""

    def __init__(self, source_file: str = ""):
        self.source_file = source_file
        self.language = "c"
        self.file_info: Optional[CFileInfo] = None
        self.raw_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file": self.source_file,
            "language": self.language,
            "file_info": self.file_info.to_dict() if self.file_info else None,
        }


# ---------------------------------------------------------------------------
# Doxygen comment parser
# ---------------------------------------------------------------------------

class DoxygenParser:
    """Parse Doxygen-style comments in C source files."""

    # Doxygen command patterns
    DOXYGEN_BRIEF = re.compile(r"@brief\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)
    DOXYGEN_PARAM = re.compile(r"@param\s+\[?(in|out|in,out|inout)?\]?\s*(\w+)\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)
    DOXYGEN_RETURN = re.compile(r"@return\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)
    DOXYGEN_RETURNS = re.compile(r"@returns\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)
    DOXYGEN_SEE = re.compile(r"@see\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)
    DOXYGEN_WARNING = re.compile(r"@warning\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)
    DOXYGEN_NOTE = re.compile(r"@note\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)
    DOXYGEN_DEPRECATED = re.compile(r"@deprecated\s+(.*?)(?=@|\n\s*\n|$)", re.DOTALL)

    @classmethod
    def parse(cls, comment: str) -> CDocstringInfo:
        """Parse a Doxygen-style comment.

        Args:
            comment: Raw Doxygen comment text (with /** and */ removed)

        Returns:
            CDocstringInfo with parsed fields
        """
        info = CDocstringInfo()
        info.style = "doxygen"
        comment = comment.strip()

        # Remove leading * from multi-line comments
        lines = []
        for line in comment.split("\n"):
            stripped = line.strip()
            if stripped.startswith("*"):
                stripped = stripped[1:].strip()
            lines.append(stripped)
        comment = "\n".join(lines).strip()

        # Extract brief
        brief_match = cls.DOXYGEN_BRIEF.search(comment)
        if brief_match:
            info.brief = brief_match.group(1).strip()
            info.summary = info.brief

        # Extract params
        for match in cls.DOXYGEN_PARAM.finditer(comment):
            direction = match.group(1) or ""
            name = match.group(2)
            desc = match.group(3).strip()
            info.params.append({
                "name": name,
                "description": desc,
                "direction": direction,
            })

        # Extract return
        ret_match = cls.DOXYGEN_RETURN.search(comment) or cls.DOXYGEN_RETURNS.search(comment)
        if ret_match:
            info.returns = {"description": ret_match.group(1).strip()}

        # Extract see also
        for match in cls.DOXYGEN_SEE.finditer(comment):
            info.see.append(match.group(1).strip())

        # Extract warnings
        for match in cls.DOXYGEN_WARNING.finditer(comment):
            info.warning.append(match.group(1).strip())

        # Extract notes
        for match in cls.DOXYGEN_NOTE.finditer(comment):
            info.note.append(match.group(1).strip())

        # Extract deprecated
        dep_match = cls.DOXYGEN_DEPRECATED.search(comment)
        if dep_match:
            info.deprecated = dep_match.group(1).strip()

        # If no brief, use first paragraph as summary
        if not info.brief:
            lines = comment.split("\n")
            first_para = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    break
                if not stripped.startswith("@"):
                    first_para.append(stripped)
            if first_para:
                info.summary = first_para[0]
                info.description = " ".join(first_para[1:])

        return info


# ---------------------------------------------------------------------------
# C Parser
# ---------------------------------------------------------------------------

class CParser:
    """Parse C source/header files and extract documentation data.

    Uses regex-based parsing to extract functions, structs, unions, enums,
    typedefs, macros, and global variables.
    """

    language = "c"

    def __init__(self):
        self.source: str = ""
        self.file_info: Optional[CFileInfo] = None
        self._current_comment: str = ""

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def parse_file(self, filepath: str, include_source: bool = True) -> CParseResult:
        """Parse a C source or header file.

        Args:
            filepath: Path to .c, .h, .cpp, or .hpp file
            include_source: Include source code text in output

        Returns:
            CParseResult with extracted data
        """
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()

        return self.parse_string(source, filepath=filepath, include_source=include_source)

    def parse_string(self, source: str, filepath: str = "",
                     include_source: bool = True) -> CParseResult:
        """Parse C source code from a string.

        Args:
            source: C source code
            filepath: Optional file path for context
            include_source: Include source code text in output

        Returns:
            CParseResult with extracted data
        """
        self.source = source

        result = CParseResult(source_file=filepath)
        result.raw_source = source if include_source else ""

        self.file_info = CFileInfo(filepath=filepath)
        self.file_info.source_code = source if include_source else ""

        # Remove string literals to avoid false matches
        clean_source = self._remove_string_literals(source)

        # Extract comments
        self._extract_all_comments(source)

        # Extract includes
        self._extract_includes(clean_source)

        # Extract defines
        self._extract_defines(clean_source)

        # Extract typedefs
        self._extract_typedefs(clean_source)

        # Extract structs
        self._extract_structs(clean_source)

        # Extract unions
        self._extract_unions(clean_source)

        # Extract enums
        self._extract_enums(clean_source)

        # Extract functions
        self._extract_functions(clean_source)

        # Extract global variables
        self._extract_global_vars(clean_source)

        result.file_info = self.file_info
        return result

    def parse_project(self, root_dir: str, recursive: bool = True,
                      include_source: bool = False) -> Dict[str, CParseResult]:
        """Parse all C files in a project directory.

        Args:
            root_dir: Project root directory
            recursive: Whether to recurse into subdirectories
            include_source: Include source code in output

        Returns:
            Dict mapping file paths to CParseResult objects
        """
        results = {}
        root_dir = os.path.abspath(root_dir)

        for root, dirs, files in os.walk(root_dir):
            if not recursive and root != root_dir:
                break
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                if file.endswith((".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh")):
                    filepath = os.path.join(root, file)
                    try:
                        results[filepath] = self.parse_file(
                            filepath, include_source=include_source
                        )
                    except Exception:
                        continue

        return results

    # -----------------------------------------------------------------------
    # Comment extraction
    # -----------------------------------------------------------------------

    def _extract_all_comments(self, source: str) -> None:
        """Extract all comments and associate them with code elements."""
        # Extract Doxygen comments
        doc_comments = self._extract_doxygen_comments(source)
        self.file_info.comments = doc_comments

    def _extract_doxygen_comments(self, source: str) -> List[Dict[str, Any]]:
        """Extract Doxygen-style comments (/** ... */)."""
        comments = []
        pattern = re.compile(r"/\*\*([^*]|\*[^/])*\*/", re.DOTALL)
        for match in pattern.finditer(source):
            comment_text = match.group(0)
            # Remove the /** and */ delimiters
            inner = comment_text[3:-2]  # Remove /** and */
            comments.append({
                "text": inner.strip(),
                "start": match.start(),
                "end": match.end(),
            })
        return comments

    def _get_comment_before(self, source: str, position: int) -> Optional[str]:
        """Get the Doxygen comment immediately before a code element."""
        before = source[:position].rstrip()
        # Look for /** ... */ before this position
        match = re.search(r"/\*\*([^*]|\*[^/])*\*/", before, re.DOTALL)
        if match:
            # Check if there's only whitespace between the comment and the element
            after_comment = before[match.end():].strip()
            if after_comment == "":
                inner = match.group(0)[3:-2]
                return inner.strip()
        return None

    # -----------------------------------------------------------------------
    # Extraction methods
    # -----------------------------------------------------------------------

    def _remove_string_literals(self, source: str) -> str:
        """Remove string literals to avoid regex false matches."""
        # Remove single-line comments first
        source = re.sub(r"//.*$", "", source, flags=re.MULTILINE)
        # Remove multi-line comments
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        # Remove string literals
        source = re.sub(r'"(?:[^"\\]|\\.)*"', '""', source)
        # Remove character literals
        source = re.sub(r"'(?:[^'\\]|\\.)'", "'c'", source)
        return source

    def _extract_includes(self, source: str) -> None:
        """Extract #include directives."""
        pattern = re.compile(
            r'#include\s+[<"]([^>"]+)[>"]', re.MULTILINE
        )
        for match in pattern.finditer(source):
            self.file_info.includes.append(match.group(1))

    def _extract_defines(self, source: str) -> None:
        """Extract #define directives."""
        pattern = re.compile(
            r'#define\s+(\w+)(?:\s+(.*?))?(?:\n|$)', re.MULTILINE
        )
        for match in pattern.finditer(source):
            name = match.group(1)
            value = (match.group(2) or "").strip()
            self.file_info.defines.append({
                "name": name,
                "value": value,
                "lineno": source[:match.start()].count("\n") + 1,
            })

    def _extract_typedefs(self, source: str) -> None:
        """Extract typedef declarations."""
        # Typedef to function pointer
        func_ptr_pattern = re.compile(
            r'typedef\s+.*?\(\s*\*\s*(\w+)\s*\)\([^)]*\)\s*;', re.DOTALL
        )
        for match in func_ptr_pattern.finditer(source):
            self.file_info.typedefs.append({
                "name": match.group(1),
                "kind": "function_pointer",
                "lineno": source[:match.start()].count("\n") + 1,
            })

        # Typedef to basic type
        basic_pattern = re.compile(
            r'typedef\s+(.*?)\s+(\w+)\s*;', re.DOTALL
        )
        for match in basic_pattern.finditer(source):
            type_str = match.group(1).strip()
            name = match.group(2).strip()
            # Skip if it looks like a struct/union/enum definition
            if type_str not in ("struct", "union", "enum"):
                self.file_info.typedefs.append({
                    "name": name,
                    "type": type_str,
                    "kind": "type_alias",
                    "lineno": source[:match.start()].count("\n") + 1,
                })

    def _extract_structs(self, source: str) -> None:
        """Extract struct definitions."""
        pattern = re.compile(
            r'struct\s+(\w+)\s*\{([^}]*)\}\s*(\w+)?\s*;', re.DOTALL
        )
        for match in pattern.finditer(source):
            name = match.group(1)
            body = match.group(2)
            typedef_name = match.group(3) or ""

            struct_info = CStructInfo(name, "struct",
                                      lineno=source[:match.start()].count("\n") + 1)
            struct_info.source_code = match.group(0)

            if typedef_name:
                struct_info.typedef_name = typedef_name.strip()

            # Extract fields
            struct_info.fields = self._extract_struct_fields(body, source, match.start())

            # Check for preceding comment
            comment = self._get_comment_before(source, match.start())
            if comment:
                struct_info.docstring = DoxygenParser.parse(comment)

            self.file_info.structs.append(struct_info)

    def _extract_unions(self, source: str) -> None:
        """Extract union definitions."""
        pattern = re.compile(
            r'union\s+(\w+)\s*\{([^}]*)\}\s*(\w+)?\s*;', re.DOTALL
        )
        for match in pattern.finditer(source):
            name = match.group(1)
            body = match.group(2)
            typedef_name = match.group(3) or ""

            union_info = CStructInfo(name, "union",
                                     lineno=source[:match.start()].count("\n") + 1)
            union_info.source_code = match.group(0)
            union_info.fields = self._extract_struct_fields(body, source, match.start())

            if typedef_name:
                union_info.typedef_name = typedef_name.strip()

            self.file_info.unions.append(union_info)

    def _extract_enums(self, source: str) -> None:
        """Extract enum definitions."""
        pattern = re.compile(
            r'enum\s+(\w+)?\s*\{([^}]*)\}\s*(\w+)?\s*;', re.DOTALL
        )
        for match in pattern.finditer(source):
            name = match.group(1) or "anonymous"
            body = match.group(2)
            typedef_name = match.group(3) or ""

            enum_info = CStructInfo(name, "enum",
                                    lineno=source[:match.start()].count("\n") + 1)
            enum_info.source_code = match.group(0)

            # Extract enum members
            for member in body.split(","):
                member = member.strip()
                if member:
                    member_parts = member.split("=", 1)
                    member_name = member_parts[0].strip()
                    member_value = member_parts[1].strip() if len(member_parts) > 1 else None
                    enum_info.members.append({
                        "name": member_name,
                        "value": member_value,
                    })

            if typedef_name:
                enum_info.typedef_name = typedef_name.strip()

            self.file_info.enums.append(enum_info)

    def _extract_struct_fields(self, body: str, source: str, offset: int) -> List[Dict[str, Any]]:
        """Extract fields from a struct/union body."""
        fields = []
        for line in body.split(";"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Handle bitfields
            bitfield_pattern = re.compile(
                r'(\w+(?:\s+\w+)*)\s+(\w+)\s*:\s*(\d+)'
            )
            bf_match = bitfield_pattern.search(line)
            if bf_match:
                fields.append({
                    "type": bf_match.group(1).strip(),
                    "name": bf_match.group(2).strip(),
                    "bits": int(bf_match.group(3)),
                    "kind": "bitfield",
                })
                continue

            # Regular field
            # Split on first space or * to get type and name
            field_pattern = re.compile(
                r'((?:(?:const|unsigned|signed|volatile|static|extern|register)\s+)*'
                r'(?:\w+(?:\s*\*+\s*|\s+))*)'
                r'(\w+)\s*$'
            )
            f_match = field_pattern.search(line)
            if f_match:
                field_type = f_match.group(1).strip()
                field_name = f_match.group(2).strip()

                # Count pointer indirection
                ptr_count = field_type.count("*")
                field_type_clean = field_type.replace("*", "").strip()

                fields.append({
                    "type": field_type_clean,
                    "name": field_name,
                    "pointer_depth": ptr_count,
                    "kind": "field",
                })

        return fields

    def _extract_functions(self, source: str) -> None:
        """Extract function declarations and definitions."""
        # Function pattern: return_type function_name(params) { ... }
        # or: return_type function_name(params);
        # This is a simplified pattern that handles common cases

        # Remove preprocessor directives to avoid false matches
        source_no_preproc = re.sub(r'#.*$', '', source, flags=re.MULTILINE)

        # Match function definitions and declarations
        func_pattern = re.compile(
            r'(?:(?:static|inline|extern|virtual|constexpr|volatile)\s+)*'
            r'((?:\w+\s*[*\s]+)+)'  # Return type (greedy)
            r'(\w+)\s*'  # Function name
            r'\(([^)]*)\)\s*'  # Parameters
            r'(?:\{|;)',  # Start of body or declaration
            re.MULTILINE
        )

        for match in func_pattern.finditer(source_no_preproc):
            raw_return = match.group(1).strip()
            name = match.group(2)
            params_str = match.group(3).strip()

            # Skip if it looks like a control flow keyword
            if name in ("if", "while", "for", "switch", "catch", "return", "sizeof"):
                continue

            # Skip if the "return type" contains non-type keywords
            skip_keywords = {"if", "while", "for", "switch", "catch", "sizeof", "else", "do"}
            first_word = raw_return.split()[0] if raw_return.split() else ""
            if first_word in skip_keywords:
                continue

            func_info = CFunctionInfo(
                name=name,
                lineno=source[:match.start()].count("\n") + 1,
            )
            func_info.return_type = raw_return
            func_info.source_code = match.group(0)

            # Check for modifiers
            if "static" in raw_return:
                func_info.is_static = True
            if "inline" in raw_return:
                func_info.is_inline = True

            # Parse parameters
            if params_str and params_str != "void":
                func_info.params = self._extract_params(params_str)

            # Check for variadic
            if "..." in params_str:
                func_info.is_variadic = True

            # Check for preceding comment
            comment = self._get_comment_before(source, match.start())
            if comment:
                func_info.docstring = DoxygenParser.parse(comment)

            self.file_info.functions.append(func_info)

    def _extract_params(self, params_str: str) -> List[Dict[str, str]]:
        """Extract parameter information from a function parameter string."""
        params = []
        # Split by comma, respecting nested parentheses
        parts = self._split_params(params_str)
        for part in parts:
            part = part.strip()
            if not part or part == "void":
                continue

            # Handle function pointer parameters
            func_ptr = re.match(r'(\w+(?:\s+\w+)*)\s*\(\s*\*\s*(\w+)\s*\)\(', part)
            if func_ptr:
                params.append({
                    "type": func_ptr.group(1).strip() + " (*)()",
                    "name": func_ptr.group(2).strip(),
                })
                continue

            # Handle array parameters
            array_match = re.match(
                r'((?:\w+\s+)*\w+)\s+(\w+)\s*\[\s*\]', part
            )
            if array_match:
                params.append({
                    "type": array_match.group(1).strip() + "[]",
                    "name": array_match.group(2).strip(),
                })
                continue

            # Regular parameter: type name
            # Split on last whitespace to separate type from name
            tokens = part.split()
            if len(tokens) >= 2:
                # Handle const/volatile qualifiers
                type_tokens = []
                name_token = None
                for i, token in enumerate(tokens):
                    if token in ("const", "volatile", "unsigned", "signed",
                                  "long", "short", "struct", "union", "enum"):
                        type_tokens.append(token)
                    elif token == "*":
                        type_tokens.append("*")
                    elif token.startswith("*"):
                        type_tokens.append("*")
                        if token[1:]:
                            name_token = token[1:]
                    else:
                        if i == len(tokens) - 1:
                            name_token = token
                        else:
                            type_tokens.append(token)

                if name_token:
                    params.append({
                        "type": " ".join(type_tokens).strip(),
                        "name": name_token.strip(),
                    })
                else:
                    params.append({
                        "type": part,
                        "name": "",
                    })
            elif len(tokens) == 1:
                params.append({
                    "type": part,
                    "name": "",
                })

        return params

    def _split_params(self, params_str: str) -> List[str]:
        """Split parameter string by comma, respecting nested parens."""
        parts = []
        depth = 0
        current = []
        for char in params_str:
            if char == '(':
                depth += 1
                current.append(char)
            elif char == ')':
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

    def _extract_global_vars(self, source: str) -> None:
        """Extract global variable declarations."""
        # Match global variable declarations (not inside functions)
        # Pattern: type name [= value];
        var_pattern = re.compile(
            r'(?:(?:extern|static|const|volatile|unsigned|signed)\s+)*'
            r'(\w+(?:\s+\w+)*)\s+'  # Type
            r'(\w+)\s*'  # Name
            r'(?:=\s*([^;]+))?\s*;',  # Optional initializer
            re.MULTILINE
        )

        for match in var_pattern.finditer(source):
            type_str = match.group(1).strip()
            name = match.group(2).strip()
            initializer = match.group(3)

            # Skip if it looks like a function declaration
            if type_str in ("if", "while", "for", "switch", "return", "sizeof", "else"):
                continue

            self.file_info.global_vars.append({
                "type": type_str,
                "name": name,
                "initializer": initializer.strip() if initializer else None,
                "lineno": source[:match.start()].count("\n") + 1,
            })

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    def get_statistics(self, result: CParseResult) -> Dict[str, Any]:
        """Get summary statistics about the parsed C documentation.

        Args:
            result: CParseResult object

        Returns:
            Dict with counts and metrics
        """
        if not result.file_info:
            return {}

        fi = result.file_info
        documented_funcs = sum(1 for f in fi.functions
                               if f.docstring and f.docstring.summary)
        documented_structs = sum(1 for s in fi.structs
                                 if s.docstring and s.docstring.summary)

        return {
            "total_functions": len(fi.functions),
            "total_structs": len(fi.structs),
            "total_unions": len(fi.unions),
            "total_enums": len(fi.enums),
            "total_typedefs": len(fi.typedefs),
            "total_macros": len(fi.defines),
            "total_includes": len(fi.includes),
            "total_global_vars": len(fi.global_vars),
            "documented_functions": documented_funcs,
            "documented_structs": documented_structs,
            "doc_coverage_functions": (
                (documented_funcs / len(fi.functions) * 100)
                if fi.functions else 0
            ),
            "doc_coverage_structs": (
                (documented_structs / len(fi.structs) * 100)
                if fi.structs else 0
            ),
        }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def extract_preprocessor_ifs(source: str) -> List[Dict[str, Any]]:
    """Extract #if/#ifdef/#ifndef/#else/#endif directives.

    Args:
        source: C source code

    Returns:
        List of conditional compilation directives
    """
    conditionals = []
    pattern = re.compile(
        r'#\s*(if|ifdef|ifndef|else|elif|endif)\b(.*?)$',
        re.MULTILINE
    )
    for match in pattern.finditer(source):
        conditionals.append({
            "directive": match.group(1),
            "condition": match.group(2).strip(),
            "lineno": source[:match.start()].count("\n") + 1,
        })
    return conditionals


def extract_pragma_once(source: str) -> bool:
    """Check if a header file has #pragma once.

    Args:
        source: C source code

    Returns:
        True if #pragma once is present
    """
    return bool(re.search(r'#\s*pragma\s+once', source))


def extract_include_guard(source: str) -> Optional[str]:
    """Extract the include guard macro name.

    Args:
        source: C source code

    Returns:
        The include guard macro name, or None
    """
    # Check for #ifndef/#define pattern at the start
    match = re.search(
        r'#\s*ifndef\s+(\w+)\s*\n\s*#\s*define\s+\1\b',
        source, re.MULTILINE
    )
    if match:
        return match.group(1)
    return None


def generate_c_api_summary(result: CParseResult) -> str:
    """Generate a human-readable API summary from parsed C data.

    Args:
        result: CParseResult object

    Returns:
        Formatted summary string
    """
    if not result.file_info:
        return "No data parsed."

    fi = result.file_info
    lines = []
    lines.append(f"# C API Summary: {result.source_file}")
    lines.append("")

    if fi.functions:
        lines.append(f"## Functions ({len(fi.functions)})")
        for func in fi.functions:
            params_str = ", ".join(
                f"{p.get('type', '')} {p.get('name', '')}"
                for p in func.params
            )
            static_str = "static " if func.is_static else ""
            inline_str = "inline " if func.is_inline else ""
            lines.append(
                f"- {static_str}{inline_str}`{func.return_type} {func.name}({params_str})`"
            )
            if func.docstring and func.docstring.summary:
                lines.append(f"  - {func.docstring.summary}")
        lines.append("")

    if fi.structs:
        lines.append(f"## Structs ({len(fi.structs)})")
        for s in fi.structs:
            lines.append(f"- `struct {s.name}`")
            if s.docstring and s.docstring.summary:
                lines.append(f"  - {s.docstring.summary}")
            if s.fields:
                lines.append(f"  - Fields: {len(s.fields)}")
        lines.append("")

    if fi.enums:
        lines.append(f"## Enums ({len(fi.enums)})")
        for e in fi.enums:
            lines.append(f"- `enum {e.name}`")
            if e.members:
                lines.append(f"  - Values: {len(e.members)}")
        lines.append("")

    if fi.defines:
        lines.append(f"## Macros ({len(fi.defines)})")
        for d in fi.defines[:10]:
            lines.append(f"- `{d['name']}` = `{d['value']}`")
        if len(fi.defines) > 10:
            lines.append(f"- ... and {len(fi.defines) - 10} more")
        lines.append("")

    if fi.includes:
        lines.append(f"## Includes ({len(fi.includes)})")
        for inc in fi.includes[:15]:
            lines.append(f"- `{inc}`")
        if len(fi.includes) > 15:
            lines.append(f"- ... and {len(fi.includes) - 15} more")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "CParser",
    "DoxygenParser",
    "CDocstringInfo",
    "CFunctionInfo",
    "CStructInfo",
    "CFileInfo",
    "CParseResult",
    "extract_preprocessor_ifs",
    "extract_pragma_once",
    "extract_include_guard",
    "generate_c_api_summary",
]